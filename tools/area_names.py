"""area_names.py: one rule for naming a GPS interference region or event (board.py, feed_v2.py through the board, and
the Atom feed in site_days.py).

A region or event is named, first that applies:
  place    the nearest listed place (site/data/places.json, rank 5 or better) within NAME_KM of its point, provided
           the place's country is one the area covers (a sample point of its H3 cells, or its own point) or the area
           covers no land: "near Zagreb"; when none is in reach, the nearest smaller listed place (rank 6 or 7,
           MINOR_RANKS) on the same terms: "near Batumi";
  country  the country its own point lies in; else, when at least LAND_MIN of its cells' sample points are on land,
           the country most of that land lies in: "in Hungary, 160 km E of Budapest". A point the kit's coarse
           outlines put at sea but Natural Earth's 10 m coast puts on land (tools/coast.py) takes the nearest country
           outline within COAST_KM as its own; a single point (point=True: a spoofed-to place) that the 10 m coast
           puts at sea skips the cells' land and takes its sea;
  sea      the Natural Earth marine area its point lies in (tools/sea_areas.py): "in the Baltic Sea, 260 km S of
           Stockholm";
  offshore the nearest place within SEA_KM, the old limit, as a name only: "near Chennai" (only where no sea
           outline is in reach).
Country and sea names carry no place coordinates, so the feed's country tags come from the cells alone and never
from a borrowed city. Countries read as in a sentence ("the United States", "the Netherlands"; THE). An event
of SPREAD_REGIONS or more regions whose cells reach SPREAD_MIN or more countries says so: "across 25 countries,
centred near Zagreb" (where()).

Why point first and sea names (18 Nov 2026, Tom's choice): on 17 Nov 2026 a burst whose point lies in Hungary read
"in Ukraine" (most of its five cells' land), and areas at sea took a country from a sliver of coast: "in Italy, 320
km S of Marseille" from 1 of 56 sample points on Sardinia, "in Turkey, 160 km W of Nicosia" west of Cyprus.

A country name also carries a reference point, "220 km W of Tbilisi" (ref()): the nearest listed place within REF_KM
in that country, unless a place across a border is under 1/REF_SAME of its distance, when that one is used, and then
named with its country: "in Saudi Arabia, 220 km S of Doha, Qatar". The reference is words only: no place
coordinates, so it never adds a country tag. Why (18 Nov 2026, Tom's choice "B"):
on 17 Nov 2026 the brief said GPS interference started in Saudi Arabia and fell below jamming scale in Saudi Arabia,
two areas about 500 km apart; "Saudi Arabia (330 km W of Abu Dhabi)" and "Saudi Arabia (210 km NW of Manama)" tell
them apart. The Sentinel-6 card already words its peaks this way ("64 km N of Shostka").

Why the 10 m coast (24 Nov 2026, Tom's yes): the kit's outlines are thinned to about 5 km, so a spoofed-to place
0.5 km inland in Myanmar (14.63N 97.91E) read "in the Andaman Sea, 300 km W of Bangkok", and one 7 km out in the
Gulf (25.79N 55.05E) read "in Iran" because its cell is half Iranian land. A false position is a point, not an area.

Why smaller places and the reference's country (18 Nov 2026 evening CST, Tom's yes after the reader's review of the
17 Nov feed): two Black Sea coast events read "in Turkey, 390 km E of Samsun" with Batumi (rank 6) in reach, and "in
Saudi Arabia, 220 km S of Doha" read as if Doha were in Saudi Arabia.

Why (17 Nov 2026, Tom's yes): with 350 km, the two 15 Nov 2026 majors on the Turkish-Georgian Black Sea coast
(41.26N 41.05E) were "near Sochi" (281 km) and tagged RU. On 3-16 Nov 2026, 82 of 256 major and notable events were
named after a place 150-350 km away, some across a border (a point in Greece "near Tirana").
"""
import functools
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CELLS = os.path.join(ROOT, "site", "data", "cell_countries.json")   # _cell_countries for every res-2 cell (build_cells)

NAME_KM = 150     # listed places within this distance of the area's point
SAMPLE_RES = 4    # sample points for the area's countries: each cell's corners, centre and res-4 children's centres
SEA_KM = 350      # an area over open sea with no place in reach and no country: the old naming distance
REF_KM = 500      # a country name's reference place: within this distance of the area's point
REF_SAME = 1.5    # ... in the named country, unless the nearest place elsewhere is closer by more than this factor
LAND_MIN = 0.5    # an area whose point is at sea takes a country only when this share of its sample points is land
SPREAD_MIN = 5    # an event whose cells reach this many countries is named "across N countries, centred ..."
SPREAD_REGIONS = 10   # ... when it also covers this many regions (Tom, 18 Nov 2026: at 5 countries alone, 18 of
                      # 17 Nov's 152 events read so, a one-region burst "across 5 countries, centred near Brussels")
COAST_KM = 10     # a point on 10 m land but outside the kit's outlines takes a country outline this close
MINOR_RANKS = (6, 7)    # smaller listed places, tried only when no rank 5 or better place is within NAME_KM
PLACES = os.path.join(ROOT, "site", "data", "places.json")
IN_KINDS = ("country", "sea")    # these names follow "in"; a place (or offshore name) follows "near"
# Country names as they read in a sentence (the kit's geo names otherwise).
THE = {"United States of America": "the United States"}
THE.update({n: "the " + n for n in (
    "United Kingdom", "United Arab Emirates", "Netherlands", "Philippines", "Bahamas", "Central African Republic",
    "Comoros", "Democratic Republic of the Congo", "Republic of the Congo", "Dominican Republic", "Gambia",
    "Maldives", "Seychelles", "Vatican", "British Indian Ocean Territory",
    "South Georgia and the South Sandwich Islands")})
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def km(a, b):
    p = math.pi / 180
    h = math.sin((b[0] - a[0]) * p / 2) ** 2 + math.cos(a[0] * p) * math.cos(b[0] * p) * math.sin((b[1] - a[1]) * p / 2) ** 2
    return 12742 * math.asin(min(1.0, math.sqrt(h)))


def bearing(a, b):
    """Initial compass bearing in degrees from a to b."""
    p = math.pi / 180
    y = math.sin((b[1] - a[1]) * p) * math.cos(b[0] * p)
    x = math.cos(a[0] * p) * math.sin(b[0] * p) - math.sin(a[0] * p) * math.cos(b[0] * p) * math.cos((b[1] - a[1]) * p)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def ref(places, lat, lon, cc=None, limit=REF_KM):
    """'220 km W of Tbilisi': the area's point from a listed place, distance to the nearest 10 km and one of eight
    compass points. The place is the nearest in country `cc` within `limit` km, unless one elsewhere is closer than
    1/REF_SAME of its distance; None when no place is in reach."""
    import feed_v2
    near = sorted((km((lat, lon), (p[1], p[2])), p[0], (p[1], p[2])) for p in _band(places, lat, limit))
    near = [t for t in near if t[0] <= limit]
    if not near:
        return None
    pick = near[0]
    if cc:
        for t in near:
            if t[0] > near[0][0] * REF_SAME:
                break
            if _place_country(t[2][0], t[2][1]) == cc:
                pick = t
                break
    d, name, at = pick
    out = f"{max(10, round(d / 10) * 10):.0f} km {COMPASS[int((bearing(at, (lat, lon)) + 22.5) // 45) % 8]} of {name}"
    pc = _place_country(at[0], at[1]) if cc else None
    if pc and pc != cc and country_name(pc):          # a place across the border is named with its country
        out += ", " + plain_country(pc)
    return out


def plain_country(cc):
    """A country's name after a place, as in an address: 'Doha, Qatar', 'Dubai, United Arab Emirates'."""
    n = country_name(cc)
    return n[4:] if n and n.startswith("the ") else n


@functools.lru_cache(maxsize=1)
def minor_places():
    """The listed places of MINOR_RANKS from places.json ([] when missing)."""
    try:
        with open(PLACES, encoding="utf-8") as f:
            pl = json.load(f).get("places", [])
    except (OSError, ValueError):
        return []
    return [p for p in pl if len(p) > 3 and p[3] in MINOR_RANKS]


def label(name, kind, near_ref):
    """The words for a named area after "in"/"near": 'Georgia, 220 km W of Tbilisi' for a country or sea with a
    reference, else the name."""
    return f"{name}, {near_ref}" if kind in IN_KINDS and near_ref else name


def phrase(name, kind, near_ref):
    """'near Zagreb', 'in Georgia, 220 km W of Tbilisi', 'in the Baltic Sea, 260 km S of Stockholm'; None unnamed."""
    if not name:
        return None
    return ("in " if kind in IN_KINDS else "near ") + label(name, kind, near_ref)


def country_name(cc):
    """The kit's name for a country code, as it reads in a sentence ("the United States")."""
    import feed_v2
    n = feed_v2.geo.name(cc) if cc else None
    if not n:
        return None
    return THE.get(n) or ("the " + n if n.endswith(" Islands") else n)


def spread(cells):
    """How many countries an area's cells reach (any sample point on land)."""
    seen = set()
    for c in dict.fromkeys(cells or []):
        seen.update(_cell_countries(c))
    return len(seen)


def where(places, lat, lon, cells=(), event=False, limit=NAME_KM, point=False):
    """The full words for an area: phrase() of area_ref(); for an event (event=True) of SPREAD_REGIONS or more regions
    whose cells reach SPREAD_MIN or more countries, 'across 25 countries, centred near Zagreb'. None when unnamed."""
    name, _, kind, ref = area_ref(places, lat, lon, cells, limit, point)
    w = phrase(name, kind, ref)
    if w and event and len(set(cells or [])) >= SPREAD_REGIONS:
        n = spread(cells)
        if n >= SPREAD_MIN:
            w = f"across {n} countries, centred {w}"
    return w


@functools.lru_cache(maxsize=4096)
def _place_country(lat, lon):
    """feed_v2.place_country, cached: the same listed places come up for event after event."""
    import feed_v2
    return feed_v2.place_country([lat, lon])


def fingerprint(places):
    """A short hash of the naming code, its tables and the place list: a names cache keyed on it empties itself
    when any of them changes."""
    import hashlib
    h = hashlib.sha1()
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, "area_names.py"), os.path.join(here, "sea_areas.py"), os.path.join(here, "coast.py"),
              os.path.join(here, "assets", "land10m.json.gz"), CELLS,
              os.path.join(ROOT, "site", "data", "seas.json"), PLACES):
        try:
            with open(p, "rb") as f:
                h.update(f.read())
        except OSError:
            h.update(b"-")
    h.update(json.dumps(places, sort_keys=True).encode())
    return h.hexdigest()[:16]


def _band(places, lat, limit):
    """The place rows within `limit` km of latitude `lat` (a cheap cut before the great-circle distances)."""
    d = limit / 111.0 + 0.01
    return [p for p in places if abs(p[1] - lat) <= d]


def nearest(places, lat, lon, limit):
    """(name, [lat, lon]) of the nearest place row [name, lat, lon, ...] within `limit` km, or (None, None)."""
    best, hit = limit, (None, None)
    for p in _band(places, lat, limit):
        d = km((lat, lon), (p[1], p[2]))
        if d < best:
            best, hit = d, (p[0], [p[1], p[2]])
    return hit


def _cell_points(cell):
    import h3
    pts = list(h3.cell_to_boundary(cell)) + [h3.cell_to_latlng(cell)]
    if h3.get_resolution(cell) < SAMPLE_RES:
        pts += [h3.cell_to_latlng(c) for c in h3.cell_to_children(cell, SAMPLE_RES)]
    return pts


@functools.lru_cache(maxsize=4096)
def _cell_samples(cell):
    """How many sample points _cell_countries looks at for a cell, land or sea (0 without h3)."""
    try:
        return len(_cell_points(cell))
    except ImportError:
        return 0


@functools.lru_cache(maxsize=1)
def _table():
    """The committed cell table (build_cells), or None when it is missing or was built another way."""
    try:
        with open(CELLS, encoding="utf-8") as f:
            t = json.load(f)
    except (OSError, ValueError):
        return None
    return t["cells"] if t.get("sample_res") == SAMPLE_RES and t.get("res") == 2 else None


@functools.lru_cache(maxsize=4096)
def _cell_countries(cell):
    """{country: sample points} over one H3 cell: 56 points for a res-2 cell (about 26 km apart), 7 times fewer
    country lookups than feed_v2.cell_points' res-5 set, which the country tags still use. A res-2 cell is read from
    site/data/cell_countries.json (borders don't move; 0.2 s a cell otherwise, 33 s for one day's 214 map events on
    18 Nov 2026); rebuild it with `python tools/area_names.py cells` after the kit's borders change."""
    t = _table()
    if t is not None and len(cell) == 15 and cell[1] == "2":
        return t.get(cell, {})
    return _count_countries(cell)


def _count_countries(cell):
    import feed_v2
    try:
        pts = _cell_points(cell)
    except ImportError:      # without h3: name from the point alone
        return {}
    seen = {}
    for la, lo in pts:
        cc = feed_v2.geo.country_at(la, lo)
        if cc:
            seen[cc] = seen.get(cc, 0) + 1
    return seen


def area_name(places, lat, lon, cells=(), limit=NAME_KM, point=False):
    """(name, place [lat, lon] or None) for a jamming region or event at (lat, lon) covering H3 `cells`; (None, None)
    when neither a place nor a country is known."""
    return area(places, lat, lon, cells, limit, point)[:2]


def area(places, lat, lon, cells=(), limit=NAME_KM, point=False):
    """(name, place [lat, lon] or None, kind): kind "place", "country", "sea" (a named sea), "offshore" (open sea out
    of reach of any sea outline, a place name only) or None."""
    return _area(places, lat, lon, cells, limit, point)[:3]


def area_ref(places, lat, lon, cells=(), limit=NAME_KM, point=False):
    """area() plus a reference for a country or sea name ("220 km W of Tbilisi", ref()), else None."""
    name, at, kind, cc = _area(places, lat, lon, cells, limit, point)
    return name, at, kind, (ref(places, lat, lon, cc) if kind in IN_KINDS else None)


def _coast_country(lat, lon, prefer=()):
    """The kit country whose outline is nearest (lat, lon) within COAST_KM, those in `prefer` first; else None."""
    import feed_v2
    kx = math.cos(math.radians(lat)) * 111.32
    py, px = COAST_KM / 111.32 + 0.01, COAST_KM / max(kx, 5.0) + 0.01     # the distance as degrees of lat, lon
    best = {}
    for c in feed_v2.geo._countries():
        b = c["bbox"]
        if not (b[0] - px <= lon <= b[2] + px and b[1] - py <= lat <= b[3] + py):
            continue
        for r in c["rings"]:
            for (x0, y0), (x1, y1) in zip(r, r[1:] + r[:1]):
                ax, ay, bx, by = (x0 - lon) * kx, (y0 - lat) * 111.32, (x1 - lon) * kx, (y1 - lat) * 111.32
                dx, dy = bx - ax, by - ay
                t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
                d = math.hypot(ax + t * dx, ay + t * dy)
                if d <= COAST_KM and d < best.get(c["cc"], COAST_KM + 1):
                    best[c["cc"]] = d
    if not best:
        return None
    pick = [cc for cc in best if cc in prefer] or list(best)
    return min(sorted(pick), key=best.get)


def _on_land(lat, lon):
    """tools/coast.py's 10 m land test: True, False, or None without its asset."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import coast
        return coast.on_land(round(lat, 4), round(lon, 4))
    except ImportError:
        return None


def _area(places, lat, lon, cells=(), limit=NAME_KM, point=False):
    import feed_v2
    seen = {}
    for c in dict.fromkeys(cells or []):
        for cc, k in _cell_countries(c).items():
            seen[cc] = seen.get(cc, 0) + k
    here = feed_v2.geo.country_at(lat, lon)
    land = None
    if not here:                                        # the kit's 5 km outlines miss some coastal points
        land = _on_land(lat, lon)
        if land:
            here = _coast_country(lat, lon, seen)
    covered = set(seen) | ({here} if here else set())
    near = sorted((km((lat, lon), (p[1], p[2])), p[0], [p[1], p[2]]) for p in _band(places, lat, limit))
    for d, n, at in near:
        if d > limit:
            break
        if not covered or _place_country(at[0], at[1]) in covered:
            return n, at, "place", None
    minor = sorted((km((lat, lon), (p[1], p[2])), p[0], [p[1], p[2]]) for p in _band(minor_places(), lat, limit))
    for d, n, at in minor:                              # a smaller place in reach before a country name
        if d > limit:
            break
        if not covered or _place_country(at[0], at[1]) in covered:
            return n, at, "place", None
    if here and country_name(here):                     # the point's own country first
        return country_name(here), None, "country", here
    cells = list(dict.fromkeys(cells or []))
    total = sum(_cell_samples(c) for c in cells)
    if seen and (not total or sum(seen.values()) >= LAND_MIN * total) and not (point and land is False):
        cc = max(sorted(seen), key=seen.get)
        if country_name(cc):
            return country_name(cc), None, "country", cc
    import sea_areas
    s = sea_areas.sea_at(round(lat, 2), round(lon, 2))
    if s:
        return sea_areas.with_article(s), None, "sea", None
    if seen:                                            # some land, no sea outline in reach: its country after all
        cc = max(sorted(seen), key=seen.get)
        if country_name(cc):
            return country_name(cc), None, "country", cc
    # Open sea out of reach of any outline: the nearest place within the old 350 km, as a name only.
    n, _ = nearest(places, lat, lon, SEA_KM)
    return (n, None, "offshore", None) if n else (None, None, None, None)


def _one(cell):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    return cell, _count_countries(cell)


def build_cells(out=CELLS, procs=8):
    """Write _cell_countries for every H3 res-2 cell (land cells only; a cell not listed has no land)."""
    import h3
    from multiprocessing import Pool
    cells = sorted(c for r in h3.get_res0_cells() for c in h3.cell_to_children(r, 2))
    with Pool(procs) as pool:
        got = dict(pool.map(_one, cells, chunksize=20))
    land = {c: dict(sorted(v.items())) for c, v in sorted(got.items()) if v}
    doc = {"res": 2, "sample_res": SAMPLE_RES, "cells_checked": len(cells),
           "source": "tools/area_names.py build_cells: country of each sample point (corners, centre, res-4 children) "
                     "from the doctrine kit's geo/countries.json (Natural Earth, public domain)", "cells": land}
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, separators=(",", ":"))
    return len(cells), len(land)


if __name__ == "__main__":
    if sys.argv[1:] == ["cells"]:
        print(build_cells())
    else:
        sys.exit("usage: python tools/area_names.py cells")
