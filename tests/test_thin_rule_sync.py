"""The map's thin-coverage hatching (site_src/map.js THIN_MIN) uses the same floor as <day>.coverage.json
(tools/feeder_coverage.py MIN_CELLS). Run: python tests/test_thin_rule_sync.py"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import feeder_coverage as F  # noqa: E402

with open(os.path.join(ROOT, "site_src", "map.js"), encoding="utf-8") as f:
    m = re.search(r"\bTHIN_MIN = (\d+)", f.read())
assert m, "THIN_MIN not found in site_src/map.js"
assert int(m.group(1)) == F.MIN_CELLS, f"map.js THIN_MIN {m.group(1)} != feeder_coverage MIN_CELLS {F.MIN_CELLS}"
print(f"ok: thin floor {F.MIN_CELLS} in both")
