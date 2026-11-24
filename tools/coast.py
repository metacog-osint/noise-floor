"""coast.py: is a point on land, by Natural Earth's 10 m coastline? (tools/area_names.py)

The doctrine kit's country outlines (geo/countries.json) are Natural Earth 50 m thinned to about 5 km, which is right
for tagging but puts some coastal points on the wrong side of the shore. On 24 Nov 2026 a spoofed-to place 0.5 km
inland in Myanmar (14.63N 97.91E, Yebyu Township) read "in the Andaman Sea", and a point 7 km out in the Gulf
(25.79N 55.05E) read "in Iran" from its cell's land. area_names asks this module when the kit finds no country at a
point.

  on_land(lat, lon)   True or False by the 10 m land and minor islands; None when the asset is missing
  python tools/coast.py build <ne_10m_land.geojson> <ne_10m_minor_islands.geojson>
                      rewrites ASSET (needs shapely; only for a rebuild)

ASSET: every ring of Natural Earth 10 m land plus minor islands (public domain, naturalearthdata.com, v5.1.2),
simplified to 0.002 degrees (about 220 m; polygons under SMALL
across kept whole) and stored as integer thousandths of a degree, each ring's first point
whole and the rest as differences, gzipped. Even-odd over all rings, so lakes cut out of land count as water.
"""
import functools
import gzip
import json
import math
import os
import sys

ASSET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "land10m.json.gz")
TOL = 0.002       # simplification, degrees
SCALE = 1000      # stored integers per degree
BAND = 0.1        # edge index: latitude bands this many degrees tall
SMALL = 0.1       # polygons smaller than this many degrees across are not simplified


@functools.lru_cache(maxsize=1)
def _edges():
    """{band: [(x0, y0, x1, y1), ...]} for every ring edge, by the latitude bands it spans; None without the asset."""
    try:
        with gzip.open(ASSET, "rt", encoding="utf-8") as f:
            rings = json.load(f)["rings"]
    except (OSError, ValueError, KeyError):
        return None
    out = {}
    for r in rings:
        x, y = r[0], r[1]
        pts = [(x, y)]
        for i in range(2, len(r), 2):
            x += r[i]
            y += r[i + 1]
            pts.append((x, y))
        pts = [(a / SCALE, b / SCALE) for a, b in pts]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
            if y0 == y1:
                continue
            for b in range(math.floor(min(y0, y1) / BAND), math.floor(max(y0, y1) / BAND) + 1):
                out.setdefault(b, []).append((x0, y0, x1, y1))
    return out


@functools.lru_cache(maxsize=8192)
def on_land(lat, lon):
    """True when (lat, lon) lies on Natural Earth 10 m land, False at sea, None when the asset is missing."""
    e = _edges()
    if e is None:
        return None
    inside = False
    for x0, y0, x1, y1 in e.get(math.floor(lat / BAND), ()):
        if (y0 > lat) != (y1 > lat) and lon < (x1 - x0) * (lat - y0) / (y1 - y0) + x0:
            inside = not inside
    return inside


def build(land, islands, out=ASSET):
    from shapely.geometry import shape
    from shapely.strtree import STRtree
    polys = {}
    for src in (land, islands):
        with open(src, encoding="utf-8") as f:
            polys[src] = [p for ft in json.load(f)["features"] for g in [shape(ft["geometry"])]
                          for p in ([g] if g.geom_type == "Polygon" else list(g.geoms))]
    tree = STRtree(polys[land])
    # many minor islands are in the land layer too, and even-odd would cancel a ring drawn twice (Abu Musa, 24 Nov 2026)
    extra = [p for p in polys[islands] if not any(polys[land][i].intersects(p) for i in tree.query(p))]
    rings = []
    for p in polys[land] + extra:
        b = p.bounds                  # small islands keep every point: simplifying can drop them whole
        if max(b[2] - b[0], b[3] - b[1]) > SMALL:
            p = p.simplify(TOL, preserve_topology=True)
        for ring in [p.exterior] + list(p.interiors):
            pts = [(round(x * SCALE), round(y * SCALE)) for x, y in ring.coords[:-1]]
            pts = [q for i, q in enumerate(pts) if i == 0 or q != pts[i - 1]]
            if len(pts) < 3:
                continue
            enc = [pts[0][0], pts[0][1]]
            for (a, b), (c, d) in zip(pts, pts[1:]):
                enc += [c - a, d - b]
            rings.append(enc)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    doc = {"source": "Natural Earth 10 m land and minor islands (public domain, naturalearthdata.com, v5.1.2); "
                     f"simplified to {TOL} degrees, polygons under {SMALL} across kept whole; integers are thousandths of a degree, [x0, y0, dx, dy, ...] per "
                     "ring (tools/coast.py)", "rings": rings}
    with gzip.GzipFile(out, "wb", compresslevel=9, mtime=0) as f:
        f.write(json.dumps(doc, separators=(",", ":")).encode())
    return len(rings), os.path.getsize(out)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "build":
        print("rings %d, %d bytes" % build(sys.argv[2], sys.argv[3]))
    else:
        print(__doc__)
