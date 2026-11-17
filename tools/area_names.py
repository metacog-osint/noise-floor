"""area_names.py: one rule for naming a GPS interference region or event (board.py, feed_v2.py through the board, and
the Atom feed in site_days.py).

A region or event is named after the nearest listed place (site/data/places.json, rank 5 or better) within NAME_KM of
its point, provided the place's country is one the area covers (a sample point of its H3 cells, or its own point) or
the area covers no land. Otherwise it is named by the country most of its cells' land lies in (its own point's
country when the cells give none), with no place coordinates, so the feed's country tags come from the cells alone and
never from a borrowed city. An area over open sea with neither falls back to the nearest place within SEA_KM, the old
limit, as a name only.

Why (17 Nov 2026, Tom's yes): with 350 km, the two 15 Nov 2026 majors on the Turkish-Georgian Black Sea coast
(41.26N 41.05E) were "near Sochi" (281 km) and tagged RU. On 3-16 Nov 2026, 82 of 256 major and notable events were
named after a place 150-350 km away, some across a border (a point in Greece "near Tirana").
"""
import functools
import math

NAME_KM = 150     # listed places within this distance of the area's point
SAMPLE_RES = 4    # sample points for the area's countries: each cell's corners, centre and res-4 children's centres
SEA_KM = 350      # an area over open sea with no place in reach and no country: the old naming distance


def km(a, b):
    p = math.pi / 180
    h = math.sin((b[0] - a[0]) * p / 2) ** 2 + math.cos(a[0] * p) * math.cos(b[0] * p) * math.sin((b[1] - a[1]) * p / 2) ** 2
    return 12742 * math.asin(min(1.0, math.sqrt(h)))


def nearest(places, lat, lon, limit):
    """(name, [lat, lon]) of the nearest place row [name, lat, lon, ...] within `limit` km, or (None, None)."""
    best, hit = limit, (None, None)
    for p in places:
        d = km((lat, lon), (p[1], p[2]))
        if d < best:
            best, hit = d, (p[0], [p[1], p[2]])
    return hit


@functools.lru_cache(maxsize=4096)
def _cell_countries(cell):
    """{country: sample points} over one H3 cell, cached: the same regions recur day after day. 56 points for a res-2
    cell (about 26 km apart), 7 times fewer country lookups than feed_v2.cell_points' res-5 set, which the country tags
    still use."""
    import feed_v2
    try:
        import h3
    except ImportError:      # the deploy runs site_days.py before it installs h3: name from the point alone
        return {}
    pts = list(h3.cell_to_boundary(cell)) + [h3.cell_to_latlng(cell)]
    if h3.get_resolution(cell) < SAMPLE_RES:
        pts += [h3.cell_to_latlng(c) for c in h3.cell_to_children(cell, SAMPLE_RES)]
    seen = {}
    for la, lo in pts:
        cc = feed_v2.geo.country_at(la, lo)
        if cc:
            seen[cc] = seen.get(cc, 0) + 1
    return seen


def area_name(places, lat, lon, cells=(), limit=NAME_KM):
    """(name, place [lat, lon] or None) for a jamming region or event at (lat, lon) covering H3 `cells`; (None, None)
    when neither a place nor a country is known."""
    return area(places, lat, lon, cells, limit)[:2]


def area(places, lat, lon, cells=(), limit=NAME_KM):
    """(name, place [lat, lon] or None, kind): kind "place", "country", "sea" (open sea, a place name only) or None."""
    import feed_v2
    seen = {}
    for c in dict.fromkeys(cells or []):
        for cc, k in _cell_countries(c).items():
            seen[cc] = seen.get(cc, 0) + k
    here = feed_v2.geo.country_at(lat, lon)
    covered = set(seen) | ({here} if here else set())
    near = sorted((km((lat, lon), (p[1], p[2])), p[0], [p[1], p[2]]) for p in places)
    for d, n, at in near:
        if d > limit:
            break
        if not covered or feed_v2.place_country(at) in covered:
            return n, at, "place"
    cc = max(sorted(seen), key=seen.get) if seen else here
    country = feed_v2.geo.name(cc) if cc else None
    if country:
        return country, None, "country"
    # Open sea: the nearest place within the old 350 km, as a name only (no place coordinates, so no country tag).
    n, _ = nearest(places, lat, lon, SEA_KM)
    return (n, None, "sea") if n else (None, None, None)
