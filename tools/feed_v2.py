#!/usr/bin/env python3
"""feed_v2.py: Noisefloor's items in The Intelligence Company's feed contract v2: SITE/data/feed.geojson.

  python tools/feed_v2.py [SITE]

Built at deploy, right after board.py, from SITE/data/board.json and SITE/data/gnss/days.json. Every item here is a
measurement (kind observation): regions that newly reached jamming scale this week, regions where it ended, named areas
whose severe share rose 5 points or more above their 30-day median, the day's major and notable events, and up to five
places where aircraft were newly shown at a false position (spoofing; tools/spoof_site.py new_targets(), placed where
the aircraft really were), plus one daily summary. Warnings (judged, with likelihood and confidence) come later through doctrine/indicators.json.

The doctrine kit's tradecraft linter (doctrine/kit) checks the feed before it is written. A feed that fails is not
written, the reason is printed, and the deploy carries on.
"""
import json
import os
import statistics
import sys
from datetime import datetime, timezone

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


def h3_polygon(cell):
    import h3
    ring = [[round(lo, 4), round(la, 4)] for la, lo in h3.cell_to_boundary(cell)]
    return {"type": "Polygon", "coordinates": [ring + [ring[0]]]}, [(la, lo) for lo, la in ring]


def tags(points, extra=None):
    cc = geo.countries_in(points)
    out = {"countries": cc, "ncf": NCF, "sector": vocab.derive_sectors(NCF)}
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
        feats.append({"type": "Feature", "geometry": geom, "properties": {**base, **props}})

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
        near = r.get("near")
        add(geom, {
            "id": f"noisefloor-new-{r['region']}-{day}", "kind": "observation", "tier": "anomaly",
            "product_category": "current", "precision_class": "area",
            "title": f"GPS interference newly seen{' near ' + near if near else ''}",
            "summary": f"At jamming scale on {r['days_in_last7']} of the last 7 days and on none of the 30 before.",
            "measure": {"name": "days_at_jamming_scale_last7", "value": r["days_in_last7"], "expected": 0},
            "baseline_ref": {"id": "noisefloor-regions-30d", "window": "30 days before the last 7", "type": "rolling",
                             "version": "1", "rule": rule},
            "requirement_ids": ["NF-PIR-2"], "warning_problem_id": "NF-WP-1", "indicator_id": "NF-IND-1",
            "hypothesis_id": "NF-WP-1-H1", "direction": "supports", "indicator_state": "present",
            **tags(pts)})
    for r in ch.get("ended") or []:
        geom, pts = h3_polygon(r["region"])
        near = r.get("near")
        add(geom, {
            "id": f"noisefloor-ended-{r['region']}-{day}", "kind": "observation", "tier": "routine",
            "product_category": "current", "precision_class": "area",
            "title": f"GPS interference no longer seen{' near ' + near if near else ''}",
            "summary": f"At jamming scale on {r['days_in_prior30']} of the 30 days before last week, and on none of the "
                       "last 7. Check position loss before reading this as an easing (assumption NF-AS-3).",
            "requirement_ids": ["NF-PIR-2"], **tags(pts)})

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
        near = e.get("near")
        hours = f"{e['h0']}-{e['h1']} UTC" if e.get("h0") is not None and e.get("h1") is not None else ""
        add({"type": "Point", "coordinates": [e["lon"], e["lat"]]}, {
            "id": f"noisefloor-event-{te.get('day', day)}-{i + 1}", "kind": "observation", "tier": "anomaly",
            "product_category": "current", "precision_class": "approximate",
            "title": f"{e['tier'].capitalize()} GPS interference event{' near ' + near if near else ''}",
            "summary": " ".join(x for x in [f"Graded {e['tier']} by Noisefloor's events rule.", hours,
                                            "Coincides with an announced test." if e.get("test") else ""] if x),
            "measure": {"name": "peak_degraded_aircraft", "value": e.get("peak"), "excess": e.get("excess")},
            "baseline_ref": {"id": "noisefloor-events", "window": "same hour on up to 14 earlier days", "type": "rolling",
                             "version": "1"},
            "requirement_ids": ["NF-PIR-1"], **tags([(e["lat"], e["lon"])])})

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
                        "transmitter site."),
            "measure": {"name": "spoofed_active_aircraft_hours", "value": r["active_ah"], "expected": r["usual"]},
            "baseline_ref": {"id": "noisefloor-spoof-region-level", "window": f"{rl['earlier_days']} earlier days with "
                             "regional shares (up to 30)", "type": "rolling", "version": "1", "rule": rl.get("rule", "")},
            "requirement_ids": ["NF-EEI-3"], **tags(pts)})

    return {
        "type": "FeatureCollection", "contract": CONTRACT, "program": "noisefloor", "generated_at": published,
        "data_as_of": as_of, "method_version": METHOD,
        "licence": "ODbL 1.0 (derived from adsb.lol); text CC BY 4.0",
        "attribution": "Noisefloor, The Intelligence Company. Aircraft data: adsb.lol contributors (ODbL).",
        "language_key": "https://github.com/metacog-osint/noise-floor/blob/main/doctrine/kit/docs/language-key.md",
        "features": feats,
    }


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
