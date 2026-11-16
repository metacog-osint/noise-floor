"""Space weather files on the site and in the feed (tools/swx_site.py, site_layers.py, board.py, feed_v2.py).
Run as a plain script: python tests/test_swx_site.py"""
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "doctrine", "kit", "python"))
import feed_v2  # noqa: E402
import swx_site  # noqa: E402
from tic_doctrine import lint  # noqa: E402

DAY = "2026-11-15"
LIMB = {
    "feed": "cosmic2-limb-s4", "version": "1.0", "day": DAY, "as_of": "2026-11-16T04:50:51Z",
    "measure": swx_site.LIMB_LABEL, "licence": "CC BY 4.0", "credit": ["COSMIC-2 data: UCAR"],
    "columns": ["cell", "lat", "lon", "n", "links", "p95", "max", "lst", "rfi"],
    "satellites": ["C2E2", "C2E5", "C2E6"], "counts": {"cell_hours": 5, "with_p95": 4}, "problems": [],
    "hours": [
        {"hour": f"{DAY}T00:00Z", "cells": [["81553ffffffffff", 24.17, -11.5, 12, 1, 0.40, 0.5, 0.1, 0.0],
                                             ["8120bffffffffff", 37.84, 71.0, 9, 1, None, 0.9, 5.7, 1.0]]},
        {"hour": f"{DAY}T20:00Z", "cells": [["81553ffffffffff", 24.17, -11.5, 12, 1, 1.87, 2.6, 20.1, 0.17],
                                             # 1 cell away from the first: too close to be another top cell
                                             ["81557ffffffffff", 19.12, -5.81, 14, 1, 1.50, 1.6, 20.0, 0.0],
                                             ["818bbffffffffff", -12.09, -56.4, 23, 1, 1.09, 1.1, 23.2, 0.04],
                                             # most values RFI-flagged: on the map, never a top cell
                                             ["81a5bffffffffff", -16.76, -34.99, 22, 1, 1.86, 1.9, 20.5, 0.73]]}],
}
ROTI = {
    "feed": "ground-roti", "version": "1.0", "day": DAY, "as_of": "2026-11-16T10:21:32Z", "measure": swx_site.ROTI_LABEL,
    "units": "TECU/min", "licence": "CC BY 4.0",
    "columns": ["station", "lat", "lon", "n", "sats", "p95", "max", "max_lat", "max_lon", "lst", "breaks"],
    "stations": [{"id": "UNSA00ARG", "place": "Argentina"}, {"id": "DGAR00GBR", "place": "Diego Garcia"}],
    "missing": ["SHLG00IND"], "problems": [],
    "hours": [{"hour": f"{DAY}T01:00Z", "stations": [["UNSA00ARG", -24.73, -65.41, 90, 9, 6.715, 8.0, -25, -66, 21.1, 3],
                                                     ["DGAR00GBR", -7.27, 72.37, 120, 12, 0.08, 0.1, -8, 70, 5.8, 0]]},
              {"hour": f"{DAY}T16:00Z", "stations": [["UNSA00ARG", -24.73, -65.41, 90, 9, 0.05, 0.1, -25, -66, 12.1, 0],
                                                     ["DGAR00GBR", -7.27, 72.37, 120, 12, 3.864, 4.0, -8, 70, 21.3, 2]]}],
}


def test_maps():
    m = swx_site.limb_map(LIMB)
    assert m["measure"] == swx_site.LIMB_LABEL
    assert m["file"].endswith(f"/swx-data-2026-11/{DAY}.cosmic2-limb-s4.json")
    by = {c[0]: c for c in m["cells"]}
    assert "8120bffffffffff" not in by                         # no hour with 10 or more values: no p95, not drawn
    assert by["81553ffffffffff"][1:5] == [1.87, 20, 20.1, 0.17]  # the cell's highest hour, not the first
    assert by["81553ffffffffff"][8] == 2                        # two hours with a p95
    r = swx_site.roti_map(ROTI)
    st = {s["id"]: s for s in r["stations"]}
    assert st["DGAR00GBR"]["max_p95"] == 3.864 and st["DGAR00GBR"]["hour"] == 16 and st["DGAR00GBR"]["lst"] == 21.3
    assert st["UNSA00ARG"]["p95"][1] == 6.715 and st["UNSA00ARG"]["p95"][0] is None and st["UNSA00ARG"]["hours"] == 2
    assert "not an S4 value" in r["note"] and r["missing"] == ["SHLG00IND"]


def test_site_layers_and_card():
    with tempfile.TemporaryDirectory() as rel, tempfile.TemporaryDirectory() as site:
        for kind, d in (("cosmic2-limb-s4", LIMB), ("ground-roti", ROTI)):
            with open(os.path.join(rel, f"{DAY}.{kind}.json"), "w", encoding="utf-8") as f:
                json.dump(d, f)
        out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "site_layers.py"), rel, site],
                             capture_output=True, text=True, check=True).stdout
        assert "cosmic2-limb-s4: 1 days" in out and "ground-roti: 1 days" in out, out
        idx = json.load(open(os.path.join(site, "data", "limbs4", "index.json")))
        assert idx["days"] == [DAY]
        ls = json.load(open(os.path.join(site, "data", "limbs4", f"{DAY}.json")))
        assert ls["cells"] and "hours" not in ls                 # slimmed for the map
        assert os.path.exists(os.path.join(site, "data", "roti", f"{DAY}.json"))
        card = swx_site.card(rel)
    top = [t["cell"] for t in card["limb"]["top"]]
    assert top == ["81553ffffffffff", "818bbffffffffff"], top  # RFI-flagged and too-close cells left out
    assert card["roti"]["stations"][0]["id"] == "UNSA00ARG"
    return card


def test_feed(card):
    board = {"freshness": {"aircraft_day": DAY}, "swx": card}
    feed = feed_v2.build(board, [], now=datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc))
    assert not feed_v2.check(feed), feed_v2.check(feed)
    items = [f for f in feed["features"] if "-limb-s4-" in f["properties"]["id"] or "-roti-" in f["properties"]["id"]]
    assert len(items) == 4, [f["properties"]["id"] for f in items]   # 2 limb cells, 2 stations
    for f in items:
        p = f["properties"]
        assert p["kind"] == "observation" and p["tier"] == "routine", p["id"]   # no baseline: nothing above routine
        assert "baseline_ref" not in p and "data_as_of_precision" not in p
        assert p["sources"][0]["id"] in ("cosmic2-ro", "cors-igs")
        if "-limb-s4-" in p["id"]:
            assert f["geometry"]["type"] == "Polygon" and p["precision_class"] == "area"
            assert swx_site.LIMB_LABEL in p["summary"] and "never compared with the alert levels" in p["summary"]
        else:
            assert f["geometry"]["type"] == "Point" and p["precision_class"] == "point"
            assert swx_site.ROTI_LABEL in p["summary"] and "not an S4 value" in p["summary"]
    roti = {f["properties"]["id"]: f["properties"] for f in items if "-roti-" in f["properties"]["id"]}
    dg = roti[f"noisefloor-roti-{DAY}-dgar00gbr"]
    assert dg["period"] == {"start": f"{DAY}T16:00:00Z", "end": f"{DAY}T17:00:00Z"} and dg["data_as_of"] == f"{DAY}T17:00:00Z"
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "feed.geojson")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(feed, f)
        rep = lint.lint_files([path], os.path.join(ROOT, "doctrine"))
        assert lint.print_report(rep), "the kit's tradecraft linter must pass"


def main():
    test_maps()
    card = test_site_layers_and_card()
    test_feed(card)
    print("test_swx_site: ok")


if __name__ == "__main__":
    main()
