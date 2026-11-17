"""feeder_coverage.py: how well Noisefloor's ADS-B feeders cover each H3 res-2 region on a day (docs/validation/coverage-flag.md).

A res-4 cell is covered when it has 3 or more aircraft (every cell in <day>.map.json is). A region is `thin` when
fewer than MIN_CELLS of its 49 res-4 cells are covered. A region not listed in the file has no covered cell and is
thin too. The rule uses only Noisefloor's own counts; it was tested against GPSJam's coverage before it was adopted.

  python tools/feeder_coverage.py DAY.map.json OUT.coverage.json
"""
import json
import os
import sys
from collections import Counter

import h3

MIN_CELLS = 10
RULE = (f"thin: fewer than {MIN_CELLS} of a region's 49 H3 res-4 cells have 3 or more aircraft; "
        "a region not listed has none and is thin")


def regions(map_obj):
    """{res-2 region: covered res-4 cells} from a map.json object (every cell in it has 3+ aircraft)."""
    ia = map_obj["cols"].index("aircraft")
    return Counter(h3.cell_to_parent(c[0], 2) for c in map_obj["cells"] if c[ia] >= 3)


def coverage(map_obj):
    reg = regions(map_obj)
    return {"day": map_obj["day"], "licence": map_obj.get("licence", "ODbL 1.0; derived from adsb.lol"),
            "rule": RULE, "min_cells": MIN_CELLS, "cols": ["h3_2", "covered", "thin"],
            "regions": [[r, n, n < MIN_CELLS] for r, n in sorted(reg.items())],
            "thin": sum(1 for n in reg.values() if n < MIN_CELLS), "listed": len(reg)}


def write(map_path, out_path):
    with open(map_path, encoding="utf-8") as f:
        obj = coverage(json.load(f))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, separators=(",", ":"))
    return obj


if __name__ == "__main__":
    o = write(sys.argv[1], sys.argv[2])
    print(f"{o['day']}: {o['listed']} regions listed, {o['thin']} of them thin")
