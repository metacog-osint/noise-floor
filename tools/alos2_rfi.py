#!/usr/bin/env python3
"""alos2_rfi.py: L-band interference in ALOS-2 PALSAR-2 ScanSAR images (1257.5 MHz), from JAXA's open L2.2 archive.

JAXA's free ScanSAR Level 2.2 products (HH and HV gamma-nought, 25 m; 236,196 scenes from 4 Aug 2014 to 30 Sep 2026 when listed on 31 Oct 2026) sit in the AWS open bucket
`jaxaalos2` under palsar2/L2.2/2025/ as cloud-optimized GeoTIFFs with overviews (200 m at level 3, 400 m at level 4),
so a scene can be read coarsely for a few MB. The products carry no RFI tables. Interference from an emitter is not
polarized, so it adds about as much power to HV as to HH, while natural surfaces return HV 5-12 dB below HH. Pixels with
HV - HH above a cut (-3 dB by default) are counted as interference-like, as the NISAR lane's cross-pol excess does.

Commands
  index                         list every scene in the bucket -> data/alos2/scenes.json (about 15 minutes)
  find --bbox W S E N --start YYYY-MM-DD --end YYYY-MM-DD
                                scenes in the window whose footprint meets the box (reads each candidate's small JSON)
  score SCENE... [--level 3] [--cut -3]
                                share of valid pixels with HV - HH above the cut, the median HV - HH, and a quicklook
                                PNG of the excess -> data/alos2/score/<scene>.json and .png

Data: JAXA ALOS-2 PALSAR-2 ScanSAR L2.2 (free of charge under each platform's terms; registry row `alos2-scansar`).
Descriptive: there is no known answer to test against yet.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
import urllib.request

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "alos2")
BUCKET = "https://jaxaalos2.s3.amazonaws.com"
PREFIX = "palsar2/L2.2/2025/"
UA = {"User-Agent": "noisefloor/1.0 (+https://github.com/metacog-osint/noise-floor)"}
CUT_DB = -3.0


def index():
    tok, scenes = None, set()
    while True:
        u = f"{BUCKET}/?list-type=2&prefix={PREFIX}&max-keys=1000" + (
            f"&continuation-token={urllib.parse.quote(tok)}" if tok else "")
        x = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=120).read().decode()
        scenes.update(re.findall(rf"<Key>{re.escape(PREFIX)}([^<]+)_HV_SLP\.tif</Key>", x))
        m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", x)
        if not m:
            break
        tok = m.group(1)
    os.makedirs(DATA, exist_ok=True)
    json.dump(sorted(scenes), open(os.path.join(DATA, "scenes.json"), "w"))
    print(f"{len(scenes)} scenes")


def scene_date(s):
    """'ALOS2010632250-140804_WBDR2.2GUD' -> date(2014, 8, 4)."""
    d = s.split("-")[1][:6]
    return dt.date(2000 + int(d[:2]), int(d[2:4]), int(d[4:6]))


def meta(scene):
    p = os.path.join(DATA, "meta", f"{scene}.json")
    if not os.path.exists(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        u = f"{BUCKET}/{PREFIX}{scene}.json"
        open(p, "wb").write(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read())
    return json.load(open(p, encoding="utf-8"))


def find(bbox, start, end):
    from shapely.geometry import box, shape
    scenes = json.load(open(os.path.join(DATA, "scenes.json")))
    a, b = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    cand = [s for s in scenes if a <= scene_date(s) <= b]
    q = box(*bbox)
    out = []
    for s in cand:
        g = shape(meta(s)["geometry"])
        if g.intersects(q):
            out.append(s)
    return out


LINE_DB = 3.0          # a line across the swath counts as interference-like this far above the scene's median
LINE_MIN_PX = 50


def read_level(url, level):
    """Band 1 at an overview level, with that level's affine transform and the raster's CRS."""
    import rasterio
    with rasterio.open(url, overview_level=level) as r:
        return r.read(1).astype(np.float32), r.transform, r.crs


def along_track_profile(ex, transform, crs, footprint):
    """Median HV - HH per line across the swath. The flight direction is the footprint's first edge (corner 1 to 2;
    checked on a descending scene, where it runs north to south). Returns (line index, line medians, pixels per line,
    a function giving the line index of a (lat, lon))."""
    from pyproj import Transformer
    lonlat = footprint["coordinates"][0][:4]
    tr = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    inv = ~transform
    px = []
    for lo, la in lonlat:
        x, y = tr.transform(lo, la)
        c, r = inv * (x, y)
        px.append((c, r))
    a = np.array(px[1]) - np.array(px[0])
    a /= np.linalg.norm(a)
    rows, cols = np.nonzero(np.isfinite(ex))
    s = (cols - px[0][0]) * a[0] + (rows - px[0][1]) * a[1]
    s0 = s.min()
    k = np.floor(s - s0).astype(np.int64)
    v = ex[rows, cols]
    order = np.argsort(k, kind="stable")
    k, v = k[order], v[order]
    edges = np.r_[0, np.nonzero(np.diff(k))[0] + 1, len(k)]
    med = np.array([np.median(v[i:j]) for i, j in zip(edges[:-1], edges[1:])])
    cnt = np.diff(edges)

    def line_of(lat, lon):
        x, y = tr.transform(lon, lat)
        c, r = inv * (x, y)
        return int(np.floor((c - px[0][0]) * a[0] + (r - px[0][1]) * a[1] - s0))
    return k[edges[:-1]], med, cnt, line_of


LOCAL_HALF = 25        # lines either side for the local reference (about 5 km at overview level 3)
SCENE_MIN_RAISED = 2   # a scene is flagged with this many raised lines (docs/validation/alos2.md section 2)


def local_excess(kidx, med, cnt, half=LOCAL_HALF, min_px=LINE_MIN_PX):
    """Each line's median minus the median of the lines within +-half lines (itself excluded); NaN for thin lines."""
    out = np.full(len(med), np.nan)
    good = cnt >= min_px
    for i in range(len(med)):
        if not good[i]:
            continue
        lo, hi = np.searchsorted(kidx, kidx[i] - half), np.searchsorted(kidx, kidx[i] + half, side="right")
        nb = [j for j in range(lo, hi) if j != i and good[j]]
        if len(nb) >= 5:
            out[i] = med[i] - np.median(med[nb])
    return out


def score(scene, level=3, cut=CUT_DB):
    from PIL import Image
    base = f"/vsicurl/{BUCKET}/{PREFIX}{scene}"
    hh, transform, crs = read_level(base + "_HH_SLP.tif", level)
    hv, _, _ = read_level(base + "_HV_SLP.tif", level)
    ok = (hh > 0) & (hv > 0)
    ex = np.full(hh.shape, np.nan, np.float32)
    ex[ok] = 20.0 * np.log10(hv[ok] / hh[ok])              # same calibration factor for both, so DN ratio is enough
    n = int(ok.sum())
    fp = meta(scene)["geometry"]
    kidx, med, cnt, line_of = along_track_profile(ex, transform, crs, fp)
    m0 = float(np.median(ex[ok])) if n else np.nan
    good = cnt >= LINE_MIN_PX
    lines = med[good] - m0
    loc = local_excess(kidx, med, cnt)
    raised = kidx[np.isfinite(loc) & (loc >= LINE_DB)]
    out = {"scene": scene, "date": scene_date(scene).isoformat(), "level": level, "pixels": n,
           "share_over_cut": round(float(np.mean(ex[ok] > cut)), 4) if n else None,
           "median_hv_minus_hh_db": round(m0, 2) if n else None, "cut_db": cut,
           "lines": int(good.sum()), "lines_flagged": int((lines > LINE_DB).sum()),
           "max_line_excess_db": round(float(lines.max()), 2) if len(lines) else None,
           "lines_raised_local": int(len(raised)), "raised_lines": [int(x) for x in raised],
           "max_local_excess_db": round(float(np.nanmax(loc)), 2) if np.isfinite(loc).any() else None,
           "flagged": bool(len(raised) >= SCENE_MIN_RAISED),
           "profile_db": [round(float(x), 2) for x in lines[::4]], "footprint": fp}
    out["_line_of"] = line_of
    os.makedirs(os.path.join(DATA, "score"), exist_ok=True)
    json.dump({k: v for k, v in out.items() if not k.startswith("_")},
              open(os.path.join(DATA, "score", f"{scene}.json"), "w"), indent=1)
    img = np.zeros(hh.shape, np.uint8)
    img[ok] = np.clip((ex[ok] + 15.0) * 255.0 / 15.0, 0, 255).astype(np.uint8)   # -15 dB black ... 0 dB white
    Image.fromarray(img).save(os.path.join(DATA, "score", f"{scene}.png"))
    print(f"{scene} {out['date']}: {n} px, {out['share_over_cut']} over {cut} dB, median HV-HH {out['median_hv_minus_hh_db']} dB")
    return out


# ---------------------------------------------------------------------------------------------- NWS known answer
# docs/validation/alos2.md sections 2-3 (frozen 31 Oct 2026, commit 25ae714)
NWS_PERIOD = ("2025-10-01", "2026-09-30")
NWS_FRAMES = ((1000, 1550), (2050, 2600))
SITE_INSET_KM, CONTROL_AWAY_KM, PER_SITE = 20.0, 300.0, 6
NWS_BOX = (51.5, 73.3, -168.2, -54.8)                 # S, N, W, E


def _sites():
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import smap_rfi as M
    return dict(M.NWS_LRR), dict(M.NWS_EXCLUDED)


def _km(lat1, lon1, lat2, lon2):
    la1, lo1, la2, lo2 = (np.radians(np.asarray(v, float)) for v in (lat1, lon1, lat2, lon2))
    h = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(np.minimum(h, 1.0)))


def _ring(fp, step=60):
    """Footprint corners and points along its edges (lat, lon), and whether it crosses the antimeridian."""
    c = fp["coordinates"][0]
    lons = [p[0] for p in c]
    wrap = max(lons) - min(lons) > 180
    pts = []
    for (lo1, la1), (lo2, la2) in zip(c[:-1], c[1:]):
        for t in np.linspace(0, 1, step, endpoint=False):
            pts.append((la1 + t * (la2 - la1), lo1 + t * (lo2 - lo1)))
    return np.array(pts), wrap


def _inside_km(fp, lat, lon):
    """Distance (km) from a point to the footprint edge: positive inside, negative outside."""
    from shapely.geometry import Point, shape
    pts, _ = _ring(fp)
    d = float(_km(lat, lon, pts[:, 0], pts[:, 1]).min())
    return d if shape(fp).contains(Point(lon, lat)) else -d


def nws_select(workers=8):
    from concurrent.futures import ThreadPoolExecutor
    from shapely.geometry import shape
    sites, excluded = _sites()
    allsites = {**sites, **excluded}
    a, b = (dt.date.fromisoformat(x) for x in NWS_PERIOD)
    scenes = json.load(open(os.path.join(DATA, "scenes.json")))
    cand = [x for x in scenes if a <= scene_date(x) <= b and
            any(lo <= int(x[10:14]) <= hi for lo, hi in NWS_FRAMES)]
    print(f"{len(cand)} candidate scenes in the period and frame ranges; reading footprints")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        metas = dict(zip(cand, ex.map(lambda x: meta(x)["geometry"], cand)))
    site_scenes, control, wrapped = {n: [] for n in sites}, [], 0
    for x in sorted(cand, key=lambda x: (scene_date(x), x)):
        fp = metas[x]
        if _ring(fp)[1]:
            wrapped += 1
            continue
        for n, (la, lo) in sites.items():
            if _inside_km(fp, la, lo) >= SITE_INSET_KM:
                site_scenes[n].append(x)
        cen = shape(fp).centroid
        if NWS_BOX[0] <= cen.y <= NWS_BOX[1] and NWS_BOX[2] <= cen.x <= NWS_BOX[3]:
            if all(_inside_km(fp, la, lo) < -CONTROL_AWAY_KM for la, lo in allsites.values()):
                control.append(x)
    chosen = {n: v[:PER_SITE] for n, v in site_scenes.items()}
    site_set = sorted({x for v in chosen.values() for x in v})
    ctrl = sorted(control)
    if len(ctrl) > len(site_set):
        k = len(ctrl) / len(site_set)
        ctrl = [ctrl[int(i * k)] for i in range(len(site_set))]
    out = {"period": NWS_PERIOD, "candidates": len(cand), "wrapped_skipped": wrapped,
           "per_site_available": {n: len(v) for n, v in site_scenes.items()}, "per_site": chosen,
           "site_scenes": site_set, "control_available": len(control), "control_scenes": ctrl}
    json.dump(out, open(os.path.join(DATA, "nws_selection.json"), "w"), indent=1)
    print(f"site scenes {len(site_set)} (per site available: {out['per_site_available']}); "
          f"controls {len(ctrl)} of {len(control)} available; {wrapped} antimeridian scenes skipped")
    return out


def nws_score(workers=4):
    from concurrent.futures import ThreadPoolExecutor
    sel = json.load(open(os.path.join(DATA, "nws_selection.json")))
    sites, _ = _sites()
    todo = sel["site_scenes"] + sel["control_scenes"]
    res = {}

    def one(x):
        try:
            r = score(x)
            pos = {}
            for n, (la, lo) in sites.items():
                if _inside_km(r["footprint"], la, lo) >= SITE_INSET_KM:
                    k = r["_line_of"](la, lo)
                    near = [abs(q - k) for q in r["raised_lines"]]
                    pos[n] = {"line": k, "nearest_raised_km": round(min(near) * 0.2, 1) if near else None}
            r.pop("_line_of")
            r.pop("footprint")
            r.pop("profile_db")
            r["sites"] = pos
            return x, r
        except Exception as e:
            return x, {"error": str(e)[:200]}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for x, r in ex.map(one, todo):
            res[x] = r
    json.dump(res, open(os.path.join(DATA, "nws_scores.json"), "w"), indent=1)
    print(f"scored {sum('error' not in r for r in res.values())} of {len(todo)}")
    return res


def nws_report():
    from scipy.stats import fisher_exact
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    from cygnss_rfi import auc
    sel = json.load(open(os.path.join(DATA, "nws_selection.json")))
    res = json.load(open(os.path.join(DATA, "nws_scores.json")))
    S = [res[x] for x in sel["site_scenes"] if "error" not in res.get(x, {"error": 1})]
    C = [res[x] for x in sel["control_scenes"] if "error" not in res.get(x, {"error": 1})]
    sf, cf = sum(r["flagged"] for r in S), sum(r["flagged"] for r in C)
    p = fisher_exact([[sf, len(S) - sf], [cf, len(C) - cf]], alternative="greater")[1] if S and C else None
    sv = [r["max_local_excess_db"] for r in S if r["max_local_excess_db"] is not None]
    cv = [r["max_local_excess_db"] for r in C if r["max_local_excess_db"] is not None]
    per_site = {}
    for n in sel["per_site"]:
        rows = [res[x] for x in sel["per_site"][n] if "error" not in res.get(x, {"error": 1})]
        per_site[n] = {"scenes": len(rows), "flagged": sum(r["flagged"] for r in rows),
                       "raised_within_10km": sum(1 for r in rows if (r["sites"].get(n) or {}).get("nearest_raised_km") is not None
                                                 and r["sites"][n]["nearest_raised_km"] <= 10.0)}
    out = {"site_scenes": len(S), "control_scenes": len(C), "errors": sum("error" in r for r in res.values()),
           "site_flagged": sf, "control_flagged": cf,
           "site_share": round(sf / len(S), 3) if S else None, "control_share": round(cf / len(C), 3) if C else None,
           "fisher_p": None if p is None else float(f"{p:.3g}"),
           "auc_score": round(auc(sv, cv), 3) if sv and cv else None,
           "site_median_score": round(float(np.median(sv)), 2) if sv else None,
           "control_median_score": round(float(np.median(cv)), 2) if cv else None,
           "site_scene_median_flag": int(sum(r["lines_flagged"] > 0 for r in S)),
           "control_scene_median_flag": int(sum(r["lines_flagged"] > 0 for r in C)), "per_site": per_site}
    print(json.dumps(out, indent=1))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("index")
    f = sub.add_parser("find")
    f.add_argument("--bbox", nargs=4, type=float, required=True, metavar=("W", "S", "E", "N"))
    f.add_argument("--start", required=True)
    f.add_argument("--end", required=True)
    s = sub.add_parser("score")
    s.add_argument("scenes", nargs="+")
    s.add_argument("--level", type=int, default=3)
    s.add_argument("--cut", type=float, default=CUT_DB)
    sub.add_parser("nws-select", help="pick site and control scenes by the frozen rule (docs/validation/alos2.md)")
    sub.add_parser("nws-score", help="score the selected scenes")
    sub.add_parser("nws-report", help="checks A1-A2")
    a = ap.parse_args(argv)
    if a.cmd == "nws-select":
        return nws_select()
    if a.cmd == "nws-score":
        return nws_score()
    if a.cmd == "nws-report":
        return nws_report()
    if a.cmd == "index":
        index()
    elif a.cmd == "find":
        for x in find(a.bbox, a.start, a.end):
            print(x)
    else:
        for sc in a.scenes:
            score(sc, a.level, a.cut)


if __name__ == "__main__":
    main()
