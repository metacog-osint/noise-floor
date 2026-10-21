"""Build synthetic NISAR GCOV files (real product layout) for an end-to-end self-test.

Scene: Kaliningrad / Gulf of Gdansk on a UTM 34N grid. Land and sea come from
Natural Earth; backscatter follows typical L-band values with multilook speckle,
an HV noise floor, a calm-water patch and a wind front (both classic false-
positive sources). Two test emitters:
  J1  band A only, just off Baltiysk  (stands in for a GPS L2 jammer)
  R1  band B only, inland             (stands in for an L-band radar)

Passes (time order):
  P1 25 Sep descending  clean
  P2 07 Oct descending  clean + calm-water patch
  P3 14 Oct ascending   J1 on
  P4 19 Oct descending  J1 + R1 on + wind front
"""
import gzip
import json
import math
import os
import sys
import zlib
from functools import lru_cache

import h5py
import numpy as np
from pyproj import Transformer
from scipy import ndimage
from shapely import contains_xy
from shapely.geometry import box, shape
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from nisar_rfi import geometry as geo  # noqa: E402

EPSG = 32634
X0, Y0, SIZE = 400_000.0, 6_110_000.0, 110_000.0      # grid top-left, extent (m)
SP_A, SP_B = 40.0, 160.0
NESZ_DB = -29.0
LOOKS = 8
TRUTH = [
    {"id": "J1", "lat": 54.620, "lon": 19.760, "band": "A", "peak_db": -16.0, "sig_a_km": 1.5, "sig_r_km": 15.0,
     "label": "J1 · band A only · test jammer offshore Baltiysk"},
    {"id": "R1", "lat": 54.560, "lon": 20.950, "band": "B", "peak_db": -6.0, "sig_a_km": 1.0, "sig_r_km": 8.0,
     "label": "R1 · band B only · test radar inland"},
]
PASSES = [
    {"name": "P1", "start": "2026-09-25T18:23:12", "dir": "D", "track": 109, "frame": 60, "on": [], "extra": None},
    {"name": "P2", "start": "2026-10-07T18:23:12", "dir": "D", "track": 109, "frame": 60, "on": [], "extra": "calm"},
    {"name": "P3", "start": "2026-10-14T04:51:40", "dir": "A", "track": 37, "frame": 20, "on": ["J1"], "extra": None},
    {"name": "P4", "start": "2026-10-19T18:23:12", "dir": "D", "track": 109, "frame": 60, "on": ["J1", "R1"], "extra": "wind"},
]


def smooth_field(shape_, scale_px, rng, amp):
    """Gaussian random field with correlation ~scale_px, built coarse then upsampled (fast)."""
    k = max(1, int(scale_px // 3))
    small = (-(-shape_[0] // k), -(-shape_[1] // k))
    f = ndimage.gaussian_filter(rng.standard_normal(small), max(scale_px / k, 0.8))
    f = ndimage.zoom(f, k, order=1)[: shape_[0], : shape_[1]]
    return amp * f / (f.std() + 1e-9)


@lru_cache(maxsize=1)
def _land():
    fc = json.load(gzip.open(os.path.join(HERE, "..", "nisar_rfi", "assets", "land.geojson.gz"), "rt"))
    region = box(17, 52, 24, 57)
    return unary_union([shape(f["geometry"]).intersection(region) for f in fc["features"]
                        if shape(f["geometry"]).intersects(region)])


def land_mask(n, sp):
    land = _land()
    coarse = max(1, int(400 // sp))
    m = -(-n // coarse)
    xs = X0 + (np.arange(m) + .5) * sp * coarse
    ys = Y0 - (np.arange(m) + .5) * sp * coarse
    X, Y = np.meshgrid(xs, ys)
    lon, lat = Transformer.from_crs(EPSG, 4326, always_xy=True).transform(X, Y)
    lm = contains_xy(land, lon, lat)
    return np.kron(lm, np.ones((coarse, coarse), bool))[:n, :n]


def scene(sp, p, seed=7):
    """Natural backscatter (linear HH, HV) on a grid of spacing sp."""
    n = int(SIZE // sp)
    rng = np.random.default_rng(seed)                       # same ground every pass
    lm = land_mask(n, sp)
    s = max(1, int(1500 // sp))
    hh = np.where(lm, -9.0 + smooth_field((n, n), s, rng, 2.5), -22.0 + smooth_field((n, n), 4 * s, rng, 1.5))
    rat = np.where(lm, -6.5 + smooth_field((n, n), s, rng, 1.0), -9.0 + smooth_field((n, n), 4 * s, rng, 0.5))
    X, Y = np.meshgrid(X0 + (np.arange(n) + .5) * sp, Y0 - (np.arange(n) + .5) * sp)
    cx, cy = geo.ll_to_xy(EPSG, 54.71, 20.51)               # Kaliningrad city: bright urban
    urban = np.hypot(X - cx, Y - cy) < 6000
    hh = np.where(urban, -2.0 + smooth_field((n, n), s, rng, 1.0), hh)
    rat = np.where(urban, -10.0, rat)
    prng = np.random.default_rng(zlib.crc32(p["name"].encode()))
    if p["extra"] == "calm":                                # calm-water slick NW of the spit
        ccx, ccy = geo.ll_to_xy(EPSG, 54.85, 19.60)
        calm = np.exp(-(((X - ccx) / 9000) ** 2 + ((Y - ccy) / 5000) ** 2))
        hh = np.where(~lm, hh - 6.0 * calm, hh)
    if p["extra"] == "wind":                                # rougher sea north of 54.9N
        _, ny = geo.ll_to_xy(EPSG, 54.9, 19.8)
        hh = np.where(~lm, hh + 3.0 / (1 + np.exp(-(Y - ny) / 4000)), hh)
    hh += smooth_field((n, n), 2 * s, prng, 0.4)           # pass-to-pass change
    hv = hh + rat
    hh_l, hv_l = 10 ** (hh / 10), 10 ** (hv / 10) + 10 ** (NESZ_DB / 10)
    return X, Y, hh_l, hv_l, lm


def add_emitter(X, Y, hh, hv, t, direction, rng):
    ex, ey = geo.ll_to_xy(EPSG, t["lat"], t["lon"])
    az = geo.grid_angle(t["lat"], t["lon"], geo.range_line_azimuth(t["lat"], direction), EPSG) + 2.0
    a = math.radians(az)
    r = (X - ex) * math.sin(a) + (Y - ey) * math.cos(a)        # along range
    al = (X - ex) * math.cos(a) - (Y - ey) * math.sin(a)       # along track
    pj = 10 ** (t["peak_db"] / 10) * np.exp(-0.5 * (al / (t["sig_a_km"] * 1000)) ** 2) * np.exp(-0.5 * (r / (t["sig_r_km"] * 1000)) ** 2)
    return hh + pj, hv + pj


def swath_mask(X, Y, direction):
    """Valid data: a 100 km track-aligned square inside the grid."""
    clat, clon = 54.65, 20.33
    cx, cy = geo.ll_to_xy(EPSG, clat, clon)
    az = math.radians(geo.grid_angle(clat, clon, geo.ground_track_heading(clat, direction), EPSG))
    u = (X - cx) * math.sin(az) + (Y - cy) * math.cos(az)
    v = (X - cx) * math.cos(az) - (Y - cy) * math.sin(az)
    m = (np.abs(u) < 50_000) & (np.abs(v) < 50_000)
    corners = [(cx + uu * math.sin(az) + vv * math.cos(az), cy + uu * math.cos(az) - vv * math.sin(az))
               for uu, vv in ((50e3, 50e3), (50e3, -50e3), (-50e3, -50e3), (-50e3, 50e3), (50e3, 50e3))]
    t = Transformer.from_crs(EPSG, 4326, always_xy=True)
    poly = [t.transform(x, y) for x, y in corners]
    return m, poly


def write(path, p):
    on = [t for t in TRUTH if t["id"] in p["on"]]
    with h5py.File(path, "w") as h:
        ident = h.create_group("/science/LSAR/identification")
        gid = f'SYNTH_NISAR_L2_GCOV_{p["track"]:03d}_{p["dir"]}_{p["frame"]:03d}_{p["start"].replace("-", "").replace(":", "")}'
        footprint = None
        XA, YA, hhA, hvA, _ = scene(SP_A, p)                 # the ground: identical for both sub-bands
        k = int(SP_B // SP_A)
        nb = XA.shape[0] // k

        def down(a):
            return a[: nb * k, : nb * k].reshape(nb, k, nb, k).mean(axis=(1, 3))
        ground = {"A": (XA, YA, hhA, hvA), "B": (down(XA), down(YA), down(hhA), down(hvA))}
        for f, sp in (("A", SP_A), ("B", SP_B)):
            X, Y, hh, hv = ground[f]
            rng = np.random.default_rng(zlib.crc32((p["name"] + f).encode()))
            for t in on:
                if t["band"] == f:
                    hh, hv = add_emitter(X, Y, hh, hv, t, p["dir"], rng)
            looks = LOOKS * (sp / SP_A) ** 2
            hh = hh * rng.gamma(looks, 1 / looks, hh.shape)
            hv = hv * rng.gamma(looks, 1 / looks, hv.shape)
            m, footprint = swath_mask(X, Y, p["dir"])
            hh[~m] = np.nan
            hv[~m] = np.nan
            g = h.create_group(f"/science/LSAR/GCOV/grids/frequency{f}")
            n = hh.shape[0]
            kw = dict(chunks=(512, 512) if n > 512 else None, compression="gzip", compression_opts=1, shuffle=True)
            g.create_dataset("HHHH", data=hh.astype(np.float32), **kw)
            g.create_dataset("HVHV", data=hv.astype(np.float32), **kw)
            g["xCoordinates"] = X0 + (np.arange(n) + .5) * sp
            g["yCoordinates"] = Y0 - (np.arange(n) + .5) * sp
            g["xCoordinateSpacing"] = sp
            g["yCoordinateSpacing"] = -sp
            g["projection"] = np.uint32(EPSG)
            g["projection"].attrs["epsg_code"] = EPSG
            g["listOfPolarizations"] = np.array([b"HH", b"HV"])
            for pol in ("HH", "HV"):
                c = h.require_group(f"/science/LSAR/GCOV/metadata/calibrationInformation/frequency{f}/{pol}")
                hit = any(t["band"] == f for t in on)
                c["rfiLikelihood"] = (0.11 if f == "A" else 0.04) if hit else 0.008
        h["/science/LSAR/GCOV/metadata/processingInformation/parameters/rfiMitigationApplied"] = True
        ident["granuleId"] = gid.encode()
        ident["productType"] = b"GCOV"
        ident["zeroDopplerStartTime"] = (p["start"] + ".000000").encode()
        ident["zeroDopplerEndTime"] = (p["start"][:-2] + "48.000000").encode()
        ident["orbitPassDirection"] = (b"Descending" if p["dir"] == "D" else b"Ascending")
        ident["trackNumber"] = np.uint32(p["track"])
        ident["frameNumber"] = np.uint16(p["frame"])
        ident["listOfFrequencies"] = np.array([b"A", b"B"])
        ident["compositeReleaseId"] = b"SYNTH"
        ident["boundingPolygon"] = ("POLYGON ((" + ", ".join(f"{x:.5f} {y:.5f}" for x, y in footprint) + "))").encode()
    return gid


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "fixtures")
    os.makedirs(out, exist_ok=True)
    for p in PASSES:
        gid = write(os.path.join(out, f'{p["name"]}.h5'), p)
        print(p["name"], gid, os.path.getsize(os.path.join(out, f'{p["name"]}.h5')) // 2**20, "MB")
    json.dump(TRUTH, open(os.path.join(out, "truth.json"), "w"), indent=1)
