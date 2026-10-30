"""Contract v2 feed (tools/feed_v2.py) from a small board: every item passes the doctrine kit's tradecraft linter.
Run as a plain script: python tests/test_feed_v2.py"""
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import feed_v2  # noqa: E402

BOARD = {
    "built_utc": "2026-10-30T06:10Z",
    "summary": "41 areas with GPS interference on Thu 29 Oct, 2 new this week.",
    "brief": "GPS interference rose over the Gulf of Finland.",
    "freshness": {"aircraft_day": "2026-10-29"},
    "changes": {"day": "2026-10-29", "rule": "test rule",
                "new": [{"region": "821e07fffffffff", "lat": 44.4, "lon": 25.5, "near": "Bucharest", "days_in_last7": 4}],
                "ended": [{"region": "822d27fffffffff", "lat": 41.0, "lon": 29.0, "near": None, "days_in_prior30": 9}]},
    "hotspots": {"day": "2026-10-29", "areas": [
        {"name": "Gulf of Finland / Estonia–Russia border", "box": [58.5, 60.5, 24.0, 32.0], "today": 41.0, "median30": 30.0, "change": 11.0},
        {"name": "Caucasus", "box": [40.0, 43.5, 41.0, 49.0], "today": 2.0, "median30": 1.0, "change": 1.0}]},
    "top_events": {"day": "2026-10-29", "events": [
        {"tier": "major", "peak": 36, "excess": 30, "h0": 19, "h1": 21, "lat": 54.7, "lon": 20.5, "near": "Kaliningrad", "test": False}]},
}
DAYS = [{"day": f"2026-10-{d:02d}", "hexes": 20000} for d in range(1, 29)] + [{"day": "2026-10-29", "hexes": 15000}]


def main():
    feed = feed_v2.build(BOARD, DAYS, now=datetime(2026, 10, 30, 6, 12, tzinfo=timezone.utc))
    ids = [f["properties"]["id"] for f in feed["features"]]
    assert len(ids) == 5, ids                      # summary, 1 new, 1 ended, 1 rise (Caucasus below threshold), 1 event
    assert len(set(ids)) == len(ids), "ids must be unique"
    problems = feed_v2.check(feed)
    assert not problems, problems
    by = {f["properties"]["id"]: f["properties"] for f in feed["features"]}
    rise = next(p for i, p in by.items() if i.startswith("noisefloor-rise-"))
    assert {"EE", "RU"} <= set(rise["countries"]), rise["countries"]
    assert rise["tier"] == "anomaly" and rise["baseline_ref"]["type"] == "rolling"
    new = next(p for i, p in by.items() if i.startswith("noisefloor-new-"))
    assert new["indicator_id"] == "NF-IND-1" and new["indicator_state"] == "present"
    assert all(p["coverage_fraction"] == 0.75 for p in by.values()), "coverage = 15000 / median 20000"
    assert all(p["us_person_data"] == "none" and p["kind"] == "observation" for p in by.values())
    ev = next(f for f in feed["features"] if f["properties"]["id"].startswith("noisefloor-event-"))
    assert ev["geometry"]["type"] == "Point" and ev["properties"]["countries"] == ["RU"]
    print("test_feed_v2: all passed")


if __name__ == "__main__":
    main()
