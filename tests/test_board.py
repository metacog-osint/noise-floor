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
                     "ended": near("Tel Aviv", "Doha", "Lviv", "Yerevan", "Tianjin", "Kushiro"), "ended_count": 6}}
    assert B.brief(b) == (M + "below its usual level over Kaliningrad and the southern Black Sea. "
                          "GPS interference started in five areas this week, among them Peshawar and Las Vegas; "
                          "it has stopped in six, including Tel Aviv."), B.brief(b)


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
    """Sentence 2: areas where GPS interference started this week (new) or has stopped (ended)."""
    near = BRIEF_NEAR
    two = lambda new, n, ended, m: B.brief({"changes": {"new": new, "new_count": n, "ended": ended, "ended_count": m}})  # noqa: E731
    assert two(near("Malmö", "Ryazan", "Las Vegas"), 5, near("Tel Aviv", "Yerevan"), 4) == \
        "GPS interference started in five areas this week, among them Malmö and Ryazan; it has stopped in four, including Tel Aviv."
    assert two(near("Malmö"), 1, near("Tel Aviv"), 1) == \
        "GPS interference started in one area this week, near Malmö; it has stopped in one, near Tel Aviv."
    assert two(near("Malmö", "Ryazan"), 2, [], 0) == \
        "GPS interference started in two areas this week, near Malmö and Ryazan; it has stopped in none."
    assert two(near("Malmö"), 2, [], 0) == \
        "GPS interference started in two areas this week, among them Malmö; it has stopped in none."   # one of two unnamed
    assert two([{"near": None}], 1, [], 0) == "GPS interference started in one area this week; it has stopped in none."
    assert two([], 0, near("Tel Aviv", "Doha"), 6) == \
        "GPS interference has stopped in six areas, including Tel Aviv; it started in none this week."
    assert two([], 0, near("Tel Aviv"), 1) == "GPS interference has stopped in one area, near Tel Aviv; it started in none this week."
    assert two([], 0, [], 3) == "GPS interference has stopped in three areas; it started in none this week."
    assert two(near(*"ABCDEFGH"), 12, [], 10) == \
        "GPS interference started in 12 areas this week, among them A and B; it has stopped in 10."
    assert two([], 0, [], 0) == "GPS interference has not started or stopped in any area this week."
    assert B.brief({"changes": {}}) == "" and B.brief({"changes": None}) == ""


def test_brief_wording():
    """Every case names GPS and never uses the words a new reader can't place, or says interference fell."""
    area, near = BRIEF_AREA, BRIEF_NEAR
    for areas in ([area("Caucasus", 20.0, 13.0, 7.0)], [area("Caucasus", 7.0, 13.0, -6.0)], [area("Caucasus", 13.0, 13.0, 0.0)],
                  [area("Caucasus", 20.0, 13.0, 7.0), area("Kaliningrad and approaches", 30.0, 41.0, -11.0)], []):
        for n, m in ((0, 0), (1, 0), (0, 1), (3, 2)):
            s = B.brief({"hotspots": {"areas": areas},
                         "changes": {"new": near("Malmö") * n, "new_count": n, "ended": near("Tel Aviv") * m, "ended_count": m}})
            assert "GPS" in s and "degraded" not in s and "areas started" not in s and " stopped," not in s, s
            assert "rose" not in s and "fell" not in s and "interference fell" not in s and "stopped this week" not in s, s
            assert s.count(".") == (2 if areas else 1) and s[0].isupper(), s


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"test_board: ok ({len(tests)} tests)")


if __name__ == "__main__":
    main()
