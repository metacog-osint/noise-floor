"""Synthetic checks for tools/geo_callouts.py (frozen rules v1). Plain script: python tests/test_geo_callouts.py"""
import math
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import geo_callouts as C  # noqa: E402

D0 = datetime(2026, 8, 1, tzinfo=timezone.utc)


def gmst_deg(t):
    return math.degrees(float(C.gmst_rad(t.timestamp())))


def el(norad, t, lon, drift=0.0, inc=0.01):
    """An element set placing a near-circular, near-equatorial object over `lon` at epoch t, drifting `drift` deg/day."""
    return {"norad": norad, "epoch": t.strftime("%Y-%m-%dT%H:%M:%S.000000"), "n": (C.SIDEREAL + drift) / 360.0, "e": 0.0001,
            "i": inc, "raan": 0.0, "argp": 0.0, "M": (lon + gmst_deg(t)) % 360.0, "bstar": 0.0, "ndot": 0.0, "nddot": 0.0}


def daily(norad, lons, drifts=None):
    return [el(norad, D0 + timedelta(days=k), lon, (drifts or [0.0] * len(lons))[k]) for k, lon in enumerate(lons)]


def run(rows, owners, roles=None, days=8):
    by = {}
    for r in rows:
        by.setdefault(r["norad"], []).append(dict(r))
    static = {k: {"name": f"OBJ{k}", "owner": owners[k], "type": "PAYLOAD"} for k in owners}
    end = (D0 + timedelta(days=days - 1)).strftime("%Y-%m-%d")
    return C.run(C.finish(by), static, roles or {}, D0.strftime("%Y-%m-%d"), end)["callouts"]


def rules(cs, rule):
    return [c for c in cs if c["rule"] == rule]


def test_position_lands_on_the_longitude():
    r = C.finish({1: [el(1, D0, 62.0)]})[1]
    p, _ = C.positions(r, [D0.timestamp()])
    assert abs(float(C.lon_deg(p[0], D0.timestamp())) - 62.0) < 0.05
    assert abs(float(math.hypot(*p[0])) - 42164) < 30


def test_c1_fires_once_when_a_pair_comes_close_and_not_for_one_owner():
    a = daily(1, [10.0] * 8)
    b = daily(2, [13.0, 13.0, 13.0, 10.05, 10.05, 10.05, 10.05, 10.05])
    cs = run(a + b, {1: "X", 2: "Y"})
    c1 = rules(cs, "C1")
    assert len(c1) == 1 and c1[0]["day"] == "2026-08-04" and not c1[0]["standing"] and c1[0]["min_km"] < 60, c1
    assert not rules(run(a + b, {1: "X", 2: "X"}), "C1")


def test_c1_standing_pair_is_marked():
    cs = run(daily(1, [10.0] * 8) + daily(2, [10.05] * 8), {1: "X", 2: "Y"})
    c1 = rules(cs, "C1")
    assert len(c1) == 1 and c1[0]["standing"], c1


def test_c2_three_daily_falls_ending_under_200_km():
    a = daily(1, [10.0] * 8)
    b = daily(2, [11.6, 11.6, 11.6, 11.2, 10.8, 10.2, 10.2, 10.2])
    c2 = rules(run(a + b, {1: "X", 2: "Y"}), "C2")
    assert len(c2) == 1 and c2[0]["day"] == "2026-08-06" and c2[0]["km"] < 200, c2


def test_c3_parked_beside_another_owner_after_drifting():
    a = daily(1, [10.0] * 8)
    b = daily(2, [12.0, 11.5, 11.0, 10.5, 10.2, 10.2, 10.2, 10.2], [-0.5, -0.5, -0.5, -0.3, 0, 0, 0, 0])
    c3 = rules(run(a + b, {1: "X", 2: "Y"}), "C3")
    assert len(c3) == 1 and c3[0]["a"][0] == 2 and c3[0]["day"] == "2026-08-06", c3


def test_c3_ignores_a_libration_end_and_inclined_neighbours():
    a = daily(1, [10.0] * 12)
    slow = [-0.13 + 0.01 * k for k in range(12)]                              # eases 0.01 deg/day each day: no burn
    lons, x = [], 10.9
    for d in slow:
        lons.append(x); x += d
    assert not rules(run(a + daily(2, lons, slow), {1: "X", 2: "Y"}, days=12), "C3")
    tilted = [el(1, D0 + timedelta(days=k), 10.0, 0.0, inc=5.0) for k in range(8)]
    parked = daily(2, [12.0, 11.5, 11.0, 10.5, 10.2, 10.2, 10.2, 10.2], [-0.5, -0.5, -0.5, -0.3, 0, 0, 0, 0])
    assert not rules(run(tilted + parked, {1: "X", 2: "Y"}), "C3")             # 5 deg inclined: not station-kept


def test_c4_slowing_toward_an_occupied_slot():
    a = daily(1, [10.0] * 8)
    far = daily(2, [27.0, 26.0, 25.0, 24.0, 23.0, 22.7, 22.4, 22.1], [-1.0, -1.0, -1.0, -1.0, -0.3, -0.3, -0.3, -0.3])
    assert not rules(run(a + far, {1: "X", 2: "Y"}), "C4")                  # 13 deg out at 0.3/day: beyond 14 days
    b = daily(2, [17.0, 16.0, 15.0, 14.0, 13.0, 12.7, 12.4, 12.1], [-1.0, -1.0, -1.0, -1.0, -0.3, -0.3, -0.3, -0.3])  # 3 deg out at 0.3/day: 8 days
    c4 = rules(run(a + b, {1: "X", 2: "Y"}), "C4")
    assert len(c4) == 1 and c4[0]["a"][0] == 2 and c4[0]["b"][0] == 1 and c4[0]["day"] == "2026-08-05", c4


def test_c5_listed_role_orbit_change_only():
    a = daily(1, [10.0] * 4 + [10.4] * 4, [0.0] * 4 + [0.05] * 4)
    b = daily(2, [30.0] * 4 + [30.4] * 4, [0.0] * 4 + [0.05] * 4)
    c5 = rules(run(a + b, {1: "X", 2: "Y"}, roles={1: "inspection"}), "C5")
    assert [c["a"][0] for c in c5] == [1] and c5[0]["day"] == "2026-08-05", c5


def test_case_matching():
    ep = {"rule": "C1", "day": "2026-09-02", "end": "2026-09-10", "a": [1, "A", "X"], "b": [2, "B", "Y"]}
    assert C.matches(ep, {"rule": "C1", "ids": [2, 1], "window": ["2026-09-05", "2026-09-07"]})      # an episode overlapping the window
    assert not C.matches(ep, {"rule": "C1", "ids": [1, 3], "window": ["2026-09-05", "2026-09-07"]})
    assert C.matches(ep, {"rule": "C1", "ids": [2], "window": ["2026-09-01", "2026-09-03"]})          # one object: any partner
    c3 = {"rule": "C3", "day": "2026-09-30", "a": [5, "S", "CIS"], "b": [6, "N", "CIS"]}
    assert not C.matches(c3, {"rule": "C3", "ids": [5], "window": ["2026-09-27", "2026-10-04"], "not_neighbour": [6]})
    assert C.matches(c3, {"rule": "C3", "ids": [5], "window": ["2026-09-27", "2026-10-04"]})


def test_old_elements_are_not_used():
    r = C.finish({1: [el(1, D0, 10.0)]})[1]
    assert C.element_at(r, D0.timestamp() + 9 * 86400) is not None
    assert C.element_at(r, D0.timestamp() + 11 * 86400) is None
    assert C.element_at(r, D0.timestamp() - 60) is None


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print("ok  ", name)
            except AssertionError as e:
                fails += 1
                print("FAIL", name, e)
    sys.exit(1 if fails else 0)
