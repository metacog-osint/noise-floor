#!/usr/bin/env python3
"""spoof_heldout.py: score tools/spoof_day.py outputs on the pre-registered held-out checks H1-H6.

  python tools/spoof_heldout.py OUT_DIR [--baseline V05_DIR] [--days ...]

H1-H5 are the checks of docs/validation/spoofing.md ("Held-out test"); H6 (docs/validation/spoofing-v06.md) compares the
number of episodes located in a control box with a baseline output folder made from the same days.

  H1  pooled active share of aircraft-hours in the six control regions                       pass <= 0.01%
  H2  pooled active share in the Middle East and in the Baltic and western Russia groups      each >= 0.2% and >= 20x H1
  H3  episodes confirmed by MLAT, of those MLAT can test                                     >= 75%
  H4  each day's top res-6 spoofed-to cells (top TOP_CELLS) with >= 5 aircraft, share within
      25 km of a named published point (REF_POINTS without '*')                              >= 25%
  H5  eastern Mediterranean: the named point with the most aircraft among those top cells     Beirut, Beirut, Amman on
                                                                                             20 Feb, 20 Jun, 20 Oct 2024
  H6  episodes located in a control box, all classes, against the baseline                   <= 1.5x
"""
import argparse
import gzip
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import spoof_day as S  # noqa: E402

DAYS = ["2024-02-20", "2024-06-20", "2024-10-20", "2025-02-20", "2025-06-20", "2025-10-20", "2026-02-20", "2026-06-20",
        "2025-04-10", "2025-04-20", "2025-05-10", "2025-05-20"]
TOP_CELLS, MIN_AIRCRAFT, NEAR_KM = 6, 5, 25.0
H5_DAYS = {"2024-02-20": "Beirut OLBA", "2024-06-20": "Beirut OLBA", "2024-10-20": "Amman OJAI"}
EAST_MED = ("Beirut OLBA", "Amman OJAI", "Cairo HECA", "Tel Aviv LLBG")


def control_episodes(ev):
    ctl = {n for n, (b, k) in S.REGIONS.items() if k == "control"}
    return [e for e in ev if ({S.region_of(c) for c in e.get("victim_cells") or []} & ctl)]


def score(out_dir, days, baseline=None):
    import pyarrow.parquet as pq
    regs, sm, ev = Counter(), {}, {}
    for d in days:
        for r in pq.read_table(os.path.join(out_dir, f"{d}.hex4.parquet"), columns=["h3", "aircraft", "spoofed_active"]).to_pylist():
            g = S.region_of(r["h3"])
            if g:
                regs[(g, "aircraft")] += r["aircraft"]; regs[(g, "active")] += r["spoofed_active"]
        sm[d] = json.load(open(os.path.join(out_dir, f"{d}.summary.json"), encoding="utf-8"))
        ev[d] = json.load(gzip.open(os.path.join(out_dir, f"{d}.events.json.gz"), "rt", encoding="utf-8"))

    def share(group):
        a = sum(regs[(g, "aircraft")] for g in S.GROUPS[group]); s = sum(regs[(g, "active")] for g in S.GROUPS[group])
        return 100.0 * s / a if a else 0.0, a

    h1, ctl_ah = share("Controls")
    me, _ = share("Middle East")
    ba, _ = share("Baltic and W Russia")
    conf = sum(sm[d]["episodes_mlat_confirmed"] for d in days)
    test = sum(sm[d]["episodes_with_mlat_pairs"] for d in days)
    named = {k: v for k, v in S.REF_POINTS.items() if not k.startswith("*")}
    tops, near, h5 = 0, 0, {}
    for d in days:
        best = None
        for c, la, lo, n in sm[d]["spoofed_to_res6_top"][:TOP_CELLS]:
            if n < MIN_AIRCRAFT:
                continue
            tops += 1
            name, dist = min(((k, S.km(la, lo, *v)) for k, v in named.items()), key=lambda x: x[1])
            near += dist <= NEAR_KM
            if d in H5_DAYS and dist <= NEAR_KM and name in EAST_MED and (best is None or n > best[1]):
                best = (name, n, round(dist))
        if d in H5_DAYS:
            h5[d] = best
    ctl_now = sum(len(control_episodes(ev[d])) for d in days)
    out = {
        "days": len(days), "versions": sorted({sm[d].get("version") for d in days}),
        "H1": {"control_active_pct": round(h1, 4), "control_aircraft_hours": ctl_ah, "pass": h1 <= 0.01},
        "H2": {"middle_east_pct": round(me, 3), "baltic_w_russia_pct": round(ba, 3),
               "x_controls": [round(me / h1, 0) if h1 else None, round(ba / h1, 0) if h1 else None],
               "pass": me >= 0.2 and ba >= 0.2 and (h1 == 0 or (me >= 20 * h1 and ba >= 20 * h1))},
        "H3": {"confirmed": conf, "testable": test, "pct": round(100.0 * conf / test, 1) if test else None,
               "pass": bool(test) and conf / test >= 0.75},
        "H4": {"near_named": near, "top_cells": tops, "pct": round(100.0 * near / tops, 1) if tops else None,
               "pass": bool(tops) and near / tops >= 0.25},
        "H5": {"top_named": {d: v for d, v in h5.items()},
               "pass": all(h5.get(d) and h5[d][0] == want for d, want in H5_DAYS.items() if d in days)},
        "control_episodes": ctl_now,
        "control_episodes_by_class": dict(Counter(e["class"] for d in days for e in control_episodes(ev[d]))),
        "episodes_by_kind": dict(sum((Counter(sm[d].get("episodes_by_kind") or {}) for d in days), Counter())),
    }
    if baseline:
        ctl_base = sum(len(control_episodes(json.load(gzip.open(os.path.join(baseline, f"{d}.events.json.gz"), "rt",
                                                                encoding="utf-8")))) for d in days)
        out["H6"] = {"control_episodes": ctl_now, "baseline": ctl_base,
                     "ratio": round(ctl_now / ctl_base, 2) if ctl_base else None,
                     "pass": ctl_now <= 1.5 * ctl_base}
    return out


def new_control_episodes(out_dir, baseline, days):
    """Control-box episodes in out_dir with no episode of the same aircraft overlapping it in the baseline (local:
    holds ICAO addresses)."""
    rows = []
    for d in days:
        now = control_episodes(json.load(gzip.open(os.path.join(out_dir, f"{d}.events.json.gz"), "rt", encoding="utf-8")))
        base = json.load(gzip.open(os.path.join(baseline, f"{d}.events.json.gz"), "rt", encoding="utf-8"))
        for e in now:
            if not any(b["icao"] == e["icao"] and b["start"] <= e["end"] and b["end"] >= e["start"] for b in base):
                rows.append({"day": d, **{k: e.get(k) for k in ("icao", "type", "cat", "start", "end", "class", "kinds",
                                                                  "alt", "false_lat", "false_lon", "reported_gs",
                                                                  "mlat_pairs", "mlat_dis")},
                             "regions": sorted({S.region_of(c) for c in e.get("victim_cells") or []} - {None})})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out_dir")
    ap.add_argument("--baseline", help="output folder of the version compared against (H6)")
    ap.add_argument("--days", nargs="+", default=DAYS)
    ap.add_argument("--new-controls", help="write the control-box episodes new against the baseline here (local)")
    a = ap.parse_args()
    print(json.dumps(score(a.out_dir, a.days, a.baseline), indent=1))
    if a.new_controls and a.baseline:
        rows = new_control_episodes(a.out_dir, a.baseline, a.days)
        with open(a.new_controls, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=1)
        print(f"{len(rows)} new control-box episodes -> {a.new_controls}")


if __name__ == "__main__":
    main()
