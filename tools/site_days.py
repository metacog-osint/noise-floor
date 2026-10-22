#!/usr/bin/env python3
"""Add the daily map files to the site's map data and rebuild the day index. Standard library only.

The 20 validated days are committed in site/data/gnss/. Days made by the daily workflow are stored as
<day>.map.json assets on this repo's pnt-data-YYYY-MM releases. The deploy job downloads them and runs

  python3 tools/site_days.py DIR     # copy DIR/<day>.map.json to site/data/gnss/<day>.json, rebuild days.json

A committed file wins over a downloaded one for the same day. The index keeps the committed days' notes and
marks every other day "daily": made automatically, not reviewed by a person.
"""
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GNSS = os.path.join(ROOT, "site", "data", "gnss")
MAP_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.map\.json$")


def stats(obj):
    """(hexes with 5+ aircraft, those at jamming scale): GPSJam-style share of live bad aircraft >= 10%."""
    cols = obj["cols"]
    ia, ib = cols.index("aircraft"), cols.index("bad_live")
    n5 = [c for c in obj["cells"] if c[ia] >= 5]
    return len(n5), sum(1 for c in n5 if 100 * max(c[ib] - 1, 0) / c[ia] >= 10)


def entry(day, note="", daily=False):
    path = os.path.join(GNSS, f"{day}.json")
    with open(path, encoding="utf-8") as f:
        obj = json.load(f)
    if obj.get("day") != day:
        sys.exit(f"{path}: holds day {obj.get('day')!r}")
    hexes, jam = stats(obj)
    e = {"day": day, "note": note, "hexes": hexes, "jam_hexes": jam, "kb": round(os.path.getsize(path) / 1024)}
    if daily:
        e["daily"] = True
    return e


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    index_path = os.path.join(GNSS, "days.json")
    with open(index_path, encoding="utf-8") as f:
        committed = {d["day"]: d for d in json.load(f)}
    added = []
    for name in sorted(os.listdir(src)) if os.path.isdir(src) else []:
        m = MAP_FILE.match(name)
        if not m or m.group(1) in committed:
            continue
        shutil.copyfile(os.path.join(src, name), os.path.join(GNSS, f"{m.group(1)}.json"))
        added.append(m.group(1))
    index = list(committed.values()) + [entry(d, daily=True) for d in added]
    index.sort(key=lambda d: d["day"])
    with open(index_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(index, f, separators=(",", ":"), ensure_ascii=False)
    print(f"days.json: {len(committed)} committed + {len(added)} daily"
          + (f" ({added[0]} to {added[-1]})" if added else ""))


if __name__ == "__main__":
    main()
