#!/usr/bin/env python3
"""spoof_summary.py: one day's spoofing output (tools/spoof_day.py) -> the small public file <day>.spoof.json.

  python tools/spoof_summary.py SPOOF_DIR DAY [DAY ...] --out DIR      # backfill from existing spoof_day outputs

Used by pipeline/daily_job.py --spoofing. Contents (aggregates only, ODbL 1.0): episodes by class; active episodes and
the aircraft behind them; for the map, the H3 res-4 hexes where aircraft really were during active episodes, with the
number of active episodes in each (`cells`); the H3 res-2 regions with the most active episodes; and the places
receivers were spoofed to (from spoof_day's summary). Victim locations are where the aircraft were, not where a
transmitter is.
"""
import argparse
import gzip
import json
import os
from collections import Counter


def summarise(spoof_dir, day):
    import h3
    with open(os.path.join(spoof_dir, f"{day}.summary.json"), encoding="utf-8") as f:
        s = json.load(f)
    with gzip.open(os.path.join(spoof_dir, f"{day}.events.json.gz"), "rt", encoding="utf-8") as f:
        ev = json.load(f)
    ev = ev.get("events", ev) if isinstance(ev, dict) else ev
    active = [e for e in ev if e.get("class") == "active"]
    hexes = Counter(c for e in active for c in set(e.get("victim_cells") or []))
    regions = Counter(h3.cell_to_parent(c, 2) for e in active for c in set(e.get("victim_cells") or []))
    return {"day": day, "version": s.get("version"), "licence": "ODbL 1.0; derived from adsb.lol",
            "active": len(active), "episodes": s.get("episodes"), "classes": s.get("episodes_by_class"),
            "aircraft_with_episodes": len({e.get("icao") for e in active if e.get("icao")}),
            "cells": sorted([[c, n] for c, n in hexes.items()], key=lambda x: -x[1]),
            "victim_res2_top": [{"region": c, "lat": round(h3.cell_to_latlng(c)[0], 2), "lon": round(h3.cell_to_latlng(c)[1], 2),
                                 "episodes": n} for c, n in regions.most_common(10)],
            "spoofed_to_top": [{"lat": la, "lon": lo, "episodes": n} for _, la, lo, n in (s.get("spoofed_to_res6_top") or [])[:10]],
            "method": "tools/spoof_day.py; docs/validation/spoofing.md. Cells and regions count active episodes (where the "
                      "aircraft really were)."}


def write(spoof_dir, day, out_dir):
    d = summarise(spoof_dir, day)
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, f"{day}.spoof.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, separators=(",", ":"))
    return p, d


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("spoof_dir")
    ap.add_argument("days", nargs="+")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    for day in a.days:
        p, d = write(a.spoof_dir, day, a.out)
        print(f"{p}: {d['active']} active episodes, {len(d['cells'])} hexes")


if __name__ == "__main__":
    main()
