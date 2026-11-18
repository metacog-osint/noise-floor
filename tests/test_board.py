"""Offline tests for tools/board.py (the home page status board). Run as a plain script: python tests/test_board.py"""
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

import h3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import board as B  # noqa: E402

COLS = ["h3", "aircraft", "bad_live", "bad_raw", "capable", "capable_bad10", "usual", "usual_n"]


def hexes_in(region, k):
    return sorted(h3.cell_to_children(region, 4))[:k]


def test_jam_regions():
    r = h3.latlng_to_cell(55.0, 20.0, 2)
    cells = [[c, 10, 3, 3, 10, 0, 0, 0] for c in hexes_in(r, 3)]          # score 100 x 2 / 10 = 20: jamming scale
    assert B.jam_regions(cells, COLS) == {r: 3}
    assert B.jam_regions(cells[:2], COLS) == {}                             # 2 hexes: below the region threshold
    weak = [[c, 10, 1, 1, 10, 0, 0, 0] for c in hexes_in(r, 5)]            # score 0
    few = [[c, 4, 4, 4, 4, 0, 0, 0] for c in hexes_in(r, 5)]               # fewer than 5 aircraft
    assert B.jam_regions(weak + few, COLS) == {}


def test_hotspots_and_summary():
    trend = {"days": [f"d{i}" for i in range(31)], "measure": "m", "regions": {
        "A": {"box": [0, 1, 0, 1], "share": [10.0] * 30 + [22.0], "aircraft_hexes": [5] * 31},
        "B": {"box": [0, 1, 0, 1], "share": [None] * 25 + [5.0] * 5 + [4.0]}}}
    h = B.hotspots(trend)
    a = h["areas"][0]
    assert a["name"] == "A" and a["median30"] == 10.0 and a["change"] == 12.0 and len(a["series"]) == 30
    assert h["areas"][1]["median30"] == 5.0 and h["areas"][1]["change"] == -1.0
    line = B.summary_line({"changes": {"regions_today": 7, "day": "2026-10-25", "new_count": 2, "ended_count": 0},
                           "hotspots": h, "loss": {"areas": [{"name": "X", "share": 61.0}]}, "built_utc": "2026-10-26T18:30Z",
                           "scintillation": {"level": "below moderate", "valid_utc": "2026-10-26 17:00Z"}})
    assert line.startswith("7 areas with GPS interference on 25 Oct 2026, 2 new this week;") and "biggest rise: A (+12 points)" in line
    assert "X: 61% of aircraft heard sent no position" in line and line.endswith("scintillation below moderate.")
    stale = B.summary_line({"built_utc": "2026-10-26T21:30Z", "scintillation": {"level": "moderate", "valid_utc": "2026-10-26 17:00Z"},
                            "loss": {"areas": [{"name": "Thin", "share": 90.0, "hexes": 10, "hexes_with_mlat": 2},
                                               {"name": "Y", "share": 40.0, "hexes": 10, "hexes_with_mlat": 9}]}})
    assert "scintillation" not in stale and "Thin" not in stale and "Y: 40%" in stale


def test_easa_parse():
    page = ('<h2 class="center">impacted FIRs in the last 7 days on 14/10/2026</h2><table><tbody>'
            '<tr class="eur-row"><td class="col-rank">1</td><td class="col-region">EUR</td><td class="col-icao">LTAA</td>'
            '<td class="col-name">ANKARA</td><td class="col-spoofing">*</td><td class="col-reported">*</td></tr>'
            '<tr><td class="col-rank">2</td><td class="col-region">EUR</td><td class="col-icao">EETT</td>'
            '<td class="col-name">TALLINN</td><td class="col-spoofing">&nbsp;</td><td class="col-reported">*</td></tr></tbody></table>')
    old = B.fetch
    B.fetch = lambda url, timeout=60: page.encode()
    try:
        e = B.easa_firs()
    finally:
        B.fetch = old
    t = e["tables"][0]
    assert t["days"] == 7 and t["date"] == "2026-10-14" and [f["name"] for f in t["firs"]] == ["Ankara", "Tallinn"]
    assert t["firs"][0]["spoofing"] and not t["firs"][1]["spoofing"] and t["firs"][1]["reported"]


def test_declared_tests_window():
    tmp = tempfile.mkdtemp()
    try:
        tests = {"tests": {"T1": {"id": "T1", "place": "Range", "windows": [["2026-10-26T18:00Z", "2026-10-26T20:00Z"]]},
                           "T2": {"id": "T2", "place": "Far", "windows": [["2026-11-20T18:00Z", "2026-11-20T20:00Z"]]},
                           "T3": {"id": "T3", "place": "Soon", "windows": [["2026-10-29T10:00Z", "2026-10-29T12:00Z"]]}}}
        json.dump(tests, open(os.path.join(tmp, "faa_gps_tests.json"), "w"))
        d = B.declared(tmp, tmp, datetime(2026, 10, 26, 19, 0, tzinfo=timezone.utc))
        f = d["faa_tests"]
        assert f["today"] == 1 and f["next7"] == 2 and [r["id"] for r in f["list"]] == ["T1", "T3"]
        assert "notices" in d and all(n.get("url") for n in d["notices"])     # site_src/official_notices.json
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_build_survives_missing_sources():
    tmp = tempfile.mkdtemp()
    old_fetch = B.fetch

    def no_net(url, timeout=60):
        raise OSError("offline")
    B.fetch = no_net
    try:
        os.makedirs(os.path.join(tmp, "site", "data", "gnss"))
        b = B.build(os.path.join(tmp, "release"), os.path.join(tmp, "site"), datetime(2026, 10, 26, tzinfo=timezone.utc))
        assert "freshness" in b and b["summary"] == ""
        assert any(p.startswith("easa:") for p in b["problems"]) and any(p.startswith("scintillation:") for p in b["problems"])
    finally:
        B.fetch = old_fetch
        shutil.rmtree(tmp, ignore_errors=True)


def test_spoofing_and_cygnss_cards():
    tmp = tempfile.mkdtemp()
    try:
        for d, act in (("2026-10-24", 5), ("2026-10-25", 9)):
            json.dump({"day": d, "version": "0.5", "active": act, "episodes": act + 3, "aircraft_with_episodes": act,
                       "victim_res2_top": [{"region": "822db7fffffffff", "lat": 32.33, "lon": 35.0, "episodes": act}],
                       "spoofed_to_top": [{"lat": 31.7, "lon": 35.97, "episodes": 4}]}, open(os.path.join(tmp, f"{d}.spoof.json"), "w"))
        json.dump({"day": "2026-10-20", "judged_cells": 900, "raised_cells": 40, "cells": [["83abc", 1.5, 40]],
                   "top": [{"lat": 26.5, "lon": 56.2, "med_db": 3.1, "n": 60}]}, open(os.path.join(tmp, "2026-10-20.cygnss.json"), "w"))
        places = B.Places(tmp)
        s = B.spoofing(tmp, places)
        assert s["day"] == "2026-10-25" and s["active"] == 9 and [x["active"] for x in s["series"]] == [5, 9]
        assert s["victims"][0]["episodes"] == 9
        c = B.cygnss(tmp, places)
        assert c["day"] == "2026-10-20" and c["raised_cells"] == 40 and c["top"][0]["med_db"] == 3.1
        assert c["judged_cells"] == 900 and "cells" not in c          # the map list stays out of board.json
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_top_events_all_majors_first():
    """Every major and notable jamming event, majors first (no cap of six), with the named place's coordinates."""
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "data", "events"))
        json.dump({"places": [["Visby", 57.64, 18.3, 3, 0]]}, open(os.path.join(tmp, "data", "places.json"), "w"))
        an = [{"m": "jam", "tier": "notable" if k % 3 else "major", "h0": k, "h1": k, "peak": 20 + k, "excess": 15 + k,
               "lat": 57.5, "lon": 17.5, "cells": ["820897fffffffff"], "hs": 0.1} for k in range(9)]   # the point's own region
        an += [{"m": "jam", "tier": "minor", "lat": 0, "lon": 0}, {"m": "acc", "tier": "major", "lat": 0, "lon": 0}]
        json.dump({"anomalies": an, "bursts": [], "tests": []}, open(os.path.join(tmp, "data", "events", "2026-11-13.json"), "w"))
        te = B.top_events(tmp, "2026-11-13", B.Places(tmp))
        assert len(te["events"]) == 9 and te["majors"] == 3, te
        assert [e["tier"] for e in te["events"]] == ["major"] * 3 + ["notable"] * 6
        assert [e["h0"] for e in te["events"][:3]] == [0, 3, 6]          # each tier keeps the analysis's order
        assert te["events"][0]["near"] == "Visby" and te["events"][0]["near_at"] == [57.64, 18.3]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_sentinel6_and_smap_cards():
    tmp = tempfile.mkdtemp()
    try:
        c1 = h3.latlng_to_cell(48.7, 37.6, 2)              # eastern Ukraine
        c2 = h3.latlng_to_cell(49.5, 38.5, 2)              # next door: too close to be a second peak
        c3 = h3.latlng_to_cell(36.3, 50.0, 2)              # northern Iran
        json.dump({"day": "2026-10-24", "raised_cells": 3, "judged_cells": 5862, "threshold": 0.2409,
                   "cells": [[c2, 0.5, 300], [c1, 0.57, 320], [c3, 0.5, 280]]}, open(os.path.join(tmp, "2026-10-24.s6.json"), "w"))
        json.dump({"day": "2026-10-23", "cells": [[c1, 0.3, 300]]}, open(os.path.join(tmp, "2026-10-23.s6.json"), "w"))
        s1 = h3.latlng_to_cell(58.49, -62.59, 4)            # Saglek
        s2 = h3.latlng_to_cell(58.6, -62.3, 4)              # 25 km away: not a second entry
        s3 = h3.latlng_to_cell(70.13, -143.64, 4)           # Barter Island
        json.dump({"day": "2026-10-29", "window": ["2026-10-23", "2026-10-29"],
                   "sources": [[s1, 0.97, 0.95, 40], [s2, 0.9, 0.9, 30], [s3, 0.83, 0.8, 50]], "busy": [["83abc", 0.7, 12]]},
                  open(os.path.join(tmp, "2026-10-29.smap.json"), "w"))
        places = B.Places(tmp)
        s = B.sentinel6(tmp, places)
        assert s["day"] == "2026-10-24" and s["raised_cells"] == 3 and len(s["peaks"]) == 2, s
        assert s["peaks"][0]["score"] == 0.57 and abs(s["peaks"][1]["lat"] - 36.3) < 2
        m = B.smap(tmp, places)
        assert m["day"] == "2026-10-29" and m["sources"] == 3 and m["busy_regions"] == 1
        assert [round(x["lat"]) for x in m["strongest"]] == [59, 70] or [round(x["lat"]) for x in m["strongest"]] == [58, 70], m
        assert "cells" not in s and isinstance(m["sources"], int)       # counts only: the map lists stay out of board.json
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


BRIEF_AREA = lambda n, t, m, c: {"name": n, "today": t, "median30": m, "change": c}  # noqa: E731
BRIEF_NEAR = lambda *xs: [{"near": x} for x in xs]  # noqa: E731
M = "The share of aircraft with severe GPS error was "


def test_brief_live_board():
    """The board of 31 Oct 2026 (aircraft day 30 Oct): both big areas well below their 30-day median."""
    area, near = BRIEF_AREA, BRIEF_NEAR
    b = {"hotspots": {"areas": [area("Kaliningrad and approaches", 26.3, 41.0, -14.7),
                                area("Southern Black Sea offshore Turkey", 21.7, 38.6, -16.9),
                                area("Gulf of Finland / Estonia–Russia border", 12.6, 15.9, -3.3), area("Caucasus", 8.8, 13.7, -4.9),
                                area("Western Black Sea coast", 6.6, 10.9, -4.3), area("Cyprus–Levant", 3.2, 2.5, 0.7),
                                area("Strait of Hormuz / Gulf of Oman", 2.9, 2.0, 0.9), area("High latitude excl. Baltic/Russia", 0.1, 0.2, -0.1)]},
         "changes": {"new": near("Peshawar", "Las Vegas", "Ryazan", "Pskov", "Sakata"), "new_count": 5,
                     "below": near("Tel Aviv", "Doha", "Lviv", "Yerevan", "Tianjin", "Kushiro"), "below_count": 6}}
    assert B.brief(b) == (M + "below its usual level over Kaliningrad and the southern Black Sea. "
                          "GPS interference started in five areas this week, among them Peshawar and Las Vegas; "
                          "it fell below jamming scale in six, including Tel Aviv."), B.brief(b)


def test_brief_watched_areas():
    """Sentence 1: today's share against the 30 days before, 5 points either way; small areas say nothing."""
    area = BRIEF_AREA
    held = [area("Kaliningrad and approaches", 37.9, 41.7, -3.8), area("Southern Black Sea offshore Turkey", 37.6, 38.9, -1.2),
            area("Caucasus", 13.4, 13.9, -0.5), area("Cyprus–Levant", 1.6, 2.8, -1.2)]
    one = lambda areas: B.brief({"hotspots": {"areas": areas}})  # noqa: E731
    assert one(held) == M + "near its usual level over Kaliningrad and the southern Black Sea."
    assert one([area("Kaliningrad and approaches", 37.9, 41.7, -3.8)]) == M + "near its usual level over Kaliningrad."
    assert one([area("Caucasus", 20.0, 13.0, 7.0), area("Cyprus–Levant", 1.6, 2.8, -1.2)]) == \
        M + "above its usual level over the Caucasus."
    assert one([area("Caucasus", 18.9, 13.9, 5.0)]) == M + "above its usual level over the Caucasus."     # 5 points exactly counts
    assert one([area("Caucasus", 18.8, 13.9, 4.9)]) == M + "near its usual level over the Caucasus."
    assert one([area("Caucasus", 8.4, 13.4, -5.0)]) == M + "below its usual level over the Caucasus."
    mixed = [area("Kaliningrad and approaches", 48.0, 41.0, 7.0), area("Caucasus", 7.0, 13.0, -6.0), area("Foo", 30.0, 30.0, 0.0)]
    assert one(mixed) == M + "above its usual level over Kaliningrad and below it over the Caucasus."    # held areas unnamed
    mixed2 = [area("Kaliningrad and approaches", 48.0, 41.0, 7.0), area("Strait of Hormuz / Gulf of Oman", 20.0, 9.0, 11.0),
              area("Caucasus", 7.0, 13.0, -6.0), area("Western Black Sea coast", 6.0, 12.0, -6.0), area("Unlisted", 5.5, 12.0, -6.5)]
    assert one(mixed2) == (M + "above its usual level over Kaliningrad and the Strait of Hormuz, "
                           "and below it over the Caucasus and the western Black Sea."), one(mixed2)
    assert one([area("Cyprus–Levant", 1.6, 2.8, -1.2), area("Strait of Hormuz / Gulf of Oman", 4.9, 2.0, 2.9)]) == ""   # below 5%
    assert one([area("Cyprus–Levant", 1.0, 6.5, -5.5)]) == M + "below its usual level over Cyprus and the Levant."     # usually 5%+
    assert one([area("Caucasus", None, 13.0, None), {"name": "Caucasus", "today": 9.0, "median30": None, "change": None}]) == ""
    assert B.brief({"hotspots": None}) == B.brief({}) == ""                  # a failed section leaves its sentence out


def test_brief_started_stopped():
    """Sentence 2: areas where GPS interference started this week (new), fell below jamming scale (below) or ended
    (below, plus enough aircraft and a background-level share: suite review Mistake 2, Tom 16 Nov 2026)."""
    near = BRIEF_NEAR
    two = lambda new, n, ended, m, below=(), k=0: B.brief({"changes": {  # noqa: E731
        "new": new, "new_count": n, "ended": ended, "ended_count": m, "below": list(below), "below_count": k}})
    assert two(near("Malmö", "Ryazan", "Las Vegas"), 5, [], 0, near("Manama", "Lviv"), 4) ==         "GPS interference started in five areas this week, among them Malmö and Ryazan; it fell below jamming scale in four, including Manama."
    assert two(near("Doha"), 1, near("Tel Aviv"), 1, near("Manama", "Sochi", "Lviv"), 3) ==         ("GPS interference started in one area this week, near Doha; it ended in one, near Tel Aviv, and fell below "
         "jamming scale in three, including Manama.")
    assert two(near("Malmö"), 1, near("Tel Aviv"), 1) ==         "GPS interference started in one area this week, near Malmö; it ended in one, near Tel Aviv."
    assert two(near("Malmö", "Ryazan"), 2, [], 0) ==         "GPS interference started in two areas this week, near Malmö and Ryazan; none fell below jamming scale."
    assert two(near("Malmö"), 2, [], 0) ==         "GPS interference started in two areas this week, among them Malmö; none fell below jamming scale."   # one of two unnamed
    assert two([{"near": None}], 1, [], 0) == "GPS interference started in one area this week; none fell below jamming scale."
    assert two([], 0, near("Tel Aviv", "Doha"), 6) ==         "GPS interference ended in six areas, including Tel Aviv; it started in none this week."
    assert two([], 0, [], 0, near("Manama"), 1) ==         "GPS interference fell below jamming scale in one area, near Manama; it started in none this week."
    assert two([], 0, [], 3, [], 2) == "GPS interference ended in three areas and fell below jamming scale in two; it started in none this week."
    assert two(near(*"ABCDEFGH"), 12, [], 0, [], 10) ==         "GPS interference started in 12 areas this week, among them A and B; it fell below jamming scale in 10."
    assert two([], 0, [], 0) == "GPS interference has not started or fallen below jamming scale in any area this week."
    assert B.brief({"changes": {}}) == "" and B.brief({"changes": None}) == ""


def test_ended_check():
    """'Ended' needs 500+ aircraft-cells (and half the usual number) on each of the last 7 days and a pooled share of
    1% or less. The Manama, Sochi and Tel Aviv regions of 9-15 Nov 2026, from the live day maps."""
    r = "825367fffffffff"
    last7 = [f"d{i}" for i in range(7)]
    before = [f"b{i}" for i in range(30)]
    def tot(ac7, bad7, usual):
        t = {d: {r: [a, b]} for d, a, b in zip(last7, ac7, bad7)}
        t.update({d: {r: [usual, 0]} for d in before})
        return t
    manama = tot([5638, 5067, 5669, 5795, 6267, 6381, 5516], [214, 120, 93, 68, 140, 90, 125], 4546)
    assert B.ended_check(r, last7, before, manama) == (False, 2.11, 5067)            # 2.1%: degraded aircraft go on
    sochi = tot([59, 26, 35, 49, 34, 33, 22], [25, 7, 5, 12, 8, 5, 11], 32)
    assert B.ended_check(r, last7, before, sochi)[0] is False                      # 22-59 aircraft-cells: too few to tell
    telaviv = tot([2346, 2072, 2333, 2462, 1961, 1617, 2356], [26, 15, 27, 37, 5, 18, 12], 2533)
    assert B.ended_check(r, last7, before, telaviv) == (True, 0.92, 1617)
    thin = tot([2346, 2072, 2333, 2462, 1961, 1000, 2356], [26, 15, 27, 37, 5, 18, 12], 2533)
    assert B.ended_check(r, last7, before, thin)[0] is False                       # one day under half its usual traffic
    assert B.ended_check(r, last7, before, {})[0:2] == (False, None)                # no aircraft at all: never "ended"


def _places(tmp, rows):
    os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
    json.dump({"places": rows}, open(os.path.join(tmp, "data", "places.json"), "w", encoding="utf-8"))
    return B.Places(tmp)


def test_area_names():
    """A region or event takes a listed place within 150 km in its own country, else the country it lies in, with no
    place coordinates (so the feed tags no borrowed city). The 15 Nov 2026 Turkish-coast majors were "near Sochi"."""
    tmp = tempfile.mkdtemp()
    try:
        p = _places(tmp, [["Sochi", 43.6, 39.73, 3, 0], ["Gjirokaster", 40.08, 20.14, 5, 0], ["Visby", 57.64, 18.3, 3, 0]])
        assert p.area(41.26, 41.05, ["822c27fffffffff"]) == ("Turkey", None)          # Sochi is 281 km away
        assert p.area(39.68, 20.68, []) == ("Greece", None)                           # Albanian town, 63 km, across a border
        assert p.area(57.5, 17.5, []) == ("Visby", [57.64, 18.3])                     # at sea, 50 km: the place
        p = _places(tmp, [["Ioannina", 39.66, 20.85, 4, 0]])
        assert p.area(39.68, 20.68, []) == ("Ioannina", [39.66, 20.85])               # same country, 15 km
        assert p.area(0.0, -30.0, []) == (None, None)                                 # mid-ocean: unnamed
        p = _places(tmp, [["Doha", 25.29, 51.53, 2, 0], ["Yalta", 44.5, 34.17, 5, 0]])
        assert p.area(23.35, 51.33, ["82534ffffffffff"]) == ("Saudi Arabia", None)    # Doha is 217 km off; the land is Saudi
        assert p.area(43.0, 34.0, []) == ("Yalta", None)                              # open sea: the old 350 km, name only
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_area_reference():
    """A country name carries "220 km S of Doha" (Tom's option B, 18 Nov 2026): the nearest listed place, preferring
    one in the named country unless a place elsewhere is closer by more than 1.5 times. A place name carries none."""
    tmp = tempfile.mkdtemp()
    try:
        p = _places(tmp, [["Doha", 25.29, 51.53, 2, 0], ["Riyadh", 24.69, 46.72, 1, 0]])
        name, at, kind, ref = p.area_kind(23.35, 51.33, ["82534ffffffffff"])
        assert (name, at, kind, ref) == ("Saudi Arabia", None, "country", "220 km S of Doha"), ref   # Riyadh 490 km
        p = _places(tmp, [["Pavlodar", 52.3, 76.95, 4, 0], ["Omsk", 54.99, 73.4, 4, 0]])
        assert p.area_kind(54.52, 77.51, ["82214ffffffffff"])[2:] == ("country", "270 km E of Omsk")  # Pavlodar (KZ) 250 km
        p = _places(tmp, [["Ioannina", 39.66, 20.85, 4, 0]])
        assert p.area_kind(39.68, 20.68, []) == ("Ioannina", [39.66, 20.85], "place", None)
        p = _places(tmp, [])
        assert p.area_kind(23.35, 51.33, ["82534ffffffffff"])[2:] == ("country", None)                # nothing in reach
        b = {"changes": {"new": [{"near": "Saudi Arabia", "near_kind": "country", "near_ref": "330 km W of Abu Dhabi"},
                                 {"near": "Russia", "near_kind": "country", "near_ref": "270 km E of Omsk"}],
                         "new_count": 3, "ended_count": 0,
                         "below": [{"near": "Saudi Arabia", "near_kind": "country", "near_ref": "210 km NW of Manama"}],
                         "below_count": 3}}
        assert B.brief(b) == ("GPS interference started in three areas this week, among them Saudi Arabia (330 km W of "
                              "Abu Dhabi) and Russia (270 km E of Omsk); it fell below jamming scale in three, including "
                              "Saudi Arabia (210 km NW of Manama)."), B.brief(b)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_changes_ties_break_on_region():
    """New regions with the same day count come out in region order, the same on every build."""
    tmp = tempfile.mkdtemp()
    try:
        places = _places(tmp, [])
        os.makedirs(os.path.join(tmp, "data", "gnss"))
        regions = sorted({h3.latlng_to_cell(la, lo, 2) for la, lo in ((25.3, 51.5), (52.3, 76.9), (39.9, 116.4), (55.0, 20.0))})
        days = [{"day": f"2026-11-{d:02d}"} for d in range(1, 16)]
        for i, d in enumerate(days):
            on = regions if i == len(days) - 1 else []
            cells = [[c, 10, 3, 3, 10, 0, 0, 0] for r in on for c in hexes_in(r, 3)]
            json.dump({"cols": COLS, "cells": cells or [[hexes_in(h3.latlng_to_cell(0.0, 0.0, 2), 1)[0], 10, 0, 0, 10, 0, 0, 0]]},
                      open(os.path.join(tmp, "data", "gnss", f"{d['day']}.json"), "w"))
        c = B.changes(tmp, days, places)
        assert [r["region"] for r in c["new"]] == regions and c["new_count"] == 4, c["new"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_brief_country_names():
    """A country name reads 'in Turkey'; a place keeps 'near Tel Aviv'."""
    s = B.brief({"changes": {"new": [], "new_count": 0,
                             "ended": [{"near": "Tel Aviv", "near_kind": "place"}], "ended_count": 1,
                             "below": [{"near": "Turkey", "near_kind": "country"}], "below_count": 1}})
    assert "ended in one area, near Tel Aviv" in s and "fell below jamming scale in one, in Turkey" in s, s


def test_brief_wording():
    """Every case names GPS and never uses the words a new reader can't place, or says interference fell."""
    area, near = BRIEF_AREA, BRIEF_NEAR
    for areas in ([area("Caucasus", 20.0, 13.0, 7.0)], [area("Caucasus", 7.0, 13.0, -6.0)], [area("Caucasus", 13.0, 13.0, 0.0)],
                  [area("Caucasus", 20.0, 13.0, 7.0), area("Kaliningrad and approaches", 30.0, 41.0, -11.0)], []):
        for n, m in ((0, 0), (1, 0), (0, 1), (3, 2)):
            s = B.brief({"hotspots": {"areas": areas},
                         "changes": {"new": near("Malmö") * n, "new_count": n, "ended": near("Tel Aviv") * m, "ended_count": m,
                                     "below": near("Manama") * m, "below_count": m}})
            assert "GPS" in s and "degraded" not in s and "areas started" not in s and "stopped" not in s, s
            assert "rose" not in s and "fell" not in s.replace("fell below jamming scale", "") and "scale this week" not in s and "ended this week" not in s, s
            assert s.count(".") == (2 if areas else 1) and s[0].isupper(), s


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"test_board: ok ({len(tests)} tests)")


if __name__ == "__main__":
    main()
