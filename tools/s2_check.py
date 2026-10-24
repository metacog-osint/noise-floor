#!/usr/bin/env python3
"""s2_check.py: check Sentinel-1 ship detections (tools/ship_detect.py) against Sentinel-2 optical images.

Maritime plan, Section 10. Sentinel-2 L2A is read from Microsoft's Planetary Computer as cloud-optimised GeoTIFFs
(anonymous, short-lived signed URLs; Copernicus Sentinel data, free including commercial use, with attribution). Only the
windows covering the box are read: B08 (near infrared, 10 m) to find bright objects on water, SCL (scene classification,
20 m) for water, land and cloud, and small true-colour windows for chips.

  python tools/s2_check.py pairs  --area singapore_johor --days 60          # S1 passes and S2 datatakes, gaps, cloud
  python tools/s2_check.py s1     --area singapore_johor --scene <S1 id>     # cache one S1 pass at 20 m
  python tools/s2_check.py s2     --area singapore_johor --s2 20261023T0307 --orbit 75   # optical objects
  python tools/s2_check.py score  --area singapore_johor --scene <S1 id> --s2 20261023T0307 --orbit 75 [--k 5,6,8,10]
  python tools/s2_check.py fixed  --area singapore_johor                    # fixed_sites.json against cached S2 images
  python tools/s2_check.py stationary --area A --s2 <key> --orbit N --s2b <key> --orbitb M   # two S2 images minutes apart
  python tools/s2_check.py recall --area A --scene <S1 id> --s2 <key> --orbit N [--stationary <json>]
  python tools/s2_check.py chips  --area A --scene <S1 id> --s2 <key> --orbit N [--n 120]
  python tools/s2_check.py bigchips --area A --scene <S1 id> --s2 <key> --orbit N [--n 60] [--min-len 100]  # recall set
  python tools/s2_check.py watermask --area A --s2 <key>:<orbit>,...        # land mask for ship_detect --landmask

The matching rule was fixed before scoring: private/maritime/s2/RULE.md (private, as it names dates only; the public
summary is docs/validation/ships-s1.md). Every output (positions, chips) stays in private/maritime/s2/ (gitignored).
"""
import argparse, json, math, os, sys, time, hashlib
from datetime import datetime, timedelta, timezone

import numpy as np
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ship_detect as S  # noqa: E402

ROOT = S.ROOT
OUT1 = S.OUT
OUT2 = os.path.join(ROOT, "private", "maritime", "s2")
CACHE = os.path.join(OUT2, "cache")
SAS = "https://planetarycomputer.microsoft.com/api/sas/v1/token/{}"
LICENCE = "Contains modified Copernicus Sentinel data 2026 (via Microsoft Planetary Computer)"

# Pre-stated parameters (RULE.md). Changing any of these after scoring must be logged there.
CLOUD_SCL = (3, 8, 9, 10)          # cloud shadow, cloud medium/high probability, thin cirrus
SMALL_CLOUD_KM2 = 0.03             # cloud blobs smaller than this may be ships: not counted as cloud
SMALL_BLOB_KM2 = 0.05              # enclosed non-water blobs smaller than this are objects on the water
ISOLATION_M = 500                  # a ship-sized cloud blob with other cloud this close is cloud (change log, 24 Oct)
CLUTTER_MAX = 3.0                  # object rejected if its ring SD exceeds this many times the scene's clean-water SD
COAST_M = 100                      # optical objects this close to S2 land are coast or island edges, not vessels
TEXTURE_BLOCK_M, TEXTURE_MAX = 500, 1.6   # 500 m blocks of B08 whose robust SD exceeds 1.6 x the scene's clean-water level
                                          # are haze or cloud edges: not clear (grown by one block). Change log, 24 Oct.
CLOUD_GROW_M = 200
OPT_GUARD_M, OPT_RING_M, OPT_K, OPT_DMIN, OPT_MIN_PX = 250, 500, 5.0, 200, 3   # DMIN in L2A units (0.02 reflectance)
CLEAR_R_M, CLEAR_SHARE = 300, 0.9
WATER_R_M, WATER_SHARE = 50, 0.5
R_TIGHT, R_LOOSE = 150.0, 500.0
FIXED_R = 60.0
SHIFT_M = 3000.0
LEN_BINS = ((30, 60), (60, 100), (100, 200), (200, 10000))


# ---------------------------------------------------------------- network, with retries (local DNS drops out at times)

def retry(fn, tries=10, wait=20, what="request"):
    last = None
    for i in range(tries):
        try:
            return fn()
        except (requests.RequestException, OSError, ValueError, KeyError) as e:   # network and IO (DNS drops are transient)
            last = e
            print(f"  {what} failed ({type(e).__name__}: {str(e)[:120]}); retry {i + 1}/{tries} in {wait} s", flush=True)
            time.sleep(wait)
    raise last


def stac(body):
    """STAC search with an on-disk cache (catalogue answers for past dates don't change)."""
    os.makedirs(os.path.join(CACHE, "stac"), exist_ok=True)
    key = hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]
    p = os.path.join(CACHE, "stac", key + ".json")
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    feats = retry(lambda: requests.post(S.STAC, json=body, headers=S.UA, timeout=60).json()["features"], what="STAC")
    json.dump(feats, open(p, "w", encoding="utf-8"))
    return feats


_TOK = {}


def sign(href, collection):
    t = _TOK.get(collection)
    if not t or time.time() - t[1] > 1800:
        tok = retry(lambda: requests.get(SAS.format(collection), headers=S.UA, timeout=30).json()["token"], what="SAS token")
        _TOK[collection] = t = (tok, time.time())
    return href + ("&" if "?" in href else "?") + t[0]


def gdal_env():
    import rasterio
    return rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="6", GDAL_HTTP_RETRY_DELAY="5",
                        CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif", GDAL_CACHEMAX=512, VSI_CACHE=True)


# ---------------------------------------------------------------- grid shared with ship_detect (20 m) and S2 (10 m)

class Grid:
    """The UTM grid ship_detect.read_box uses at 20 m; the S2 grid is the same origin at 10 m (exactly 2x2 per S1 pixel)."""

    def __init__(self, box):
        from rasterio.warp import transform_bounds
        lat0, lat1, lon0, lon1 = box
        self.box = box
        self.crs = f"EPSG:{S.utm_epsg((lat0 + lat1) / 2, (lon0 + lon1) / 2)}"
        left, bottom, right, top = transform_bounds("EPSG:4326", self.crs, lon0, lat0, lon1, lat1)
        self.left, self.top = left, top
        self.w20, self.h20 = int((right - left) / 20), int((top - bottom) / 20)

    def tr(self, res):
        from rasterio.transform import from_origin
        return from_origin(self.left, self.top, res, res)

    def xy(self, r, c, res):
        return self.left + (np.asarray(c) + 0.5) * res, self.top - (np.asarray(r) + 0.5) * res

    def rc(self, x, y, res):
        return (self.top - np.asarray(y)) / res - 0.5, (np.asarray(x) - self.left) / res - 0.5

    def lonlat(self, x, y):
        from rasterio.warp import transform as warp_xy
        if len(x) == 0:
            return [], []
        lons, lats = warp_xy(self.crs, "EPSG:4326", list(map(float, x)), list(map(float, y)))
        return np.array(lons), np.array(lats)

    def to_xy(self, lons, lats):
        from rasterio.warp import transform as warp_xy
        if len(lons) == 0:
            return np.zeros(0), np.zeros(0)
        x, y = warp_xy("EPSG:4326", self.crs, list(map(float, lons)), list(map(float, lats)))
        return np.array(x), np.array(y)


def area_box(a):
    if a.area:
        return S.area_box(a.area)
    return tuple(float(v) for v in a.box.split(","))


# ---------------------------------------------------------------- Sentinel-1 side

def s1_record(scene):
    p = os.path.join(OUT1, scene + ".json")
    if not os.path.exists(p):
        sys.exit(f"no {p}: run tools/ship_detect.py detect first")
    return json.load(open(p, encoding="utf-8"))


def s1_pass(scene, box):
    """The S1 pass on the 20 m grid, cached as .npz (array, valid mask, along-track bearing)."""
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, f"s1_{scene}.npz")
    if not os.path.exists(p):
        rec = s1_record(scene)
        items = stac({"collections": ["sentinel-1-grd"], "ids": rec["frames"], "limit": 10})
        items = sorted(items, key=lambda it: rec["frames"].index(it["id"]))
        info = {}
        t0 = time.time()
        a, tr, crs, valid = retry(lambda: S.read_pass(items, box, 20.0, info=info), what="S1 read")
        np.savez(p, a=a.astype(np.float32), valid=valid, along=info.get("along_bearing", np.nan),
                 time=rec["time"], orbit=rec["orbit"])
        print(f"cached S1 {scene} in {time.time() - t0:.0f} s; along-track bearing {info.get('along_bearing', float('nan')):.1f} deg")
    z = np.load(p)
    return {"a": z["a"], "valid": z["valid"], "along": float(z["along"]), "time": str(z["time"]), "orbit": str(z["orbit"])}


def variant(spec):
    """A detector variant as text: '<k>[:c<dB>][:gdrop][:land]', e.g. '6' (original), '6:c10:gdrop:land'."""
    parts = str(spec).split(":")
    v = {"k": float(parts[0]), "min_db": None, "ghosts": "flag", "land": False}
    for p_ in parts[1:]:
        if p_.startswith("c"):
            v["min_db"] = float(p_[1:])
        elif p_ == "gdrop":
            v["ghosts"] = "drop"
        elif p_ == "land":
            v["land"] = True
    return v


_LAND = {}


def s2_landmask(g):
    p = os.path.join(OUT2, "s2_landmask.npz")
    if p not in _LAND:
        if not os.path.exists(p):
            sys.exit("no private/maritime/s2/s2_landmask.npz: run the watermask command first")
        _LAND[p] = S.load_extra_land(p, g.tr(20), (g.h20, g.w20))
    return _LAND[p]


def s1_detect(scene, box, g, k, ghosts="flag", extra_land=None, spec=None):
    """Rerun ship_detect's pipeline on the cached pass at threshold k (or a variant spec, see variant()).
    Returns (detections, sea mask, pass)."""
    sp = s1_pass(scene, box)
    min_db = None
    if spec is not None:
        v = variant(spec)
        k, ghosts, min_db = v["k"], v["ghosts"], v["min_db"]
        extra_land = s2_landmask(g) if v["land"] else None
    dets, sea = S.detect_array(sp["a"], g.tr(20), g.crs, sp["valid"], box, 20.0, k=k, along_bearing=sp["along"],
                               ghosts=ghosts, extra_land=extra_land, min_contrast_db=min_db)
    x, y = g.xy(np.array([d["y"] for d in dets]), np.array([d["x"] for d in dets]), 20)
    lon, lat = g.lonlat(x, y)
    out = []
    for i, d in enumerate(dets):
        out.append({"i": i, "x_m": float(x[i]), "y_m": float(y[i]), "lat": round(float(lat[i]), 5), "lon": round(float(lon[i]), 5),
                    "length_m": round(d["length_px"] * 20), "px": d["px"], "peak_ratio": d["peak_ratio"],
                    "peak_db": round(10 * math.log10(max(d["peak"], 1e-9)), 2), "ghost_of": d.get("ghost_of")})
    return out, sea, sp


def fixed_xy(g):
    p = os.path.join(OUT1, "fixed_sites.json")
    if not os.path.exists(p):
        return np.zeros((0, 2))
    f = json.load(open(p, encoding="utf-8"))["fixed"]
    x, y = g.to_xy([s["lon"] for s in f], [s["lat"] for s in f])
    return np.column_stack([x, y])


# ---------------------------------------------------------------- Sentinel-2 side

def s2_items(box, key, orbit):
    """Tiles of one S2 datatake (key YYYYMMDDTHHMM, relative orbit); of reprocessed duplicates keep the newest."""
    lat0, lat1, lon0, lon1 = box
    t = datetime.strptime(key, "%Y%m%dT%H%M").replace(tzinfo=timezone.utc)
    body = {"collections": ["sentinel-2-l2a"], "bbox": [lon0, lat0, lon1, lat1], "limit": 100,
            "datetime": f"{t - timedelta(minutes=3):%Y-%m-%dT%H:%M:%SZ}/{t + timedelta(minutes=4):%Y-%m-%dT%H:%M:%SZ}"}
    best = {}
    for it in stac(body):
        if int(it["properties"].get("sat:relative_orbit", -1)) != int(orbit):
            continue
        tile = it["properties"]["s2:mgrs_tile"]
        if tile not in best or it["id"].split("_")[-1] > best[tile]["id"].split("_")[-1]:
            best[tile] = it
    return sorted(best.values(), key=lambda it: it["id"])


def s2_subgrid(items, g):
    """Bounding window (10 m rows/cols, even numbers) of the datatake's footprint inside the box."""
    from shapely.geometry import shape, box as sbox
    from shapely.ops import unary_union
    lat0, lat1, lon0, lon1 = g.box
    fp = unary_union([shape(it["geometry"]) for it in items]).intersection(sbox(lon0, lat0, lon1, lat1))
    if fp.is_empty:
        return None
    lo0, la0, lo1, la1 = fp.bounds
    xs, ys = g.to_xy([lo0, lo1, lo0, lo1], [la0, la0, la1, la1])
    r0, c0 = g.rc(xs.min(), ys.max(), 10)
    r1, c1 = g.rc(xs.max(), ys.min(), 10)
    r0, c0 = max(0, int(r0) // 2 * 2 - 2), max(0, int(c0) // 2 * 2 - 2)
    r1, c1 = min(2 * g.h20, (int(r1) // 2 + 2) * 2), min(2 * g.w20, (int(c1) // 2 + 2) * 2)
    return r0, c0, r1 - r0, c1 - c0


def s2_read(items, asset, res, g, sub):
    """One band of a datatake on (a sub-window of) the shared grid at res (10 or 20 m); 0 where there is no data."""
    import rasterio
    from rasterio.windows import from_bounds, Window
    from rasterio.enums import Resampling
    r0, c0, h, w = sub
    f = 10 / res
    r0, c0, h, w = int(r0 * f), int(c0 * f), int(h * f), int(w * f)
    left, top = g.left + c0 * res, g.top - r0 * res
    out = None
    for it in items:
        def one():
            with gdal_env(), rasterio.open(sign(it["assets"][asset]["href"], "sentinel-2-l2a")) as src:
                if str(src.crs).upper() != g.crs.upper() and src.crs.to_epsg() != int(g.crs.split(":")[1]):
                    print(f"  {it['id']}: CRS {src.crs} differs from the grid; skipped"); return None
                b = src.bounds
                gx0 = max(0, math.ceil((b.left - left) / res)); gx1 = min(w, math.floor((b.right - left) / res))
                gy0 = max(0, math.ceil((top - b.top) / res)); gy1 = min(h, math.floor((top - b.bottom) / res))
                if gx1 <= gx0 or gy1 <= gy0:
                    return None
                win = from_bounds(left + gx0 * res, top - gy1 * res, left + gx1 * res, top - gy0 * res, src.transform)
                if abs(src.res[0] - res) < 1e-6:    # same pixel size: snap to whole pixels (shift <= res/2); GDAL is
                    co, ro = max(0, int(round(win.col_off))), max(0, int(round(win.row_off)))
                    win = Window(co, ro, min(gx1 - gx0, src.width - co), min(gy1 - gy0, src.height - ro))   # much faster
                    data = src.read(1, window=win)
                else:
                    data = src.read(1, window=win, out_shape=(gy1 - gy0, gx1 - gx0), resampling=Resampling.nearest)
                return gy0, gx0, data
        got = retry(one, what=f"S2 {asset} {it['properties']['s2:mgrs_tile']}")
        if out is None:
            out = np.zeros((h, w), np.uint16 if asset != "SCL" else np.uint8)
        if got is None:
            continue
        gy0, gx0, data = got
        dst = out[gy0:gy0 + data.shape[0], gx0:gx0 + data.shape[1]]
        m = (dst == 0) & (data > 0)
        dst[m] = data[m]
    return out


def remove_small(mask, min_px):
    from scipy.ndimage import label
    lab, n = label(mask, structure=np.ones((3, 3)))
    if n == 0:
        return mask
    sizes = np.bincount(lab.ravel())
    keep = sizes >= min_px
    keep[0] = False
    return keep[lab]


def s2_masks(scl):
    """Water region, land, cloud and clear masks at 20 m from SCL (pre-stated rule)."""
    from scipy.ndimage import label, binary_dilation
    px_km2 = 20 * 20 / 1e6
    valid = scl > 0
    water = scl == 6
    cloud_all = np.isin(scl, CLOUD_SCL)
    cloud_big = remove_small(cloud_all, int(round(SMALL_CLOUD_KM2 / px_km2)))
    # A ship-sized cloud blob may be a ship unless real cloud is near: a large cloud blob, cloud shadow (SCL 3) or cirrus
    # (SCL 10) within about 500 m makes it cloud. Other ship-sized blobs are not evidence: anchored ships are often
    # labelled cloud (SCL 8) and sit in groups (change log, 24 Oct 2026, run v2).
    small = cloud_all & ~cloud_big
    if small.any():
        from scipy.ndimage import uniform_filter, label as _label, maximum
        n = 2 * int(ISOLATION_M / 20) + 1
        real = cloud_big | (scl == 3) | (scl == 10)
        around = uniform_filter(real.astype(np.float32), size=n, mode="constant") * n * n
        lab_s, ns = _label(small, structure=np.ones((3, 3)))
        worst = np.asarray(maximum(around, lab_s, index=np.arange(1, ns + 1)))
        cloudy = np.concatenate([[False], worst > 0.5])
        cloud_big = cloud_big | cloudy[lab_s]
    nonwater = valid & ~water & ~cloud_big
    lab, n = label(nonwater, structure=np.ones((3, 3)))
    sizes = np.bincount(lab.ravel())
    small = sizes < int(round(SMALL_BLOB_KM2 / px_km2))
    small[0] = False
    blobs = small[lab]
    region = (water | blobs) & valid
    land = nonwater & ~blobs
    cloud = binary_dilation(cloud_big, iterations=int(CLOUD_GROW_M / 20)) & valid
    clear = valid & ~cloud
    return {"valid": valid, "water": water, "region": region, "land": land, "clear": clear}


def up2(m):
    return np.repeat(np.repeat(m, 2, axis=0), 2, axis=1)


def opt_objects(b08, bg, cand, k=OPT_K, dmin=OPT_DMIN, guard=OPT_GUARD_M // 10, ring=OPT_RING_M // 10, min_px=OPT_MIN_PX,
                max_px=3000, block=2048):
    """Bright objects on water in B08 (10 m): pixel above the mean of a ring of water pixels by k SD and by dmin,
    inside `cand` (water region and clear). Processed in blocks; returns a list of objects in pixel coordinates."""
    from scipy.ndimage import uniform_filter, label, find_objects
    H, W = b08.shape
    hit = np.zeros((H, W), bool)
    mean_all = np.zeros((H, W), np.float32)
    sd_all = np.zeros((H, W), np.float32)
    full = (2 * ring + 1) ** 2 - (2 * guard + 1) ** 2
    for y in range(0, H, block):
        for x in range(0, W, block):
            ya, yb, xa, xb = max(0, y - ring), min(H, y + block + ring), max(0, x - ring), min(W, x + block + ring)
            if not cand[max(y, ya):min(y + block, H), max(x, xa):min(x + block, W)].any():
                continue
            v = b08[ya:yb, xa:xb].astype(np.float64)
            m = bg[ya:yb, xa:xb].astype(np.float64)
            off = np.median(v[m > 0]) if (m > 0).any() else 0.0
            vv = (v - off) * m

            def bs(arr, r):
                n = 2 * r + 1
                return uniform_filter(arr, size=n, mode="constant") * n * n
            s = bs(vv, ring) - bs(vv, guard); q = bs(vv * vv, ring) - bs(vv * vv, guard); n = bs(m, ring) - bs(m, guard)
            nn = np.maximum(n, 1)
            mean = s / nn
            sd = np.sqrt(np.maximum(q / nn - mean * mean, 1.0))
            iy0, ix0 = y - ya, x - xa
            iy1, ix1 = iy0 + min(block, H - y), ix0 + min(block, W - x)
            vi, mi, si, ni = (v - off)[iy0:iy1, ix0:ix1], mean[iy0:iy1, ix0:ix1], sd[iy0:iy1, ix0:ix1], n[iy0:iy1, ix0:ix1]
            c = cand[y:y + iy1 - iy0, x:x + ix1 - ix0]
            hit[y:y + iy1 - iy0, x:x + ix1 - ix0] = c & (ni > 0.3 * full) & (vi > mi + k * si) & (vi - mi > dmin)
            mean_all[y:y + iy1 - iy0, x:x + ix1 - ix0] = (mi + off).astype(np.float32)
            sd_all[y:y + iy1 - iy0, x:x + ix1 - ix0] = si.astype(np.float32)
    lab, num = label(hit, structure=np.ones((3, 3)))
    objs = []
    for i, sl in enumerate(find_objects(lab), 1):
        if sl is None:
            continue
        ys, xs = np.nonzero(lab[sl] == i)
        if len(ys) < min_px or len(ys) > max_px:
            continue
        ys = ys + sl[0].start; xs = xs + sl[1].start
        ex = np.maximum(b08[ys, xs].astype(np.float64) - mean_all[ys, xs], 1.0)
        cy, cx = float(np.average(ys, weights=ex)), float(np.average(xs, weights=ex))
        if len(ys) >= 3:
            cov = np.cov(np.vstack([xs, ys]).astype(float))
            wv, vec = np.linalg.eigh(cov)
            u = vec[:, -1]
            pa = xs * u[0] + ys * u[1]; pb = -xs * u[1] + ys * u[0]
            length, width = float(pa.max() - pa.min() + 1), float(pb.max() - pb.min() + 1)
            heading = (math.degrees(math.atan2(u[0], -u[1])) + 360) % 180      # axis bearing, 0-180
        else:
            length = width = float(math.sqrt(len(ys))); heading = None
        objs.append({"r": cy, "c": cx, "px": int(len(ys)), "length_m": round(length * 10), "width_m": round(width * 10),
                     "axis": None if heading is None else round(heading, 1),
                     "peak_refl": round((float(b08[ys, xs].max()) - 1000) / 10000, 4),
                     "excess": round(float(ex.max()) / 10000, 4), "ring_sd": round(float(sd_all[int(cy), int(cx)]), 1)})
    samp = sd_all[cand & (sd_all > 0)][::97]
    ref_sd = float(np.median(samp)) if samp.size else float("nan")
    for o in objs:
        o["clutter"] = round(o["ring_sd"] / ref_sd, 2) if ref_sd > 0 else None
    return objs, ref_sd


def texture_mask(b08, cand10, block=TEXTURE_BLOCK_M // 10, tmax=TEXTURE_MAX):
    """Hazy or cloud-edge water at 20 m: blocks whose robust SD (1.4826 x MAD of candidate water pixels) exceeds tmax x
    the median over blocks that are mostly candidate water; grown by one block. Returns (mask at 20 m, ratio map, ref)."""
    from scipy.ndimage import binary_dilation
    H, W = b08.shape
    nb_y, nb_x = -(-H // block), -(-W // block)
    pad = np.full((nb_y * block, nb_x * block), np.nan, np.float32)
    pad[:H, :W] = np.where(cand10, b08, np.nan)
    blk = pad.reshape(nb_y, block, nb_x, block).transpose(0, 2, 1, 3).reshape(nb_y, nb_x, block * block)
    share = np.isfinite(blk).mean(-1)
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            med = np.nanmedian(blk, -1)
            mad = 1.4826 * np.nanmedian(np.abs(blk - med[..., None]), -1)
    ok = share > 0.5
    ref = float(np.nanmedian(mad[ok])) if ok.any() else float("nan")
    ratio = mad / ref
    bad = (share > 0.05) & (ratio > tmax)
    bad = binary_dilation(bad, structure=np.ones((3, 3)))
    b20 = block // 2
    m20 = np.repeat(np.repeat(bad, b20, 0), b20, 1)[:H // 2, :W // 2]
    return m20, ratio, ref


def robust_ring_sd(b08, rr, cc, inner=OPT_GUARD_M // 10, outer=OPT_RING_M // 10):
    """1.4826 x median absolute deviation of all valid B08 pixels in an annulus around each (row, col): cloud and haze
    texture raise it, a few other ships in the ring don't."""
    yy, xx = np.mgrid[-outer:outer + 1, -outer:outer + 1]
    ann = ((yy * yy + xx * xx) <= outer * outer) & ((yy * yy + xx * xx) > inner * inner)
    H, W = b08.shape
    out = np.full(len(rr), np.nan)
    for i, (y, x) in enumerate(zip(rr, cc)):
        y, x = int(round(y)), int(round(x))
        if y - outer < 0 or x - outer < 0 or y + outer >= H or x + outer >= W:
            continue
        v = b08[y - outer:y + outer + 1, x - outer:x + outer + 1][ann]
        v = v[v > 0].astype(np.float64)
        if v.size > 100:
            out[i] = 1.4826 * float(np.median(np.abs(v - np.median(v))))
    return out


def s2_scene(box, key, orbit, g, keep_b08=True, rebuild=False):
    """Read one S2 datatake over the box, build masks and optical objects. Raw bands are cached
    (cache/raw_<tag>.npz) so masks and objects can be rebuilt without downloading again; results in s2_<tag>.json."""
    tag = f"s2_{key}_R{int(orbit):03d}"
    pj, pn, praw = (os.path.join(OUT2, tag + ".json"), os.path.join(CACHE, tag + ".npz"),
                    os.path.join(CACHE, "raw_" + tag + ".npz"))
    if not rebuild and os.path.exists(pj) and os.path.exists(pn):
        rec = json.load(open(pj, encoding="utf-8"))
        z = np.load(pn)
        rec["masks"] = {k: z[k] for k in ("valid", "water", "region", "land", "clear")}
        if keep_b08:
            rec["b08"] = np.load(praw)["b08"] if os.path.exists(praw) else z["b08"]
        return rec
    items = s2_items(box, key, orbit)
    if not items:
        sys.exit(f"no S2 items for {key} R{orbit}")
    sub = s2_subgrid(items, g)
    t0 = time.time()
    old = np.load(pn) if os.path.exists(pn) else None
    if os.path.exists(praw):
        z = np.load(praw); b08, scl = z["b08"], z["scl"]
    else:
        scl = s2_read(items, "SCL", 20, g, sub)
        b08 = old["b08"] if (old is not None and "b08" in old) else s2_read(items, "B08", 10, g, sub)
        os.makedirs(CACHE, exist_ok=True)
        np.savez(praw, b08=b08, scl=scl, sub=np.array(sub))
        print(f"read {len(items)} tiles of {key} R{orbit} ({b08.shape[0]} x {b08.shape[1]} px at 10 m) in {time.time() - t0:.0f} s", flush=True)
    masks = s2_masks(scl)
    valid10 = b08 > 0
    tex, _, tex_ref = texture_mask(b08, up2(masks["region"] & masks["clear"]) & valid10)
    masks["textured"] = tex & masks["clear"]
    masks["clear"] = masks["clear"] & ~tex
    region10, clear10, water10 = up2(masks["region"]), up2(masks["clear"]), up2(masks["water"])
    objs_all, ref_sd = opt_objects(b08, water10 & clear10 & valid10, region10 & clear10 & valid10)
    r0, c0, h, w = sub
    x, y = g.xy(np.array([o["r"] for o in objs_all]) + r0, np.array([o["c"] for o in objs_all]) + c0, 10)
    lon, lat = g.lonlat(x, y)
    for o, xi, yi, lo, la in zip(objs_all, x, y, lon, lat):
        o.update({"x_m": float(xi), "y_m": float(yi), "lat": round(float(la), 5), "lon": round(float(lo), 5)})
        o.pop("r"); o.pop("c")
    # clutter: robust ring SD at the object against the same measure at random clear-water points (scene reference)
    orr, occ = g.rc(x, y, 10)
    rsd = robust_ring_sd(b08, np.asarray(orr) - r0, np.asarray(occ) - c0)
    cy, cx = np.nonzero((region10 & clear10 & valid10)[::50, ::50])
    pick = np.random.default_rng(0).choice(len(cy), min(3000, len(cy)), replace=False) if len(cy) else []
    ref = float(np.nanmedian(robust_ring_sd(b08, cy[pick] * 50, cx[pick] * 50))) if len(cy) else float("nan")
    for o, v in zip(objs_all, rsd):
        o["ring_mad_sd"] = None if not np.isfinite(v) else round(float(v), 1)
        o["clutter"] = None if not (np.isfinite(v) and ref > 0) else round(float(v) / ref, 2)
    ref_sd = ref
    from scipy.ndimage import binary_dilation
    coast = binary_dilation(masks["land"], iterations=int(COAST_M / 20))
    orr20, occ20 = g.rc(x, y, 20)
    for o, a_, b_ in zip(objs_all, np.asarray(orr20) - r0 // 2, np.asarray(occ20) - c0 // 2):
        ia, ib = int(round(a_)), int(round(b_))
        o["coast"] = bool(0 <= ia < coast.shape[0] and 0 <= ib < coast.shape[1] and coast[ia, ib])
    keep = [o["clutter"] is not None and o["clutter"] <= CLUTTER_MAX and not o["coast"] for o in objs_all]
    objs = [o for o, k_ in zip(objs_all, keep) if k_]
    n_coast = sum(o["coast"] for o in objs_all)
    print(f"  {len(objs_all)} bright objects; {n_coast} within {COAST_M} m of land; {len(objs_all) - len(objs) - n_coast} more "
          f"rejected as cloud or haze texture (ring SD > {CLUTTER_MAX:g} x scene clean-water SD {ref_sd:.0f})", flush=True)
    px_km2 = 400 / 1e6
    rec = {"key": key, "orbit": int(orbit), "items": [it["id"] for it in items],
           "time": items[0]["properties"]["datetime"], "platform": items[0]["properties"]["platform"],
           "sub": list(sub), "grid_crs": g.crs,
           "valid_km2": round(float(masks["valid"].sum()) * px_km2, 1),
           "clear_water_km2": round(float((masks["region"] & masks["clear"]).sum()) * px_km2, 1),
           "ref_sd": round(ref_sd, 1), "texture_ref_sd": round(tex_ref, 1),
           "textured_km2": round(float(masks["textured"].sum()) * px_km2, 1),
           "params": {"cloud_scl": CLOUD_SCL, "small_cloud_km2": SMALL_CLOUD_KM2, "small_blob_km2": SMALL_BLOB_KM2,
                      "isolation_m": ISOLATION_M, "clutter_max": CLUTTER_MAX, "texture_block_m": TEXTURE_BLOCK_M,
                      "texture_max": TEXTURE_MAX, "coast_m": COAST_M,
                      "cloud_grow_m": CLOUD_GROW_M, "guard_m": OPT_GUARD_M, "ring_m": OPT_RING_M, "k": OPT_K,
                      "dmin": OPT_DMIN, "min_px": OPT_MIN_PX},
           "objects": objs, "rejected_clutter": [o for o, k_ in zip(objs_all, keep) if not k_], "licence": LICENCE}
    os.makedirs(OUT2, exist_ok=True)
    json.dump(rec, open(pj, "w", encoding="utf-8"), indent=1)
    np.savez(pn, **masks)
    print(f"{tag}: {len(objs)} optical objects over {rec['clear_water_km2']} km2 of clear water", flush=True)
    rec["masks"] = masks
    if keep_b08:
        rec["b08"] = b08
    return rec


# ---------------------------------------------------------------- scoring

def disk(r_px):
    r = int(math.ceil(r_px))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    return (yy * yy + xx * xx) <= r_px * r_px


def frac_at(mask, rr, cc, kern):
    """Share of True pixels of `mask` in a disk around each (row, col) on the 20 m sub-grid; NaN off the grid."""
    r = kern.shape[0] // 2
    H, W = mask.shape
    out = np.full(len(rr), np.nan)
    for i, (y, x) in enumerate(zip(rr, cc)):
        y, x = int(round(y)), int(round(x))
        if y - r < 0 or x - r < 0 or y + r >= H or x + r >= W:
            continue
        out[i] = float(mask[y - r:y + r + 1, x - r:x + r + 1][kern].mean())
    return out


def s2_state(s2, g, xs, ys, with_coast=False):
    """For points (UTM x, y): scorable (clear water), land leak, or neither, against one S2 scene."""
    r0, c0 = s2["sub"][0] // 2, s2["sub"][1] // 2
    rr, cc = g.rc(np.asarray(xs), np.asarray(ys), 20)
    rr, cc = rr - r0, cc - c0
    m = s2["masks"]
    clear = frac_at(m["clear"] & m["valid"], rr, cc, disk(CLEAR_R_M / 20))
    water = frac_at(m["region"], rr, cc, disk(WATER_R_M / 20))
    land = frac_at(m["land"], rr, cc, disk(WATER_R_M / 20))
    near_clear = frac_at(m["clear"] & m["valid"], rr, cc, disk(WATER_R_M / 20))
    scorable = (clear >= CLEAR_SHARE) & (water >= WATER_SHARE)
    leak = (near_clear >= CLEAR_SHARE) & (land >= WATER_SHARE)
    if with_coast:
        coast = frac_at(m["land"], rr, cc, disk(COAST_M / 20))
        return np.nan_to_num(scorable).astype(bool), np.nan_to_num(leak).astype(bool), np.nan_to_num(coast) > 0
    return np.nan_to_num(scorable).astype(bool), np.nan_to_num(leak).astype(bool)


def in_mask20(mask, g, xs, ys):
    rr, cc = g.rc(np.asarray(xs), np.asarray(ys), 20)
    rr, cc = np.round(rr).astype(int), np.round(cc).astype(int)
    ok = (rr >= 0) & (cc >= 0) & (rr < mask.shape[0]) & (cc < mask.shape[1])
    out = np.zeros(len(rr), bool)
    out[ok] = mask[rr[ok], cc[ok]]
    return out


def shifts():
    return [(SHIFT_M * math.sin(math.radians(a)), SHIFT_M * math.cos(math.radians(a))) for a in range(0, 360, 45)]


def nearest(tree_pts, xs, ys):
    from scipy.spatial import cKDTree
    if len(tree_pts) == 0:
        return np.full(len(xs), np.inf)
    return cKDTree(tree_pts).query(np.column_stack([xs, ys]))[0]


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


def corrected(m, c):
    return float("nan") if c >= 1 or math.isnan(m) or math.isnan(c) else (m - c) / (1 - c)


def len_bin(L):
    for lo, hi in LEN_BINS:
        if lo <= L < hi:
            return f"{lo}-{hi - 1}" if hi < 10000 else f"{lo}+"
    return f"<{LEN_BINS[0][0]}"


def score_pass(dets, sea, s2, g, fixed):
    """Apply the pre-stated rule to one S1 detection list against one S2 scene. Adds per-detection fields and returns
    the control distances (for the chance correction)."""
    objs = np.array([(o["x_m"], o["y_m"]) for o in s2["objects"]]) if s2["objects"] else np.zeros((0, 2))
    xs, ys = np.array([d["x_m"] for d in dets]), np.array([d["y_m"] for d in dets])
    sc, leak, coast = s2_state(s2, g, xs, ys, with_coast=True)
    dist = nearest(objs, xs, ys)
    dfix = nearest(fixed, xs, ys)
    for d, s, l, cst, dd, df in zip(dets, sc, leak, coast, dist, dfix):
        d.update({"scorable": bool(s), "land_leak": bool(l and not s), "coast": bool(cst),
                  "d_s2_m": None if not np.isfinite(dd) else round(float(dd)), "fixed": bool(df <= FIXED_R)})
    ctrl = []                                          # (detection index, distance) for moved points that qualify
    for dx, dy in shifts():
        cx, cy = xs + dx, ys + dy
        ok = in_mask20(sea, g, cx, cy)
        s_ok, _ = s2_state(s2, g, cx, cy)
        ok &= s_ok
        dd = nearest(objs, cx[ok], cy[ok])
        ctrl += list(zip(np.nonzero(ok)[0].tolist(), dd.tolist()))
    return ctrl


def summarise(dets, ctrl, select, R):
    """m (confirmed share), c (control share) and chance-corrected q for detections passing `select`."""
    idx = [i for i, d in enumerate(dets) if d["scorable"] and select(d)]
    n = len(idx)
    k = sum(1 for i in idx if dets[i]["d_s2_m"] is not None and dets[i]["d_s2_m"] <= R)
    sel = set(idx)
    cd = [dd for i, dd in ctrl if i in sel]
    kc = sum(1 for dd in cd if dd <= R)
    m = k / n if n else float("nan")
    c = kc / len(cd) if cd else float("nan")
    return {"n": n, "confirmed": k, "m": round(m, 3), "m_ci": wilson(k, n), "control_n": len(cd), "c": round(c, 3),
            "q": round(corrected(m, c), 3), "q_ci": [round(corrected(v, c), 3) for v in wilson(k, n)]}


def strata_table(dets, ctrl):
    rows = []
    groups = [("all", lambda d: True), ("fixed", lambda d: d["fixed"]), ("other", lambda d: not d["fixed"]),
              ("within 100 m of S2 land", lambda d: d.get("coast", False)),
              ("other, open water", lambda d: not d["fixed"] and not d.get("coast", False)),
              ("ghost candidates", lambda d: d["ghost_of"] is not None),
              ("other, not ghost", lambda d: not d["fixed"] and d["ghost_of"] is None)]
    for lo, hi in LEN_BINS:
        groups.append((f"other, length {len_bin(lo)} m", lambda d, lo=lo, hi=hi: not d["fixed"] and lo <= d["length_m"] < hi))
    for name, f in groups:
        rows.append({"stratum": name, "tight": summarise(dets, ctrl, f, R_TIGHT), "loose": summarise(dets, ctrl, f, R_LOOSE)})
    return rows


def cmd_score(a, box, g):
    s2 = s2_scene(box, a.s2, a.orbit, g, keep_b08=False)
    fixed = fixed_xy(g)
    out = {"scene": a.scene, "s2": s2["key"], "s2_orbit": s2["orbit"], "s2_time": s2["time"], "rule": "private/maritime/s2/RULE.md",
           "by_k": {}}
    sp = s1_pass(a.scene, box)
    t1 = datetime.fromisoformat(sp["time"].replace("Z", "+00:00"))
    t2 = datetime.fromisoformat(s2["time"].replace("Z", "+00:00"))
    out["gap_h"] = round((t2 - t1).total_seconds() / 3600, 2)
    dens_done = False
    for k in a.k.split(","):
        dets, sea, _ = s1_detect(a.scene, box, g, None, spec=k)
        ctrl = score_pass(dets, sea, s2, g, fixed)
        if not dens_done:                               # S2 objects in the same water: scorable and inside the S1 sea mask
            ox, oy = np.array([o["x_m"] for o in s2["objects"]]), np.array([o["y_m"] for o in s2["objects"]])
            o_ok, _, o_coast = s2_state(s2, g, ox, oy, with_coast=True)
            o_ok &= in_mask20(sea, g, ox, oy) & ~o_coast
            # common area: S1 sea and S2 clear water, sampled on a 200 m lattice with the same scorable test
            r0_, c0_, h_, w_ = s2["sub"]
            yy, xx = np.mgrid[r0_ // 2:(r0_ + h_) // 2:10, c0_ // 2:(c0_ + w_) // 2:10]
            lx, ly = g.xy(yy.ravel(), xx.ravel(), 20)
            l_ok, _, l_coast = s2_state(s2, g, lx, ly, with_coast=True)
            l_ok &= in_mask20(sea, g, lx, ly) & ~l_coast
            area = float(l_ok.sum()) * 0.04
            olen = np.array([o["length_m"] for o in s2["objects"]])
            out["density"] = {"common_km2": round(area, 1),
                              "s2_objects": {len_bin(lo) if lo >= 30 else "10-29": int((o_ok & (olen >= lo) & (olen < hi)).sum())
                                             for lo, hi in ((10, 30),) + LEN_BINS}}
            out["density"]["s2_objects"]["all"] = int(o_ok.sum())
            dens_done = True
        d_ok = [d for d in dets if d["scorable"] and not d["coast"]]
        dens = {len_bin(lo): sum(1 for d in d_ok if lo <= d["length_m"] < hi) for lo, hi in LEN_BINS}
        dens["all"] = len(d_ok)
        out["density"][f"s1_{k}"] = dens
        r0, c0, h, w = s2["sub"]
        rr, cc = g.rc(np.array([d["x_m"] for d in dets]), np.array([d["y_m"] for d in dets]), 20)
        rr, cc = (rr - r0 // 2).astype(int), (cc - c0 // 2).astype(int)
        inside = (rr >= 0) & (cc >= 0) & (rr < h // 2) & (cc < w // 2)
        inside[inside] = s2["masks"]["valid"][rr[inside], cc[inside]]
        res = {"detections": len(dets), "in_s2_footprint": int(inside.sum()),
               "scorable": sum(d["scorable"] for d in dets), "land_leak": sum(d["land_leak"] for d in dets),
               "ghost_candidates": sum(d["ghost_of"] is not None for d in dets),
               "strata": strata_table(dets, ctrl)}
        out["by_k"][str(k)] = res
        ktag = k.replace(":", "_")
        json.dump(dets, open(os.path.join(OUT2, f"dets_{a.scene[17:32]}_{s2['key']}_k{ktag}.json"), "w", encoding="utf-8"))
        print(f"k={k}: {len(dets)} detections, {res['in_s2_footprint']} in S2 footprint, {res['scorable']} scorable, "
              f"{res['land_leak']} land leaks, {res['ghost_candidates']} ghost candidates")
        for row in res["strata"]:
            t, l = row["tight"], row["loose"]
            print(f"   {row['stratum']:28} n={t['n']:5d}  tight m={t['m']:.3f} c={t['c']:.3f} q={t['q']:.3f}   "
                  f"loose m={l['m']:.3f} c={l['c']:.3f} q={l['q']:.3f} {l['q_ci']}")
    print("density over", out["density"]["common_km2"], "km2 of common clear water:", json.dumps({k: v for k, v in out["density"].items() if k != "common_km2"}))
    json.dump(out, open(os.path.join(OUT2, f"score_{a.scene[17:32]}_{s2['key']}{a.tag}.json"), "w", encoding="utf-8"), indent=1)


# ---------------------------------------------------------------- other checks

def cmd_pairs(a, box, g):
    lat0, lat1, lon0, lon1 = box
    end = datetime.now(timezone.utc); start = end - timedelta(days=a.days)
    dt = f"{start:%Y-%m-%dT00:00:00Z}/{end:%Y-%m-%dT23:59:59Z}"
    s1 = S.passes(stac({"collections": ["sentinel-1-grd"], "bbox": [lon0, lat0, lon1, lat1], "datetime": dt, "limit": 250,
                        "query": {"sar:instrument_mode": {"eq": "IW"}}}))
    s2 = stac({"collections": ["sentinel-2-l2a"], "bbox": [lon0, lat0, lon1, lat1], "datetime": dt, "limit": 500})
    takes = {}
    for it in s2:
        p = it["properties"]
        takes.setdefault((p["datetime"][:16], p["sat:relative_orbit"], p["platform"]), []).append(p.get("eo:cloud_cover", 100))
    for gp in s1:
        t1 = gp["t"]
        near = []
        for (t, orb, plat), cc in takes.items():
            t2 = datetime.fromisoformat(t + ":00+00:00")
            gap = (t2 - t1).total_seconds() / 3600
            if abs(gap) <= 30:
                near.append(f"{plat[-2:]} R{orb:03d} {t[5:16]} {gap:+.1f} h cloud {np.mean(cc):.0f}%")
        print(f"{t1:%Y-%m-%d %H:%M} {gp['orbit']:10} {gp['frames'][0]['id'][17:32]} | " + ("; ".join(near) or "no S2 within 30 h"))


def cmd_fixed(a, box, g):
    p = os.path.join(OUT1, "fixed_sites.json")
    f = json.load(open(p, encoding="utf-8"))["fixed"]
    fx = fixed_xy(g)
    rows = []
    for pj in sorted(os.listdir(OUT2)):
        if not (pj.startswith("s2_") and pj.endswith(".json")):
            continue
        key, orb = pj[3:16], int(pj[18:21])
        s2 = s2_scene(box, key, orb, g, keep_b08=False)
        objs = np.array([(o["x_m"], o["y_m"]) for o in s2["objects"]]) if s2["objects"] else np.zeros((0, 2))
        sc, leak = s2_state(s2, g, fx[:, 0], fx[:, 1])
        d = nearest(objs, fx[:, 0], fx[:, 1])
        ctrl = []
        for dx, dy in shifts():
            s_ok, _ = s2_state(s2, g, fx[:, 0] + dx, fx[:, 1] + dy)
            ctrl += nearest(objs, fx[s_ok, 0] + dx, fx[s_ok, 1] + dy).tolist()
        n = int(sc.sum()); k = int((d[sc] <= R_TIGHT).sum()); kl = int((d[sc] <= R_LOOSE).sum())
        c = float(np.mean(np.array(ctrl) <= R_TIGHT)) if ctrl else float("nan")
        cl = float(np.mean(np.array(ctrl) <= R_LOOSE)) if ctrl else float("nan")
        row = {"s2": key, "orbit": orb, "scorable": n, "land_leak": int(leak.sum()), "confirmed_tight": k,
               "m": round(k / n, 3) if n else None, "m_ci": wilson(k, n), "c": round(c, 3), "q": round(corrected(k / n, c), 3) if n else None,
               "confirmed_loose": kl, "m_loose": round(kl / n, 3) if n else None, "c_loose": round(cl, 3),
               "per_site": [{"i": i, "d_s2_m": None if not np.isfinite(d[i]) else round(float(d[i])), "scorable": bool(sc[i]),
                             "land": bool(leak[i]), "passes": f[i]["passes"]} for i in range(len(f))]}
        rows.append(row)
        print(f"{key} R{orb:03d}: fixed sites scorable {n}, on land {int(leak.sum())}; confirmed within {R_TIGHT:.0f} m {k} "
              f"(m={row['m']}, {row['m_ci']}), control {c:.3f}, q={row['q']}; within {R_LOOSE:.0f} m {kl}")
    json.dump(rows, open(os.path.join(OUT2, "fixed_check.json"), "w", encoding="utf-8"), indent=1)


def cmd_stationary(a, box, g):
    """S2 objects seen in both of two S2 images (minutes apart) within FIXED_R: stationary. Writes the share by size."""
    s_a = s2_scene(box, a.s2, a.orbit, g, keep_b08=False)
    s_b = s2_scene(box, a.s2b, a.orbitb, g, keep_b08=False)
    oa = s_a["objects"]; ob = s_b["objects"]
    xa, ya = np.array([o["x_m"] for o in oa]), np.array([o["y_m"] for o in oa])
    xb, yb = np.array([o["x_m"] for o in ob]), np.array([o["y_m"] for o in ob])
    sa, _ = s2_state(s_a, g, xa, ya)
    sb, _ = s2_state(s_b, g, xa, ya)
    both = sa & sb                                      # clear water in both images
    d = nearest(np.column_stack([xb, yb]), xa, ya)
    t1 = datetime.fromisoformat(s_a["time"].replace("Z", "+00:00")); t2 = datetime.fromisoformat(s_b["time"].replace("Z", "+00:00"))
    gap_s = abs((t2 - t1).total_seconds())
    rows = []
    for lo, hi in ((10, 30),) + LEN_BINS:
        sel = both & (np.array([o["length_m"] for o in oa]) >= lo) & (np.array([o["length_m"] for o in oa]) < hi)
        n = int(sel.sum()); st = int((d[sel] <= FIXED_R).sum())
        rows.append({"length": len_bin(lo) if lo >= 30 else "10-29", "n": n, "stationary": st,
                     "f_stat": round(st / n, 3) if n else None, "ci": wilson(st, n)})
        print(f"optical length {rows[-1]['length']:>8} m: {n:4d} objects in clear water in both, stationary {st} "
              f"({rows[-1]['f_stat']}), {rows[-1]['ci']}")
    for o, s, dd in zip(oa, both, d):
        o["both_clear"] = bool(s); o["stationary"] = bool(s and dd <= FIXED_R)
        o["d_other_m"] = None if not np.isfinite(dd) else round(float(dd))
    out = {"a": f"{a.s2} R{a.orbit}", "b": f"{a.s2b} R{a.orbitb}", "gap_s": gap_s, "radius_m": FIXED_R, "by_length": rows, "objects": oa}
    json.dump(out, open(os.path.join(OUT2, f"stationary_{a.s2}_{a.s2b}.json"), "w", encoding="utf-8"), indent=1)


def cmd_recall(a, box, g):
    """Large S2 objects (optical length >= --min-len) in water S1 could see: share with an S1 detection nearby."""
    s2 = s2_scene(box, a.s2, a.orbit, g, keep_b08=False)
    dets, sea, sp = s1_detect(a.scene, box, g, a.k1)
    objs = s2["objects"]
    if a.stationary:
        st = json.load(open(a.stationary, encoding="utf-8"))["objects"]
        key = {(round(o["x_m"]), round(o["y_m"])): o for o in st}
        objs = [o for o in objs if key.get((round(o["x_m"]), round(o["y_m"])), {}).get("stationary")]
    objs = [o for o in objs if o["length_m"] >= a.min_len]
    xs, ys = np.array([o["x_m"] for o in objs]), np.array([o["y_m"] for o in objs])
    sc, _ = s2_state(s2, g, xs, ys)
    ok = sc & in_mask20(sea, g, xs, ys)
    dpts = np.array([(d["x_m"], d["y_m"]) for d in dets])
    dist = nearest(dpts, xs, ys)
    res = {"scene": a.scene, "s2": a.s2, "min_len": a.min_len, "stationary_only": bool(a.stationary), "k": a.k1}
    for name, R in (("tight", R_TIGHT), ("loose", R_LOOSE)):
        n = int(ok.sum()); k = int((dist[ok] <= R).sum())
        cd = []
        for dx, dy in shifts():
            cx, cy = xs + dx, ys + dy
            s_ok, _ = s2_state(s2, g, cx, cy)
            q = s_ok & in_mask20(sea, g, cx, cy)
            cd += nearest(dpts, cx[q], cy[q]).tolist()
        c = float(np.mean(np.array(cd) <= R)) if cd else float("nan")
        m = k / n if n else float("nan")
        res[name] = {"n": n, "detected": k, "recall": round(m, 3), "ci": wilson(k, n), "control": round(c, 3),
                     "corrected": round(corrected(m, c), 3), "corrected_ci": [round(corrected(v, c), 3) for v in wilson(k, n)]}
        print(f"{name}: {n} S2 objects >= {a.min_len} m{' (stationary)' if a.stationary else ''} in S1-visible clear water; "
              f"S1 detection within {R:.0f} m for {k} ({res[name]['recall']}, {res[name]['ci']}); control {c:.3f}; corrected {res[name]['corrected']}")
    for o, okk, dd in zip(objs, ok, dist):
        o["s1_visible"] = bool(okk); o["d_s1_m"] = None if not np.isfinite(dd) else round(float(dd))
    res["objects"] = objs
    tag = f"recall_{a.scene[17:32]}_{a.s2}_{a.min_len}{'_stat' if a.stationary else ''}.json"
    json.dump(res, open(os.path.join(OUT2, tag), "w", encoding="utf-8"), indent=1)


# ---------------------------------------------------------------- chips for by-eye checks

def tci_chip(s2, g, x, y, half_m=800):
    """True-colour window (S2 'visual' asset, 10 m) around a point."""
    import rasterio
    from rasterio.windows import from_bounds
    items = [it for it in s2_items(g.box, s2["key"], s2["orbit"])]
    from shapely.geometry import Point, shape
    lon, lat = g.lonlat([x], [y])
    for it in items:
        if not shape(it["geometry"]).contains(Point(float(lon[0]), float(lat[0]))):
            continue
        def one():
            with gdal_env(), rasterio.open(sign(it["assets"]["visual"]["href"], "sentinel-2-l2a")) as src:
                win = from_bounds(x - half_m, y - half_m, x + half_m, y + half_m, src.transform)
                return src.read(window=win, out_shape=(3, int(2 * half_m / 10), int(2 * half_m / 10)), boundless=True, fill_value=0)
        return np.transpose(retry(one, what="TCI chip"), (1, 2, 0))
    return None


def s1_chip(sp, g, x, y, half_m=800):
    r, c = g.rc(x, y, 20)
    r, c, h = int(round(float(r))), int(round(float(c))), int(half_m / 20)
    a = sp["a"]
    win = np.zeros((2 * h, 2 * h), np.float32)
    y0, x0 = r - h, c - h
    ys, xs = max(0, y0), max(0, x0)
    ye, xe = min(a.shape[0], r + h), min(a.shape[1], c + h)
    if ye > ys and xe > xs:
        win[ys - y0:ye - y0, xs - x0:xe - x0] = a[ys:ye, xs:xe]
    db = 10 * np.log10(np.maximum(win, 1) ** 2)
    sea = db[win > 0]
    lo = np.percentile(sea, 5) if sea.size else 0
    v = np.clip((db - lo) / 30.0, 0, 1)
    return np.repeat(np.repeat((v * 255).astype(np.uint8), 2, 0), 2, 1)


def b08_chip(s2, g, x, y, half_m=800):
    r0, c0 = s2["sub"][0], s2["sub"][1]
    r, c = g.rc(x, y, 10)
    r, c, h = int(round(float(r))) - r0, int(round(float(c))) - c0, int(half_m / 10)
    b = s2["b08"]
    win = np.zeros((2 * h, 2 * h), np.float32)
    y0, x0 = r - h, c - h
    ys, xs = max(0, y0), max(0, x0)
    ye, xe = min(b.shape[0], r + h), min(b.shape[1], c + h)
    if ye > ys and xe > xs:
        win[ys - y0:ye - y0, xs - x0:xe - x0] = b[ys:ye, xs:xe]
    vals = win[win > 0]
    lo = np.percentile(vals, 2) if vals.size else 0
    hi = lo + 1500
    return (np.clip((win - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8)


def cmd_chips(a, box, g):
    """Mosaics of S1 (20 m), S2 B08 and S2 true colour chips for a stratified random sample of scorable detections
    (pre-stated: 30 per S1 length stratum, seed 20261024), plus a CSV to record labels by eye."""
    from PIL import Image, ImageDraw
    s2 = s2_scene(box, a.s2, a.orbit, g, keep_b08=True)
    dets = json.load(open(os.path.join(OUT2, f"dets_{a.scene[17:32]}_{a.s2}_k{a.k1:g}.json"), encoding="utf-8"))
    sp = s1_pass(a.scene, box)
    rng = np.random.default_rng(20261024)
    pick = []
    for lo, hi in LEN_BINS:
        pool = [d for d in dets if d["scorable"] and lo <= d["length_m"] < hi]
        n = min(a.n // len(LEN_BINS), len(pool))
        pick += [pool[i] for i in sorted(rng.choice(len(pool), n, replace=False))] if n else []
    if a.extra:                                         # optional extra selection, e.g. ghost candidates or land leaks
        extra = [d for d in dets if (a.extra == "ghost" and d["ghost_of"] is not None and d["scorable"]) or
                 (a.extra == "leak" and d["land_leak"])]
        pick = [extra[i] for i in sorted(rng.choice(len(extra), min(a.n, len(extra)), replace=False))] if extra else []
    cdir = os.path.join(OUT2, "chips", f"{a.scene[17:32]}_{a.s2}{'_' + a.extra if a.extra else ''}")
    os.makedirs(cdir, exist_ok=True)
    cell, per = 160, 12
    rows_csv = ["n,i,lat,lon,length_m,peak_ratio,peak_db,fixed,ghost,d_s2_m,label,notes"]
    for page in range(0, len(pick), per):
        chunk = pick[page:page + per]
        img = Image.new("RGB", (3 * cell * 2 + 30, len(chunk) // 2 * (cell + 18) + (cell + 18) * (len(chunk) % 2)), (40, 40, 40))
        dr = ImageDraw.Draw(img)
        for j, d in enumerate(chunk):
            n = page + j
            col, row = j % 2, j // 2
            ox, oy = col * (3 * cell + 30), row * (cell + 18)
            s1c = Image.fromarray(s1_chip(sp, g, d["x_m"], d["y_m"])).convert("RGB")
            b8c = Image.fromarray(b08_chip(s2, g, d["x_m"], d["y_m"])).convert("RGB")
            tc = tci_chip(s2, g, d["x_m"], d["y_m"])
            tcc = Image.fromarray(tc).convert("RGB") if tc is not None else Image.new("RGB", (cell, cell))
            for k_, im in enumerate((s1c, b8c, tcc)):
                im = im.resize((cell, cell))
                d2 = ImageDraw.Draw(im)
                c0 = cell / 2
                rr = R_TIGHT / 1600 * cell
                d2.ellipse([c0 - rr, c0 - rr, c0 + rr, c0 + rr], outline=(255, 60, 0))
                img.paste(im, (ox + k_ * cell, oy + 16))
            dr.text((ox + 2, oy + 2), f"#{n} L{d['length_m']} pr{d['peak_ratio']:.0f} {'F' if d['fixed'] else ''}{'G' if d['ghost_of'] is not None else ''} d{d['d_s2_m']}",
                    fill=(255, 255, 0))
            rows_csv.append(f"{n},{d['i']},{d['lat']},{d['lon']},{d['length_m']},{d['peak_ratio']},{d['peak_db']},{int(d['fixed'])},"
                            f"{int(d['ghost_of'] is not None)},{d['d_s2_m']},,")
        img.save(os.path.join(cdir, f"page_{page // per:02d}.png"))
    open(os.path.join(cdir, "labels.csv"), "w", encoding="utf-8").write("\n".join(rows_csv) + "\n")
    print(f"{len(pick)} chips in {cdir} (S1 20 m | S2 B08 | S2 true colour; 1.6 km across; red circle {R_TIGHT:.0f} m)")


def cmd_bigchips(a, box, g):
    """Recall set for by-eye vetting: a random sample (seed 20261024) of S2 objects >= --min-len in clear water that S1
    could see (S1 sea mask), with the S1 image and its detections. Labels go in labels.csv: vessel (no wake), vessel
    (wake), cloud, other. Distances to the nearest S1 detection are filled in automatically."""
    from PIL import Image, ImageDraw
    s2 = s2_scene(box, a.s2, a.orbit, g, keep_b08=True)
    dets, sea, sp = s1_detect(a.scene, box, g, a.k1)
    objs = [o for o in s2["objects"] if o["length_m"] >= a.min_len]
    xs, ys = np.array([o["x_m"] for o in objs]), np.array([o["y_m"] for o in objs])
    sc, _, cst = s2_state(s2, g, xs, ys, with_coast=True)
    ok = sc & ~cst & in_mask20(sea, g, xs, ys)
    pool = [o for o, k_ in zip(objs, ok) if k_]
    dp = np.array([(d["x_m"], d["y_m"]) for d in dets])
    rng = np.random.default_rng(20261024)
    pick = [pool[i] for i in sorted(rng.choice(len(pool), min(a.n, len(pool)), replace=False))] if pool else []
    dist = nearest(dp, np.array([o["x_m"] for o in pick]), np.array([o["y_m"] for o in pick]))
    cdir = os.path.join(OUT2, "chips", f"big_{a.scene[17:32]}_{a.s2}")
    os.makedirs(cdir, exist_ok=True)
    cell, per = 160, 12
    rows = ["n,lat,lon,length_m,width_m,excess,d_s1_m,label,notes"]
    from scipy.spatial import cKDTree
    tree = cKDTree(dp) if len(dp) else None
    for page in range(0, len(pick), per):
        chunk = pick[page:page + per]
        img = Image.new("RGB", (2 * (3 * cell + 30), -(-len(chunk) // 2) * (cell + 18)), (40, 40, 40))
        dr = ImageDraw.Draw(img)
        for j, o in enumerate(chunk):
            n = page + j
            ox, oy = (j % 2) * (3 * cell + 30), (j // 2) * (cell + 18)
            b8 = Image.fromarray(b08_chip(s2, g, o["x_m"], o["y_m"])).convert("RGB")
            tc = tci_chip(s2, g, o["x_m"], o["y_m"])
            tcc = Image.fromarray(tc).convert("RGB") if tc is not None else Image.new("RGB", (cell, cell))
            s1c = Image.fromarray(s1_chip(sp, g, o["x_m"], o["y_m"])).convert("RGB")
            for k_, im in enumerate((b8, tcc, s1c)):
                im = im.resize((cell, cell)); d2 = ImageDraw.Draw(im)
                c0 = cell / 2; rr = R_LOOSE / 1600 * cell
                d2.ellipse([c0 - rr, c0 - rr, c0 + rr, c0 + rr], outline=(0, 160, 255))
                if k_ == 2 and tree is not None:            # S1 detections in the chip
                    for jj in tree.query_ball_point((o["x_m"], o["y_m"]), 1150):
                        px_ = c0 + (dp[jj, 0] - o["x_m"]) / 1600 * cell; py_ = c0 - (dp[jj, 1] - o["y_m"]) / 1600 * cell
                        d2.rectangle([px_ - 4, py_ - 4, px_ + 4, py_ + 4], outline=(255, 60, 0))
                img.paste(im, (ox + k_ * cell, oy + 16))
            dd = dist[n] if np.isfinite(dist[n]) else -1
            dr.text((ox + 2, oy + 2), f"#{n} L{o['length_m']} W{o['width_m']} e{o['excess']:.2f} dS1 {dd:.0f}", fill=(255, 255, 0))
            rows.append(f"{n},{o['lat']},{o['lon']},{o['length_m']},{o['width_m']},{o['excess']},{dd:.0f},,")
        img.save(os.path.join(cdir, f"page_{page // per:02d}.png"))
    open(os.path.join(cdir, "labels.csv"), "w", encoding="utf-8").write("\n".join(rows) + "\n")
    print(f"{len(pick)} of {len(pool)} S2 objects >= {a.min_len} m in S1-visible clear water; chips in {cdir} "
          f"(S2 B08 | S2 true colour | S1 with detections; blue circle {R_LOOSE:.0f} m)")


def cmd_bigscore(a, box, g):
    """Score the by-eye labels of a bigchips sample: per label, the share of objects with an S1 detection within 150 and
    500 m, the chance share from the 8-shift control, and the corrected recall (m - c) / (1 - c)."""
    import csv
    s2 = s2_scene(box, a.s2, a.orbit, g, keep_b08=False)
    dets, sea, _ = s1_detect(a.scene, box, g, a.k1, spec=a.spec)
    dp = np.array([(d["x_m"], d["y_m"]) for d in dets])
    p = os.path.join(OUT2, "chips", f"big_{a.scene[17:32]}_{a.s2}", "labels.csv")
    rows = [r for r in csv.DictReader(open(p, encoding="utf-8")) if r["label"]]
    out = {"scene": a.scene, "s2": a.s2, "k": a.k1, "labels": {}}
    groups = sorted({r["label"] for r in rows}) + ["vessel_all"]
    for lab in groups:
        sel = [r for r in rows if (r["label"] == lab or (lab == "vessel_all" and r["label"].startswith("vessel")))]
        if not sel:
            continue
        x, y = g.to_xy([float(r["lon"]) for r in sel], [float(r["lat"]) for r in sel])
        d = nearest(dp, x, y)
        res = {"n": len(sel)}
        for name, R in (("tight", R_TIGHT), ("loose", R_LOOSE)):
            cd = []
            for dx, dy in shifts():
                ok_s, _ = s2_state(s2, g, x + dx, y + dy)
                ok_s &= in_mask20(sea, g, x + dx, y + dy)
                cd += nearest(dp, (x + dx)[ok_s], (y + dy)[ok_s]).tolist()
            k = int((d <= R).sum()); m = k / len(sel)
            c = float(np.mean(np.array(cd) <= R)) if cd else float("nan")
            res[name] = {"detected": k, "m": round(m, 3), "ci": wilson(k, len(sel)), "c": round(c, 3),
                         "corrected": round(corrected(m, c), 3), "corrected_ci": [round(corrected(v, c), 3) for v in wilson(k, len(sel))]}
        out["labels"][lab] = res
        print(f"{lab:16} n={len(sel):3d}  within {R_TIGHT:.0f} m {res['tight']['detected']:3d} (m={res['tight']['m']:.2f}, c={res['tight']['c']:.2f}, "
              f"corr {res['tight']['corrected']:.2f})   within {R_LOOSE:.0f} m {res['loose']['detected']:3d} (m={res['loose']['m']:.2f} "
              f"{res['loose']['ci']}, c={res['loose']['c']:.2f}, corr {res['loose']['corrected']:.2f} {res['loose']['corrected_ci']})")
    vt = (a.spec or f"{a.k1:g}").replace(":", "_")
    json.dump(out, open(os.path.join(OUT2, f"bigscore_{a.scene[17:32]}_{a.s2}_k{vt}.json"), "w", encoding="utf-8"), indent=1)


# ---------------------------------------------------------------- land mask from S2 for ship_detect --landmask

def cmd_watermask(a, box, g):
    """Land where clear S2 observations call a pixel non-water in most images (enclosed small blobs, which are ships
    or structures, excluded). Saved on the 20 m S1 grid for ship_detect --landmask."""
    H, W = g.h20, g.w20
    n_obs = np.zeros((H, W), np.uint8); n_land = np.zeros((H, W), np.uint8)
    for spec in a.s2.split(","):
        key, orb = spec.split(":")
        items = s2_items(box, key, int(orb))
        sub = s2_subgrid(items, g)
        scl = s2_read(items, "SCL", 20, g, sub)
        m = s2_masks(scl)
        r0, c0, h, w = sub[0] // 2, sub[1] // 2, sub[2] // 2, sub[3] // 2
        ok = m["clear"] & (m["region"] | m["land"])
        n_obs[r0:r0 + h, c0:c0 + w] += ok.astype(np.uint8)
        n_land[r0:r0 + h, c0:c0 + w] += (ok & m["land"]).astype(np.uint8)
        print(f"  {key} R{orb}: clear share {ok.mean():.2f}")
    land = (n_obs > 0) & (n_land * 2 > n_obs)
    land = remove_small(land, int(round(0.1 / (400 / 1e6))))
    p = os.path.join(OUT2, "s2_landmask.npz")
    np.savez_compressed(p, land=land, transform=np.array([g.left, g.top, 20.0]), n_obs=n_obs)
    print(f"land mask: {land.mean():.3f} of the box is land; pixels never seen clear: {(n_obs == 0).mean():.3f}; saved {p}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["pairs", "s1", "s2", "score", "fixed", "stationary", "recall", "chips", "bigchips", "bigscore", "watermask"])
    ap.add_argument("--area"); ap.add_argument("--box")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--scene", help="S1 scene id (first frame, as in private/maritime/s1/)")
    ap.add_argument("--s2", help="S2 datatake start, YYYYMMDDTHHMM (UTC); for watermask a list key:orbit,...")
    ap.add_argument("--orbit", type=int, help="S2 relative orbit")
    ap.add_argument("--s2b"); ap.add_argument("--orbitb", type=int)
    ap.add_argument("--k", default="6", help="detector variants to score, comma-separated: k[:c<dB>][:gdrop][:land]")
    ap.add_argument("--spec", help="bigscore: one detector variant (as for --k) instead of --k1")
    ap.add_argument("--tag", default="", help="score: suffix for the output file name")
    ap.add_argument("--k1", type=float, default=6.0, help="CFAR threshold for recall and chips")
    ap.add_argument("--min-len", type=int, default=100)
    ap.add_argument("--stationary", help="stationary_*.json from the stationary command (recall on stationary objects only)")
    ap.add_argument("--n", type=int, default=120)
    ap.add_argument("--extra", choices=["ghost", "leak"])
    ap.add_argument("--rebuild", action="store_true", help="s2: rebuild masks and objects from the cached bands")
    a = ap.parse_args()
    box = area_box(a)
    g = Grid(box)
    os.makedirs(OUT2, exist_ok=True)
    if a.cmd == "pairs":
        return cmd_pairs(a, box, g)
    if a.cmd == "s1":
        sp = s1_pass(a.scene, box)
        for k in [float(v) for v in a.k.split(",")]:
            dets, sea, _ = s1_detect(a.scene, box, g, k)
            print(f"k={k:g}: {len(dets)} detections ({sum(d['ghost_of'] is not None for d in dets)} ghost candidates); "
                  f"sea {sea.sum() * 400 / 1e6:.0f} km2; along-track bearing {sp['along']:.1f}")
        return
    if a.cmd == "s2":
        return s2_scene(box, a.s2, a.orbit, g, keep_b08=False, rebuild=a.rebuild) and None
    return {"score": cmd_score, "fixed": cmd_fixed, "stationary": cmd_stationary, "recall": cmd_recall,
            "chips": cmd_chips, "bigchips": cmd_bigchips, "bigscore": cmd_bigscore, "watermask": cmd_watermask}[a.cmd](a, box, g)


if __name__ == "__main__":
    main()
