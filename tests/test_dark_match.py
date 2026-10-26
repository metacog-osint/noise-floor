"""Offline tests for tools/dark_match.py (dark ships and phantom tracks): matching, the ghost rule, the fixed-object
rule and the H1-H3 scores, on small synthetic inputs. No imagery or network. Run as a plain script."""
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import dark_match as D  # noqa: E402


def offset(lat, lon, bearing_deg, km):
    """A point km away from (lat, lon) along a bearing (flat-earth, fine for a few km)."""
    b = math.radians(bearing_deg)
    return lat + km * math.cos(b) / 111.2, lon + km * math.sin(b) / (111.2 * math.cos(math.radians(lat)))


class AllCovered:
    def covers(self, lat, lon):
        return True


def det(lat, lon, length=120):
    return {"lat": lat, "lon": lon, "length_m": length, "contrast_db": 15.0, "region": "Gulf of Finland 22.5-27E"}


def test_along_across():
    p = offset(60.0, 25.0, 0, 5.0)
    al, ac = D.along_across((60.0, 25.0), {"lat": p[0], "lon": p[1]}, 0.0)
    assert abs(al - 5.0) < 0.01 and abs(ac) < 0.01
    al, ac = D.along_across((60.0, 25.0), {"lat": p[0], "lon": p[1]}, 90.0)
    assert abs(al) < 0.01 and abs(abs(ac) - 5.0) < 0.01


def test_match_one_to_one_and_dark():
    a, b = (60.0, 25.0), (60.0, 25.2)
    near_a = offset(*a, 45, 0.3)
    dets = [det(*near_a), det(*offset(*a, 45, 0.6)), det(*offset(*b, 0, 3.0))]
    vessels = {1: {"known": True, "lat": a[0], "lon": a[1]}, 2: {"known": False, "lat": b[0], "lon": b[1]},
               3: {"known": True, "lat": 60.5, "lon": 26.0}}
    D.match(dets, vessels, [AllCovered()])
    assert dets[0]["match"]["mmsi"] == 1 and "match" not in dets[1]           # one to one: the nearer detection wins
    assert dets[1]["dark"] is True                                              # the second near vessel 1 is dark
    assert dets[2]["dark"] is True and dets[2]["near_unknown"] is False         # 3 km from the unknown vessel
    assert vessels[1]["match_m"] <= 400 and vessels[3]["scored"] and not vessels[2]["scored"]
    d4 = [det(*offset(*b, 0, 0.5))]
    D.match(d4, {2: {"known": False, "lat": b[0], "lon": b[1]}}, [AllCovered()])
    assert d4[0]["dark"] is False and d4[0]["near_unknown"] is True            # within 1 km of an unknown: not dark


def test_ghost_rule():
    src = (60.0, 25.0)
    rec = {"along_bearing": 190.0, "vessels": {},
           "detections": [dict(det(*src), match={"mmsi": 1, "m": 100}),
                          det(*offset(*src, 190, 5.0)),                         # along track, 5 km: ghost
                          det(*offset(*src, 10, 4.0)),                          # along track the other way: ghost
                          det(*offset(*src, 100, 5.0)),                         # across track: not a ghost
                          det(*offset(*src, 190, 10.0))]}                       # too far along: not a ghost
    D.ghost_flags(rec)
    assert [d["ghost"] for d in rec["detections"]] == [False, True, True, False, False]
    rec2 = {"along_bearing": 350.0, "detections": [det(*offset(*src, 350, 6.0))],
            "vessels": {"7": {"known": True, "lat": src[0], "lon": src[1], "length_m": 180}}}
    D.ghost_flags(rec2)                                                         # an AIS ship can be the source
    assert rec2["detections"][0]["ghost"] is True
    rec3 = {"along_bearing": None, "detections": [det(*offset(*src, 190, 5.0))], "vessels": {}}
    D.ghost_flags(rec3)
    assert rec3["detections"][0]["ghost"] is False                              # no bearing, no ghost call


def test_clutter_and_score():
    rock = (60.1, 24.0)
    ship_pos = (59.9, 25.5)
    passes = [{"pass": f"P{k}", "variant": "B", "detections": [det(*rock)] if k < 3 else []} for k in range(5)]
    old_cov, old_load = D.covered_by, D.load_clutter
    D.covered_by = lambda rec, lat, lon: True
    D.load_clutter = lambda variant: passes
    try:
        r = {"pass": "H1", "variant": "B", "along_bearing": 190.0,
             "detections": [det(*rock), dict(det(*ship_pos), match={"mmsi": 1, "m": 300}), det(*offset(*ship_pos, 190, 5.0)),
                            det(59.5, 23.0, length=150)],
             "vessels": {"1": {"known": True, "scored": True, "lat": ship_pos[0], "lon": ship_pos[1], "length_m": 200, "match_m": 300},
                         "2": {"known": True, "scored": True, "lat": 59.7, "lon": 26.0, "length_m": 120}}}
        for d in r["detections"][2:]:
            d["dark"] = True
        r["detections"][0]["dark"] = True
        out = D.score([r], amend3=True)
        assert r["detections"][0]["fixed_map"] is True                          # seen in 3 of 5 covering passes
        assert r["detections"][2]["ghost"] is True
        assert out["H1"]["matched"] == 1 and out["H1"]["of"] == 2               # vessel 2 is a phantom candidate
        assert out["H3"]["dark_large"] == 1 and out["H3"]["of_large"] == 3      # rock out; ghost not dark; 1 real dark
        assert out["reported"]["ghosts"] == 1 and out["reported"]["fixed_map"] == 1
        assert out["verdict"] == "too few ships"                                # fewer than 20 large ships
    finally:
        D.covered_by, D.load_clutter = old_cov, old_load


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"test_dark_match: ok ({len(tests)} tests)")


if __name__ == "__main__":
    main()
