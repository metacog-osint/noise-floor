#!/usr/bin/env python3
"""Add the daily map and event files to the site's data and rebuild the day index. Standard library only.

The 20 validated days are committed in site/data/gnss/ and site/data/events/. Days made by the daily workflow are
stored as assets on this repo's pnt-data-YYYY-MM releases. The deploy job downloads them and runs

  python3 tools/site_days.py DIR [SITE]   # DIR/<day>.map.json -> SITE/data/gnss/<day>.json, rebuild days.json;
                                          # DIR/<day>.{anomalies,bursts,sbas}.json -> SITE/data/events/<day>.json;
                                          # DIR/<day>.hotspots.json (every day) -> SITE/data/trend.json;
                                          # DIR/faa_gps_tests.json -> announced tests in every events file
                                          # then SITE/feed.xml: Atom feed of the latest 30 days' summaries

A committed file wins over a downloaded one for the same day. The index keeps the committed days' notes and
marks every other day "daily": made automatically, not reviewed by a person.
"""
import json
import math
import os
import re
import shutil
import sys
from datetime import date, timedelta
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GNSS = os.path.join(ROOT, "site", "data", "gnss")
EVENTS = os.path.join(ROOT, "site", "data", "events")
MAP_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.map\.json$")
HOT_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.hotspots\.json$")
MEASURE = {"gross": "jam", "capable_10m": "acc"}
FEED = os.path.join(ROOT, "site", "feed.xml")
PLACES = os.path.join(ROOT, "site", "data", "places.json")
SUN_ALERTS = os.path.join(ROOT, "site", "data", "sun", "alerts.json")   # written at deploy by tools/sun_alerts.py
SITE_URL = "https://noisefloor.theintelligence.company"
TIER = {"major": "Major", "notable": "Notable", "minor": "Minor"}


def stats(obj):
    """Per-day counts for the map's day index and timeline strip:
    hexes      hexes with 5 or more aircraft
    jam_hexes  of those, GPSJam-style share of live bad aircraft >= 10% (the map's top two jamming-scale classes)
    acc_hexes  hexes with 5 or more 10 m-capable aircraft and >= 50% of them below 10 m (top two accuracy classes)"""
    cols = obj["cols"]
    ia, ib, ic, icb = (cols.index(k) for k in ("aircraft", "bad_live", "capable", "capable_bad10"))
    n5 = [c for c in obj["cells"] if c[ia] >= 5]
    return {"hexes": len(n5), "jam_hexes": sum(1 for c in n5 if 100 * max(c[ib] - 1, 0) / c[ia] >= 10),
            "acc_hexes": sum(1 for c in obj["cells"] if c[ic] >= 5 and 100 * max(c[icb] - 1, 0) / c[ic] >= 50)}


def sbas_runs(sbas):
    """Flagged SBAS hours as runs: [{area, start, end, state}] (consecutive hours with the same state)."""
    runs = []
    for area, v in (sbas.get("areas") or {}).items():
        for h in v.get("hours") or []:
            if not h or h["state"].startswith("ok"):
                continue
            last = runs[-1] if runs else None
            if last and last["area"] == area and last["state"] == h["state"] and last["end"] == h["hour"] - 1:
                last["end"] = h["hour"]
            else:
                runs.append({"area": area, "start": h["hour"], "end": h["hour"], "state": h["state"]})
    return runs


def events(day, anomalies, bursts, sbas):
    """The map page's event file for a day, from pnt_analysis outputs: anomaly events (ranked as the analysis ranks
    them), burst events and SBAS flags. Aggregates and H3 res-2 region ids only."""
    out = {"day": day, "licence": "ODbL 1.0; derived from adsb.lol",
           "baseline_days": len(anomalies.get("baseline_days") or []), "anomaly_note": anomalies.get("error", ""),
           "burst_basis": (bursts.get("events") or [{}])[0].get("basis", ""), "anomalies": [], "bursts": [],
           "sbas": sbas_runs(sbas)}
    for e in anomalies.get("events") or []:
        out["anomalies"].append({"m": MEASURE[e["measure"]], "tier": e["tier"], "h0": e["start_hour"], "h1": e["end_hour"],
                                 "regions": e["regions"], "rh": e["region_hours"], "peak": e["peak_share"],
                                 "excess": e["peak_excess"], "lat": e["lat"], "lon": e["lon"], "cells": e.get("cells", []),
                                 "hs": e.get("heavy_share")})
    for e in bursts.get("events") or []:
        out["bursts"].append({"t0": e["start"], "t1": e["end"], "peak": e["peak_aircraft"], "regions": e["regions"],
                              "lat": e["lat"], "lon": e["lon"], "cells": e.get("cells", []), "hs": e.get("heavy_share")})
    return out


def write_events(day, folder, out_dir):
    """Write out_dir/<day>.json from folder/<day>.{anomalies,bursts,sbas}.json; False if any is missing."""
    src = {k: os.path.join(folder, f"{day}.{k}.json") for k in ("anomalies", "bursts", "sbas")}
    if not all(os.path.exists(p) for p in src.values()):
        return False
    loaded = {}
    for k, p in src.items():
        with open(p, encoding="utf-8") as f:
            loaded[k] = json.load(f)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"{day}.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(events(day, loaded["anomalies"], loaded["bursts"], loaded["sbas"]), f, separators=(",", ":"), ensure_ascii=False)
    return True


def write_trend(days, folder, path):
    """The charts page's daily hotspot trend from folder/<day>.hotspots.json. Returns the number of days found."""
    found = {}
    for day in days:
        p = os.path.join(folder, f"{day}.hotspots.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                found[day] = json.load(f)["regions"]
    if not found:
        return 0
    first, last = date.fromisoformat(min(found)), date.fromisoformat(max(found))
    order = [(first + timedelta(days=k)).isoformat() for k in range((last - first).days + 1)]   # missing days are gaps
    names = list(found[max(found)])                       # the newest day's areas, in its order
    regions = {}
    for name in names:
        r = [(found.get(d) or {}).get(name) or {} for d in order]
        regions[name] = {"box": next((x["box"] for x in r if x.get("box")), None),
                         "share": [x.get("share") for x in r], "aircraft_hexes": [x.get("aircraft_hexes") for x in r]}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"licence": "ODbL 1.0; derived from adsb.lol", "measure": "share of aircraft-hexes worse than 93 m, live",
                   "days": order, "regions": regions}, f, separators=(",", ":"), ensure_ascii=False)
    return len(found)


def km(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 12742 * math.asin(min(1.0, math.sqrt(h)))


def reach_nm(test):
    """Widest radius in an advisory (the FL400 one): aircraft at cruise are affected farthest out."""
    return max(test.get("radii_nm", {}).values() or [0])


def tests_on(tests, day):
    """Announced tests with a window overlapping the UTC day, trimmed to that day's windows."""
    d0, d1, out = f"{day}T00:00Z", f"{day}T23:59Z", []
    for t in tests:
        w = [x for x in t["windows"] if x[0] <= d1 and x[1] >= d0]
        if w:
            out.append({"id": t["id"], "place": t.get("place", ""), "centre": t["centre"], "radii_nm": t.get("radii_nm", {}),
                        "windows": w, "url": t.get("notice_url", "")})
    return out


def annotate(ev, tests):
    """Add the day's announced tests to an events file, and tag each anomaly or burst that overlaps one in time and
    lies within its widest radius. A tag means "consistent with an announced test", not proof."""
    day = ev["day"]
    ev["tests"] = tests_on(tests, day)
    for e in ev.get("anomalies", []) + ev.get("bursts", []):
        if "t0" in e:
            s, f = f"{day}T{e['t0'][:5]}Z", f"{day}T{e['t1'][:5]}Z"
        else:
            s, f = f"{day}T{e['h0']:02d}:00Z", f"{day}T{e['h1']:02d}:59Z"
        e.pop("test", None)
        for t in ev["tests"]:
            if any(w[0] <= f and w[1] >= s for w in t["windows"]) and km((e["lat"], e["lon"]), t["centre"]) <= reach_nm(t) * 1.852:
                e["test"] = t["id"]
                break
    return ev


def annotate_all(events_dir, tests_path):
    """Annotate every events file (committed and daily) with the announced tests. Returns (files, tagged events)."""
    if not os.path.exists(tests_path) or not os.path.isdir(events_dir):
        return 0, 0
    with open(tests_path, encoding="utf-8") as f:
        tests = list(json.load(f).get("tests", {}).values())
    files = tagged = 0
    for name in sorted(os.listdir(events_dir)):
        if not name.endswith(".json"):
            continue
        p = os.path.join(events_dir, name)
        with open(p, encoding="utf-8") as f:
            ev = annotate(json.load(f), tests)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            json.dump(ev, f, separators=(",", ":"), ensure_ascii=False)
        files += 1
        tagged += sum(1 for e in ev.get("anomalies", []) + ev.get("bursts", []) if e.get("test"))
    return files, tagged


def ll2(lat, lon):
    return f"{abs(lat):.1f}°{'N' if lat >= 0 else 'S'} {abs(lon):.1f}°{'E' if lon >= 0 else 'W'}"


def nearest(places, lat, lon, limit_km=350):
    best, name = limit_km, None
    for p in places:
        d = km((lat, lon), (p[1], p[2]))
        if d < best:
            best, name = d, p[0]
    return name


def day_summary(d, prior, ev, places):
    """(title, html) for one day: hexes at jamming scale against the 30 days before, the top jamming-scale events
    with the nearest named place, burst and announced-test counts. Mirrors the home page's "on the map today"."""
    med = sorted(prior)[len(prior) // 2] if prior else None
    top = [e for e in (ev or {}).get("anomalies", []) if e.get("m") == "jam" and e.get("tier") != "minor"][:5]
    n_major = sum(1 for e in (ev or {}).get("anomalies", []) if e.get("m") == "jam" and e.get("tier") == "major")
    title = (f"{d['day']}: {d['jam_hexes']:,} hexes at jamming scale" + (f" (30-day median {med:,})" if med is not None else "")
             + (f", {n_major} major event{'s' if n_major != 1 else ''}" if n_major else ""))
    link = f"{SITE_URL}/map#day={d['day']}&m=jam"
    parts = [f"<p>{d['jam_hexes']:,} hexes at jamming scale" + (f" (30-day median {med:,})" if med is not None else "")
             + f", out of {d['hexes']:,} with 5 or more aircraft." + (f" Note: {escape(d['note'])}." if d.get("note") else "") + "</p>"]
    if ev is None:
        parts.append("<p>No event file for this day.</p>")
    else:
        items = []
        for e in top:
            near = nearest(places, e["lat"], e["lon"])
            url = f"{SITE_URL}/map#day={d['day']}&m=jam&v={e['lat']:.2f},{e['lon']:.2f},6"
            hs = e.get("hs")
            items.append(f'<li><a href="{escape(url)}">{TIER.get(e["tier"], e["tier"])}: {e["peak"]:.0f}% of aircraft degraded around '
                         f'{ll2(e["lat"], e["lon"])}' + (f" (near {escape(near)})" if near else "") + "</a>, "
                         f'{e["h0"]:02d}:00–{e["h1"]:02d}:59 UTC, {e["excess"]:.0f} points above usual'
                         + (f"; {hs * 100:.0f}% of the degraded aircraft were A350s or A380s" if hs is not None and hs >= 0.5 else "")
                         + (f"; fits announced test {escape(e['test'])}" if e.get("test") else "") + ".</li>")
        if items:
            parts.append("<ul>" + "".join(items) + "</ul>")
        else:
            parts.append("<p>No major or notable jamming-scale anomaly events.</p>")
        extra = []
        if ev.get("bursts"):
            extra.append(f"{len(ev['bursts'])} minute-level bursts.")
        if ev.get("tests"):
            extra.append(f"{len(ev['tests'])} announced US GPS tests.")
        if extra:
            parts.append("<p>" + " ".join(extra) + "</p>")
    how = "From the automatic daily run, not reviewed by a person." if d.get("daily") else "One of the validated days, checked by hand."
    parts.append(f'<p><a href="{escape(link)}">Open the map for {d["day"]}</a>. {how} Derived from adsb.lol data (ODbL 1.0).</p>')
    return title, "".join(parts)


def write_feed(index, events_dir, path=None, places_path=None, n=30, alerts_path=None):
    """Atom feed of the latest n days, plus the sun-outage and radio-burst alerts in alerts_path (tools/sun_alerts.py).
    Each day entry's updated time is the end of its UTC day and each alert's is its own time, so a redeploy doesn't
    re-announce old entries. Returns the number of entries."""
    path, places_path, alerts_path = path or FEED, places_path or PLACES, alerts_path or SUN_ALERTS
    places = []
    if os.path.exists(places_path):
        with open(places_path, encoding="utf-8") as f:
            places = [p for p in json.load(f).get("places", []) if p[3] <= 5]
    days = sorted(index, key=lambda d: d["day"])
    entries = []
    for i in range(len(days) - 1, max(-1, len(days) - 1 - n), -1):
        d = days[i]
        prior = [x["jam_hexes"] for x in days[max(0, i - 30):i]]
        ev_path = os.path.join(events_dir, f"{d['day']}.json")
        ev = None
        if os.path.exists(ev_path):
            with open(ev_path, encoding="utf-8") as f:
                ev = json.load(f)
        title, html = day_summary(d, prior, ev, places)
        updated = f"{d['day']}T23:59:59Z"
        entries.append((updated, f"<entry><id>tag:noisefloor.theintelligence.company,2026:gnss-day-{d['day']}</id>"
                       f"<title>{escape(title)}</title><updated>{updated}</updated>"
                       f'<link rel="alternate" type="text/html" href="{escape(SITE_URL + "/map#day=" + d["day"] + "&m=jam")}"/>'
                       f'<content type="html">{escape(html)}</content></entry>'))
    if os.path.exists(alerts_path):
        with open(alerts_path, encoding="utf-8") as f:
            alerts = json.load(f).get("alerts", [])
        titles = {"burst-in-window": "Sun-outage alert: radio burst during predicted outages",
                  "bright-sun": "Sun-outage alert: bright sun during predicted outages",
                  "l-burst": "Radio burst at GNSS frequencies", "report": "Reported satellite outage, checked against sun outages",
                  "aircraft": "Radio burst seen in aircraft GNSS"}
        for a in alerts:
            html = (f"<p>{escape(a.get('text', ''))}</p><p>Predicted from geometry for the public watch list; observed by NOAA SWPC "
                    f'(US public domain). Thresholds are provisional. <a href="{SITE_URL}/sun">How sun outages work</a></p>')
            link = a.get("link") or SITE_URL + "/"
            entries.append((a["t"], f"<entry><id>tag:noisefloor.theintelligence.company,2026:{escape(a['id'])}</id>"
                                    f"<title>{escape(titles.get(a.get('kind'), 'Alert'))}</title><updated>{escape(a['t'])}</updated>"
                                    f'<link rel="alternate" type="text/html" href="{escape(link)}"/>'
                                    f'<content type="html">{escape(html)}</content></entry>'))
    entries.sort(key=lambda e: e[0], reverse=True)
    feed_updated = entries[0][0] if entries else "2026-01-01T00:00:00Z"
    xml = ('<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">'
           "<id>tag:noisefloor.theintelligence.company,2026:gnss-daily</id>"
           "<title>Noisefloor: daily GNSS summary and alerts</title>"
           "<subtitle>GNSS degradation seen by aircraft worldwide, one entry per UTC day from the automatic daily run, plus "
           "sun-outage and radio-burst alerts.</subtitle>"
           f'<link rel="self" type="application/atom+xml" href="{SITE_URL}/feed.xml"/>'
           f'<link rel="alternate" type="text/html" href="{SITE_URL}/map"/>'
           f"<updated>{feed_updated}</updated><author><name>Noisefloor</name><uri>{SITE_URL}</uri></author>"
           "<rights>Daily entries derived from adsb.lol data, ODbL 1.0</rights>" + "".join(e[1] for e in entries) + "</feed>\n")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(xml)
    return len(entries)


def entry(day, note="", daily=False):
    path = os.path.join(GNSS, f"{day}.json")
    with open(path, encoding="utf-8") as f:
        obj = json.load(f)
    if obj.get("day") != day:
        sys.exit(f"{path}: holds day {obj.get('day')!r}")
    e = {"day": day, "note": note, **stats(obj), "kb": round(os.path.getsize(path) / 1024)}
    if daily:
        e["daily"] = True
    return e


def main():
    global GNSS, EVENTS, FEED, PLACES
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    src = sys.argv[1]
    if len(sys.argv) == 3:
        GNSS, EVENTS = os.path.join(sys.argv[2], "data", "gnss"), os.path.join(sys.argv[2], "data", "events")
        FEED, PLACES = os.path.join(sys.argv[2], "feed.xml"), os.path.join(sys.argv[2], "data", "places.json")
    index_path = os.path.join(GNSS, "days.json")
    with open(index_path, encoding="utf-8") as f:
        committed = {d["day"]: d for d in json.load(f)}
    added = []
    for name in sorted(os.listdir(src)) if os.path.isdir(src) else []:
        m = MAP_FILE.match(name)
        if not m or m.group(1) in committed:
            continue
        shutil.copyfile(os.path.join(src, name), os.path.join(GNSS, f"{m.group(1)}.json"))
        added.append(m.group(1))
    with_events = [d for d in added if write_events(d, src, EVENTS)]
    hot_days = sorted(m.group(1) for m in map(HOT_FILE.match, os.listdir(src) if os.path.isdir(src) else []) if m)
    trend = write_trend(hot_days, src, os.path.join(os.path.dirname(GNSS), "trend.json"))   # every day, validated too
    n_files, n_tagged = annotate_all(EVENTS, os.path.join(src, "faa_gps_tests.json"))
    index = list(committed.values()) + [entry(d, daily=True) for d in added]
    index.sort(key=lambda d: d["day"])
    with open(index_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(index, f, separators=(",", ":"), ensure_ascii=False)
    n_feed = write_feed(index, EVENTS)
    print(f"feed.xml: {n_feed} entries")
    print(f"days.json: {len(committed)} committed + {len(added)} daily"
          + (f" ({added[0]} to {added[-1]}); event files for {len(with_events)}; trend days {trend}" if added else "")
          + (f"; announced tests on {n_files} event files, {n_tagged} events tagged" if n_files else ""))


if __name__ == "__main__":
    main()
