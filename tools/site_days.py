#!/usr/bin/env python3
"""Add the daily map and event files to the site's data and rebuild the day index. Standard library only.

The 20 validated days are committed in site/data/gnss/ and site/data/events/. Days made by the daily workflow are
stored as assets on this repo's pnt-data-YYYY-MM releases. The deploy job downloads them and runs

  python3 tools/site_days.py DIR [SITE]   # DIR/<day>.map.json -> SITE/data/gnss/<day>.json, rebuild days.json;
                                          # DIR/<day>.{anomalies,bursts,sbas}.json -> SITE/data/events/<day>.json

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
EVENTS = os.path.join(ROOT, "site", "data", "events")
MAP_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.map\.json$")
MEASURE = {"gross": "jam", "capable_10m": "acc"}


def stats(obj):
    """(hexes with 5+ aircraft, those at jamming scale): GPSJam-style share of live bad aircraft >= 10%."""
    cols = obj["cols"]
    ia, ib = cols.index("aircraft"), cols.index("bad_live")
    n5 = [c for c in obj["cells"] if c[ia] >= 5]
    return len(n5), sum(1 for c in n5 if 100 * max(c[ib] - 1, 0) / c[ia] >= 10)


def sbas_runs(sbas):
    """Flagged SBAS hours as runs: [{area, start, end, state}] (consecutive hours with the same state)."""
    runs = []
    for area, v in (sbas.get("areas") or {}).items():
        for h in v.get("hours") or []:
            if not h or h["state"].startswith("ok"):
                continue
            last = runs[-1] if runs else None
            if last and last["area"] == area and last["state"] == h["state"] and last["end"] == h["hour"] - 1:
                last["end"] = h["hour"]
            else:
                runs.append({"area": area, "start": h["hour"], "end": h["hour"], "state": h["state"]})
    return runs


def events(day, anomalies, bursts, sbas):
    """The map page's event file for a day, from pnt_analysis outputs: anomaly events (ranked as the analysis ranks
    them), burst events and SBAS flags. Aggregates and H3 res-2 region ids only."""
    out = {"day": day, "licence": "ODbL 1.0; derived from adsb.lol",
           "baseline_days": len(anomalies.get("baseline_days") or []), "anomaly_note": anomalies.get("error", ""),
           "burst_basis": (bursts.get("events") or [{}])[0].get("basis", ""), "anomalies": [], "bursts": [],
           "sbas": sbas_runs(sbas)}
    for e in anomalies.get("events") or []:
        out["anomalies"].append({"m": MEASURE[e["measure"]], "tier": e["tier"], "h0": e["start_hour"], "h1": e["end_hour"],
                                 "regions": e["regions"], "rh": e["region_hours"], "peak": e["peak_share"],
                                 "excess": e["peak_excess"], "lat": e["lat"], "lon": e["lon"], "cells": e.get("cells", [])})
    for e in bursts.get("events") or []:
        out["bursts"].append({"t0": e["start"], "t1": e["end"], "peak": e["peak_aircraft"], "regions": e["regions"],
                              "lat": e["lat"], "lon": e["lon"], "cells": e.get("cells", [])})
    return out


def write_events(day, folder, out_dir):
    """Write out_dir/<day>.json from folder/<day>.{anomalies,bursts,sbas}.json; False if any is missing."""
    src = {k: os.path.join(folder, f"{day}.{k}.json") for k in ("anomalies", "bursts", "sbas")}
    if not all(os.path.exists(p) for p in src.values()):
        return False
    loaded = {}
    for k, p in src.items():
        with open(p, encoding="utf-8") as f:
            loaded[k] = json.load(f)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"{day}.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(events(day, loaded["anomalies"], loaded["bursts"], loaded["sbas"]), f, separators=(",", ":"), ensure_ascii=False)
    return True


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
    global GNSS, EVENTS
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    src = sys.argv[1]
    if len(sys.argv) == 3:
        GNSS, EVENTS = os.path.join(sys.argv[2], "data", "gnss"), os.path.join(sys.argv[2], "data", "events")
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
    with_events = [d for d in added if write_events(d, src, EVENTS)]
    index = list(committed.values()) + [entry(d, daily=True) for d in added]
    index.sort(key=lambda d: d["day"])
    with open(index_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(index, f, separators=(",", ":"), ensure_ascii=False)
    print(f"days.json: {len(committed)} committed + {len(added)} daily"
          + (f" ({added[0]} to {added[-1]}); event files for {len(with_events)}" if added else ""))


if __name__ == "__main__":
    main()
