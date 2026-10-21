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
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


@lru_cache(maxsize=1)
def _load():
    d = json.load(gzip.open(DATA, "rt", encoding="utf-8"))
    geoms = [shape(f["geometry"]) for f in d["countries"]["features"]]
    return d["places"], geoms, [f["properties"] for f in d["countries"]["features"]], STRtree(geoms)


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
    places, *_ = _load()
    best = None
    for name, plat, plon, _, pop in places:
        az, _, d = GEOD.inv(plon, plat, lon, lat)
        d /= 1000
        # prefer bigger places when distances are similar
        score = d - 4 * math.log10(max(pop, 1))
        if best is None or score < best[0]:
            best = (score, name, d, az)
    iso, cname, on_land = country(lat, lon)
    where = ""
    if best and best[2] <= 150:
        _, name, d, az = best
        where = name if d < 3 else f"{d:.0f} km {COMPASS[int(((az % 360) + 22.5) // 45) % 8]} of {name}"
    else:                                   # outside the bundled gazetteer's region
        where = f"{abs(lat):.2f}{'N' if lat >= 0 else 'S'} {abs(lon):.2f}{'E' if lon >= 0 else 'W'}"
    if iso:
        where += f" ({iso}{'' if on_land else ', offshore'})"
    return where.strip(), iso
