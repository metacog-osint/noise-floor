#!/usr/bin/env python3
"""site_history.py: per-area history for the map's click-for-history, and each hex's usual level. Deploy time.

  python3 tools/site_history.py [SITE]    # SITE defaults to ./site

Reads every day file in SITE/data/gnss/ (oldest first) and:
  1. adds a "usual" column to each day file: the median jamming-scale share (GPSJam formula, live counts) of that hex
     over its previous 14 days with 5 or more aircraft; null with fewer than 5 such days. The map's "change from
     usual" view is today's share minus this.
  2. writes SITE/data/history/<res2>.json: for every H3 resolution-3 area (about 12,000 km2) with traffic, its daily
     sums of aircraft, live bad, capable and capable-bad aircraft-hexes, plus the days an anomaly event covered it
     (from SITE/data/events/). One file per resolution-2 cell (up to 7 areas), so a click fetches one small file.

Run after tools/site_days.py, which adds the daily days. Needs h3 (the deploy job installs it).
"""
import collections
import json
import os
import statistics
import sys

import h3

SITE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "site")
GNSS, EVENTS, HIST = (os.path.join(SITE, "data", d) for d in ("gnss", "events", "history"))
WINDOW, MIN_DAYS = 14, 5


def jam_share(n, bad):
    return 100 * max(bad - 1, 0) / n


def main():
    days = sorted(n[:-5] for n in os.listdir(GNSS) if n.endswith(".json") and n != "days.json")
    past = collections.defaultdict(lambda: collections.deque(maxlen=WINDOW))
    areas = collections.defaultdict(dict)        # res3 -> {day index: [aircraft, bad_live, capable, capable_bad10]}
    parent3 = {}
    for i, day in enumerate(days):
        p = os.path.join(GNSS, f"{day}.json")
        with open(p, encoding="utf-8") as f:
            obj = json.load(f)
        cols = obj["cols"]
        if "usual" in cols:                      # rerun: drop the old column first
            k = cols.index("usual")
            cols = cols[:k] + cols[k + 1:]
            obj["cells"] = [c[:k] + c[k + 1:] for c in obj["cells"]]
        ih, ia, ib, ic, icb = (cols.index(x) for x in ("h3", "aircraft", "bad_live", "capable", "capable_bad10"))
        for c in obj["cells"]:
            hx, n = c[ih], c[ia]
            q = past[hx]
            c.append(round(statistics.median(q), 1) if len(q) >= MIN_DAYS else None)
            if n >= 5:
                q.append(jam_share(n, c[ib]))
            r3 = parent3.get(hx) or parent3.setdefault(hx, h3.cell_to_parent(hx, 3))
            s = areas[r3].setdefault(i, [0, 0, 0, 0])
            s[0] += n; s[1] += c[ib]; s[2] += c[ic]; s[3] += c[icb]
        obj["cols"] = cols + ["usual"]
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, separators=(",", ":"), ensure_ascii=False)

    # anomaly events per res-2 region and day, by measure
    ev = collections.defaultdict(lambda: {"jam": [], "acc": []})
    for i, day in enumerate(days):
        p = os.path.join(EVENTS, f"{day}.json")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            e = json.load(f)
        for a in e.get("anomalies", []):
            for r2 in a.get("cells", []):
                ev[r2][a["m"]].append([i, {"major": 3, "notable": 2}.get(a["tier"], 1)])   # [day index, level]

    tiles = collections.defaultdict(dict)
    for r3, by_day in areas.items():
        lat, lon = h3.cell_to_latlng(r3)
        series = [by_day.get(i, [0, 0, 0, 0]) for i in range(len(days))]
        rec = {"c": [round(lat, 2), round(lon, 2)], "a": [s[0] for s in series], "b": [s[1] for s in series],
               "k": [s[2] for s in series], "kb": [s[3] for s in series]}
        r2 = h3.cell_to_parent(r3, 2)
        if r2 in ev:
            rec["ev"] = ev[r2]
        tiles[r2][r3] = rec
    os.makedirs(HIST, exist_ok=True)
    for name in os.listdir(HIST):
        if name.endswith(".json"):
            os.remove(os.path.join(HIST, name))
    for r1, recs in tiles.items():
        with open(os.path.join(HIST, f"{r1}.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump({"days": days, "areas": recs}, f, separators=(",", ":"))
    print(f"site_history: {len(days)} days; usual levels added; {len(areas)} areas in {len(tiles)} history files")


if __name__ == "__main__":
    main()
