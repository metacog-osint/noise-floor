"""Offline tests for tools/geo_globe.py (GEO globe data). Run as a plain script: python tests/test_geo_globe.py"""
import json
import math
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import geo_globe as G  # noqa: E402
import geo_region as R  # noqa: E402

N_GEO = 1.00273791                                     # rev/day: no drift


def elset(norad, epoch, lon, n=N_GEO, i=0.0):
    """A circular equatorial element set whose sub-satellite longitude at epoch is `lon` (SGP4 mean elements)."""
    from sgp4.api import jday
    from sgp4.propagation import gstime
    t = datetime.fromisoformat(epoch)
    jd, fr = jday(t.year, t.month, t.day, t.hour, t.minute, t.second)
    M = (math.degrees(gstime(jd + fr)) + lon) % 360
    return {"norad": norad, "epoch": epoch, "n": n, "e": 0.0001, "i": i, "raan": 0.0, "argp": 0.0, "M": M, "bstar": 0.0,
            "ndot": 0.0, "nddot": 0.0, "elset": 1, "rev": 1}


def test_encode_roundtrip():
    pts = [(179.5, 0.1, 3), (-179.8, 0.12, 4), (-178.0, -0.5, -10)]          # crosses the date line the short way
    tr = G.encode(5, pts)
    assert tr[:4] == [5, 17950, 10, 3]
    s, back = G.decode(tr)
    assert s == 5 and [(round(a, 2), round(b, 2), c) for a, b, c in back] == [(179.5, 0.1, 3), (-179.8, 0.12, 4), (-178.0, -0.5, -10)]
    assert abs(tr[4]) < 100                                                   # 0.7 deg east, not 359.3 deg west


def test_build_tracks():
    tmp = tempfile.mkdtemp()
    try:
        rel, site = os.path.join(tmp, "rel"), os.path.join(tmp, "site")
        os.makedirs(rel)
        now = datetime(2026, 10, 27, 12, 0)
        sets = [elset(1, "2026-10-20T00:00:00", 62.0),                          # station-kept at 62E all window
                elset(2, "2026-10-27T03:00:00", 10.0, n=N_GEO - 1.0 / 360)]     # appears 3 h into the last day, drifting 1 deg/day west
        R.write_elements(os.path.join(rel, "geo-elements-2026-10.parquet"), sets)
        objects = [[1, "KEPT", "2010-001A", "PAYLOAD", "US", "2010-01-01", "LARGE", "zone", "2026-10-20T00:00:00", N_GEO, 0.0001, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                   [2, "DRIFTER", "2011-001A", "PAYLOAD", "PRC", "2011-01-01", "LARGE", "graveyard", "2026-10-27T03:00:00", N_GEO - 1 / 360, 0.0001, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]
        json.dump({"day": "2026-10-27", "object_cols": R.OBJ_COLS, "objects": objects, "regions": {}},
                  open(os.path.join(rel, "2026-10-27.geo-region.json"), "w"))
        json.dump({"day": "2026-10-27", "objects": [{"id": 1}]}, open(os.path.join(rel, "2026-10-27.geo.json"), "w"))
        doc = G.build(rel, site, now)
        assert [o[8] for o in doc["objects"]] == [1, 0]                       # active flag from the CelesTrak list
        assert doc["owners"].get("PRC") and doc["owners"].get("US")          # owner names from site_src/satcat_owners.json
        t1 = json.load(open(os.path.join(site, "data", "geo", "tracks-1d.json")))
        assert t1["step_min"] == 15 and t1["samples"] == 97 and t1["start_utc"] == "2026-10-26T12:00Z"
        s, pts = G.decode(t1["tracks"]["1"])
        assert s == 0 and len(pts) == 97 and all(abs(p[0] - 62.0) < 0.3 and abs(p[1]) < 0.1 and abs(p[2]) < 30 for p in pts)
        s2, pts2 = G.decode(t1["tracks"]["2"])
        assert s2 == 60 and len(pts2) == 37                                   # 12:00 UTC on the 26th + 60 x 15 min = 03:00 on the 27th
        assert abs(pts2[0][0] - 10.0) < 0.3 and pts2[-1][0] < pts2[0][0]       # moving west
        assert doc["tracks"]["90"]["step_min"] == 720
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"test_geo_globe: ok ({len(tests)} tests)")


if __name__ == "__main__":
    main()
