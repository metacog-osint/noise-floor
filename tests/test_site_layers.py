"""Tests for the map layers: tools/spoof_summary.py (spoofing day -> public summary with map cells) and
tools/site_layers.py (release files -> site/data/spoof, site/data/cygnss and site/data/nisar). Run as a plain script."""
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import spoof_summary  # noqa: E402


def test_spoof_summary_cells():
    import h3
    tmp = tempfile.mkdtemp()
    try:
        a, b = h3.latlng_to_cell(55.0, 21.0, 4), h3.latlng_to_cell(56.0, 24.0, 4)
        ev = [{"icao": "x1", "class": "active", "victim_cells": [a, a, b]},       # a repeated within one episode counts once
              {"icao": "x2", "class": "active", "victim_cells": [a]},
              {"icao": "x3", "class": "suspect", "victim_cells": [b]}]
        with gzip.open(os.path.join(tmp, "2026-10-27.events.json.gz"), "wt", encoding="utf-8") as f:
            json.dump({"events": ev}, f)
        with open(os.path.join(tmp, "2026-10-27.summary.json"), "w", encoding="utf-8") as f:
            json.dump({"version": "0.5", "episodes": 3, "episodes_by_class": {"active": 2, "suspect": 1},
                       "spoofed_to_res6_top": [["c", 54.8, 20.7, 2]]}, f)
        d = spoof_summary.summarise(tmp, "2026-10-27")
        assert d["active"] == 2 and d["aircraft_with_episodes"] == 2
        assert d["cells"] == [[a, 2], [b, 1]]
        assert d["spoofed_to_top"] == [{"lat": 54.8, "lon": 20.7, "episodes": 2}]
        with open(os.path.join(tmp, "2026-10-28.summary.json"), "w", encoding="utf-8") as f:
            json.dump({"aircraft_with_episodes": 9}, f)
        with gzip.open(os.path.join(tmp, "2026-10-28.events.json.gz"), "wt", encoding="utf-8") as f:
            json.dump([ev[2]], f)
        quiet = spoof_summary.summarise(tmp, "2026-10-28")
        assert quiet["active"] == 0 and quiet["aircraft_with_episodes"] == 0 and quiet["cells"] == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_site_layers():
    tmp = tempfile.mkdtemp()
    try:
        rel, site = os.path.join(tmp, "rel"), os.path.join(tmp, "site")
        os.makedirs(rel)
        json.dump({"day": "2026-10-27", "active": 1, "cells": [["84abc", 1]]}, open(os.path.join(rel, "2026-10-27.spoof.json"), "w"))
        json.dump({"day": "2026-10-26", "active": 1}, open(os.path.join(rel, "2026-10-26.spoof.json"), "w"))   # no cells: skipped
        json.dump({"day": "2026-10-20", "cells": [["83abc", 1.5, 40]]}, open(os.path.join(rel, "2026-10-20.cygnss.json"), "w"))
        json.dump({"day": "2026-10-28", "sites": [{"id": "NZ-0027"}]}, open(os.path.join(rel, "2026-10-28.nisar.json"), "w"))
        json.dump({"day": "2026-10-29", "sites": []}, open(os.path.join(rel, "2026-10-29.nisar.json"), "w"))   # empty: kept
        json.dump({"day": "2026-10-30"}, open(os.path.join(rel, "2026-10-30.nisar.json"), "w"))                # no sites key: skipped
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "site_layers.py"), rel, site], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        idx = json.load(open(os.path.join(site, "data", "spoof", "index.json")))
        assert idx["days"] == ["2026-10-27"] and "ODbL" in idx["licence"]
        assert json.load(open(os.path.join(site, "data", "cygnss", "index.json")))["days"] == ["2026-10-20"]
        assert json.load(open(os.path.join(site, "data", "cygnss", "2026-10-20.json")))["licence"].startswith("Derived from NASA")
        nidx = json.load(open(os.path.join(site, "data", "nisar", "index.json")))
        assert nidx["days"] == ["2026-10-28", "2026-10-29"] and "NISAR" in nidx["licence"], nidx
        assert json.load(open(os.path.join(site, "data", "nisar", "2026-10-28.json")))["sites"][0]["id"] == "NZ-0027"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"test_site_layers: ok ({len(tests)} tests)")


if __name__ == "__main__":
    main()
