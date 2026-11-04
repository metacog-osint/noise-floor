"""Offline tests for tools/sentinel_e21.py (step E2.1): regional satellites, the load, the frozen index with its
final-pass cells, the slope fit and the check marks. The SBAS and Keplerian records are copied from the IGS merged
broadcast file for 16 May 2026 (public). Run as a plain script: python tests/test_sentinel_e21.py
"""
import datetime as dt
import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import sentinel_e21 as M  # noqa: E402
import sentinel_rfi as SR  # noqa: E402
import test_station_bands as TB  # noqa: E402

SBAS = "\n".join([
    "S22 2026 05 16 06 00 00 0.000000000000E+00 0.000000000000E+00 5.400120000000E+05",
    "    -3.389392800000E+04 0.000000000000E+00 0.000000000000E+00 6.300000000000E+01",
    "     2.508018800000E+04 0.000000000000E+00 0.000000000000E+00 3.276700000000E+04",
    "     0.000000000000E+00 0.000000000000E+00 0.000000000000E+00 5.300000000000E+01",
    "S31 2026 05 16 06 03 44-1.862645149231E-09 7.275957614183E-12 5.401990000000E+05",
    "    -1.913864712000E+04 1.275000000000E-04 1.250000000000E-08 3.100000000000E+01",
    "    -3.757069032000E+04 5.062500000000E-05-2.500000000000E-08 2.000000000000E+00",
    "    -3.814800000000E+00 6.000000000000E-05 0.000000000000E+00 4.100000000000E+01",
    ""])
NAV = TB.NAV.rstrip("\n") + "\n" + SBAS
GPS_DAY0 = (dt.datetime(2026, 5, 16, tzinfo=dt.timezone.utc) - dt.datetime(1980, 1, 6, tzinfo=dt.timezone.utc)).total_seconds()


def test_regional_records():
    kep, kinds, sbas = M.regional_records(NAV)
    assert sorted(kep) == ["C01", "C03", "J02"], sorted(kep)            # C19 is MEO; R01 isn't regional
    assert kinds["C01"] == "bds_geo" and kinds["C03"] == "bds_geo" and kinds["J02"] == "qzss_incl"
    assert kinds["S22"] == "sbas" and kinds["S31"] == "sbas"
    assert sbas["S22"][0]["health"] == 63.0 and sbas["S31"][0]["health"] == 31.0     # counted whatever the health
    assert sbas["S31"][0]["t"] == GPS_DAY0 + 6 * 3600 + 3 * 60 + 44                # SBAS epochs are GPS time
    lon = math.degrees(math.atan2(sbas["S22"][0]["pos"][1], sbas["S22"][0]["pos"][0]))
    assert abs(lon - 143.5) < 0.1, lon


def test_regional_positions():
    kep, kinds, sbas = M.regional_records(NAV)
    t = np.array([GPS_DAY0 + 6 * 3600 + 224, GPS_DAY0 + 6 * 3600 + 3600, GPS_DAY0 + 12 * 3600])
    pos = M.regional_positions(kep, sbas, t)
    s31 = pos["S31"]
    assert np.allclose(s31[0], np.array(sbas["S31"][0]["pos"]), atol=1.0)          # at the record time: the record
    assert np.linalg.norm(s31[1] - s31[0]) < 1000.0                                # a GEO barely moves in an hour
    assert np.isnan(s31[2]).all() and np.isnan(pos["C01"][2]).all()               # 6 h on: beyond 4 h, no position
    assert 42100e3 < np.linalg.norm(pos["C01"][0]) < 42250e3


def test_load():
    R = 7.07e6
    pos = np.array([[R, 0.0, 0.0], [R, 0.0, 0.0]])
    vel = np.array([[0.0, 7500.0, 0.0], [0.0, 7500.0, 0.0]])
    up, fwd, right = M.SG.frames(pos, vel)
    over = np.array([[4.2e7, 0.0, 0.0]] * 2)                           # overhead: elevation 90, sin 1
    below = np.array([[-4.2e7, 0.0, 0.0]] * 2)                         # behind the Earth: below the horizon
    side = np.array([[R, 4.2e7 * math.cos(math.radians(5)), 4.2e7 * math.sin(math.radians(5))]] * 2)   # ~0-5 deg
    L, Li = M.load(pos, up, fwd, right, {"S1": over, "S2": below, "C9": side}, {"S1": "sbas", "C9": "bds_igso"})
    assert np.allclose(L, 1.0) and np.allclose(Li, 0.0), (L, Li)
    L, Li = M.load(pos, up, fwd, right, {"C9": over}, {"C9": "bds_igso"})
    assert np.allclose(Li, 1.0)


def synthetic_rows(n_epochs=400, links=6, hot_cell_epochs=(100, 200), drop=-4.0):
    rng = np.random.default_rng(5)
    t, sat, el, val, cell = [], [], [], [], []
    for k in range(n_epochs):
        for j in range(links):
            e = 15.0 + 10.0 * j
            v = 35.0 + 0.2 * e + rng.normal(0, 0.3)
            in_hot = hot_cell_epochs[0] <= k < hot_cell_epochs[1]
            t.append(k * 10.0); sat.append(f"G{j + 1:02d}"); el.append(e); val.append(v + (drop if in_hot else 0.0))
            cell.append("H" if in_hot else "Q")
    return np.array(t), np.array(sat), np.array(el), np.array(val), np.array(cell, dtype=object)


def test_index_with_hot_matches_frozen_index():
    t, sat, el, val, cell = synthetic_rows()
    ei, hot = M.index_with_hot("u", t, sat, el, val, cell)
    ref = SR.index_signal("u", t, sat, el, val, cell)
    assert np.array_equal(ei["t"], ref["t"]) and np.allclose(ei["idx"], ref["idx"])
    assert hot == {"H"}, hot                                            # the degraded cell was left out of the baseline
    assert np.median(ei["idx"][(ei["t"] >= 1000) & (ei["t"] < 2000)]) < -3.5


def test_fit_beta():
    rng = np.random.default_rng(2)
    L = rng.uniform(0, 20, 2000)
    D = 0.1 - 0.05 * L + rng.normal(0, 0.2, 2000)
    ok = np.ones(2000, bool)
    beta, icpt, n = M.fit_beta(D, L, ok)
    assert abs(beta + 0.05) < 0.005 and abs(icpt - 0.1) < 0.05 and n == 2000
    D2 = D.copy()
    D2[:500] -= 5.0                                                    # jammed epochs, left out of the fit
    ok2 = ok.copy()
    ok2[:500] = False
    assert abs(M.fit_beta(D2, L, ok2)[0] + 0.05) < 0.005
    assert M.fit_beta(D, L, np.r_[np.ones(99, bool), np.zeros(1901, bool)])[0] == 0.0       # too few epochs
    assert M.fit_beta(D, np.full(2000, 3.0), ok)[0] == 0.0                                  # no spread in L


def test_marks():
    assert [M.verdict_le(1, v) for v in (0.40, 0.65, 0.90)] == ["holds", "weakened", "fails"]
    assert [M.verdict_le(4, v) for v in (0.01, 0.03, 0.06)] == ["holds", "weakened", "fails"]
    assert [M.verdict_le(5, v) for v in (0.04, 0.08, 0.12)] == ["holds", "weakened", "fails"]
    assert M.verdict_le(1, None) == "not judged"
    # check 2: holds at 0.80+ and within 0.01 of D; fails below 0.70 or more than 0.03 below D
    assert M.verdict_auc(0.85, 0.855) == "holds"
    assert M.verdict_auc(0.85, 0.87) == "weakened"
    assert M.verdict_auc(0.83, 0.87) == "fails"
    assert M.verdict_auc(0.75, 0.75) == "weakened" and M.verdict_auc(0.69, 0.60) == "fails"
    # check 3: holds at 0.80+ and within 0.02 of D; fails below 0.70 only
    c3 = dict(max_drop_hold=0.02, max_drop_fail=None)
    assert M.verdict_auc(0.81, 0.83, **c3) == "holds"
    assert M.verdict_auc(0.80, 0.90, **c3) == "weakened"
    assert M.verdict_auc(0.69, 0.70, **c3) == "fails"
    assert M.verdict_auc(None, 0.8) == "not judged"


def test_profile_and_flatness():
    lat = np.full(36 * 200, -20.0)
    lon = np.repeat(np.arange(-175.0, 180.0, 10.0), 200)
    v = np.where((lon > 80) & (lon < 140), -1.0, 0.0)
    prof = M.lon_profile(lat, lon, v, M.QUIET_BAND)
    assert len(prof) == 18 and all(p[2] == 400 for p in prof)
    assert M.flatness(prof) == 1.0
    assert M.lon_profile(lat[:50], lon[:50], v[:50], M.QUIET_BAND)[0][1] is None         # under 100 epochs


def test_frozen_windows():
    assert [str(w) for w in M.WINDOWS] == ["2025-10-27", "2025-12-08", "2026-01-19", "2026-03-02", "2026-04-13",
                                           "2026-05-25", "2026-07-06", "2026-08-17"]
    assert M.PLACE == (-45.0, -10.0, 90.0, 130.0) and M.QUIET_BAND == (-45.0, -10.0)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
        except Exception as ex:          # report every failure, then exit non-zero
            failed += 1
            print(f"FAIL {fn.__name__}: {type(ex).__name__}: {ex}")
    if failed:
        sys.exit(f"test_sentinel_e21: {failed} of {len(tests)} failed")
    print(f"test_sentinel_e21: ok ({len(tests)} tests)")


if __name__ == "__main__":
    main()
