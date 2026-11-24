"""A moving jamming event keeps one subject (tools/event_subjects.py, ideas#118). Run as a plain script."""
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import h3  # noqa: E402
import event_subjects as es  # noqa: E402
import feed_history  # noqa: E402
import feed_v2  # noqa: E402

A = h3.latlng_to_cell(44.4, 26.1, 2)                   # Bucharest's region
B, C = sorted(h3.grid_ring(A, 1))[:2]                  # two of its neighbours
FAR = h3.latlng_to_cell(25.2, 55.3, 2)                 # Dubai's region, nowhere near
NOW = datetime(2026, 11, 3, 6, tzinfo=timezone.utc)


def item(iid, centre, cells, tier="anomaly"):
    geom, _ = feed_v2.h3_area(cells)
    return {"type": "Feature", "geometry": geom,
            "properties": {"id": iid, "subject_id": es.PREFIX + centre, "tier": tier}}


def feed(*items):
    return {"type": "FeatureCollection", "features": list(items)}


def state(*items):
    return {"open": {f["properties"]["subject_id"]: {"item": f} for f in items}}


def sid(f):
    return f["properties"]["subject_id"]


def regions_round_trip():
    assert es.regions(feed_v2.h3_area([A, B, C])[0]) == {A, B, C}
    assert es.regions({"type": "Point", "coordinates": [26.1, 44.4]}) == {A}
    assert es.regions(None) == set()


def moves_one_cell():
    """Yesterday centred on A over A and B; today centred on B over B and C: the same subject."""
    today = item("e-2", B, [B, C])
    moved = es.apply(feed(today), state(item("e-1", A, [A, B])), [], NOW)
    assert sid(today) == es.PREFIX + A, sid(today)
    assert moved == {"e-2": (es.PREFIX + B, es.PREFIX + A)}


def one_roll_gap():
    """Ended in the last roll (not open now), back today over the same ground: it keeps the subject."""
    gone = item("e-1", A, [A, B])
    line = {"change": "ended", "subject_id": es.PREFIX + A, "ended_at": "2026-11-02T06:00:00Z", "item": gone}
    today = item("e-3", B, [B])
    es.apply(feed(today), {"open": {}}, [line], NOW)
    assert sid(today) == es.PREFIX + A, sid(today)
    old = dict(line, ended_at="2026-10-31T06:00:00Z")      # older than GAP_HOURS: not continued
    today = item("e-3", B, [B])
    es.apply(feed(today), {"open": {}}, [old], NOW)
    assert sid(today) == es.PREFIX + B, sid(today)


def one_subject_per_item():
    """Two of today's events overlap one earlier subject: the one sharing more regions takes it; the other keeps its
    centre key, or a free one when that is taken."""
    big, small = item("e-big", B, [A, B]), item("e-small", A, [A], tier="routine")
    es.apply(feed(small, big), state(item("e-1", A, [A, B])), [], NOW)
    assert sid(big) == es.PREFIX + A and sid(small) == es.PREFIX + A + "-2", (sid(big), sid(small))
    one, two = item("e-x", FAR, [FAR]), item("e-y", FAR, [FAR], tier="routine")     # same centre, nothing earlier
    es.apply(feed(one, two), {"open": {}}, [], NOW)
    assert {sid(one), sid(two)} == {es.PREFIX + FAR, es.PREFIX + FAR + "-2"}, (sid(one), sid(two))


def no_overlap():
    """Nothing earlier on its ground: the centre key, unless an open subject that moved away is named for that region."""
    lone = item("e-1", FAR, [FAR])
    assert es.apply(feed(lone), state(item("e-0", A, [A])), [], NOW) == {}
    assert sid(lone) == es.PREFIX + FAR
    wandered = item("e-0", C, [C])
    wandered["properties"]["subject_id"] = es.PREFIX + A          # subject named for A, now only over C
    fresh = item("e-2", A, [A])
    es.apply(feed(fresh), state(wandered), [], NOW)
    assert sid(fresh) == es.PREFIX + A + "-2", sid(fresh)


def other_keys_untouched():
    spoof = {"type": "Feature", "geometry": None, "properties": {"id": "s", "subject_id": "noisefloor:spoof-place:x"}}
    assert es.apply(feed(spoof), state(item("e-1", A, [A])), [], NOW) == {} and sid(spoof) == "noisefloor:spoof-place:x"


def history_lines_for_a_moving_event():
    """Through the build and the history run: a move logs nothing, a gap reopens the subject, nothing churns."""
    def board(day, lat, lon, cells):
        return {"freshness": {"aircraft_day": day},
                "top_events": {"day": day, "events": [{"tier": "major", "peak": 40, "excess": 30, "h0": 1, "h1": 2,
                                                       "lat": lat, "lon": lon, "cells": cells, "near": "Bucharest",
                                                       "test": False}]}}
    lat_b, lon_b = h3.cell_to_latlng(B)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        runs = [("2026-11-01", 44.4, 26.1, [A, B]), ("2026-11-02", lat_b, lon_b, [B, C])]
        logged = []
        for i, (day, lat, lon, cells) in enumerate(runs):
            now = datetime(2026, 11, 2 + i, 6, tzinfo=timezone.utc)
            built = feed_v2.build(board(day, lat, lon, cells), [], now=now)
            logged.append(feed_history.apply(built, root, now))
        ev = [x for x in logged[1] if (x.get("subject_id") or "").startswith(es.PREFIX)]
        assert not ev, [(x["change"], x.get("subject_id")) for x in ev]        # moved one cell: no new, no ended
        now = datetime(2026, 11, 4, 6, tzinfo=timezone.utc)                     # a day with no event: it ends
        quiet = feed_v2.build({"freshness": {"aircraft_day": "2026-11-03"}, "top_events": {"day": "2026-11-03", "events": []}},
                              [], now=now)
        ended = [x for x in feed_history.apply(quiet, root, now) if x["change"] == "ended"]
        assert [x["subject_id"] for x in ended] == [es.PREFIX + A], ended
        now = datetime(2026, 11, 5, 6, tzinfo=timezone.utc)                     # back the next day over C
        lat_c, lon_c = h3.cell_to_latlng(C)
        back = feed_v2.build(board("2026-11-04", lat_c, lon_c, [C]), [], now=now)
        lines = [x for x in feed_history.apply(back, root, now) if (x.get("subject_id") or "").startswith(es.PREFIX)]
        assert [(x["change"], x["subject_id"]) for x in lines] == [("new", es.PREFIX + A)], lines
        assert not feed_v2.check(back)


def failure_keeps_built_keys():
    bad = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "MultiPolygon",
           "coordinates": [[[]]]}, "properties": {"id": "e", "subject_id": es.PREFIX + A}}]}
    st = state(item("e-1", A, [A]))
    with tempfile.TemporaryDirectory() as tmp:
        assert feed_history.carry_events(bad, st, Path(tmp), NOW) == {}
    assert bad["features"][0]["properties"]["subject_id"] == es.PREFIX + A


def main():
    for t in (regions_round_trip, moves_one_cell, one_roll_gap, one_subject_per_item, no_overlap,
              other_keys_untouched, history_lines_for_a_moving_event, failure_keeps_built_keys):
        t()
        print("ok", t.__name__)


if __name__ == "__main__":
    main()
