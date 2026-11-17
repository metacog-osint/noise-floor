"""Offline test for tools/feeder_coverage.py (per-region feeder coverage). Run as a plain script."""
import json
import os
import sys
import tempfile

import h3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import feeder_coverage as C  # noqa: E402


def test_thin_and_covered():
    busy = h3.latlng_to_cell(55.0, 37.0, 2)
    sparse = h3.latlng_to_cell(9.0, 39.0, 2)
    kids_busy = sorted(h3.cell_to_children(busy, 4))[:12]       # 12 covered cells: not thin
    kids_sparse = sorted(h3.cell_to_children(sparse, 4))[:9]    # 9: thin (fewer than 10)
    cols = ["h3", "aircraft", "bad_live", "bad_raw", "capable", "capable_bad10", "bad_any"]
    cells = [[k, 5, 0, 0, 3, 0, 1] for k in kids_busy + kids_sparse]
    cells.append([h3.latlng_to_cell(30.0, 30.0, 4), 2, 0, 0, 1, 0, 0])   # under 3 aircraft: never counted
    obj = C.coverage({"day": "2026-11-17", "licence": "ODbL 1.0; derived from adsb.lol", "cols": cols, "cells": cells})
    rows = {r[0]: r for r in obj["regions"]}
    assert rows[busy] == [busy, 12, False], rows[busy]
    assert rows[sparse] == [sparse, 9, True], rows[sparse]
    assert len(rows) == 2 and obj["listed"] == 2 and obj["thin"] == 1
    assert obj["cols"] == ["h3_2", "covered", "thin"] and obj["min_cells"] == 10
    assert obj["licence"].startswith("ODbL")


def test_write_roundtrip():
    tmp = tempfile.mkdtemp()
    m = os.path.join(tmp, "d.map.json")
    k = h3.latlng_to_cell(26.0, 52.0, 4)
    json.dump({"day": "2026-11-02", "cols": ["h3", "aircraft"], "cells": [[k, 4]]}, open(m, "w"))
    out = os.path.join(tmp, "out", "d.coverage.json")
    C.write(m, out)
    got = json.load(open(out))
    assert got["regions"] == [[h3.cell_to_parent(k, 2), 1, True]], got
    assert got["day"] == "2026-11-02"


if __name__ == "__main__":
    test_thin_and_covered()
    test_write_roundtrip()
    print("ok")
