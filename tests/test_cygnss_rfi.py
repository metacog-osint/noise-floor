"""Offline tests for tools/cygnss_rfi.py and tools/cygnss_checks.py (CYGNSS noise-floor interference lane).
No network, no data/ files."""
import json, os, shutil, sys, tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cygnss_rfi as C  # noqa: E402
import cygnss_checks as K  # noqa: E402


def test_gaps():
    # 1 s cadence, a 101 s jump after t = 99 (100 samples missing), then a 3 s hiccup that is not a gap.
    t = np.concatenate([np.arange(0, 100.0), np.arange(200, 300.0), [303.0]])
    lat = np.linspace(0, 10, len(t))
    lon = np.linspace(20, 40, len(t))
    mlat, mlon, cad = C.gaps(t, lat, lon)
    assert cad == 1.0
    assert len(mlat) == 100, len(mlat)
    a, b = 99, 100  # the samples either side of the gap
    assert np.all((mlat > lat[a]) & (mlat < lat[b])) and np.all((mlon > lon[a]) & (mlon < lon[b]))
    assert np.all(np.diff(mlon) > 0)
    # a gap longer than MAX_GAP is not filled
    t2 = np.array([0.0, 1.0, 2.0, 2.0 + C.MAX_GAP + 10, 3.0 + C.MAX_GAP + 10])
    assert len(C.gaps(t2, np.zeros(5), np.arange(5.0))[0]) == 0


def test_group_median():
    v = np.array([5.0, 1.0, 3.0, 10.0, 20.0, 7.0])
    g = np.array([0, 0, 0, 2, 2, 2])
    med, ug, _, cnt, _ = C.group_median(v, g)
    assert med[0] == 3.0 and med[2] == 10.0 and np.isnan(med[1])
    assert list(ug) == [0, 2] and list(cnt) == [3, 3]


def test_excess_leaves_hot_cells_out_of_the_baseline():
    rng = np.random.default_rng(1)
    n = 20000
    sc = rng.integers(1, 4, n).astype("int16")
    ant = rng.integers(2, 4, n).astype("int16")
    offset = sc * 0.7 + (ant - 2) * 0.3            # receiver-dependent level
    x = offset + rng.normal(0, 0.1, n)
    cell = rng.integers(0, 50, n)                   # 50 coarse cells, 20 of them jammed (40% of the data)
    hot = cell < 20
    x[hot] += 4.0
    d = {"x": x, "lat": np.zeros(n), "lon": np.zeros(n), "sc": sc, "ant": ant}
    orig = C.land_fraction
    C.land_fraction = lambda lat, lon: np.zeros(len(lat))
    try:
        ex, lf, hot_share = C.excess(d, cell)
    finally:
        C.land_fraction = orig
    assert abs(np.median(ex[~hot])) < 0.02, np.median(ex[~hot])
    assert abs(np.median(ex[hot]) - 4.0) < 0.05, np.median(ex[hot])
    assert abs(hot_share - hot.mean()) < 1e-9


def test_land_mask_and_footprint_smoothing():
    square = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": {
        "type": "Polygon", "coordinates": [[[10, 0], [20, 0], [20, 10], [10, 10], [10, 0]],
                                           [[14, 4], [16, 4], [16, 6], [14, 6], [14, 4]]]}}]}
    m = C.land_mask(square)
    iy = lambda lat: int((90 - lat) / C.LAND_RES)
    ix = lambda lon: int((lon + 180) / C.LAND_RES)
    assert m[iy(2), ix(12)] and not m[iy(5), ix(15)] and not m[iy(2), ix(25)] and not m[iy(-5), ix(12)]
    tmp = tempfile.mkdtemp()
    saved = (C.CACHE, C.DATA, C._LAND)
    try:
        C.CACHE, C.DATA, C._LAND = tmp, tmp, None
        json.dump(square, open(os.path.join(tmp, "ne_50m_land.geojson"), "w"))
        lf = C.land_fraction(np.array([2.0, 5.0, 30.0, 5.0]), np.array([11.0, 10.0, 15.0, 30.0]))
        assert 0.3 < lf[0] < 1.0 and 0.25 < lf[1] < 0.75 and lf[2] < 0.01 and lf[3] < 0.01, lf
    finally:
        C.CACHE, C.DATA, C._LAND = saved
        shutil.rmtree(tmp, ignore_errors=True)


def test_subset_url_has_no_secret():
    os.environ["EARTHDATA_TOKEN"] = "not-a-real-token-123"
    u = C.subset_url("https://opendap.earthdata.nasa.gov/collections/C1/granules/g1", 168744, 2)
    assert u.startswith("https://opendap.earthdata.nasa.gov/collections/C1/granules/g1.dap.nc4?dap4.ce=")
    assert "/ddm_noise_floor%5B0:2:168743%5D%5B0:3%5D" in u and "/sc_lat%5B0:2:168743%5D;" in u
    assert "not-a-real-token" not in u


def test_scoring_helpers():
    assert C.auc([3.0, 4.0], [0.0, 1.0, 2.0]) == 1.0
    assert C.auc([1.0], [1.0]) == 0.5
    r = {"n": 50, "med_db": 0.2, "dropout": 0.8}
    assert C.affected(r) and C.noise_ok(r) and C.drop_ok(r)
    assert not C.affected({"n": 50, "med_db": 0.9, "dropout": None})
    assert C.affected({"n": 5, "med_db": None, "dropout": 0.5})
    pairs = [({"n": 50, "med_db": 3.0, "dropout": None, "lat": 0, "lon": 0}, 30.0, 100),
             ({"n": 50, "med_db": 0.1, "dropout": None, "lat": 0, "lon": 0}, 0.0, 100),
             ({"n": 50, "med_db": 1.2, "dropout": None, "lat": 0, "lon": 0}, 1.0, 100)]
    s = C.score_table(pairs, "med_db", C.noise_ok, (1.0,))
    assert s["jam"] == 1 and s["clean"] == 2 and s["auc"] == 1.0
    assert s["rates"]["1.0"] == {"hit": 1.0, "fa": 0.5}


def test_pass_cells():
    # two cells; cell 0 has one spacecraft in two 10-minute buckets, cell 1 has two spacecraft in one bucket
    ucell = np.array(["c0", "c1"])
    cid = np.array([0] * 6 + [0] * 5 + [1] * 5 + [1] * 5 + [1] * 2)
    sc = np.array([3] * 6 + [3] * 5 + [4] * 5 + [7] * 5 + [7] * 2)
    t = np.array([10.0] * 6 + [700.0] * 5 + [50.0] * 5 + [60.0] * 5 + [1300.0] * 2)
    ex = np.array([1, 2, 3, 4, 5, 6] + [0] * 5 + [2.0] * 5 + [-1.0] * 5 + [9, 9], dtype=float)
    rows = C.pass_cells(ucell, cid, sc, t, ex)
    got = {(r["h3"], r["sc"], r["bucket"]): r for r in rows}
    assert set(got) == {("c0", 3, 0), ("c0", 3, 1), ("c1", 4, 0), ("c1", 7, 0)}, got   # (c1, 7, 2) has 2 DDMs < 5
    assert got[("c0", 3, 0)]["med_db"] == 3.5 and got[("c0", 3, 0)]["n"] == 6 and got[("c0", 3, 0)]["t_mid"] == 10.0
    assert got[("c0", 3, 1)]["med_db"] == 0.0 and got[("c1", 7, 0)]["med_db"] == -1.0
    assert C.pass_cells(ucell, cid[:0], sc[:0], t[:0], ex[:0]) == []


def test_checks_helpers():
    # distances and clustering: two groups 1,000+ km apart, members ~100 km apart
    assert abs(K.km(0.0, 0.0, 0.0, 1.0) - 111.19) < 0.1
    lab = K.single_linkage([25.0, 25.5, 26.0, 10.0, 10.4], [50.0, 50.5, 51.0, 95.0, 95.4], 200.0)
    assert list(lab) == [0, 0, 0, 1, 1], lab
    lo, hi = K.wilson(64, 100)
    assert 0.54 < lo < 0.64 < hi < 0.73 and K.wilson(0, 0) == (None, None)
    # windows: inside own -> in; far from every nearby window -> out; within 60 min of an edge -> None
    own = [(1000, 1100)]
    near = [(1000, 1100), (2000, 2100)]
    assert K.window_class(1050, own, near) == "in"
    assert K.window_class(1500, own, near) == "out"
    assert K.window_class(1130, own, near) is None and K.window_class(2050, own, near) is None
    runs = K.split_passes(np.array([0.0, 1.0, 2.0, 1000.0, 1001.0]))
    assert [list(r) for r in runs] == [[0, 1, 2], [3, 4]]


def test_region_heldout():
    rng = np.random.default_rng(3)
    pairs = []
    # region A (Gulf-like): 12 jammed, scored high; region B (far away): 3 jammed, scored low; clean cells everywhere
    for i in range(12):
        pairs.append({"day": "d1", "lat": 26 + 0.1 * i, "lon": 52.0, "med_db": 3.0 + 0.01 * i, "share": 30.0})
    for i in range(3):
        pairs.append({"day": "d2", "lat": 20.0, "lon": 97 + 0.1 * i, "med_db": 0.2, "share": 15.0})
    for i in range(40):
        pairs.append({"day": "d1", "lat": -20 + i, "lon": -60.0, "med_db": float(rng.normal(0, 0.3)), "share": 0.0})
    pairs.append({"day": "d1", "lat": 26.5, "lon": 53.0, "med_db": 2.5, "share": 0.5})   # clean cell inside region A
    r = K.region_heldout(pairs, link_km=500.0, min_jam=2)
    assert len(r["regions"]) == 2 and r["regions"][0]["jam"] == 12 and r["regions"][1]["jam"] == 3
    a, b = r["regions"]
    assert a["own_auc"] > 0.95 and b["own_auc"] < 0.8
    # leaving A out leaves only B's weak positives (AUC drops); leaving B out leaves A's strong ones
    assert a["auc_without"] < 0.8 and b["auc_without"] > 0.95
    assert a["clean_left"] == 40 and b["clean_left"] == 41     # A's buffer also drops the clean cell inside it


def test_faa_sites_and_passes():
    tests = [{"id": "A1", "place": "Range A", "centre": [32.4, -106.4], "windows": [["2026-05-14T06:00Z", "2026-05-14T08:00Z"]]},
             {"id": "A2", "place": "Range A", "centre": [32.6, -106.3], "windows": [["2026-05-14T07:30Z", "2026-05-14T09:00Z"]]},
             {"id": "B", "place": "Range B", "centre": [21.4, -158.0], "windows": [["2026-05-14T20:00Z", "2026-05-14T21:00Z"]]},
             {"id": "N", "place": "North", "centre": [45.0, -100.0], "windows": [["2026-05-14T00:00Z", "2026-05-14T01:00Z"]]}]
    sites = K.faa_sites(tests)
    assert len(sites) == 2 and sites[0]["tests"] == ["A1", "A2"] and len(sites[0]["windows"]) == 1   # merged windows
    day0 = K._epoch_min("2026-05-14T00:00Z")
    assert sites[0]["windows"][0] == [day0 + 360, day0 + 540]
    # one spacecraft over site A at 07:00 (in window) and at 15:00 (out), 20 DDMs each; DDMs far away are ignored
    t = np.concatenate([np.full(20, 7 * 3600.0) + np.arange(20), np.full(20, 15 * 3600.0) + np.arange(20), [7 * 3600.0] * 5])
    d = {"lat": np.concatenate([np.full(40, 32.5), np.full(5, 0.0)]), "lon": np.concatenate([np.full(40, -106.4), np.full(5, 0.0)]),
         "t": t, "sc": np.full(45, 4)}
    ex = np.concatenate([np.full(20, 2.0), np.full(20, 0.1), np.full(5, 5.0)])
    ps = K.site_passes("2026-05-14", d, ex, sites)
    assert len(ps) == 2 and [p["med_db"] for p in ps] == [2.0, 0.1], ps
    sc = K.faa_score(ps, sites)
    assert sc["overall"]["in"] == 1 and sc["overall"]["out"] == 1 and sc["overall"]["auc"] == 1.0
    assert not sc["overall"]["detected"]                 # needs 10+ in-window passes


def test_random_points_seeded():
    a = K.random_points("2026-01-04", n=50, land=False)
    b = K.random_points("2026-01-04", n=50, land=False)
    assert a == b and len(a) == 50 and all(abs(la) <= K.BAND_LAT for la, _ in a)
    assert a != K.random_points("2026-01-05", n=50, land=False)


def main():
    test_gaps()
    test_group_median()
    test_excess_leaves_hot_cells_out_of_the_baseline()
    try:                                # land_mask uses matplotlib.path, which CI's requirements don't install
        import matplotlib.path  # noqa: F401
    except ImportError:
        print("skip test_land_mask_and_footprint_smoothing (matplotlib not installed)")
    else:
        test_land_mask_and_footprint_smoothing()
    test_subset_url_has_no_secret()
    test_scoring_helpers()
    test_pass_cells()
    test_checks_helpers()
    test_region_heldout()
    test_faa_sites_and_passes()
    test_random_points_seeded()
    print("test_cygnss_rfi: ok")


if __name__ == "__main__":
    main()
