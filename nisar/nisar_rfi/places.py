"""Offline 'where is this' wording from Natural Earth (public domain), worldwide."""
import gzip
import json
import math
import os
from functools import lru_cache

from shapely.geometry import Point, shape
from shapely.strtree import STRtree

from .geometry import GEOD

DATA = os.path.join(os.path.dirname(__file__), "assets", "gazetteer.json.gz")
REGIONS = os.path.join(os.path.dirname(__file__), "assets", "regions.json.gz")   # tools/build_place_regions.py
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
NEAR_KM, FAR_KM = 150, 400
SPECIFIC_KM2 = 400_000          # a named land region smaller than this says more than a town 150-400 km away


@lru_cache(maxsize=1)
def _load():
    d = json.load(gzip.open(DATA, "rt", encoding="utf-8"))
    places = [[" ".join(p[0].split()), *p[1:]] for p in d["places"]]       # Natural Earth has "St.  Petersburg"
    geoms = [shape(f["geometry"]) for f in d["countries"]["features"]]
    return places, geoms, [f["properties"] for f in d["countries"]["features"]], STRtree(geoms)


@lru_cache(maxsize=1)
def _regions():
    if not os.path.exists(REGIONS):
        return {}
    d = json.load(gzip.open(REGIONS, "rt", encoding="utf-8"))
    out = {}
    for kind in ("land", "sea"):
        geoms = [shape(f["geometry"]) for f in d[kind]]
        out[kind] = (geoms, [f["name"] for f in d[kind]], STRtree(geoms))
    return out


def region(lat, lon, kind):
    """(name, area km²) of the smallest named land region or sea containing the point, or None."""
    r = _regions().get(kind)
    if not r:
        return None
    geoms, names, tree = r
    p = Point(lon, lat)
    hits = [(abs(GEOD.geometry_area_perimeter(geoms[i])[0]) / 1e6, names[i]) for i in tree.query(p) if geoms[i].contains(p)]
    if not hits:
        return None
    area, name = min(hits)
    return name, area


def country(lat, lon):
    """(ISO2, name, on_land) — nearest country within ~60 km when the point is at sea."""
    _, geoms, props, tree = _load()
    p = Point(lon, lat)
    for i in tree.query(p):
        if geoms[i].contains(p):
            return props[i]["iso"], props[i]["name"], True
    i = tree.nearest(p)
    if i is not None and geoms[i].distance(p) < 0.9:
        return props[i]["iso"], props[i]["name"], False
    return None, None, False


def describe(lat, lon):
    """A town within 150 km; else the named region it lies in (an island group, a desert, a sea); else a town within
    400 km; else coordinates. The country follows in brackets; at sea beyond any country, the sea's name does."""
    places, *_ = _load()
    best = None
    for name, plat, plon, _, pop in places:
        az, _, d = GEOD.inv(plon, plat, lon, lat)
        d /= 1000
        # prefer bigger places when distances are similar
        score = d - 4 * math.log10(max(pop, 1))
        if best is None or score < best[0]:
            best = (score, name, d, az)

    def from_town():
        _, name, d, az = best
        return name if d < 3 else f"{d:.0f} km {COMPASS[int(((az % 360) + 22.5) // 45) % 8]} of {name}"

    iso, cname, on_land = country(lat, lon)
    near = bool(best and best[2] <= NEAR_KM)
    land = None if near else region(lat, lon, "land")
    sea = None if on_land or (near and iso) else region(lat, lon, "sea")
    if near:
        where = from_town()
    elif land and land[1] < SPECIFIC_KM2:
        where = land[0]
    elif best and best[2] <= FAR_KM:
        where = from_town()
    elif land or sea:
        where = (land or sea)[0]
    else:
        where = f"{abs(lat):.2f}{'N' if lat >= 0 else 'S'} {abs(lon):.2f}{'E' if lon >= 0 else 'W'}"
    if iso:
        where += f" ({iso}{'' if on_land else ', offshore'})"
    elif sea and sea[0] != where:
        where += f" ({sea[0]})"
    return where.strip(), iso
