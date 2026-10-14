#!/usr/bin/env python3
"""validate_phase1_2.py — Phase 1.2 validation: SBAS flag, minute bursts, same-hour baselines.

Run pipeline/pnt_analysis.py for the days first. Writes docs/validation/phase1_2_results.md and img/phase1_2_*.png.

Usage
  python tools/validate_phase1_2.py --sbas 2025-10-09:2025-10-25 --bay 2026-09-22 --anom 2025-10-23:2025-10-25 --bursts 2025-10-09:2025-10-25
"""
import argparse, json, os, sys
from collections import Counter
from datetime import date, timedelta

import h3
import pyarrow.parquet as pq

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validate_phase1 import ROOT, country  # noqa: E402

DAILY = os.path.join(ROOT, "data", "pnt", "daily")
AN = os.path.join(ROOT, "data", "pnt", "analysis")
OUT_MD = os.path.join(ROOT, "docs", "validation", "phase1_2_results.md")
IMG = os.path.join(ROOT, "docs", "validation", "img")
BAY = (35.5, 38.5, -123.5, -119.5)
ATTR = "Data: adsb.lol (ODbL 1.0) · Method: docs/method-card.md (v1.2)"


def days(spec):
    a, b = (date.fromisoformat(x) for x in spec.split(":")) if ":" in spec else (date.fromisoformat(spec),) * 2
    while a <= b:
        yield a.isoformat(); a += timedelta(days=1)


def load(day, kind):
    p = os.path.join(AN, f"{day}.{kind}.json")
    return json.load(open(p)) if os.path.exists(p) else None


def sbas_section(ds):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    areas = None; grid = []
    for d in ds:
        sb = load(d, "sbas")
        if not sb:
            continue
        areas = areas or list(sb["areas"])
        grid.append((d, sb))
    md = ["## 1. SBAS service flag (area-wide share of 10 m-capable aircraft below 10 m)", "",
          "Outage ≥ 60%, degraded ≥ 35%, over ≥ 200 capable aircraft-hex-hours in the hour. Kp ≥ 5 labels the hour as storm.", "",
          "| Day | " + " | ".join(areas) + " |", "|---|" + "---|" * len(areas)]
    for d, sb in grid:
        cells = []
        for a in areas:
            hrs = [h for h in sb["areas"][a]["hours"] if h and not h["state"].startswith("ok")]
            if not hrs:
                cells.append("–"); continue
            kinds = Counter(h["state"].split(" (")[0] + (" storm" if "storm" in h["state"] else "") for h in hrs)
            cells.append(f"{len(hrs)} h: " + ", ".join(f"{k} {v}" for k, v in kinds.items()) + f" ({hrs[0]['hour']:02d}–{hrs[-1]['hour']:02d}Z)")
        md.append(f"| {d} | " + " | ".join(cells) + " |")
    # EGNOS share timeline
    fig, ax = plt.subplots(figsize=(14, 3.6), dpi=110)
    xs, ys, lab = [], [], []
    for i, (d, sb) in enumerate(grid):
        for h in sb["areas"]["EGNOS (Europe)"]["hours"]:
            if h:
                xs.append(i * 24 + h["hour"]); ys.append(h["share"])
        lab.append(d[5:])
    ax.plot(xs, ys, color="#2c3e50", lw=1)
    ax.axhline(60, color="#c0392b", ls="--", lw=1); ax.axhline(35, color="#e67e22", ls=":", lw=1)
    ax.set_xticks([i * 24 for i in range(len(grid))]); ax.set_xticklabels(lab, fontsize=8)
    ax.set_ylabel("% capable below 10 m"); ax.grid(alpha=0.3)
    ax.set_title(f"EGNOS service area, hourly (dashed: outage 60%, dotted: degraded 35%) · {ATTR}", fontsize=9)
    fig.savefig(os.path.join(IMG, "phase1_2_egnos_timeline.png"), bbox_inches="tight"); plt.close(fig)
    md += ["", "![EGNOS timeline](img/phase1_2_egnos_timeline.png)"]
    return md


def bay_section(day):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    rows = pq.read_table(os.path.join(DAILY, f"{day}.minute.parquet")).to_pylist()
    s = [0] * 1440
    for r in rows:
        la, lo = h3.cell_to_latlng(r["h3"])
        if BAY[0] <= la <= BAY[1] and BAY[2] <= lo <= BAY[3]:
            s[r["minute"]] += r["bad_nacp"]
    fig, ax = plt.subplots(figsize=(12, 4), dpi=110)
    lo_, hi_ = 16 * 60, 22 * 60
    ax.fill_between(range(lo_, hi_), s[lo_:hi_], step="mid", color="#e67e22", alpha=0.8)
    ax.axvspan(18 * 60 + 30, 20 * 60 + 30, color="#8e44ad", alpha=0.12, label="Point Mugu NOTAM window 18:30–20:29Z (per Wiseman; UNVERIFIED)")
    ax.set_xticks(range(lo_, hi_ + 1, 30)); ax.set_xticklabels([f"{m // 60:02d}:{m % 60:02d}" for m in range(lo_, hi_ + 1, 30)], fontsize=8)
    ax.set_ylabel("aircraft with a report worse than 93 m"); ax.legend(fontsize=8, loc="upper left"); ax.grid(alpha=0.3)
    ax.set_title(f"{day}, Bay Area and Central Valley (35.5–38.5N, 123.5–119.5W), per minute, aircraft ≥ 1,000 ft · {ATTR}", fontsize=9)
    fig.savefig(os.path.join(IMG, f"phase1_2_bay_minutes_{day}.png"), bbox_inches="tight"); plt.close(fig)
    win = s[lo_:hi_]
    peaks = sorted(range(lo_, hi_), key=lambda m: -s[m])[:5]
    bu = load(day, "bursts") or {"events": []}
    near = [e for e in bu.get("events", []) if BAY[0] - 2 <= e["lat"] <= BAY[1] + 2 and BAY[2] - 2 <= e["lon"] <= BAY[3] + 2]
    md = ["", f"## 2. Minute bursts: Bay Area, {day}", "",
          f"Median per minute 16–22Z in the box: {sorted(win)[len(win) // 2]} aircraft; peak minutes: " +
          ", ".join(f"{m // 60:02d}:{m % 60:02d}Z ({s[m]})" for m in sorted(peaks)), "",
          "Burst events detected by `pnt_analysis.py` near the area (res-2 cells and res-2 neighbourhoods, merged):", "",
          "| Start | End | Peak aircraft | Centre | Detections | Threshold basis |", "|---|---|---|---|---|---|"]
    for e in sorted(near, key=lambda e: e["start"]):
        md.append(f"| {e['start']} | {e['end']} | {e['peak_aircraft']} | {e['lat']}, {e['lon']} | {e['detections']} | {e['basis']} |")
    md += ["", f"![Bay Area minutes](img/phase1_2_bay_minutes_{day}.png)"]
    return md


def anom_section(ds):
    md = ["", "## 3. Same-hour baseline anomaly events (H3 res-2 regions, previous 14 days)", "",
          "Adjacent anomalous region-hours on one measure form an event. Tiers by peak excess over the baseline median: "
          "major ≥ 25 points, notable ≥ 10, minor below.", ""]
    for d in ds:
        an = load(d, "anomalies")
        if not an:
            continue
        if "error" in an:
            md += [f"**{d}:** {an['error']}", ""]; continue
        ev = an.get("events", [])
        tiers = Counter(e["tier"] for e in ev)
        md += [f"### {d}: {len(ev)} events (major {tiers.get('major', 0)}, notable {tiers.get('notable', 0)}, minor {tiers.get('minor', 0)}) "
               f"from {len(an['anomalies'])} region-hours; baseline {an['baseline_days'][-1]} to {an['baseline_days'][0]}", "",
               "| Tier | Measure | Hours (UTC) | Region-hours | Peak share % | Excess (pts) | Centre | Country |", "|---|---|---|---|---|---|---|---|"]
        for e in [e for e in ev if e["tier"] == "major"][:12]:
            md.append(f"| {e['tier']} | {e['measure']} | {e['start_hour']:02d}–{e['end_hour']:02d} | {e['region_hours']} | {e['peak_share']} | "
                      f"+{e['peak_excess']} | {e['lat']}, {e['lon']} | {country(e['lat'], e['lon'])} |")
        md.append("")
    return md


def bursts_section(ds):
    md = ["", "## 4. Minute-burst events by day (largest three)", "", "| Day | Events | Largest (start–end, peak aircraft, centre, country, basis) |", "|---|---|---|"]
    for d in ds:
        bu = load(d, "bursts")
        if not bu or "events" not in bu:
            continue
        top = bu["events"][:3]
        md.append(f"| {d} | {len(bu['events'])} | " + "; ".join(
            f"{e['start']}–{e['end']}, {e['peak_aircraft']}, {e['lat']},{e['lon']} ({country(e['lat'], e['lon'])})" for e in top)
            + (f" · {top[0]['basis']}" if top else "") + " |")
    return md


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sbas", required=True); ap.add_argument("--bay", required=True)
    ap.add_argument("--anom", required=True); ap.add_argument("--bursts", required=True)
    a = ap.parse_args()
    os.makedirs(IMG, exist_ok=True)
    md = ["# Phase 1.2 validation: generated results", "", "Generated by `tools/validate_phase1_2.py`. Narrative and verdicts: `phase1.md` (Phase 1.2 section).", ""]
    md += sbas_section(list(days(a.sbas))) + bay_section(a.bay) + anom_section(list(days(a.anom))) + bursts_section(list(days(a.bursts)))
    open(OUT_MD, "w", encoding="utf-8").write("\n".join(md) + "\n")
    print(f"wrote {OUT_MD}")


if __name__ == "__main__":
    main()
