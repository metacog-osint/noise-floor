"""Offline tests for tools/s2_check.py (Sentinel-2 check of Sentinel-1 ship detections) and the azimuth-ghost rule in
tools/ship_detect.py, on synthetic arrays. No network, no rasterio.

Run:  python tests/test_s2_check.py
"""
import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import s2_check as C  # noqa: E402
import ship_detect as S  # noqa: E402


def test_masks():
    scl = np.full((200, 200), 6, np.uint8)            # water
    scl[:, :40] = 5                                    # land strip (8,000 px = 3.2 km2)
    scl[100:103, 100:104] = 9                          # 12-px "cloud": ship-sized, must not count as cloud
    scl[150:180, 150:180] = 8                          # 900-px cloud
    scl[50:52, 120:125] = 5                            # 10-px enclosed blob: an object on the water
    scl[100:103, 110:114] = 8                          # a second ship-sized "cloud" 120 m away: anchored ships in a group
    scl[176:178, 146:148] = 9                          # a ship-sized blob 40 m from the big cloud: cloud
    m = C.s2_masks(scl)
    assert m["region"][101, 111] and m["clear"][101, 111], "grouped ship-sized blobs are not a cloud field"
    assert not m["clear"][177, 147], "a small blob next to a real cloud is cloud"
    assert m["land"][10, 10] and not m["region"][10, 10]
    assert m["region"][51, 122], "small enclosed blob should count as water region"
    assert m["region"][101, 101] and m["clear"][101, 101], "ship-sized cloud blob should stay clear water"
    assert not m["clear"][165, 165] and not m["clear"][149, 165], "cloud and its 200 m margin are not clear"
    assert m["clear"][60, 60]


def test_optical_objects():
    rng = np.random.default_rng(1)
    b08 = (1200 + rng.normal(0, 30, (400, 400))).astype(np.uint16)   # dark water, reflectance about 0.02
    b08[200:203, 150:165] = 3500                       # 15 x 3 px ship (150 m)
    b08[50, 50] = 1500                                  # single bright pixel: too small and too faint
    water = np.ones(b08.shape, bool)
    objs, ref_sd = C.opt_objects(b08, water, water)
    assert 20 < ref_sd < 45, ref_sd                    # ring SD of clean water ~ the noise SD (30)
    assert len(objs) == 1, objs
    o = objs[0]
    assert 140 <= o["length_m"] <= 160 and 20 <= o["width_m"] <= 40, o
    assert o["axis"] is not None and (abs(o["axis"] - 90) < 5), o            # east-west hull
    quiet, _ = C.opt_objects((1200 + rng.normal(0, 30, (300, 300))).astype(np.uint16), np.ones((300, 300), bool), np.ones((300, 300), bool))
    assert quiet == [], quiet


def test_ghost_rule():
    res = 20.0
    bearing = 192.0                                    # descending along-track direction
    u = (math.sin(math.radians(bearing)), math.cos(math.radians(bearing)))

    def at(east, north, peak):
        return {"x": east / res, "y": -north / res, "peak": peak}
    dets = [at(0, 0, 1e7),                              # bright source
            at(5000 * u[0], 5000 * u[1], 1e4),         # 30 dB fainter, 5 km along track: ghost
            at(5000 * u[1], -5000 * u[0], 1e4),        # 5 km across track: not a ghost
            at(-5200 * u[0], -5200 * u[1], 5e5),       # along track but only 13 dB fainter: not a ghost
            at(9000 * u[0], 9000 * u[1], 1e4)]         # too far along track
    src = S.ghost_sources(dets, bearing, res)
    assert src == [None, 0, None, None, None], src
    assert S.ghost_sources(dets, None, res) == [None] * 5


def test_stats():
    assert C.corrected(0.5, 0.2) == (0.5 - 0.2) / 0.8
    lo, hi = C.wilson(50, 100)
    assert 0.39 < lo < 0.41 and 0.59 < hi < 0.61
    assert C.len_bin(45) == "30-59" and C.len_bin(250) == "200+" and C.len_bin(10) == "<30"
    k = C.disk(2.5)
    assert k.shape == (7, 7) and k[3, 3] and not k[0, 0]
    m = np.zeros((50, 50), bool); m[:, 25:] = True
    f = C.frac_at(m, [25, 25, 0], [10, 40, 0], C.disk(3))
    assert f[0] == 0 and f[1] == 1 and math.isnan(f[2])


def test_remove_small():
    m = np.zeros((30, 30), bool)
    m[2:4, 2:4] = True                                 # 4 px
    m[10:20, 10:20] = True                             # 100 px
    r = C.remove_small(m, 10)
    assert not r[2, 2] and r[15, 15]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
