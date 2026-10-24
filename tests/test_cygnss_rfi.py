"""Offline tests for tools/cygnss_rfi.py (CYGNSS noise-floor interference lane). No network, no data/ files."""
import json, os, shutil, sys, tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cygnss_rfi as C  # noqa: E402


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
    print("test_cygnss_rfi: ok")


if __name__ == "__main__":
    main()
