"""sea_areas.py: which named sea, gulf, bay, strait or ocean a point lies in, for area names at sea
(tools/area_names.py; Tom's choice 18 Nov 2026).

Source: Natural Earth 10m marine areas (ne_10m_geography_marine_polys, v5.1.0, public domain, registry row
`natural-earth`), cut by `build` into site/data/seas.json: English names, outlines simplified to about 2 km and
rounded to 0.01 degree.

    python tools/sea_areas.py build <folder with ne_10m_geography_marine_polys.shp/.dbf>

The shapefile is read with the small reader below (no GIS libraries needed). A point takes the smallest named area
that contains it (the Ligurian Sea before the Mediterranean Sea); a point just outside every outline, where Natural
Earth's coast and the country borders disagree, takes the nearest outline within NEAR_KM.
"""
import functools
import json
import math
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEAS = os.path.join(ROOT, "site", "data", "seas.json")
TOLERANCE = 0.02     # degrees: Douglas-Peucker simplification
NEAR_KM = 60         # a point outside every outline takes the nearest one within this distance
# Natural Earth's `name` is the local form for some areas ("Golfo de California"); `name_en` drops the hemisphere
# from the oceans ("Atlantic Ocean") and is worse for these few, which keep `name`.
KEEP_NAME = {"North Atlantic Ocean", "South Atlantic Ocean", "North Pacific Ocean", "South Pacific Ocean",
             "Hangzhou Bay", "Garabogaz Bay", "Cook Inlet"}
NO_ARTICLE = (" Bay", " Sound", " Inlet")      # "in Hudson Bay", "in Puget Sound"; "in the Gulf of Aden"


# ---------- building seas.json from the shapefile ----------

def _dbf(path):
    b = open(path, "rb").read()
    n, hlen, rlen = struct.unpack("<IHH", b[4:12])
    fields, off = [], 32
    while b[off] != 0x0D:
        fields.append((b[off:off + 11].split(b"\0")[0].decode("ascii"), b[off + 16]))
        off += 32
    rows = []
    for i in range(n):
        r, p, row = b[hlen + i * rlen: hlen + (i + 1) * rlen], 1, {}
        for name, ln in fields:
            row[name] = r[p:p + ln].decode("utf-8", "replace").strip()
            p += ln
        rows.append(row)
    return rows


def _shp(path):
    b = open(path, "rb").read()
    off, out = 100, []
    while off < len(b):
        clen = struct.unpack(">I", b[off + 4:off + 8])[0]
        rec = b[off + 8: off + 8 + clen * 2]
        off += 8 + clen * 2
        if struct.unpack("<i", rec[:4])[0] != 5:          # 0 = null shape; this layer has only polygons
            out.append([])
            continue
        nparts, npts = struct.unpack("<ii", rec[36:44])
        parts = list(struct.unpack(f"<{nparts}i", rec[44:44 + 4 * nparts])) + [npts]
        pts = struct.unpack(f"<{2 * npts}d", rec[44 + 4 * nparts: 44 + 4 * nparts + 16 * npts])
        xy = [(pts[2 * i], pts[2 * i + 1]) for i in range(npts)]
        out.append([xy[parts[k]:parts[k + 1]] for k in range(nparts)])
    return out


def _simplify(pts, tol):
    """Douglas-Peucker on [(x, y), ...], iterative."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        best, bi = 0.0, None
        for i in range(a + 1, b):
            x, y = pts[i]
            d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / L if L else math.hypot(x - x1, y - y1)
            if d > best:
                best, bi = d, i
        if bi is not None and best > tol:
            keep[bi] = True
            stack += [(a, bi), (bi, b)]
    return [p for p, k in zip(pts, keep) if k]


def display(row):
    """The English name used in area names."""
    return row["name"] if row["name"] in KEEP_NAME else (row.get("name_en") or row["name"])


def build(folder, out=SEAS):
    base = os.path.join(folder, "ne_10m_geography_marine_polys")
    rows, geoms = _dbf(base + ".dbf"), _shp(base + ".shp")
    assert len(rows) == len(geoms), (len(rows), len(geoms))
    seas = []
    for row, rings in zip(rows, geoms):
        kept = []
        for r in rings:
            s = [[round(x, 2), round(y, 2)] for x, y in _simplify(r, TOLERANCE)]
            if len(s) >= 4:
                kept.append(s)
        if not kept:
            continue
        xs = [p[0] for r in kept for p in r]
        ys = [p[1] for r in kept for p in r]
        seas.append({"name": display(row), "kind": row["featurecla"],
                     "bbox": [min(xs), min(ys), max(xs), max(ys)], "rings": kept})
    doc = {"source": "Natural Earth 10m marine areas (ne_10m_geography_marine_polys v5.1.0), public domain; "
                     f"outlines simplified ({TOLERANCE} degree) by tools/sea_areas.py", "seas": seas}
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    return len(seas), os.path.getsize(out)


# ---------- lookup ----------

@functools.lru_cache(maxsize=1)
def _seas():
    if not os.path.exists(SEAS):
        return ()
    with open(SEAS, encoding="utf-8") as f:
        return tuple(json.load(f)["seas"])


def _inside(x, y, rings):
    """Even-odd over all rings, so holes (islands) count as outside."""
    inside = False
    for r in rings:
        j = len(r) - 1
        for i in range(len(r)):
            xi, yi = r[i]
            xj, yj = r[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
    return inside


def _km(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    h = math.sin((lat2 - lat1) * p / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
    return 12742 * math.asin(min(1.0, math.sqrt(h)))


@functools.lru_cache(maxsize=4096)
def sea_at(lat, lon):
    """The English name of the smallest Natural Earth marine area containing (lat, lon), else of the nearest outline
    within NEAR_KM, else None."""
    hit = None
    for s in _seas():
        b = s["bbox"]
        if b[0] <= lon <= b[2] and b[1] <= lat <= b[3] and _inside(lon, lat, s["rings"]):
            size = (b[2] - b[0]) * (b[3] - b[1])
            if hit is None or size < hit[0]:
                hit = (size, s["name"])
    if hit:
        return hit[1]
    pad = NEAR_KM / 111.0 * 2
    best = None
    for s in _seas():
        b = s["bbox"]
        if not (b[0] - pad <= lon <= b[2] + pad and b[1] - pad / 2 <= lat <= b[3] + pad / 2):
            continue
        for r in s["rings"]:
            for x, y in r:
                d = _km(lat, lon, y, x)
                if d <= NEAR_KM and (best is None or d < best[0]):
                    best = (d, s["name"])
    return best[1] if best else None


def with_article(name):
    """'the Mediterranean Sea', 'the Gulf of Aden', but 'Hudson Bay', 'Puget Sound'."""
    return name if name.endswith(NO_ARTICLE) or name.startswith("Lake ") else "the " + name


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "build":
        n, size = build(sys.argv[2])
        print(json.dumps({"seas": n, "kb": size // 1024}))
    else:
        sys.exit(__doc__)
