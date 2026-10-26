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
                           "hotspots": h, "loss": {"areas": [{"name": "X", "share": 61.0}]},
                           "scintillation": {"level": "below moderate"}})
    assert line.startswith("7 regions at jamming scale on 2026-10-25, 2 new this week;") and "biggest rise: A (+12 points)" in line
    assert "X: 61% of aircraft heard sent no position" in line and line.endswith("scintillation below moderate.")


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


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"test_board: ok ({len(tests)} tests)")


if __name__ == "__main__":
    main()
