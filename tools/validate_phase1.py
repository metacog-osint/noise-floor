#!/usr/bin/env python3
"""validate_phase1.py — tables and maps for the Phase 1 validation report.

Reads data/pnt/daily/<day>.parquet for each test day and writes:
  docs/validation/phase1_results.md         generated tables (regions, latitude bands, top hexes)
  docs/validation/img/phase1_<day>_<view>.png   maps in GPSJam's colour bins, for side-by-side visual comparison

Regions are broad validation boxes around published hotspots plus controls, not watch areas.
Basemap: Natural Earth 50m (public domain), cached in data/cache/.

Usage
  python tools/validate_phase1.py 2025-10-16 2025-10-18 2025-10-22
"""
import json, os, sys

import h3
import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY = os.path.join(ROOT, "data", "pnt", "daily")
CACHE = os.path.join(ROOT, "data", "cache")
OUT_MD = os.path.join(ROOT, "docs", "validation", "phase1_results.md")
IMG = os.path.join(ROOT, "docs", "validation", "img")
MIN_AC = 10   # aircraft per hex before a hex counts in "red hexes" and top lists

# (lat_min, lat_max, lon_min, lon_max). Hotspot boxes match emso-watch's GPSJam regions; controls are expected quiet.
REGIONS = {
    "Baltic": (53.5, 61.0, 17.0, 30.0),
    "Black Sea": (40.5, 47.5, 27.0, 42.0),
    "Eastern Mediterranean": (31.0, 37.0, 29.0, 36.5),
    "Persian Gulf": (23.0, 30.5, 47.0, 57.0),
    "Control: central Europe": (47.0, 52.0, 5.0, 15.0),
    "Control: US Midwest": (37.0, 45.0, -100.0, -85.0),
    # high-latitude control for space weather; northern Canada had no adsb.lol coverage on the test days
    "Control: western Norway (high latitude)": (60.0, 68.0, 5.0, 16.0),
}
# Tighter boxes inside and around the hotspots, plus a high-latitude control that excludes the Baltic/Russia hotspots
SUBREGIONS = {
    "Kaliningrad and approaches": (54.0, 55.6, 19.0, 23.0),
    "Gulf of Finland / Estonia–Russia border": (58.5, 60.5, 24.0, 32.0),
    "Southern Black Sea offshore Turkey": (41.3, 42.5, 34.0, 41.0),
    "Western Black Sea coast": (42.0, 45.5, 27.0, 30.0),
    "Caucasus": (40.0, 43.5, 41.0, 49.0),
    "Cyprus–Levant": (32.0, 36.0, 32.0, 36.5),
    "High latitude excl. Baltic/Russia": (60.0, 72.0, -30.0, 20.0),
}
BANDS = [(0, 30), (30, 50), (50, 60), (60, 90)]
VIEWS = {"world": (-180, 180, -60, 80), "europe_me": (-15, 62, 22, 72)}


def load(day):
    return pq.read_table(os.path.join(DAILY, f"{day}.parquet")).to_pylist()


def summary(day):
    return json.load(open(os.path.join(DAILY, f"{day}.summary.json")))


def in_box(r, b):
    return b[0] <= r["lat"] <= b[1] and b[2] <= r["lon"] <= b[3]


def agg(rows):
    ac = sum(r["aircraft"] for r in rows); bad = sum(r["bad_nacp"] for r in rows)
    red = sum(1 for r in rows if r["aircraft"] >= MIN_AC and r["score"] > 10)
    big = sum(1 for r in rows if r["aircraft"] >= MIN_AC)
    return ac, (100 * bad / ac if ac else None), red, big


# ---- country labels: point-in-polygon on Natural Earth countries (matplotlib Path; no shapely needed) ----
_COUNTRIES = None


def country(lat, lon):
    global _COUNTRIES
    from matplotlib.path import Path
    if _COUNTRIES is None:
        gj = json.load(open(os.path.join(CACHE, "ne_50m_admin_0_countries.geojson"), encoding="utf-8"))
        _COUNTRIES = []
        for f in gj["features"]:
            g = f["geometry"]; polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
            _COUNTRIES.append((f["properties"].get("NAME") or f["properties"].get("ADMIN"), [Path(p[0]) for p in polys]))
    for name, paths in _COUNTRIES:
        if any(p.contains_point((lon, lat)) for p in paths):
            return name
    return "sea / unknown"


def color(score):
    return "#d7301f" if score > 10 else "#fdae3b" if score >= 2 else "#41ab5d"   # GPSJam bins: >10 red, 2-10 yellow


def draw(day, rows, view):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    x0, x1, y0, y1 = VIEWS[view]
    fig, ax = plt.subplots(figsize=(14, 7.5) if view == "world" else (11, 9), dpi=110)
    land = json.load(open(os.path.join(CACHE, "ne_50m_land.geojson"), encoding="utf-8"))
    for f in land["features"]:
        g = f["geometry"]; polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for p in polys:
            xs, ys = zip(*p[0]); ax.fill(xs, ys, color="#eceae4", lw=0, zorder=0)
    polys, cols = [], []
    for r in rows:
        if r["aircraft"] < 3 or not (x0 - 5 <= r["lon"] <= x1 + 5 and y0 - 5 <= r["lat"] <= y1 + 5):
            continue
        b = [(lo, la) for la, lo in h3.cell_to_boundary(r["h3"])]
        if max(p[0] for p in b) - min(p[0] for p in b) > 180:
            continue  # skip antimeridian-crossing cells
        polys.append(b); cols.append(color(r["score"]))
    ax.add_collection(PolyCollection(polys, facecolors=cols, edgecolors="none", alpha=0.85, zorder=1))
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect(1.0 if view == "world" else 1.6)
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title(f"GNSS degradation from ADS-B, {day} (UTC day) — share of aircraft with NACp < 8, H3 res 4", fontsize=11)
    ax.text(0.005, 0.005, "Green < 2 %  ·  Yellow 2–10 %  ·  Red > 10 %  ·  hexes with ≥ 3 aircraft\n"
            "Data: adsb.lol (ODbL 1.0)  ·  Basemap: Natural Earth  ·  Method: docs/method-card.md (v1)",
            transform=ax.transAxes, fontsize=8, va="bottom", color="#444")
    os.makedirs(IMG, exist_ok=True)
    path = os.path.join(IMG, f"phase1_{day}_{view}.png")
    fig.savefig(path, bbox_inches="tight"); plt.close(fig)
    return os.path.relpath(path, os.path.dirname(OUT_MD)).replace("\\", "/")


def main():
    days = sys.argv[1:]
    data = {d: load(d) for d in days}
    sums = {d: summary(d) for d in days}
    md = ["# Phase 1 validation: generated results", "",
          f"Generated by `tools/validate_phase1.py` for {', '.join(days)}. Narrative and verdicts: `phase1.md`.", "",
          "## Runs", "", "| Day | Seconds | Trace files | Aircraft | Avionics suspects | Hexes | Reports used |", "|---|---|---|---|---|---|---|"]
    for d in days:
        s = sums[d]
        md.append(f"| {d} | {s['seconds']} | {s['files']:,} | {s['aircraft']:,} | {s['avionics_suspects']} | {s['hexes']:,} | {s['reports_used']:,} |")
    md += ["", f"## Regions (aircraft-hex weighted share with NACp < 8; red = hexes with ≥ {MIN_AC} aircraft and score > 10)", "",
           "| Region | " + " | ".join(f"{d} share % (red / hexes ≥{MIN_AC})" for d in days) + " |", "|---|" + "---|" * len(days)]
    for name, box in REGIONS.items():
        cells = []
        for d in days:
            ac, share, red, big = agg([r for r in data[d] if in_box(r, box)])
            cells.append(f"{share:.1f} ({red} / {big})" if share is not None else "no data")
        md.append(f"| {name} | " + " | ".join(cells) + " |")
    md += ["", "## Sub-regions (same metrics)", "",
           "| Sub-region (lat, lon box) | " + " | ".join(f"{d} share % (red / hexes ≥{MIN_AC})" for d in days) + " |", "|---|" + "---|" * len(days)]
    for name, box in SUBREGIONS.items():
        cells = []
        for d in days:
            ac, share, red, big = agg([r for r in data[d] if in_box(r, box)])
            cells.append(f"{share:.1f} ({red} / {big})" if share is not None else "no data")
        md.append(f"| {name} ({box[0]}–{box[1]}N, {box[2]}–{box[3]}E) | " + " | ".join(cells) + " |")
    md += ["", "## Latitude bands (all hexes; both hemispheres)", "", "| |abs lat| band | " + " | ".join(f"{d} share %" for d in days) + " |",
           "|---|" + "---|" * len(days)]
    for lo, hi in BANDS:
        cells = []
        for d in days:
            ac, share, _, _ = agg([r for r in data[d] if lo <= abs(r["lat"]) < hi])
            cells.append(f"{share:.2f}" if share is not None else "–")
        md.append(f"| {lo}–{hi}° | " + " | ".join(cells) + " |")
    for d in days:
        top = sorted((r for r in data[d] if r["aircraft"] >= MIN_AC), key=lambda r: -r["score"])[:20]
        md += ["", f"## Top 20 hexes, {d} (≥ {MIN_AC} aircraft)", "", "| Score | Aircraft | Bad (NACp) | Bad (NIC) | Lat | Lon | Country | Region |", "|---|---|---|---|---|---|---|---|"]
        for r in top:
            reg = next((n for n, b in REGIONS.items() if in_box(r, b)), "")
            md.append(f"| {r['score']} | {r['aircraft']} | {r['bad_nacp']} | {r['bad_nic']} | {r['lat']:.2f} | {r['lon']:.2f} | {country(r['lat'], r['lon'])} | {reg} |")
        md += ["", f"![{d} world]({draw(d, data[d], 'world')})", "", f"![{d} Europe and Middle East]({draw(d, data[d], 'europe_me')})",
               "", f"Compare by eye: [GPSJam {d}](https://gpsjam.org/?lat=45&lon=25&z=3.5&date={d})"]
    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    open(OUT_MD, "w", encoding="utf-8").write("\n".join(md) + "\n")
    print(f"wrote {OUT_MD}")


if __name__ == "__main__":
    main()
