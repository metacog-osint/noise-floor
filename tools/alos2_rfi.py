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
    checked on a descending scene, where it runs north to south). Returns (line medians, pixels per line)."""
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
    k = np.floor(s - s.min()).astype(np.int64)
    v = ex[rows, cols]
    order = np.argsort(k, kind="stable")
    k, v = k[order], v[order]
    edges = np.r_[0, np.nonzero(np.diff(k))[0] + 1, len(k)]
    med = np.array([np.median(v[i:j]) for i, j in zip(edges[:-1], edges[1:])])
    cnt = np.diff(edges)
    return med, cnt


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
    med, cnt = along_track_profile(ex, transform, crs, fp)
    m0 = float(np.median(ex[ok])) if n else np.nan
    good = cnt >= LINE_MIN_PX
    lines = med[good] - m0
    out = {"scene": scene, "date": scene_date(scene).isoformat(), "level": level, "pixels": n,
           "share_over_cut": round(float(np.mean(ex[ok] > cut)), 4) if n else None,
           "median_hv_minus_hh_db": round(m0, 2) if n else None, "cut_db": cut,
           "lines": int(good.sum()), "lines_flagged": int((lines > LINE_DB).sum()),
           "max_line_excess_db": round(float(lines.max()), 2) if len(lines) else None,
           "profile_db": [round(float(x), 2) for x in lines[::4]], "footprint": fp}
    os.makedirs(os.path.join(DATA, "score"), exist_ok=True)
    json.dump(out, open(os.path.join(DATA, "score", f"{scene}.json"), "w"), indent=1)
    img = np.zeros(hh.shape, np.uint8)
    img[ok] = np.clip((ex[ok] + 15.0) * 255.0 / 15.0, 0, 255).astype(np.uint8)   # -15 dB black ... 0 dB white
    Image.fromarray(img).save(os.path.join(DATA, "score", f"{scene}.png"))
    print(f"{scene} {out['date']}: {n} px, {out['share_over_cut']} over {cut} dB, median HV-HH {out['median_hv_minus_hh_db']} dB")
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
    a = ap.parse_args(argv)
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
