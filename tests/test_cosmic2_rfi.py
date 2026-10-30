"""Offline tests for tools/cosmic2_rfi.py (COSMIC-2 navigation-antenna RFI index). No network, no data/ files."""
import io
import math
import os
import sys
import tarfile

import numpy as np
from scipy.io import netcdf_file

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cosmic2_rfi as M  # noqa: E402

R = 6371.0 + 550.0


def km(lat1, lon1, lat2, lon2):
    a = M.unit_ll(lat1, lon1)
    b = M.unit_ll(lat2, lon2)
    return 6371.0 * np.arccos(np.clip((a * b).sum(-1), -1, 1))


def nc_bytes(start, rfi, leo, gps, antenna):
    buf = io.BytesIO()
    f = netcdf_file(buf, "w")
    f.createDimension("time", len(rfi))
    f.start_time = float(start)
    f.antenna_id = int(antenna)
    v = f.createVariable("time", "d", ("time",))
    v[:] = np.arange(len(rfi), dtype=float)
    v = f.createVariable("RFI", "f", ("time",))
    v[:] = rfi
    for i, ax in enumerate("xyz"):
        f.createVariable(f"{ax}_LEO", "d", ("time",))[:] = leo[:, i]
        f.createVariable(f"{ax}_GPS", "d", ("time",))[:] = gps[:, i]
    f.flush()
    data = buf.getvalue()
    f.close()
    return data


def test_sat_of():
    assert M.sat_of("podTc2_C2E2.2026.302.00.13.0010.G19.02_0001.0001_nc") == 2
    assert M.sat_of("podTc2_C2E6.2026.001.23.59.0001.G01.01_0001.0001_nc") == 6


def test_link_frame():
    # LEO over (0N, 0E) moving east (+y); a GPS satellite ahead and above
    t = np.arange(5.0)
    leo = np.stack([np.full(5, R), 7.5 * t, np.zeros(5)], axis=1)
    gps = leo + np.array([1000.0, 20000.0, 0.0])
    fr = M.link_frame(leo, gps)
    assert np.all(fr[:, 0] > 0.9) and np.all(np.abs(fr[:, 1]) < 1e-6) and np.all(fr[:, 2] > 0)


def test_reduce_stream():
    n = 6
    t = np.arange(n, dtype=float)
    leo = np.stack([np.full(n, R), 7.5 * t, np.zeros(n)], axis=1)
    gps = leo + np.array([5000.0, 20000.0, 0.0])
    rfi = np.array([0.0, 2e-4, 3e-4, -999.0, 1e-6, 5e-4], dtype=np.float32)
    start = 1477267200.0                                   # GPS seconds
    files = {"podTc2_C2E3.2026.302.00.00.0001.G01.01_0001.0001_nc": nc_bytes(start, rfi, leo, gps, 1),
             # a second link on the same antenna, same seconds and values: must not add rows
             "podTc2_C2E3.2026.302.00.00.0001.G02.01_0001.0001_nc": nc_bytes(start, rfi, leo, gps * 1.01, 1),
             # the other antenna, offset by two seconds
             "podTc2_C2E3.2026.302.00.00.0001.G03.02_0001.0001_nc": nc_bytes(start + 2, rfi, leo, gps, 2)}
    tbuf = io.BytesIO()
    with tarfile.open(fileobj=tbuf, mode="w:gz") as tf:
        for name, data in files.items():
            ti = tarfile.TarInfo("2026.302/" + name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    tbuf.seek(0)
    c, pointing, counts = M.reduce_stream(tbuf)
    assert counts == {"files": 3, "bad": 0, "rows": 10}, counts      # 5 valid seconds x 2 antennas
    assert set(c["sat"].tolist()) == {3}
    ant1 = c["ant"] == 1
    unix0 = int(start) + M.GPS_UNIX - M.LEAP
    assert c["t"][ant1].tolist() == [unix0 + k for k in (0, 1, 2, 4, 5)]
    assert np.allclose(c["rfi"][ant1], [0.0, 2e-4, 3e-4, 1e-6, 5e-4])
    assert np.allclose(c["lat"], 0.0, atol=1e-4) and np.allclose(c["alt"], 550.0, atol=1.0)
    assert pointing["3.1"]["along"] > 0.9 and pointing["3.1"]["samples"] == 10


def test_bins():
    t = np.arange(100, 130)                                  # three bins
    rfi = np.zeros(30)
    rfi[10:15] = 1e-3                                        # half of the second bin flagged
    b = M.bins(t, np.ones(30), np.ones(30), rfi, np.zeros(30), np.linspace(0, 1, 30))
    assert len(b["f"]) == 3 and b["n"].tolist() == [10, 10, 10]
    assert np.allclose(b["f"], [0.0, 0.5, 0.0])
    assert np.allclose(np.linalg.norm(b["pos"], axis=1), 1.0)


def orbit_tracks(n_sats=6, day_s=86400, step=10, inc=24.0, period=95.6 * 60):
    """Sub-satellite points of circular orbits (no node drift); satellites spread in node and phase."""
    t = np.arange(0, day_s, step, dtype=float)
    lat, lon = [], []
    for k in range(n_sats):
        u = 2 * math.pi * t / period + k * 1.1
        la = np.degrees(np.arcsin(math.sin(math.radians(inc)) * np.sin(u)))
        lo = k * 60.0 + np.degrees(np.arctan2(math.cos(math.radians(inc)) * np.sin(u), np.cos(u))) - 360.0 * t / 86164.0
        lat.append(la)
        lon.append((lo + 180) % 360 - 180)
    return np.concatenate(lat), np.concatenate(lon)


def test_backproject_finds_emitter():
    rng = np.random.default_rng(7)
    lat, lon = orbit_tracks()
    em = (30.0, 50.0)
    d = km(lat, lon, *em)
    f = np.where(d < 1500, 1.0, (rng.random(len(lat)) < 0.01).astype(float))
    pos = M.unit_ll(lat, lon)
    ids, ll, cen = M.cells(2)
    for radius in (1500.0, 2000.0):                          # kernel matched to the detection range, and too wide
        n_vis, s = M.backproject(pos, f, cen, radius_km=radius)
        score = np.where(n_vis >= M.MIN_VIS, M.corr_score(n_vis, s, f), np.nan)
        best = int(np.nanargmax(score))
        off = float(km(ll[best, 0], ll[best, 1], *em))
        if radius == 1500.0:
            assert off < 400, (radius, ll[best], off)
        else:
            # An emitter poleward of the orbit is heard only from the south, so latitude trades off against the
            # detection range: a kernel 500 km too wide moves the peak poleward. Longitude holds.
            assert abs(ll[best, 1] - em[1]) <= 3.0 and ll[best, 0] > em[0], (radius, ll[best])
        quiet = km(ll[:, 0], ll[:, 1], -10.0, -140.0) < 500  # central Pacific
        assert np.nanmax(score[quiet]) < 0.05, (radius, np.nanmax(score[quiet]))
        # cells beyond any satellite's view stay unscored
        assert np.all(np.isnan(score[np.abs(ll[:, 0]) > 50]))
    # an emitter inside the orbit's band is heard from all sides: a smaller error from the same mismatch
    em2 = (10.0, -60.0)
    f2 = np.where(km(lat, lon, *em2) < 1500, 1.0, 0.0)
    for radius, tol in ((1500.0, 400), (2000.0, 600)):
        n_vis2, s2 = M.backproject(pos, f2, cen, radius_km=radius)
        sc2 = np.where(n_vis2 >= M.MIN_VIS, M.corr_score(n_vis2, s2, f2), np.nan)
        b = int(np.nanargmax(sc2))
        assert float(km(ll[b, 0], ll[b, 1], *em2)) < tol, (radius, ll[b])
    # the plain flagged share is pulled toward the edge of coverage (why the score is a correlation)
    share = np.where(n_vis >= M.MIN_VIS, s / np.maximum(n_vis, 1), np.nan)
    b2 = int(np.nanargmax(share))
    assert float(km(ll[b2, 0], ll[b2, 1], *em)) > 600


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
