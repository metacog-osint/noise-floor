"""Offline tests for tools/station_cn0.py: sidereal baseline, drop rule, runs, baseline-day choice, RINEX 3 parsing.

Synthetic data only (no network, no hatanaka). Run as a plain script: python tests/test_station_cn0.py
"""
import math, os, sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import station_cn0 as S  # noqa: E402

T = S.NEP


def pass_track(centre_s, half_s=3 * 3600, peak=70.0):
    """A satellite pass: elevation peaks at centre_s (seconds of day); azimuth sweeps 60 -> 300 deg."""
    t = np.arange(T) * S.STEP
    x = (t - centre_s) / half_s
    el = np.where(np.abs(x) < 1, peak * np.cos(x * math.pi / 2) - 5, np.nan)
    az = np.where(np.abs(x) < 1, 180 + 120 * x, np.nan)
    return az, el


def cn0_of(el):
    return 35 + 0.2 * el                 # C/N0 rises with elevation


def test_match_sidereal():
    # Baseline day 3 days earlier: the same pass comes 3 x 250 s later in the day (true shift 250 s, nominal 246 s)
    t_az, t_el = pass_track(40000)
    b_az, b_el = pass_track(40000 + 3 * 250)
    b_val = cn0_of(b_el) + 1.0           # the baseline day reads 1 dB-Hz high everywhere
    out = S.match_sidereal(t_az, t_el, b_az, b_el, b_val, k_days=3)
    ok = np.isfinite(t_el) & (t_el > 10)
    assert np.isfinite(out[ok]).mean() > 0.99, np.isfinite(out[ok]).mean()
    err = out[ok] - (cn0_of(t_el[ok]) + 1.0)
    assert np.nanmax(np.abs(err)) < 0.2, np.nanmax(np.abs(err))      # within 0.2 dB-Hz: matched by sky position
    # A different orbit (pass 2 h away) is beyond the +-15 min window: no match, not a wrong value
    b_az2, b_el2 = pass_track(40000 + 7200)
    out2 = S.match_sidereal(t_az, t_el, b_az2, b_el2, cn0_of(b_el2), k_days=3)
    assert not np.isfinite(out2[(t_el > 50)]).any()


def test_combine_baseline():
    stack = np.array([[1.0, 2.0, np.nan], [3.0, np.nan, np.nan], [5.0, 4.0, 7.0]])
    med, cnt = S.combine_baseline(stack)
    assert med[0] == 3.0 and list(cnt) == [3, 2, 1]
    assert np.isnan(med[1]) and np.isnan(med[2])                         # fewer than 3 baseline days


def synthetic_day(nsat=8, drop=None, drop_sats=None, lost=None, missing_epochs=None):
    """Test-day C/N0, baseline, counts and elevations for nsat satellites, all above the mask all day."""
    el = np.full((nsat, T), 45.0)
    el[0, :] = 10.0                                                      # satellite 0 is below the 15 deg mask
    base = np.full((nsat, T), 45.0)
    cnt = np.full((nsat, T), 5)
    rng = np.random.default_rng(1)
    test = base + rng.normal(0, 0.5, (nsat, T))
    if drop:
        a, b, db = drop
        for s in (drop_sats if drop_sats is not None else range(nsat)):
            test[s, a:b] -= db
    if lost:
        a, b, sats = lost
        for s in sats:
            test[s, a:b] = np.nan
    present = np.ones(T, bool)
    if missing_epochs:
        present[missing_epochs[0]:missing_epochs[1]] = False
        test[:, missing_epochs[0]:missing_epochs[1]] = np.nan
    return test, base, cnt, el, present


def flagged(test, base, cnt, el, present):
    r = S.residuals(test, base, cnt, el, present)
    D, F, n = S.station_stats(r)
    flags, d5, f5 = S.flag_epochs(D, F)
    return S.runs(flags), D, F, n, r


def test_residuals_and_loss():
    test, base, cnt, el, present = synthetic_day(lost=(100, 110, [3]), missing_epochs=(200, 210))
    r = S.residuals(test, base, cnt, el, present)
    assert np.isnan(r[0]).all()                                          # below the mask
    assert (r[3, 100:110] == S.LOSS_DB).all()                            # tracked on baseline days, lost today
    assert np.isnan(r[:, 200:210]).all()                                 # epochs missing from the file: no score
    cnt2 = cnt.copy(); cnt2[4, :] = 2
    r2 = S.residuals(test, base, cnt2, el, present)
    assert np.isnan(r2[4]).all()                                         # under 3 baseline days: not scored
    r3 = S.residuals(test, base, cnt, el, present, count_loss=False)
    assert np.isnan(r3[3, 100:110]).all()
    D, F, n = S.station_stats(r)
    assert n[50] == 7 and abs(D[50]) < 1.0 and F[50] < 0.2


def test_drop_rule():
    # 10-minute 6 dB drop on every satellite: one run of about 10 minutes
    rs, D, F, n, _ = flagged(*synthetic_day(drop=(1000, 1020, 6.0)))
    assert len(rs) == 1, rs
    a, b = rs[0]
    assert abs(a - 1000) <= 3 and abs(b - 1019) <= 3, rs
    # the same drop on 2 of 7 scored satellites (multipath, obstruction): not simultaneous, no flag
    rs, *_ = flagged(*synthetic_day(drop=(1000, 1020, 6.0), drop_sats=[1, 2]))
    assert rs == [], rs
    # a 2 dB drop on every satellite: below the 3 dB-Hz threshold
    rs, *_ = flagged(*synthetic_day(drop=(1000, 1020, 2.0)))
    assert rs == [], rs
    # a 1-minute drop (2 epochs) is removed by the 5-minute running median
    rs, *_ = flagged(*synthetic_day(drop=(1000, 1002, 10.0)))
    assert rs == [], rs
    # loss of lock on all satellites for 8 minutes counts as a drop
    rs, D, *_ = flagged(*synthetic_day(lost=(500, 516, range(8))))
    assert len(rs) == 1 and D[505] == S.LOSS_DB, rs
    # quiet day: nothing
    rs, *_ = flagged(*synthetic_day())
    assert rs == []
    # too few satellites (3 scored) never scores
    test, base, cnt, el, present = synthetic_day(nsat=4, drop=(1000, 1040, 8.0))
    rs, D, *_ = flagged(test, base, cnt, el, present)
    assert rs == [] and np.isnan(D).all()


def test_runs():
    f = np.zeros(200, bool)
    f[10:20] = True; f[23:30] = True        # gap of 3 epochs (90 s): merged
    f[50:60] = True; f[67:80] = True        # gap of 7 epochs (210 s): separate
    f[100:103] = True                       # 90 s long: dropped
    assert S.runs(f) == [(10, 29), (50, 59), (67, 79)], S.runs(f)
    m = S.run_mask([(10, 29)], 200)
    assert m.sum() == 20
    assert S.runs(np.zeros(5, bool)) == []


def test_rolling_median():
    x = np.array([0, 0, 0, 0, 0, -9, 0, 0, 0, 0, 0, 0, 0], float)
    assert (S.rolling_median(x, 11)[np.isfinite(S.rolling_median(x, 11))] == 0).all()
    y = np.full(20, np.nan); y[:4] = 1.0
    r = S.rolling_median(y, 11)
    assert np.isnan(r).all()                # never 6 valid values in a window


def test_elbin_baseline():
    rng = np.random.default_rng(2)
    els = [rng.uniform(0, 90, (5, 100)) for _ in range(4)]
    vals = [cn0_of(e) for e in els]
    test_el = np.array([[20.0, 50.0, 10.0, np.nan]])
    base, cnt = S.elbin_baseline(vals, els, test_el)
    assert abs(base[0, 0] - cn0_of(21.25)) < 0.3 and abs(base[0, 1] - cn0_of(51.25)) < 0.3, base
    assert cnt[0, 0] == 4 and np.isnan(base[0, 3])


def test_minutes_and_aircraft():
    x = np.zeros(T); x[:4] = 10.0
    m = S.epochs_to_minutes(x)
    # epoch 0 (GPS 00:00:00) is UTC 23:59:42 the day before: dropped; epochs 1-2 -> minute 0; epoch 3 -> minute 1
    assert m[0] == 10.0 and m[1] == 5.0 and m[2] == 0.0
    f = np.zeros(T, bool); f[10] = True
    assert S.epochs_to_minutes(f, how="any").sum() == 1
    day = "2026-05-09"
    t0 = S.unix_day0(day)
    t = np.array([t0 + 10, t0 + 20, t0 + 30, t0 + 70, t0 + 70, t0 - 5])
    lat = np.array([55.0, 55.0, 55.0, 55.0, 57.0, 55.0])                # the fifth point is ~220 km away
    lon = np.full(6, 20.0)
    adsb = np.array([True, True, False, True, True, True])              # the third point is MLAT
    nacp = np.array([10, 5, 3, -1, 2, 2])                               # the fourth has no NACp yet
    n, bad = S.aircraft_minutes(t, lat, lon, adsb, nacp, 55.0, 20.0, day)
    assert n[0] == 2 and bad[0] == 1 and n[1] == 0 and n.sum() == 2


def test_lag_corr():
    rng = np.random.default_rng(3)
    x = rng.normal(size=600)
    y = np.full(600, np.nan); y[5:] = x[:-5]                            # aircraft follow the station by 5 minutes
    lag, r, r0 = S.lag_corr(x, y)
    assert lag == 5 and r > 0.99 and abs(r0) < 0.2, (lag, r, r0)


def test_pick_baseline():
    shares = {"2026-05-0%d" % d: (s, 100) for d, s in ((1, 1.0), (2, 9.0), (3, 2.0), (4, 3.0), (5, 1.5), (6, 1.0),
                                                     (7, 8.0), (8, 2.5), (9, 40.0))}
    shares["2026-05-10"] = (1.0, 10)                                    # too few aircraft-hexes
    days, med = S.pick_baseline("2026-05-09", shares, exclude={"2026-05-06"}, n=3)
    assert med == 2.5, med                                              # median over days with >= 50 aircraft-hexes
    assert days == ["2026-05-08", "2026-05-05", "2026-05-03"], days     # nearest quiet; 7 and 4 May above it, 6 May excluded
    assert S.pick_baseline("2026-05-09", {}) == (None, None)
    assert S.nearest_days("2025-06-15", n=4) == ["2025-06-14", "2025-06-16", "2025-06-13", "2025-06-17"]


def test_verdict():
    J, Q = ["a", "b", "c"], ["q1", "q2"]
    assert S.verdict({"a": 30, "b": 12, "c": 0, "q1": 0, "q2": 2}, J, Q) == "PRESENT"
    assert S.verdict({"a": 30, "b": 12, "c": 0, "q1": 0, "q2": 5}, J, Q) == "MIXED"
    assert S.verdict({"a": 3, "b": 0, "c": None, "q1": 0, "q2": 0}, J, Q) == "NULL"
    assert S.verdict({"a": None}, J, Q) == "NO DATA"


def hline(content, label):
    return f"{content:<60}{label:<20}"


def obs_rec(vals):
    return "".join(" " * 16 if v is None else f"{v:14.3f}  " for v in vals)


RINEX_OBS = "\n".join([
    hline("     3.04           OBSERVATION DATA    M", "RINEX VERSION / TYPE"),
    hline("TEST", "MARKER NAME"),
    hline("12345               TESTRECEIVER        1.0", "REC # / TYPE / VERS"),
    hline("1                   TESTANT         NONE", "ANT # / TYPE"),
    hline("  3524523.2669  1329693.4580  5129846.1890", "APPROX POSITION XYZ"),
    hline("G    4 C1C L1C S1C S2W", "SYS / # / OBS TYPES"),
    hline("E    2 C1C S1C", "SYS / # / OBS TYPES"),
    hline("R    1 S1C", "SYS / # / OBS TYPES"),
    hline("DBHZ", "SIGNAL STRENGTH UNIT"),
    hline("    30.000", "INTERVAL"),
    hline("CC BY 4.0", "LICENSE OF USE"),
    hline("", "END OF HEADER"),
    "> 2026 05 09 00 00  0.0000000  0  3",
    "G01" + obs_rec([22000000.123, 115000000.5, 45.25, 38.0]),
    "E11" + obs_rec([23000000.0, 47.5]),
    "R05" + obs_rec([41.0]),
    "> 2026 05 09 00 00 30.0000000  0  2",
    "G 1" + obs_rec([22000001.0, 115000005.0, None, 37.5]),            # blank S1C; "G 1" spelling
    "G12" + obs_rec([21000000.0, 110000000.0, 50.0]),                  # short line: S2W missing
    "> 2026 05 09 00 01 00.0000000  4  1",                             # event record: 1 header line follows
    hline("ANTENNA MOVED?", "COMMENT"),
    "> 2026 05 09 00 01 15.0000000  0  1",                             # off the 30 s grid: ignored
    "G01" + obs_rec([1.0, 2.0, 30.0, 30.0]),
    "> 2026 05 09 23 59 30.0000000  0  1",
    "G05" + obs_rec([1.0, 2.0, 41.5, 33.0]),
    ""])


def test_parse_obs():
    hdr, obs, present = S.parse_obs(RINEX_OBS, "2026-05-09")
    assert hdr["version"] == "3.04" and hdr["receiver"] == "TESTRECEIVER" and hdr["antenna"] == "TESTANT         NONE"
    assert hdr["xyz"] == [3524523.2669, 1329693.458, 5129846.189] and hdr["licence"] == ["CC BY 4.0"]
    assert hdr["types"] == {"G": ["S1C", "S2W"], "E": ["S1C"]}, hdr["types"]       # GLONASS not kept
    assert present[0] and present[1] and not present[2] and present[2879] and present.sum() == 3
    assert obs["G01"]["S1C"][0] == np.float32(45.25) and obs["G01"]["S2W"][0] == 38.0
    assert np.isnan(obs["G01"]["S1C"][1]) and obs["G01"]["S2W"][1] == 37.5
    assert obs["G12"]["S1C"][1] == 50.0 and "S2W" not in obs["G12"]
    assert obs["E11"]["S1C"][0] == 47.5 and "R05" not in obs
    assert obs["G05"]["S1C"][2879] == np.float32(41.5)
    assert np.isfinite(obs["G01"]["S1C"]).sum() == 1                    # the 00:01:15 epoch was not stored
    try:
        S.parse_obs(hline("     2.11           OBSERVATION DATA    M", "RINEX VERSION / TYPE") + "\n", "2026-05-09")
        raise AssertionError("RINEX 2 accepted")
    except ValueError:
        pass


def nav_rec(sat, vals):
    """A RINEX 3 Keplerian navigation record: 29 values over 8 lines."""
    f = lambda x: f"{x:19.12E}"
    lines = [f"{sat} 2026 05 09 00 00 00" + "".join(f(v) for v in vals[0:3])]
    for k in range(7):
        lines.append("    " + "".join(f(v) for v in vals[3 + 4 * k:7 + 4 * k]))
    return lines


def test_nav_and_geometry():
    week = 2400
    a = 26560e3
    v = [0.0] * 29
    v[10] = math.sqrt(a)        # sqrt(A)
    v[11] = 3600.0              # toe
    v[21] = week                # GPS week
    rec = nav_rec("G07", v)
    sick = nav_rec("G08", v[:24] + [1.0] + v[25:])                     # SV health 1: unusable
    text = "\n".join([hline("     3.04           N: GNSS NAV DATA    M", "RINEX VERSION / TYPE"),
                      hline("", "END OF HEADER")] + rec + ["R01 2026 05 09 00 15 00" + " 0.0" * 3, "     0.0", "     0.0", "     0.0"]
                     + sick + [""])
    eph = S.parse_nav(text)
    assert set(eph) == {"G07", "G08"} and eph["G07"][0]["toe"] == 3600.0 and eph["G07"][0]["week"] == week
    e = eph["G07"][0]
    t = np.array([week * 604800.0 + 3600.0])
    xyz = S.sat_xyz(e, t)[0]
    # circular equatorial orbit at toe with all angles zero: on the x axis, rotated back by Earth rotation over toe
    ang = -7.2921151467e-5 * 3600.0
    assert np.allclose(xyz, [a * math.cos(ang), a * math.sin(ang), 0.0], atol=1e-3), xyz
    assert abs(np.linalg.norm(S.sat_xyz(e, t + 3000.0)[0]) - a) < 1e-3
    # a satellite straight above an equatorial station is at 90 deg; one beyond the limb is below the horizon
    sta = [6378137.0 * math.cos(ang), 6378137.0 * math.sin(ang), 0.0]
    az, el = S.azel(xyz[None, :], sta)
    assert abs(el[0] - 90.0) < 1e-6
    az, el = S.azel(np.array([[-a, 0.0, 0.0]]), [6378137.0, 0.0, 0.0])
    assert el[0] < -80
    lat, lon, h = S.ecef_to_geodetic(3524523.2669, 1329693.458, 5129846.189)
    assert abs(lat - 53.892) < 0.01 and abs(lon - 20.670) < 0.01 and 100 < h < 250, (lat, lon, h)


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
        sys.exit(f"test_station_cn0: {failed} of {len(tests)} failed")
    print(f"test_station_cn0: ok ({len(tests)} tests)")


if __name__ == "__main__":
    main()
