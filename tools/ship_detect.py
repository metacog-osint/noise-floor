#!/usr/bin/env python3
"""ship_detect.py: ships in Sentinel-1 radar images over a box (maritime plan, detector D1 groundwork).

Reads only the box from Sentinel-1 IW GRD scenes served as cloud-optimised GeoTIFFs by Microsoft's Planetary Computer
(free, anonymous signed URLs; the data are Copernicus Sentinel data, free including commercial use), warps the box to a
local UTM grid, masks land, and finds bright targets on dark sea with a CFAR test (each pixel against the mean and spread
of a ring of sea pixels around it). Outputs one JSON per scene with each detection's position, size and brightness,
plus a quick-look PNG.

  python tools/ship_detect.py search --area singapore_johor --days 60
  python tools/ship_detect.py detect --area singapore_johor --days 60 [--res 20] [--max 20]
  python tools/ship_detect.py detect --box lat0,lat1,lon0,lon1 --scene <item id>
  python tools/ship_detect.py persist [--radius 60] [--share 0.6]   # fixed structures vs ships across passes

--area reads a focus-area box from the private watch config (private/watch/maritime.json); boxes are never written to
tracked files. Outputs go to private/maritime/s1/ (gitignored).

Limits (first version): GRD amplitude is not radiometrically calibrated here (fine for a relative test); the land mask
is Natural Earth 10 m, which misses recent reclamation, so a buffer is applied; fixed structures and anchored ships both
show as targets; ambiguities from very bright targets and azimuth ghosts are not removed.
"""
import argparse, json, math, os, sys, time
from datetime import datetime, timedelta, timezone

import numpy as np
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "private", "maritime", "s1")
REF = os.path.join(ROOT, "data", "ref")
STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
SAS = "https://planetarycomputer.microsoft.com/api/sas/v1/token/sentinel-1-grd"
NE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/{}.geojson"
UA = {"User-Agent": "noise-floor (github.com/metacog-osint/noise-floor)"}


def area_box(area):
    cfg = json.load(open(os.path.join(ROOT, "private", "watch", "maritime.json"), encoding="utf-8"))
    for a in cfg["focus_areas"]:
        if a["id"] == area:
            return tuple(a["box"])
    sys.exit(f"no focus area {area!r} in private/watch/maritime.json")


def search(box, start, end):
    lat0, lat1, lon0, lon1 = box
    body = {"collections": ["sentinel-1-grd"], "bbox": [lon0, lat0, lon1, lat1],
            "datetime": f"{start:%Y-%m-%dT%H:%M:%SZ}/{end:%Y-%m-%dT%H:%M:%SZ}", "limit": 250,
            "query": {"sar:instrument_mode": {"eq": "IW"}}}
    items = requests.post(STAC, json=body, headers=UA, timeout=60).json().get("features", [])
    return sorted(items, key=lambda it: it["properties"]["datetime"])


_TOKEN = {"v": None, "t": 0}


def sign(href):
    if not _TOKEN["v"] or time.time() - _TOKEN["t"] > 1800:
        _TOKEN["v"] = requests.get(SAS, headers=UA, timeout=30).json()["token"]; _TOKEN["t"] = time.time()
    return href + ("&" if "?" in href else "?") + _TOKEN["v"]


def utm_epsg(lat, lon):
    return (32600 if lat >= 0 else 32700) + int((lon + 180) // 6) + 1


def land_geoms():
    """Natural Earth 10 m land and minor islands (public domain), cached under data/ref/."""
    os.makedirs(REF, exist_ok=True)
    out = []
    for name in ("ne_10m_land", "ne_10m_minor_islands"):
        p = os.path.join(REF, name + ".geojson")
        if not os.path.exists(p):
            r = requests.get(NE.format(name), headers=UA, timeout=300); r.raise_for_status()
            open(p, "wb").write(r.content)
        out += [f["geometry"] for f in json.load(open(p, encoding="utf-8"))["features"]]
    return out


def read_box(item, box, res, pol="vv"):
    """The box from one scene on a UTM grid at res metres: (array float32 of DN, transform, crs, valid mask).
    GRD files carry control points (GCPs), not a map transform. Each output pixel is mapped back to the scene's
    row/column through the GCPs, and only the window covering the box is read (at a matching overview level)."""
    import rasterio
    from rasterio.warp import transform_bounds, transform as warp_xy
    from rasterio.transform import from_origin, GCPTransformer
    from rasterio.windows import Window
    lat0, lat1, lon0, lon1 = box
    epsg = utm_epsg((lat0 + lat1) / 2, (lon0 + lon1) / 2)
    crs = f"EPSG:{epsg}"
    left, bottom, right, top = transform_bounds("EPSG:4326", crs, lon0, lat0, lon1, lat1)
    w, h = int((right - left) / res), int((top - bottom) / res)
    tr = from_origin(left, top, res, res)
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="4", GDAL_HTTP_RETRY_DELAY="2"):
        with rasterio.open(sign(item["assets"][pol]["href"])) as src:
            gcps, gcrs = src.gcps
            gt = GCPTransformer(gcps)
            # output pixel centres -> lon/lat -> source row/col (on a coarse lattice, then interpolated: GCPs are smooth)
            step = 16
            gy, gx = np.mgrid[0:h + step:step, 0:w + step:step]
            ex, ey = tr.c + (gx + 0.5) * res, tr.f - (gy + 0.5) * res
            lons, lats = warp_xy(crs, "EPSG:4326", ex.ravel().tolist(), ey.ravel().tolist())
            rows, cols = gt.rowcol(lons, lats, op=float)
            rows = np.array(rows, float).reshape(gy.shape); cols = np.array(cols, float).reshape(gx.shape)
            from scipy.ndimage import map_coordinates
            fy, fx = np.mgrid[0:h, 0:w]
            R = map_coordinates(rows, [fy / step, fx / step], order=1, mode="nearest")
            C = map_coordinates(cols, [fy / step, fx / step], order=1, mode="nearest")
            inside = (R >= 0) & (R < src.height) & (C >= 0) & (C < src.width)
            if not inside.any():
                return np.zeros((h, w), np.float32), tr, crs, np.zeros((h, w), bool)
            r0, r1 = int(max(R[inside].min(), 0)), int(min(R[inside].max() + 1, src.height))
            c0, c1 = int(max(C[inside].min(), 0)), int(min(C[inside].max() + 1, src.width))
            src_px = 10.0                                # IW GRDH pixel spacing, metres
            f = max(1, int(res // src_px))               # read decimated to about the output resolution
            win = Window(c0, r0, c1 - c0, r1 - r0)
            data = src.read(1, window=win, out_shape=(max(1, (r1 - r0) // f), max(1, (c1 - c0) // f)),
                            resampling=rasterio.enums.Resampling.average).astype(np.float32)
    rr = np.clip(((R - r0) / f).astype(int), 0, data.shape[0] - 1)
    cc = np.clip(((C - c0) / f).astype(int), 0, data.shape[1] - 1)
    a = np.where(inside, data[rr, cc], 0).astype(np.float32)
    return a, tr, crs, a > 0


def read_pass(frames, box, res, pol="vv"):
    """One acquisition can need two adjacent frames to cover the box: warp each to the same grid and combine."""
    out = None
    for it in frames:
        a, tr, crs, valid = read_box(it, box, res, pol)
        out = (a, tr, crs) if out is None else (np.where(valid & (out[0] == 0), a, out[0]), tr, crs)
    a, tr, crs = out
    return a, tr, crs, a > 0


def passes(items):
    """Group frames into acquisitions (same orbit direction, start times within 3 minutes)."""
    groups = []
    for it in sorted(items, key=lambda x: x["properties"]["datetime"]):
        t = datetime.fromisoformat(it["properties"]["datetime"].replace("Z", "+00:00"))
        if groups and (t - groups[-1]["t"]).total_seconds() < 180 and groups[-1]["orbit"] == it["properties"].get("sat:orbit_state"):
            groups[-1]["frames"].append(it)
        else:
            groups.append({"t": t, "orbit": it["properties"].get("sat:orbit_state"), "frames": [it]})
    return groups


def water_mask(shape, tr, crs, buffer_px, box):
    from rasterio.features import rasterize
    from rasterio.warp import transform_geom
    from scipy.ndimage import binary_dilation
    from shapely.geometry import shape as shp, box as sbox, mapping
    lat0, lat1, lon0, lon1 = box
    clip = sbox(lon0 - 0.2, lat0 - 0.2, lon1 + 0.2, lat1 + 0.2)   # clip first: whole continents don't reproject to UTM
    geoms = []
    for g in land_geoms():
        s = shp(g)
        if s.intersects(clip):
            geoms.append(transform_geom("EPSG:4326", crs, mapping(s.intersection(clip))))
    land = rasterize(((g, 1) for g in geoms), out_shape=shape, transform=tr, fill=0, dtype="uint8").astype(bool)
    if buffer_px:
        land = binary_dilation(land, iterations=buffer_px)
    return ~land


def image_land(a, valid, res, scale_m=600, factor=3.0, grow_px=2):
    """Land from the image itself: smoothed over about 600 m, land stays far brighter than open sea while a single
    ship is smoothed away. Threshold = factor x the median of the darker half of the scene (open sea)."""
    from scipy.ndimage import uniform_filter, binary_dilation
    n = max(3, int(scale_m / res) | 1)
    sm = uniform_filter(np.where(valid, a, 0), size=n) / np.maximum(uniform_filter(valid.astype(float), size=n), 1e-6)
    sea_level = np.median(a[valid][a[valid] <= np.median(a[valid])]) if valid.any() else 0
    land = valid & (sm > factor * sea_level)
    return binary_dilation(land, iterations=grow_px)


def cfar(intensity, sea, guard=7, ring=31, k=6.0, min_px=2):
    """Two-parameter CFAR: a pixel is a target when its intensity exceeds the ring's sea mean by k ring standard
    deviations (ring = a (2*ring+1) square minus a (2*guard+1) square, sea pixels only)."""
    from scipy.ndimage import uniform_filter, label, find_objects
    x = np.where(sea, intensity, 0.0).astype(np.float64)
    m = sea.astype(np.float64)

    def box_sum(v, r):
        n = 2 * r + 1
        return uniform_filter(v, size=n, mode="constant") * n * n

    s_out, s_in = box_sum(x, ring), box_sum(x, guard)
    q_out, q_in = box_sum(x * x, ring), box_sum(x * x, guard)
    n_out, n_in = box_sum(m, ring), box_sum(m, guard)
    n = np.maximum(n_out - n_in, 1)
    mean = (s_out - s_in) / n
    var = np.maximum((q_out - q_in) / n - mean * mean, 1e-12)
    hit = sea & (n > 0.5 * ((2 * ring + 1) ** 2 - (2 * guard + 1) ** 2)) & (x > mean + k * np.sqrt(var))
    lab, num = label(hit)
    out = []
    for i, sl in enumerate(find_objects(lab), 1):
        if sl is None:
            continue
        ys, xs = np.nonzero(lab[sl] == i)
        if len(ys) < min_px:
            continue
        ys = ys + sl[0].start; xs = xs + sl[1].start
        vals = intensity[ys, xs]
        cy, cx = float(np.average(ys, weights=vals)), float(np.average(xs, weights=vals))
        if len(ys) > 2:                                # major-axis length from second moments
            cov = np.cov(np.vstack([xs, ys]))
            length_px = 4 * math.sqrt(max(np.linalg.eigvalsh(cov)[-1], 0.25))
        else:
            length_px = math.sqrt(len(ys)) * 1.5
        out.append({"y": cy, "x": cx, "px": int(len(ys)), "length_px": round(length_px, 1), "peak": float(vals.max()),
                    "peak_ratio": round(float(vals.max() / max(mean[int(cy), int(cx)], 1e-9)), 1)})
    return out


def merge_nearby(dets, radius_px):
    """Bright ships leave cross-shaped sidelobes and break into pieces; keep the brightest detection within radius_px
    and fold the rest into it (non-maximum suppression)."""
    if not dets:
        return dets
    from scipy.spatial import cKDTree
    order = sorted(range(len(dets)), key=lambda i: -dets[i]["peak"])
    xy = np.array([(dets[i]["x"], dets[i]["y"]) for i in range(len(dets))])
    tree, gone, keep = cKDTree(xy), set(), []
    for i in order:
        if i in gone:
            continue
        keep.append(dets[i])
        for j in tree.query_ball_point(xy[i], radius_px):
            if j != i:
                gone.add(j)
    for d in keep:
        d.pop("peak", None)
    return keep


def to_lonlat(dets, tr, crs, res):
    from rasterio.warp import transform as warp_xy
    xs = [tr.c + (d["x"] + 0.5) * tr.a for d in dets]
    ys = [tr.f + (d["y"] + 0.5) * tr.e for d in dets]
    lons, lats = warp_xy(crs, "EPSG:4326", xs, ys) if dets else ([], [])
    for d, lo, la in zip(dets, lons, lats):
        d["lat"], d["lon"] = round(la, 5), round(lo, 5)
        d["length_m"] = round(d.pop("length_px") * res)
        d.pop("x"); d.pop("y")
    return dets


def quicklook(a, sea, dets_px, path):
    from PIL import Image, ImageDraw
    db = 10 * np.log10(np.maximum(a, 1) ** 2)
    v = np.clip((db - np.percentile(db[a > 0], 2)) / max(np.ptp(db[a > 0]) * 0.8, 1), 0, 1) if (a > 0).any() else db * 0
    img = Image.fromarray((v * 255).astype(np.uint8)).convert("RGB")
    step = max(1, max(img.size) // 2000)
    img = img.resize((img.size[0] // step, img.size[1] // step))
    d = ImageDraw.Draw(img)
    for p in dets_px:
        x, y = p[0] / step, p[1] / step
        d.ellipse([x - 4, y - 4, x + 4, y + 4], outline=(255, 80, 0), width=1)
    img.save(path)


def detect_scene(group, box, res, k, buffer_m, max_ships_png=True, min_len=30):
    item = group["frames"][0]
    a, tr, crs, valid = read_pass(group["frames"], box, res)
    if valid.mean() < 0.05:
        return None
    sea = water_mask(a.shape, tr, crs, int(round(buffer_m / res)), box) & valid
    sea &= ~image_land(a, valid, res)                   # coastline data misses reclamation, piers and river banks
    inten = a * a
    dets = merge_nearby(cfar(inten, sea, k=k), 200 / res)
    dets = [d for d in dets if d["length_px"] * res >= min_len]
    px = [(d["x"], d["y"]) for d in dets]
    dets = to_lonlat(dets, tr, crs, res)
    os.makedirs(OUT, exist_ok=True)
    rec = {"scene": item["id"], "frames": [f["id"] for f in group["frames"]], "time": item["properties"]["datetime"], "orbit": item["properties"].get("sat:orbit_state"),
           "res_m": res, "k": k, "land_buffer_m": buffer_m, "min_length_m": min_len, "merge_m": 200, "sea_km2": round(float(sea.sum()) * res * res / 1e6, 1),
           "valid_frac": round(float(valid.mean()), 3), "detections": dets,
           "licence": "Contains modified Copernicus Sentinel data (via Microsoft Planetary Computer)"}
    json.dump(rec, open(os.path.join(OUT, item["id"] + ".json"), "w", encoding="utf-8"), indent=1)
    if max_ships_png:
        quicklook(a, sea, px, os.path.join(OUT, item["id"] + ".png"))
    return rec


def persist(radius_m=60.0, share=0.6, min_valid=0.9):
    """Targets that recur within radius_m in at least `share` of the fully covered passes are fixed structures (fish
    farms, platforms, beacons, wrecks); the rest are ships or other movers. Anchored ships swing and shift between
    passes days apart, so they rarely recur this tightly."""
    from scipy.spatial import cKDTree
    recs = [json.load(open(os.path.join(OUT, f), encoding="utf-8")) for f in sorted(os.listdir(OUT))
            if f.endswith(".json") and f.startswith("S1")]
    full = [r for r in recs if r["valid_frac"] >= min_valid]
    if not full:
        sys.exit("no fully covered passes yet")
    lat_c = float(np.mean([d["lat"] for r in full for d in r["detections"]] or [0]))
    kx = 111320 * math.cos(math.radians(lat_c))
    pts, owner = [], []
    for i, r in enumerate(full):
        for d in r["detections"]:
            pts.append((d["lon"] * kx, d["lat"] * 110540)); owner.append(i)
    pts = np.array(pts); owner = np.array(owner)
    parent = np.arange(len(pts))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    for a, b in cKDTree(pts).query_pairs(radius_m):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    roots = np.array([find(i) for i in range(len(pts))])
    fixed = []
    for r_ in np.unique(roots):
        idx = np.nonzero(roots == r_)[0]
        n_pass = len(set(owner[idx].tolist()))
        if n_pass >= share * len(full):
            fixed.append({"lat": round(float(np.mean(pts[idx, 1]) / 110540), 5), "lon": round(float(np.mean(pts[idx, 0]) / kx), 5),
                          "passes": n_pass})
    fixed_xy = cKDTree(np.array([(f["lon"] * kx, f["lat"] * 110540) for f in fixed])) if fixed else None
    print(f"{len(full)} fully covered passes; {len(fixed)} fixed sites (recurring within {radius_m:.0f} m in {share:.0%}+ of passes)")
    for r in full:
        xy = np.array([(d["lon"] * kx, d["lat"] * 110540) for d in r["detections"]]) if r["detections"] else np.zeros((0, 2))
        n_fixed = int((fixed_xy.query(xy, distance_upper_bound=radius_m)[0] < radius_m).sum()) if (fixed_xy is not None and len(xy)) else 0
        print(f"  {r['time'][:16]} {r['orbit']:10} detections {len(r['detections']):5d}, at fixed sites {n_fixed:4d}, movers {len(r['detections']) - n_fixed:5d}")
    json.dump({"radius_m": radius_m, "share": share, "passes": len(full), "fixed": fixed},
              open(os.path.join(OUT, "fixed_sites.json"), "w", encoding="utf-8"), indent=1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["search", "detect", "persist"])
    ap.add_argument("--area"); ap.add_argument("--box")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--scene", help="one Planetary Computer item id")
    ap.add_argument("--res", type=float, default=20.0, help="output pixel size, metres")
    ap.add_argument("--k", type=float, default=6.0, help="CFAR threshold in ring standard deviations")
    ap.add_argument("--buffer", type=float, default=400.0, help="land buffer, metres")
    ap.add_argument("--max", type=int, default=10, help="most scenes to process")
    ap.add_argument("--radius", type=float, default=60.0); ap.add_argument("--share", type=float, default=0.6)
    a = ap.parse_args()
    if a.cmd == "persist":
        return persist(a.radius, a.share)
    box = area_box(a.area) if a.area else tuple(float(v) for v in a.box.split(","))
    end = datetime.now(timezone.utc); start = end - timedelta(days=a.days)
    items = search(box, start, end)
    if a.scene:
        items = [it for it in items if it["id"] == a.scene]
    if a.cmd == "search":
        acq = sorted({it["properties"]["datetime"][:16] for it in items})
        print(f"{len(items)} frames, {len(acq)} acquisitions in {a.days} days "
              f"({sum(1 for it in items if it['properties'].get('sat:orbit_state') == 'ascending')} ascending frames)")
        for it in items:
            p = it["properties"]; print(" ", p["datetime"][:19], p.get("sat:orbit_state"), it["id"])
        return
    done = 0
    for g in reversed(passes(items)):                   # newest first
        if done >= a.max:
            break
        t0 = time.time(); it = g["frames"][0]
        try:
            rec = detect_scene(g, box, a.res, a.k, a.buffer)
        except Exception as e:
            print(f"{it['id']}: failed ({type(e).__name__}: {e})"); continue
        if rec is None:
            print(f"{it['id']}: box not covered"); continue
        done += 1
        lens = sorted(d["length_m"] for d in rec["detections"])
        print(f"{it['id']} {rec['time'][:16]} {rec['orbit']}: {len(rec['detections'])} detections over {rec['sea_km2']} km2 of sea "
              f"(valid {rec['valid_frac']:.0%}); median length {lens[len(lens) // 2] if lens else 0} m; {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
