"""Offline tests for tools/event_no_heavy.py (rule N, the pre-registered no-A350/A380 grade), on made-up counts."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import event_no_heavy as N  # noqa: E402

KEY = ("r", 3)


def history(n, bad, days=5):
    return [{KEY: (n, bad)} for _ in range(days)]


def event(tier, *rh):
    return {"tier": tier, "rh": [list(x) for x in rh]}


def row(st, tier, n_tier, **kw):
    return {"set": st, "tier": tier, "N": n_tier, "box": None, **kw}


def expect_exit(fn, text):
    try:
        fn()
    except SystemExit as e:
        assert text in str(e), e
        return
    raise AssertionError("expected SystemExit")


def main():
    # share and median each rounded to 0.1, as V0 rounds them
    assert N.excess_n(KEY, 40.0, {KEY: (100, 15)}, history(100, 2)) == (13.0, True)
    # too few other aircraft today, or too few usable baseline days: keeps the V0 excess
    assert N.excess_n(KEY, 40.0, {KEY: (49, 40)}, history(100, 2)) == (40.0, False)
    assert N.excess_n(KEY, 40.0, {KEY: (100, 15)}, history(100, 2, days=4)) == (40.0, False)
    assert N.excess_n(KEY, 40.0, {KEY: (100, 15)}, history(49, 2)) == (40.0, False)
    assert N.excess_n(KEY, 40.0, {}, history(100, 2)) == (40.0, False)

    found = {("r", 3): {"share": 45.0, "baseline_median": 5.0}, ("s", 4): {"share": 30.0, "baseline_median": 2.0}}
    hist = [{("r", 3): (100, 2), ("s", 4): (100, 2)} for _ in range(5)]
    # major falls to notable when every region-hour can be judged
    g = N.grade(event("major", ("r", 3), ("s", 4)), found, {("r", 3): (100, 15), ("s", 4): (100, 4)}, hist)
    assert (g["tier_n"], g["excess_n"], g["gradable"], g["region_hours"]) == ("notable", 13.0, 2, 2), g
    # one region-hour that cannot be judged keeps its V0 excess, so the event stays major
    g = N.grade(event("major", ("r", 3), ("s", 4)), found, {("r", 3): (100, 15), ("s", 4): (10, 1)}, hist)
    assert (g["tier_n"], g["excess_n"], g["gradable"]) == ("major", 28.0, 1), g
    # never raised: a notable event with a higher excess without those types stays notable
    g = N.grade(event("notable", ("r", 3)), found, {("r", 3): (100, 60)}, hist)
    assert g["tier_n"] == "notable" and g["excess_n"] == 58.0, g
    # never removed: the lowest result is minor
    g = N.grade(event("major", ("r", 3)), found, {("r", 3): (100, 2)}, hist)
    assert g["tier_n"] == "minor" and g["excess_n"] == 0.0, g
    assert [N.tier_of(x) for x in (25, 24.9, 10, 9.9)] == ["major", "notable", "notable", "minor"]

    # plan: the first 14 published days back, within 30; held-out days are refused
    have = {f"2026-11-{d:02d}" for d in range(1, 20)} - {"2026-11-10"}
    days = N.baseline_for("2026-11-20", have.__contains__)
    assert len(days) == 14 and days[0] == "2026-11-19" and days[-1] == "2026-11-05" and "2026-11-10" not in days, days
    assert N.plan_days(["2026-11-20"], have.__contains__) == sorted(days + ["2026-11-20"])
    assert N.expand(["2026-11-20", "2026-11-20"]) == ["2026-11-20"]
    assert len(N.expand(["A", "B"])) == 42 and N.SET_D[0] == "2026-11-22" and N.SET_D[-1] == "2026-12-05"
    expect_exit(lambda: N.expand(["2026-11-22"]), "Set D")
    expect_exit(lambda: N.event_rows({"2026-11-22": {}}, {}, None), "Set D")
    # a missing table stops scoring; it is never counted as "not gradable"
    v0 = {"2026-11-20": {"day": "2026-11-20", "baseline_days": ["2026-11-19"], "found": [], "events": []}}
    expect_exit(lambda: N.event_rows(v0, {"2026-11-20": {}}, None), "2026-11-19")

    # marks
    rows = ([row("A", "major", "major", box="Caucasus")] * 9 + [row("A", "major", "notable", box="Caucasus")]
            + [row("B", "notable", "notable", corroboration=["x"])] * 8 + [row("B", "major", "major", corroboration=["x"])] * 3
            + [row("B", "major", "notable", corroboration=["x"])]
            + [row("B", "notable", "minor", corroboration=[])] + [row("B", "notable", "notable", corroboration=[])])
    m = N.marks(rows)
    assert m["values"]["P1"] == (0.9, 10) and m["values"]["P5B"] == (0.75, 4) and m["values"]["P6B"] == (0.5, 2), m
    assert m["verdict"]["P3"] == "not scored" and m["passes_A_and_B"] is True, m
    failing = N.marks(rows + [row("B", "notable", "minor", corroboration=["x"])] * 2)
    assert failing["verdict"]["P4B"] == "fail" and failing["passes_A_and_B"] is False, failing
    assert N.marks([])["passes_A_and_B"] is False         # no cases never counts as a pass

    ng = N.not_gradable([row("A", "major", "major", box="Caucasus", gradable=1, region_hours=4)])
    assert ng["set A"] == {"not_gradable": 3, "region_hours": 4, "share": 0.75} and ng["box Caucasus"]["not_gradable"] == 3
    print("test_event_no_heavy: all passed")


if __name__ == "__main__":
    main()
