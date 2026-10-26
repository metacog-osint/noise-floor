"""Offline tests for tools/geo.py (GEO board). Run as a plain script: python tests/test_geo.py"""
import json
import math
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import geo as G  # noqa: E402

T0 = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
N_GEO = G.SIDEREAL / 360.0          # rev/day with zero drift


def obj(oid, lon, owner="US", n=N_GEO, i=0.0, t=T0, name=None):
    """A circular, equatorial object whose sub-satellite longitude at epoch t is `lon`."""
    return {"id": oid, "name": name or f"SAT {oid}", "owner": owner, "epoch": t.strftime("%Y-%m-%dT%H:%M:%S.%f"),
            "n": n, "e": 0.0, "i": i, "raan": 0.0, "argp": 0.0, "M": (G.gmst_deg(t) + lon) % 360,
            "lon": lon, "drift": round(n * 360 - G.SIDEREAL, 4)}


def test_gmst_reference():
    assert abs(G.gmst_deg(datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc)) - 280.46061837) < 1e-6


def test_longitude_and_drift():
    o = obj(1, 62.0)
    assert abs(G.state(o, T0)[1] - 62.0) < 1e-6
    assert abs(G.state(o, T0 + timedelta(days=3))[1] - 62.0) < 0.01          # no drift: stays put
    d = obj(2, 10.0, n=N_GEO + 1.0 / 360)                                     # +1 deg/day eastward
    assert abs(d["drift"] - 1.0) < 1e-3 and abs(G.state(d, T0 + timedelta(days=2))[1] - 12.0) < 0.01
    r = math.dist(G.state(o, T0)[0], (0, 0, 0))
    assert abs(r - 42164) < 2                                                  # the GEO radius
    assert G.classify(o) == "station-kept" and G.classify(d) == "drifting" and G.classify(obj(3, 0, i=3.0)) == "inclined"


def test_manoeuvres():
    a = obj(1, 62.0)
    later = T0 + timedelta(days=1)
    b = dict(obj(1, 62.0, t=later))                                            # same place a day later: nothing
    assert G.manoeuvres({"objects": [a]}, {"objects": [b]}) == []
    c = obj(1, 62.5, n=N_GEO + 0.05 / 360, t=later)                            # moved and changed drift
    m = G.manoeuvres({"objects": [a]}, {"objects": [c]})
    assert len(m) == 1 and "drift" in m[0]["what"] and "longitude" in m[0]["what"]


def test_build_close_pairs():
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "site", "data"))
        step = 50.0 / 42164 * 180 / math.pi                                   # 50 km along the arc, in degrees
        objs = [obj(1, 62.0, "CIS", name="LUCH"), obj(2, 62.0 + step, "ITSO", name="INTELSAT"),
                obj(3, 19.2, "SES"), obj(4, 19.2 + step / 2, "SES"), obj(5, 100.0, "PRC")]
        json.dump({"day": "2026-10-26", "objects": objs}, open(os.path.join(tmp, "2026-10-26.geo.json"), "w"))
        out = G.build(tmp, os.path.join(tmp, "site"), T0)
        assert out["counts"]["objects"] == 5 and len(out["close_other_owner"]) == 1
        p = out["close_other_owner"][0]
        assert {p["a"][1], p["b"][1]} == {"LUCH", "INTELSAT"} and 45 <= p["km"] <= 55
        assert out["close_same_owner_count"] == 1 and out["manoeuvres"] == []
        assert os.path.exists(os.path.join(tmp, "site", "data", "geo.json"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"test_geo: ok ({len(tests)} tests)")


if __name__ == "__main__":
    main()
