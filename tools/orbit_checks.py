#!/usr/bin/env python3
"""orbit_checks.py: checks O1 and O2 of docs/assessment/events.md ("v1.2 candidate: orbital GNSS receivers"), frozen
in commit 5913d00 before they were run.

For Sentinel-6A (tools/s6_rfi.py grids) and COSMIC-2 (tools/cosmic2_rfi.py grids) on the 21 held-out days:
  O1  place: share of ADS-B 93 m observations whose res-2 cells reach the sensor's threshold, against random land points
  O2  time within a region: for res-2 regions with 93 m observations on 2-18 of the 21 days, the mean score on those
      days minus the mean on the others; share of regions positive and a one-sided sign test

  python tools/orbit_checks.py            # prints JSON and writes data/events/orbit_checks.json
"""
import json
import math
import os
import sqlite3
import sys
from collections import defaultdict

import h3
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
REGISTER = os.path.join(ROOT, "data", "events", "register.sqlite")
OUT = os.path.join(ROOT, "data", "events", "orbit_checks.json")
DAYS = ["2025-10-01", "2025-10-20", "2025-11-08", "2025-11-27", "2025-12-16", "2026-01-04", "2026-01-23", "2026-02-11",
        "2026-03-02", "2026-03-21", "2026-04-09", "2026-04-28", "2026-05-17", "2026-06-05", "2026-06-24", "2026-07-13",
        "2026-08-01", "2026-08-20", "2026-09-08", "2026-09-27", "2026-10-16"]
POINTS = 400


def sensors():
    import cosmic2_rfi as C2
    import s6_rfi as S6
    return {"sentinel6": (lambda d: S6.read_grid(d), 0.2409, 66.0),
            "cosmic2": (lambda d: C2.read_grid(d, 2, 2500.0, True), 0.23, 45.0)}


def sign_p(k, n):
    """One-sided sign test: P(X >= k) for X ~ Binomial(n, 0.5)."""
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n if n else None


def run():
    from cygnss_checks import random_points, wilson
    db = sqlite3.connect(f"file:{REGISTER}?mode=ro", uri=True)
    obs = {}
    for d in DAYS:
        obs[d] = [(m, la, lo, json.loads(c)) for m, la, lo, c in db.execute(
            "SELECT measure, lat, lon, cells FROM observations WHERE family='adsb' AND day=? AND measure IN "
            "('gross','capable') AND lat IS NOT NULL", (d,)).fetchall()]
    report = {"days": DAYS, "register_obs": {d: len(v) for d, v in obs.items()}, "sensors": {}}
    for name, (read, thr, band) in sensors().items():
        grids = {d: read(d) for d in DAYS}
        missing = [d for d, g in grids.items() if g is None]
        cnt = {k: [0, 0] for k in ("gross", "capable", "random_land")}      # [judged, raised]
        per_day = {}
        region_days = defaultdict(set)
        for d in DAYS:
            g = grids[d]
            if g is None:
                continue
            dd = {k: [0, 0] for k in cnt}
            for m, la, lo, cells in obs[d]:
                if abs(la) > band:
                    continue
                vals = [g[c]["score"] for c in cells if c in g]
                if not vals:
                    continue
                for t in (cnt[m], dd[m]):
                    t[0] += 1
                    t[1] += max(vals) >= thr
                if m == "gross":
                    region_days[h3.latlng_to_cell(la, lo, 2)].add(d)
            for la, lo in random_points(d, n=POINTS, band=band, land=True):
                c = h3.latlng_to_cell(la, lo, 2)
                if c in g:
                    for t in (cnt["random_land"], dd["random_land"]):
                        t[0] += 1
                        t[1] += g[c]["score"] >= thr
            per_day[d] = {k: f"{v[1]}/{v[0]}" for k, v in dd.items()}
        share = {k: (v[1] / v[0] if v[0] else None) for k, v in cnt.items()}
        wil = {k: wilson(v[1], v[0]) for k, v in cnt.items()}
        ratio = share["gross"] / share["random_land"] if share["random_land"] else None
        o1 = ("holds" if ratio is not None and ratio >= 2 and wil["gross"][0] > wil["random_land"][1]
              else "fails" if ratio is not None and ratio < 1.5 else "weakened")
        diffs = []
        for r, ds in region_days.items():
            if not (2 <= len(ds) <= 18) or any(r not in grids[d] for d in DAYS if grids[d] is not None) or missing:
                continue
            on = [grids[d][r]["score"] for d in DAYS if d in ds]
            off = [grids[d][r]["score"] for d in DAYS if d not in ds]
            diffs.append(float(np.mean(on) - np.mean(off)))
        nz = [x for x in diffs if x != 0]
        pos = sum(1 for x in nz if x > 0)
        frac = pos / len(nz) if nz else None
        p = sign_p(pos, len(nz))
        o2 = ("holds" if frac is not None and frac >= 0.6 and p < 0.01
              else "fails" if frac is not None and frac <= 0.5 else "weakened")
        report["sensors"][name] = {
            "threshold": thr, "lat_limit": band, "missing_grids": missing,
            "counts": {k: {"judged": v[0], "raised": v[1], "share": None if share[k] is None else round(share[k], 3),
                           "wilson": wil[k]} for k, v in cnt.items()},
            "O1": {"ratio": None if ratio is None else round(ratio, 2), "verdict": o1},
            "O2": {"regions": len(diffs), "positive": pos, "nonzero": len(nz),
                   "share_positive": None if frac is None else round(frac, 3), "sign_p": None if p is None else float(f"{p:.3g}"),
                   "median_diff": round(float(np.median(diffs)), 4) if diffs else None, "verdict": o2},
            "joins_orbit_rx": o1 == "holds" and o2 == "holds", "per_day": per_day}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(report, open(OUT, "w"), indent=1)
    return report


if __name__ == "__main__":
    r = run()
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "per_day"} for k, v in r["sensors"].items()}, indent=1))
