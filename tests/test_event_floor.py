"""Offline tests for tools/event_floor.py (the pre-registered event-grade test). Run as a plain script."""
import os
import sys

import h3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import event_floor as E  # noqa: E402


def f(region, hour, share, med=0.0):
    la, lo = h3.cell_to_latlng(region)
    return {"region": region, "lat": la, "lon": lo, "hour": hour, "measure": "gross", "share": share,
            "baseline_median": med, "n": 100}


def main():
    a = h3.latlng_to_cell(55.0, 20.0, 2)
    b = h3.grid_ring(a, 1)[0]                       # a neighbour: same event as a
    far = h3.latlng_to_cell(13.0, 81.0, 2)          # a separate event
    found = [f(a, 3, 40.0), f(b, 4, 12.0), f(far, 17, 30.0),
             {**f(far, 9, 50.0), "measure": "capable_10m"}]           # the 10 m measure is never touched
    hh = {(a, 3): [9, 10], (b, 4): [0, 10], (far, 17): [8, 8]}       # heavy live gross-bad, live gross-bad
    distinct = {(a, 3): 2, (b, 4): 5, (far, 17): 1}

    v0 = E.events(found, hh)
    assert [e["tier"] for e in v0] == ["major", "major"], v0
    big = next(e for e in v0 if e["region_hours"] == 2)
    assert big["rh"] == sorted([[a, 3], [b, 4]]) and big["heavy_share"] == 0.45, big

    ff = E.floor(found, distinct)
    assert [(x["region"], x["hour"]) for x in ff if x["measure"] == "gross"] == [(b, 4)]
    assert any(x["measure"] == "capable_10m" for x in ff)
    fv = E.events(ff, hh)
    assert len(fv) == 1 and fv[0]["tier"] == "notable" and fv[0]["rh"] == [[b, 4]], fv   # the excess left is b's 12

    hv = E.demote(v0)
    lone = next(e for e in hv if e["rh"] == [[far, 17]])
    assert lone["tier"] == "notable" and lone["tier_before"] == "major"       # heavy share 1.0
    assert next(e for e in hv if e["region_hours"] == 2)["tier"] == "major"   # 0.45: kept

    assert E.outcome(big, fv) == "notable"                 # followed by its surviving region-hour
    assert E.outcome(next(e for e in v0 if e["rh"] == [[far, 17]]), fv) == "none"
    assert E.outcome(big, hv) == "major"

    s = E.slim(big, distinct)
    assert s["distinct_min"] == 2 and s["distinct_max"] == 5 and "rh" in s

    assert E.in_box({"lat": 59.5, "lon": 28.0}) == "Gulf of Finland / Estonia–Russia border"
    assert E.in_box({"lat": 41.26, "lon": 41.05}) == "Caucasus"
    assert E.in_box({"lat": 13.0, "lon": 81.0}) is None
    assert len(E.SET_A) == 20 and E.SET_B[0] == "2026-10-25" and E.SET_B[-1] == "2026-11-15" and E.SET_C[-1] == "2026-11-29"
    print("test_event_floor: all passed")


if __name__ == "__main__":
    main()
