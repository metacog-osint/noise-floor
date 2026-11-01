"""Offline tests for tools/station_bands.py: orbits for every constellation, signal table, baselines, loss counting,
signatures, and station_cn0's keep="all" parsing and local-file lookup.

The navigation records below are copied from the IGS merged broadcast file for 16 May 2026 (BRDC00IGS_R_20261360000,
public). Everything else is synthetic. Run as a plain script: python tests/test_station_bands.py
"""
import math
import os
import shutil
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import station_bands as B  # noqa: E402
import station_cn0 as S  # noqa: E402

T = S.NEP


def hline(content, label):
    return f"{content:<60}{label:<20}"


NAV = "\n".join([
    hline("     3.04           N: GNSS NAV DATA    M: MIXED", "RINEX VERSION / TYPE"),
    hline("", "END OF HEADER"),
    "R01 2026 05 16 06 15 00 1.697568222880E-04 9.094947017729E-13 5.400000000000E+05",
    "     1.216974316406E+04-7.828884124756E-01-1.862645149231E-09 0.000000000000E+00",
    "    -8.828728515625E+03 2.713756561279E+00-3.725290298462E-09 1.000000000000E+00",
    "    -2.061084912109E+04-1.622569084167E+00 0.000000000000E+00 0.000000000000E+00",
    "R01 2026 05 16 06 45 00 1.697596162558E-04 9.094947017729E-13 5.418000000000E+05",
    "     1.108051464844E+04-4.050655364990E-01-1.862645149231E-09 0.000000000000E+00",
    "    -3.570161621094E+03 3.082984924316E+00-1.862645149231E-09 1.000000000000E+00",
    "    -2.269734960938E+04-6.806688308716E-01 1.862645149231E-09 0.000000000000E+00",
    "C01 2026 05 16 06 00 00-7.685739547010E-07-3.019806626980E-14 0.000000000000E+00",
    "     1.000000000000E+00-4.165156250000E+02 1.168655822060E-08-5.831873666550E-01",
    "    -1.339195296170E-05 3.411869984120E-04-3.057252615690E-05 6.493353809360E+03",
    "     5.400000000000E+05-4.279427230360E-07-1.459664804010E+00-5.527399480340E-07",
    "     7.769502913270E-02 9.341093750000E+02-1.186041200410E-01-1.073580433220E-08",
    "     2.857261873570E-11 0.000000000000E+00 1.062000000000E+03 0.000000000000E+00",
    "     2.000000000000E+00 0.000000000000E+00 4.499999928240E-09 4.500000000000E-09",
    "     5.400000000000E+05 1.000000000000E+00",
    "C03 2026 05 16 06 00 00-4.895264282820E-07 2.664535259100E-14 0.000000000000E+00",
    "     1.000000000000E+00 4.068281250000E+02 1.168655822060E-08 5.929935844940E-01",
    "     1.348834484820E-05 3.104625502600E-04-3.076996654270E-05 6.493400684360E+03",
    "     5.400000000000E+05-3.771856427190E-07-1.856914327500E+00-4.190951585770E-07",
    "     1.044316476430E-01 9.481250000000E+02-1.413406460980E+00-1.081580766470E-08",
    "     3.307280618660E-10 0.000000000000E+00 1.062000000000E+03 0.000000000000E+00",
    "     2.000000000000E+00 0.000000000000E+00 3.530000114440E-08 3.530000000000E-08",
    "     5.400000000000E+05 1.000000000000E+00",
    "C19 2026 05 16 06 00 00-9.424918098375E-04 2.588151915006E-12 0.000000000000E+00",
    "     1.000000000000E+00-6.665625000000E+01 2.979409818664E-09-1.886656206918E+00",
    "    -3.325752913952E-06 1.027536927722E-03 1.277681440115E-05 5.282637231827E+03",
    "     5.400000000000E+05 2.328306436539E-09-2.856481387755E+00 7.916241884232E-09",
    "     9.893359100632E-01 1.197343750000E+02-4.854672638544E-01-6.157399337540E-09",
    "     6.725280134912E-10 0.000000000000E+00 1.062000000000E+03",
    "     2.000000000000E+00 0.000000000000E+00 9.300000000000E-09 9.300000000000E-09",
    "     5.400000000000E+05 0.000000000000E+00",
    "C19 2026 05 16 07 00 00-9.424826130271E-04 2.576605595550E-12 0.000000000000E+00",
    "     1.000000000000E+00-7.098437500000E+01 2.975123925853E-09-1.399837143853E+00",
    "    -3.600493073463E-06 1.027501304634E-03 1.251138746738E-05 5.282635740280E+03",
    "     5.436000000000E+05 8.381903171539E-09-2.856503580223E+00 8.381903171539E-09",
    "     9.893383297297E-01 1.232968750000E+02-4.847256170533E-01-6.159899441680E-09",
    "     6.757424330990E-10 0.000000000000E+00 1.062000000000E+03",
    "     2.000000000000E+00 0.000000000000E+00 9.300000000000E-09 9.300000000000E-09",
    "     5.436000000000E+05 0.000000000000E+00",
    "J02 2026 05 16 06 00 00-1.816079020500E-07-1.136868377220E-13 0.000000000000E+00",
    "     1.490000000000E+02 9.893125000000E+02 1.810789712370E-10-8.511894734700E-01",
    "     3.258138895030E-05 7.586981868370E-02 1.374073326590E-05 6.493083370210E+03",
    "     5.400000000000E+05-5.271285772320E-07 2.768979829180E-01 3.106892108920E-06",
    "     6.899128683830E-01-2.015937500000E+02-1.587734954920E+00-6.310977163240E-10",
    "    -1.019328173400E-09 0.000000000000E+00 2.418000000000E+03 1.000000000000E+00",
    "     2.800000000000E+00 1.000000000000E+00 1.396983861920E-09 9.170000000000E+02",
    "     5.364060000000E+05 1.000000000000E+00",
    ""])
DAY = "2026-05-16"


def geodetic(x):
    lat, lon, _ = S.ecef_to_geodetic(*x)
    return lat, lon, float(np.linalg.norm(x)) / 1e3


def test_parse_nav_all():
    kep, glo = B.parse_nav_all(NAV)
    assert sorted(kep) == ["C01", "C03", "C19", "J02"] and sorted(glo) == ["R01"], (sorted(kep), sorted(glo))
    assert len(kep["C19"]) == 2 and len(glo["R01"]) == 2
    c01 = kep["C01"][0]
    # BeiDou: toe is BDT seconds of BDT week 1062; BDT week 0 = GPS week 1356 and BDT = GPS - 14 s
    assert c01["week"] == 1062 and c01["toe"] == 540000.0
    assert c01["toe_abs"] == S.gps_seconds(DAY) + 6 * 3600 + 14, c01["toe_abs"] - S.gps_seconds(DAY)
    assert kep["J02"][0]["toe_abs"] == S.gps_seconds(DAY) + 6 * 3600       # QZSS runs on GPS time
    r = glo["R01"][0]
    assert r["k"] == 1 and r["health"] == 0
    assert r["t"] == S.gps_seconds(DAY) + 6 * 3600 + 15 * 60 + S.LEAP      # GLONASS epochs are UTC
    assert abs(r["pos"][0] - 12169743.16406) < 1e-3 and abs(r["vel"][1] - 2713.756561279) < 1e-6
    assert [B.orbit_class(kep[s][0]) for s in ("C01", "C03", "C19", "J02")] == ["geo", "geo", "meo", "igso"]


def test_beidou_geo():
    kep, _ = B.parse_nav_all(NAV)
    for sat, slot in (("C01", 140.0), ("C03", 110.5)):        # published GEO slots
        e = kep[sat][0]
        p0 = B.kep_xyz(e, np.array([e["toe_abs"]]))[0]
        lat, lon, r = geodetic(p0)
        assert abs(lon - slot) < 0.5 and abs(lat) < 5 and 42100 < r < 42250, (sat, lat, lon, r)
        # Without the GEO rotation the satellite would sweep ~11,000 km an hour in the Earth-fixed frame. With it, only
        # the inclination moves it: C03 swings about 2.3 deg north-south, up to ~120 m/s (~440 km an hour)
        p1 = B.kep_xyz(e, np.array([e["toe_abs"] + 3600]))[0]
        assert np.linalg.norm(p1 - p0) < 1000e3, np.linalg.norm(p1 - p0)


def test_beidou_meo_consecutive_records():
    kep, _ = B.parse_nav_all(NAV)
    a, b = kep["C19"]
    tm = np.array([(a["toe_abs"] + b["toe_abs"]) / 2])
    pa, pb = B.kep_xyz(a, tm)[0], B.kep_xyz(b, tm)[0]
    assert np.linalg.norm(pa - pb) < 5.0, np.linalg.norm(pa - pb)
    assert 27800 < geodetic(pa)[2] < 28000


def test_qzss_igso():
    kep, _ = B.parse_nav_all(NAV)
    e = kep["J02"][0]
    t = e["toe_abs"] + np.arange(0, 86400, 3600.0)
    lon = np.array([geodetic(p)[1] for p in B.kep_xyz(e, t)])
    r = np.linalg.norm(B.kep_xyz(e, t), axis=1) / 1e3
    assert np.all((r > 32000) & (r < 52000)), r            # eccentric quasi-zenith orbit
    assert np.all((lon > 100) & (lon < 175)), lon           # its figure-of-eight stays over the western Pacific


def test_glonass_propagation():
    _, glo = B.parse_nav_all(NAV)
    a, b = glo["R01"]
    dt = b["t"] - a["t"]
    assert dt == 1800.0
    fwd = B.glo_propagate([a], np.array([[dt]]))[0, 0]
    back = B.glo_propagate([b], np.array([[-dt]]))[0, 0]
    assert np.linalg.norm(fwd - np.array(b["pos"])) < 20.0, np.linalg.norm(fwd - np.array(b["pos"]))
    assert np.linalg.norm(back - np.array(a["pos"])) < 20.0
    # Several offsets in one call, as the day grid needs them
    many = B.glo_propagate([a, a], np.array([[0.0, 900.0, dt], [0.0, -30.0, np.nan]]))
    assert np.allclose(many[0, 0], a["pos"]) and np.linalg.norm(many[0, 2] - fwd) < 1e-3 and np.isnan(many[1, 2]).all()
    # glonass_xyz on a grid: nearest record within max_age, NaN beyond
    t = np.array([a["t"] - 1000, a["t"] + 600, b["t"] + 1700, b["t"] + 4000])
    xyz = B.glonass_xyz(glo["R01"], t)
    assert np.isfinite(xyz[:3]).all() and np.isnan(xyz[3]).all()
    assert 25400e3 < np.linalg.norm(xyz[1]) < 25600e3


def test_sky_all():
    kep, glo = B.parse_nav_all(NAV)
    sta = [-3642161.2689, 2861487.8616, 4370351.3311]        # a station in Hokkaido
    sky, meta = B.sky_all(kep, glo, sta, DAY)
    assert set(sky) == {"C01", "C03", "C19", "J02", "R01"}, set(sky)
    az, el = sky["C01"]
    t6 = (6 * 3600) // S.STEP
    assert 30 < el[t6] < 60 and 150 < az[t6] < 220, (el[t6], az[t6])      # GEO at 140 E seen from 43 N 142 E: south
    assert np.isnan(el[0])                                     # 6 h from the only record: beyond max_age
    assert meta["R01"]["k"] == 1 and meta["C01"]["orbit"] == "geo" and meta["J02"]["health"] == [1.0]


def test_glonass_mhz():
    assert B.glonass_mhz(0, 1) == 1602.0 and B.glonass_mhz(0, 2) == 1246.0
    assert B.glonass_mhz(-7, 1) == 1598.0625 and B.glonass_mhz(6, 2) == 1248.625


def test_signal_table():
    seen = {}
    for name, sysc, codes, mhz in B.SIGNALS:
        for c in codes:
            assert (sysc, c) not in seen, f"{sysc} {c} in both {seen.get((sysc, c))} and {name}"
            seen[(sysc, c)] = name
            assert c.startswith("S") and len(c) == 3
        assert (mhz is None) == (sysc == "R" and name[8:10] in ("G1", "G2")), name
    assert B.pick_code({"C": {"S7I", "S7D"}}, "C", ["S7D", "S7P"]) == "S7D"
    assert B.pick_code({"G": {"S2W", "S2L"}}, "G", ["S2L", "S2S", "S2X"]) == "S2L"
    assert B.pick_code({"G": {"S1C"}}, "E", ["S1C"]) is None


def test_kind_of():
    meta = {"C01": {"orbit": "geo"}, "C08": {"orbit": "igso"}, "C19": {"orbit": "meo"}}
    assert B.kind_of("G05", meta) == ("sky", S.SHIFT_S)
    assert B.kind_of("J02", {}) == ("sky", B.SHIFT_1SD) and abs(B.SHIFT_1SD - 235.9) < 0.1
    assert B.kind_of("C01", meta)[0] == "sky" and B.kind_of("C08", meta)[0] == "sky"
    assert B.kind_of("C19", meta) == ("elbin", None) and B.kind_of("R05", meta)[0] == "elbin"
    assert B.kind_of("E11", meta)[0] == "elbin"


def test_sat_elbin_baseline():
    el = np.linspace(10, 80, T)
    days = [np.where(np.arange(T) < T // 2, 40.0 + 0.1 * el, np.nan) for _ in range(3)]
    els = [el.copy() for _ in range(3)]
    test_el = np.full(T, 30.0)
    base, cnt = B.sat_elbin_baseline(days, els, test_el)
    assert np.allclose(base, 40.0 + 0.1 * 31.25, atol=0.15) and (cnt == 3).all(), (base[0], cnt[0])
    # Elevations the baseline days never reached have no baseline
    base, cnt = B.sat_elbin_baseline(days, els, np.full(T, 70.0))
    assert np.isnan(base).all() and (cnt == 0).all()
    # Two days are not enough
    base, _ = B.sat_elbin_baseline(days[:2], els[:2], test_el)
    assert np.isnan(base).all()


def test_tracked_sky_and_loss():
    nsat = 6
    az = np.tile(np.linspace(0, 359, T), (nsat, 1))
    el = np.full((nsat, T), 45.0)
    v = np.full((nsat, T), 45.0)
    blocked = az < 30                                           # the baseline days never track the 0-30 deg sector
    v[blocked] = np.nan
    sky_ok = B.tracked_sky([(v, az, el)] * 3)
    cells = B.sky_cells(az[0], el[0])
    assert not sky_ok[cells[az[0] < 29]].any() and sky_ok[cells[(az[0] > 31) & (az[0] < 359)]].all()
    test = np.full((nsat, T), 45.0)
    test[:, :] = np.nan                                         # everything missing on the test day ...
    base = np.full((nsat, T), 45.0)
    cnt = np.full((nsat, T), 5)
    loss_ok = np.where(cells >= 0, sky_ok[np.clip(cells, 0, None)], False)[None, :].repeat(nsat, 0)
    r = B.score(test, base, cnt, el, np.ones(T, bool), loss_ok, np.ones(nsat, bool))
    assert (r[:, az[0] > 31] == S.LOSS_DB).all()               # ... counts as lost where the sky is normally tracked
    assert np.isnan(r[:, az[0] < 29]).all()                    # ... but not in the obstructed sector
    r = B.score(test, base, cnt, el, np.ones(T, bool), loss_ok, np.zeros(nsat, bool))
    assert np.isnan(r).all()                                    # satellites not kept are never scored


def test_tracked_enough():
    el = np.full((3, T), 40.0)
    v = np.full((3, T), np.nan)
    v[0] = 45.0
    v[1, : int(0.05 * T)] = 45.0
    v[2, : int(0.2 * T)] = 45.0
    assert list(B.tracked_enough(v, el)) == [True, False, True]


def test_utc_epochs_and_merge():
    a, b = B.utc_epochs("00:09-00:18")
    assert (a, b) == (19, 36), (a, b)                           # 00:09:18 and 00:18:18 GPS on the 30 s grid
    assert B.utc_epochs("23:50-23:59")[1] <= S.NEP - 1
    assert B.merge_runs([[(10, 20), (100, 110)], [(22, 30)], [(200, 210)]]) == [(10, 30), (100, 110), (200, 210)]
    assert B.merge_runs([[(10, 20)], [(26, 30)]]) == [(10, 20), (26, 30)]       # 5 epochs = 150 s apart: not merged


def test_signature_and_ladder():
    def fake(d, mhz, sats=("R01", "R02"), lose=False):
        D = np.zeros(T)
        D[100:120] = d
        r = np.zeros((len(sats), T))
        r[:, 100:120] = d
        if lose:
            r[1, 100:120] = S.LOSS_DB
        return {"D": D, "d5": D.copy(), "n": np.full(T, len(sats)), "r": r, "sats": list(sats), "code": "S1C", "mhz": mhz}
    per = {"GPS L1 C/A": fake(-5.0, 1575.42), "GPS L5": fake(-1.0, 1176.45),
           "GLONASS G1 C/A": fake(-3.0, [1602.5625, 1600.875], lose=True)}
    sig = B.signature(per, 100, 119)
    assert [x["signal"] for x in sig] == ["GPS L5", "GPS L1 C/A", "GLONASS G1 C/A"]          # sorted by carrier
    assert sig[1]["d_median"] == -5.0 and sig[0]["d_median"] == -1.0 and sig[2]["lost_share"] == 0.5
    lad = B.glonass_ladder(per, {"R01": {"k": 1}, "R02": {"k": -2}}, 100, 119)
    assert [(x["sat"], x["k"], x["mhz"]) for x in lad] == [("R02", -2, 1600.875), ("R01", 1, 1602.5625)]
    assert lad[0]["residual"] == S.LOSS_DB and lad[0]["lost"] == 20 and lad[1]["residual"] == -3.0


OBS = "\n".join([
    hline("     3.04           OBSERVATION DATA    M", "RINEX VERSION / TYPE"),
    hline("  3196720.0000  1300210.0000  5335130.0000", "APPROX POSITION XYZ"),
    hline("G    3 C1C S1C S5Q", "SYS / # / OBS TYPES"),
    hline("R    3 S1C S2C S2P", "SYS / # / OBS TYPES"),
    hline("C    2 S2I S7D", "SYS / # / OBS TYPES"),
    hline("J    1 S1Z", "SYS / # / OBS TYPES"),
    hline("", "END OF HEADER"),
    "> 2026 05 17 00 00  0.0000000  0  4",
    "G01" + "".join(f"{v:14.3f}  " for v in (22000000.0, 45.0, 48.5)),
    "R05" + "".join(f"{v:14.3f}  " for v in (41.0, 39.5, 39.0)),
    "C20" + "".join(f"{v:14.3f}  " for v in (44.0, 46.0)),
    "J02" + "".join(f"{v:14.3f}  " for v in (47.0,)),
    ""])


def test_parse_obs_keep_all():
    hdr, obs, _ = S.parse_obs(OBS, "2026-05-17")
    assert set(obs) == {"G01"} and set(obs["G01"]) == {"S1C", "S5Q"}       # default: station_cn0's codes; no R, C or J
    hdr, obs, _ = S.parse_obs(OBS, "2026-05-17", keep="all")
    assert set(obs["R05"]) == {"S1C", "S2C", "S2P"} and set(obs["C20"]) == {"S2I", "S7D"}
    assert obs["J02"]["S1Z"][0] == 47.0 and obs["G01"]["S5Q"][0] == 48.5 and "C1C" not in obs["G01"]


def test_local_raw():
    tmp = tempfile.mkdtemp()
    old = S.RAW
    try:
        S.RAW = tmp
        sub = os.path.join(tmp, "2026", "137")
        os.makedirs(sub)
        for f in ("VAIN00LVA_S_20261370000_01D_30S_MO.crx.gz", "BRDC00IGS_R_20261370000_01D_MN.rnx.gz", "p0261370.26d.gz"):
            with open(os.path.join(sub, f), "wb") as fh:
                fh.write(b"x")
        with open(os.path.join(sub, "RIGA00LVA_R_20261370000_01D_30S_MO.crx.gz"), "wb"):
            pass                                                   # empty file: treated as absent
        obs, nav = S.local_raw("VAIN00LVA", "2026-05-17")
        assert obs.endswith("VAIN00LVA_S_20261370000_01D_30S_MO.crx.gz") and nav.endswith("BRDC00IGS_R_20261370000_01D_MN.rnx.gz")
        assert S.local_raw("RIGA00LVA", "2026-05-17")[0] is None
        assert S.local_raw("P026", "2026-05-17")[0].endswith("p0261370.26d.gz")
        assert S.local_raw("VAIN00LVA", "2026-05-18") == (None, None)
        assert S.fetch("VAIN00LVA", "2026-05-17") == (obs, nav)    # held files: no network
    finally:
        S.RAW = old
        shutil.rmtree(tmp, ignore_errors=True)


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
        sys.exit(f"test_station_bands: {failed} of {len(tests)} failed")
    print(f"test_station_bands: ok ({len(tests)} tests)")


if __name__ == "__main__":
    main()
