#!/usr/bin/env python3
"""ais_detect.py: behaviour and spoofing detectors (maritime plan D3-D7) on AIS collected by collectors/digitraffic_ais.py.

Input: data/ais/digitraffic/<day>/locations*.parquet and metadata*.parquet (Digitraffic AIS, CC BY 4.0).
Output (root data/ is gitignored; AIS-derived records stay private until reviewed, maritime plan Section 11):
  data/ais/digitraffic/events/events_<first>_<last>.jsonl   one event per line (rule, time span, place, MMSIs, numbers)
  data/ais/digitraffic/events/summary_<first>_<last>.json   counts, region tables, GNSS-signature tables
and a plain-text summary on stdout.

Detectors (rule version RULES_VERSION; thresholds are starting points from docs/maritime-plan.md Section 5):
  D7 spoofed track   impossible implied speed between positions (per vessel class), split into single-report spikes,
                     excursions that return, and jumps without return; positions on land (Natural Earth 10m land minus
                     lakes, more than LAND_DEPTH_KM inland, outside cells many vessels use); several vessels at one
                     point; vessels circling a shared centre
  D5 going dark      reporting gaps over --gap-h hours that start and end where other vessels kept being received
  D3 rendezvous      two vessels within 500 m, both under 2 kn, for over --rdv-h hours
  D4 loitering       one vessel under 2 kn for over --loiter-h hours outside ports and anchorages
  D6 identity        name, call sign, IMO or type changes on one MMSI; one IMO on several MMSIs; invalid IMO check
                     digits; destination text that is not a port or LOCODE
  GNSS signatures    posAcc and RAIM shares by region, flag changes on a vessel, positions not available (91/181),
                     positions frozen while under way, course over ground far from heading, reported speed far from
                     track speed; compared with the aircraft GNSS map (data/pnt/year/<day>.parquet, H3 res 4)

--preset plan uses the plan's durations (gap 6 h, rendezvous 2 h, loitering 6 h). --preset sample scales them down
for a short development sample (0.5 h, 0.33 h, 1 h). Results are indicators for a person to review, never verdicts.

Usage
  python tools/ais_detect.py                          # every collected day, preset chosen by sample length
  python tools/ais_detect.py --days 2026-10-24 --preset plan
"""
import argparse
import glob
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AIS_DIR = os.path.join(ROOT, "data", "ais", "digitraffic")
PNT_YEAR = os.path.join(ROOT, "data", "pnt", "year")
NE_DIR = os.path.join(ROOT, "data", "natural_earth")          # same cache as tools/export_site_data.py
NE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/{}.geojson"
CACHE = os.path.join(ROOT, "data", "cache")
RULES_VERSION = "ais-0.1 (2026-10-24)"
SOURCE = "digitraffic-ais: Fintraffic / digitraffic.fi, license CC 4.0 BY"
KN = 1.852                    # km per nautical mile
SOG_NA = 102.25               # AIS SOG 102.3 = not available (102.2 = 102.2 kn or more); float32 storage
LAND_DEPTH_KM = 3.0           # a position must be this far inside land to count as on land (NE 10m is coarse in
                              # the archipelagos: harbours sit 1-3 km "inland" in it)
CLIP = (8.0, 52.0, 36.0, 68.0)  # lon0, lat0, lon1, lat1 for the land mask (Baltic and approaches)

PRESETS = {"plan": {"gap_h": 6.0, "rdv_h": 2.0, "loiter_h": 6.0},
           "sample": {"gap_h": 0.5, "rdv_h": 1 / 3, "loiter_h": 1.0}}

# Named sea areas for the region tables: generic geography, not watch areas. (lat0, lat1, lon0, lon1); first match wins.
REGIONS = [
    ("Narva Bay (Estonia-Russia border)", (59.30, 59.80, 27.30, 28.30)),
    ("Gulf of Finland east of 27E", (59.30, 60.80, 27.00, 30.60)),
    ("Gulf of Finland 22.5-27E", (59.10, 60.50, 22.50, 27.00)),
    ("Archipelago Sea and Aland", (59.60, 60.80, 19.00, 22.50)),
    ("Bothnian Sea", (60.80, 63.50, 16.50, 23.20)),
    ("Bothnian Bay and Kvarken", (63.50, 66.00, 19.00, 25.80)),
    ("Northern Baltic Proper", (56.50, 59.60, 16.00, 23.50)),
    ("Gulf of Riga", (56.50, 59.10, 23.50, 25.00)),
    ("Finnish and Russian lakes, inland", (60.50, 65.00, 23.20, 33.50)),
    ("Kaliningrad and approaches", (54.00, 55.60, 19.00, 23.00)),
]


# ----------------------------------------------------------------------------------------------- basics
def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(a, dtype=float)) for a in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(np.minimum(a, 1.0)))


def iso(t):
    return datetime.fromtimestamp(float(t), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def region_of(lat, lon):
    for name, (a, b, c, d) in REGIONS:
        if a <= lat <= b and c <= lon <= d:
            return name
    return "Other"


def regions_of(lat, lon):
    out = np.full(len(lat), "Other", dtype=object)
    done = np.zeros(len(lat), bool)
    for name, (a, b, c, d) in REGIONS:
        m = ~done & (lat >= a) & (lat <= b) & (lon >= c) & (lon <= d)
        out[m] = name
        done |= m
    return out


def mmsi_kind(m):
    """ITU-R M.585 numbering: what kind of station an MMSI belongs to."""
    m = int(m)
    s = f"{m:09d}"
    if m <= 0 or m > 999_999_999:
        return "invalid"
    if s.startswith("111"):
        return "sar_aircraft"
    if s.startswith("970") or s.startswith("972") or s.startswith("974"):
        return "sart_mob_epirb"
    if s.startswith("99"):
        return "aton"
    if s.startswith("98"):
        return "craft_of_parent_ship"
    if s.startswith("00"):
        return "coast_station"
    if s[0] == "0":
        return "group"
    if s[0] == "8":
        return "handheld"
    if s[0] in "234567":
        mid = int(s[:3])
        return "ship" if 201 <= mid <= 775 else "ship_unallocated_mid"
    return "other"


def vessel_class(t):
    """(class, typical maximum speed in knots) from the AIS ship-type code (ITU-R M.1371 table 53)."""
    if t is None or t <= 0:
        return "unknown", 45.0
    if 20 <= t <= 29:
        return "wing-in-ground", 60.0
    fixed = {30: ("fishing", 16), 31: ("towing", 16), 32: ("towing", 16), 33: ("dredging", 15), 34: ("diving", 20),
             35: ("military", 35), 36: ("sailing", 20), 37: ("pleasure", 45), 50: ("pilot", 30), 51: ("sar", 45),
             52: ("tug", 16), 53: ("port tender", 25), 54: ("anti-pollution", 20), 55: ("law enforcement", 40),
             58: ("medical", 30), 59: ("non-combatant", 30)}
    if t in fixed:
        return fixed[t][0], float(fixed[t][1])
    if 40 <= t <= 49:
        return "high-speed craft", 50.0
    if 60 <= t <= 69:
        return "passenger", 32.0
    if 70 <= t <= 79:
        return "cargo", 25.0
    if 80 <= t <= 89:
        return "tanker", 20.0
    if 90 <= t <= 99:
        return "other", 35.0
    return "unknown", 45.0


def speed_limit_kn(t):
    """Implied-speed threshold: 1.5 x the class maximum, and at least 10 kn above it."""
    v = vessel_class(t)[1]
    return max(1.5 * v, v + 10.0)


def is_private_small(t):
    """Sailing and pleasure craft: counted, never named (maritime plan Section 12)."""
    return t in (36, 37)


def is_commercial(t, imo):
    return t is not None and (60 <= t <= 89 or 30 <= t <= 35 or 40 <= t <= 59 or 90 <= t <= 99) and not is_private_small(t)


def imo_valid(imo):
    """IMO number check digit: digits 1-6 weighted 7..2, sum mod 10 equals digit 7."""
    if imo is None or not (1_000_000 <= int(imo) <= 9_999_999):
        return False
    s = str(int(imo))
    return sum(int(s[i]) * (7 - i) for i in range(6)) % 10 == int(s[6])


# ----------------------------------------------------------------------------------------------- loading
def days_available():
    return sorted(os.path.basename(d) for d in glob.glob(os.path.join(AIS_DIR, "????-??-??")))


def read_kind(days, kind):
    tables = []
    for day in days:
        for p in sorted(glob.glob(os.path.join(AIS_DIR, day, f"{kind}*.parquet"))):
            try:
                tables.append(pq.read_table(p))
            except Exception as e:
                print(f"skip {p}: {e}", file=sys.stderr)
    if not tables:
        return None
    return pa.concat_tables(tables, promote_options="default")


def load_locations(days, since=None, until=None):
    """Positions as numpy arrays sorted by (mmsi, time), exact duplicates removed. Positions 'not available'
    (lat 91 / lon 181) and out-of-range values are split off and counted. since/until (epoch seconds) keep
    [since, until), so one collection run can be read apart from another in the same UTC day folder."""
    t = read_kind(days, "locations")
    if t is None:
        raise SystemExit("no location files found")
    d = {k: t.column(k).to_numpy(zero_copy_only=False) for k in
         ("mmsi", "time", "lat", "lon", "sog", "cog", "heading", "navStat", "posAcc", "raim", "rx_ms")}
    d["time"] = np.where(d["time"] > 0, d["time"], d["rx_ms"] // 1000).astype(np.int64)
    if since is not None or until is not None:
        keep = (d["time"] >= (since if since is not None else -2**62)) & (d["time"] < (until if until is not None else 2**62))
        d = {k: v[keep] for k, v in d.items()}
    for k in ("lat", "lon", "sog", "cog"):
        d[k] = np.asarray(d[k], dtype=float)
    d["heading"] = np.nan_to_num(np.asarray(d["heading"], dtype=float), nan=511).astype(np.int16)
    d["navStat"] = np.nan_to_num(np.asarray(d["navStat"], dtype=float), nan=15).astype(np.int8)
    for k in ("posAcc", "raim"):
        d[k] = np.asarray([bool(x) if x is not None else False for x in d[k]]) if d[k].dtype == object else d[k].astype(bool)
    n_raw = len(d["mmsi"])
    order = np.lexsort((d["lon"], d["lat"], d["time"], d["mmsi"]))
    d = {k: v[order] for k, v in d.items()}
    same = np.zeros(n_raw, bool)
    same[1:] = ((d["mmsi"][1:] == d["mmsi"][:-1]) & (d["time"][1:] == d["time"][:-1]) &
                (d["lat"][1:] == d["lat"][:-1]) & (d["lon"][1:] == d["lon"][:-1]))
    d = {k: v[~same] for k, v in d.items()}
    na = (d["lat"] > 90) | (d["lat"] < -90) | (d["lon"] > 180) | (d["lon"] < -180) | np.isnan(d["lat"]) | np.isnan(d["lon"])
    zero = (d["lat"] == 0) & (d["lon"] == 0)
    bad = na | zero
    unavailable = {k: v[bad] for k, v in d.items()}
    d = {k: v[~bad] for k, v in d.items()}
    return d, {"raw_rows": int(n_raw), "duplicates": int(same.sum()), "not_available": int(na.sum()),
               "zero_zero": int(zero.sum()), "rows": int(len(d["mmsi"]))}, unavailable


def norm_text(s):
    return " ".join(str(s).replace("@", " ").split()).upper() if s is not None else ""


def load_metadata(days):
    """Per MMSI: latest static fields and every distinct identity value seen, with first and last receive times."""
    t = read_kind(days, "metadata")
    vessels = {}
    if t is None:
        return vessels
    rows = t.sort_by([("mmsi", "ascending"), ("rx_ms", "ascending")]).to_pylist()
    for r in rows:
        m = r["mmsi"]
        v = vessels.setdefault(m, {"mmsi": m, "hist": defaultdict(dict), "n": 0})
        v["n"] += 1
        for k in ("name", "callSign", "imo", "type", "destination", "draught"):
            val = r.get(k)
            if k in ("name", "callSign", "destination"):
                val = norm_text(val)
                if not val:
                    continue
            elif val is None or (k == "imo" and val == 0) or (k == "type" and val == 0):
                continue
            h = v["hist"][k].setdefault(val, [r["rx_ms"], r["rx_ms"], 0, set()])
            h[0] = min(h[0], r["rx_ms"]); h[1] = max(h[1], r["rx_ms"]); h[2] += 1; h[3].add(r["src"])
            v[k] = val                     # latest wins (rows are in receive order)
        if r.get("refA") is not None and r.get("refB") is not None and (r["refA"] or r["refB"]):
            v["length"] = (r["refA"] or 0) + (r["refB"] or 0)
    return vessels


def vessel_type(meta, m):
    v = meta.get(int(m))
    return v.get("type") if v else None


def label(meta, m):
    """A short public-safe label: name and IMO for commercial vessels, a class only for small private craft."""
    v = meta.get(int(m), {})
    t = v.get("type")
    cls = vessel_class(t)[0]
    if is_private_small(t) or not v.get("imo"):
        return f"{cls} (no IMO)" if not is_private_small(t) else cls
    return f"{v.get('name', '?')} (IMO {v.get('imo')}, {cls})"


# ----------------------------------------------------------------------------------------------- geography
def natural_earth(name):
    path = os.path.join(NE_DIR, f"{name}.geojson")
    if not os.path.exists(path):
        import urllib.request
        os.makedirs(NE_DIR, exist_ok=True)
        with urllib.request.urlopen(NE_URL.format(name), timeout=180) as r:
            open(path, "wb").write(r.read())
    return json.load(open(path, encoding="utf-8"))


_TF = None


def to_xy(lon, lat):
    """WGS84 -> ETRS-TM35FIN (EPSG:3067) metres, good across the Finnish AIS coverage."""
    global _TF
    if _TF is None:
        from pyproj import Transformer
        _TF = Transformer.from_crs(4326, 3067, always_xy=True)
    return _TF.transform(np.asarray(lon, dtype=float), np.asarray(lat, dtype=float))


class LandMask:
    """Natural Earth 10m land minus 10m lakes (global and European sets), clipped to CLIP and projected to EPSG:3067.
    Natural Earth is public domain. Cached as WKB in data/cache/."""

    def __init__(self):
        import shapely
        self.shapely = shapely
        cache = os.path.join(CACHE, "ais_land_3067_v1.wkb")
        if os.path.exists(cache):
            self.geom = shapely.from_wkb(open(cache, "rb").read())
        else:
            from shapely.geometry import box, shape
            clip = box(*CLIP)
            land = []
            for f in natural_earth("ne_10m_land")["features"]:
                g = shape(f["geometry"])
                if g.intersects(clip):
                    land.append(shapely.make_valid(g).intersection(clip))
            lakes = []
            for name in ("ne_10m_lakes", "ne_10m_lakes_europe"):
                for f in natural_earth(name)["features"]:
                    g = shape(f["geometry"])
                    if g.intersects(clip):
                        lakes.append(shapely.make_valid(g).intersection(clip))
            geom = shapely.union_all(land)
            if lakes:
                geom = geom.difference(shapely.union_all(lakes))
            geom = shapely.transform(geom, lambda c: np.column_stack(to_xy(c[:, 0], c[:, 1])))
            os.makedirs(CACHE, exist_ok=True)
            open(cache, "wb").write(shapely.to_wkb(geom))
            self.geom = geom
        shapely.prepare(self.geom)
        self.boundary = self.geom.boundary
        shapely.prepare(self.boundary)

    def depth_km(self, lon, lat):
        """Distance inside land in km for each point (0 for points at sea)."""
        x, y = to_xy(lon, lat)
        inside = self.shapely.contains_xy(self.geom, x, y)
        out = np.zeros(len(x))
        if inside.any():
            pts = self.shapely.points(x[inside], y[inside])
            out[inside] = self.shapely.distance(self.boundary, pts) / 1000.0
        return out

    def shore_km(self, lon, lat):
        """Distance to the Natural Earth 10m coastline in km (positive at sea and on land alike)."""
        x, y = to_xy(np.atleast_1d(lon), np.atleast_1d(lat))
        return self.shapely.distance(self.boundary, self.shapely.points(x, y)) / 1000.0


def ports():
    """Natural Earth 10m ports (public domain) as (lat, lon) arrays."""
    try:
        fs = natural_earth("ne_10m_ports")["features"]
    except Exception:
        return np.zeros(0), np.zeros(0)
    pts = [(f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0]) for f in fs]
    a = np.array(pts)
    return a[:, 0], a[:, 1]


def pos_key(lat, lon, decimals):
    """Exact int64 key for a position rounded to `decimals` (no float collisions)."""
    f = 10 ** decimals
    return np.round(np.asarray(lat) * f).astype(np.int64) * (400 * f) + np.round((np.asarray(lon) + 180) * f).astype(np.int64)


def h3_cells(lat, lon, res):
    import h3
    uniq, inv = np.unique(np.column_stack([np.round(lat, 5), np.round(lon, 5)]), axis=0, return_inverse=True)
    cells = np.array([h3.latlng_to_cell(a, b, res) for a, b in uniq], dtype=object)
    return cells[inv.ravel()]


# ----------------------------------------------------------------------------------------------- D7 speed jumps
def vessel_slices(mmsi):
    """(mmsi, start, end) for each vessel in an mmsi-sorted array."""
    if len(mmsi) == 0:
        return []
    cut = np.flatnonzero(np.diff(mmsi)) + 1
    starts = np.concatenate([[0], cut])
    ends = np.concatenate([cut, [len(mmsi)]])
    return [(int(mmsi[s]), int(s), int(e)) for s, e in zip(starts, ends)]


def walk_track(t, lat, lon, limit_kn, min_km=1.0, max_excursion=8, max_excursion_s=3600):
    """Split one vessel's track into accepted positions and excursions.

    Keeps an anchor (last accepted position). A position that needs more than limit_kn from the anchor (and is more
    than min_km away) starts an excursion. The excursion ends when a later position is again reachable from the anchor
    (a return), or becomes a relocation when it lasts more than max_excursion reports or max_excursion_s seconds
    (the track then continues from the excursion). Returns (suspect mask, list of excursions) where each excursion is
    dict(i0=first bad index, i1=last bad index, anchor=index, ret=index or None, kind=spike|excursion|jump)."""
    n = len(t)
    suspect = np.zeros(n, bool)
    exc = []
    if n < 2:
        return suspect, exc
    anchor = 0
    buf = []
    for i in range(1, n):
        dt = max(float(t[i] - t[anchor]), 1.0)
        d = float(haversine_km(lat[anchor], lon[anchor], lat[i], lon[i]))
        ok = d <= min_km or d / dt * 3600 / KN <= limit_kn
        if not buf:
            if ok:
                anchor = i
            else:
                buf = [i]
            continue
        if ok:            # back on the anchor's track: the buffered positions were an excursion that returned
            exc.append({"i0": buf[0], "i1": buf[-1], "anchor": anchor, "ret": i,
                        "kind": "spike" if len(buf) == 1 else "excursion"})
            suspect[buf] = True
            buf = []
            anchor = i
            continue
        buf.append(i)
        if len(buf) > max_excursion or t[i] - t[buf[0]] > max_excursion_s:
            # did the excursion hold together (consistent among itself)? then the vessel (or its reported position)
            # really moved: one jump without return; the track continues from here
            exc.append({"i0": buf[0], "i1": buf[-1], "anchor": anchor, "ret": None, "kind": "jump"})
            anchor = buf[-1]
            buf = []
    if buf:  # track ended during an excursion
        exc.append({"i0": buf[0], "i1": buf[-1], "anchor": anchor, "ret": None, "kind": "open"})
        suspect[buf] = True
    return suspect, exc


def merge_episodes(events, gap_s=1800):
    """Merge one vessel's D7-speed excursions that follow each other within gap_s into one episode. The first
    excursion's anchor is the last trusted position before the episode (where the vessel probably really was)."""
    out = []
    by_v = defaultdict(list)
    for e in events:
        by_v[e["mmsi"][0]].append(e)
    for m, evs in by_v.items():
        evs.sort(key=lambda e: e["t0"])
        cur = None
        for e in evs:
            t0 = datetime.fromisoformat(e["t0"].replace("Z", "+00:00")).timestamp()
            if cur and t0 - cur["_t1"] <= gap_s:
                cur["t1"] = e["t1"]
                cur["_t1"] = datetime.fromisoformat(e["t1"].replace("Z", "+00:00")).timestamp()
                n = cur["numbers"]
                n["excursions"] += 1
                n["kinds"][e["kind"]] = n["kinds"].get(e["kind"], 0) + 1
                n["max_jump_km"] = max(n["max_jump_km"], e["numbers"]["jump_km"])
                n["max_implied_kn"] = max(n["max_implied_kn"], e["numbers"]["implied_kn"])
                n["reports_away"] += e["numbers"]["reports_away"]
                cur["_pts"].append((e["lat"], e["lon"]))
                continue
            if cur:
                out.append(cur)
            cur = dict(e)
            cur["_t1"] = datetime.fromisoformat(e["t1"].replace("Z", "+00:00")).timestamp()
            cur["numbers"] = {"excursions": 1, "kinds": {e["kind"]: 1}, "max_jump_km": e["numbers"]["jump_km"],
                              "max_implied_kn": e["numbers"]["implied_kn"], "limit_kn": e["numbers"]["limit_kn"],
                              "reports_away": e["numbers"]["reports_away"], "first_jump_km": e["numbers"]["jump_km"]}
            cur["_pts"] = [(e["lat"], e["lon"])]
        if cur:
            out.append(cur)
    for e in out:
        pts = np.array(e.pop("_pts"))
        e.pop("_t1")
        e["numbers"]["spread_km"] = round(float(haversine_km(pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max())), 2)
        k = e["numbers"]["kinds"]
        e["kind"] = ("single spike" if k == {"spike": 1} else "spikes" if set(k) == {"spike"} else "displacement")
    return out


def d7_reported_speed(L, meta):
    """Reported SOG above the class threshold, up to 102.2 kn ('102.2 kn or more'; 102.3 means not available). AIS SOG comes from the
    GNSS receiver, so a spoofed receiver can report it; one event per vessel per run (holes up to 10 min)."""
    events = []
    flag = np.zeros(len(L["mmsi"]), bool)
    for m, s, e in vessel_slices(L["mmsi"]):
        if mmsi_kind(m) in ("sar_aircraft", "aton", "coast_station"):
            continue
        lim = speed_limit_kn(vessel_type(meta, m))
        f = (L["sog"][s:e] > lim) & (L["sog"][s:e] < SOG_NA)
        if not f.any():
            continue
        idx = np.flatnonzero(f) + s
        flag[idx] = True
        runs = np.split(idx, np.flatnonzero(np.diff(L["time"][idx]) > 600) + 1)
        for r in runs:
            events.append({"rule": "D7-reported-speed", "t0": iso(L["time"][r[0]]), "t1": iso(L["time"][r[-1]]),
                           "lat": round(float(np.median(L["lat"][r])), 5), "lon": round(float(np.median(L["lon"][r])), 5),
                           "mmsi": [m], "numbers": {"reports": int(len(r)), "median_sog": round(float(np.median(L["sog"][r])), 1),
                                                    "limit_kn": round(lim, 1)},
                           "context": {"class": vessel_class(vessel_type(meta, m))[0],
                                       "region": region_of(float(np.median(L["lat"][r])), float(np.median(L["lon"][r])))}})
    return events, flag


def d7_speed(L, meta, stats):
    """Impossible implied speeds per vessel. Returns (episodes, suspect mask over all rows, per-vessel jump counts)."""
    events = []
    suspect = np.zeros(len(L["mmsi"]), bool)
    per_vessel = {}
    same_second = 0
    for m, s, e in vessel_slices(L["mmsi"]):
        kind = mmsi_kind(m)
        if kind in ("sar_aircraft", "aton", "coast_station"):
            continue
        t, lat, lon = L["time"][s:e], L["lat"][s:e], L["lon"][s:e]
        if e - s < 2:
            continue
        d = haversine_km(lat[:-1], lon[:-1], lat[1:], lon[1:])
        dt = np.diff(t).astype(float)
        same_second += int(((dt == 0) & (d > 1.0)).sum())
        lim = speed_limit_kn(vessel_type(meta, m))
        v = d / np.maximum(dt, 1.0) * 3600 / KN
        if not ((v > lim) & (d > 1.0)).any():
            continue
        sus, exc = walk_track(t, lat, lon, lim)
        suspect[s:e] = sus
        steps = len(d)
        bad_steps = int(((v > lim) & (d > 1.0)).sum())
        per_vessel[m] = {"excursions": len(exc), "bad_steps": bad_steps, "steps": steps}
        repeated = len(exc) >= 4 and bad_steps >= 0.1 * steps
        for x in exc:
            a, i0, i1 = s + x["anchor"], s + x["i0"], s + x["i1"]
            jump_km = float(haversine_km(L["lat"][a], L["lon"][a], L["lat"][i0], L["lon"][i0]))
            dt0 = max(int(L["time"][i0] - L["time"][a]), 1)
            ev = {"rule": "D7-speed", "kind": x["kind"], "t0": iso(L["time"][i0]), "t1": iso(L["time"][i1]),
                  "lat": round(float(L["lat"][i0]), 5), "lon": round(float(L["lon"][i0]), 5),
                  "from_lat": round(float(L["lat"][a]), 5), "from_lon": round(float(L["lon"][a]), 5),
                  "mmsi": [m], "numbers": {"jump_km": round(jump_km, 2), "dt_s": dt0,
                                           "implied_kn": round(jump_km / dt0 * 3600 / KN, 1), "limit_kn": round(lim, 1),
                                           "reports_away": x["i1"] - x["i0"] + 1,
                                           "away_s": int(L["time"][i1] - L["time"][i0])},
                  "context": {"pattern": "repeated (shared MMSI, faulty unit or sustained interference)" if repeated else "isolated",
                              "mmsi_kind": kind, "class": vessel_class(vessel_type(meta, m))[0],
                              "region": region_of(L["lat"][i0], L["lon"][i0])}}
            events.append(ev)
    stats["same_second_conflicts"] = same_second
    stats["d7_excursions_before_merge"] = len(events)
    return merge_episodes(events), suspect, per_vessel


# ----------------------------------------------------------------------------------------------- D7 land
def land_depth(L, land):
    """Depth inside land (km) for every row, computed once per distinct position (rounded to 1e-4 deg)."""
    key = pos_key(L["lat"], L["lon"], 4)
    uk, first, inv = np.unique(key, return_index=True, return_inverse=True)
    return land.depth_km(L["lon"][first], L["lat"][first])[inv.ravel()]


def d7_land(L, meta, suspect, depth, cells8, dirty_vessels):
    """Positions more than LAND_DEPTH_KM inside land, outside H3 res-8 cells used by >= 3 clean vessels (no
    impossible jumps or reported speeds anywhere in the sample). One event per vessel per continuous on-land run."""
    if depth is None:
        return [], {}
    onland = depth > LAND_DEPTH_KM
    # cells many clean vessels use are navigable (canals, rivers, harbours missing from Natural Earth 10m)
    clean = ~suspect & ~np.isin(L["mmsi"], np.array(sorted(dirty_vessels), dtype=L["mmsi"].dtype))
    pairs = set(zip(cells8[clean], L["mmsi"][clean]))
    users = Counter(c for c, _ in pairs)
    navigable = np.array([users.get(c, 0) >= 3 for c in cells8])
    flag = onland & ~navigable
    events, stats = [], {"onland_positions_raw": int(onland.sum()), "onland_in_navigable_cells": int((onland & navigable).sum()),
                         "onland_flagged_positions": int(flag.sum())}
    for m, s, e in vessel_slices(L["mmsi"]):
        f = flag[s:e]
        if not f.any():
            continue
        idx = np.flatnonzero(f) + s
        runs = np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1)
        for r in runs:
            i0, i1 = int(r[0]), int(r[-1])
            arrived_by_jump = bool(suspect[r].any()) or m in dirty_vessels
            deep = float(depth[r].max()) >= 20
            events.append({"rule": "D7-land", "t0": iso(L["time"][i0]), "t1": iso(L["time"][i1]),
                           "lat": round(float(L["lat"][i0]), 5), "lon": round(float(L["lon"][i0]), 5), "mmsi": [m],
                           "numbers": {"reports": len(r), "max_depth_km": round(float(depth[r].max()), 2)},
                           "context": {"arrived_by_impossible_jump": arrived_by_jump,
                                       "strong": bool(arrived_by_jump or deep),
                                       "reading": "spoofing or GNSS fault likely" if (arrived_by_jump or deep) else
                                       "smooth track a little inland: coastline gap, harbour or inland waterway likely",
                                       "class": vessel_class(vessel_type(meta, m))[0],
                                       "region": region_of(L["lat"][i0], L["lon"][i0])}})
    return events, stats


# ----------------------------------------------------------------------------------------------- binning helpers
def minute_grid(L, mask, bin_s=60, hold_s=360):
    """Latest masked position of each vessel in each time bin, held forward up to hold_s. Returns
    (bins, dict mmsi -> arrays (bin index, row index))."""
    t0 = int(L["time"].min()) // bin_s * bin_s
    out = {}
    for m, s, e in vessel_slices(L["mmsi"]):
        idx = np.flatnonzero(mask[s:e]) + s
        if len(idx) == 0:
            continue
        b = (L["time"][idx] - t0) // bin_s
        last = np.flatnonzero(np.r_[b[1:] != b[:-1], True])      # last report in each bin
        b, idx = b[last], idx[last]
        fb, fi = [], []
        for k in range(len(b)):
            nxt = b[k + 1] if k + 1 < len(b) else b[k] + 1
            stop = min(nxt, b[k] + hold_s // bin_s + 1)
            rng = np.arange(b[k], stop)
            fb.append(rng); fi.append(np.full(len(rng), idx[k]))
        out[m] = (np.concatenate(fb), np.concatenate(fi))
    return t0, out


def runs_of(bins, max_hole=5):
    """Split sorted bin indices into runs allowing holes up to max_hole bins."""
    if len(bins) == 0:
        return []
    cut = np.flatnonzero(np.diff(bins) > max_hole + 1) + 1
    return [r for r in np.split(bins, cut)]


def port_zones(L, ports_ll):
    """Port and anchorage areas: H3 res-7 cells (about 5 km2) where >= 2 vessels were moored (navStat 5), >= 3
    anchored (navStat 1) or >= 3 stationary (SOG < 0.5 kn; many domestic craft never set navStat); res-6 cells (about
    36 km2) with >= 3 anchored vessels; plus cells within ~5 km of a Natural Earth port."""
    import h3
    c7 = h3_cells(L["lat"], L["lon"], 7)
    moored = Counter(c for c, _ in set(zip(c7[L["navStat"] == 5], L["mmsi"][L["navStat"] == 5])))
    anch = Counter(c for c, _ in set(zip(c7[L["navStat"] == 1], L["mmsi"][L["navStat"] == 1])))
    still = L["sog"] < 0.5
    stat = Counter(c for c, _ in set(zip(c7[still], L["mmsi"][still])))
    zone = ({c for c, n in moored.items() if n >= 2} | {c for c, n in anch.items() if n >= 3}
            | {c for c, n in stat.items() if n >= 3})
    # anchorages are wider than a res-7 cell (ships lie 1-3 km apart): 3 or more anchored in a res-6 cell (about 36 km2)
    a6 = Counter(h3.cell_to_parent(c, 6) for c, _ in set(zip(c7[L["navStat"] == 1], L["mmsi"][L["navStat"] == 1])))
    for c6, n in a6.items():
        if n >= 3:
            zone |= set(h3.cell_to_children(c6, 7))
    for la, lo in zip(*ports_ll):
        if CLIP[1] <= la <= CLIP[3] and CLIP[0] <= lo <= CLIP[2]:
            zone |= set(h3.grid_disk(h3.latlng_to_cell(la, lo, 7), 2))
    return c7, zone


# ----------------------------------------------------------------------------------------------- D3 rendezvous
def setting_of(in_zone, shore_km, outside="open water"):
    if in_zone:
        return "port or anchorage zone"
    if shore_km is not None and shore_km < 2.0:
        return "near shore (harbour or archipelago)"
    return outside


def d3_rendezvous(L, meta, suspect, c7, zone, min_h, radius_m=500.0, slow_kn=2.0, land=None):
    from scipy.spatial import cKDTree
    slow = (~suspect) & (L["sog"] < slow_kn)
    t0, grid = minute_grid(L, slow)
    x, y = to_xy(L["lon"], L["lat"])
    by_bin = defaultdict(list)
    for m, (b, i) in grid.items():
        k = mmsi_kind(m)
        if k not in ("ship", "ship_unallocated_mid", "other"):
            continue
        for bb, ii in zip(b, i):
            by_bin[int(bb)].append((m, int(ii)))
    pair_bins = defaultdict(list)
    for bb, lst in by_bin.items():
        if len(lst) < 2:
            continue
        pts = np.array([[x[i], y[i]] for _, i in lst])
        for a, b in cKDTree(pts).query_pairs(radius_m):
            ma, mb = lst[a][0], lst[b][0]
            key = (min(ma, mb), max(ma, mb))
            pair_bins[key].append((bb, lst[a][1], lst[b][1]))
    events, considered = [], 0
    for (ma, mb), recs in pair_bins.items():
        recs.sort()
        bins = np.array([r[0] for r in recs])
        for run in runs_of(bins):
            dur_h = (run[-1] - run[0] + 1) / 60
            if dur_h < min_h:
                continue
            considered += 1
            sel = [r for r in recs if run[0] <= r[0] <= run[-1]]
            ia = np.array([r[1] for r in sel]); ib = np.array([r[2] for r in sel])
            ns = np.concatenate([L["navStat"][ia], L["navStat"][ib]])
            both_moored = bool((L["navStat"][ia] == 5).mean() > 0.5 and (L["navStat"][ib] == 5).mean() > 0.5)
            in_zone = bool(np.mean([c7[i] in zone for i in ia]) > 0.5)
            ta, tb = vessel_type(meta, ma), vessel_type(meta, mb)
            service = any(t is not None and 50 <= t <= 59 for t in (ta, tb))
            small = any(is_private_small(t) for t in (ta, tb))
            dist = haversine_km(L["lat"][ia], L["lon"][ia], L["lat"][ib], L["lon"][ib]) * 1000
            la_, lo_ = float(L["lat"][ia].mean()), float(L["lon"][ia].mean())
            shore = float(land.shore_km(lo_, la_)[0]) if land is not None else None
            ctx = "moored together" if both_moored else setting_of(in_zone, shore)
            events.append({"rule": "D3-rendezvous", "t0": iso(t0 + run[0] * 60), "t1": iso(t0 + (run[-1] + 1) * 60),
                           "lat": round(float(L["lat"][ia].mean()), 5), "lon": round(float(L["lon"][ia].mean()), 5),
                           "mmsi": [ma, mb],
                           "numbers": {"hours": round(dur_h, 2), "median_sep_m": int(np.median(dist)),
                                       "min_sep_m": int(dist.min())},
                           "context": {"setting": ctx, "shore_km": None if shore is None else round(shore, 2),
                                       "same_hull_or_rafted": bool(np.median(dist) < 15),
                                       "service_craft_involved": service, "small_private_involved": small,
                                       "classes": [vessel_class(ta)[0], vessel_class(tb)[0]],
                                       "nav_status": dict(Counter(int(v) for v in ns).most_common(3)),
                                       "region": region_of(L["lat"][ia[0]], L["lon"][ia[0]])}})
    return events


# ----------------------------------------------------------------------------------------------- D4 loitering
def d4_loiter(L, meta, suspect, c7, zone, min_h, slow_kn=2.0, land=None):
    events = []
    slow = (~suspect) & (L["sog"] < slow_kn)
    for m, s, e in vessel_slices(L["mmsi"]):
        if mmsi_kind(m) not in ("ship", "ship_unallocated_mid", "other"):
            continue
        idx = np.flatnonzero(slow[s:e]) + s
        if len(idx) < 2:
            continue
        # a run of slow reports with no fast report in between and no gap over 30 min
        allidx = np.arange(s, e)
        fast_pos = np.flatnonzero(~slow[s:e] & ~suspect[s:e]) + s
        cuts = np.searchsorted(fast_pos, idx)
        grp = np.flatnonzero((np.diff(cuts) != 0) | (np.diff(L["time"][idx]) > 1800)) + 1
        for r in np.split(idx, grp):
            if len(r) < 2:
                continue
            dur = (L["time"][r[-1]] - L["time"][r[0]]) / 3600
            if dur < min_h:
                continue
            ns = L["navStat"][r]
            if (ns == 5).mean() > 0.5:
                continue                    # moored
            in_zone = np.mean([c7[i] in zone for i in r]) > 0.5
            spread = float(haversine_km(L["lat"][r].min(), L["lon"][r].min(), L["lat"][r].max(), L["lon"][r].max()))
            t = vessel_type(meta, m)
            la_, lo_ = float(np.median(L["lat"][r])), float(np.median(L["lon"][r]))
            shore = float(land.shore_km(lo_, la_)[0]) if land is not None else None
            events.append({"rule": "D4-loiter", "t0": iso(L["time"][r[0]]), "t1": iso(L["time"][r[-1]]),
                           "lat": round(float(np.median(L["lat"][r])), 5), "lon": round(float(np.median(L["lon"][r])), 5),
                           "mmsi": [m], "numbers": {"hours": round(float(dur), 2), "box_diag_km": round(spread, 2),
                                                    "reports": int(len(r))},
                           "context": {"setting": setting_of(in_zone, shore, "outside ports and anchorages"),
                                       "shore_km": None if shore is None else round(shore, 2),
                                       "nav_status": {int(k): int(v) for k, v in Counter(ns.tolist()).most_common(3)},
                                       "at_anchor": bool((ns == 1).mean() > 0.5), "class": vessel_class(t)[0],
                                       "small_private": is_private_small(t),
                                       "region": region_of(L["lat"][r[0]], L["lon"][r[0]])}})
    return events


# ----------------------------------------------------------------------------------------------- D5 going dark
def coverage_table(L, cells5, bin_s=600):
    """Distinct vessels received per (H3 res-5 cell, 10-min bin)."""
    b = L["time"] // bin_s
    keys = defaultdict(set)
    for c, bb, m in zip(cells5, b, L["mmsi"]):
        keys[(c, int(bb))].add(int(m))
    return {k: len(v) for k, v in keys.items()}, bin_s


def good_coverage(cov, bin_s, cell, t_a, t_b, min_vessels=3, min_share=0.75):
    """True when the cell received >= min_vessels other vessels in >= min_share of the 10-min bins inside the gap
    (the silent vessel itself contributes nothing during its gap)."""
    bins = range(int(t_a) // bin_s + 1, int(t_b) // bin_s)
    if len(bins) == 0:
        return True, 1.0
    ok = sum(1 for bb in bins if cov.get((cell, bb), 0) >= min_vessels)
    share = ok / len(bins)
    return share >= min_share, share


def d5_dark(L, meta, cells5, min_gap_h, t_first, t_last, min_reports=5):
    """Gaps over min_gap_h that start and end where other vessels kept being received, by vessels that were received
    regularly just before and just after (>= min_reports within the gap's length or 1 h, whichever is shorter), so
    vessels at the edge of coverage, received only now and then, are not counted."""
    cov, bin_s = coverage_table(L, cells5)
    edge = 0
    events, n_gaps = [], 0
    for m, s, e in vessel_slices(L["mmsi"]):
        if mmsi_kind(m) not in ("ship", "ship_unallocated_mid", "other") or e - s < 2:
            continue
        t = L["time"][s:e]
        gaps = np.flatnonzero(np.diff(t) >= min_gap_h * 3600)
        for g in gaps:
            a, b = s + g, s + g + 1
            n_gaps += 1
            ok_a, sh_a = good_coverage(cov, bin_s, cells5[a], L["time"][a], L["time"][b])
            ok_b, sh_b = good_coverage(cov, bin_s, cells5[b], L["time"][a], L["time"][b])
            if not (ok_a and ok_b):
                continue
            w = min(3600, int(L["time"][b] - L["time"][a]))
            n_before = int(((t >= L["time"][a] - w) & (t <= L["time"][a])).sum())
            n_after = int(((t >= L["time"][b]) & (t <= L["time"][b] + w)).sum())
            if n_before < min_reports or n_after < min_reports:
                edge += 1
                continue
            gap_h = (L["time"][b] - L["time"][a]) / 3600
            dist = float(haversine_km(L["lat"][a], L["lon"][a], L["lat"][b], L["lon"][b]))
            ty = vessel_type(meta, m)
            stationary = L["sog"][a] < 1 and L["sog"][b] < 1 and dist < 1
            events.append({"rule": "D5-dark", "t0": iso(L["time"][a]), "t1": iso(L["time"][b]),
                           "lat": round(float(L["lat"][a]), 5), "lon": round(float(L["lon"][a]), 5),
                           "end_lat": round(float(L["lat"][b]), 5), "end_lon": round(float(L["lon"][b]), 5),
                           "mmsi": [m], "numbers": {"gap_h": round(float(gap_h), 2), "moved_km": round(dist, 2),
                                                    "implied_kn": round(dist / max(gap_h, 1e-6) / KN, 1),
                                                    "coverage_share_start": round(sh_a, 2), "coverage_share_end": round(sh_b, 2)},
                           "context": {"stationary_both_ends": bool(stationary), "class": vessel_class(ty)[0],
                                       "has_imo": bool(meta.get(m, {}).get("imo")), "small_private": is_private_small(ty),
                                       "nav_status_start": int(L["navStat"][a]),
                                       "region": region_of(L["lat"][a], L["lon"][a])}})
    return events, {"gaps_over_threshold": n_gaps, "gaps_irregular_reception": edge}


# ----------------------------------------------------------------------------------------------- D7 clusters and circles
def d7_clusters(L, meta, suspect, depth_flag, rs_flag=None, bin_s=600, radius_m=50.0, min_vessels=4):
    """Several vessels at one point in the same 10-min bin. Reported when the group is tied to spoofing evidence:
    at least two members with impossible jumps or impossible reported speeds, or on land. Also reports identical
    coordinates shared by different MMSIs in the same minute while moving (stationary pairs are only counted)."""
    if rs_flag is not None:
        suspect = suspect | rs_flag
    from scipy.spatial import cKDTree
    x, y = to_xy(L["lon"], L["lat"])
    b = L["time"] // bin_s
    events, tight_groups = [], 0
    order = np.argsort(b, kind="stable")
    bs = b[order]
    cut = np.flatnonzero(np.diff(bs)) + 1
    for grp in np.split(order, cut):
        if len(grp) < min_vessels:
            continue
        # latest position per vessel in the bin
        mm = L["mmsi"][grp]
        last = {}
        for i in grp:
            last[int(L["mmsi"][i])] = i
        idx = np.array(list(last.values()))
        if len(idx) < min_vessels:
            continue
        tree = cKDTree(np.column_stack([x[idx], y[idx]]))
        pairs = tree.query_pairs(radius_m, output_type="ndarray")
        if len(pairs) == 0:
            continue
        # connected components
        parent = list(range(len(idx)))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a
        for a, c in pairs:
            parent[find(a)] = find(c)
        comps = defaultdict(list)
        for k in range(len(idx)):
            comps[find(k)].append(idx[k])
        for members in comps.values():
            if len(members) < min_vessels:
                continue
            tight_groups += 1
            members = np.array(members)
            n_sus = int(suspect[members].sum())
            n_land = int(depth_flag[members].sum()) if depth_flag is not None else 0
            if n_sus >= 2 or n_land >= 2:
                events.append({"rule": "D7-cluster", "t0": iso(L["time"][members].min()), "t1": iso(L["time"][members].max()),
                               "lat": round(float(L["lat"][members].mean()), 5), "lon": round(float(L["lon"][members].mean()), 5),
                               "mmsi": sorted(int(v) for v in L["mmsi"][members]),
                               "numbers": {"vessels": int(len(members)), "suspect": n_sus, "on_land": n_land},
                               "context": {"region": region_of(L["lat"][members[0]], L["lon"][members[0]])}})
    # identical coordinates (to 1e-5 deg, about 1 m) from different MMSIs in the same minute
    key = pos_key(L["lat"], L["lon"], 5)
    minute = L["time"] // 60
    o = np.lexsort((L["mmsi"], key, minute))
    k2, n2, m2 = key[o], minute[o], L["mmsi"][o]
    same = np.flatnonzero((k2[1:] == k2[:-1]) & (n2[1:] == n2[:-1]) & (m2[1:] != m2[:-1]))
    shared = {}
    for j in same:
        i, i2 = o[j], o[j + 1]
        pair = (min(int(L["mmsi"][i]), int(L["mmsi"][i2])), max(int(L["mmsi"][i]), int(L["mmsi"][i2])))
        shared.setdefault(pair, []).append(i)
    stationary_pairs = 0
    for (a, c), lst in shared.items():
        moored = bool(np.mean(L["sog"][lst] < 0.5) > 0.5)
        if moored:
            stationary_pairs += 1
            continue
        events.append({"rule": "D7-shared-fix", "t0": iso(L["time"][lst].min()), "t1": iso(L["time"][lst].max()),
                       "lat": round(float(L["lat"][lst[0]]), 5), "lon": round(float(L["lon"][lst[0]]), 5),
                       "mmsi": [a, c], "numbers": {"minutes_shared": len(lst)},
                       "context": {"stationary": moored, "kinds": [mmsi_kind(a), mmsi_kind(c)],
                                   "region": region_of(L["lat"][lst[0]], L["lon"][lst[0]])}})
    return events, {"tight_groups_4plus_within_50m": tight_groups, "shared_fix_pairs_stationary": stationary_pairs}


def d7_circles(L, meta, suspect, window_s=1800, min_turn_deg=720, max_radius_km=1.5, min_kn=3.0):
    """Vessels whose track turns through >= 720 degrees within 30 min inside a small radius while moving.
    Mostly benign alone (fishing, SAR training, compass swinging); several vessels circling one centre at the same
    time is the spoofing pattern."""
    single = []
    for m, s, e in vessel_slices(L["mmsi"]):
        ok = np.flatnonzero(~suspect[s:e]) + s
        if len(ok) < 10:
            continue
        lat, lon, t = L["lat"][ok], L["lon"][ok], L["time"][ok]
        x, y = to_xy(lon, lat)
        dx, dy = np.diff(x), np.diff(y)
        step = np.hypot(dx, dy)
        keep = step > 20                       # ignore jitter
        if keep.sum() < 8:
            continue
        brg = np.degrees(np.arctan2(dx[keep], dy[keep]))
        tt = t[1:][keep]
        turn = np.abs((np.diff(brg) + 180) % 360 - 180)
        tt2 = tt[1:]
        if len(turn) < 6:
            continue
        cs = np.concatenate([[0], np.cumsum(turn)])
        j = 0
        k = 0
        while k < len(tt2):
            while tt2[k] - tt2[j] > window_s:
                j += 1
            if cs[k + 1] - cs[j] >= min_turn_deg:
                sel = (t >= tt2[j]) & (t <= tt2[k])
                cx, cy = x[sel].mean(), y[sel].mean()
                rad = float(np.sqrt(((x[sel] - cx) ** 2 + (y[sel] - cy) ** 2).mean())) / 1000
                v = float(np.median(L["sog"][ok][sel]))
                if rad <= max_radius_km and v >= min_kn:
                    hd, cg = L["heading"][ok][sel], L["cog"][ok][sel]
                    hv = (hd < 360) & (cg < 360)
                    div = float((np.abs((cg[hv] - hd[hv] + 180) % 360 - 180) > 45).mean()) if hv.sum() >= 5 else None
                    single.append({"mmsi": m, "t0": int(tt2[j]), "t1": int(tt2[k]), "x": cx, "y": cy,
                                   "lat": float(lat[sel].mean()), "lon": float(lon[sel].mean()),
                                   "radius_km": rad, "turn_deg": float(cs[k + 1] - cs[j]), "sog": v, "div": div})
                    # skip ahead past this window
                    while k < len(tt2) and tt2[k] - tt2[j] <= window_s:
                        k += 1
                    j = k
                    continue
            k += 1
    # group circling windows that share a centre (within 2 km) and overlap in time (chained)
    parent = list(range(len(single)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for i, a in enumerate(single):
        for j in range(i + 1, len(single)):
            b = single[j]
            if a["t0"] - window_s <= b["t1"] and b["t0"] - window_s <= a["t1"] and math.hypot(a["x"] - b["x"], a["y"] - b["y"]) < 2000:
                parent[find(i)] = find(j)
    groups = defaultdict(list)
    for i in range(len(single)):
        groups[find(i)].append(single[i])
    events = []
    for g in groups.values():
        ms = sorted({c["mmsi"] for c in g})
        multi = len(ms) > 1
        events.append({"rule": "D7-circle", "t0": iso(min(c["t0"] for c in g)), "t1": iso(max(c["t1"] for c in g)),
                       "lat": round(float(np.mean([c["lat"] for c in g])), 5), "lon": round(float(np.mean([c["lon"] for c in g])), 5),
                       "mmsi": ms,
                       "numbers": {"vessels": len(ms), "windows": len(g),
                                   "median_radius_km": round(float(np.median([c["radius_km"] for c in g])), 2),
                                   "median_sog": round(float(np.median([c["sog"] for c in g])), 1),
                                   "cog_heading_gt45_share": (None if all(c["div"] is None for c in g) else
                                                              round(float(np.mean([c["div"] for c in g if c["div"] is not None])), 2))},
                       "context": {"reading": "shared-centre circling: spoofing pattern" if multi else
                                   "single vessel, course detached from heading: check for spoofing"
                                   if any((c["div"] or 0) > 0.5 for c in g) else
                                   "single vessel, no heading reported: usually benign (fishing, SAR, trials)"
                                   if all(c["div"] is None for c in g) else
                                   "single vessel, heading follows course: real manoeuvre likely (waiting, fishing, SAR, trials)",
                                   "classes": sorted({vessel_class(vessel_type(meta, m))[0] for m in ms}),
                                   "region": region_of(g[0]["lat"], g[0]["lon"])}})
    return events


def spoof_victims(L, meta, flagged, dirty):
    """For each vessel with flagged positions (impossible jump, impossible reported speed, or deep inland): where it
    last was before (trusted position) and first was after, and where its flagged positions were. The trusted
    positions show where the interference reached vessels; the flagged ones where the receivers were told they were."""
    out = []
    for m, s, e in vessel_slices(L["mmsi"]):
        f = flagged[s:e]
        if not f.any():
            continue
        fi = np.flatnonzero(f) + s
        ti = np.flatnonzero(~f) + s
        before = ti[ti < fi[0]]
        after = ti[ti > fi[-1]]
        fl_lat, fl_lon = float(np.median(L["lat"][fi])), float(np.median(L["lon"][fi]))
        rec = {"mmsi": m, "label": label(meta, m), "flagged_reports": int(len(fi)), "reports": int(e - s),
               "first_flagged": iso(L["time"][fi[0]]), "last_flagged": iso(L["time"][fi[-1]]),
               "flagged_center": [round(fl_lat, 4), round(fl_lon, 4)],
               "flagged_median_sog": round(float(np.median(L["sog"][fi])), 1),
               "posAcc_flagged": round(float(L["posAcc"][fi].mean()), 2), "raim_flagged": round(float(L["raim"][fi].mean()), 2)}
        lim = speed_limit_kn(vessel_type(meta, m))
        sog_bad = float(((L["sog"][fi] > lim) & (L["sog"][fi] < SOG_NA)).mean())
        hv = (L["heading"][fi] < 360) & (L["cog"][fi] < 360) & (L["sog"][fi] > 5)
        hd = float((np.abs((L["cog"][fi][hv] - L["heading"][fi][hv] + 180) % 360 - 180) > 45).mean()) if hv.sum() >= 5 else None
        rec["impossible_sog_share"] = round(sog_bad, 2)
        rec["cog_heading_gt45_share"] = None if hd is None else round(hd, 2)
        # a shared MMSI gives two plausible tracks with plausible speeds; a spoofed or jammed receiver gives
        # impossible GNSS speeds, course detached from heading, or positions far inland
        rec["reading"] = ("GNSS interference likely" if sog_bad > 0.3 or (hd is not None and hd > 0.5) else
                          "shared MMSI, data error or interference: check")
        for name, idx in (("before", before[-1] if len(before) else None), ("after", after[0] if len(after) else None)):
            if idx is not None:
                rec[name] = {"t": iso(L["time"][idx]), "lat": round(float(L["lat"][idx]), 4), "lon": round(float(L["lon"][idx]), 4),
                             "sog": round(float(L["sog"][idx]), 1), "region": region_of(L["lat"][idx], L["lon"][idx])}
        ref = rec.get("before") or rec.get("after")
        rec["displacement_km"] = round(float(haversine_km(ref["lat"], ref["lon"], fl_lat, fl_lon)), 1) if ref else None
        out.append(rec)
    return sorted(out, key=lambda r: -(r["displacement_km"] or 0))


# ----------------------------------------------------------------------------------------------- D6 identity
LOCODE = re.compile(r"^[A-Z]{2} ?[A-Z0-9]{3}$")
ROUTE = re.compile(r"^[A-Z]{2} ?[A-Z0-9]{3} ?(>|-|=>|TO|/) ?[A-Z]{2} ?[A-Z0-9]{3}$")
PLACE = re.compile(r"^[A-Z0-9][A-Z0-9 .,\-/'_>()]{0,19}$")
SERVICE = re.compile(r"\b(PILOT|CH ?\d+|VTS|TUG|ICEBREAK|PATROL|SAR|RESCUE|DREDG|SURVEY|WORK|SERVICE)")
# Generic statements seen in AIS destination fields in conflict areas (e.g. Red Sea, maritime plan D6). Method
# parameters, not a watch list; a private file can add patterns with --dest-patterns.
STATEMENT = re.compile(r"\b(CREW|ARMED|GUARDS?|SECURITY|OWNER|NO (LINK|CONNECTION|CONTACT|RELATION)|ALL CHINESE|"
                       r"CHINESE|RUSSIAN|ISRAEL|NO ISR|SANCTION|WAR|MILITARY|NAVY|HELP|MAYDAY|PIRAT)\b")


def dest_class(s, extra=None):
    if not s:
        return "empty"
    if STATEMENT.search(s) or (extra and extra.search(s)):
        return "statement"
    if LOCODE.match(s) or ROUTE.match(s):
        return "locode"
    if s in ("FOR ORDERS", "FOR ORDER", "ORDERS", "TBN", "TBA", "N/A", "NONE", "UNKNOWN", "SEA", "AT SEA", "FISHING",
             "ANCHORAGE", "TRIALS", "SEA TRIALS", "PATROL", "ICEBREAKING", "WORKING"):
        return "generic"
    if SERVICE.search(s):
        return "service"
    if PLACE.match(s) and len(s.split()) <= 3:
        return "place"
    return "unusual"


def d6_identity(meta, L, extra_patterns=None):
    events = []
    active = set(int(m) for m in np.unique(L["mmsi"]))
    for m, v in meta.items():
        changes = {k: sorted(v["hist"][k].items(), key=lambda kv: kv[1][0]) for k in ("name", "callSign", "imo", "type")
                   if len(v["hist"].get(k, {})) > 1}
        if changes:
            t0 = min(h[0] for k in changes for _, h in changes[k])
            t1 = max(h[1] for k in changes for _, h in changes[k])
            events.append({"rule": "D6-identity-change", "t0": iso(t0 / 1000), "t1": iso(t1 / 1000), "mmsi": [m],
                           "numbers": {k: len(c) for k, c in changes.items()},
                           "values": {k: [[str(val), iso(h[0] / 1000), iso(h[1] / 1000), h[2], sorted(h[3])] for val, h in c]
                                      for k, c in changes.items()},
                           "context": {"class": vessel_class(v.get("type"))[0], "small_private": is_private_small(v.get("type")),
                                       "active_in_sample": m in active}})
    by_imo = defaultdict(set)
    for m, v in meta.items():
        for imo in v["hist"].get("imo", {}):
            by_imo[imo].add(m)
    for imo, ms in by_imo.items():
        if len(ms) > 1:
            act = sorted(ms & active)
            events.append({"rule": "D6-imo-shared", "mmsi": sorted(ms), "imo": imo,
                           "numbers": {"mmsis": len(ms), "active": len(act)},
                           "context": {"names": sorted({meta[m].get("name", "") for m in ms})}})
    # IMO field: 7 digits with a wrong check digit is the signal; other numbers (often the MMSI or a national
    # register number typed into the IMO field on small domestic craft) are only counted
    imo_stats = Counter()
    for m, v in meta.items():
        imo = v.get("imo")
        if not imo:
            imo_stats["none"] += 1
            continue
        if not (1_000_000 <= imo <= 9_999_999):
            imo_stats["not_7_digits"] += 1
            continue
        if imo_valid(imo):
            imo_stats["valid"] += 1
            continue
        imo_stats["bad_check_digit"] += 1
        events.append({"rule": "D6-imo-invalid", "mmsi": [m], "imo": imo,
                       "context": {"class": vessel_class(v.get("type"))[0], "small_private": is_private_small(v.get("type")),
                                   "active_in_sample": m in active}})
    dest = Counter()
    dest_vessels = defaultdict(set)
    for m, v in meta.items():
        for d in v["hist"].get("destination", {}):
            c = dest_class(d, extra_patterns)
            dest[c] += 1
            dest_vessels[(c, d)].add(m)
    for (c, d), ms in dest_vessels.items():
        if c in ("statement", "unusual"):
            events.append({"rule": "D6-destination-text", "text": d, "mmsi": sorted(ms),
                           "numbers": {"vessels": len(ms)}, "context": {"class": c}})
    return events, {"destination_classes": dict(dest), "imo_field": dict(imo_stats)}


# ----------------------------------------------------------------------------------------------- GNSS signatures
def gnss_signatures(L, U, meta, suspect, regions):
    """Per region: posAcc and RAIM shares, flag toggles, frozen positions while under way, COG-heading divergence,
    SOG vs track speed. Returns (table rows, per-vessel event list)."""
    out = defaultdict(lambda: Counter())
    vessels = defaultdict(set)
    togglers = defaultdict(set)
    for r, m, pa_, ra, sog, cog in zip(regions, L["mmsi"], L["posAcc"], L["raim"], L["sog"], L["cog"]):
        o = out[r]
        o["msgs"] += 1; o["posAcc1"] += int(pa_); o["raim1"] += int(ra)
        o["sog_na"] += int(sog >= SOG_NA); o["cog_na"] += int(cog >= 360)
        vessels[r].add(int(m))
    events = []
    for m, s, e in vessel_slices(L["mmsi"]):
        if e - s < 3:
            continue
        idx = np.arange(s, e)
        r = regions[s:e]
        # flag toggles
        for k, name in (("posAcc", "posacc_toggles"), ("raim", "raim_toggles")):
            tg = np.flatnonzero(L[k][s + 1:e] != L[k][s:e - 1]) + s + 1
            for i in tg:
                out[regions[i]][name] += 1
                togglers[(name, regions[i])].add(m)
        for i in np.flatnonzero(L["sog"][s:e] >= SOG_NA) + s:
            togglers[("sog_na", regions[i])].add(m)
        # frozen: identical position on consecutive reports >= 5 min apart in total while SOG > 3 kn
        same = ((L["lat"][s + 1:e] == L["lat"][s:e - 1]) & (L["lon"][s + 1:e] == L["lon"][s:e - 1]) & (L["sog"][s + 1:e] > 3)
                & (L["sog"][s + 1:e] < SOG_NA))
        if same.any():
            j = np.flatnonzero(same) + s + 1
            runs = np.split(j, np.flatnonzero(np.diff(j) > 1) + 1)
            for rr in runs:
                dur = L["time"][rr[-1]] - L["time"][rr[0] - 1]
                if dur >= 300:
                    out[regions[rr[0]]]["frozen_runs"] += 1
                    events.append({"rule": "GNSS-frozen", "t0": iso(L["time"][rr[0] - 1]), "t1": iso(L["time"][rr[-1]]),
                                   "lat": round(float(L["lat"][rr[0]]), 5), "lon": round(float(L["lon"][rr[0]]), 5),
                                   "mmsi": [m], "numbers": {"seconds": int(dur), "median_sog": float(np.median(L["sog"][rr]))},
                                   "context": {"region": regions[rr[0]], "class": vessel_class(vessel_type(meta, m))[0]}})
        # COG vs heading at speed (heading 511 = not available)
        ok = (L["sog"][s:e] > 5) & (L["heading"][s:e] < 360) & (L["cog"][s:e] < 360)
        if ok.sum() >= 5:
            diff = np.abs((L["cog"][s:e] - L["heading"][s:e] + 180) % 360 - 180)
            big = ok & (diff > 45)
            for i in np.flatnonzero(ok) + s:
                out[regions[i]]["cog_hdg_checked"] += 1
            for i in np.flatnonzero(big) + s:
                out[regions[i]]["cog_hdg_gt45"] += 1
        # SOG vs track speed over >= 60 s, between accepted positions
        ok2 = np.flatnonzero(~suspect[s:e]) + s
        if len(ok2) >= 3:
            dt = np.diff(L["time"][ok2]).astype(float)
            d = haversine_km(L["lat"][ok2[:-1]], L["lon"][ok2[:-1]], L["lat"][ok2[1:]], L["lon"][ok2[1:]])
            sel = (dt >= 60) & (dt <= 900) & (L["sog"][ok2[1:]] < SOG_NA) & (L["sog"][ok2[:-1]] < SOG_NA)
            vt = d / np.maximum(dt, 1) * 3600 / KN
            vs = (L["sog"][ok2[1:]] + L["sog"][ok2[:-1]]) / 2
            mism = sel & (np.abs(vt - vs) > np.maximum(5, 0.5 * vs))
            for i in ok2[1:][sel]:
                out[regions[i]]["speed_checked"] += 1
            for i in ok2[1:][mism]:
                out[regions[i]]["speed_mismatch"] += 1
    for r_ in out:
        out[r_]["vessels"] = len(vessels[r_])
        for name in ("posacc_toggles", "raim_toggles", "sog_na"):
            out[r_][name + "_vessels"] = len(togglers.get((name, r_), ()))
    # positions not available, by the vessel's last known region
    lastreg = {}
    for m, s, e in vessel_slices(L["mmsi"]):
        lastreg[m] = regions[e - 1]
    for m in U["mmsi"]:
        out[lastreg.get(int(m), "Unknown (no valid position)")]["not_available"] += 1
    sus_r = Counter(regions[suspect])
    for r_, n in sus_r.items():
        out[r_]["suspect_positions"] += n
    return {k: dict(v) for k, v in out.items()}, events


def aircraft_compare(L, regions, suspect, days_back=14, last_day=None):
    """Aircraft GNSS degradation (bad_nacp_live / aircraft, data/pnt/year, H3 res 4) over the last days_back days
    available, joined to AIS H3 res-4 cells. Returns rows per region and per cell."""
    files = sorted(glob.glob(os.path.join(PNT_YEAR, "????-??-??.parquet")))
    if last_day:
        files = [f for f in files if os.path.basename(f)[:10] <= last_day]
    files = files[-days_back:]
    if not files:
        return None
    ac = Counter(); bad = Counter()
    for f in files:
        t = pq.read_table(f, columns=["h3", "aircraft", "bad_nacp_live"])
        for c, a, b in zip(t.column("h3").to_pylist(), t.column("aircraft").to_pylist(), t.column("bad_nacp_live").to_pylist()):
            ac[c] += a; bad[c] += b
    c4 = h3_cells(L["lat"], L["lon"], 4)
    cells = defaultdict(lambda: Counter())
    for c, r, s, pa_, m in zip(c4, regions, suspect, L["posAcc"], L["mmsi"]):
        k = cells[c]
        k["msgs"] += 1; k["suspect"] += int(s); k["posAcc1"] += int(pa_)
    rows = []
    for c, k in cells.items():
        rows.append({"h3": c, "region": None, "ais_msgs": k["msgs"], "ais_suspect": k["suspect"],
                     "ais_posacc1_share": round(k["posAcc1"] / k["msgs"], 3),
                     "aircraft": ac.get(c, 0), "aircraft_bad_share": round(bad.get(c, 0) / ac[c], 3) if ac.get(c) else None})
    import h3
    for r in rows:
        la, lo = h3.cell_to_latlng(r["h3"])
        r["lat"], r["lon"] = round(la, 3), round(lo, 3)
        r["region"] = region_of(la, lo)
    reg = defaultdict(lambda: Counter())
    for r in rows:
        g = reg[r["region"]]
        g["ais_msgs"] += r["ais_msgs"]; g["ais_suspect"] += r["ais_suspect"]
        g["aircraft"] += r["aircraft"]
        g["aircraft_bad"] += bad.get(r["h3"], 0)
    corr = None
    use = [r for r in rows if r["aircraft"] >= 20 and r["ais_msgs"] >= 100]
    if len(use) >= 8:
        from scipy.stats import spearmanr

        def rho(a, b):
            if len(set(a)) < 2 or len(set(b)) < 2:
                return None                    # constant input: undefined
            return round(float(spearmanr(a, b)[0]), 3)
        x = [r["aircraft_bad_share"] for r in use]
        corr = {"cells": len(use),
                "rho_aircraft_bad_vs_ais_flagged_share": rho(x, [r["ais_suspect"] / r["ais_msgs"] for r in use]),
                "rho_aircraft_bad_vs_ais_posacc1_share": rho(x, [r["ais_posacc1_share"] for r in use])}
    return {"days": [os.path.basename(f)[:10] for f in files], "cells": sorted(rows, key=lambda r: -(r["aircraft_bad_share"] or 0)),
            "regions": {k: dict(v) for k, v in reg.items()}, "cell_correlation": corr}


# ----------------------------------------------------------------------------------------------- main
def reporting_intervals(L):
    """Median reporting interval per vessel, split by moving (> 3 kn) or not, to see whether the feed is decimated."""
    mv, st = [], []
    for m, s, e in vessel_slices(L["mmsi"]):
        if e - s < 5:
            continue
        dt = np.diff(L["time"][s:e])
        sp = L["sog"][s + 1:e]
        if (sp > 3).sum() >= 4:
            mv.append(float(np.median(dt[sp > 3])))
        if (sp < 0.5).sum() >= 4:
            st.append(float(np.median(dt[sp < 0.5])))
    q = lambda a: [round(float(np.percentile(a, p)), 1) for p in (10, 50, 90)] if a else None
    return {"moving_median_interval_s_p10_p50_p90": q(mv), "stationary_median_interval_s_p10_p50_p90": q(st),
            "moving_vessels": len(mv), "stationary_vessels": len(st)}


def main():
    ap = argparse.ArgumentParser(description="AIS behaviour and spoofing detectors (maritime plan D3-D7)")
    ap.add_argument("--days", nargs="*", help="UTC days to read (default: all collected)")
    ap.add_argument("--preset", choices=sorted(PRESETS), help="duration thresholds (default: sample if < 12 h of data)")
    ap.add_argument("--gap-h", type=float); ap.add_argument("--rdv-h", type=float); ap.add_argument("--loiter-h", type=float)
    ap.add_argument("--no-land", action="store_true", help="skip the land mask (no Natural Earth download)")
    ap.add_argument("--dest-patterns", help="file of extra destination-text regexes (one per line), e.g. in private/")
    ap.add_argument("--aircraft-days", type=int, default=14, help="aircraft GNSS days to compare (latest available)")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--since", help="keep positions from this UTC time (e.g. 2026-10-25T19:51:00Z)")
    ap.add_argument("--until", help="keep positions before this UTC time")
    args = ap.parse_args()

    days = args.days or days_available()
    ep = lambda s: int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()) if s else None
    L, load_stats, U = load_locations(days, ep(args.since), ep(args.until))
    meta = load_metadata(days)
    t_first, t_last = int(L["time"].min()), int(L["time"].max())
    hours = (t_last - t_first) / 3600
    preset = args.preset or ("sample" if hours < 12 else "plan")
    th = dict(PRESETS[preset])
    for k in ("gap_h", "rdv_h", "loiter_h"):
        if getattr(args, k) is not None:
            th[k] = getattr(args, k)
    extra = None
    if args.dest_patterns and os.path.exists(args.dest_patterns):
        pats = [l.strip() for l in open(args.dest_patterns, encoding="utf-8") if l.strip() and not l.startswith("#")]
        extra = re.compile("|".join(f"(?:{p})" for p in pats), re.I) if pats else None

    stats = {"rules_version": RULES_VERSION, "source": SOURCE, "days": days, "first_utc": iso(t_first), "last_utc": iso(t_last),
             "hours": round(hours, 2), "preset": preset, "thresholds": th, "load": load_stats,
             "vessels_with_positions": int(len(np.unique(L["mmsi"]))), "vessels_with_metadata": len(meta)}
    kinds = Counter(mmsi_kind(m) for m in np.unique(L["mmsi"]))
    stats["mmsi_kinds"] = dict(kinds)
    types = Counter(vessel_class(vessel_type(meta, m))[0] for m in np.unique(L["mmsi"]))
    stats["classes"] = dict(types)
    stats["reporting"] = reporting_intervals(L)

    regions = regions_of(L["lat"], L["lon"])
    stats["positions_by_region"] = dict(Counter(regions.tolist()))

    ev_speed, suspect, per_vessel = d7_speed(L, meta, stats)
    stats["suspect_positions"] = int(suspect.sum())
    ev_rs, rs_flag = d7_reported_speed(L, meta)
    stats["reported_speed_impossible_positions"] = int(rs_flag.sum())
    dirty = {m for m, v in per_vessel.items() if v["excursions"]} | set(int(m) for m in np.unique(L["mmsi"][rs_flag]))
    land, depth = None, None
    if not args.no_land:
        try:
            land = LandMask()
            depth = land_depth(L, land)
        except Exception as e:
            print(f"land mask unavailable: {e}", file=sys.stderr)
    cells8 = h3_cells(L["lat"], L["lon"], 8)
    ev_land, land_stats = d7_land(L, meta, suspect, depth, cells8, dirty)
    stats["land"] = land_stats
    depth_flag = depth > LAND_DEPTH_KM if depth is not None else None
    ev_cluster, cl_stats = d7_clusters(L, meta, suspect, depth_flag, rs_flag)
    stats.update(cl_stats)
    ev_circle = d7_circles(L, meta, suspect)
    flagged = suspect | rs_flag | (depth >= 20 if depth is not None else False)
    stats["spoof_victims"] = spoof_victims(L, meta, flagged, dirty)
    vic = [v for v in stats["spoof_victims"] if v["reading"] == "GNSS interference likely"]
    stats["victims_by_trusted_region"] = dict(Counter((v.get("before") or v.get("after") or {}).get("region", "no trusted position")
                                                      for v in vic))
    stats["spoofed_to"] = dict(Counter(f"{round(v['flagged_center'][0], 1)},{round(v['flagged_center'][1], 1)}" for v in vic
                                       if (v["displacement_km"] or 0) > 50 or (v.get("before") is None and v.get("after") is None)))
    hrs = (L["time"][flagged] // 3600) * 3600
    stats["flagged_by_hour"] = {iso(h): {"positions": int(n), "vessels": int(len(np.unique(L["mmsi"][flagged][hrs == h])))}
                                for h, n in zip(*np.unique(hrs, return_counts=True))}

    c7, zone = port_zones(L, ports())
    ev_rdv = d3_rendezvous(L, meta, suspect | rs_flag, c7, zone, th["rdv_h"], land=land)
    ev_loiter = d4_loiter(L, meta, suspect | rs_flag, c7, zone, th["loiter_h"], land=land)
    cells5 = h3_cells(L["lat"], L["lon"], 5)
    ev_dark, d5_stats = d5_dark(L, meta, cells5, th["gap_h"], t_first, t_last)
    stats.update(d5_stats)
    ev_id, id_stats = d6_identity(meta, L, extra)
    stats.update(id_stats)
    sig, ev_frozen = gnss_signatures(L, U, meta, flagged, regions)
    stats["gnss_by_region"] = sig
    last_day = datetime.fromtimestamp(t_first, timezone.utc).strftime("%Y-%m-%d")
    stats["aircraft"] = aircraft_compare(L, regions, flagged, args.aircraft_days, last_day)

    events = ev_speed + ev_rs + ev_land + ev_cluster + ev_circle + ev_rdv + ev_loiter + ev_dark + ev_id + ev_frozen
    for ev in events:
        ev.setdefault("rule_version", RULES_VERSION)
        ev.setdefault("source", "digitraffic-ais")
        if ev.get("mmsi"):
            ev["labels"] = [label(meta, m) for m in ev["mmsi"]]
    stats["events_by_rule"] = dict(Counter(e["rule"] for e in events))
    stats["d3_breakdown"] = dict(Counter(
        f"{e['context']['setting']}|{'same hull/rafted' if e['context']['same_hull_or_rafted'] else 'service' if e['context']['service_craft_involved'] else 'small' if e['context']['small_private_involved'] else 'other'}"
        for e in ev_rdv))
    stats["d4_breakdown"] = dict(Counter(
        f"{e['context']['setting']}|{'anchored' if e['context']['at_anchor'] else 'not anchored'}|{'small' if e['context']['small_private'] else e['context']['class']}"
        for e in ev_loiter))
    stats["d5_breakdown"] = dict(Counter(
        f"{'stationary' if e['context']['stationary_both_ends'] else 'moved'}|{'small' if e['context']['small_private'] else e['context']['class']}"
        for e in ev_dark))
    stats["d7_land_breakdown"] = dict(Counter("strong" if e["context"]["strong"] else "weak" for e in ev_land))
    # list the events a person should look at first
    def rank(e):
        c = e.get("context", {})
        if e["rule"] == "D3-rendezvous":
            return (c["setting"] != "open water", c["service_craft_involved"] or c["small_private_involved"] or c["same_hull_or_rafted"],
                    -e["numbers"]["hours"])
        if e["rule"] == "D4-loiter":
            return (c["setting"] != "outside ports and anchorages", c["small_private"], -e["numbers"]["hours"])
        if e["rule"] == "D5-dark":
            return (c["small_private"] or not c["has_imo"], c["stationary_both_ends"], -e["numbers"]["gap_h"])
        if e["rule"] == "D7-land":
            return (not c["strong"], -e["numbers"]["max_depth_km"])
        return (0,)
    events.sort(key=lambda e: (e["rule"], rank(e)))
    out_dir = os.path.join(AIS_DIR, "events")
    os.makedirs(out_dir, exist_ok=True)
    tag = f"{days[0]}_{days[-1]}"
    with open(os.path.join(out_dir, f"events_{tag}.jsonl"), "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, default=str) + "\n")
    with open(os.path.join(out_dir, f"summary_{tag}.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=1, default=str)
    if not args.quiet:
        print_summary(stats, events, meta)


def print_summary(stats, events, meta):
    p = print
    p(f"AIS sample {stats['first_utc']} - {stats['last_utc']} ({stats['hours']} h), preset {stats['preset']} {stats['thresholds']}")
    p(f"rows {stats['load']}; vessels with positions {stats['vessels_with_positions']}, with metadata {stats['vessels_with_metadata']}")
    p(f"MMSI kinds {stats['mmsi_kinds']}")
    p(f"classes {stats['classes']}")
    p(f"reporting {stats['reporting']}")
    p(f"positions by region {stats['positions_by_region']}")
    p(f"events by rule {stats['events_by_rule']}")
    for k in ("d3_breakdown", "d4_breakdown", "d5_breakdown", "d7_land_breakdown"):
        p(f"{k} {stats.get(k)}")
    p(f"suspect positions {stats['suspect_positions']}; same-second conflicts {stats.get('same_second_conflicts')}; land {stats.get('land')}")
    p(f"tight groups (>=4 vessels within 50 m) {stats.get('tight_groups_4plus_within_50m')}; stationary shared-fix pairs "
      f"{stats.get('shared_fix_pairs_stationary')}; gaps over threshold {stats.get('gaps_over_threshold')}")
    p(f"reported-speed-impossible positions {stats.get('reported_speed_impossible_positions')}; D7 excursions before merge {stats.get('d7_excursions_before_merge')}")
    p(f"destination classes {stats['destination_classes']}; IMO field {stats.get('imo_field')}")
    p("\nD7 speed episodes by kind and pattern:", dict(Counter((e["kind"], e["context"]["pattern"][:8]) for e in events if e["rule"] == "D7-speed")))
    p(f"\nGNSS-interference victims by trusted region {stats.get('victims_by_trusted_region')}; spoofed-to centres {stats.get('spoofed_to')}")
    p(f"flagged by hour {stats.get('flagged_by_hour')}")
    p("Spoof-affected vessels (trusted position before -> flagged centre):")
    for v in stats.get("spoof_victims", [])[:25]:
        b = v.get("before") or v.get("after") or {}
        p(f"  {v['mmsi']} {v['label']}: {v['flagged_reports']}/{v['reports']} flagged {v['first_flagged']}..{v['last_flagged']}, "
          f"trusted {b.get('lat')},{b.get('lon')} ({b.get('region')}) -> flagged {v['flagged_center']} "
          f"({v['displacement_km']} km), flagged sog {v['flagged_median_sog']}, posAcc {v['posAcc_flagged']}, raim {v['raim_flagged']}, {v.get('reading')}")
    p("\nGNSS by region:")
    for r, v in sorted(stats["gnss_by_region"].items(), key=lambda kv: -kv[1].get("msgs", 0)):
        msgs = v.get("msgs", 0)
        if not msgs:
            p(f"  {r}: {v}")
            continue
        p(f"  {r}: msgs {msgs}, vessels {v.get('vessels')}, posAcc1 {v.get('posAcc1', 0) / msgs:.1%}, raim1 {v.get('raim1', 0) / msgs:.1%}, "
          f"toggles pa/raim {v.get('posacc_toggles', 0)}/{v.get('raim_toggles', 0)} (vessels {v.get('posacc_toggles_vessels', 0)}/{v.get('raim_toggles_vessels', 0)}), "
          f"sog n/a vessels {v.get('sog_na_vessels', 0)}, frozen {v.get('frozen_runs', 0)}, "
          f"cog-hdg>45 {v.get('cog_hdg_gt45', 0)}/{v.get('cog_hdg_checked', 0)}, speed mismatch {v.get('speed_mismatch', 0)}/{v.get('speed_checked', 0)}, "
          f"flagged {v.get('suspect_positions', 0)}, pos n/a {v.get('not_available', 0)}, sog n/a {v.get('sog_na', 0)}, cog n/a {v.get('cog_na', 0)}")
    a = stats.get("aircraft")
    if a:
        p(f"\nAircraft GNSS ({a['days'][0]}..{a['days'][-1]}) by region:")
        for r, v in a["regions"].items():
            share = v["aircraft_bad"] / v["aircraft"] if v.get("aircraft") else None
            p(f"  {r}: aircraft {v.get('aircraft')}, bad share {share if share is None else round(share, 3)}, AIS msgs {v['ais_msgs']}, AIS suspect {v['ais_suspect']}")
        p(f"  cell correlation (aircraft >= 20, AIS msgs >= 100): {a.get('cell_correlation')}")
        p("  top cells by aircraft bad share:")
        for c in a["cells"][:12]:
            p(f"   {c}")
    for rule in ("D7-speed", "D7-reported-speed", "D7-land", "D7-cluster", "D7-shared-fix", "D7-circle", "D3-rendezvous", "D4-loiter", "D5-dark",
                 "D6-identity-change", "D6-imo-shared", "D6-imo-invalid", "D6-destination-text", "GNSS-frozen"):
        ev = [e for e in events if e["rule"] == rule]
        if not ev:
            continue
        p(f"\n{rule}: {len(ev)}")
        for e in ev[:8]:
            p("  ", json.dumps({k: e[k] for k in e if k not in ("source", "rule_version", "rule")}, default=str)[:400])


if __name__ == "__main__":
    main()
