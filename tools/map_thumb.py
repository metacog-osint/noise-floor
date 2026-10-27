#!/usr/bin/env python3
"""map_thumb.py: the home page's map of the latest day, as two small SVGs (light and dark), built at deploy.

  python3 tools/map_thumb.py [SITE]          # SITE defaults to site/

Reads SITE/data/gnss/days.json (the latest daily day, else the latest day), that day's SITE/data/gnss/<day>.json and
SITE/data/land.json, and writes SITE/data/today-map.svg and today-map-dark.svg. The measure and classes are the map
page's "jamming-scale loss" (site_src/map.js): share = 100 * max(bad - 1, 0) / aircraft over hexes with 5 or more
aircraft, in classes 2-5, 5-10, 10-25 and 25% or more; quieter hexes are drawn faintly to show coverage. The view is
Europe, the Middle East and Pakistan, where most interference is. Needs h3. Data: adsb.lol (ODbL 1.0) through the
daily pipeline; land: Natural Earth (public domain).
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LON0, LON1, LAT0, LAT1 = -10.0, 78.0, 22.0, 64.0
W = 800
K = math.cos(math.radians((LAT0 + LAT1) / 2))
H = round(W * (LAT1 - LAT0) / ((LON1 - LON0) * K))
BREAKS = [2, 5, 10, 25]
THEMES = {   # the site's map tokens (style.css --map-*, --ramp-1..4)
    "today-map.svg": {"ocean": "#d6dfe9", "land": "#ffffff", "coast": "#b8c3cf", "quiet": "#5f6978", "quiet_op": 0.07,
                      "edge": "#ffffff", "ramp": ["#e3824c", "#c85f2a", "#a2441a", "#6e2c0f"]},
    "today-map-dark.svg": {"ocean": "#0b0e12", "land": "#1f252e", "coast": "#323a46", "quiet": "#a0aab9", "quiet_op": 0.07,
                           "edge": "#0b0e12", "ramp": ["#b04c1f", "#d8652b", "#f28a4a", "#ffbd8a"]},
}


def xy(lon, lat, nd=1):
    return round((lon - LON0) / (LON1 - LON0) * W, nd), round((LAT1 - lat) / (LAT1 - LAT0) * H, nd)


def near_view(lon, lat, pad=4):
    return LON0 - pad <= lon <= LON1 + pad and LAT0 - pad <= lat <= LAT1 + pad


def path(points, nd=1):
    return "M" + "L".join("%g,%g" % xy(lo, la, nd) for lo, la in points) + "Z"


def land_paths(land):
    out = []
    for f in land.get("features", []):
        g = f["geometry"]
        for poly in ([g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]):
            ring = poly[0]
            if len(ring) >= 4 and any(near_view(lo, la) for lo, la in ring):
                out.append(path(ring))
    return out


def hex_paths(day):
    import h3
    cols = day["cols"]
    ia, ib = cols.index("aircraft"), cols.index("bad_live")
    quiet, hot = [], [[] for _ in BREAKS]
    for c in day["cells"]:
        n, bad = c[ia], c[ib]
        if n < 5:
            continue
        la, lo = h3.cell_to_latlng(c[0])
        if not near_view(lo, la, pad=1):
            continue
        share = 100 * max(bad - 1, 0) / n
        k = sum(share >= b for b in BREAKS)
        ring = [(lo2, la2) for la2, lo2 in h3.cell_to_boundary(c[0])]
        if k == 0:
            quiet.append(path(ring, nd=0))
        else:
            hot[k - 1].append(path(ring))
    return quiet, hot


def svg(theme, land, quiet, hot, day):
    t = THEMES[theme]
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">',
             f"<title>Aircraft GPS loss, {day} (UTC)</title>",
             f'<rect width="{W}" height="{H}" fill="{t["ocean"]}"/>',
             f'<path d="{"".join(land)}" fill="{t["land"]}" stroke="{t["coast"]}" stroke-width="0.6" stroke-linejoin="round"/>',
             f'<path d="{"".join(quiet)}" fill="{t["quiet"]}" fill-opacity="{t["quiet_op"]}"/>']
    for k, ps in enumerate(hot):
        if ps:
            parts.append(f'<path d="{"".join(ps)}" fill="{t["ramp"][k]}" stroke="{t["edge"]}" stroke-width="0.4" stroke-opacity="0.6"/>')
    parts.append("</svg>")
    return "".join(parts)


def main():
    site = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "site")
    data = os.path.join(site, "data")
    days = json.load(open(os.path.join(data, "gnss", "days.json"), encoding="utf-8"))
    daily = [d for d in days if d.get("daily")]
    day = (daily or days)[-1]["day"]
    cells = json.load(open(os.path.join(data, "gnss", f"{day}.json"), encoding="utf-8"))
    land = land_paths(json.load(open(os.path.join(data, "land.json"), encoding="utf-8")))
    quiet, hot = hex_paths(cells)
    for name in THEMES:
        with open(os.path.join(data, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(svg(name, land, quiet, hot, day))
    print(f"map thumbnail {day}: {sum(len(h) for h in hot)} hexes at 2% or more, {len(quiet)} quieter; "
          f"{os.path.getsize(os.path.join(data, 'today-map.svg')) // 1024} KB each")


if __name__ == "__main__":
    main()
