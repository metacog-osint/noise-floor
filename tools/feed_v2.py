#!/usr/bin/env python3
"""feed_v2.py: Noisefloor's items in The Intelligence Company's feed contract v2: SITE/data/feed.geojson.

  python tools/feed_v2.py [SITE]

Built at deploy, right after board.py, from SITE/data/board.json and SITE/data/gnss/days.json. Every item here is a
measurement (kind observation): regions that newly reached jamming scale this week, regions that fell below it or where it ended, named areas
whose severe share rose 5 points or more above their 30-day median, the day's major and notable events (majors
anomaly, notables routine; each drawn as its H3 res-2 regions, stamped with its own hours), and up to five
places where aircraft were newly shown at a false position (spoofing; tools/spoof_site.py new_targets(), placed where
the aircraft really were), plus one daily summary. From 16 Nov 2026 (Tom's yes) also the space weather files
(tools/swx_site.py, board section "swx"): the day's highest limb S4 cells (H3 res-1 polygons) and every ground ROTI
station (points), each at its highest UTC hour. Those are routine observations with no baseline: no tier above routine
is used for them until a baseline is set and stated, and neither is read against S4 alert levels. Warnings (judged, with likelihood and confidence) come later through doctrine/indicators.json.

The doctrine kit's tradecraft linter (doctrine/kit) checks the feed before it is written. A feed that fails is not
written, the reason is printed, and the deploy carries on.
"""
import json
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "doctrine", "kit", "python"))
from tic_doctrine import CONTRACT, contract, geo, vocab  # noqa: E402

SITE_URL = "https://noisefloor.theintelligence.company"
METHOD = "noisefloor-feed-1.0"
NEW_SPOOF_ITEMS = 5                                   # new spoofed-to places per day, largest first
ABOVE_SPOOF_ITEMS = 5                                 # spoofed-to places above their usual level, biggest rise first
ABOVE_REGION_ITEMS = 5                                # regions (where aircraft were) above their usual level, biggest rise first
NCF = ["provide_pnt", "transport_by_air"]           # doctrine/ncf_map.json, product gnss-aircraft
ADSBLOL = {"id": "adsblol-archive", "publisher": "adsb.lol", "url": "https://github.com/adsblol/globe_history_2026",
           "licence": "ODbL 1.0", "grade": "B2", "independence_group": "adsb-feeders", "source_type": "dataset",
           "descriptor": "Crowd-fed ADS-B receiver archive (readsb traces with navigation-accuracy fields); daily file "
                         "posted the next morning; evaluated by Noisefloor's validation days."}
COSMIC2 = {"id": "cosmic2-ro", "publisher": "UCAR COSMIC Program (CDAAC)",
           "url": "https://data.cosmic.ucar.edu/gnss-ro/cosmic2/nrt/level1b/", "licence": "CC BY 4.0 (UCAR data terms)",
           "grade": "A2", "independence_group": "ucar-cosmic2", "source_type": "dataset",
           "descriptor": "COSMIC-2 near-real-time level 1b podTc2 files: S4 computed on board each receiver every 10 s from "
                         "GPS signal-to-noise ratio; daily archive posted about 04:35 UTC the next day; evaluated against "
                         "INGV eSWua ground receivers (docs/validation/cosmic2-limb-s4.md)."}
IGS = {"id": "cors-igs", "publisher": "International GNSS Service (IGS) and the station operators, via the BKG GNSS Data "
       "Center", "url": "https://igs.bkg.bund.de/root_ftp/IGS/obs/",
       "licence": "IGS terms of use: open, attribution required (derived day files CC BY 4.0)", "grade": "A2",
       "independence_group": "igs-stations", "source_type": "dataset",
       "descriptor": "Daily 30 s RINEX observation files of 17 IGS stations and the IGS merged broadcast orbits; posted "
                     "the next day; evaluated against INGV eSWua ground receivers (docs/validation/ground-roti.md)."}
SWX_NCF = ["provide_pnt"]                              # doctrine/ncf_map.json, product space-weather
ROTI_STATIONS = 17                                     # stations in the frozen method (docs/validation/ground-roti.md)
COSMIC2_SATELLITES = 6                                 # COSMIC-2 receivers; only some deliver podTc2 files
COMMON = {"contract": CONTRACT, "program": "noisefloor", "status": "actual", "msg_type": "new", "human_review": "none",
          "us_person_data": "none", "method_version": METHOD, "ie_aspect": ["physical"], "pmesii_pt": ["infrastructure"],
          "ascope": ["capabilities"]}


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def utc(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def coverage(days, day):
    """Cells with aircraft data on the day, against the median of the 28 days before (capped at 1)."""
    idx = {d["day"]: i for i, d in enumerate(days)}
    if day not in idx:
        return None
    i = idx[day]
    prior = [d.get("hexes") for d in days[max(0, i - 28):i] if d.get("hexes")]
    if not prior or not days[i].get("hexes"):
        return None
    return round(min(1.0, days[i]["hexes"] / statistics.median(prior)), 3)


def box_polygon(box):
    la0, la1, lo0, lo1 = box
    return {"type": "Polygon", "coordinates": [[[lo0, la0], [lo1, la0], [lo1, la1], [lo0, la1], [lo0, la0]]]}


def box_points(box):
    la0, la1, lo0, lo1 = box
    return [(la0 + (la1 - la0) * a, lo0 + (lo1 - lo0) * b) for a in (0.1, 0.5, 0.9) for b in (0.1, 0.5, 0.9)]


SAMPLE_RES = 5                                        # a res-2 cell is sampled at its 343 res-5 children's centres


def cell_points(cell):
    """Sample points over an H3 cell for country tags: its corners, its centre and its res-5 children's centres
    (343 for a res-2 cell, about 9 km apart). Corners alone missed the country in the middle of the cell: the
    "near Tel Aviv" region was tagged EG, JO, LB without IL (suite review, 15 Nov 2026)."""
    import h3
    pts = list(h3.cell_to_boundary(cell)) + [h3.cell_to_latlng(cell)]
    if h3.get_resolution(cell) < SAMPLE_RES:
        pts += [h3.cell_to_latlng(c) for c in h3.cell_to_children(cell, SAMPLE_RES)]
    return pts


def h3_polygon(cell):
    import h3
    ring = [[round(lo, 4), round(la, 4)] for la, lo in h3.cell_to_boundary(cell)]
    return {"type": "Polygon", "coordinates": [ring + [ring[0]]]}, cell_points(cell)


def h3_area(cells):
    """A MultiPolygon of H3 cells and their sample points: an event's res-2 regions, drawn as published."""
    import h3
    polys, pts = [], []
    for c in cells:
        ring = [[round(lo, 4), round(la, 4)] for la, lo in h3.cell_to_boundary(c)]
        polys.append([ring + [ring[0]]])
        pts += cell_points(c)
    return {"type": "MultiPolygon", "coordinates": polys}, pts


def place_country(at):
    """Country of a named place [lat, lon]: the kit's country_at, or, for a coastal or border town that the kit's
    thinned outlines miss (Manama, Nicosia), the commonest country on rings 5, 10 and 25 km around it."""
    if not at:
        return None
    lat, lon = at
    cc = geo.country_at(lat, lon)
    if cc:
        return cc
    import math
    seen = {}
    for r_km in (5, 10, 25):
        for k in range(12):
            a = math.radians(30 * k)
            la = lat + r_km / 111.2 * math.cos(a)
            lo = lon + r_km / (111.2 * max(math.cos(math.radians(lat)), 0.01)) * math.sin(a)
            c = geo.country_at(la, lo)
            if c:
                seen[c] = seen.get(c, 0) + 1
        if seen:
            return max(sorted(seen), key=seen.get)
    return None


def event_span(day, h0, h1):
    """An event's UTC hours as times: start of its first hour, start of its last hour, and end of its last hour (the
    moment it was last true, used as data_as_of). None without hours."""
    if h0 is None or h1 is None:
        return None
    d = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return {"start": utc(d + timedelta(hours=h0)), "last": utc(d + timedelta(hours=h1)),
            "end": utc(d + timedelta(hours=h1 + 1))}


def where(r):
    """' near Doha' for a place, ' in Georgia, 220 km W of Tbilisi' for a country (board.py's near_kind and
    near_ref, tools/area_names.py), '' unnamed."""
    near = r.get("near")
    if not near:
        return ""
    if r.get("near_kind") == "country":
        return " in " + near + (", " + r["near_ref"] if r.get("near_ref") else "")
    return " near " + near


def plain_day(day):
    return datetime.strptime(day, "%Y-%m-%d").strftime("%d %b %Y").lstrip("0")


def tags(points, extra=None, near_at=None):
    """Countries any sample point falls in, plus the country of the named place the title uses ("near Doha" is
    tagged QA even when Doha sits just outside the cell)."""
    cc = set(geo.countries_in(points))
    pc = place_country(near_at)
    if pc:
        cc.add(pc)
    out = {"countries": sorted(cc), "ncf": NCF, "sector": vocab.derive_sectors(NCF)}
    out.update(extra or {})
    return out


# Every item covers one whole UTC day and the source gives no time (tic-feed/2, kit 0.5.6): `day` precision means
# data_as_of is midnight UTC on that date, and consumers show a date, never a clock time.
DAY_ONLY = {"data_as_of_precision": "day"}


def build(board, days, now=None):
    now = now or datetime.now(timezone.utc)
    day = (board.get("freshness") or {}).get("aircraft_day")
    if not day:
        raise ValueError("board has no aircraft day")
    as_of, published = f"{day}T23:59:59Z", utc(now)   # as_of: the feed header only; items are date-only (DAY_ONLY)
    cov = coverage(days, day)
    src = [{**ADSBLOL, "accessed_at": published}]
    base = {**COMMON, "data_as_of": f"{day}T00:00:00Z", **DAY_ONLY, "published_at": published, "sources": src, "status_class": "assessed"}
    if cov is not None:
        base["coverage_fraction"] = cov
    feats = []

    def add(geom, props):
        merged = {**base, **props}
        if merged.get("data_as_of_precision") is None:    # an item with a real time (an event) is not date-only
            merged.pop("data_as_of_precision", None)
        feats.append({"type": "Feature", "geometry": geom, "properties": merged})

    add(None, {
        "id": f"noisefloor-summary-{day}", "kind": "observation", "tier": "routine", "product_category": "current",
        "title": board.get("summary") or f"GPS interference picture for {day}",
        "summary": board.get("brief") or "", "countries": [], "precision_class": "none",
        "requirement_ids": ["NF-PIR-1", "NF-PIR-2"], "ncf": NCF, "sector": vocab.derive_sectors(NCF),
        "visual": {"type": "map", "url": f"{SITE_URL}/map"}})

    ch = board.get("changes") or {}
    rule = ch.get("rule", "")
    for r in ch.get("new") or []:
        geom, pts = h3_polygon(r["region"])
        add(geom, {
            "id": f"noisefloor-new-{r['region']}-{day}", "kind": "observation", "tier": "anomaly",
            "product_category": "current", "precision_class": "area",
            "title": f"GPS interference newly seen{where(r)}",
            "summary": f"At jamming scale on {r['days_in_last7']} of the last 7 days and on none of the 30 before.",
            "measure": {"name": "days_at_jamming_scale_last7", "value": r["days_in_last7"], "expected": 0},
            "baseline_ref": {"id": "noisefloor-regions-30d", "window": "30 days before the last 7", "type": "rolling",
                             "version": "1", "rule": rule},
            "requirement_ids": ["NF-PIR-2"], "warning_problem_id": "NF-WP-1", "indicator_id": "NF-IND-1",
            "hypothesis_id": "NF-WP-1-H1", "direction": "supports", "indicator_state": "present",
            **tags(pts, near_at=r.get("near_at"))})
    for key in ("ended", "below"):      # ended passes board.ended_check(); below only dropped under the 3-cell mark
        for r in ch.get(key) or []:
            geom, pts = h3_polygon(r["region"])
            share = r.get("share7_pct")
            seen = (f"Severe GPS error over the last 7 days: {share:g}% of {r.get('min_aircraft', 0):,}+ aircraft-cells a day"
                    if share is not None else "No aircraft-cells over the last 7 days")
            if key == "ended":
                title, says = "ended", (f"{seen}, at background level with enough aircraft to tell. Check position loss "
                                        "before reading this as an easing (assumption NF-AS-3).")
            else:
                title, says = "fell below jamming scale", (f"{seen}; that is not yet background level, or too few aircraft "
                                                           "were seen to tell, so this is not an end.")
            add(geom, {
                "id": f"noisefloor-{key}-{r['region']}-{day}", "kind": "observation", "tier": "routine",
                "product_category": "current", "precision_class": "area",
                "title": f"GPS interference {title}{where(r)}",
                "summary": f"At jamming scale on {r['days_in_prior30']} of the 30 days before last week, and on none of "
                           f"the last 7. {says}",
                "requirement_ids": ["NF-PIR-2"], **tags(pts, near_at=r.get("near_at"))})

    hs = board.get("hotspots") or {}
    for a in hs.get("areas") or []:
        if a.get("change") is None or a.get("box") is None or a["change"] < 5 or max(a["today"] or 0, a["median30"] or 0) < 5:
            continue
        add(box_polygon(a["box"]), {
            "id": f"noisefloor-rise-{a['name'].lower().replace(' ', '-').replace('/', '')}-{day}",
            "kind": "observation", "tier": "anomaly", "product_category": "current", "precision_class": "area",
            "title": f"Severe GPS error rose over {a['name']}",
            "summary": f"{a['today']:g}% of aircraft with severe GPS error, against a 30-day median of {a['median30']:g}% "
                       f"(+{a['change']:g} points).",
            "measure": {"name": "severe_share_pct", "value": a["today"], "expected": a["median30"]},
            "baseline_ref": {"id": "noisefloor-areas-30d", "window": "previous 30 days", "type": "rolling", "version": "1"},
            "requirement_ids": ["NF-PIR-1"], "warning_problem_id": "NF-WP-2", "indicator_id": "NF-IND-2",
            "hypothesis_id": "NF-WP-2-H1", "direction": "supports", "indicator_state": "present",
            **tags(box_points(a["box"]))})

    te = board.get("top_events") or {}
    for i, e in enumerate(te.get("events") or []):
        eday = te.get("day", day)
        span = event_span(eday, e.get("h0"), e.get("h1"))
        major = e["tier"] == "major"
        cells = [c for c in e.get("cells") or [] if c]
        if cells:                       # the event's own H3 res-2 regions, as the analysis found them
            geom, pts = h3_area(cells)
            place = {"precision_class": "area"}
        else:                           # an older event file without cells: the mean of its regions' centres
            geom, pts = {"type": "Point", "coordinates": [e["lon"], e["lat"]]}, [(e["lat"], e["lon"])]
            place = {"precision_class": "approximate"}
        add(geom, {
            "id": f"noisefloor-event-{eday}-{i + 1}", "kind": "observation",
            "tier": "anomaly" if major else "routine", "product_category": "current", **place,
            "title": f"{e['tier'].capitalize()} GPS interference event{where(e)}",
            "summary": " ".join(x for x in [
                f"Graded {e['tier']} by Noisefloor's events rule"
                + (" (25 points or more over the same hour's usual share)." if major else
                   " (10 to 25 points over the same hour's usual share): above its own baseline but below the major "
                   "grade, so sent as routine. Noisefloor's validation reads majors first."),
                f"Between {span['start'][11:16]} and {span['last'][11:13]}:59 UTC on {plain_day(eday)}." if span else "",
                (f"Its highest region-hour had severe GPS error (worse than 93 m) in {e['peak']:g}% of "
                 f"aircraft-cell-hours, and its largest rise over a region's usual share for that hour was "
                 f"{e['excess']:g} points." if e.get("peak") is not None and e.get("excess") is not None else ""),
                (f"Across {len(cells)} region{'s' if len(cells) != 1 else ''} about 300 km across." if cells else ""),
                "Coincides with an announced test." if e.get("test") else ""] if x),
            "measure": {"name": "peak_severe_share_pct", "value": e.get("peak"), "excess": e.get("excess"),
                        "unit": "percent of aircraft-cell-hours with severe GPS error (NACp below 8, worse than 93 m) in "
                                "the event's highest region-hour; excess is the largest rise in points over a region's "
                                "same-hour usual share"},
            "baseline_ref": {"id": "noisefloor-events", "window": "same hour on up to 14 earlier days", "type": "rolling",
                             "version": "1"},
            **({"data_as_of": span["end"], "data_as_of_precision": None, "period": {"start": span["start"],
                "end": span["end"]}} if span else {}),
            "requirement_ids": ["NF-PIR-1"], **tags(pts, near_at=e.get("near_at"))})

    sp = (board.get("spoofing") or {}).get("new_places") or {}
    for i, t in enumerate((sp.get("new") or [])[:NEW_SPOOF_ITEMS]):
        vic = [v for v in t.get("victims") or [] if v.get("region")]
        if not vic:                     # the item is placed where the aircraft really were; none known, no item
            continue
        geom, pts = h3_polygon(vic[0]["region"])
        over = ", ".join(dict.fromkeys(v["near"] for v in vic if v.get("near"))) or "unnamed areas"
        at = t.get("near") or f"{abs(t['lat']):.1f}°{'N' if t['lat'] >= 0 else 'S'}, {abs(t['lon']):.1f}°{'E' if t['lon'] >= 0 else 'W'}"
        far = t.get("km_from_aircraft")
        add(geom, {
            "id": f"noisefloor-spoof-new-{sp['day']}-{i + 1}", "kind": "observation", "tier": "anomaly",
            "product_category": "current", "precision_class": "area", "data_as_of": f"{sp['day']}T00:00:00Z",
            "title": f"Aircraft shown at a new false position near {at}",
            "summary": (f"{t['aircraft']} aircraft over or near {over} had receivers showing them near {at} on "
                        f"{datetime.strptime(sp['day'], '%Y-%m-%d').strftime('%d %b %Y').lstrip('0')}"
                        + (f", about {far:,} km from where most of them were" if far else "") + f"; no false position within "
                        f"10 km in the {sp['history_days']} days before with a spoofing targets file. The false "
                        "position is where receivers were told they were, not a transmitter site."),
            "measure": {"name": "aircraft_shown_at_new_false_position", "value": t["aircraft"], "expected": 0},
            "baseline_ref": {"id": "noisefloor-spoof-targets", "window": f"{sp['history_days']} earlier days with a "
                             "targets file (up to 30)", "type": "rolling", "version": "1", "rule": sp.get("rule", "")},
            "requirement_ids": ["NF-EEI-3"], **tags(pts)})

    lv = (board.get("spoofing") or {}).get("place_levels") or {}
    for i, t in enumerate((lv.get("above") or [])[:ABOVE_SPOOF_ITEMS]):
        regs = [r for r in t.get("regions") or [] if r.get("region")]
        if not regs:                    # placed where the aircraft really were; none known, no item
            continue
        geom, pts = h3_polygon(regs[0]["region"])
        over = ", ".join(dict.fromkeys(r["near"] for r in regs if r.get("near"))) or "unnamed areas"
        at = t.get("near") or f"{abs(t['lat']):.1f}°{'N' if t['lat'] >= 0 else 'S'}, {abs(t['lon']):.1f}°{'E' if t['lon'] >= 0 else 'W'}"
        usual = f"{t['usual']:g}"
        add(geom, {
            "id": f"noisefloor-spoof-above-{lv['day']}-{i + 1}", "kind": "observation", "tier": "anomaly",
            "product_category": "current", "precision_class": "area", "data_as_of": f"{lv['day']}T00:00:00Z",
            "title": f"More aircraft than usual shown at the false position near {at}",
            "summary": (f"{t['latest']} aircraft, mostly over or near {over}, had receivers showing them near {at} on "
                        f"{datetime.strptime(lv['day'], '%Y-%m-%d').strftime('%d %b %Y').lstrip('0')}, against a usual "
                        f"{usual} a day (median of the {lv['earlier_days']} earlier days with a spoofing targets file). "
                        "The false position is where receivers were told they were, not a transmitter site."),
            "measure": {"name": "aircraft_shown_at_false_position", "value": t["latest"], "expected": t["usual"]},
            "baseline_ref": {"id": "noisefloor-spoof-place-level", "window": f"{lv['earlier_days']} earlier days with a "
                             "targets file (up to 30)", "type": "rolling", "version": "1", "rule": lv.get("rule", "")},
            "requirement_ids": ["NF-EEI-3"], **tags(pts)})

    rl = (board.get("spoofing") or {}).get("region_levels") or {}
    for i, r in enumerate((rl.get("above") or [])[:ABOVE_REGION_ITEMS]):
        geom, pts = h3_polygon(r["region"])
        at = r.get("near") or f"{abs(r['lat']):.1f}°{'N' if r['lat'] >= 0 else 'S'}, {abs(r['lon']):.1f}°{'E' if r['lon'] >= 0 else 'W'}"
        share = 100 * r["active_ah"] / r["aircraft_hours"] if r.get("aircraft_hours") else None
        add(geom, {
            "id": f"noisefloor-spoof-region-above-{rl['day']}-{i + 1}", "kind": "observation", "tier": "anomaly",
            "product_category": "current", "precision_class": "area", "data_as_of": f"{rl['day']}T00:00:00Z",
            "title": f"More GPS spoofing than usual near {at}",
            "summary": (f"Aircraft in the region about 300 km across near {at} spent {r['active_ah']} aircraft-hours in "
                        f"active spoofing episodes on "
                        f"{datetime.strptime(rl['day'], '%Y-%m-%d').strftime('%d %b %Y').lstrip('0')}"
                        + (f" ({share:.1f}% of {r['aircraft_hours']:,} aircraft-hours)" if share is not None else "")
                        + f", against a usual {r['usual']:g} (median of the {rl['earlier_days']} earlier days with "
                        "regional shares). Counted where the aircraft really were, not where they were shown; not a "
                        "transmitter site."
                        + (f" Coincides with an announced US GPS test that day (FAA flight advisory "
                           f"{', '.join(r['tests'])}), whose area covers the region." if r.get("tests") else "")),
            "measure": {"name": "spoofed_active_aircraft_hours", "value": r["active_ah"], "expected": r["usual"]},
            "baseline_ref": {"id": "noisefloor-spoof-region-level", "window": f"{rl['earlier_days']} earlier days with "
                             "regional shares (up to 30)", "type": "rolling", "version": "1", "rule": rl.get("rule", "")},
            "requirement_ids": ["NF-EEI-3"], **tags(pts)})

    swx_items(board.get("swx") or {}, add, published)

    return {
        "type": "FeatureCollection", "contract": CONTRACT, "program": "noisefloor", "generated_at": published,
        "data_as_of": as_of, "method_version": METHOD,
        "licence": "ODbL 1.0 for items derived from adsb.lol; CC BY 4.0 for the space weather items (limb S4 from UCAR "
                   "COSMIC-2, ROTI from IGS stations); text CC BY 4.0",
        "attribution": "Noisefloor, The Intelligence Company. Aircraft data: adsb.lol contributors (ODbL). COSMIC-2 data: "
                       "UCAR COSMIC Program (CDAAC). GNSS station data: International GNSS Service (IGS) and the station "
                       "operators, via BKG.",
        "language_key": "https://github.com/metacog-osint/noise-floor/blob/main/doctrine/kit/docs/language-key.md",
        "features": feats,
    }


def hour_span(day, hour):
    d = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(hours=hour)
    return {"start": utc(d), "end": utc(d + timedelta(hours=1))}


def solar(lst):
    """Local solar time as "21:30" (the files give hours as a decimal)."""
    if lst is None:
        return None
    m = int(round(lst * 60)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


SWX_TAGS = {"ncf": SWX_NCF, "sector": vocab.derive_sectors(SWX_NCF), "pmesii_pt": ["physical_environment"],
            "ascope": ["areas"], "requirement_ids": ["NF-PIR-3", "NF-EEI-5"], "kind": "observation", "tier": "routine",
            "product_category": "current"}


def swx_items(sw, add, published):
    """Limb S4 and ground ROTI items (routine observations, no baseline): see the module docstring."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import swx_site
    lm = sw.get("limb") or {}
    sats = lm.get("satellites") or []
    for i, c in enumerate(lm.get("top") or []):
        geom, pts = h3_polygon(c["cell"])
        span = hour_span(lm["day"], c["hour"])
        near = c.get("near")
        at = near or f"{abs(c['lat']):.0f}°{'N' if c['lat'] >= 0 else 'S'}, {abs(c['lon']):.0f}°{'E' if c['lon'] >= 0 else 'W'}"
        lst = solar(c.get("lst"))
        add(geom, {
            **SWX_TAGS, "id": f"noisefloor-limb-s4-{lm['day']}-{i + 1}", "precision_class": "area",
            "title": f"Among the day's highest limb S4 readings from COSMIC-2, {'near ' if near else 'at '}{at}",
            "summary": (f"{swx_site.LIMB_LABEL}: 95th percentile {c['p95']:.2f} from {c['n']} ten-second values on "
                        f"{c['links']} radio-occultation link{'s' if c['links'] != 1 else ''}, in the hour from "
                        f"{span['start'][11:16]} UTC on {plain_day(lm['day'])}"
                        + (f" (about {lst} local solar time)" if lst else "")
                        + ", that cell's highest hour. The cell is about 840 km across, and the place along the ray "
                        "is uncertain by up to about 2,000 km. One of the day's "
                        f"{len(lm['top'])} highest cells at least 1,500 km apart, leaving out cell-hours where most "
                        "values came while UCAR's interference index was raised"
                        + (f" ({c['rfi'] * 100:.0f}% of this hour's values did)" if c.get("rfi") else "")
                        + f". {swx_site.LIMB_NOT_GROUND} These are the day's highest values, not a departure from a "
                        f"usual level. {len(sats)} of {COSMIC2_SATELLITES} COSMIC-2 satellites delivered data"
                        + (f" ({', '.join(sats)})" if sats else "")
                        + ". Checked against INGV eSWua ground scintillation receivers on 25 held-out days (AUC 0.834)."),
            "measure": {"name": "limb_s4_p95", "value": c["p95"], "max": c["max"],
                        "unit": swx_site.LIMB_LABEL + "; unitless 95th percentile of the cell-hour's 10 s values"},
            "data_as_of": span["end"], "data_as_of_precision": None, "period": span,
            "sources": [{**COSMIC2, "accessed_at": lm.get("as_of") or published}],
            "coverage_fraction": round(len(sats) / COSMIC2_SATELLITES, 3),
            "visual": {"type": "map", "url": f"{SITE_URL}/map#day={lm['day']}&ls=1"},
            **tags(pts, near_at=c.get("near_at"))})
    ro = sw.get("roti") or {}
    n_st = len(ro.get("stations") or [])
    for s in ro.get("stations") or []:
        if s.get("max_p95") is None or s.get("hour") is None:
            continue
        span = hour_span(ro["day"], s["hour"])
        lst = solar(s.get("lst"))
        place = s.get("place") or s["id"]
        add({"type": "Point", "coordinates": [s["lon"], s["lat"]]}, {
            **SWX_TAGS, "id": f"noisefloor-roti-{ro['day']}-{s['id'].lower()}", "precision_class": "point",
            "title": f"Ground ROTI at {place}: the highest hour of {plain_day(ro['day'])}",
            "summary": (f"{swx_site.ROTI_LABEL}: at IGS station {s['id']} ({place}) the highest hourly 95th percentile on "
                        f"{plain_day(ro['day'])} was {s['max_p95']:.2f} TECU/min, in the hour from "
                        f"{span['start'][11:16]} UTC" + (f" (about {lst} local solar time)" if lst else "")
                        + ", from GPS and Galileo paths above 30° whose 350 km pierce points lie within about 550 km "
                        f"of the station; {s['hours']} of 24 hours had values. {swx_site.ROTI_NOT_S4} This is the "
                        "day's highest hour, not a departure from a usual level. Checked against INGV eSWua ground "
                        "scintillation receivers on 25 held-out days (AUC 0.887)."),
            "measure": {"name": "roti_p95", "value": s["max_p95"],
                        "unit": "TECU/min; " + swx_site.ROTI_LABEL + ", 95th percentile of the station-hour's 5-minute values"},
            "data_as_of": span["end"], "data_as_of_precision": None, "period": span,
            "sources": [{**IGS, "accessed_at": ro.get("as_of") or published}],
            "coverage_fraction": round(min(1.0, n_st / ROTI_STATIONS), 3),
            "visual": {"type": "map", "url": f"{SITE_URL}/map#day={ro['day']}&rt=1"},
            **tags([(s["lat"], s["lon"])], near_at=[s["lat"], s["lon"]])})


def check(feed):
    problems = []
    for f in feed["features"]:
        problems += [(f["properties"]["id"], *p) for p in contract.check(f) if p[1] == "error"]
    return problems


def write(site, board=None, now=None):
    board = board if board is not None else load(os.path.join(site, "data", "board.json"))
    if not board:
        raise ValueError("no board.json")
    feed = build(board, load(os.path.join(site, "data", "gnss", "days.json"), []) or [], now)
    problems = check(feed)
    if problems:
        raise ValueError(f"{len(problems)} contract errors, first: {problems[0]}")
    out = os.path.join(site, "data", "feed.geojson")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(feed, f, separators=(",", ":"), ensure_ascii=False)
    return out, len(feed["features"])


def main():
    site = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "site")
    try:
        out, n = write(site)
        print(f"feed_v2: {n} items -> {out}")
    except Exception as e:              # the feed is an extra; it must never stop a deploy
        print(f"::warning::contract v2 feed skipped: {type(e).__name__}: {str(e)[:200]}")


if __name__ == "__main__":
    main()
