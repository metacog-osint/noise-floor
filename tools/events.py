#!/usr/bin/env python3
"""events.py: the Events and grading lane (v0.1). Observations fuse into events; each event gets five grade fields.

Every input item becomes an observation. Observations on the same UTC day fuse into events (space-time clustering),
the exclusion checks run, and each event is graded on five independent fields: signal_type, support,
localization_error_km, attribution_status and verdict. Every grade is stored with the rule that set it and the
observations behind it. Method and rules: docs/assessment/events.md.

Commands
  python tools/events.py fetch [--days A..B]      public inputs that aren't on disk: the site's daily event files
                                                   (about 25 KB a day) and GFZ Kp (one request). Cached in data/events/.
  python tools/events.py build --days 2025-10-01..2026-10-21   (or --days D1,D2,... or --all)
  python tools/events.py show --day 2026-03-10 [--limit 40]    or   show --event EV-20260310-ab12cd
  python tools/events.py stats

Inputs per UTC day (first found wins):
  anomaly and burst events, SBAS runs   site/data/events/<day>.json, data/events/inputs/<day>.json (fetched), or
                                        data/pnt/analysis/<day>.{anomalies,bursts,sbas}.json
  per-hex daily table (level check)     data/pnt/daily/<day>.parquet or data/pnt/year/<day>.parquet
  announced GPS tests                   data/declared/faa_gps_tests.json (FAA SPANS flight advisories)
  Kp                                    data/events/kp.json (GFZ Potsdam, fetched)

Output: data/events/register.sqlite (gitignored, like all of data/). Times are UTC.
"""
import argparse
import hashlib
import json
import math
import os
import sqlite3
import sys
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import h3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from pnt_analysis import SBAS_AREAS  # noqa: E402  (one source of truth for the SBAS boxes)

VERSION = "events v0.2"
EVENTS_DIR = os.path.join(ROOT, "data", "events")
REGISTER = os.path.join(EVENTS_DIR, "register.sqlite")
INPUTS = os.path.join(EVENTS_DIR, "inputs")
KP_FILE = os.path.join(EVENTS_DIR, "kp.json")
SITE_EVENTS = os.path.join(ROOT, "site", "data", "events")
ANALYSIS = os.path.join(ROOT, "data", "pnt", "analysis")
DAILY_DIRS = [os.path.join(ROOT, "data", "pnt", "daily"), os.path.join(ROOT, "data", "pnt", "year")]
FAA_FILE = os.path.join(ROOT, "data", "declared", "faa_gps_tests.json")
CYGNSS_GRID = os.path.join(ROOT, "data", "cygnss", "grid")
PLACES = os.path.join(ROOT, "site", "data", "places.json")
SITE_URL = "https://noisefloor.theintelligence.company"
KP_URL = "https://kp.gfz.de/app/json/?start={0}T00:00:00Z&end={1}T23:59:59Z&index=Kp"
UA = {"User-Agent": "noise-floor events (research)"}

# ---- parameters (docs/assessment/events.md explains each) ----
REGION_RES = 2            # H3 resolution of the fusion regions (the analysis regions)
FUSE_RING = 1             # same or adjacent region (grid distance <= 1)
FUSE_GAP_MIN = 60         # overlapping, or a gap of at most 60 min (adjacent hours)
EPISODE_GAP_DAYS = 1      # episodes: a region's run of jamming-scale days survives one missing day
MAX_EVENT_KM = 600        # no two member centroids farther apart. A clustering guard, not a physical limit: a little
                          # over the radio horizon from a ground emitter to an aircraft at FL350 (~440 km). Set after
                          # looking at one case (22 Sep 2026; 900 km merged it with bursts ~630 km away): tunable.
LEVEL_MIN_AIRCRAFT = 5    # level check: hexes with >= 5 aircraft (the map's colouring rule)
LEVEL_SHARE = 10.0        #   GPSJam-style hex score 100 x max(bad - 1, 0) / aircraft >= 10 (map's top two classes)
LEVEL_MIN_HEXES = 3       #   at least 3 such res-4 hexes in one res-2 region on the day
STORM_KP = 5.0            # NATURAL: Kp >= 5 (NOAA G1 or stronger), as pnt_analysis labels SBAS storms
KP_PAD_H = 3              # storm effects lag and outlast the 3-hourly index: look 3 h either side
MLAT_GATE = ((8.0, 0.0), (7.0, 40.0), (5.0, 50.0))   # (Kp at least, |geomagnetic latitude| at least, degrees)
DIPOLE_POLE = (80.8, -72.7)   # approximate geomagnetic north pole (centred dipole, 2025 epoch): coarse gate only
SBAS_UNRELIABLE = ("GAGAN (India)", "SouthPAN (Australia/NZ)")   # method card: flag fires most days there
# CYGNSS lane (tools/cygnss_rfi.py, docs/validation/cygnss.md): the values that lane fixed before its validation
CYG_MIN_DDM = 20          # DDMs in a res-3 cell for its noise value to count (PAIR_MIN_DDM there)
CYG_ELEVATED_DB = 1.0     # median noise-floor excess that makes a cell "elevated" (ELEVATED_DB there)
CYG_DROPOUT = 0.5         # share of expected samples missing that makes a cell "drop out" (DROPOUT_SHARE there)
BEAM_LINK_KM = 300        # beam-scale observations link by distance, not by cell adjacency (see fuse)
BEAM_KINDS = ("cygnss_noise",)          # located only to an antenna beam a few hundred km wide
APART_KINDS = ("cygnss_dropout",)       # located by the spacecraft, not the beam: fuse only with their own kind
NO_SUPPORT_KINDS = ("cygnss_dropout",)  # recorded, but never counted toward support

SUPPORT = ("Single-source, unverified", "Partially corroborated", "Multiple sources")
SIGNAL = ("EFFECT", "WARNING", "NATURAL")
ATTRIB = ("none", "candidate", "attributed")
VERDICT = ("open", "benign_natural", "planned", "deliberate_suspected")
TIER_RANK = {None: 0, "minor": 1, "notable": 2, "major": 3}

SOURCES = {   # family -> (source text, sensor?)  Sensors in one family are not independent of each other.
    "adsb": ("adsb.lol daily archive through the PNT processor (ODbL 1.0)", True),
    "cygnss": ("NASA CYGNSS L1 SDR V3.2 DDM noise floor through tools/cygnss_rfi.py (NASA open data)", True),
    "faa": ("FAA SPANS flight advisory, announced GPS test (US public domain)", False),
    "gfz_kp": ("GFZ Potsdam Kp index (CC BY 4.0)", False),
}


# ---------------------------------------------------------------- small helpers
def minutes(hhmm):
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


def iso(day, m):
    return f"{day}T{m // 60:02d}:{m % 60:02d}Z"


def hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def km(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    x = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 12742 * math.asin(min(1.0, math.sqrt(x)))


def mlat(lat, lon):
    """Geomagnetic latitude on a centred dipole. Good to a few degrees: used only as a coarse gate."""
    pl, po = map(math.radians, DIPOLE_POLE)
    la, lo = math.radians(lat), math.radians(lon)
    s = math.sin(la) * math.sin(pl) + math.cos(la) * math.cos(pl) * math.cos(lo - po)
    return math.degrees(math.asin(max(-1.0, min(1.0, s))))


def mean_ll(points):
    """Mean of (lat, lon) points, with a circular mean for longitude (safe across the antimeridian)."""
    if not points:
        return None, None
    lat = sum(p[0] for p in points) / len(points)
    x = sum(math.cos(math.radians(p[1])) for p in points)
    y = sum(math.sin(math.radians(p[1])) for p in points)
    return round(lat, 2), round(math.degrees(math.atan2(y, x)), 2)


def gap(a, b):
    """Minutes between two observations' spans (<= 0 means they overlap)."""
    return max(a["t0"], b["t0"]) - min(a["t1"], b["t1"])


def h(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


class UF:
    def __init__(self, n):
        self.up = list(range(n))

    def root(self, i):
        while self.up[i] != i:
            self.up[i] = self.up[self.up[i]]
            i = self.up[i]
        return i

    def join(self, i, j):
        self.up[self.root(i)] = self.root(j)

    def groups(self):
        g = defaultdict(list)
        for i in range(len(self.up)):
            g[self.root(i)].append(i)
        return list(g.values())


_DISK, _LLC = {}, {}


def disk(cell, k=None):
    k = FUSE_RING if k is None else k
    if (cell, k) not in _DISK:
        _DISK[(cell, k)] = set(h3.grid_disk(cell, k))
    return _DISK[(cell, k)]


def cell_ll(cell):
    if cell not in _LLC:
        _LLC[cell] = h3.cell_to_latlng(cell)
    return _LLC[cell]


def in_area(area, lat, lon):
    a0, a1, o0, o1 = SBAS_AREAS[area]
    return lat is not None and a0 <= lat <= a1 and o0 <= lon <= o1


def parse_days(spec):
    if ".." in spec:
        a, b = (date.fromisoformat(x) for x in spec.split(".."))
        return [(a + timedelta(days=k)).isoformat() for k in range((b - a).days + 1)]
    return [date.fromisoformat(x.strip()).isoformat() for x in spec.split(",") if x.strip()]


# ---------------------------------------------------------------- observations
def obs(day, kind, signal, family, t0, t1, time_res, lat=None, lon=None, cells=(), area=None, measure=None,
        detail=None, ref="", key=""):
    return {"id": "OB-" + h(f"{day}|{kind}|{key}")[:10], "day": day, "kind": kind, "signal_type": signal,
            "family": family, "source": SOURCES[family][0], "sensor": SOURCES[family][1], "t0": t0, "t1": t1,
            "time_res": time_res, "lat": lat, "lon": lon, "cells": sorted(cells), "area": area, "measure": measure,
            "detail": detail or {}, "ref": ref}


def observations_from_events_file(day, ev, ref=""):
    """Anomaly events, burst events and SBAS runs from a site events file (tools/site_days.py format)."""
    out = []
    for i, a in enumerate(ev.get("anomalies") or []):
        measure = "gross" if a["m"] == "jam" else "capable"
        det = {k: a.get(k) for k in ("tier", "regions", "rh", "peak", "excess")}
        det["site_test_tag"] = a.get("test")
        out.append(obs(day, "adsb_anomaly", "EFFECT", "adsb", a["h0"] * 60, a["h1"] * 60 + 59, "hour", a["lat"], a["lon"],
                       a.get("cells") or [h3.latlng_to_cell(a["lat"], a["lon"], REGION_RES)], measure=measure,
                       detail=det, ref=f"{ref}#anomalies[{i}]",
                       key=f"{a['m']}|{a['h0']}|{a['h1']}|{','.join(a.get('cells') or [])}|{a['lat']}|{a['lon']}"))
    for i, b in enumerate(ev.get("bursts") or []):
        det = {"peak_aircraft": b.get("peak"), "regions": b.get("regions"), "site_test_tag": b.get("test")}
        out.append(obs(day, "adsb_burst", "EFFECT", "adsb", minutes(b["t0"]), minutes(b["t1"]), "minute", b["lat"], b["lon"],
                       b.get("cells") or [h3.latlng_to_cell(b["lat"], b["lon"], REGION_RES)], measure="gross",
                       detail=det, ref=f"{ref}#bursts[{i}]",
                       key=f"{b['t0']}|{b['t1']}|{','.join(b.get('cells') or [])}|{b['lat']}|{b['lon']}"))
    for i, s in enumerate(ev.get("sbas") or []):
        state = s["state"].split(" (")[0]
        a0, a1, o0, o1 = SBAS_AREAS.get(s["area"], (None,) * 4)
        lat, lon = (None, None) if a0 is None else ((a0 + a1) / 2, (o0 + o1) / 2)
        det = {"state": state, "input_label": s["state"], "unreliable_area": s["area"] in SBAS_UNRELIABLE}
        out.append(obs(day, "adsb_sbas", "EFFECT", "adsb", s["start"] * 60, s["end"] * 60 + 59, "hour", lat, lon,
                       area=s["area"], measure="capable", detail=det, ref=f"{ref}#sbas[{i}]",
                       key=f"{s['area']}|{s['start']}|{s['end']}|{state}"))
    return out


def level_observations(day, rows, ref=""):
    """Persistent degradation from the per-hex daily table: res-2 regions with >= LEVEL_MIN_HEXES res-4 hexes at the
    map's jamming scale (>= 5 aircraft, score >= 10). The anomaly check compares each region with its own past, so it
    is blind to interference that is there every day; this check is not."""
    regions = defaultdict(lambda: {"jam": [], "hexes": 0, "aircraft": 0, "bad": 0})
    for r in rows:
        n = r["aircraft"]
        if n < LEVEL_MIN_AIRCRAFT:
            continue
        b = r["bad_nacp_live"] if r.get("bad_nacp_live") is not None else r["bad_nacp"]
        x = regions[h3.cell_to_parent(r["h3"], REGION_RES)]
        x["hexes"] += 1
        x["aircraft"] += n
        x["bad"] += b
        if 100 * max(b - 1, 0) / n >= LEVEL_SHARE:
            x["jam"].append((r["lat"], r["lon"]))
    out = []
    for reg, x in sorted(regions.items()):
        if len(x["jam"]) >= LEVEL_MIN_HEXES:
            lat, lon = mean_ll(x["jam"])
            det = {"jam_hexes": len(x["jam"]), "hexes_5plus": x["hexes"],
                   "share": round(100 * x["bad"] / x["aircraft"], 1) if x["aircraft"] else None}
            out.append(obs(day, "adsb_level", "EFFECT", "adsb", 0, 1439, "day", lat, lon, [reg], measure="gross",
                           detail=det, ref=ref, key=reg))
    return out


def cygnss_observations(day, rows, ref=""):
    """CYGNSS cells (H3 res 3, from tools/cygnss_rfi.py) for the day. `cygnss_noise`: CYG_MIN_DDM or more DDMs and a
    median noise-floor excess of at least CYG_ELEVATED_DB. `cygnss_dropout`: half or more of the cell's expected
    samples missing (the lane computes this only for cells with 30+ expected samples, by sub-satellite point). Both
    fuse through the cell's res-2 parent; the grid is daily, so the time resolution is the day."""
    out = []
    for r in rows:
        par = h3.cell_to_parent(r["h3"], REGION_RES)
        rd = lambda k, n=2: None if r.get(k) is None else round(r[k], n)  # noqa: E731
        det = {"res3": r["h3"], "n": r.get("n"), "passes": r.get("passes"), "med_db": rd("med_db"), "p90_db": rd("p90_db"),
               "frac1": rd("frac1"), "land": rd("land"), "dropout": rd("dropout", 3)}
        if (r.get("n") or 0) >= CYG_MIN_DDM and r.get("med_db") is not None and r["med_db"] >= CYG_ELEVATED_DB:
            out.append(obs(day, "cygnss_noise", "EFFECT", "cygnss", 0, 1439, "day", r["lat"], r["lon"], [par],
                           measure="rf", detail=det, ref=ref, key="noise|" + r["h3"]))
        if r.get("dropout") is not None and r["dropout"] >= CYG_DROPOUT:
            out.append(obs(day, "cygnss_dropout", "EFFECT", "cygnss", 0, 1439, "day", r["lat"], r["lon"], [par],
                           measure="dropout", detail=det, ref=ref, key="drop|" + r["h3"]))
    return out


def cygnss_field(rows):
    """Every judged CYGNSS cell of the day (CYG_MIN_DDM+ DDMs), indexed by res-2 parent: {parent: [(lat, lon, med_db)]}.
    Rule S3 reads the field around an ADS-B observation, not just the raised cells."""
    field = defaultdict(list)
    for r in rows:
        if (r.get("n") or 0) >= CYG_MIN_DDM and r.get("med_db") is not None:
            field[h3.cell_to_parent(r["h3"], REGION_RES)].append((r["lat"], r["lon"], r["med_db"]))
    return dict(field)


def local_cygnss(o, field):
    """(median excess, cells) of the judged CYGNSS cells within BEAM_LINK_KM of an observation's anchor points."""
    pts = anchors(o)
    vals = []
    for c in {c2 for c in o["cells"] for c2 in disk(c, 2)}:
        for la, lo, v in field.get(c, ()):
            if min(km(a, (la, lo)) for a in pts) <= BEAM_LINK_KM:
                vals.append(v)
    vals.sort()
    if not vals:
        return None, 0
    m = len(vals) // 2
    return round(vals[m] if len(vals) % 2 else (vals[m - 1] + vals[m]) / 2, 2), len(vals)


_WIN = {}


def _win_min(s):
    """'2026-05-31T06:01Z' -> minutes since the epoch (cached: every day re-reads the same notices)."""
    if s not in _WIN:
        _WIN[s] = int(datetime.strptime(s, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc).timestamp()) // 60
    return _WIN[s]


def faa_observations(day, tests):
    """One WARNING observation per announced test per UTC day, with that day's windows (minutes)."""
    e = _epoch_min(day)
    out = []
    for t in tests:
        wins = []
        for a, b in t.get("windows") or []:
            m0, m1 = _win_min(a) - e, _win_min(b) - e
            if m1 >= 0 and m0 <= 1439:
                wins.append([int(max(0, m0)), int(min(1439, m1))])
        if not wins:
            continue
        radius = max((t.get("radii_nm") or {}).values() or [0]) * 1.852
        det = {"test_id": t["id"], "place": t.get("place", ""), "centre": t["centre"], "radius_km": round(radius, 1),
               "windows": wins, "url": t.get("notice_url") or t.get("url", "")}
        out.append(obs(day, "faa_test", "WARNING", "faa", min(w[0] for w in wins), max(w[1] for w in wins), "minute",
                       t["centre"][0], t["centre"][1], detail=det, ref="faa_gps_tests.json", key=t["id"]))
    return out


class Kp:
    """3-hourly Kp series, indexed by 3-hour slot since the epoch. rows: [(start datetime UTC, kp, status)]."""

    def __init__(self, rows):
        self.rows = sorted(rows)
        self.by = {int(s.timestamp()) // 10800: k for s, k, _ in self.rows}
        self.lo, self.hi = min(self.by), max(self.by)

    def __bool__(self):
        return bool(self.rows)


def load_kp(path=KP_FILE):
    """Kp from a GFZ JSON response, or None."""
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    st = d.get("status") or ["?"] * len(d["Kp"])
    return Kp([(datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc), k, s)
               for t, k, s in zip(d["datetime"], d["Kp"], st)])


def _epoch_min(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()) // 60


def kp_max(kp, day, t0, t1, pad_h=KP_PAD_H):
    """Highest Kp in 3-hour intervals that overlap [t0 - pad, t1 + pad] (minutes on `day`); None without coverage.
    The event's own span must be covered; the padding may run past either end of the series."""
    if not kp:
        return None
    e = _epoch_min(day)
    if (e + t0) // 180 < kp.lo or (e + t1) // 180 > kp.hi:
        return None
    vals = [kp.by[i] for i in range((e + t0 - 60 * pad_h) // 180, (e + t1 + 60 * pad_h) // 180 + 1) if i in kp.by]
    return max(vals) if vals else None


def kp_observations(day, kp):
    """NATURAL observations: runs of 3-hour Kp intervals >= STORM_KP that touch the UTC day, clipped to the day."""
    if not kp:
        return []
    d0 = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    runs = []
    for s, k, st in kp.rows:
        if s < d0 - timedelta(hours=3) or s > d0 + timedelta(days=1):
            continue
        m0 = int((s - d0).total_seconds() // 60)
        if k < STORM_KP or m0 + 180 <= 0 or m0 > 1439:
            continue
        if runs and runs[-1]["m1"] + 1 >= m0:
            runs[-1]["m1"] = m0 + 179
            runs[-1]["kp"].append((s.strftime("%H:%MZ"), k, st))
        else:
            runs.append({"m0": m0, "m1": m0 + 179, "kp": [(s.strftime("%H:%MZ"), k, st)]})
    out = []
    for r in runs:
        t0, t1 = max(0, r["m0"]), min(1439, r["m1"])
        det = {"kp_max": max(k for _, k, _ in r["kp"]), "intervals": r["kp"],
               "status": sorted({st for _, _, st in r["kp"]})}
        out.append(obs(day, "kp_storm", "NATURAL", "gfz_kp", t0, t1, "3h", detail=det, ref="kp.json", key=f"{t0}"))
    return out


def sbas_storm(o, kp):
    """True/False/None: is an SBAS run storm-time (Kp >= STORM_KP within KP_PAD_H h)? None if Kp is unavailable."""
    k = kp_max(kp, o["day"], o["t0"], o["t1"])
    if k is None:
        lab = o["detail"].get("input_label", "")
        return True if "(storm)" in lab else False if "quiet Kp" in lab else None
    return k >= STORM_KP


# ---------------------------------------------------------------- fusion
def consistent(o, f):
    """Distance (km) if H3 observation o overlaps announced test f in time and lies within its widest radius."""
    if not o["cells"] or o["signal_type"] != "EFFECT" or o["lat"] is None or o["kind"] in APART_KINDS:
        return None
    if not any(o["t0"] <= w1 and o["t1"] >= w0 for w0, w1 in f["detail"]["windows"]):
        return None
    d = km((o["lat"], o["lon"]), f["detail"]["centre"])
    return round(d) if d <= f["detail"]["radius_km"] else None


def anchors(o):
    """Points that place an observation for the distance rules: a beam-scale or spacecraft-located cell is its own
    centre; other located observations add the centres of their res-2 cells to their centroid."""
    if o["kind"] in BEAM_KINDS or o["kind"] in APART_KINDS:
        return [(o["lat"], o["lon"])]
    return [(o["lat"], o["lon"])] + [cell_ll(c) for c in o["cells"]]


def linked(o, p):
    """Do two located observations of one UTC day link? Used by the fusion and by rule S3.
      both cell-located   a cell of one within grid distance FUSE_RING of a cell of the other (res 2)
      beam-scale (CYGNSS) the beam cell's centre within BEAM_LINK_KM of the other's centroid or res-2 cell centres
      CYGNSS dropouts     only with other dropouts, centres within BEAM_LINK_KM
    and in every case spans that overlap or are at most FUSE_GAP_MIN minutes apart (day-level spans always overlap)."""
    if not o["cells"] or not p["cells"] or gap(o, p) > FUSE_GAP_MIN:
        return False
    apart = (o["kind"] in APART_KINDS, p["kind"] in APART_KINDS)
    if any(apart):
        return all(apart) and km((o["lat"], o["lon"]), (p["lat"], p["lon"])) <= BEAM_LINK_KM
    if o["kind"] in BEAM_KINDS or p["kind"] in BEAM_KINDS:
        return min(km(a, b) for a in anchors(o) for b in anchors(p)) <= BEAM_LINK_KM
    near = set().union(*(disk(c) for c in o["cells"]))
    return any(c in near for c in p["cells"])


def agree(a, b):
    """Rule S3's pairwise test for observations from two families. Both must link (`linked`). For ADS-B with a
    beam-scale CYGNSS cell, the ADS-B side must be on the 93 m measure (the one the CYGNSS lane was validated against)
    and the judged CYGNSS cells within BEAM_LINK_KM of it must have a median excess of at least CYG_ELEVATED_DB, so
    one raised cell in an otherwise quiet neighbourhood isn't enough (see docs/assessment/events.md, chance rates)."""
    if not linked(a, b):
        return False
    for x, y in ((a, b), (b, a)):
        if y["kind"] in BEAM_KINDS and x["family"] == "adsb":
            med = x["detail"].get("cyg_local_med")
            return x["measure"] == "gross" and med is not None and med >= CYG_ELEVATED_DB
    return True


def fuse(observations):
    """Events for one UTC day, as lists of observation indices. Sensor observations fuse; notices attach.
      located observations  linked by `linked` (cell adjacency, or a distance rule for beam-scale CYGNSS cells).
                            Links are taken closest first, and two groups merge only if every pair of member
                            centroids stays within MAX_EVENT_KM, so a chain of adjacent regions can't grow into one
                            continent-wide event.
      SBAS runs             linked when in the same service area and at most FUSE_GAP_MIN minutes apart.
      announced tests       never fuse anything. Each attaches to every event holding a located EFFECT observation
                            consistent with it (inside a window and within the widest radius); with none, it is its own
                            event.
      Kp storms             never linked: each is its own NATURAL event (Kp is planetary, not local)."""
    n = len(observations)
    uf = UF(n)
    index = defaultdict(list)
    for i, o in enumerate(observations):
        for c in o["cells"]:
            index[c].append(i)
    cand = set()
    for i, o in enumerate(observations):
        if not o["cells"]:
            continue
        ring = 2 if o["kind"] in BEAM_KINDS or o["kind"] in APART_KINDS else FUSE_RING   # 300 km can span 2 rings
        near = set()
        for c in o["cells"]:
            for c2 in disk(c, ring):
                near.update(index.get(c2, ()))
        cand.update((min(i, j), max(i, j)) for j in near if j != i)
    links = []
    for i, j in cand:
        o, p = observations[i], observations[j]
        if linked(o, p):
            links.append((km((o["lat"], o["lon"]), (p["lat"], p["lon"])), max(gap(o, p), 0), i, j))
    pts = {i: [(o["lat"], o["lon"])] for i, o in enumerate(observations)}
    rad = dict.fromkeys(range(n), 0.0)        # farthest member from the group's first point (a cheap bound)
    for _, _, i, j in sorted(links):
        ri, rj = uf.root(i), uf.root(j)
        if ri == rj:
            continue
        d0 = km(pts[ri][0], pts[rj][0])
        if d0 > MAX_EVENT_KM or (d0 + rad[ri] + rad[rj] > MAX_EVENT_KM and
                                 any(km(a, b) > MAX_EVENT_KM for a in pts[ri] for b in pts[rj])):
            continue
        uf.join(ri, rj)                       # rj stays the root and keeps its first point
        rad[rj] = max([rad[rj]] + [km(pts[rj][0], q) for q in pts[ri]])
        pts[rj] = pts[rj] + pts[ri]
    sb = [i for i, o in enumerate(observations) if o["kind"] == "adsb_sbas"]
    for a in sb:
        for b in sb:
            if a < b and observations[a]["area"] == observations[b]["area"] and gap(observations[a], observations[b]) <= FUSE_GAP_MIN:
                uf.join(a, b)
    groups = [g for g in uf.groups() if observations[g[0]]["kind"] != "faa_test"]
    for i, f in enumerate(observations):
        if f["kind"] != "faa_test":
            continue
        hit = [g for g in groups if any(consistent(observations[j], f) is not None for j in g)]
        for g in hit:
            g.append(i)
        if not hit:
            groups.append([i])
    return sorted(groups, key=lambda g: (min(observations[i]["t0"] for i in g), g[0]))


# ---------------------------------------------------------------- grading
def grade(members, day_obs, kp):
    """Five grade fields with rule, reason and basis each, plus the exclusion checks. `members` are the event's
    observations, `day_obs` every observation that day (for context: announced tests, SBAS storm runs)."""
    effects = [o for o in members if o["signal_type"] == "EFFECT"]
    warnings = [o for o in members if o["signal_type"] == "WARNING"]
    naturals = [o for o in members if o["signal_type"] == "NATURAL"]
    h3eff = [o for o in effects if o["cells"]]       # located on H3 regions (every lane but area-wide SBAS)
    ids = lambda xs: [o["id"] for o in xs]  # noqa: E731
    grades, excl, context = {}, {}, []
    pts = [(o["lat"], o["lon"]) for o in (h3eff or effects or warnings) if o["lat"] is not None]
    lat, lon = mean_ll(pts)
    span = effects or members           # an attached notice's windows don't stretch the event
    t0, t1 = min(o["t0"] for o in span), max(o["t1"] for o in span)
    day = members[0]["day"]

    # signal_type
    if effects:
        grades["signal_type"] = ("EFFECT", "T1", f"{len(effects)} observation(s) of measured GNSS degradation", ids(effects))
    elif warnings:
        grades["signal_type"] = ("WARNING", "T2", "an official notice only; no degradation measured with it", ids(warnings))
    else:
        grades["signal_type"] = ("NATURAL", "T3", "a space-weather alert only (Kp)", ids(naturals))

    # support: S3 needs observations from two independent sensor families that link directly (rule `linked`),
    # not merely through a chain of other members
    counting = [o for o in effects if o["sensor"] and o["kind"] not in NO_SUPPORT_KINDS]
    sensor_fams = sorted({o["family"] for o in counting})
    corrob = sorted({o["family"] for o in warnings if o["family"] not in sensor_fams})
    pairs = []
    if len(sensor_fams) >= 2:
        by_fam = defaultdict(list)
        for o in counting:
            by_fam[o["family"]].append(o)
        for x, f1 in enumerate(sensor_fams):
            for f2 in sensor_fams[x + 1:]:
                pairs += [(a, b) for a in by_fam[f1] for b in by_fam[f2] if agree(a, b)]
    dropped = sum(1 for o in effects if o["kind"] in NO_SUPPORT_KINDS)
    note = (f"; {dropped} CYGNSS dropout cell(s) recorded but not counted (placed by the spacecraft, not the beam)"
            if dropped else "")
    if pairs:
        fams = sorted({a["family"] for a, _ in pairs} | {b["family"] for _, b in pairs})
        grades["support"] = (SUPPORT[2], "S3", f"independent sensor families agree in time and space: {' + '.join(fams)} "
                             f"({len(pairs)} agreeing pair(s): linked on the same UTC day, and for ADS-B with CYGNSS a "
                             f"93 m observation whose CYGNSS cells within {BEAM_LINK_KM} km have a median excess >= "
                             f"{CYG_ELEVATED_DB:g} dB){note}", sorted({o["id"] for pr in pairs for o in pr}))
    elif sensor_fams and corrob:
        grades["support"] = (SUPPORT[1], "S2", f"sensor family {' + '.join(sensor_fams)} plus an independent notice that "
                             f"matches in time and place ({', '.join(corrob)}){note}", ids(counting + warnings))
    else:
        if len(sensor_fams) >= 2:
            why = (f"{' and '.join(sensor_fams)} both in the event, but no pair agrees (rule S3: for ADS-B with "
                   f"CYGNSS, a 93 m observation whose CYGNSS cells within {BEAM_LINK_KM} km have a median excess "
                   f">= {CYG_ELEVATED_DB:g} dB, with a raised cell linked to it)")
        elif not sensor_fams:
            why = "one source" if not effects else "only observations that don't count toward support"
        elif len(counting) == 1:
            why = f"one observation from one sensor family ({sensor_fams[0]})"
        else:
            why = (f"one sensor family ({sensor_fams[0]}): its {len(counting)} observations come from one source, so "
                   "they are not independent")
        grades["support"] = (SUPPORT[0], "S1", why + note, ids(members))

    # localization
    grades["localization_error_km"] = (None, "L0", "no fix: no localization method feeds this lane yet", [])

    # exclusion: space weather
    measures = {o["measure"] for o in effects}
    cap_only = bool(effects) and measures == {"capable"}
    natural = None
    if naturals:
        k = max(o["detail"]["kp_max"] for o in naturals)
        excl["space_weather"] = ("alert", "N0", {"kp_max": k, "observations": ids(naturals)})
        natural = "N0"
    elif effects:
        k = kp_max(kp, day, t0, t1)
        sb = [o for o in effects if o["kind"] == "adsb_sbas"]
        storm_runs = [o for o in day_obs if o["kind"] == "adsb_sbas" and sbas_storm(o, kp)]
        if sb and len(sb) == len(effects) and all(sbas_storm(o, kp) for o in sb):
            natural = "N1"
            excl["space_weather"] = ("benign_natural", "N1", {"kp_max": k, "why": "area-wide 10 m loss during Kp >= "
                                     f"{STORM_KP:g} (within {KP_PAD_H} h)", "observations": ids(sb)})
        elif cap_only and h3eff and len(h3eff) == len(effects) and any(
                in_area(o["area"], lat, lon) and gap(o, {"t0": t0, "t1": t1}) <= FUSE_GAP_MIN for o in storm_runs):
            runs = [o for o in storm_runs if in_area(o["area"], lat, lon) and gap(o, {"t0": t0, "t1": t1}) <= FUSE_GAP_MIN]
            natural = "N1"
            context += ids(runs)
            excl["space_weather"] = ("benign_natural", "N1", {"kp_max": k, "why": "10 m-only effect inside an SBAS area "
                                     "flagged at storm time, same or adjacent hour", "observations": ids(runs)})
        elif not measures & {"gross", "capable"}:
            excl["space_weather"] = ("not_applicable", "N-", {"kp_max": k, "why": "CYGNSS evidence only: the noise "
                                     "floor measures RF power, which the Kp rules don't address"})
        elif k is None:
            excl["space_weather"] = ("unknown", "N-", {"why": "Kp unavailable for this time"})
        elif k >= STORM_KP:
            ml = None if lat is None else round(mlat(lat, lon), 1)
            need = next(g for kk, g in MLAT_GATE if k >= kk)
            located = bool(h3eff) and len(h3eff) == len(effects)
            if cap_only and located and ml is not None and abs(ml) >= need:
                natural = "N2"
                excl["space_weather"] = ("benign_natural", "N2", {"kp_max": k, "mlat": ml, "gate_deg": need,
                                         "why": "10 m-only effect during a storm, poleward of the latitude gate"})
            elif "gross" in measures:
                excl["space_weather"] = ("storm_partial", "N-", {"kp_max": k, "why": "storm in progress, but the event "
                                         "includes worse-than-93 m loss, which storms rarely cause in our validation"})
            elif not cap_only:
                excl["space_weather"] = ("storm_partial", "N-", {"kp_max": k, "why": "storm in progress, but the event "
                                         "includes CYGNSS RF evidence, which the Kp rules don't explain"})
            elif not located:
                excl["space_weather"] = ("storm_partial", "N-", {"kp_max": k, "why": "SBAS flag only partly at storm "
                                         "time (rule N1 needs every flagged hour within 3 h of Kp >= 5)"})
            else:
                excl["space_weather"] = ("storm_partial", "N-", {"kp_max": k, "mlat": ml, "gate_deg": need,
                                         "why": "storm in progress, but the event is equatorward of the latitude gate"})
        else:
            excl["space_weather"] = ("not_indicated", "N-", {"kp_max": k})
        if natural in ("N1", "N2"):
            context += [o["id"] for o in day_obs if o["kind"] == "kp_storm" and gap(o, {"t0": t0 - 60 * KP_PAD_H,
                                                                                       "t1": t1 + 60 * KP_PAD_H}) <= 0]

    # exclusion: planned test
    tests = [o for o in day_obs if o["kind"] == "faa_test"]
    planned = None
    match = {}
    for o in h3eff:
        hits = [(f, consistent(o, f)) for f in tests]
        hits = [(f, d) for f, d in hits if d is not None]
        if hits:
            match[o["id"]] = [{"test": f["detail"]["test_id"], "km": d, "obs": f["id"]} for f, d in hits]
    timed = any(o["id"] in match and not o["kind"].startswith("cygnss") for o in effects)
    if effects and h3eff and len(match) == len(effects) and timed:   # CYGNSS cells are timed only to the day, so they
        planned = "P1"                                                # can't on their own place an effect inside a window
        excl["planned_test"] = ("planned", "P1", {"matches": match})
    elif match:
        excl["planned_test"] = ("partial", "P-", {"matches": match, "why": f"{len(match)} of {len(effects)} effect "
                                "observations fall inside an announced test window and radius"})
    elif warnings and not effects:
        planned = "P2"
        excl["planned_test"] = ("declared", "P2", {"tests": [w["detail"]["test_id"] for w in warnings],
                                "why": "an announced test with no ADS-B effect matched to it"})
    elif effects:
        excl["planned_test"] = ("not_indicated", "P-", {"tests_that_day": len(tests)})

    # exclusion: receiver fault and SBAS service
    if any(o["family"] == "adsb" for o in effects):
        excl["receiver_fault"] = ("screened_upstream", "R0", {"why": "the PNT processor drops avionics suspects (peer "
                                  "test) and post-exposure aircraft before counting"})
    sb = [o for o in effects if o["kind"] == "adsb_sbas"]
    hint = None
    if sb and natural is None:
        if all(o["detail"].get("unreliable_area") for o in sb):
            hint = "sbas_equipage"
            excl["sbas_service"] = ("likely_benign", "B2", {"why": "SBAS area where most aircraft don't use the "
                                    "service; the flag fires on most days there (method card)"})
        elif all(sbas_storm(o, kp) is False for o in sb):
            hint = "sbas_service"
            excl["sbas_service"] = ("probable", "B1", {"why": "area-wide 10 m loss with quiet Kp: probable SBAS "
                                    "service problem, not local interference"})

    # verdict (planned outranks natural: a matched notice is more specific than a storm-time heuristic)
    if planned:
        rule = planned
        why = ("every effect observation lies inside an announced test's window and widest radius" if planned == "P1"
               else "the event is an announced test notice")
        grades["verdict"] = ("planned", rule, why, ids(warnings) + ids(h3eff))
    elif natural:
        grades["verdict"] = ("benign_natural", natural, excl["space_weather"][2].get("why", "space-weather alert"),
                             ids(naturals) + context + ids(effects))
    else:
        grades["verdict"] = ("open", "V0", "no exclusion check explains the event, and no interference warning "
                             "corroborates it (deliberate_suspected needs one: rule D1)", ids(effects))
        if not hint:
            sw = excl.get("space_weather", ("",))[0]
            pt = excl.get("planned_test", ("",))[0]
            hint = "storm_partial" if sw == "storm_partial" else "test_partial" if pt == "partial" else None

    # attribution
    if planned == "P1":
        cands = sorted({m["test"] for ms in match.values() for m in ms})
        grades["attribution_status"] = ("candidate", "A1", "announced test(s) consistent in time and place: "
                                        + ", ".join(cands), ids(warnings))
    else:
        grades["attribution_status"] = ("none", "A0", "no candidate source with evidence", [])

    tier = max((o["detail"].get("tier") for o in effects), key=lambda t: TIER_RANK.get(t, 0), default=None)
    em = ("both" if {"gross", "capable"} <= measures else "gross" if "gross" in measures
          else "capable" if "capable" in measures else "rf" if "rf" in measures
          else "dropout" if "dropout" in measures else None)
    return {"grades": grades, "exclusions": excl, "context": sorted(set(context)), "lat": lat, "lon": lon,
            "t0": t0, "t1": t1, "open_hint": hint, "tier": tier, "effect_measure": em}


def label(g):
    v = {k: x[0] for k, x in g["grades"].items()}
    loc = "no fix" if v["localization_error_km"] is None else f"±{v['localization_error_km']:g} km"
    att = v["attribution_status"]
    if att == "candidate":
        att = "candidate: announced test " + g["grades"]["attribution_status"][2].split(": ", 1)[-1]
    return f"{v['signal_type']} · {v['support']} · {loc} · {att} · {v['verdict']}"


def summary(members, g):
    c = Counter(o["kind"] for o in members)
    parts = []
    an =[o for o in members if o["kind"] == "adsb_anomaly"]
    for m in ("gross", "capable"):
        xs = [o for o in an if o["measure"] == m]
        if xs:
            t = max((o["detail"].get("tier") for o in xs), key=lambda t: TIER_RANK.get(t, 0))
            parts.append(f"{len(xs)} {'93 m' if m == 'gross' else '10 m'} anomaly event(s), top tier {t}, peak excess "
                         f"{max(o['detail'].get('excess') or 0 for o in xs):g} pts")
    if c["adsb_burst"]:
        parts.append(f"{c['adsb_burst']} burst(s), peak {max(o['detail']['peak_aircraft'] or 0 for o in members if o['kind'] == 'adsb_burst')} aircraft")
    if c["cygnss_noise"]:
        cy = [o for o in members if o["kind"] == "cygnss_noise"]
        parts.append(f"{len(cy)} CYGNSS cell(s) with a raised noise floor, max median +{max(o['detail']['med_db'] for o in cy):g} dB")
    if c["cygnss_dropout"]:
        parts.append(f"{c['cygnss_dropout']} CYGNSS dropout cell(s)")
    if c["adsb_level"]:
        parts.append(f"{c['adsb_level']} region(s) at jamming scale all day "
                     f"({sum(o['detail']['jam_hexes'] for o in members if o['kind'] == 'adsb_level')} hexes)")
    for o in members:
        if o["kind"] == "adsb_sbas":
            parts.append(f"SBAS {o['detail']['state']} {o['area']} {hhmm(o['t0'])}-{hhmm(o['t1'])}Z")
        elif o["kind"] == "faa_test":
            parts.append(f"announced test {o['detail']['test_id']} ({o['detail']['place']})")
        elif o["kind"] == "kp_storm":
            parts.append(f"Kp {o['detail']['kp_max']:.1f} (GFZ) {hhmm(o['t0'])}-{hhmm(o['t1'])}Z")
    return "; ".join(parts)


def event_id(day, members):
    return f"EV-{day.replace('-', '')}-" + h("|".join(sorted(o["id"] for o in members)))[:8]


def build_day(day, observations, kp, field=None):
    """Fuse one day's observations and grade each event. Returns a list of event dicts. `field` (cygnss_field) lets
    rule S3 read the CYGNSS neighbourhood of each ADS-B observation; the result is kept in the observation's detail."""
    if field:
        for o in observations:
            if o["family"] == "adsb" and o["cells"]:
                o["detail"]["cyg_local_med"], o["detail"]["cyg_local_n"] = local_cygnss(o, field)
    seen = Counter()
    for o in observations:            # identical inputs would collide: keep ids unique and stable
        seen[o["id"]] += 1
        if seen[o["id"]] > 1:
            o["id"] = f"{o['id']}-{seen[o['id']]}"
    events, ids = [], Counter()
    groups = fuse(observations)
    for g in groups:
        members = [observations[i] for i in g]
        gr = grade(members, observations, kp)
        cells = sorted({c for o in members for c in o["cells"]})
        areas = sorted({o["area"] for o in members if o["area"]})
        eid = event_id(day, members)
        ids[eid] += 1
        eid = eid if ids[eid] == 1 else f"{eid}-{ids[eid]}"     # hash collision guard
        events.append({"id": eid, "day": day, "members": [o["id"] for o in members],
                       "cells": cells, "regions": len(cells), "area": ", ".join(areas) or None,
                       "label": label(gr), "summary": summary(members, gr), **gr})
    return events


# ---------------------------------------------------------------- inputs
def events_input(day):
    """(events dict, source path) for a day, or (None, None)."""
    for folder in (SITE_EVENTS, INPUTS):
        p = os.path.join(folder, f"{day}.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f), os.path.relpath(p, ROOT).replace(os.sep, "/")
    src = {k: os.path.join(ANALYSIS, f"{day}.{k}.json") for k in ("anomalies", "bursts", "sbas")}
    if all(os.path.exists(p) for p in src.values()):
        import site_days
        loaded = {}
        for k, p in src.items():
            with open(p, encoding="utf-8") as f:
                loaded[k] = json.load(f)
        return site_days.events(day, loaded["anomalies"], loaded["bursts"], loaded["sbas"]), "data/pnt/analysis"
    return None, None


def level_input(day):
    for folder in DAILY_DIRS:
        p = os.path.join(folder, f"{day}.parquet")
        if os.path.exists(p):
            import pyarrow.parquet as pq
            cols = ["h3", "lat", "lon", "aircraft", "bad_nacp"]
            names = pq.read_schema(p).names
            cols += ["bad_nacp_live"] if "bad_nacp_live" in names else []
            return pq.read_table(p, columns=cols).to_pylist(), os.path.relpath(p, ROOT).replace(os.sep, "/")
    return None, None


def cygnss_input(day):
    p = os.path.join(CYGNSS_GRID, f"{day}.r3.parquet")
    if not os.path.exists(p):
        return None, None
    import pyarrow.parquet as pq
    return pq.read_table(p).to_pylist(), os.path.relpath(p, ROOT).replace(os.sep, "/")


def faa_tests():
    if not os.path.exists(FAA_FILE):
        return None
    with open(FAA_FILE, encoding="utf-8") as f:
        return list(json.load(f).get("tests", {}).values())


def available_days():
    days = set()
    for folder in (SITE_EVENTS, INPUTS):
        if os.path.isdir(folder):
            days |= {n[:10] for n in os.listdir(folder) if n.endswith(".json") and n[:4].isdigit() and len(n) == 15}
    if os.path.isdir(ANALYSIS):
        days |= {n[:10] for n in os.listdir(ANALYSIS) if n.endswith(".anomalies.json")}
    for folder in DAILY_DIRS:
        if os.path.isdir(folder):
            days |= {n[:10] for n in os.listdir(folder) if n.endswith(".parquet") and n.count(".") == 1}
    return sorted(days)


# ---------------------------------------------------------------- register
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS day_inputs(day TEXT PRIMARY KEY, events_src TEXT, level_src TEXT, n_anomalies INT,
  n_bursts INT, n_sbas INT, n_level INT, n_tests INT, n_kp INT, kp TEXT, built_at TEXT, cygnss_src TEXT,
  n_cygnss INT, n_cygnss_dropout INT);
CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY, day TEXT, kind TEXT, signal_type TEXT, family TEXT,
  source TEXT, sensor INT, start_utc TEXT, end_utc TEXT, time_res TEXT, lat REAL, lon REAL, cells TEXT, area TEXT,
  measure TEXT, detail TEXT, ref TEXT);
CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, day TEXT, start_utc TEXT, end_utc TEXT, lat REAL, lon REAL,
  cells TEXT, regions INT, area TEXT, signal_type TEXT, support TEXT, localization_error_km REAL,
  attribution_status TEXT, verdict TEXT, open_hint TEXT, effect_measure TEXT, tier TEXT, label TEXT, summary TEXT,
  episode_id TEXT, episode_days INT, episode_index INT);
CREATE TABLE IF NOT EXISTS event_observations(event_id TEXT, observation_id TEXT, role TEXT,
  PRIMARY KEY(event_id, observation_id, role));
CREATE TABLE IF NOT EXISTS grades(event_id TEXT, field TEXT, value TEXT, rule TEXT, reason TEXT, basis TEXT,
  PRIMARY KEY(event_id, field));
CREATE TABLE IF NOT EXISTS exclusions(event_id TEXT, cause TEXT, result TEXT, rule TEXT, evidence TEXT,
  PRIMARY KEY(event_id, cause));
CREATE TABLE IF NOT EXISTS episodes(id TEXT PRIMARY KEY, region TEXT, first_day TEXT, last_day TEXT, days INT,
  events INT, lat REAL, lon REAL);
CREATE INDEX IF NOT EXISTS ev_day ON events(day);
CREATE INDEX IF NOT EXISTS ob_day ON observations(day);
CREATE INDEX IF NOT EXISTS ob_kind ON observations(kind);
CREATE INDEX IF NOT EXISTS eo_obs ON event_observations(observation_id);
"""


def connect(path=None):
    path = path or REGISTER
    os.makedirs(os.path.dirname(path), exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")       # far fewer syncs: the register lives on a USB drive
    db.execute("PRAGMA synchronous=NORMAL")
    db.executescript(SCHEMA)
    have = {r[1] for r in db.execute("PRAGMA table_info(day_inputs)")}
    for col, typ in (("cygnss_src", "TEXT"), ("n_cygnss", "INT"), ("n_cygnss_dropout", "INT")):
        if col not in have:                       # registers built by v0.1
            db.execute(f"ALTER TABLE day_inputs ADD COLUMN {col} {typ}")
    return db


def write_day(db, day, observations, events, inputs):
    old = [r[0] for r in db.execute("SELECT id FROM events WHERE day=?", (day,))]
    for t in ("event_observations", "grades", "exclusions"):
        db.executemany(f"DELETE FROM {t} WHERE event_id=?", [(i,) for i in old])
    db.execute("DELETE FROM events WHERE day=?", (day,))
    db.execute("DELETE FROM observations WHERE day=?", (day,))
    db.executemany("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        (o["id"], day, o["kind"], o["signal_type"], o["family"], o["source"], int(o["sensor"]), iso(day, o["t0"]),
         iso(day, o["t1"]), o["time_res"], o["lat"], o["lon"], json.dumps(o["cells"]), o["area"], o["measure"],
         json.dumps(o["detail"], ensure_ascii=False), o["ref"]) for o in observations])
    for e in events:
        g = {k: v[0] for k, v in e["grades"].items()}
        db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            e["id"], day, iso(day, e["t0"]), iso(day, e["t1"]), e["lat"], e["lon"], json.dumps(e["cells"]), e["regions"],
            e["area"], g["signal_type"], g["support"], g["localization_error_km"], g["attribution_status"], g["verdict"],
            e["open_hint"], e["effect_measure"], e["tier"], e["label"], e["summary"], None, None, None))
        db.executemany("INSERT OR IGNORE INTO event_observations VALUES (?,?,?)",
                       [(e["id"], o, "member") for o in e["members"]] + [(e["id"], o, "context") for o in e["context"]])
        db.executemany("INSERT INTO grades VALUES (?,?,?,?,?,?)", [
            (e["id"], k, None if v[0] is None else str(v[0]), v[1], v[2], json.dumps(v[3])) for k, v in e["grades"].items()])
        db.executemany("INSERT INTO exclusions VALUES (?,?,?,?,?)", [
            (e["id"], k, v[0], v[1], json.dumps(v[2], ensure_ascii=False)) for k, v in e["exclusions"].items()])
    n = Counter(o["kind"] for o in observations)
    db.execute("INSERT OR REPLACE INTO day_inputs (day, events_src, level_src, n_anomalies, n_bursts, n_sbas, n_level, "
               "n_tests, n_kp, kp, built_at, cygnss_src, n_cygnss, n_cygnss_dropout) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        day, inputs.get("events_src"), inputs.get("level_src"), n["adsb_anomaly"], n["adsb_burst"], n["adsb_sbas"],
        n["adsb_level"], n["faa_test"], n["kp_storm"], inputs.get("kp"), datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        inputs.get("cygnss_src"), n["cygnss_noise"], n["cygnss_dropout"]))


def episodes(db):
    """Persistence, per region. An episode is a run of register days on which one res-2 region is at jamming scale
    all day (a level observation), allowing gaps of up to EPISODE_GAP_DAYS days (flicker at the threshold, or a day
    missing or partial at the source). Each event with a level observation takes the episode of its longest-running
    region so far: episode_index is how many level days that run has reached on the event's day, episode_days the
    run's total. Per-region runs can't chain across a continent the way linking whole events would. Rewrites the
    episodes table and columns."""
    days = [r[0] for r in db.execute("SELECT day FROM day_inputs ORDER BY day")]
    pos = {d: i for i, d in enumerate(days)}
    per_region = defaultdict(list)
    for cells, day, eid in db.execute("SELECT o.cells, o.day, eo.event_id FROM observations o JOIN event_observations eo "
                                      "ON eo.observation_id=o.id AND eo.role='member' WHERE o.kind='adsb_level'"):
        per_region[json.loads(cells)[0]].append((pos[day], day, eid))
    db.execute("DROP TABLE IF EXISTS episodes")
    db.execute("CREATE TABLE episodes(id TEXT PRIMARY KEY, region TEXT, first_day TEXT, last_day TEXT, days INT, "
               "events INT, lat REAL, lon REAL)")
    db.execute("UPDATE events SET episode_id=NULL, episode_days=NULL, episode_index=NULL WHERE episode_id IS NOT NULL")
    best = {}                                   # event id -> (index so far, total, episode id)
    for region, rows in per_region.items():
        rows.sort()
        run_list, cur = [], []
        for r in rows:
            if cur and r[0] - cur[-1][0] > EPISODE_GAP_DAYS + 1:
                run_list.append(cur)
                cur = []
            cur.append(r)
        run_list.append(cur)
        la, lo = h3.cell_to_latlng(region)
        for run in run_list:
            ep = f"EP-{run[0][1].replace('-', '')}-{h(region)[:6]}"
            db.execute("INSERT INTO episodes VALUES (?,?,?,?,?,?,?,?)", (ep, region, run[0][1], run[-1][1],
                       len({r[1] for r in run}), len({r[2] for r in run}), round(la, 2), round(lo, 2)))
            for k, (_, _, eid) in enumerate(run, 1):
                cand = (k, len(run), ep)
                if cand > best.get(eid, (0, 0, "")):
                    best[eid] = cand
    db.executemany("UPDATE events SET episode_id=?, episode_days=?, episode_index=? WHERE id=?",
                   [(ep, total, k, eid) for eid, (k, total, ep) in best.items()])


def cmd_build(a):
    global MAX_EVENT_KM
    MAX_EVENT_KM = a.max_km or MAX_EVENT_KM
    days = available_days() if a.all else parse_days(a.days)
    kp = load_kp()
    tests = faa_tests()
    db = connect()
    tot = Counter()
    for day in days:
        ev, ev_src = events_input(day)
        rows, lv_src = level_input(day)
        cyg, cy_src = cygnss_input(day)
        if ev is None and rows is None:
            print(f"{day}: no inputs, skipped")
            continue
        observations = []
        if ev is not None:
            observations += observations_from_events_file(day, ev, ev_src)
        if rows is not None:
            observations += level_observations(day, rows, lv_src)
        if cyg is not None:
            observations += cygnss_observations(day, cyg, cy_src)
        observations += faa_observations(day, tests if tests is not None else ev.get("tests", []) if ev else [])
        observations += kp_observations(day, kp)
        kmax = kp_max(kp, day, 0, 1439, pad_h=0)
        events = build_day(day, observations, kp, cygnss_field(cyg) if cyg is not None else None)
        write_day(db, day, observations, events, {"events_src": ev_src, "level_src": lv_src, "cygnss_src": cy_src,
                                                   "kp": None if kmax is None else f"max {kmax:.1f}"})
        tot["days"] += 1
        tot["observations"] += len(observations)
        tot["events"] += len(events)
        if a.verbose:
            print(f"{day}: {len(observations)} observations -> {len(events)} events")
    episodes(db)
    db.execute("INSERT OR REPLACE INTO meta VALUES ('version', ?)", (VERSION,))
    db.execute("INSERT OR REPLACE INTO meta VALUES ('built_at', ?)", (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),))
    db.execute("INSERT OR REPLACE INTO meta VALUES ('parameters', ?)", (json.dumps({
        "REGION_RES": REGION_RES, "FUSE_RING": FUSE_RING, "FUSE_GAP_MIN": FUSE_GAP_MIN, "MAX_EVENT_KM": MAX_EVENT_KM, "LEVEL_MIN_AIRCRAFT": LEVEL_MIN_AIRCRAFT,
        "LEVEL_SHARE": LEVEL_SHARE, "LEVEL_MIN_HEXES": LEVEL_MIN_HEXES, "STORM_KP": STORM_KP, "KP_PAD_H": KP_PAD_H,
        "MLAT_GATE": MLAT_GATE, "EPISODE_GAP_DAYS": EPISODE_GAP_DAYS, "CYG_MIN_DDM": CYG_MIN_DDM,
        "CYG_ELEVATED_DB": CYG_ELEVATED_DB, "CYG_DROPOUT": CYG_DROPOUT, "BEAM_LINK_KM": BEAM_LINK_KM, "DIPOLE_POLE": DIPOLE_POLE, "SBAS_UNRELIABLE": SBAS_UNRELIABLE}),))
    db.commit()
    print(f"built {tot['days']} day(s): {tot['observations']} observations, {tot['events']} events -> "
          f"{os.path.relpath(REGISTER, ROOT)}" + ("" if kp else "  (no Kp file: run `fetch` first)"))


# ---------------------------------------------------------------- fetch
def cmd_fetch(a):
    os.makedirs(INPUTS, exist_ok=True)
    with urllib.request.urlopen(urllib.request.Request(f"{SITE_URL}/data/gnss/days.json", headers=UA), timeout=60) as r:
        listed = [d["day"] for d in json.load(r)]
    want = set(parse_days(a.days)) if a.days else set(listed)
    todo = [d for d in listed if d in want and not os.path.exists(os.path.join(SITE_EVENTS, f"{d}.json"))
            and (a.refresh or not os.path.exists(os.path.join(INPUTS, f"{d}.json")))]

    def get(day):
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{SITE_URL}/data/events/{day}.json", headers=UA), timeout=60) as r:
                data = r.read()
            json.loads(data)
            with open(os.path.join(INPUTS, f"{day}.json"), "wb") as f:
                f.write(data)
            return len(data)
        except Exception as e:  # a day without an events file (e.g. a gap at the source) is not fatal
            print(f"  {day}: {e}")
            return 0

    with ThreadPoolExecutor(4) as ex:
        sizes = list(ex.map(get, todo))
    print(f"events files: {len(listed)} days listed; fetched {sum(1 for s in sizes if s)} ({sum(sizes) / 1e6:.1f} MB)")
    d0 = (date.fromisoformat(min(listed)) - timedelta(days=2)).isoformat()
    d1 = (datetime.now(timezone.utc).date()).isoformat()
    with urllib.request.urlopen(urllib.request.Request(KP_URL.format(d0, d1), headers=UA), timeout=60) as r:
        kp = json.load(r)
    kp["fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    kp["source"] = "GFZ Potsdam Kp index (CC BY 4.0), kp.gfz.de"
    with open(KP_FILE, "w", encoding="utf-8") as f:
        json.dump(kp, f)
    st = Counter(kp.get("status") or [])
    print(f"Kp: {len(kp['Kp'])} intervals {kp['datetime'][0][:10]} to {kp['datetime'][-1][:16]}Z; status {dict(st)}")


# ---------------------------------------------------------------- show / stats
_PL = None


def near(lat, lon):
    global _PL
    if lat is None:
        return ""
    if _PL is None:
        try:
            with open(PLACES, encoding="utf-8") as f:
                _PL = [(p[0], p[1], p[2]) for p in json.load(f)["places"]]
        except Exception:
            _PL = []
    if not _PL:
        return ""
    name, d = min(((n, km((lat, lon), (a, b))) for n, a, b in _PL), key=lambda x: x[1])
    return f"{d:.0f} km from {name}"


def fmt_ll(lat, lon):
    if lat is None:
        return "global"
    return f"{abs(lat):.2f}{'N' if lat >= 0 else 'S'} {abs(lon):.2f}{'E' if lon >= 0 else 'W'}"


def describe_obs(r):
    kind, measure, det = r["kind"], r["measure"], json.loads(r["detail"])
    t = f"{r['start_utc'][11:16]}-{r['end_utc'][11:16]}Z" if r["time_res"] != "day" else "whole day"
    if kind == "adsb_anomaly":
        s = (f"{'93 m' if measure == 'gross' else '10 m'} anomaly, {det['tier']}, peak {det['peak']}% "
             f"(+{det['excess']} pts over baseline), {det['regions']} region(s)")
    elif kind == "adsb_burst":
        s = f"burst, peak {det['peak_aircraft']} aircraft with a gross-bad report, {det['regions']} region(s)"
    elif kind == "adsb_level":
        s = f"jamming scale all day: {det['jam_hexes']} of {det['hexes_5plus']} hexes, share {det['share']}%"
    elif kind == "adsb_sbas":
        s = f"SBAS {det['state']}, {r['area']}" + (" (unreliable area)" if det.get("unreliable_area") else "")
    elif kind == "cygnss_noise":
        s = (f"CYGNSS noise floor, median +{det['med_db']} dB (p90 +{det['p90_db']}), {det['n']} DDMs on {det['passes']} "
             f"pass(es), res-3 cell")
    elif kind == "cygnss_dropout":
        s = f"CYGNSS data dropout: {100 * det['dropout']:.0f}% of expected samples missing (by sub-satellite point)"
    elif kind == "faa_test":
        s = f"announced test {det['test_id']}, {det['place']}, radius {det['radius_km']:.0f} km, windows " + ", ".join(
            f"{hhmm(a)}-{hhmm(b)}Z" for a, b in det["windows"])
    else:
        s = f"Kp max {det['kp_max']:.1f} ({', '.join(det['status'])})"
    return f"{r['id']}  {r['signal_type']:<7} {t:<13} {s}  @ {fmt_ll(r['lat'], r['lon'])}"


def show_event(db, eid, full=True):
    db.row_factory = sqlite3.Row
    e = db.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
    if not e:
        print(f"no event {eid}")
        return
    print(f"{e['id']}  {e['start_utc'][:10]} {e['start_utc'][11:16]}-{e['end_utc'][11:16]} UTC")
    print(f"  {e['label']}")
    where = (f"{e['regions']} H3 res-2 region(s) around {fmt_ll(e['lat'], e['lon'])}" if e["regions"] else
             e["area"] or fmt_ll(e["lat"], e["lon"]))
    pl = near(e["lat"], e["lon"])
    print(f"  where: {where}" + (f" ({pl})" if pl and e["regions"] else ""))
    print(f"  what:  {e['summary']}")
    if e["episode_id"]:
        print(f"  episode: {e['episode_id']}, day {e['episode_index']} of {e['episode_days']}")
    if not full:
        return
    rows = db.execute("SELECT o.*, eo.role FROM event_observations eo JOIN observations o ON o.id=eo.observation_id "
                      "WHERE eo.event_id=? ORDER BY eo.role DESC, o.start_utc", (eid,)).fetchall()
    print(f"  evidence ({sum(1 for r in rows if r['role'] == 'member')} observations"
          + (f", {sum(1 for r in rows if r['role'] == 'context')} context" if any(r["role"] == "context" for r in rows) else "")
          + "):")
    for r in rows:
        print(f"    {'+' if r['role'] == 'member' else 'ctx'} {describe_obs(r)}")
    print("  grades:")
    for g in db.execute("SELECT * FROM grades WHERE event_id=?", (eid,)):
        basis = json.loads(g["basis"])
        b = f"  [basis: {', '.join(basis[:4])}{' +%d' % (len(basis) - 4) if len(basis) > 4 else ''}]" if basis else ""
        print(f"    {g['field']:<22} = {str(g['value']):<26} rule {g['rule']}: {g['reason']}{b}")
    print("  exclusion checks:")
    for x in db.execute("SELECT * FROM exclusions WHERE event_id=?", (eid,)):
        ev = json.loads(x["evidence"])
        brief = {k: v for k, v in ev.items() if k not in ("matches", "observations")}
        if "matches" in ev:
            brief["matches"] = sorted({m["test"] + f" ({m['km']} km)" for ms in ev["matches"].values() for m in ms})
        print(f"    {x['cause']:<15} {x['result']:<18} rule {x['rule']}  {json.dumps(brief, ensure_ascii=False)}")


def cmd_show(a):
    db = connect()
    if a.event:
        show_event(db, a.event)
        return
    db.row_factory = sqlite3.Row
    inp = db.execute("SELECT * FROM day_inputs WHERE day=?", (a.day,)).fetchone()
    if not inp:
        print(f"{a.day}: not in the register (run build)")
        return
    print(f"{a.day} (UTC). Inputs: events {inp['events_src']}; level {inp['level_src']}; {inp['n_anomalies']} anomaly "
          f"events, {inp['n_bursts']} bursts, {inp['n_sbas']} SBAS runs, {inp['n_level']} level regions, "
          f"{inp['n_tests']} announced tests, {inp['n_kp']} Kp storm runs; Kp {inp['kp'] or 'unavailable'}"
          + (f"; CYGNSS {inp['n_cygnss']} raised cells, {inp['n_cygnss_dropout']} dropout cells" if inp["cygnss_src"] else ""))
    evs = db.execute("SELECT * FROM events WHERE day=?", (a.day,)).fetchall()
    c = Counter((e["signal_type"], e["verdict"]) for e in evs)
    print(f"{len(evs)} events: " + ", ".join(f"{k[0]}/{k[1]} {n}" for k, n in sorted(c.items())))
    order = sorted(evs, key=lambda e: (SIGNAL.index(e["signal_type"]), e["effect_measure"] not in ("gross", "both"),
                                       -TIER_RANK.get(e["tier"], 0), -(e["regions"] or 0), e["start_utc"]))
    for e in order[:a.limit]:
        print()
        show_event(db, e["id"], full=a.full)
    if len(order) > a.limit:
        print(f"\n... {len(order) - a.limit} more (use --limit)")


def cmd_stats(a):
    db = connect()
    n = db.execute("SELECT COUNT(*), MIN(day), MAX(day), COUNT(DISTINCT day) FROM events").fetchone()
    no = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    print(f"register: {n[0]} events from {no} observations, {n[3]} days ({n[1]} to {n[2]}, UTC)\n")
    print("observations by kind:", dict(db.execute("SELECT kind, COUNT(*) FROM observations GROUP BY kind ORDER BY 2 DESC")))
    for field, values in (("signal_type", SIGNAL), ("support", SUPPORT), ("attribution_status", ATTRIB), ("verdict", VERDICT)):
        c = dict(db.execute(f"SELECT {field}, COUNT(*) FROM events GROUP BY {field}"))
        print(f"{field:<20} " + "  ".join(f"{v}: {c.get(v, 0)}" for v in values))
    loc = db.execute("SELECT COUNT(*) FROM events WHERE localization_error_km IS NOT NULL").fetchone()[0]
    print(f"{'localization':<20} with a fix: {loc}  null: {n[0] - loc}")
    print("\nsignal_type x verdict:")
    for s in SIGNAL:
        c = dict(db.execute("SELECT verdict, COUNT(*) FROM events WHERE signal_type=? GROUP BY verdict", (s,)))
        print(f"  {s:<8} " + "  ".join(f"{v}: {c.get(v, 0)}" for v in VERDICT))
    print("\nEFFECT events by measure and verdict:")
    for m in ("gross", "both", "capable", "rf", "dropout"):
        c = dict(db.execute("SELECT verdict, COUNT(*) FROM events WHERE signal_type='EFFECT' AND effect_measure=? "
                            "GROUP BY verdict", (m,)))
        print(f"  {m:<8} " + "  ".join(f"{v}: {c.get(v, 0)}" for v in VERDICT))
    s3 = db.execute("SELECT day, COUNT(*) FROM events WHERE support='Multiple sources' GROUP BY day").fetchall()
    if s3:
        print("Multiple sources by day:", dict(s3))
    print("open events by hint:", dict(db.execute("SELECT COALESCE(open_hint, 'none'), COUNT(*) FROM events "
                                                  "WHERE verdict='open' GROUP BY 1 ORDER BY 2 DESC")))
    print("\nby month (UTC):  events | EFFECT WARNING NATURAL | open benign_natural planned deliberate_suspected | "
          "single partial multiple")
    for (m,) in db.execute("SELECT DISTINCT substr(day,1,7) FROM events ORDER BY 1"):
        def cnt(field):
            return dict(db.execute(f"SELECT {field}, COUNT(*) FROM events WHERE substr(day,1,7)=? GROUP BY {field}", (m,)))
        s, v, p = cnt("signal_type"), cnt("verdict"), cnt("support")
        tot = sum(s.values())
        print(f"  {m}  {tot:>6} | " + " ".join(f"{s.get(x, 0):>6}" for x in SIGNAL) + " | "
              + " ".join(f"{v.get(x, 0):>5}" for x in VERDICT) + " | " + " ".join(f"{p.get(x, 0):>6}" for x in SUPPORT))
    ne = db.execute("SELECT COUNT(*), COUNT(DISTINCT region) FROM episodes").fetchone()
    print(f"\nepisodes (a res-2 region at jamming scale on consecutive days, 1-day gaps allowed): {ne[0]} in {ne[1]} regions")
    for lo_, hi_ in ((1, 1), (2, 6), (7, 29), (30, 89), (90, 9999)):
        n_ = db.execute("SELECT COUNT(*) FROM episodes WHERE days BETWEEN ? AND ?", (lo_, hi_)).fetchone()[0]
        print(f"  {lo_}{'-' + str(hi_) if hi_ != lo_ and hi_ < 9999 else '+' if hi_ >= 9999 else ''} days: {n_}")
    print("  longest:")
    for r in db.execute("SELECT id, first_day, last_day, days, lat, lon FROM episodes ORDER BY days DESC LIMIT 8"):
        print(f"    {r[0]}  {r[1]}..{r[2]}  {r[3]} days, region centre {fmt_ll(r[4], r[5])}")
    # cross-check: the planned-test rule against the site's own test tags (tools/site_days.py annotate)
    matched = set()
    for (ev,) in db.execute("SELECT evidence FROM exclusions WHERE cause='planned_test' AND result IN ('planned','partial')"):
        matched |= set(json.loads(ev).get("matches", {}))
    tagged = agree = mine = 0
    for oid, det in db.execute("SELECT id, detail FROM observations WHERE kind IN ('adsb_anomaly','adsb_burst')"):
        tag, hit = bool(json.loads(det).get("site_test_tag")), oid in matched
        tagged += tag
        mine += hit
        agree += tag and hit
    print(f"\nplanned-test cross-check (anomalies and bursts): tagged on the site {tagged}, matched by rule P1/P- {mine}, "
          f"both {agree}")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--days")
    f.add_argument("--refresh", action="store_true", help="fetch days already cached too")
    b = sub.add_parser("build")
    g = b.add_mutually_exclusive_group(required=True)
    g.add_argument("--days")
    g.add_argument("--all", action="store_true")
    b.add_argument("-v", "--verbose", action="store_true")
    b.add_argument("--max-km", type=float, help=f"event diameter cap (default {MAX_EVENT_KM:g} km)")
    s = sub.add_parser("show")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--day")
    g.add_argument("--event")
    s.add_argument("--limit", type=int, default=25)
    s.add_argument("--full", action="store_true", help="evidence and grade reasons for every event of the day")
    sub.add_parser("stats")
    a = ap.parse_args()
    {"fetch": cmd_fetch, "build": cmd_build, "show": cmd_show, "stats": cmd_stats}[a.cmd](a)


if __name__ == "__main__":
    main()
