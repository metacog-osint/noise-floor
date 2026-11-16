"""Tests for tools/spoof_site.py (the site's spoofed-to places, new places and history), the feed items and board
line built from them, and spoof_summary.share2. Run as a plain script."""
import json
import os
import shutil
import sys
import tempfile
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import h3  # noqa: E402
import spoof_site as SP  # noqa: E402
import spoof_summary as SS  # noqa: E402

HUNGARY = h3.latlng_to_cell(47.5, 19.0, 4)
LIMA = (-12.043, -77.050)
DUBAI_SEA = (25.5, 55.0)


class Places:
    def near(self, lat, lon, limit=350):
        for name, la, lo in (("Lima", -12.05, -77.05), ("Budapest", 47.5, 19.04), ("Dubai", 25.2, 55.27)):
            if SP.km(lat, lon, la, lo) <= limit:
                return name
        return None


def cluster(lat, lon, aircraft, cells=((HUNGARY, 3, 3),), day="2026-11-12"):
    return {"lat": lat, "lon": lon, "r50_km": 0.9, "r90_km": 1.5, "episodes": aircraft, "aircraft": aircraft,
            "classes": {"active": aircraft}, "kinds": {"slow": aircraft}, "first": f"{day}T04:00:00Z",
            "last": f"{day}T05:00:00Z", "alt_ft": [34000, 37000], "clean": aircraft, "mlat_confirmed": 0,
            "located": aircraft, "victim_cells": [list(c) for c in cells]}


def days(n, start="2026-11-01"):
    d0 = date.fromisoformat(start)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def tfile(day, clusters, unplaced=()):
    return {"day": day, "version": "0.6", "targets_version": "2", "clusters": list(clusters), "unplaced": list(unplaced)}


def test_new_place_needs_history_and_distance():
    ds = days(9)
    td = {d: tfile(d, [cluster(*DUBAI_SEA, 5, day=d)]) for d in ds[:-1]}
    td[ds[-1]] = tfile(ds[-1], [cluster(*DUBAI_SEA, 6), cluster(*LIMA, 8), cluster(30.0, 30.0, 2)])
    n = SP.new_targets(None, Places(), td)
    assert n["day"] == ds[-1] and n["history_days"] == 8
    assert [(x["near"], x["aircraft"]) for x in n["new"]] == [("Lima", 8)], n["new"]   # Dubai seen before; 2 aircraft too few
    assert 11000 < n["new"][0]["km_from_aircraft"] < 12000, n["new"][0]["km_from_aircraft"]
    assert n["new"][0]["victims"][0]["near"] == "Budapest"
    # too little history: no list, a note instead
    short = {d: td[d] for d in ds[-4:]}
    s = SP.new_targets(None, Places(), short)
    assert s["new"] == [] and "needed" in s["note"]
    # a point 8 km from an earlier one is not new; 15 km away is
    moved = dict(td)
    moved[ds[-1]] = tfile(ds[-1], [cluster(DUBAI_SEA[0] + 0.072, DUBAI_SEA[1], 9), cluster(DUBAI_SEA[0] + 0.135, DUBAI_SEA[1], 4)])
    m = SP.new_targets(None, Places(), moved)
    assert [x["aircraft"] for x in m["new"]] == [4], m["new"]


def test_track_and_compact():
    ds = days(3)
    td = {ds[0]: tfile(ds[0], [cluster(*LIMA, 4)]),
          ds[1]: tfile(ds[1], [cluster(LIMA[0] + 0.01, LIMA[1], 2), cluster(30.0, 30.0, 1)]),
          ds[2]: tfile(ds[2], [cluster(*LIMA, 7)], unplaced=[{"reported_gs_kt": 110, "aircraft": 12, "episodes": 12,
                                                              "victim_cells": [[HUNGARY, 12, 12]]}])}
    t = SP.track(td, Places())
    rows = {r["near"]: r for r in t["rows"]}
    assert "Lima" in rows and rows["Lima"]["days"] == 3 and rows["Lima"]["aircraft_days"] == 13
    assert rows["Lima"]["series"] == [4, 2, 7] and rows["Lima"]["latest"] == 7 and rows["Lima"]["victims"] == ["Budapest"]
    assert all(r["near"] != None or r["aircraft_days"] >= 5 for r in t["rows"])   # the 1-aircraft point is left out
    assert t["places"] == 1
    rows_c, un = SP.compact(td[ds[2]], Places())
    r = rows_c[0]
    assert r[:5] == [LIMA[0], LIMA[1], 7, 7, 7] and r[7] == "Lima" and r[9][0][0] == h3.cell_to_parent(HUNGARY, 2)
    assert un == [[110, 12, 12, [[h3.cell_to_parent(HUNGARY, 2), 12, "Budapest"]]]]
    assert "icao" not in json.dumps([rows_c, un])


def test_place_levels():
    """Each followed place against its own usual level (median of earlier days, 0 when not shown), and all places
    together; a place not used on any earlier day is "new", left to new_targets()."""
    assert SP.level(12, [5] * 8) == (5, "above")
    assert SP.level(7, [5] * 8) == (5, "near")                     # under 2x
    assert SP.level(4, [1, 1, 1, 1, 1, 1, 1, 2]) == (1, "above")    # 4x and 3 over
    assert SP.level(3, [1, 1, 1, 1, 1, 1, 1, 2]) == (1, "near")     # 3x but only 2 over
    assert SP.level(1, [6] * 8) == (6, "below")
    assert SP.level(9, [5] * 6) == (None, None)                     # fewer than 7 earlier days
    ds = days(9)
    td = {d: tfile(d, [cluster(*DUBAI_SEA, 5, day=d)] + ([cluster(*LIMA, 2, day=d)] if i in (2, 5) else []))
          for i, d in enumerate(ds[:-1])}
    td[ds[-1]] = tfile(ds[-1], [cluster(*DUBAI_SEA, 12), cluster(*LIMA, 6), cluster(30.0, 30.0, 9)])
    t = SP.track(td, Places())
    rows = {r["near"] or "other": r for r in t["rows"]}
    assert rows["Dubai"]["usual"] == 5 and rows["Dubai"]["level"] == "above"
    assert rows["Lima"]["usual"] == 0 and rows["Lima"]["level"] == "above"    # used on 2 earlier days: not new
    assert rows["other"]["level"] == "new"
    assert [r["near"] for r in t["above"]] == ["Dubai", "Lima"] and t["above_count"] == 2
    assert t["above"][0]["regions"][0][0] == h3.cell_to_parent(HUNGARY, 2)
    assert t["total"]["latest"] == 27 and t["total"]["usual"] == 5 and t["total"]["level"] == "above"
    assert t["earlier_days"] == 8 and "median" in t["level_rule"]
    # the feed item: placed where the newest day's aircraft really were, against the usual level
    import feed_v2
    lv = {"day": ds[-1], "earlier_days": 8, "rule": t["level_rule"], "total": t["total"], "above_count": 2,
          "above": [{"lat": r["lat"], "lon": r["lon"], "near": r["near"], "latest": r["latest"], "usual": r["usual"],
                     "regions": [{"region": g, "episodes": n, "near": "Budapest"} for g, n in r["regions"]]} for r in t["above"]]}
    b = {"freshness": {"aircraft_day": ds[-1]}, "spoofing": {"day": ds[-1], "active": 5, "place_levels": lv},
         "summary": "", "brief": ""}
    f = feed_v2.build(b, [])
    items = [x["properties"] for x in f["features"] if x["properties"]["id"].startswith("noisefloor-spoof-above-")]
    assert len(items) == 2 and not feed_v2.check(f), feed_v2.check(f)
    assert items[0]["tier"] == "anomaly" and "near Dubai" in items[0]["title"] and "usual 5 a day" in items[0]["summary"]
    assert items[0]["measure"] == {"name": "aircraft_shown_at_false_position", "value": 12, "expected": 5}


def test_regions_and_day_series():
    reg, groups = SP.regions()
    assert "east_med" in reg and "Middle East" in groups
    assert SP.group_of(33.9, 35.5, reg, groups) == "Middle East"
    assert SP.group_of(57.0, 24.0, reg, groups) == "Baltic and western Russia"
    assert SP.group_of(49.0, 8.0, reg, groups) is None            # a control box folds into Elsewhere
    tmp = tempfile.mkdtemp()
    try:
        cells = [[h3.latlng_to_cell(33.9, 35.5, 4), 3], [h3.latlng_to_cell(47.5, 19.0, 4), 1]]
        json.dump({"day": "2026-11-12", "version": "0.6", "active": 4, "aircraft_with_episodes": 4, "cells": cells},
                  open(os.path.join(tmp, "2026-11-12.spoof.json"), "w"))
        out, names = SP.day_series(tmp)
        assert names[-1] == "Elsewhere" and "Controls" not in names
        assert out[0]["cells"]["Middle East"] == 1 and out[0]["cells"]["Elsewhere"] == 1 and out[0]["active"] == 4
    finally:
        shutil.rmtree(tmp)


def test_main_writes_site_files():
    tmp = tempfile.mkdtemp()
    try:
        rel, site = os.path.join(tmp, "rel"), os.path.join(tmp, "site")
        os.makedirs(rel); os.makedirs(os.path.join(site, "data", "spoof"))
        json.dump({"places": [["Lima", -12.05, -77.05, 1, 1], ["Budapest", 47.5, 19.04, 1, 1]]},
                  open(os.path.join(site, "data", "places.json"), "w"))
        for i, d in enumerate(days(9)):
            cl = [cluster(*DUBAI_SEA, 5, day=d)] + ([cluster(*LIMA, 8, day=d)] if i == 8 else [])
            json.dump(tfile(d, cl), open(os.path.join(rel, f"{d}.spoof-targets.json"), "w"))
            json.dump({"day": d, "version": "0.6", "active": 5, "aircraft_with_episodes": 5,
                       "cells": [[HUNGARY, 5]], "spoofed_to_top": []}, open(os.path.join(rel, f"{d}.spoof.json"), "w"))
            json.dump({"day": d, "active": 5, "cells": [[HUNGARY, 5]]}, open(os.path.join(site, "data", "spoof", f"{d}.json"), "w"))
        argv = sys.argv
        sys.argv = ["spoof_site.py", rel, site]
        try:
            SP.main()
        finally:
            sys.argv = argv
        last = json.load(open(os.path.join(site, "data", "spoof", "2026-11-09.json"), encoding="utf-8"))
        assert len(last["targets"]) == 2 and last["active"] == 5
        h = json.load(open(os.path.join(site, "data", "spoof", "history.json"), encoding="utf-8"))
        assert len(h["days"]) == 9 and [x["near"] for x in h["new"]["new"]] == ["Lima"]

        # the board line and the feed item built from the same files
        import board
        import feed_v2
        sp = board.spoofing(rel, board.Places(site))
        assert [x["near"] for x in sp["new_places"]["new"]] == ["Lima"]
        b = {"freshness": {"aircraft_day": "2026-11-09"}, "spoofing": sp, "summary": "", "brief": ""}
        line = board.summary_line(b)
        assert "new far-off false position near Lima" in line, line
        f = feed_v2.build(b, [])
        items = [x for x in f["features"] if x["properties"]["id"].startswith("noisefloor-spoof-new-")]
        assert len(items) == 1 and not feed_v2.check(f), feed_v2.check(f)
        p = items[0]["properties"]
        assert p["kind"] == "observation" and "Lima" in p["title"] and "9 Nov 2026" in p["summary"]
        assert "not a transmitter site" in p["summary"] and p["requirement_ids"] == ["NF-EEI-3"]
        assert items[0]["geometry"]["type"] == "Polygon"             # placed where the aircraft really were
    finally:
        shutil.rmtree(tmp)


def test_region_levels_pool_and_sent():
    """Regions against their own usual level (active aircraft-hours, median of earlier share2 days, 0 when absent),
    the 7-day pool, where each region's aircraft were shown, the site day file, the Today line and the feed items."""
    gulf, balt, quiet = (h3.latlng_to_cell(*p, 2) for p in ((26.0, 52.0), (59.0, 23.0), (47.5, 19.0)))
    ds = days(10)
    sd = {d: {gulf: (2000, 10), balt: (500, 4 if i % 3 else 0), quiet: (900, 0)} for i, d in enumerate(ds[:-1])}
    sd[ds[-1]] = {gulf: (2100, 30), balt: (40, 0), quiet: (900, 0)}
    n, lv = SP.region_levels(sd, ds[-1])
    assert n == 9 and lv[gulf] == [10, "above"] and lv[balt] == [4, "below"] and quiet not in lv, lv
    assert SP.region_levels(sd, ds[5]) == (5, {})                    # fewer than 7 earlier days: no levels
    rows, use = SP.pooled(sd, ds[-1])
    assert use == ds[-7:] and dict((r, (a, k)) for r, a, k in rows)[gulf] == (6 * 2000 + 2100, 6 * 10 + 30)
    r = SP.regions_now(sd, Places())
    assert r["day"] == ds[-1] and r["above_count"] == 1 and r["above"][0]["region"] == gulf
    assert r["above"][0]["active_ah"] == 30 and r["above"][0]["usual"] == 10 and r["above"][0]["near"] is None
    assert r["total"]["latest"] == 30 and r["total"]["level"] == "above" and r["spoofed_regions"] == 1
    # where each region's aircraft were shown: per cluster, the most aircraft in any one res-4 cell of the region
    hu2 = h3.cell_to_parent(HUNGARY, 2)
    other4 = [c for c in h3.cell_to_children(hu2, 4) if c != HUNGARY][0]
    t = tfile(ds[-1], [cluster(*LIMA, 7, cells=((HUNGARY, 5, 5), (other4, 3, 3))), cluster(*DUBAI_SEA, 2)],
              unplaced=[{"reported_gs_kt": 110, "aircraft": 4, "episodes": 4, "victim_cells": [[HUNGARY, 4, 4]]}])
    to, un = SP.sent(t)
    assert to == {hu2: [[0, 5], [1, 3]]} and un == {hu2: 4}, (to, un)
    d = SP.add_regions({"day": ds[-1]}, t, sd, Places())
    assert d["sent2"] == to and d["level_days"] == 9 and d["level2"][gulf] == [10, "above"] and len(d["targets"]) == 2
    assert d["share2_7_days"] == ds[-7:] and "icao" not in json.dumps(d)
    # the Today line and the feed items from the board's spoofing section
    import board
    import feed_v2
    sp = {"day": ds[-1], "active": 9, "region_levels": dict(r, above=[dict(r["above"][0], near="Doha")])}
    line = board.spoof_line(sp)
    assert line == "Spoofing on 10 Nov 2026 was above its usual level in one region, most near Doha; all regions " \
                   "together were above their usual level.", line
    assert board.spoof_line({"day": ds[-1], "active": 9}) .startswith("9 active spoofing episodes on 10 Nov 2026")
    quiet_day = dict(r, above=[], above_count=0, total=dict(r["total"], level="near"))
    assert "was not above its usual level in any region" in board.spoof_line({"region_levels": quiet_day})
    b = {"freshness": {"aircraft_day": ds[-1]}, "spoofing": sp, "summary": "", "brief": ""}
    f = feed_v2.build(b, [])
    items = [x for x in f["features"] if x["properties"]["id"].startswith("noisefloor-spoof-region-above-")]
    assert len(items) == 1 and not feed_v2.check(f), feed_v2.check(f)
    p = items[0]["properties"]
    assert p["tier"] == "anomaly" and p["title"] == "More GPS spoofing than usual near Doha"
    assert "30 aircraft-hours" in p["summary"] and "usual 10" in p["summary"] and "1.4% of 2,100" in p["summary"]
    assert p["measure"] == {"name": "spoofed_active_aircraft_hours", "value": 30, "expected": 10}
    assert items[0]["geometry"]["type"] == "Polygon"


def test_share2():
    import pyarrow as pa
    import pyarrow.parquet as pq
    tmp = tempfile.mkdtemp()
    try:
        a, b = h3.latlng_to_cell(33.9, 35.5, 2), h3.latlng_to_cell(47.5, 19.0, 2)
        pq.write_table(pa.table({"h3": [a, a, b, b], "hour": pa.array([1, 2, 1, 2], pa.int8()),
                                 "aircraft": pa.array([40, 30, 5, 4], pa.int32()),
                                 "spoofed_active": pa.array([3, 1, 0, 0], pa.int32())}),
                       os.path.join(tmp, "2026-11-12.hex2.parquet"))
        assert SS.share2(tmp, "2026-11-12") == [[a, 70, 4]]               # b has 9 aircraft-hours, under 10
        assert SS.share2(tmp, "2026-11-13") is None
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
