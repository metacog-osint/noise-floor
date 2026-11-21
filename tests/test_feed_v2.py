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
                "ended": [{"region": "822d27fffffffff", "lat": 41.0, "lon": 29.0, "near": None, "days_in_prior30": 9,
                           "share7_pct": 0.4, "min_aircraft": 900}],
                "below": [{"region": "825367fffffffff", "lat": 27.71, "lon": 49.21, "near": "Manama", "days_in_prior30": 11,
                           "share7_pct": 2.11, "min_aircraft": 5067}]},
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
    assert len(ids) == 7, ids                      # summary, 1 new, 1 ended, 1 below, 1 rise (Caucasus below threshold), 1 event, 1 spoof
    assert len(set(ids)) == len(ids), "ids must be unique"
    problems = feed_v2.check(feed)
    assert not problems, problems
    by = {f["properties"]["id"]: f["properties"] for f in feed["features"]}
    below = by["noisefloor-below-825367fffffffff-2026-10-29"]                  # suite review Mistake 2: never "stopped"
    assert below["title"] == "GPS interference fell below jamming scale near Manama", below["title"]
    assert "2.11% of 5,067+ aircraft-cells a day" in below["summary"] and "not an end" in below["summary"], below["summary"]
    assert by["noisefloor-ended-822d27fffffffff-2026-10-29"]["title"] == "GPS interference ended"
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
        if i.startswith("noisefloor-event-"):     # an event has its own hours: stamped at its end, not date-only
            assert "data_as_of_precision" not in p and p["data_as_of"] == "2026-10-29T22:00:00Z", p["data_as_of"]
            assert p["period"] == {"start": "2026-10-29T19:00:00Z", "end": "2026-10-29T22:00:00Z"}, p["period"]
            continue
        assert p["data_as_of_precision"] == "day", i
        assert p["data_as_of"] == "2026-10-29T00:00:00Z", (i, p["data_as_of"])
    country_tags()
    event_tiers()
    event_place_unit_time()
    same_titles_and_swx_names()
    rev21_fields()
    history_across_days()
    print("test_feed_v2: all passed")


def event_tiers():
    """Majors are anomalies, notables routine, and none is cut (suite review Mistake 3: exactly six anomalies a day)."""
    evs = [{"tier": "major" if k < 2 else "notable", "peak": 30 - k, "excess": 28 - k, "h0": k, "h1": k,
            "lat": 57.0 + k * 0.1, "lon": 17.0, "near": None, "test": False} for k in range(9)]
    board = {"freshness": {"aircraft_day": "2026-11-13"}, "top_events": {"day": "2026-11-13", "events": evs}}
    feed = feed_v2.build(board, [], now=datetime(2026, 11, 14, 6, 0, tzinfo=timezone.utc))
    assert not feed_v2.check(feed)
    ev = [f["properties"] for f in feed["features"] if f["properties"]["id"].startswith("noisefloor-event-")]
    assert len(ev) == 9, len(ev)
    assert [p["tier"] for p in ev] == ["anomaly"] * 2 + ["routine"] * 7
    assert "below the major grade" in ev[5]["summary"] and "below" not in ev[0]["summary"]


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


def event_place_unit_time():
    """Suite review Mistake 5: an event is its res-2 regions (an area, not a point marked approximate), its measure is
    named a share, and it carries its own start and end hours. The 15 Nov 2026 Nicosia event, 00-03 UTC."""
    ev = {"tier": "notable", "peak": 18.1, "excess": 18.1, "h0": 0, "h1": 3, "lat": 34.34, "lon": 31.23,
          "near": "Nicosia", "near_at": [35.17, 33.37], "test": False,
          "cells": ["823f4ffffffffff", "823f5ffffffffff", "823f6ffffffffff"]}
    late = {**ev, "tier": "major", "excess": 30.0, "h0": 22, "h1": 23}
    board = {"freshness": {"aircraft_day": "2026-11-15"}, "top_events": {"day": "2026-11-15", "events": [ev, late]}}
    feed = feed_v2.build(board, [], now=datetime(2026, 11, 16, 14, 0, tzinfo=timezone.utc))
    assert not feed_v2.check(feed), feed_v2.check(feed)
    g, p = feed["features"][1]["geometry"], feed["features"][1]["properties"]
    assert g["type"] == "MultiPolygon" and len(g["coordinates"]) == 3 and p["precision_class"] == "area"
    assert "CY" in p["countries"], p["countries"]
    assert p["measure"]["name"] == "peak_severe_share_pct" and "percent" in p["measure"]["unit"]
    assert p["data_as_of"] == "2026-11-15T04:00:00Z" and "data_as_of_precision" not in p
    assert p["period"] == {"start": "2026-11-15T00:00:00Z", "end": "2026-11-15T04:00:00Z"}
    assert "Between 00:00 and 03:59 UTC on 15 Nov 2026." in p["summary"] and "3 regions" in p["summary"], p["summary"]
    q = feed["features"][2]["properties"]                    # an event in the day's last hour ends at midnight
    assert q["data_as_of"] == "2026-11-16T00:00:00Z" and q["period"]["start"] == "2026-11-15T22:00:00Z"
    assert feed["features"][0]["properties"]["data_as_of_precision"] == "day"   # the summary stays date-only



def same_titles_and_swx_names():
    """Tom's yes, 18 Nov 2026 evening CST: two items that read the same take their UTC hours; limb S4 cells take the
    board's words ("in Brazil, 350 km S of Marabá"); a ROTI station named by its country alone reads "in Gabon
    (station NKLG)"."""
    ev = {"tier": "notable", "peak": 12.0, "excess": 11.0, "h0": 6, "h1": 8, "lat": 20.3, "lon": 85.8,
          "where": "near Bhubaneswar", "test": False, "cells": []}
    other = {**ev, "h0": 14, "h1": 14}
    board = {"freshness": {"aircraft_day": "2026-11-17"}, "top_events": {"day": "2026-11-17", "events": [ev, other]},
             "swx": {"limb": {"day": "2026-11-17", "top": [
                 {"cell": "81803ffffffffff", "lat": -8.5, "lon": -49.5, "p95": 0.5, "hour": 1, "lst": 22.0, "rfi": 0,
                  "n": 40, "links": 3, "max": 0.7, "near": "Brazil", "near_at": None, "near_kind": "country",
                  "near_ref": "350 km S of Marabá", "where": "in Brazil, 350 km S of Marabá"}]},
                     "roti": {"day": "2026-11-17", "stations": [
                         {"id": "NKLG00GAB", "place": "Gabon", "lat": 0.354, "lon": 9.672, "max_p95": 1.2, "hour": 20,
                          "lst": 20.6, "hours": 24},
                         {"id": "MAL200KEN", "place": "Malindi, Kenya", "lat": -2.996, "lon": 40.194, "max_p95": 0.9,
                          "hour": 19, "lst": 21.7, "hours": 24}]}}}
    feed = feed_v2.build(board, [], now=datetime(2026, 11, 18, 14, 0, tzinfo=timezone.utc))
    assert not feed_v2.check(feed), feed_v2.check(feed)
    titles = [f["properties"]["title"] for f in feed["features"]]
    assert "Notable GPS interference event near Bhubaneswar, 06:00–08:59 UTC" in titles, titles
    assert "Notable GPS interference event near Bhubaneswar, 14:00–14:59 UTC" in titles, titles
    assert "Among the day's highest limb S4 readings from COSMIC-2, in Brazil, 350 km S of Marabá" in titles, titles
    assert "Ground ROTI in Gabon (station NKLG): the highest hour of 17 Nov 2026" in titles, titles
    assert "Ground ROTI at Malindi, Kenya: the highest hour of 17 Nov 2026" in titles, titles


def rev21_fields():
    """Contract revision 2.1 (feed-contract step 4.4): dateless subjects, event times, seas, place basis, lanes, health."""
    feed = feed_v2.build(BOARD, DAYS, now=datetime(2026, 10, 30, 6, 12, tzinfo=timezone.utc))
    assert feed["contract_rev"] == "2.1" and feed["kit"] and not feed_v2.check(feed)
    by = {f["properties"]["id"]: f["properties"] for f in feed["features"]}
    for i, p in by.items():
        assert p["subject_id"].startswith("noisefloor:") and "2026" not in p["subject_id"], (i, p["subject_id"])
        assert p["event_start"] and p["event_time_precision"] in ("hour", "day"), i
    assert by["noisefloor-summary-2026-10-29"]["subject_id"] == "noisefloor:summary:daily"
    new, below = by["noisefloor-new-821e07fffffffff-2026-10-29"], by["noisefloor-below-825367fffffffff-2026-10-29"]
    assert new["subject_id"] == "noisefloor:region:821e07fffffffff" and new["last_change"] == "new"
    assert new["last_change_at"] == "2026-10-29T00:00:00Z" and new["signal"]["expected"] == 0
    assert below["last_change"] == "lowered" and "persian-gulf" in below["sea_areas"], below["sea_areas"]
    assert below["place_basis"] == "location" and "signal" not in below
    ev = next(p for i, p in by.items() if i.startswith("noisefloor-event-"))
    assert ev["event_start"] == "2026-10-29T19:00:00Z" and ev["event_end"] == "2026-10-29T21:00:00Z"   # start of last hour
    assert ev["event_time_precision"] == "hour" and ev["signal"]["value"] == 30
    spoof = next(p for i, p in by.items() if i.startswith("noisefloor-spoof-new-"))
    assert spoof["sources"][0]["lane"] == "spoofing" and spoof["signal"]["baseline_n"] == 10
    assert "lane" not in new["sources"][0]                     # the shared source dict is not edited
    h = feed["health"]
    assert set(h) == {"adsblol-archive", "spoofing", "cosmic2-ro", "cors-igs", "milair"}
    assert h["adsblol-archive"]["state"] == "fresh" and h["adsblol-archive"]["last_ok"] == h["adsblol-archive"]["checked_at"]
    assert h["milair"]["state"] == "failing" and h["milair"]["last_ok"] is None


def history_across_days():
    """Two aircraft days: a recurring event is one subject, no new-and-ended burst; a stated change keeps its first time."""
    import tempfile
    from pathlib import Path
    import feed_history

    def board(day):
        return {"freshness": {"aircraft_day": day},
                "changes": {"day": day, "rule": "r", "new": [{"region": "821e07fffffffff", "near": "Bucharest", "days_in_last7": 3}]},
                "top_events": {"day": day, "events": [{"tier": "major", "peak": 40, "excess": 30, "h0": 1, "h1": 2,
                                                       "lat": 54.7, "lon": 20.5, "near": "Kaliningrad", "test": False}]}}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        one = feed_v2.build(board("2026-11-01"), [], now=datetime(2026, 11, 2, 6, tzinfo=timezone.utc))
        first = feed_history.apply(one, root, datetime(2026, 11, 2, 6, tzinfo=timezone.utc))
        assert {x["change"] for x in first} == {"new"}, first
        assert next(f for f in one["features"] if "event" in f["properties"]["id"])["properties"]["last_change"] == "none"
        two = feed_v2.build(board("2026-11-02"), [], now=datetime(2026, 11, 3, 6, tzinfo=timezone.utc))
        second = feed_history.apply(two, root, datetime(2026, 11, 3, 6, tzinfo=timezone.utc))
        assert not second, [(x["change"], x.get("subject_id")) for x in second]    # same subjects: no lines at all
        new = next(f for f in two["features"] if "-new-" in f["properties"]["id"])["properties"]
        assert new["last_change"] == "new" and new["last_change_at"] == "2026-11-01T00:00:00Z", new["last_change_at"]
        assert not feed_v2.check(two)
    names = ["state.json", "log-2026-11-01.jsonl", "log-2026-11-01.jsonl.gz", "log-2026-11-02.jsonl"]
    assert feed_history.wanted(names) == ["state.json", "log-2026-11-01.jsonl.gz", "log-2026-11-02.jsonl"]
    assert feed_history.asset_path("log-2026-11-01.jsonl.gz") == "log/2026/11/01.jsonl.gz"
    assert feed_history.asset_name("log/2026/11/01.jsonl.gz") == "log-2026-11-01.jsonl.gz"


if __name__ == "__main__":
    main()
