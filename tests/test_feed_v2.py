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
    "spoofing": {"new_places": {"day": "2026-10-29", "history_days": 10, "rule": "test rule", "new": [
        {"aircraft": 6, "lat": 33.0, "lon": 36.0, "near": "Damascus", "km_from_aircraft": 300,
         "victims": [{"region": "821e07fffffffff", "near": "Bucharest"}]}]}},
}
DAYS = [{"day": f"2026-10-{d:02d}", "hexes": 20000} for d in range(1, 29)] + [{"day": "2026-10-29", "hexes": 15000}]


def main():
    feed = feed_v2.build(BOARD, DAYS, now=datetime(2026, 10, 30, 6, 12, tzinfo=timezone.utc))
    ids = [f["properties"]["id"] for f in feed["features"]]
    assert len(ids) == 6, ids                      # summary, 1 new, 1 ended, 1 rise (Caucasus below threshold), 1 event, 1 spoof
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
    # Every item covers a whole UTC day and the source gives no time: precision "day", data_as_of at midnight UTC
    # (kit 0.5.6 contract), so consumers print a date and never "5:59 PM".
    assert any(i.startswith("noisefloor-spoof-new-") for i in by), "the spoof item must be covered too"
    for i, p in by.items():
        assert p["data_as_of_precision"] == "day", i
        assert p["data_as_of"] == "2026-10-29T00:00:00Z", (i, p["data_as_of"])
    country_tags()
    print("test_feed_v2: all passed")


def country_tags():
    """Real res-2 regions and events from the live feed of 15-16 Nov 2026 (suite review Mistake 1): the cell's interior
    is sampled, not just its six corners, and the named place's country is added."""
    board = {"freshness": {"aircraft_day": "2026-11-15"}, "changes": {"day": "2026-11-15", "rule": "test rule",
             "new": [{"region": "82534ffffffffff", "near": "Doha", "near_at": [25.29, 51.53], "days_in_last7": 2}],
             "ended": [{"region": "825367fffffffff", "near": "Manama", "near_at": [26.24, 50.58], "days_in_prior30": 5},
                       {"region": "822db7fffffffff", "near": "Tel Aviv", "near_at": [32.08, 34.77], "days_in_prior30": 9},
                       {"region": "822db7fffffffff", "near": None, "near_at": None, "days_in_prior30": 9}]},
             "top_events": {"day": "2026-11-15", "events": [
                 {"tier": "notable", "peak": 18.1, "excess": 18.1, "h0": 0, "h1": 3, "lat": 34.34, "lon": 31.23,
                  "near": "Nicosia", "near_at": [35.17, 33.37], "test": False}]}}
    feed = feed_v2.build(board, [], now=datetime(2026, 11, 16, 14, 0, tzinfo=timezone.utc))
    assert not feed_v2.check(feed)
    cc = [f["properties"]["countries"] for f in feed["features"][1:]]
    assert {"QA", "AE", "SA"} <= set(cc[0]), cc[0]          # was AE, SA: Qatar's south is in the cell, Doha just outside
    assert "BH" in cc[1], cc[1]                              # was SA: Manama is outside the cell; its country is added
    assert {"IL", "PS"} <= set(cc[2]), cc[2]                 # was EG, JO, LB: Israel fills the middle of the cell
    assert {"IL", "PS"} <= set(cc[3]), cc[3]                 # the interior alone finds Israel, with no named place
    assert cc[4] == ["CY"], cc[4]                            # was none: the event point is at sea off Cyprus
    # Coastal and divided-city points the kit's thinned outlines miss fall back to the commonest country nearby.
    assert feed_v2.place_country([26.24, 50.58]) == "BH" and feed_v2.place_country([35.17, 33.37]) == "CY"
    assert feed_v2.place_country([0.0, -30.0]) is None       # open ocean: nothing


if __name__ == "__main__":
    main()
