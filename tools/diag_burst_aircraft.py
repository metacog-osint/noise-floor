#!/usr/bin/env python3
"""diag_burst_aircraft.py — who makes up a day's largest night-time burst events over central Europe?

Re-reads the day's adsb.lol archive and, for the three largest burst events starting 01-06Z over central Europe
(45-55N, 5-25E; from data/pnt/analysis/<day>.bursts.json), reports the aircraft with gross-bad reports in them:
  - post-exposure tagged or not; peer bad share; where each first degraded that day
  - aircraft-type mix of the degraded aircraft vs all aircraft present in the same hex-hours
Prints types and positions only; no aircraft identifiers. This is how the A350 pattern of 21-25 Oct 2025 was found.

Usage
  python tools/diag_burst_aircraft.py 2025-10-23 --raw <folder with the day's adsb.lol tar or parts>
"""
import argparse, io, json, os, sys
from collections import Counter
from datetime import datetime, timezone
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import h3  # noqa: E402
import pnt_daily as P  # noqa: E402

BOX = (45.0, 55.0, 5.0, 25.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("day")
    ap.add_argument("--raw", required=True)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()
    ev = json.load(open(os.path.join(ROOT, "data", "pnt", "analysis", f"{a.day}.bursts.json")))["events"]
    ev = sorted([e for e in ev if BOX[0] <= e["lat"] <= BOX[1] and BOX[2] <= e["lon"] <= BOX[3] and 1 <= int(e["start"][:2]) < 6],
                key=lambda e: -e["peak_aircraft"])[:3]
    day0 = int(datetime.fromisoformat(a.day).replace(tzinfo=timezone.utc).timestamp())
    stream = io.BufferedReader(P.Chain(P.day_parts(a.raw, a.day)), buffer_size=8 << 20)
    recs = []
    with Pool(a.workers) as pool:
        for r, _ in pool.imap_unordered(P.work, P.batches(stream, day0), chunksize=1):
            recs.extend(r)
    tot = P.hex_hour_totals(recs)
    tagged, _ = P.resolve_post_exposure(recs, tot)
    for e in ev:
        cells = set(h3.grid_disk(h3.latlng_to_cell(e["lat"], e["lon"], 2), 1))
        m0 = int(e["start"][:2]) * 60 + int(e["start"][3:5]); m1 = int(e["end"][:2]) * 60 + int(e["end"][3:5])
        hits, keys = [], set()
        for i, (c, meta, bad_minutes) in enumerate(recs):
            mins = [(hx, m) for hx, m in bad_minutes if m0 <= m <= m1 and h3.cell_to_parent(h3.int_to_str(hx), 2) in cells]
            if not mins:
                continue
            keys |= {(hx, m // 60) for hx, m in mins}
            shares = [(tot[(hx, m // 60)][1] - 1) / (tot[(hx, m // 60)][0] - 1) for hx, m in mins if tot[(hx, m // 60)][0] > 1]
            first = min(m for _, m in bad_minutes)
            la, lo = h3.cell_to_latlng(h3.int_to_str(next(hx for hx, m in bad_minutes if m == first)))
            hits.append({"type": meta[6] or "?", "tagged": any((hx, m // 60) in tagged[i] for hx, m in mins),
                         "peer_bad": sum(shares) / len(shares) if shares else None, "first_bad_at": (round(la), round(lo))})
        present = Counter(meta[6] or "?" for c, meta, _ in recs if any(k in c for k in keys))
        deg = Counter(h["type"] for h in hits)
        print(f"\n== {e['start']}-{e['end']} near {e['lat']},{e['lon']}: {len(hits)} aircraft with gross-bad reports")
        print(f"   post-exposure tagged: {sum(h['tagged'] for h in hits)}; median peer bad share: "
              f"{sorted(h['peer_bad'] for h in hits if h['peer_bad'] is not None)[len(hits) // 2]:.2f}")
        print("   first degraded at (lat, lon):", Counter(h["first_bad_at"] for h in hits).most_common(6))
        print("   types, degraded vs all present:")
        for t, n in deg.most_common(6):
            print(f"     {t}: {n}/{len(hits)} ({100 * n / len(hits):.0f}%) vs {present[t]}/{sum(present.values())} ({100 * present[t] / max(1, sum(present.values())):.1f}%)")


if __name__ == "__main__":
    main()
