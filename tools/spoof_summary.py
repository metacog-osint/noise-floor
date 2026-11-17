#!/usr/bin/env python3
"""spoof_summary.py: one day's spoofing output (tools/spoof_day.py) -> the small public file <day>.spoof.json, and the
spoofed-to clusters, <day>.spoof-targets.json.

  python tools/spoof_summary.py SPOOF_DIR DAY [DAY ...] --out DIR      # backfill from existing spoof_day outputs

Used by pipeline/daily_job.py --spoofing. Both files hold aggregates only (ODbL 1.0) and no aircraft identifiers.

<day>.spoof.json (the home board and the map layer): episodes by class; active episodes and the aircraft behind them;
for the map, the H3 res-4 hexes where aircraft really were during active episodes, with the number of active episodes
in each (`cells`); the H3 res-2 regions with the most active episodes; the places receivers were spoofed to (from
spoof_day's summary, top 10); and, from late Nov 2026, the active share of aircraft-hours in every H3 res-2 region with
traffic (`share2`, from spoof_day's hex2 table). Victim locations are where the aircraft were, not where a transmitter is.

<day>.spoof-targets.json (from Nov 2026): every place the detector saw receivers spoofed to that day, not only the top
10, so that a reader can follow any one destination from day to day. Each episode's spoofed-to point is the median of
its false positions (spoof_day's false_lat / false_lon). Points are grouped by targets(): densest first, each cluster
takes every ungrouped point within TARGET_KM of its seed. A ring of about 1 km radius stays one cluster (any point on it
is within 2 km of every other). Replay episodes (stale data, not spoofing) are left out. Per cluster: centre, spread,
episodes and distinct aircraft, episodes by class and by kind, first and last time, the altitude range, and the H3
res-4 cells where the aircraft really were during those episodes, with episode and aircraft counts. A separate file
because it runs to tens of kB a day (70 kB on 12 Nov 2026), which the site, which copies every <day>.spoof.json, doesn't need.
"""
import argparse
import gzip
import json
import math
import os
import statistics
from collections import Counter, defaultdict

TARGET_KM = 5.0          # cluster radius around the seed (see targets())
TARGET_RES = 5           # H3 resolution of the neighbour search (cells far wider than TARGET_KM)
TARGETS_VERSION = "2"           # 2 (v0.6, Nov 2026): adds unplaced
SHARE_MIN_AH = 10               # share2: res-2 cells with at least this many aircraft-hours


def km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 12742.0 * math.asin(min(1.0, math.sqrt(a)))


def load(spoof_dir, day):
    with open(os.path.join(spoof_dir, f"{day}.summary.json"), encoding="utf-8") as f:
        s = json.load(f)
    with gzip.open(os.path.join(spoof_dir, f"{day}.events.json.gz"), "rt", encoding="utf-8") as f:
        ev = json.load(f)
    return s, (ev.get("events", ev) if isinstance(ev, dict) else ev)


def share2(spoof_dir, day, min_aircraft_hours=SHARE_MIN_AH):
    """[[H3 res-2 cell, aircraft-hours, active aircraft-hours]] from spoof_day's <day>.hex2.parquet (the measure of
    the held-out checks H1 and H2: aircraft counted once per cell and UTC hour), for cells with at least
    min_aircraft_hours; None when the table isn't there (summaries rebuilt from the published files alone)."""
    path = os.path.join(spoof_dir, f"{day}.hex2.parquet")
    if not os.path.exists(path):
        return None
    import pyarrow.parquet as pq
    tot = defaultdict(lambda: [0, 0])
    for r in pq.read_table(path, columns=["h3", "aircraft", "spoofed_active"]).to_pylist():
        tot[r["h3"]][0] += r["aircraft"] or 0
        tot[r["h3"]][1] += r["spoofed_active"] or 0
    return sorted(([c, a, s] for c, (a, s) in tot.items() if a >= min_aircraft_hours), key=lambda x: x[0])


def summarise(spoof_dir, day, loaded=None):
    import h3
    s, ev = loaded or load(spoof_dir, day)
    active = [e for e in ev if e.get("class") == "active"]
    hexes = Counter(c for e in active for c in set(e.get("victim_cells") or []))
    regions = Counter(h3.cell_to_parent(c, 2) for e in active for c in set(e.get("victim_cells") or []))
    return {"day": day, "version": s.get("version"), "licence": "ODbL 1.0; derived from adsb.lol",
            "active": len(active), "episodes": s.get("episodes"), "classes": s.get("episodes_by_class"),
            "aircraft_with_episodes": len({e.get("icao") for e in active if e.get("icao")}),
            "cells": sorted([[c, n] for c, n in hexes.items()], key=lambda x: -x[1]),
            "victim_res2_top": [{"region": c, "lat": round(h3.cell_to_latlng(c)[0], 2), "lon": round(h3.cell_to_latlng(c)[1], 2),
                                 "episodes": n} for c, n in sorted(regions.items(), key=lambda x: (-x[1], x[0]))[:10]],
            "spoofed_to_top": [{"lat": la, "lon": lo, "episodes": n} for _, la, lo, n in (s.get("spoofed_to_res6_top") or [])[:10]],
            "targets_file": f"{day}.spoof-targets.json",
            **({"share2": sh} if (sh := share2(spoof_dir, day)) is not None else {}),
            "method": "tools/spoof_day.py; docs/validation/spoofing.md. Cells and regions count active episodes (where the "
                      "aircraft really were). Every spoofed-to cluster, not only the top 10: targets_file. share2 (from late "
                      "Nov 2026): [H3 res-2 cell, aircraft-hours, aircraft-hours in active episodes] for cells with "
                      f"{SHARE_MIN_AH} or more aircraft-hours, the measure of the held-out checks."}


def targets(events, radius_km=TARGET_KM):
    """Group episodes by spoofed-to point. Returns a list of member-index lists, largest first.

    Deterministic leader clustering: count each point's neighbours within radius_km; take the point with the most
    (ties: earliest start, then lat, lon) as a seed; its cluster is every ungrouped point within radius_km of it; repeat.
    Clusters are at most 2 * radius_km across, so neighbouring spoofing points more than about radius_km apart stay
    apart, and points on a ring of radius under radius_km / 2 always share one cluster."""
    import h3
    pts = [(i, e["false_lat"], e["false_lon"]) for i, e in enumerate(events)]
    cell_of = {i: h3.latlng_to_cell(la, lo, TARGET_RES) for i, la, lo in pts}
    by_cell = defaultdict(list)
    for i, la, lo in pts:
        by_cell[cell_of[i]].append((i, la, lo))
    near = {}
    for i, la, lo in pts:
        near[i] = [j for c in h3.grid_disk(cell_of[i], 1) for j, la2, lo2 in by_cell.get(c, ())
                   if km(la, lo, la2, lo2) <= radius_km]
    order = sorted((i for i, _, _ in pts), key=lambda i: (-len(near[i]), events[i].get("start") or "",
                                                           events[i]["false_lat"], events[i]["false_lon"]))
    done, out = set(), []
    for i in order:
        if i in done:
            continue
        members = sorted(j for j in near[i] if j not in done)
        done.update(members)
        out.append(members)
    out.sort(key=lambda m: (-len(m), min(events[j].get("start") or "" for j in m)))
    return out


def target_summary(day, events, s=None, radius_km=TARGET_KM):
    """<day>.spoof-targets.json from spoof_day's events (aggregates only: no ICAO addresses, types or flight times)."""
    import h3
    usable = [e for e in events if e.get("class") != "replay" and e.get("false_lat") is not None
              and e.get("false_lon") is not None]
    def common(eps):
        cells = defaultdict(lambda: [0, set()])
        for e in eps:
            for c in set(e.get("victim_cells") or []):
                cells[c][0] += 1
                cells[c][1].add(e.get("icao"))
        alts = [e["alt"] for e in eps if isinstance(e.get("alt"), (int, float))]
        return {
            "episodes": len(eps), "aircraft": len({e.get("icao") for e in eps}),
            "classes": dict(sorted(Counter(e.get("class") for e in eps).items())),
            "kinds": dict(sorted(Counter(k for e in eps for k in e.get("kinds") or []).items())),
            "first": min(e["start"] for e in eps), "last": max(e["end"] for e in eps),
            "alt_ft": [min(alts), max(alts)] if alts else None,
            "clean": sum(1 for e in eps if (e.get("clean_share") or 0) >= 0.5),
            "mlat_confirmed": sum(1 for e in eps if e.get("mlat_dis")),
            "located": sum(1 for e in eps if e.get("victim_cells")),
            "victim_cells": sorted(([c, n, len(a)] for c, (n, a) in cells.items()), key=lambda x: (-x[1], x[0])),
        }

    clusters = []
    for members in targets(usable, radius_km):
        eps = [usable[j] for j in members]
        lat = statistics.median(e["false_lat"] for e in eps)
        lon = statistics.median(e["false_lon"] for e in eps)
        d = sorted(km(lat, lon, e["false_lat"], e["false_lon"]) for e in eps)
        clusters.append({"lat": round(lat, 4), "lon": round(lon, 4),
                         "r50_km": round(d[len(d) // 2], 2), "r90_km": round(d[min(len(d) - 1, int(0.9 * len(d)))], 2),
                         **common(eps)})
    bands = defaultdict(list)
    for e in events:
        if e.get("class") != "replay" and (e.get("false_lat") is None or e.get("false_lon") is None):
            g = e.get("reported_gs")
            bands[int(round(g / 10.0)) * 10 if isinstance(g, (int, float)) else None].append(e)
    unplaced = [{"reported_gs_kt": b, **common(eps)}
                for b, eps in sorted(bands.items(), key=lambda x: (-len(x[1]), x[0] is None, x[0] or 0))]
    return {
        "day": day, "version": (s or {}).get("version"), "targets_version": TARGETS_VERSION,
        "licence": "ODbL 1.0; derived from adsb.lol",
        "radius_km": radius_km, "episodes": len(events), "clustered": len(usable),
        "left_out": {"replay": sum(1 for e in events if e.get("class") == "replay"),
                     "no_false_position": sum(1 for e in events if e.get("class") != "replay"
                                              and (e.get("false_lat") is None or e.get("false_lon") is None))},
        "fields": {
            "lat, lon": "cluster centre: median of the episodes' spoofed-to points (each the median of its false positions)",
            "r50_km, r90_km": "median and 90th-percentile distance of those points from the centre",
            "episodes, aircraft": "spoofing episodes, and distinct aircraft, shown here",
            "classes": "episodes by class: active, post (post-exposure), isolated, unlocated (docs/validation/spoofing.md)",
            "kinds": "episodes with slow, loiter or excursion positions (an episode can have more than one)",
            "first, last": "start of the first episode and end of the last, UTC",
            "alt_ft": "lowest and highest baro altitude at the start of an episode",
            "clean": "episodes whose false positions were mostly NACp 8 or better",
            "mlat_confirmed": "episodes where MLAT put the aircraft 20 km or more from its ADS-B position",
            "located": "episodes with a victim location (where the aircraft really was)",
            "victim_cells": "[H3 res-4 cell, episodes, distinct aircraft]: where the aircraft really were during these "
                            "episodes (interpolated between trusted positions; good at res 2, rough at res 4)",
            "unplaced": "episodes with no spoofed-to point (v0.6 speed episodes: the aircraft reported a slow ground "
                        "speed while MLAT showed it moving at normal speed; its false positions aren't in the archive), "
                        "grouped by the median reported ground speed rounded to 10 kt (reported_gs_kt), with the same "
                        "fields as a cluster; victim_cells are the MLAT positions",
        },
        "clusters": clusters,
        "unplaced": unplaced,
        "method": "tools/spoof_day.py and tools/spoof_summary.py targets(); docs/validation/spoofing.md. Spoofed-to points "
                  "are where receivers were shown, not where a transmitter is.",
    }


def write(spoof_dir, day, out_dir):
    """Write <day>.spoof.json and <day>.spoof-targets.json. Returns (spoof.json path, its dict, targets path)."""
    s, ev = load(spoof_dir, day)
    d = summarise(spoof_dir, day, (s, ev))
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, f"{day}.spoof.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, separators=(",", ":"))
    pt = os.path.join(out_dir, f"{day}.spoof-targets.json")
    with open(pt, "w", encoding="utf-8") as f:
        json.dump(target_summary(day, ev, s), f, separators=(",", ":"))
    return p, d, pt


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("spoof_dir")
    ap.add_argument("days", nargs="+")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    for day in a.days:
        p, d, pt = write(a.spoof_dir, day, a.out)
        print(f"{p}: {d['active']} active episodes, {len(d['cells'])} hexes; {pt}: {os.path.getsize(pt):,} bytes")


if __name__ == "__main__":
    main()
