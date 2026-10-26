#!/usr/bin/env python3
"""dark_match.py: dark ships (D1) and phantom tracks (D2): Sentinel-1 detections matched with Finland's open AIS.

Pre-registered test and its rules: docs/validation/dark-ships-baltic.md (amendment 1 included). The detector is
tools/ship_detect.py, called through its own functions with the frozen setting (k = 6, 10 dB contrast floor, ghosts
dropped, 20 m pixels, Natural Earth land with a 400 m buffer), so the detector code is unchanged and the sea mask is at
hand for scoring.

For each Sentinel-1 pass over the scored regions:
  1. read each region in tiles (1 deg lon x 0.7 deg lat, 0.04 deg padding) and detect; keep detections and AIS vessels
     whose point lies in the tile core, in a scored region, on sea at least 1.5 km from the land mask;
  2. AIS position at the acquisition: linear interpolation between reports within +-10 min on both sides, or the single
     nearest report within +-2 min; otherwise "unknown" (also when ais_detect lists the vessel as a spoofing victim with
     a flagged span covering the acquisition, or when the segment implies more than 60 kn);
  3. match detections to known vessels one to one, nearest first, within 1 km; a detection within 1 km of an unknown
     vessel's nearest report isn't dark;
  4. fixed structures: covered by at least two passes and detected within 100 m in at least 60% of them.

Amendment 3 (fixed objects and ghosts, both decided on development data only):
  - a fixed-object map from every Sentinel-1 pass over the scored regions from 10 to 23 Oct 2026 (`clutter`): a place
    detected (within FIXED_M) in at least CLUTTER_SHARE of the passes whose scoring area covers it, with at least
    CLUTTER_MIN_COVER covering passes, is a fixed object (rocks, beacons, buoys, aquaculture); detections there aren't
    counted as ships or dark ships;
  - azimuth ghosts: an unmatched detection whose offset from a matched detection, or from a known AIS vessel of 50 m or
    more, is GHOST_ALONG_KM along the satellite track and within GHOST_ACROSS_M across it is a ghost, not a dark ship.

Variants (amendment 2): A is the pre-registered setting (Natural Earth land only). B adds OpenStreetMap land polygons
(data/ref/osm/baltic_land.json, ODbL) through the detector's own extra-land step, because Natural Earth misses the
skerries of the Archipelago Sea and the Gulf of Finland. Everything else is identical; both are scored.

  python tools/dark_match.py run --variant A|B --scenes <frame id prefix> [...] --days 2026-10-24 [--summary <json>]
  python tools/dark_match.py score --variant A|B --set dev        (or --set heldout; reads private/maritime/dark/<variant>/)
  python tools/dark_match.py clutter --variant B --start 2026-10-10 --end 2026-10-23   (fixed-object map; resumable)

Outputs (private, gitignored): private/maritime/dark/<pass>.json with every detection and vessel; score prints H1-H3.
Positions and identities stay private; only counts and the verdict are published.
"""
import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import ais_detect as A  # noqa: E402
import ship_detect as SD  # noqa: E402

OUT = os.path.join(ROOT, "private", "maritime", "dark")
RULES = "dark-0.1 (pre-registered 26 Oct 2026)"
SCORED = ["Gulf of Finland 22.5-27E", "Gulf of Finland east of 27E", "Archipelago Sea and Aland"]
BOXES = {n: b for n, b in A.REGIONS}
TILE_LON, TILE_LAT, PAD = 1.0, 0.7, 0.04
RES = 20.0
DETECT = dict(k=6.0, buffer_m=400.0, min_len=30, ghosts="drop", min_contrast_db=10.0)
EDGE_M = 1500.0
MATCH_M = 1000.0
WIN_S, NEAR_S, SCENE_S = 600, 120, 1800
MAX_KN = 60.0
FIXED_M, FIXED_SHARE = 100.0, 0.6
SETS = {"dev": ["2026-10-24"], "heldout": ["2026-10-26"]}
CLUTTER_SHARE, CLUTTER_MIN_COVER = 0.5, 4       # amendment 3
GHOST_ALONG_KM, GHOST_ACROSS_M = (3.5, 7.5), 800.0
SCORED_BOX = (59.1, 60.8, 19.0, 30.6)           # lat0, lat1, lon0, lon1: the three scored regions' extent
OSM_LAND = os.path.join(ROOT, "data", "ref", "osm", "baltic_land.json")
_OSM = {}


def osm_land(padded, shape, tr, crs):
    """OpenStreetMap land rasterised onto a tile grid (all touched), or None if the file is missing."""
    if "geoms" not in _OSM:
        if not os.path.exists(OSM_LAND):
            sys.exit(f"variant B needs {OSM_LAND} (see registry row osm-land-polygons)")
        from shapely.geometry import shape as to_shape
        from shapely.strtree import STRtree
        g = json.load(open(OSM_LAND, encoding="utf-8"))["geometries"]
        _OSM["geoms"] = g
        _OSM["tree"] = STRtree([to_shape(x).envelope for x in g])
    from shapely.geometry import box as sbox
    from rasterio.features import rasterize
    from rasterio.warp import transform_geom
    lat0, lat1, lon0, lon1 = padded
    hits = _OSM["tree"].query(sbox(lon0, lat0, lon1, lat1))
    if len(hits) == 0:
        return np.zeros(shape, bool)
    shapes = [(transform_geom("EPSG:4326", crs, _OSM["geoms"][i]), 1) for i in hits]
    return rasterize(shapes, out_shape=shape, transform=tr, fill=0, all_touched=True, dtype="uint8").astype(bool)


def km(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    x = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 12742 * math.asin(min(1.0, math.sqrt(x)))


def tiles(box):
    lat0, lat1, lon0, lon1 = box
    lo = lon0
    while lo < lon1 - 1e-9:
        la = lat0
        while la < lat1 - 1e-9:
            core = (la, min(la + TILE_LAT, lat1), lo, min(lo + TILE_LON, lon1))
            yield core, (core[0] - PAD, core[1] + PAD, core[2] - PAD * 2, core[3] + PAD * 2)
            la += TILE_LAT
        lo += TILE_LON


def in_box(b, lat, lon):
    return b[0] <= lat < b[1] and b[2] <= lon < b[3]


def scored_point(lat, lon):
    return A.region_of(lat, lon) in SCORED


class Tile:
    """One detected tile: transform, scoring mask (sea, valid, at least EDGE_M from non-sea) and its core box."""

    def __init__(self, core, tr, crs, score):
        self.core, self.tr, self.crs, self.score = core, tr, crs, score

    def covers(self, lat, lon):
        if not in_box(self.core, lat, lon) or not scored_point(lat, lon):
            return False
        from rasterio.warp import transform as warp_xy
        xs, ys = warp_xy("EPSG:4326", self.crs, [lon], [lat])
        c, r = int((xs[0] - self.tr.c) / self.tr.a), int((ys[0] - self.tr.f) / self.tr.e)
        H, W = self.score.shape
        return 0 <= r < H and 0 <= c < W and bool(self.score[r, c])


def detect_pass(group, variant="A"):
    """Detections and covered tiles for one acquisition over every scored region."""
    from scipy.ndimage import distance_transform_edt
    dets, cover, bearings = [], [], []
    for name in SCORED:
        for core, padded in tiles(BOXES[name]):
            frames = [f for f in group["frames"] if f["bbox"][0] < padded[3] and f["bbox"][2] > padded[2]
                      and f["bbox"][1] < padded[1] and f["bbox"][3] > padded[0]]
            if not frames:
                continue
            info = {}
            try:
                a, tr, crs, valid = SD.read_pass(frames, padded, RES, info=info)
            except Exception as e:                      # a tile the pass doesn't reach, or a read error
                print(f"  {name} {core}: {type(e).__name__}: {e}")
                continue
            if valid.mean() < 0.02:
                continue
            extra = osm_land(padded, a.shape, tr, crs) if variant == "B" else None
            px, sea = SD.detect_array(a, tr, crs, valid, padded, RES, along_bearing=info.get("along_bearing"),
                                      extra_land=extra, **DETECT)
            if info.get("along_bearing") is not None:
                bearings.append(info["along_bearing"])
            score = sea & (distance_transform_edt(sea) * RES >= EDGE_M)
            t = Tile(core, tr, crs, score)
            ll = SD.to_lonlat([dict(d) for d in px], tr, crs, RES)
            for d in ll:
                if t.covers(d["lat"], d["lon"]):
                    dets.append({"lat": d["lat"], "lon": d["lon"], "length_m": d["length_m"],
                                 "contrast_db": round(10 * math.log10(max(d.get("peak_ratio", 1e-9), 1e-9)), 1),
                                 "region": A.region_of(d["lat"], d["lon"])})
            cover.append(t)
    bearing = sorted(bearings)[len(bearings) // 2] if bearings else None
    return dets, cover, bearing


def spoof_spans(summary_path):
    """MMSI -> [(t0, t1)] flagged spans (epoch s, +-10 min) from an ais_detect summary."""
    spans = {}
    if not summary_path or not os.path.exists(summary_path):
        return spans
    s = json.load(open(summary_path, encoding="utf-8"))
    for v in s.get("spoof_victims", []):
        try:
            t0 = datetime.strptime(v["first_flagged"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
            t1 = datetime.strptime(v["last_flagged"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        except (KeyError, TypeError, ValueError):
            continue
        spans.setdefault(int(v["mmsi"]), []).append((t0 - WIN_S, t1 + WIN_S))
    return spans


def ais_at(days, t, spans):
    """Each vessel's position at acquisition time t (epoch s): (known, lat, lon, info) per MMSI heard within +-30 min."""
    L, _, _ = A.load_locations(days, since=int(t - SCENE_S), until=int(t + SCENE_S) + 1)
    out = {}
    m = L["mmsi"]
    if not len(m):
        return out
    cuts = np.flatnonzero(np.diff(m)) + 1
    for idx in np.split(np.arange(len(m)), cuts):
        mm = int(m[idx[0]])
        tt, la, lo = L["time"][idx].astype(float), L["lat"][idx], L["lon"][idx]
        j = int(np.argmin(np.abs(tt - t)))
        nearest = (float(la[j]), float(lo[j]))
        before = np.flatnonzero((tt <= t) & (tt >= t - WIN_S))
        after = np.flatnonzero((tt >= t) & (tt <= t + WIN_S))
        known, pos, why = False, nearest, "no report within the windows"
        if len(before) and len(after):
            b, a_ = before[-1], after[0]
            if tt[a_] == tt[b]:
                pos, known, why = (float(la[b]), float(lo[b])), True, "report at acquisition"
            else:
                d_km = km((la[b], lo[b]), (la[a_], lo[a_]))
                kn = d_km / 1.852 / max((tt[a_] - tt[b]) / 3600, 1e-9)
                if kn > MAX_KN:
                    why = f"segment implies {kn:.0f} kn"
                else:
                    f = (t - tt[b]) / (tt[a_] - tt[b])
                    pos = (float(la[b] + f * (la[a_] - la[b])), float(lo[b] + f * (lo[a_] - lo[b])))
                    known, why = True, "interpolated"
        elif abs(tt[j] - t) <= NEAR_S:
            known, why = True, "single report within 2 min"
        if known and any(a0 <= t <= a1 for a0, a1 in spans.get(mm, [])):
            known, why = False, "spoofing victim flagged at acquisition"
        out[mm] = {"known": known, "lat": round(pos[0], 5), "lon": round(pos[1], 5), "why": why}
    return out


def match(dets, vessels, cover):
    """Nearest-first one-to-one matching within MATCH_M; returns pairs and marks each detection and vessel."""
    known = [(m, v) for m, v in vessels.items() if v["known"]]
    pairs = []
    for i, d in enumerate(dets):
        for m, v in known:
            if abs(v["lat"] - d["lat"]) < 0.02 and abs(v["lon"] - d["lon"]) < 0.04:
                dist = km((d["lat"], d["lon"]), (v["lat"], v["lon"])) * 1000
                if dist <= MATCH_M:
                    pairs.append((dist, i, m))
    used_d, used_v = set(), set()
    for dist, i, m in sorted(pairs):
        if i in used_d or m in used_v:
            continue
        used_d.add(i)
        used_v.add(m)
        dets[i]["match"] = {"mmsi": m, "m": round(dist)}
        vessels[m]["match_m"] = round(dist)
    unknown = [v for v in vessels.values() if not v["known"]]
    for d in dets:
        if "match" not in d:
            near_unknown = any(abs(v["lat"] - d["lat"]) < 0.02 and km((d["lat"], d["lon"]), (v["lat"], v["lon"])) * 1000
                               <= MATCH_M for v in unknown)
            d["dark"] = not near_unknown
            d["near_unknown"] = near_unknown
    for m, v in vessels.items():
        v["scored"] = v["known"] and any(t.covers(v["lat"], v["lon"]) for t in cover)
    return dets


def cmd_run(a):
    items = []
    for fid in a.scenes:
        t0 = datetime.strptime(fid.split("_")[4], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        found = SD.search((57.0, 63.0, 17.0, 31.0), t0 - timedelta(minutes=5), t0 + timedelta(minutes=5))
        items += [it for it in found if it["id"].startswith(fid) and it not in items]   # a unique prefix is enough
    groups = SD.passes(items)
    meta = A.load_metadata(a.days)
    spans = spoof_spans(a.summary)
    out_dir = os.path.join(OUT, a.variant)
    os.makedirs(out_dir, exist_ok=True)
    for g in groups:
        t = g["t"].timestamp()
        tag = g["frames"][0]["id"]
        print(f"{tag} {g['t']:%Y-%m-%d %H:%M:%S}Z {g['orbit']}: {len(g['frames'])} frame(s)")
        dets, cover, bearing = detect_pass(g, a.variant)
        vessels = ais_at(a.days, t, spans)
        for mm, v in vessels.items():
            v["length_m"] = (meta.get(mm) or {}).get("length")
            if v["length_m"] is not None and not 5 <= v["length_m"] <= 400:
                v["length_m"] = None
        match(dets, vessels, cover)
        rec = {"rules": RULES, "variant": a.variant, "pass": tag, "along_bearing": bearing, "frames": [f["id"] for f in g["frames"]], "time": g["t"].isoformat(),
               "orbit": g["orbit"], "detections": dets,
               "vessels": {str(k): v for k, v in vessels.items() if v.get("scored") or v.get("match_m") is not None},
               "vessels_heard": len(vessels), "tiles": len(cover),
               "cover": [pack(t_) for t_ in cover],
               "licence": "Contains modified Copernicus Sentinel data; AIS from Fintraffic Digitraffic (CC BY 4.0)"}
        with open(os.path.join(out_dir, f"{tag}.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f)
        nd = sum(1 for d in dets if d.get("dark"))
        print(f"  {len(dets)} detections ({nd} dark), {sum(1 for v in vessels.values() if v.get('scored'))} scored vessels, "
              f"{len(cover)} tiles")


def pack(t):
    """A tile's scoring mask at 100 m, bit-packed, with what's needed to look a point up."""
    import base64
    g = t.score[::5, ::5]
    return {"core": t.core, "crs": t.crs, "tr": list(t.tr)[:6], "shape": list(g.shape),
            "mask": base64.b64encode(np.packbits(g).tobytes()).decode()}


_MASKS = {}


def cmd_clutter(a):
    """Detections and coverage for every pass over the scored regions in [start, end] (no AIS): the fixed-object map."""
    start = datetime.fromisoformat(a.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(a.end).replace(tzinfo=timezone.utc) + timedelta(days=1)
    groups = SD.passes(SD.search(SCORED_BOX, start, end))
    out_dir = os.path.join(OUT, "clutter", a.variant)
    os.makedirs(out_dir, exist_ok=True)
    print(f"{len(groups)} passes from {a.start} to {a.end}")
    for g in groups:
        tag = g["frames"][0]["id"]
        path = os.path.join(out_dir, f"{tag}.json")
        if os.path.exists(path):
            continue
        dets, cover, bearing = detect_pass(g, a.variant)
        rec = {"pass": tag, "time": g["t"].isoformat(), "orbit": g["orbit"], "variant": a.variant, "along_bearing": bearing,
               "detections": [{"lat": d["lat"], "lon": d["lon"], "length_m": d["length_m"]} for d in dets],
               "cover": [pack(t) for t in cover]}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rec, f)
        print(f"  {tag[:40]} {g['t']:%Y-%m-%d %H:%M}Z {g['orbit']}: {len(dets)} detections, {len(cover)} tiles", flush=True)


def load_clutter(variant):
    d = os.path.join(OUT, "clutter", variant)
    return [json.load(open(os.path.join(d, n), encoding="utf-8")) for n in sorted(os.listdir(d)) if n.endswith(".json")] \
        if os.path.isdir(d) else []


def clutter_flags(recs, clutter):
    """Amendment 3: mark detections at places seen in >= CLUTTER_SHARE of the >= CLUTTER_MIN_COVER clutter passes
    covering them."""
    for r in recs:
        for d in r["detections"]:
            cov = hit = 0
            for c in clutter:
                if covered_by(c, d["lat"], d["lon"]):
                    cov += 1
                    hit += any(abs(e["lat"] - d["lat"]) < 0.002 and km((d["lat"], d["lon"]), (e["lat"], e["lon"])) * 1000
                               <= FIXED_M for e in c["detections"])
            d["clutter_cover"], d["clutter_hits"] = cov, hit
            d["fixed_map"] = cov >= CLUTTER_MIN_COVER and hit / cov >= CLUTTER_SHARE


def along_across(src, d, bearing):
    """(along-track, across-track) offset in km of d from src, for a pass whose along-track bearing is `bearing`."""
    dn = (d["lat"] - src[0]) * 111.2
    de = (d["lon"] - src[1]) * 111.2 * math.cos(math.radians((d["lat"] + src[0]) / 2))
    b = math.radians(bearing)
    return dn * math.cos(b) + de * math.sin(b), -dn * math.sin(b) + de * math.cos(b)


def ghost_flags(r):
    """Amendment 3: unmatched detections that sit GHOST_ALONG_KM along track (and within GHOST_ACROSS_M across) from a
    matched detection or a known AIS vessel of 50 m or more."""
    b = r.get("along_bearing")
    srcs = [(d["lat"], d["lon"]) for d in r["detections"] if d.get("match")]
    srcs += [(v["lat"], v["lon"]) for v in r["vessels"].values() if v.get("known") and (v.get("length_m") or 0) >= 50]
    for d in r["detections"]:
        d["ghost"] = False
        if d.get("match") or b is None:
            continue
        for s0 in srcs:
            al, ac = along_across(s0, d, b)
            if GHOST_ALONG_KM[0] <= abs(al) <= GHOST_ALONG_KM[1] and abs(ac) * 1000 <= GHOST_ACROSS_M:
                d["ghost"] = True
                break


def covered_by(rec, lat, lon):
    import base64
    from rasterio.warp import transform as warp_xy
    for i, c in enumerate(rec["cover"]):
        if not in_box(c["core"], lat, lon):
            continue
        key = (rec["pass"], i)
        if key not in _MASKS:
            n = c["shape"][0] * c["shape"][1]
            _MASKS[key] = np.unpackbits(np.frombuffer(base64.b64decode(c["mask"]), np.uint8))[:n].reshape(c["shape"])
        g = _MASKS[key]
        xs, ys = warp_xy("EPSG:4326", c["crs"], [lon], [lat])
        tr = c["tr"]
        col, row = int((xs[0] - tr[2]) / (tr[0] * 5)), int((ys[0] - tr[5]) / (tr[4] * 5))
        if 0 <= row < g.shape[0] and 0 <= col < g.shape[1] and g[row, col]:
            return True
    return False


def fixed_flags(recs):
    """Mark detections at sites seen in at least FIXED_SHARE of the passes covering them (two passes or more)."""
    for r in recs:
        for d in r["detections"]:
            cov = hit = 0
            for r2 in recs:
                if r2 is r:
                    cov += 1
                    hit += 1
                    continue
                if covered_by(r2, d["lat"], d["lon"]):
                    cov += 1
                    hit += any(abs(e["lat"] - d["lat"]) < 0.002 and km((d["lat"], d["lon"]), (e["lat"], e["lon"])) * 1000
                               <= FIXED_M for e in r2["detections"])
            d["fixed"] = cov >= 2 and hit / cov >= FIXED_SHARE


def score(recs, amend3=False):
    fixed_flags(recs)
    if amend3:
        clutter_flags(recs, load_clutter(recs[0].get("variant", "B")))
        for r in recs:
            ghost_flags(r)
            for d in r["detections"]:
                d["fixed"] = d.get("fixed") or d.get("fixed_map")
    v = [x for r in recs for x in r["vessels"].values() if x.get("scored")]
    big = [x for x in v if (x.get("length_m") or 0) >= 100]
    mid = [x for x in v if 50 <= (x.get("length_m") or 0) < 100]
    found = [x for x in big if x.get("match_m") is not None]
    dists = sorted(x["match_m"] for x in found)
    dets = [d for r in recs for d in r["detections"]]
    large = [d for d in dets if d["length_m"] >= 50 and not d.get("fixed")]
    dark_large = [d for d in large if d.get("dark") and not d.get("ghost")]
    east = [d for d in dark_large if d["region"] == "Gulf of Finland east of 27E"]
    h1 = len(found) / len(big) if big else float("nan")
    h2 = dists[len(dists) // 2] if dists else float("nan")
    h3 = len(dark_large) / len(large) if large else float("nan")
    out = {"passes": [r["pass"] for r in recs], "vessels_scored": len(v), "vessels_100m": len(big),
           "H1": {"matched": len(found), "of": len(big), "recall": round(h1, 3), "pass": bool(h1 >= 0.85)},
           "H2": {"median_m": h2, "pass": bool(h2 <= 500)},
           "H3": {"dark_large": len(dark_large), "of_large": len(large), "share": round(h3, 3), "pass": bool(h3 <= 0.10)},
           "reported": {"recall_50_100m": f"{sum(1 for x in mid if x.get('match_m') is not None)} of {len(mid)}",
                        "detections": len(dets), "fixed": sum(1 for d in dets if d.get("fixed")),
                        "dark_all": sum(1 for d in dets if d.get("dark") and not d.get("ghost") and not d.get("fixed")),
                        "ghosts": sum(1 for d in dets if d.get("ghost")), "fixed_map": sum(1 for d in dets if d.get("fixed_map")),
                        "dark_large_east_of_27E": len(east),
                        "phantom_candidates_50m": sum(1 for x in v if (x.get("length_m") or 0) >= 50
                                                      and x.get("match_m") is None)}}
    few = len(big) < 20
    h = (out["H1"]["pass"], out["H2"]["pass"], out["H3"]["pass"])
    out["verdict"] = ("too few ships" if few else "validated (regional)" if all(h)
                      else "partly validated" if h[0] and h[1] else "not validated")
    return out


def cmd_score(a):
    recs = []
    d = os.path.join(OUT, a.variant)
    for n in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if n.endswith(".json"):
            r = json.load(open(os.path.join(d, n), encoding="utf-8"))
            if any(r["time"].startswith(d) for d in SETS[a.set]):
                recs.append(r)
    if not recs:
        sys.exit(f"no passes for set {a.set} in {d}")
    print(json.dumps(score(recs, amend3=a.amend3), indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--scenes", nargs="+", required=True, help="Sentinel-1 frame ids of one or more passes")
    r.add_argument("--days", nargs="+", required=True, help="AIS UTC day folders to read")
    r.add_argument("--summary", help="ais_detect summary JSON for the same capture (spoofing victims)")
    r.add_argument("--variant", choices=["A", "B"], default="A", help="A: pre-registered; B: plus OpenStreetMap land")
    s = sub.add_parser("score")
    s.add_argument("--variant", choices=["A", "B"], default="A")
    s.add_argument("--amend3", action="store_true", help="apply amendment 3 (fixed-object map and ghost rule)")
    c = sub.add_parser("clutter")
    c.add_argument("--variant", choices=["A", "B"], default="B")
    c.add_argument("--start", required=True)
    c.add_argument("--end", required=True)
    s.add_argument("--set", choices=sorted(SETS), required=True)
    a = ap.parse_args()
    {"run": cmd_run, "score": cmd_score, "clutter": cmd_clutter}[a.cmd](a)


if __name__ == "__main__":
    main()
