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

Options added 24 Oct 2026 after the Sentinel-2 check (docs/validation/ships-s1.md); all off by default, so the original
behaviour is unchanged: --min-contrast 10 (drop low-contrast clutter blobs), --ghosts drop (azimuth ghosts of bright
targets), --landmask <npz> (an S2-derived land mask from tools/s2_check.py watermask, applied after the CFAR test).

Limits: GRD amplitude is not radiometrically calibrated here (fine for a relative test); the default land mask is Natural
Earth 10 m, which misses recent reclamation and small islands, so a buffer is applied; fixed structures and anchored ships
both show as targets; the Gaussian CFAR test passes low-contrast blobs in patchy low-wind sea.
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


def read_box(item, box, res, pol="vv", info=None):
    """The box from one scene on a UTM grid at res metres: (array float32 of DN, transform, crs, valid mask).
    GRD files carry control points (GCPs), not a map transform. Each output pixel is mapped back to the scene's
    row/column through the GCPs, and only the window covering the box is read (at a matching overview level).
    If `info` is a dict, the along-track bearing (direction of increasing image row, degrees from north) is stored in it."""
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
            if info is not None:                         # along-track direction from the row gradient where covered
                iy, ix = np.nonzero(inside[::step, ::step])
                cy, cx = int(np.median(iy)) * step, int(np.median(ix)) * step
                cy, cx = min(max(cy, 1), h - 2), min(max(cx, 1), w - 2)
                d_east = (R[cy, cx + 1] - R[cy, cx - 1]) / 2.0
                d_north = -(R[cy + 1, cx] - R[cy - 1, cx]) / 2.0
                info["along_bearing"] = (math.degrees(math.atan2(d_east, d_north)) + 360) % 360
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


def read_pass(frames, box, res, pol="vv", info=None):
    """One acquisition can need two adjacent frames to cover the box: warp each to the same grid and combine."""
    out = None
    for it in frames:
        a, tr, crs, valid = read_box(it, box, res, pol, info)
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


def merge_nearby(dets, radius_px, keep_peak=False):
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
    if not keep_peak:
        for d in keep:
            d.pop("peak", None)
    return keep


GHOST_ALONG_M = (4300.0, 6300.0)   # IW azimuth-ambiguity offsets seen in these passes (lambda R PRF / 2V, about 4.7-5.7 km)
GHOST_ACROSS_M = 200.0
GHOST_DB = 20.0                    # source at least this much brighter (peak intensity); S1 IW ambiguity ratio is about -22 dB


def ghost_sources(dets, along_bearing, res, along=GHOST_ALONG_M, across=GHOST_ACROSS_M, db=GHOST_DB):
    """Azimuth ghosts: a very bright target repeats, faintly and smeared, a few km either way along the satellite track.
    For each detection (pixel coordinates, with 'peak' intensity), return the index of a detection at least `db` brighter
    that sits `along` metres away along track and within `across` metres across track, or None."""
    out = [None] * len(dets)
    if not dets or along_bearing is None:
        return out
    from scipy.spatial import cKDTree
    b = math.radians(along_bearing)
    u = np.array([math.sin(b), math.cos(b)])                          # along track, (east, north)
    xy = np.array([(d["x"] * res, -d["y"] * res) for d in dets])       # metres, east and north
    pk = np.array([d["peak"] for d in dets])
    tree, ratio = cKDTree(xy), 10 ** (db / 10)
    for i in np.nonzero(pk >= ratio * pk.min())[0]:                   # only targets bright enough to cast a ghost
        for j in tree.query_ball_point(xy[i], along[1] + across):
            if j == i or pk[i] < ratio * pk[j]:
                continue
            v = xy[j] - xy[i]
            a, c = abs(float(v @ u)), abs(float(v[0] * u[1] - v[1] * u[0]))
            if along[0] <= a <= along[1] and c <= across and (out[j] is None or pk[i] > pk[out[j]]):
                out[j] = int(i)
    return out


def detect_array(a, tr, crs, valid, box, res, k=6.0, buffer_m=400.0, min_len=30, along_bearing=None, ghosts="keep",
                 extra_land=None, min_contrast_db=None):
    """The detection steps on one warped pass (as used by `detect`). Returns (detections in pixel coordinates with
    'peak' intensity, sea mask). ghosts: 'keep' (original behaviour), 'flag' (add 'ghost_of') or 'drop'.
    extra_land: optional boolean land mask on the same grid (for example from Sentinel-2). Detections on it (or within
    40 m) are dropped after the CFAR test, so the ring statistics stay as they were.
    min_contrast_db: optional floor on the peak's contrast over the ring's sea mean (10 log10 peak_ratio). Low-contrast
    blobs in patchy low-wind sea pass a Gaussian CFAR test but are rarely vessels (docs/validation/ships-s1.md)."""
    sea = water_mask(a.shape, tr, crs, int(round(buffer_m / res)), box) & valid
    sea &= ~image_land(a, valid, res)                   # coastline data misses reclamation, piers and river banks
    inten = a * a
    dets = merge_nearby(cfar(inten, sea, k=k), 200 / res, keep_peak=True)
    dets = [d for d in dets if d["length_px"] * res >= min_len]
    if min_contrast_db is not None:
        dets = [d for d in dets if 10 * math.log10(max(d["peak_ratio"], 1e-9)) >= min_contrast_db]
    if ghosts != "keep":                                # before the land filter: bright targets on land cast ghosts too
        src = ghost_sources(dets, along_bearing, res)
        if ghosts == "drop":
            dets = [d for d, s in zip(dets, src) if s is None]
        else:
            for d, s in zip(dets, src):
                if s is not None:
                    d["ghost_of"] = (dets[s]["x"], dets[s]["y"])   # pixel position of the bright source
    if extra_land is not None:
        from scipy.ndimage import binary_dilation
        near = binary_dilation(extra_land, iterations=2)
        H, W = near.shape
        dets = [d for d in dets if not near[min(max(int(round(d["y"])), 0), H - 1), min(max(int(round(d["x"])), 0), W - 1)]]
        sea = sea & ~near
    return dets, sea


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


def load_extra_land(path, tr, shape):
    """A land mask saved by tools/s2_check.py (watermask), resampled by nearest neighbour onto this pass's grid."""
    z = np.load(path)
    land, t2 = z["land"], z["transform"]                 # t2 = (left, top, res)
    ys = (tr.f + (np.arange(shape[0]) + 0.5) * tr.e - t2[1]) / -t2[2]
    xs = (tr.c + (np.arange(shape[1]) + 0.5) * tr.a - t2[0]) / t2[2]
    yi, xi = np.floor(ys).astype(int), np.floor(xs).astype(int)
    ok_y, ok_x = (yi >= 0) & (yi < land.shape[0]), (xi >= 0) & (xi < land.shape[1])
    out = np.zeros(shape, bool)
    out[np.ix_(ok_y, ok_x)] = land[np.ix_(yi[ok_y], xi[ok_x])]
    return out


def detect_scene(group, box, res, k, buffer_m, max_ships_png=True, min_len=30, ghosts="keep", landmask=None, out_dir=None,
                 min_contrast_db=None):
    item = group["frames"][0]
    out_dir = out_dir or OUT
    info = {}
    a, tr, crs, valid = read_pass(group["frames"], box, res, info=info)
    if valid.mean() < 0.05:
        return None
    extra = load_extra_land(landmask, tr, a.shape) if landmask else None
    dets, sea = detect_array(a, tr, crs, valid, box, res, k, buffer_m, min_len, info.get("along_bearing"), ghosts, extra,
                             min_contrast_db)
    px = [(d["x"], d["y"]) for d in dets]
    dets = to_lonlat(dets, tr, crs, res)
    for d in dets:
        d.pop("peak", None)
    if ghosts == "flag":                                # pixel position of the bright source -> lat, lon
        from rasterio.warp import transform as warp_xy
        for d in dets:
            if "ghost_of" in d:
                gx, gy = d["ghost_of"]
                lo, la = warp_xy(crs, "EPSG:4326", [tr.c + (gx + 0.5) * tr.a], [tr.f + (gy + 0.5) * tr.e])
                d["ghost_of"] = [round(la[0], 5), round(lo[0], 5)]
    os.makedirs(out_dir, exist_ok=True)
    rec = {"scene": item["id"], "frames": [f["id"] for f in group["frames"]], "time": item["properties"]["datetime"], "orbit": item["properties"].get("sat:orbit_state"),
           "res_m": res, "k": k, "land_buffer_m": buffer_m, "min_length_m": min_len, "merge_m": 200, "sea_km2": round(float(sea.sum()) * res * res / 1e6, 1),
           "valid_frac": round(float(valid.mean()), 3), "detections": dets,
           "licence": "Contains modified Copernicus Sentinel data (via Microsoft Planetary Computer)"}
    if ghosts != "keep" or landmask or min_contrast_db is not None:
        rec.update({"ghosts": ghosts, "along_bearing": round(info.get("along_bearing", float("nan")), 2),
                    "extra_landmask": os.path.basename(landmask) if landmask else None, "min_contrast_db": min_contrast_db})
    json.dump(rec, open(os.path.join(out_dir, item["id"] + ".json"), "w", encoding="utf-8"), indent=1)
    if max_ships_png:
        quicklook(a, sea, px, os.path.join(out_dir, item["id"] + ".png"))
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
    ap.add_argument("--ghosts", choices=["keep", "flag", "drop"], default="keep",
                    help="azimuth-ghost candidates: keep (original behaviour), flag (add ghost_of) or drop")
    ap.add_argument("--landmask", help="extra land mask (.npz from tools/s2_check.py watermask): detections on it, or "
                    "within 40 m, are dropped after the CFAR test")
    ap.add_argument("--out", help="output folder (default private/maritime/s1)")
    ap.add_argument("--min-contrast", type=float, help="drop detections whose peak is less than this many dB above the ring's "
                    "sea mean (off by default: original behaviour)")
    a = ap.parse_args()
    if a.cmd == "persist":
        return persist(a.radius, a.share)
    box = area_box(a.area) if a.area else tuple(float(v) for v in a.box.split(","))
    end = datetime.now(timezone.utc); start = end - timedelta(days=a.days)
    items = search(box, start, end)
    if a.scene:                                         # the whole acquisition that frame belongs to (it may need 2 frames)
        keep = [g for g in passes(items) if any(f["id"] == a.scene for f in g["frames"])]
        items = [f for g in keep for f in g["frames"]]
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
            rec = detect_scene(g, box, a.res, a.k, a.buffer, ghosts=a.ghosts, landmask=a.landmask, out_dir=a.out,
                               min_contrast_db=a.min_contrast)
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
