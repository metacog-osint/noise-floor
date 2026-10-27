"""Offline test for tools/map_thumb.py (the home page's map of the latest day). Run as a plain script."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

import h3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_thumbnail():
    tmp = tempfile.mkdtemp()
    try:
        g = os.path.join(tmp, "data", "gnss")
        os.makedirs(g)
        json.dump([{"day": "2026-10-25", "daily": True}, {"day": "2026-10-26", "daily": True}], open(os.path.join(g, "days.json"), "w"))
        cols = ["h3", "aircraft", "bad_live", "bad_raw", "capable", "capable_bad10", "usual", "usual_n"]
        cells = [[h3.latlng_to_cell(55.0, 20.5, 4), 20, 11, 11, 20, 12, 0, 3],     # 50%: the darkest class
                 [h3.latlng_to_cell(45.0, 30.0, 4), 20, 2, 2, 20, 3, 0, 3],      # 5%: second class
                 [h3.latlng_to_cell(48.0, 10.0, 4), 20, 0, 0, 20, 0, 0, 3],      # quiet
                 [h3.latlng_to_cell(48.5, 11.0, 4), 3, 3, 3, 3, 3, 0, 3],        # under 5 aircraft: not drawn
                 [h3.latlng_to_cell(40.0, -100.0, 4), 20, 15, 15, 20, 15, 0, 3]]  # outside the view
        json.dump({"day": "2026-10-26", "cols": cols, "cells": cells}, open(os.path.join(g, "2026-10-26.json"), "w"))
        land = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": {
            "type": "Polygon", "coordinates": [[[0, 40], [30, 40], [30, 60], [0, 60], [0, 40]]]}}]}
        json.dump(land, open(os.path.join(tmp, "data", "land.json"), "w"))
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "map_thumb.py"), tmp], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert "2 hexes at 2% or more, 1 quieter" in r.stdout, r.stdout
        light = open(os.path.join(tmp, "data", "today-map.svg"), encoding="utf-8").read()
        dark = open(os.path.join(tmp, "data", "today-map-dark.svg"), encoding="utf-8").read()
        assert "<title>Aircraft GPS loss, 2026-10-26 (UTC)</title>" in light
        assert 'fill="#6e2c0f"' in light and 'fill="#c85f2a"' in light and 'fill="#e3824c"' not in light
        assert 'fill="#ffbd8a"' in dark and 'fill="#0b0e12"' in dark
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    test_thumbnail()
    print("test_map_thumb: ok (1 test)")


if __name__ == "__main__":
    main()
