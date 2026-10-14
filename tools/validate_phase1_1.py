#!/usr/bin/env python3
"""validate_phase1_1.py — tables and figures for the Phase 1.1 validation (processor v1.1).

  1. v1 vs v1.1 on the hotspot sub-regions (effect of the peer-based avionics-suspect rule)
  2. Storm test, hourly: share of aircraft worse than 10 m (NACp < 10) and worse than 93 m (NACp < 8) by UTC hour,
     storm day vs the two quiet days, in high-latitude regions and a low-latitude control
  3. Coverage: aircraft per hex, to set the minimum aircraft count for colouring public maps

Writes docs/validation/phase1_1_results.md and docs/validation/img/phase1_1_*.png.

Usage
  python tools/validate_phase1_1.py 2025-10-16 2025-10-18 2025-10-22 --storm 2025-10-18 --storm-hours 18-21
"""
import argparse, json, os, sys

import h3
import pyarrow.parquet as pq

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validate_phase1 import CACHE, ROOT, SUBREGIONS, in_box  # noqa: E402

DAILY = os.path.join(ROOT, "data", "pnt", "daily")
DAILY_V1 = os.path.join(ROOT, "data", "pnt", "daily_v1")
OUT_MD = os.path.join(ROOT, "docs", "validation", "phase1_1_results.md")
IMG = os.path.join(ROOT, "docs", "validation", "img")
MIN_AC = 10

# High-latitude regions away from the known hotspots, plus a low-latitude control (lat_min, lat_max, lon_min, lon_max)
STORM_REGIONS = {
    "Northern Europe (56–72N, 10W–15E)": (56.0, 72.0, -10.0, 15.0),
    "North America northern tier (43–55N, 125W–65W)": (43.0, 55.0, -125.0, -65.0),
    "Control: southern US (25–35N, 110W–80W)": (25.0, 35.0, -110.0, -80.0),
}


def share(rows, k):
    ac = sum(r["aircraft"] for r in rows)
    return (100 * sum(r[k] for r in rows) / ac if ac else None), ac


def sub_table(days):
    md = ["## 1. v1 vs v1.1 on the hotspots (share of aircraft with NACp < 8)", "",
          "| Sub-region | " + " | ".join(f"{d} v1 → v1.1" for d in days) + " |", "|---|" + "---|" * len(days)]
    v1 = {d: pq.read_table(os.path.join(DAILY_V1, f"{d}.parquet")).to_pylist() for d in days}
    v11 = {d: pq.read_table(os.path.join(DAILY, f"{d}.parquet")).to_pylist() for d in days}
    for name, box in SUBREGIONS.items():
        cells = []
        for d in days:
            a, _ = share([r for r in v1[d] if in_box(r, box)], "bad_nacp")
            b, _ = share([r for r in v11[d] if in_box(r, box)], "bad_nacp")
            cells.append(f"{a:.1f} → {b:.1f}" if a is not None and b is not None else "no data")
        md.append(f"| {name} | " + " | ".join(cells) + " |")
    md += ["", "| Day | Suspects v1 | Suspects v1.1 | v1.1 suspects centred in a hotspot sub-region |", "|---|---|---|---|"]
    hot = {k: v for k, v in SUBREGIONS.items() if not k.startswith(("Cyprus", "High latitude"))}
    for d in days:
        s1 = json.load(open(os.path.join(DAILY_V1, f"{d}.summary.json")))["avionics_suspects"]
        s = json.load(open(os.path.join(DAILY, f"{d}.summary.json")))
        inhot = sum(1 for la, lo, *_ in s["avionics_suspect_centroids"] if any(in_box({"lat": la, "lon": lo}, b) for b in hot.values()))
        md.append(f"| {d} | {s1} | {s['avionics_suspects']} | {inhot} |")
    return md


def hourly_series(day):
    rows = pq.read_table(os.path.join(DAILY, f"{day}.hourly.parquet")).to_pylist()
    ll = {}
    # [aircraft, acc bad, gross bad, capable aircraft, capable acc bad]
    out = {name: [[0, 0, 0, 0, 0] for _ in range(24)] for name in STORM_REGIONS}
    for r in rows:
        if r["h3"] not in ll:
            ll[r["h3"]] = h3.cell_to_latlng(r["h3"])
        la, lo = ll[r["h3"]]
        for name, box in STORM_REGIONS.items():
            if in_box({"lat": la, "lon": lo}, box):
                a = out[name][r["hour"]]
                a[0] += r["aircraft"]; a[1] += r["bad_acc10"]; a[2] += r["bad_nacp"]; a[3] += r["capable"]; a[4] += r["cap_bad_acc10"]
    return out


def storm(days, storm_day, h0, h1):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    series = {d: hourly_series(d) for d in days}
    measures = ((4, 3, "10 m-capable aircraft below 10 m"), (1, 0, "all aircraft worse than 10 m (NACp < 10)"),
                (2, 0, "worse than 93 m (NACp < 8)"))
    fig, axes = plt.subplots(len(measures), len(STORM_REGIONS), figsize=(15, 10), dpi=110, sharex=True)
    md = ["", f"## 2. Storm test: {storm_day}, Kp ≥ 6 window {h0:02d}–{h1:02d}Z, against the same hours on the quiet days", "",
          "Share of aircraft (aircraft-hex-hour weighted) by threshold, mean over the window.", "",
          "| Region | Threshold | " + " | ".join(days) + " |", "|---|---|" + "---|" * len(days)]
    for j, (name, _) in enumerate(STORM_REGIONS.items()):
        for i, (k, den, label) in enumerate(measures):
            ax = axes[i][j]
            vals = []
            for d in days:
                s = series[d][name]
                y = [100 * h[k] / h[den] if h[den] >= 20 else None for h in s]
                ax.plot(range(24), [v if v is not None else float("nan") for v in y], marker=".",
                        lw=2.2 if d == storm_day else 1.2, color="#c0392b" if d == storm_day else None,
                        label=d + (" (storm)" if d == storm_day else ""))
                win = [s[h] for h in range(h0, h1)]
                ac = sum(w[den] for w in win)
                vals.append(f"{100 * sum(w[k] for w in win) / ac:.2f}" if ac else "–")
            ax.axvspan(h0, h1, color="#c0392b", alpha=0.08)
            ax.set_title(f"{name}\n{label}", fontsize=9)
            ax.set_xticks(range(0, 24, 3)); ax.grid(alpha=0.3)
            if j == 0:
                ax.set_ylabel("% of aircraft")
            md.append(f"| {name} | {label} | " + " | ".join(vals) + " |")
    axes[-1][0].set_xlabel("UTC hour"); axes[0][0].legend(fontsize=8)
    fig.suptitle(f"Hourly GNSS accuracy, storm day {storm_day} (shaded: Kp ≥ 6) vs quiet days · hours with ≥ 20 aircraft · Data: adsb.lol (ODbL 1.0)", fontsize=10)
    fig.tight_layout()
    path = os.path.join(IMG, "phase1_1_storm_hourly.png")
    fig.savefig(path, bbox_inches="tight"); plt.close(fig)
    md += ["", "![Storm test, hourly](img/phase1_1_storm_hourly.png)"]
    return md


def coverage(day):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    rows = pq.read_table(os.path.join(DAILY, f"{day}.parquet")).to_pylist()
    bins = [(1, 2), (3, 4), (5, 9), (10, 49), (50, 10**9)]
    counts = {b: sum(1 for r in rows if b[0] <= r["aircraft"] <= b[1]) for b in bins}
    cols = {(1, 2): "#d9d9d9", (3, 4): "#bdbdbd", (5, 9): "#9ecae1", (10, 49): "#4292c6", (50, 10**9): "#08306b"}
    fig, ax = plt.subplots(figsize=(14, 7.5), dpi=110)
    land = json.load(open(os.path.join(CACHE, "ne_50m_land.geojson"), encoding="utf-8"))
    for f in land["features"]:
        g = f["geometry"]; polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for p in polys:
            xs, ys = zip(*p[0]); ax.fill(xs, ys, color="#f2f0eb", lw=0, zorder=0)
    polys, fc = [], []
    for r in rows:
        b = [(lo, la) for la, lo in h3.cell_to_boundary(r["h3"])]
        if max(p[0] for p in b) - min(p[0] for p in b) > 180:
            continue
        polys.append(b); fc.append(next(c for (lo, hi), c in cols.items() if lo <= r["aircraft"] <= hi))
    ax.add_collection(PolyCollection(polys, facecolors=fc, edgecolors="none", zorder=1))
    ax.set_xlim(-180, 180); ax.set_ylim(-60, 80); ax.set_xticks([]); ax.set_yticks([])
    ax.set_title(f"adsb.lol coverage, {day}: aircraft per H3 res-4 hex (kept reports)", fontsize=11)
    ax.text(0.005, 0.005, "1–2 · 3–4 · 5–9 · 10–49 · 50+ aircraft (light grey to dark blue)  ·  Data: adsb.lol (ODbL 1.0)  ·  Basemap: Natural Earth",
            transform=ax.transAxes, fontsize=8, color="#444")
    path = os.path.join(IMG, f"phase1_1_coverage_{day}.png")
    fig.savefig(path, bbox_inches="tight"); plt.close(fig)
    total = len(rows)
    md = ["", f"## 3. Coverage, {day}", "", "| Aircraft per hex | Hexes | Share |", "|---|---|---|"]
    for b, n in counts.items():
        md.append(f"| {b[0]}–{b[1] if b[1] < 10**9 else '+'} | {n:,} | {100 * n / total:.1f}% |")
    md += ["", f"![Coverage {day}](img/phase1_1_coverage_{day}.png)"]
    return md


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("days", nargs="+")
    ap.add_argument("--storm", required=True)
    ap.add_argument("--storm-hours", default="18-21")
    a = ap.parse_args()
    h0, h1 = (int(x) for x in a.storm_hours.split("-"))
    os.makedirs(IMG, exist_ok=True)
    md = ["# Phase 1.1 validation: generated results", "",
          f"Generated by `tools/validate_phase1_1.py` for {', '.join(a.days)}. Narrative and verdicts: `phase1.md` (Phase 1.1 section).", ""]
    md += sub_table(a.days) + storm(a.days, a.storm, h0, h1) + coverage(a.days[0])
    open(OUT_MD, "w", encoding="utf-8").write("\n".join(md) + "\n")
    print(f"wrote {OUT_MD}")


if __name__ == "__main__":
    main()
