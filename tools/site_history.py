#!/usr/bin/env python3
"""site_history.py: per-area history for the map's click-for-history, and each hex's usual level. Deploy time.

  python3 tools/site_history.py [SITE]    # SITE defaults to ./site

Reads every day file in SITE/data/gnss/ (oldest first) and:
  1. adds a "usual" column to each day file: the median jamming-scale share (GPSJam formula, live counts) of that hex
     over its previous 14 days with 5 or more aircraft; null with fewer than 5 such days. The map's "change from
     usual" view is today's share minus this.
     Adds a "usual_n" column too: the hex's median aircraft count over its previous 14 day files, counting files
     without it as zero (null until it has 7). Hexes that usually have 10 or more aircraft but are missing today get a
     row with zero aircraft, so the map's "fewer aircraft than usual" view can show them: strong jamming can stop
     aircraft sending a position at all, and then they vanish instead of showing as degraded.
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
MIN_HIST, MISS_MIN = 7, 10          # usual_n needs 7 earlier day files; missing hexes are added from 10 usual aircraft
ADDED = ("usual", "usual_n")        # columns this script adds (dropped first on a rerun)


def jam_share(n, bad):
    return 100 * max(bad - 1, 0) / n


def median(q):
    s = sorted(q); k = len(s) // 2
    return s[k] if len(s) % 2 else (s[k - 1] + s[k]) / 2


def main():
    days = sorted(n[:-5] for n in os.listdir(GNSS) if n.endswith(".json") and n != "days.json")
    past = collections.defaultdict(lambda: collections.deque(maxlen=WINDOW))
    past_n = {}                                  # hex -> deque of aircraft counts over its last 14 day files (0 = absent)
    areas = collections.defaultdict(dict)        # res3 -> {day index: [aircraft, bad_live, capable, capable_bad10]}
    parent3 = {}
    added = 0
    for i, day in enumerate(days):
        p = os.path.join(GNSS, f"{day}.json")
        with open(p, encoding="utf-8") as f:
            obj = json.load(f)
        cols = obj["cols"]
        drop = [k for k, name in enumerate(cols) if name in ADDED]
        if drop:                                 # rerun: drop the added columns and the zero-aircraft rows first
            ia0 = cols.index("aircraft")
            obj["cells"] = [[v for k, v in enumerate(c) if k not in drop] for c in obj["cells"] if c[ia0]]
            cols = [name for k, name in enumerate(cols) if k not in drop]
        ih, ia, ib, ic, icb = (cols.index(x) for x in ("h3", "aircraft", "bad_live", "capable", "capable_bad10"))
        present = {}
        for c in obj["cells"]:
            hx, n = c[ih], c[ia]
            present[hx] = n
            q = past[hx]
            c.append(round(statistics.median(q), 1) if len(q) >= MIN_DAYS else None)
            if n >= 5:
                q.append(jam_share(n, c[ib]))
            qn = past_n.get(hx)
            c.append(median(qn) if qn is not None and len(qn) >= MIN_HIST else None)
            r3 = parent3.get(hx) or parent3.setdefault(hx, h3.cell_to_parent(hx, 3))
            s = areas[r3].setdefault(i, [0, 0, 0, 0])
            s[0] += n; s[1] += c[ib]; s[2] += c[ic]; s[3] += c[icb]
        width = len(cols)
        for hx, qn in list(past_n.items()):      # usual traffic, none today: a zero-aircraft row
            if hx not in present:
                if len(qn) >= MIN_HIST:
                    u = median(qn)
                    if u >= MISS_MIN:
                        obj["cells"].append([hx] + [0] * (width - 1) + [None, u]); added += 1
                qn.append(0)
                if not any(qn):
                    del past_n[hx]
        for hx, n in present.items():
            past_n.setdefault(hx, collections.deque(maxlen=WINDOW)).append(n)
        obj["cols"] = cols + list(ADDED)
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
    print(f"site_history: {len(days)} days; usual levels and counts added ({added} zero-aircraft rows for missing hexes); "
          f"{len(areas)} areas in {len(tiles)} history files")


if __name__ == "__main__":
    main()
