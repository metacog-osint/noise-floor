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


def test_no_false_manoeuvre_inclined_eccentric():
    """An inclined, slightly eccentric orbit left alone swings in longitude through the day (a figure-of-eight plus the
    eccentric swing, about a degree here). Two snapshots of the same, unmanoeuvred elements must not flag anything."""
    q = obj(7, 75.0, i=5.0)
    q.update(e=0.01, argp=40.0, raan=80.0)
    q["lon"] = G.state(q, T0)[1]
    for hours in (6, 14.4, 30, 54):
        t1 = T0 + timedelta(hours=hours)
        o = dict(q, epoch=t1.strftime("%Y-%m-%dT%H:%M:%S.%f"), M=(q["M"] + q["n"] * 360 * hours / 24) % 360)
        o["lon"] = G.state(o, t1)[1]
        assert G.manoeuvres({"objects": [q]}, {"objects": [o]}) == [], hours
    t1 = T0 + timedelta(hours=14.4)                                            # the same object, nudged 0.3 deg east
    o = dict(q, epoch=t1.strftime("%Y-%m-%dT%H:%M:%S.%f"), M=(q["M"] + q["n"] * 360 * 0.6 + 0.3) % 360)
    o["lon"] = G.state(o, t1)[1]
    m = G.manoeuvres({"objects": [q]}, {"objects": [o]})
    assert len(m) == 1 and "longitude" in m[0]["what"]


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


def test_build_manoeuvres_from_two_snapshots():
    """With fewer than eight snapshots, each one must be compared with the one before it, not with itself."""
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "site", "data"))
        later = T0 + timedelta(days=1)
        json.dump({"day": "2026-10-26", "objects": [obj(1, 62.0), obj(2, 100.0)]}, open(os.path.join(tmp, "2026-10-26.geo.json"), "w"))
        json.dump({"day": "2026-10-27", "objects": [obj(1, 62.5, n=N_GEO + 0.05 / 360, t=later), obj(2, 100.0, t=later)]},
                  open(os.path.join(tmp, "2026-10-27.geo.json"), "w"))
        out = G.build(tmp, os.path.join(tmp, "site"), later)
        assert [m["id"] for m in out["manoeuvres"]] == [1] and out["manoeuvres"][0]["day"] == "2026-10-27"
        for k in range(3):                                                     # three more quiet days: still one
            t = later + timedelta(days=k + 1)
            json.dump({"day": t.strftime("%Y-%m-%d"), "objects": [obj(1, 62.5, n=N_GEO + 0.05 / 360, t=later), obj(2, 100.0, t=t)]},
                      open(os.path.join(tmp, t.strftime("%Y-%m-%d") + ".geo.json"), "w"))
        assert [m["id"] for m in G.build(tmp, os.path.join(tmp, "site"), t)["manoeuvres"]] == [1]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_kinds():
    """Station-kept before and after is routine; everything else is the rarer kind, listed first."""
    later = T0 + timedelta(days=1)
    kept = obj(1, 62.0)
    trim = dict(obj(1, 62.0, n=N_GEO + 0.03 / 360, t=later))                  # drift trimmed by 0.03 deg a day
    m = G.manoeuvres({"objects": [kept]}, {"objects": [trim]})
    assert [x["kind"] for x in m] == ["station-keeping"] and m[0]["changed"] == ["drift"] and m[0]["drift"][1] > 0.02
    tilt = dict(trim, i=0.05, drift=kept["drift"], n=kept["n"])              # an inclination reset only
    m = G.manoeuvres({"objects": [kept]}, {"objects": [tilt]})
    assert m[0]["kind"] == "station-keeping" and m[0]["changed"] == ["inclination"] and m[0]["inc"] == [0.0, 0.05]
    go = obj(1, 62.0, n=N_GEO + 0.4 / 360, t=later)                            # leaves its slot at 0.4 deg a day
    assert G.manoeuvres({"objects": [kept]}, {"objects": [go]})[0]["kind"] == "started drifting"
    moving = obj(2, 10.0, n=N_GEO - 4.2 / 360)
    stop = obj(2, 10.0 - 4.2, t=later)
    assert G.man_kind(moving, stop) == "stopped drifting"
    assert G.man_kind(moving, obj(2, 6.0, n=N_GEO - 3.8 / 360, t=later)) == "drift rate changed"
    assert G.man_kind(obj(3, 0.0, i=9.9), obj(3, 0.0, i=9.95, t=later), ["inclination"]) == "inclined orbit changed"
    assert G.man_kind(obj(3, 0.0, i=3.4), obj(3, 0.0, i=3.4, t=later), ["drift"]) == "station-keeping"   # east-west keeping


def test_build_counts_by_kind():
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "site", "data"))
        later = T0 + timedelta(days=1)
        json.dump({"day": "2026-10-26", "objects": [obj(1, 62.0), obj(2, 100.0)]}, open(os.path.join(tmp, "2026-10-26.geo.json"), "w"))
        json.dump({"day": "2026-10-27", "objects": [obj(1, 62.0, n=N_GEO + 0.03 / 360, t=later), obj(2, 100.0, n=N_GEO + 0.4 / 360, t=later)]},
                  open(os.path.join(tmp, "2026-10-27.geo.json"), "w"))
        out = G.build(tmp, os.path.join(tmp, "site"), later)
        assert out["manoeuvre_counts"] == {"other": 1, "station-keeping": 1}
        assert {m["id"]: m["kind"] for m in out["manoeuvres"]} == {1: "station-keeping", 2: "started drifting"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_roles_and_pair_kind():
    assert G.pair_kind("inspection", None) == "inspection-capable involved"
    assert G.pair_kind(None, "servicing") == "servicing involved"
    assert G.pair_kind(None, None).startswith("no listed role")
    roles = G.load_roles()
    assert roles and all(r.get("sources") and r["role"] in ("inspection", "servicing") for r in roles.values())
    assert roles[55841]["role"] == "inspection" and roles[46113]["role"] == "servicing"


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"test_geo: ok ({len(tests)} tests)")


if __name__ == "__main__":
    main()
