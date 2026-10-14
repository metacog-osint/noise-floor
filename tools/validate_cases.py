#!/usr/bin/env python3
"""validate_cases.py — two event case studies for processor v1.1 (Phase 1.1 validation).

  A. Natural: the 11-12 Nov 2025 geomagnetic storm (GFZ Kp 8.7 at 00-06Z on 12 Nov) over North America.
     Hourly share of 10 m-capable aircraft (reported NACp >= 10 that day) that fell below 10 m, storm night vs the
     previous night, plus 48-hour regional series. Independent replication, on adsb.lol (ODbL) data, of the effect
     John Wiseman showed from his own data (Bluesky, 7 Oct 2026).
  B. Deliberate: 22 Sep 2026 GPS loss over the San Francisco Bay Area and Central Valley, linked in the same thread
     to a Point Mugu NOTAM window (18:30-20:29Z; NOTAM text not independently retrieved: UNVERIFIED).
     Hourly gross-degraded aircraft in the area; Kp <= 1.7 all day, so space weather is ruled out.

Writes docs/validation/cases_results.md and docs/validation/img/case_*.png.
"""
import json, os, sys
from collections import defaultdict

import h3
import pyarrow.parquet as pq

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validate_phase1 import CACHE, ROOT, in_box  # noqa: E402

DAILY = os.path.join(ROOT, "data", "pnt", "daily")
OUT_MD = os.path.join(ROOT, "docs", "validation", "cases_results.md")
IMG = os.path.join(ROOT, "docs", "validation", "img")
ATTR = "Data: adsb.lol (ODbL 1.0) · Basemap: Natural Earth · Method: docs/method-card.md (v1.1)"

NA_REGIONS = {
    "North America northern tier (43–55N, 125W–65W)": (43.0, 55.0, -125.0, -65.0),
    "Control: southern US (25–35N, 110W–80W)": (25.0, 35.0, -110.0, -80.0),
}
BAY = (35.5, 38.5, -123.5, -119.5)   # Bay Area, Central Valley, Santa Cruz-Salinas coast


def hourly(day):
    return pq.read_table(os.path.join(DAILY, f"{day}.hourly.parquet")).to_pylist()


_LL = {}


def ll(cell):
    if cell not in _LL:
        _LL[cell] = h3.cell_to_latlng(cell)
    return _LL[cell]


def region_series(day, box):
    s = [[0, 0, 0, 0] for _ in range(24)]   # [aircraft, gross bad, capable, capable acc-bad]
    for r in hourly(day):
        la, lo = ll(r["h3"])
        if in_box({"lat": la, "lon": lo}, box):
            a = s[r["hour"]]; a[0] += r["aircraft"]; a[1] += r["bad_nacp"]; a[2] += r["capable"]; a[3] += r["cap_bad_acc10"]
    return s


def pct(a, b):
    return 100 * a / b if b >= 20 else float("nan")


def basemap(ax, x0, x1, y0, y1):
    land = json.load(open(os.path.join(CACHE, "ne_50m_land.geojson"), encoding="utf-8"))
    for f in land["features"]:
        g = f["geometry"]; polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for p in polys:
            xs, ys = zip(*p[0])
            if max(xs) < x0 - 10 or min(xs) > x1 + 10 or max(ys) < y0 - 10 or min(ys) > y1 + 10:
                continue
            ax.fill(xs, ys, color="#2b2b33", lw=0, zorder=0)
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_xticks([]); ax.set_yticks([]); ax.set_facecolor("#15151b")


def storm_maps(storm_day, control_day, hours):
    """Small multiples like Wiseman's figure: H3 res-3 cells, share of capable aircraft below 10 m."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    from matplotlib import cm, colors
    x0, x1, y0, y1 = -135, -55, 22, 62
    norm = colors.Normalize(0, 60); cmap = matplotlib.colormaps["magma"]
    fig, axes = plt.subplots(2, len(hours), figsize=(3.1 * len(hours), 5.2), dpi=110)
    for row, day in enumerate((control_day, storm_day)):
        cells = defaultdict(lambda: defaultdict(lambda: [0, 0]))   # hour -> res-3 parent -> [capable, bad]
        for r in hourly(day):
            if r["hour"] in hours:
                la, lo = ll(r["h3"])
                if x0 - 5 <= lo <= x1 + 5 and y0 - 5 <= la <= y1 + 5:
                    c = cells[r["hour"]][h3.cell_to_parent(r["h3"], 3)]; c[0] += r["capable"]; c[1] += r["cap_bad_acc10"]
        for j, hr in enumerate(hours):
            ax = axes[row][j]; basemap(ax, x0, x1, y0, y1)
            polys, fc = [], []
            for cell, (n, b) in cells[hr].items():
                if n < 3:
                    continue
                polys.append([(lo, la) for la, lo in h3.cell_to_boundary(cell)]); fc.append(cmap(norm(100 * b / n)))
            ax.add_collection(PolyCollection(polys, facecolors=fc, edgecolors="none", zorder=1))
            ax.set_title(f"{day[5:]} {hr:02d}Z" + (" (control)" if row == 0 else ""), fontsize=9, color="#ddd")
    sm = cm.ScalarMappable(norm=norm, cmap=cmap)
    cb = fig.colorbar(sm, ax=axes, fraction=0.015, pad=0.01); cb.set_label("% of 10 m-capable aircraft below 10 m", color="#ddd")
    cb.ax.yaxis.set_tick_params(color="#ddd"); plt.setp(cb.ax.get_yticklabels(), color="#ddd")
    fig.patch.set_facecolor("#15151b")
    fig.suptitle(f"Geomagnetic storm {storm_day} (GFZ Kp 8.7 at 00–06Z) vs the previous night · H3 res-3 cells with ≥ 3 capable aircraft\n{ATTR}",
                 color="#ddd", fontsize=10)
    path = os.path.join(IMG, f"case_storm_{storm_day}_maps.png")
    fig.savefig(path, bbox_inches="tight", facecolor=fig.get_facecolor()); plt.close(fig)
    return os.path.basename(path)


def storm_series(days, quiet_days):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, len(NA_REGIONS), figsize=(14, 6.5), dpi=110, sharex=True)
    md = []
    for j, (name, box) in enumerate(NA_REGIONS.items()):
        ser = [h for d in days for h in region_series(d, box)]
        base = [region_series(d, box) for d in quiet_days]
        base48 = [[sum(b[h][k] for b in base) for k in range(4)] for h in range(24)] * len(days)
        for i, (num, den, label) in enumerate(((3, 2, "10 m-capable aircraft below 10 m"), (1, 0, "aircraft worse than 93 m (NACp < 8)"))):
            ax = axes[i][j]
            ax.plot(range(len(ser)), [pct(h[num], h[den]) for h in ser], color="#c0392b", lw=2, label=" + ".join(days))
            ax.plot(range(len(ser)), [pct(h[num], h[den]) for h in base48], color="#7f8c8d", lw=1.2, ls="--",
                    label=f"quiet-day baseline ({', '.join(quiet_days)})")
            ax.axvspan(24, 30, color="#c0392b", alpha=0.08)
            ax.set_xticks(range(0, len(ser) + 1, 6)); ax.set_xticklabels([f"{h % 24:02d}Z" for h in range(0, len(ser) + 1, 6)])
            ax.set_title(f"{name}\n{label}", fontsize=9); ax.grid(alpha=0.3)
            if j == 0:
                ax.set_ylabel("%")
        axes[0][0].legend(fontsize=8)
        win = ser[24:30]; bwin = base48[24:30]
        md.append(f"| {name} | {pct(sum(h[3] for h in win), sum(h[2] for h in win)):.1f} | {pct(sum(h[3] for h in bwin), sum(h[2] for h in bwin)):.1f} "
                  f"| {pct(sum(h[1] for h in win), sum(h[0] for h in win)):.2f} | {pct(sum(h[1] for h in bwin), sum(h[0] for h in bwin)):.2f} |")
    fig.suptitle(f"Hourly, {days[0]} 00Z to {days[-1]} 23Z (shaded: 00–06Z on {days[-1]}, Kp 8.7) · hours with ≥ 20 aircraft · {ATTR}", fontsize=9)
    fig.tight_layout()
    path = os.path.join(IMG, "case_storm_series.png")
    fig.savefig(path, bbox_inches="tight"); plt.close(fig)
    return os.path.basename(path), md


def bay_case(day):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    s = region_series(day, BAY)
    fig, ax = plt.subplots(figsize=(10, 4.2), dpi=110)
    hrs = list(range(24))
    ax.bar(hrs, [h[1] for h in s], color="#e67e22", label="aircraft-hexes worse than 93 m (NACp < 8)")
    ax2 = ax.twinx(); ax2.plot(hrs, [pct(h[1], h[0]) for h in s], color="#2c3e50", marker=".", label="share of aircraft-hexes (%)")
    ax.axvspan(18.5, 20.5, color="#8e44ad", alpha=0.12, label="Point Mugu NOTAM window 18:30–20:29Z (per Wiseman; UNVERIFIED)")
    ax.set_xticks(range(0, 24, 2)); ax.set_xlabel("UTC hour (bar at hour h covers h:00–h:59)"); ax.set_ylabel("aircraft-hexes"); ax2.set_ylabel("%")
    ax.set_title(f"{day}: Bay Area and Central Valley (35.5–38.5N, 123.5–119.5W), hourly · GFZ Kp ≤ 1.7 all day · {ATTR}", fontsize=8.5)
    h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels(); ax.legend(h1 + h2, l1 + l2, fontsize=8, loc="upper left")
    path = os.path.join(IMG, f"case_bay_{day}.png")
    fig.savefig(path, bbox_inches="tight"); plt.close(fig)
    rows = ["| UTC hour | Aircraft-hexes | Worse than 93 m | Share % | Capable below 10 m % |", "|---|---|---|---|---|"]
    for h in range(14, 24):
        a = s[h]
        rows.append(f"| {h:02d} | {a[0]} | {a[1]} | {pct(a[1], a[0]):.1f} | {pct(a[3], a[2]):.1f} |")
    return os.path.basename(path), rows


def main():
    os.makedirs(IMG, exist_ok=True)
    maps = storm_maps("2025-11-12", "2025-11-11", [0, 1, 2, 3, 4, 5])
    series, srows = storm_series(["2025-11-11", "2025-11-12"], ["2025-10-16", "2025-10-22"])
    bay, brows = bay_case("2026-09-22")
    md = ["# Event case studies: generated results", "", "Generated by `tools/validate_cases.py`. Narrative and verdicts: `phase1.md` (Phase 1.1 section).", "",
          "## A. Geomagnetic storm, 11–12 Nov 2025 (GFZ Kp 8.7 at 00–06Z on 12 Nov)", "",
          "Storm window 00–06Z on 12 Nov, against the same hours on the quiet-day baseline (16 and 22 Oct 2025).", "",
          "| Region | Capable below 10 m, storm % | Baseline % | Worse than 93 m, storm % | Baseline % |", "|---|---|---|---|---|", *srows, "",
          f"![Storm maps](img/{maps})", "", f"![Storm series](img/{series})", "",
          "## B. Bay Area GPS loss, 22 Sep 2026 (GFZ Kp ≤ 1.7 all day)", "", *brows, "", f"![Bay Area](img/{bay})"]
    open(OUT_MD, "w", encoding="utf-8").write("\n".join(md) + "\n")
    print(f"wrote {OUT_MD}")


if __name__ == "__main__":
    main()
