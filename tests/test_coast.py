"""Offline test for tools/coast.py and the 10 m coast in tools/area_names.py (24 Nov 2026 naming fixes)."""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import area_names as A  # noqa: E402
import coast  # noqa: E402


def places():
    with open(os.path.join(ROOT, "site", "data", "places.json"), encoding="utf-8") as f:
        pl = json.load(f)["places"]
    return [p for p in pl if len(p) > 3 and isinstance(p[3], (int, float)) and p[3] <= 5]


def test_on_land():
    assert coast.on_land(14.6317, 97.9062) is True      # 0.5 km inland, Yebyu Township, Myanmar
    assert coast.on_land(25.7912, 55.0521) is False     # the Gulf, 7 km from Abu Musa
    assert coast.on_land(25.87, 55.03) is True          # Abu Musa: in both Natural Earth layers, kept once
    assert coast.on_land(51.5, -0.1) is True            # London
    assert coast.on_land(30.0, -40.0) is False          # mid-Atlantic
    assert coast.on_land(57.95, 19.23) is True          # Fårö, off Gotland


def test_names():
    import h3
    pl = places()

    def where(la, lo, point):
        return A.where(pl, la, lo, [h3.latlng_to_cell(la, lo, 2)], point=point)
    # a coastal point the kit's thinned outlines put at sea now takes its country
    assert where(14.6317, 97.9062, True).startswith("in Myanmar"), where(14.6317, 97.9062, True)
    # a spoofed-to point at sea takes its sea, not its half-land cell's country ...
    assert where(25.7912, 55.0521, True).startswith("in the Persian Gulf"), where(25.7912, 55.0521, True)
    # ... while a region (an area) keeps the cells' land rule
    assert where(25.7912, 55.0521, False).startswith("in Iran"), where(25.7912, 55.0521, False)


def test_missing_asset():
    real = coast.ASSET
    coast._edges.cache_clear(); coast.on_land.cache_clear()
    coast.ASSET = os.path.join(ROOT, "no-such-file.json.gz")
    try:
        assert coast.on_land(51.5, -0.1) is None         # names fall back to the kit's outlines alone
    finally:
        coast.ASSET = real
        coast._edges.cache_clear(); coast.on_land.cache_clear()


def test_fingerprint_covers_coast():
    src = open(os.path.join(ROOT, "tools", "area_names.py"), encoding="utf-8").read()
    assert "land10m.json.gz" in src and '"coast.py"' in src


if __name__ == "__main__":
    test_on_land()
    test_names()
    test_missing_asset()
    test_fingerprint_covers_coast()
    print("ok")
