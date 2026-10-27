"""Offline tests for tools/geo_region.py (Space-Track GEO region). Run as a plain script: python tests/test_geo_region.py"""
import math
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import geo_region as G  # noqa: E402


def n_for(alt_km):
    """Mean motion (rev/day) of a circular orbit at an altitude."""
    a = alt_km + G.RE
    return 86400 / (2 * math.pi) * math.sqrt(G.MU / a ** 3)


def rec(norad, epoch, alt=35786.0, e=0.0, i=0.05, typ="PAYLOAD", launch="2015-03-01", name=None, owner="US"):
    """A Space-Track GP record: every value a string, as the API returns them."""
    return {"NORAD_CAT_ID": str(norad), "EPOCH": epoch, "MEAN_MOTION": f"{n_for(alt):.8f}", "ECCENTRICITY": f"{e:.7f}",
            "INCLINATION": f"{i:.4f}", "RA_OF_ASC_NODE": "80.0", "ARG_OF_PERICENTER": "10.0", "MEAN_ANOMALY": "200.0",
            "BSTAR": "0", "MEAN_MOTION_DOT": "0", "MEAN_MOTION_DDOT": "0", "ELEMENT_SET_NO": "999", "REV_AT_EPOCH": "1000",
            "OBJECT_NAME": name or f"OBJ {norad}", "OBJECT_ID": "2015-010A", "OBJECT_TYPE": typ, "COUNTRY_CODE": owner,
            "LAUNCH_DATE": launch, "RCS_SIZE": "LARGE"}


def test_regions():
    p, a = G.altitudes(n_for(35786.0), 0.0)
    assert abs(p - 35786) < 0.5 and abs(a - 35786) < 0.5
    assert G.region_of(n_for(35786), 0.0, 0.05) == "zone"
    assert G.region_of(n_for(35786 + 150), 0.0, 14.9) == "zone"
    assert G.region_of(n_for(35786 + 320), 0.0, 3.0) == "graveyard"
    assert G.region_of(n_for(35786 - 400), 0.0, 0.1) == "below"
    assert G.region_of(n_for(35786), 0.02, 0.1) == "crossing"          # perigee ~840 km low, apogee ~840 km high
    assert G.region_of(n_for(35786), 0.0, 55.0) == "inclined"
    assert G.near_geo(1.0027, 0.001) and not G.near_geo(2.0, 0.001) and not G.near_geo(1.0, 0.5)


def test_edges_hold():
    """25 km (0.25 deg) of hysteresis at the zone's edges: an edge-rider keeps the region it had."""
    up, down = n_for(35786 + 210), n_for(35786 + 190)
    assert G.region_of(up, 0.0, 0.05) == "graveyard" and G.region_of(up, 0.0, 0.05, "zone") == "zone"
    assert G.region_of(down, 0.0, 0.05) == "zone" and G.region_of(down, 0.0, 0.05, "crossing") == "crossing"
    assert G.region_of(n_for(35786 + 240), 0.0, 0.05, "zone") == "graveyard"          # well past the edge: left
    assert G.region_of(n_for(35786), 0.0, 15.1, "zone") == "zone" and G.region_of(n_for(35786), 0.0, 15.1, "crossing") == "inclined"


def test_quiet_only_for_active():
    prev = {5: {"region": "zone", "epoch": "2026-10-20T12:00:00"}}
    static = {5: {"type": "PAYLOAD"}}
    assert [e["kind"] for e in G.events(prev, dict(prev), "2026-10-27", static)] == ["quiet"]
    assert G.events(prev, dict(prev), "2026-10-27", static, active={9}) == []          # not on the active list
    assert [e["kind"] for e in G.events(prev, dict(prev), "2026-10-27", static, active={5})] == ["quiet"]


def test_inventory_latest_before_day_end():
    rows = [G.elset_row(r) for r in (rec(1, "2026-10-25T10:00:00"), rec(1, "2026-10-26T23:00:00", alt=36200),
                                     rec(1, "2026-10-27T01:00:00"), rec(2, "2026-10-20T00:00:00", alt=1000))]
    inv = G.inventory(rows, "2026-10-26")
    assert inv == {1: {"region": "graveyard", "epoch": "2026-10-26T23:00:00"}}   # object 2 isn't near GEO


def test_daily_pulls_and_events():
    tmp = tempfile.mkdtemp()
    try:
        d1 = [rec(1001, "2026-10-26T06:00:00"), rec(1002, "2026-10-26T06:00:00"), rec(1003, "2026-10-26T06:00:00", e=0.02),
              rec(1006, "2026-10-26T06:00:00"), rec(1007, "2026-10-20T12:00:00"), rec(1008, "2026-10-26T06:00:00"),
              rec(1009, "2026-10-26T06:00:00"), rec(1010, "2026-10-01T00:00:00", typ="DEBRIS")]
        d2 = [rec(1001, "2026-10-27T06:00:00"),
              rec(1002, "2026-10-27T06:00:00", alt=36100),                       # raised 314 km: left up
              rec(1003, "2026-10-27T06:00:00"),                                  # circularised: arrived
              rec(1004, "2026-10-27T06:00:00", launch="2026-09-01", name="NEWSAT"),  # new, in the zone
              rec(1005, "2026-10-27T06:00:00", e=0.02, launch="2001-05-05"),      # first seen, old: returned
              rec(1007, "2026-10-20T12:00:00"),                                  # no new elements: quiet on the 27th
              rec(1008, "2026-10-27T06:00:00", alt=35400),                       # lowered: left down
              rec(1009, "2026-10-27T06:00:00", i=20.0),                          # tilted out of the latitude limit: left
              rec(1010, "2026-10-01T00:00:00", typ="DEBRIS")]                    # stale debris: never "quiet"
        G.pull("2026-10-26", tmp, False, d1, geo_dir=tmp)       # no snapshot: every payload counts
        assert G.load_region(tmp, "2026-10-26")["events"] == []                # a first day has no yesterday
        G.pull("2026-10-27", tmp, False, d2, geo_dir=tmp)
        doc = G.load_region(tmp, "2026-10-27")
        got = sorted((e["norad"], e["kind"]) for e in doc["events"])
        assert got == [(1002, "left up"), (1003, "arrived"), (1004, "arrived"), (1004, "new"), (1005, "returned"),
                       (1006, "gone"), (1007, "quiet"), (1008, "left down"), (1009, "left")], got
        new = [e for e in doc["events"] if e["kind"] == "new"][0]
        assert new["name"] == "NEWSAT" and new["owner"] == "US" and new["region"] == "zone"
        assert doc["counts"]["zone"] == {"PAYLOAD": 4, "DEBRIS": 1} and doc["counts"]["graveyard"] == {"PAYLOAD": 1}
        assert doc["object_cols"][:3] == ["norad", "name", "cospar"] and len(doc["objects"]) == len(doc["regions"]) == 9
        held = G.read_elements(os.path.join(tmp, "geo-elements-2026-10.parquet"))
        assert len(held) == len({(r["norad"], r["epoch"]) for r in held}) == 15   # repeated sets are kept once
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_paths_and_tags():
    assert "decay_date/null-val" in G.GP_NEAR_GEO and "MEAN_MOTION/0.9--1.1" in G.GP_NEAR_GEO
    h = G.history_path([1, 2], "2026-07-01", "2026-10-28")
    assert "class/gp_history/NORAD_CAT_ID/1,2/EPOCH/2026-07-01--2026-10-28/" in h and "/predicates/NORAD_CAT_ID,EPOCH," in h
    assert G.tags_for("geo-elements-2026-11.parquet") == ["pnt-data-2026-11", "pnt-data-2026-10"]
    assert G.tags_for("2026-11-01.geo-region.json") == ["pnt-data-2026-11", "pnt-data-2026-10"]
    assert G.tags_for("2027-01-02.geo-region.json") == ["pnt-data-2027-01", "pnt-data-2026-12"]


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"test_geo_region: ok ({len(tests)} tests)")


if __name__ == "__main__":
    main()
