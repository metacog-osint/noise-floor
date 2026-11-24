#!/usr/bin/env python3
"""board.py: the home page status board's data, built at deploy: SITE/data/board.json.

  python3 tools/board.py RELEASE_DIR [SITE]

Reads what the deploy already has (SITE/data/gnss/*.json day maps and days.json, trend.json, events/<day>.json,
events-monthly.json, vessels/gnss_at_sea.json, places.json; RELEASE_DIR/faa_gps_tests.json, <day>.loss_daily.parquet,
<day>.spoof.json, cygnss/<day>.cygnss.json, <day>.s6.json, <day>.smap.json), the public list of official notices (site_src/official_notices.json), and
two live snapshots taken at build time: EASA's table of FIRs with GNSS interference reports, and ESA's ionospheric
scintillation nowcast. Every section is built on its own: a source that fails leaves its section out and is named in
"problems", and the deploy carries on.

Sections: summary (one line), hotspots (named areas: today, against the 30 days before, 30-day series), changes (H3
res-2 regions at jamming scale: new, fell below, ended, long-running), declared (announced US GPS tests, official notices, EASA
FIRs), loss (aircraft heard by MLAT but sending no position), scintillation, spoofing, cygnss, sentinel6, smap, events (this month's
graded counts), freshness. Aggregates only; licences are stated in the file.
"""
import glob
import json
import math
import os
import re
import statistics
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "noise-floor board (github.com/metacog-osint/noise-floor)"}
JAM_MIN_AIRCRAFT, JAM_SCORE, REGION_HEXES = 5, 10.0, 3        # the map's colouring rule and the events level check
# "Ended" needs more than falling below jamming scale (suite review 15 Nov 2026, Mistake 2; Tom's choice 16 Nov):
# coverage on each of the last 7 days (aircraft-cells >= ENDED_MIN_AIRCRAFT and >= half the region's own median over
# the 30 days before) and a pooled 7-day severe-error share at background level. In regions never at jamming scale,
# 95% of 7-day windows with 500+ aircraft-cells a day pooled to 0.92% or less (live day maps 10 Oct-15 Nov 2026).
ENDED_MIN_AIRCRAFT, ENDED_COVER, ENDED_MAX_SHARE = 500, 0.5, 1.0
LOOKBACK = 60                                                 # days of day maps read for the changes section
FAR_KM = 1000                                                 # a new spoofed-to place this far from its aircraft is named in the summary
LOSS_BOXES = {"Suwałki–Ełk": (53.5, 54.35, 21.6, 23.0)}       # added to the trend's named areas (position-loss write-up)
EASA_URL = "https://www.easa.europa.eu/en/domains/air-operations/global-navigation-satellite-system-outages-and-alterations"
ESA_URL = "https://swe.ssa.esa.int/assets/ism/ism_nowcast/{}_nowcast_grid.xml"
ESA_REC = re.compile(r"<ns2:date>([^<]+)</ns2:date><ns2:stringValue>([^<]+)</ns2:stringValue><ns2:stringValue>([^<]+)"
                     r"</ns2:stringValue><ns2:stringValue>([^<]+)</ns2:stringValue><ns2:stringValue>([^<]+)</ns2:stringValue>")
# date, lon, lat, value, error (the same parse as the data repo's capture script)


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def km(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    x = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 12742 * math.asin(min(1.0, math.sqrt(x)))


class Places:
    def __init__(self, site):
        try:                                  # place names are a nicety: a bad file leaves cards unnamed, not missing
            pl = (load(os.path.join(site, "data", "places.json"), {}) or {}).get("places", [])
            self.pl = [p for p in pl if len(p) > 3 and isinstance(p[3], (int, float)) and p[3] <= 5]
        except Exception:
            self.pl = []

    def nearest(self, lat, lon, limit=350):
        """(name, [lat, lon]) of the nearest listed place within `limit` km, or (None, None)."""
        best, hit = limit, (None, None)
        for p in self.pl:
            d = km((lat, lon), (p[1], p[2]))
            if d < best:
                best, hit = d, (p[0], [p[1], p[2]])
        return hit

    def near(self, lat, lon, limit=350):
        return self.nearest(lat, lon, limit)[0]

    def area(self, lat, lon, cells=()):
        """(name, place [lat, lon] or None) for a jamming region or event: a listed place within 150 km in the same
        country, else the country it lies in (tools/area_names.py)."""
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import area_names
        return area_names.area_name(self.pl, lat, lon, cells)

    def area_kind(self, lat, lon, cells=()):
        """area() plus the kind of name ("place", "country", "sea", "offshore" or None) and, for a country or sea, a
        reference such as "220 km W of Tbilisi" (area_names.ref)."""
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import area_names
        return area_names.area_ref(self.pl, lat, lon, cells)

    def where(self, lat, lon, cells=(), event=False):
        """The full words: 'near Doha', 'in the Baltic Sea, 260 km S of Stockholm', for an event 'across 25
        countries, centred near Zagreb' (area_names.where)."""
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import area_names
        return area_names.where(self.pl, lat, lon, cells, event=event)


def _countries(rows):
    return bool(rows) and all(r.get("near_kind") in ("country", "sea") for r in rows)


def fetch(url, timeout=60):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


# ---------------------------------------------------------------- GNSS: hotspots and changes
def hotspots(trend):
    out = []
    days = trend["days"]
    for name, r in trend["regions"].items():
        sh = r["share"]
        today = sh[-1]
        prior = [v for v in sh[-31:-1] if v is not None]
        med = statistics.median(prior) if prior else None
        out.append({"name": name, "box": r.get("box"), "today": today, "median30": None if med is None else round(med, 1),
                    "change": None if today is None or med is None else round(today - med, 1),
                    "series": sh[-30:], "aircraft_hexes": (r.get("aircraft_hexes") or [None])[-1]})
    out.sort(key=lambda x: -(x["today"] or 0))
    return {"day": days[-1], "measure": trend.get("measure"), "areas": out}


def jam_regions(cells, cols):
    """H3 res-2 regions with at least REGION_HEXES res-4 hexes at jamming scale (hex score 100 x max(bad - 1, 0) /
    aircraft >= JAM_SCORE with >= JAM_MIN_AIRCRAFT aircraft), as {region: hexes}."""
    import h3
    i_h, i_a, i_b = cols.index("h3"), cols.index("aircraft"), cols.index("bad_live")
    count = {}
    for c in cells:
        a = c[i_a]
        if a >= JAM_MIN_AIRCRAFT and 100 * max(c[i_b] - 1, 0) / a >= JAM_SCORE:
            r = h3.cell_to_parent(c[i_h], 2)
            count[r] = count.get(r, 0) + 1
    return {r: n for r, n in count.items() if n >= REGION_HEXES}


def region_totals(cells, cols):
    """{H3 res-2 region: [aircraft-cells, severe-error aircraft-cells]} summed over its res-4 cells."""
    import h3
    i_h, i_a, i_b = cols.index("h3"), cols.index("aircraft"), cols.index("bad_live")
    out = {}
    for c in cells:
        t = out.setdefault(h3.cell_to_parent(c[i_h], 2), [0, 0])
        t[0] += c[i_a]
        t[1] += c[i_b]
    return out


def ended_check(r, last7, before, totals):
    """The 'ended' gate for a region that fell below jamming scale: (passed, 7-day share %, fewest aircraft-cells)."""
    ac = [totals.get(d, {}).get(r, [0, 0])[0] for d in last7]
    bad = sum(totals.get(d, {}).get(r, [0, 0])[1] for d in last7)
    usual = statistics.median([totals.get(d, {}).get(r, [0, 0])[0] for d in before]) if before else 0
    share = round(100 * bad / sum(ac), 2) if sum(ac) else None
    covered = min(ac) >= max(ENDED_MIN_AIRCRAFT, ENDED_COVER * usual)
    return covered and share is not None and share <= ENDED_MAX_SHARE, share, min(ac)


def changes(site, days, places):
    import h3
    recent = [d["day"] for d in days][-LOOKBACK:]
    per_day, totals = {}, {}
    for day in recent:
        m = load(os.path.join(site, "data", "gnss", f"{day}.json"))
        if m and m.get("cells"):
            per_day[day] = jam_regions(m["cells"], m["cols"])
            totals[day] = region_totals(m["cells"], m["cols"])
    ds = sorted(per_day)
    if len(ds) < 14:
        raise ValueError(f"only {len(ds)} day maps")
    last7, before = ds[-7:], ds[-37:-7]
    seen7 = set().union(*(per_day[d] for d in last7))
    seen_before = {}
    for d in before:
        for r in per_day[d]:
            seen_before[r] = seen_before.get(r, 0) + 1
    today = per_day[ds[-1]]

    def row(r, extra):
        la, lo = h3.cell_to_latlng(r)
        name, at, kind, ref = places.area_kind(la, lo, [r])
        return {"region": r, "lat": round(la, 2), "lon": round(lo, 2), "near": name, "near_at": at,
                "near_kind": kind, "near_ref": ref, "where": places.where(la, lo, [r]), **extra}

    new = [row(r, {"days_in_last7": sum(1 for d in last7 if r in per_day[d])}) for r in seen7 if r not in seen_before]
    ended, below = [], []
    for r, n in seen_before.items():
        if n >= 3 and r not in seen7:
            ok, share, fewest = ended_check(r, last7, before, totals)
            (ended if ok else below).append(row(r, {"days_in_prior30": n, "share7_pct": share, "min_aircraft": fewest}))
    span = ds[-LOOKBACK:]
    long_running = [r for r in set().union(*(per_day[d] for d in span))
                    if sum(1 for d in span if r in per_day[d]) >= 0.9 * len(span)]
    # Ties break on the region id, so the same week names the same places on every build (new regions came from a
    # set, and Doha and Pavlodar became Doha and Beijing between two builds on 15 Nov 2026).
    new.sort(key=lambda x: (-x["days_in_last7"], x["region"]))
    ended.sort(key=lambda x: (-x["days_in_prior30"], x["region"]))
    below.sort(key=lambda x: (-x["days_in_prior30"], x["region"]))
    return {"day": ds[-1], "regions_today": len(today), "new": new[:8], "new_count": len(new),
            "below": below[:8], "below_count": len(below), "ended": ended[:8], "ended_count": len(ended),
            "long_running": len(long_running), "long_running_days": len(span),
            "rule": f"an H3 res-2 region with {REGION_HEXES}+ hexes at jamming scale; new = in the last 7 days and none of "
                    "the 30 before; fell below jamming scale = on 3+ of those 30 days and none of the last 7; ended = "
                    f"fell below it, with {ENDED_MIN_AIRCRAFT}+ aircraft-hexes (and half the region's usual number) on each "
                    f"of the last 7 days and a 7-day severe-error share of {ENDED_MAX_SHARE:g}% or less (background); "
                    f"long-running = 90% of the days read ({len(span)})"}


def top_events(site, day, places):
    ev = load(os.path.join(site, "data", "events", f"{day}.json"))
    if not ev:
        return None
    rows = []
    for e in ev.get("anomalies", []):
        if e.get("m") == "jam" and e.get("tier") in ("major", "notable"):
            name, at, kind, ref = places.area_kind(e["lat"], e["lon"], e.get("cells") or [])
            rows.append({"tier": e["tier"], "peak": e.get("peak"), "excess": e.get("excess"), "h0": e.get("h0"),
                         "h1": e.get("h1"), "lat": e["lat"], "lon": e["lon"], "near": name, "near_at": at,
                         "near_kind": kind, "near_ref": ref,
                         "where": places.where(e["lat"], e["lon"], e.get("cells") or [], event=True),
                         "cells": e.get("cells") or [], "heavy_share": e.get("hs"), "test": e.get("test")})
    rows.sort(key=lambda r: r["tier"] != "major")    # majors first, each tier in the analysis's own order (stable)
    # Every major and notable event, not the first six: a cap of six fired exactly six event items a day, 31 Oct to
    # 13 Nov, and cut a Baltic event (suite review 15 Nov 2026, Mistake 3). The feed tiers them; the page shows six.
    return {"day": day, "events": rows, "majors": sum(1 for r in rows if r["tier"] == "major"),
            "bursts": len(ev.get("bursts") or []), "tests": len(ev.get("tests") or [])}


# ---------------------------------------------------------------- declared and official
def declared(release, site, now):
    out = {}
    tests = load(os.path.join(release, "faa_gps_tests.json"))
    if tests:
        t0, t7 = now.strftime("%Y-%m-%dT%H:%MZ"), (now + timedelta(days=7)).strftime("%Y-%m-%dT%H:%MZ")
        end_day = now.strftime("%Y-%m-%d") + "T23:59Z"
        rows = []
        for t in tests.get("tests", {}).values():
            w = [x for x in t.get("windows", []) if x[1] >= t0 and x[0] <= t7]
            if w:
                rows.append({"id": t["id"], "place": t.get("place", ""), "next": min(x[0] for x in w),
                             "today": any(x[0] <= end_day for x in w), "url": t.get("notice_url") or t.get("url", "")})
        rows.sort(key=lambda r: r["next"])
        out["faa_tests"] = {"today": sum(1 for r in rows if r["today"]), "next7": len(rows), "list": rows[:8],
                            "source": "FAA SPANS flight advisories (US public domain)"}
    notices = load(os.path.join(ROOT, "site_src", "official_notices.json"))
    if notices:
        out["notices"] = [n for n in notices.get("notices", []) if not n.get("valid_to_utc") or n["valid_to_utc"] >= now.strftime("%Y-%m-%dT%H:%MZ")]
    nt = load(os.path.join(site, "data", "notams", "index.json"))    # pipeline/gnss_notams.py site, run before the board
    if nt and nt.get("days"):
        d = nt["days"][-1]
        out["notams"] = {"day": d["day"], "n": d["n"], "groups": d["groups"], "counts": d.get("counts") or {},
                         "source_note": nt.get("source_note")}
    return out


def easa_firs():
    """EASA's 7-day and 30-day tables of FIRs with GNSS interference (spoofing column, reported column)."""
    return easa_parse(fetch(EASA_URL).decode("utf-8", "replace"))


def easa_parse(s, url=EASA_URL):
    """The FIR tables in a copy of EASA's page (live, or an Internet Archive capture: tools/easa_history.py)."""
    import html as H
    tables = []
    for m in re.finditer(r"<h2[^>]*>\s*impacted FIRs in the last (\d+) days on ([0-9/]+)\s*</h2>(.*?)</table>", s, re.S | re.I):
        rows = []
        for tr in re.finditer(r"<tr[^>]*>(.*?)</tr>", m.group(3), re.S):
            cells = {c: H.unescape(re.sub(r"<[^>]+>", "", v)).strip()
                     for c, v in re.findall(r'<td class="col-(\w+)"[^>]*>(.*?)</td>', tr.group(1), re.S)}
            if cells.get("name"):
                rows.append({"rank": cells.get("rank"), "region": cells.get("region"), "icao": cells.get("icao"),
                             "name": cells["name"].title(), "spoofing": cells.get("spoofing") == "*",
                             "reported": cells.get("reported") == "*"})
        d, mo, y = m.group(2).split("/")
        tables.append({"days": int(m.group(1)), "date": f"{y}-{mo}-{d}", "firs": rows})
    if not tables:
        raise ValueError("FIR tables not found on the EASA page")
    return {"url": url, "tables": tables, "credit": "Source: EASA (European Union Aviation Safety Agency), "
            "GNSS outages and alterations: impacted FIRs (ADS-B data and reports)"}


# ---------------------------------------------------------------- phase B: position loss and scintillation
def position_loss(release, trend):
    files = sorted(glob.glob(os.path.join(release, "*.loss_daily.parquet")))
    if not files:
        raise ValueError("no loss_daily files")
    import pyarrow.parquet as pq
    path = files[-1]
    t = pq.read_table(path, columns=["lat", "lon", "heard", "mlat_only", "mlat_any"]).to_pydict()
    boxes = {n: r["box"] for n, r in trend["regions"].items()}
    boxes.update(LOSS_BOXES)
    rows = []
    for name, (a0, a1, o0, o1) in boxes.items():
        idx = [i for i in range(len(t["lat"])) if a0 <= t["lat"][i] <= a1 and o0 <= t["lon"][i] <= o1]
        heard = sum(t["heard"][i] for i in idx)
        mo = sum(t["mlat_only"][i] for i in idx)
        mlat_hexes = sum(1 for i in idx if t["mlat_any"][i] > 0)
        if heard:
            rows.append({"name": name, "heard": heard, "mlat_only": mo, "share": round(100 * mo / heard, 1),
                         "hexes": len(idx), "hexes_with_mlat": mlat_hexes})
    rows.sort(key=lambda r: -r["share"])
    return {"day": os.path.basename(path)[:10], "areas": rows, "definition": "aircraft heard by MLAT but sending no GNSS "
            "position, of all aircraft heard in the area (aircraft-hexes); a lower bound, and only where MLAT reaches"}


def scintillation():
    """A derived snapshot of ESA's current nowcast: highest S4 and sigma-phi, cells at ICAO moderate or worse."""
    vals, when = {}, set()
    for name in ("s4", "sigma_phi"):
        recs = ESA_REC.findall(fetch(ESA_URL.format(name), timeout=90).decode("utf-8", "replace"))
        if len(recs) < 10000:
            raise ValueError(f"{name}: only {len(recs)} cells")
        when |= {r[0][:16] for r in recs}
        vals[name] = [(float(r[1]), float(r[2]), float(r[3])) for r in recs]   # lon, lat, value
    out = {"valid_utc": min(when).replace("T", " ") + "Z" if when else None}
    for name, thr in (("s4", (0.5, 0.8)), ("sigma_phi", (0.4, 0.7))):
        v = vals[name]
        top = max(v, key=lambda x: x[2])
        out[name] = {"max": round(top[2], 2), "at": [round(top[1], 1), round(top[0], 1)],
                     "moderate_cells": sum(1 for x in v if x[2] >= thr[0]), "severe_cells": sum(1 for x in v if x[2] >= thr[1])}
    out["level"] = ("severe" if out["s4"]["severe_cells"] or out["sigma_phi"]["severe_cells"] else
                    "moderate" if out["s4"]["moderate_cells"] or out["sigma_phi"]["moderate_cells"] else "below moderate")
    out["thresholds"] = "ICAO GNSS scintillation categories: S4 0.5/0.8, sigma-phi 0.4/0.7 rad (moderate/severe)"
    out["credit"] = ("Data provided by the European Space Agency (ESA) as part of its Space Safety Programme (S2P). "
                     "© ESA 2026. Derived summary of the ISM nowcast (CLS).")
    return out


# ---------------------------------------------------------------- phase C: spoofing and CYGNSS
def spoofing(release, places):
    files = sorted(glob.glob(os.path.join(release, "*.spoof.json")))
    if not files:
        raise ValueError("no spoofing summaries yet")
    days = []
    for f in files[-30:]:
        s = load(f)
        if s:
            days.append(s)
    last = days[-1]
    vic = []
    for r in (last.get("victim_res2_top") or [])[:6]:
        la, lo = r.get("lat"), r.get("lon")
        vic.append({**r, "near": places.near(la, lo) if la is not None else None})
    out = {"day": last["day"], "version": last.get("version"), "active": last.get("active"),
            "episodes": last.get("episodes"), "aircraft": last.get("aircraft_with_episodes"), "victims": vic,
            "spoofed_to": [p for p in (last.get("spoofed_to_top") or [])        # 0°, 0° is a default, not a place
                           if abs(p.get("lat") or 0) > 0.9 or abs(p.get("lon") or 0) > 0.9][:5],
            "series": [{"day": s["day"], "active": s.get("active")} for s in days],
            "new_places": _new_places(release, places),
            "place_levels": _place_levels(release, places),
            "region_levels": _region_levels(files, places),
            "note": "Where receivers were, not where a transmitter is. Offset tracks with no jump are missed."}
    out["line"] = spoof_line(out)
    return out


def _region_levels(files, places):
    """Regions (where aircraft really were) above their own usual level on the newest day with regional shares, and
    all regions together (tools/spoof_site.py regions_now(), with the announced US GPS tests in the same release
    folder); None without such a day."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import spoof_site
        tests = spoof_site.load_tests(os.path.dirname(files[-1])) if files else []
        return spoof_site.regions_now(spoof_site.share_days(files), places, tests)
    except Exception:                    # a nicety on the card: never stop the spoofing section
        return None


LEVEL_WORD = {"above": "above", "near": "near", "below": "below"}


def spoof_line(sp):
    """One plain sentence for the Today page from the board's spoofing section: the newest day's regions against their
    usual level, else the active episodes. Fixed rules, no forecast words."""
    if not sp:
        return None
    rl = sp.get("region_levels") or {}
    day = rl.get("day") or sp.get("day")
    when = _dayname(day) if day else ""
    tot = rl.get("total") or {}
    if rl and tot.get("level"):
        n = rl.get("above_count") or 0
        names = list(dict.fromkeys(a["near"] for a in rl.get("above") or [] if a.get("near")))[:3]
        if n:
            head = (f"Spoofing on {when} was above its usual level in {_num(n)} region{'' if n == 1 else 's'}"
                    + (f", most near {_and(names)}" if names else ""))
            k = rl.get("above_in_tests") or 0
            if k:
                head += (" (inside an announced US GPS test area)" if k == n else
                         f" ({_num(k)} of them inside an announced US GPS test area)")
        else:
            head = f"Spoofing on {when} was not above its usual level in any region"
        return head + f"; all regions together were {LEVEL_WORD[tot['level']]} their usual level."
    if sp.get("active") is not None:
        return f"{sp['active']} active spoofing episodes on {when}; no usual level yet (too few earlier days)."
    return None


def _new_places(release, places):
    """Spoofed-to places new on the newest targets day (tools/spoof_site.py new_targets()); None without files."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import spoof_site
        return spoof_site.new_targets(release, places)
    except Exception:                    # a nicety on the card: never stop the spoofing section
        return None


def _place_levels(release, places):
    """Spoofed-to places above their own usual level on the newest targets day, and all places together
    (tools/spoof_site.py track()); None without files."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import spoof_site
        import h3
        t = spoof_site.track(spoof_site.target_days(release), places)
        if not t.get("to"):
            return None
        above = []
        for r in t["above"]:
            regs = []
            for reg, n in r.get("regions") or []:
                la, lo = h3.cell_to_latlng(reg)
                regs.append({"region": reg, "episodes": n, "near": places.near(la, lo) if places else None})
            above.append({k: r[k] for k in ("lat", "lon", "near", "latest", "usual", "first", "days")} | {"regions": regs})
        return {"day": t["to"], "earlier_days": t["earlier_days"], "above": above, "above_count": t["above_count"],
                "total": t["total"], "rule": t["level_rule"]}
    except Exception:                    # a nicety on the card: never stop the spoofing section
        return None


def cygnss(release, places):
    files = sorted(glob.glob(os.path.join(release, "*.cygnss.json")))
    if not files:
        raise ValueError("no CYGNSS summaries yet")
    s = load(files[-1])
    top = []
    for r in (s.get("top") or [])[:6]:
        top.append({**r, "near": places.near(r["lat"], r["lon"], limit=500)})
    return {"day": s["day"], "judged_cells": s.get("judged_cells"), "raised_cells": s.get("raised_cells"), "top": top,
            "note": "Noise floor of GPS reflections seen from orbit; the beam is a few hundred km wide, so this is "
                    "exposure, not a transmitter site. About 38°N to 38°S."}


def swx_card(release, places):
    """Limb S4 and ground ROTI, the newest day of each (tools/swx_site.py card): measurements with no baseline."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import swx_site
    return swx_site.card(release, places)


def _latlng(cell):
    import h3
    return h3.cell_to_latlng(cell)


def sentinel6(release, places, spacing_km=1500.0, top=3):
    """The newest Sentinel-6A day: its raised cells and the strongest regions, at least spacing_km apart."""
    files = sorted(glob.glob(os.path.join(release, "*.s6.json")))
    if not files:
        raise ValueError("no Sentinel-6 files yet")
    s = load(files[-1])
    if s.get("peaks"):                         # named at source (tools/s6_daily.py, the NISAR lane's gazetteer)
        return {"day": s["day"], "raised_cells": s.get("raised_cells"), "judged_cells": s.get("judged_cells"),
                "threshold": s.get("threshold"), "peaks": [{**p, "near": p.get("where")} for p in s["peaks"][:top]],
                "note": "Sentinel-6A's own GPS receiver: regions where it lost signal strength on all its links at once; "
                        "each cell draws on everything within 3,800 km, so these are regions, not transmitter sites."}
    peaks = []
    for c, score, _ in sorted(s.get("cells") or [], key=lambda r: -r[1]):
        la, lo = _latlng(c)
        if all(km((la, lo), (p["lat"], p["lon"])) >= spacing_km for p in peaks):
            peaks.append({"lat": round(la, 2), "lon": round(lo, 2), "score": score, "near": places.near(la, lo, limit=500)})
        if len(peaks) == top:
            break
    return {"day": s["day"], "raised_cells": s.get("raised_cells"), "judged_cells": s.get("judged_cells"),
            "threshold": s.get("threshold"), "peaks": peaks,
            "note": "Sentinel-6A's own GPS receiver: regions where it lost signal strength on all its links at once; each "
                    "cell draws on everything within 3,800 km, so these are regions, not transmitter sites."}


def smap(release, places, spacing_km=500.0, top=3):
    """The newest SMAP 7-day window: stand-out emitter cells (count and the strongest few, apart) and busy regions."""
    files = sorted(glob.glob(os.path.join(release, "*.smap.json")))
    if not files:
        raise ValueError("no SMAP files yet")
    s = load(files[-1])
    strongest = [{**p, "near": p.get("where")} for p in (s.get("strongest") or [])[:top]]
    for c, share, contrast, looks in ([] if strongest else sorted(s.get("sources") or [], key=lambda r: (-r[2], -r[1], -r[3]))):
        la, lo = _latlng(c)
        if all(km((la, lo), (p["lat"], p["lon"])) >= spacing_km for p in strongest):
            strongest.append({"lat": round(la, 2), "lon": round(lo, 2), "share": share, "contrast": contrast,
                              "near": places.near(la, lo, limit=500)})
        if len(strongest) == top:
            break
    return {"day": s["day"], "window": s.get("window"), "sources": len(s.get("sources") or []),
            "busy_regions": len(s.get("busy") or []), "strongest": strongest,
            "note": "Interference in the protected 1400-1427 MHz band flagged by NASA's SMAP: single emitters standing out "
                    "of a quiet background, many likely L-band radars. Not GPS jammers."}


# ---------------------------------------------------------------- the board
SHORT = {   # watched-area names as they read inside a sentence
    "Kaliningrad and approaches": "Kaliningrad", "Southern Black Sea offshore Turkey": "the southern Black Sea",
    "Caucasus": "the Caucasus", "Gulf of Finland / Estonia–Russia border": "the Gulf of Finland",
    "Western Black Sea coast": "the western Black Sea", "Cyprus–Levant": "Cyprus and the Levant",
    "Strait of Hormuz / Gulf of Oman": "the Strait of Hormuz", "High latitude excl. Baltic/Russia": "high latitudes",
}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _dayname(d):
    """'2026-10-26' -> '26 Oct 2026' (the site's date style)."""
    return f"{int(d[8:10])} {MONTHS[int(d[5:7]) - 1]} {d[:4]}"


WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"]


def _and(xs):
    xs = [x for x in xs if x]
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1] if xs else ""


def _num(n):
    """A count inside a sentence: 'one', 'six', '12'."""
    return WORDS[n].lower() if n < len(WORDS) else str(n)


def _brief_name(r):
    """A named area in the brief: 'Saudi Arabia (330 km W of Abu Dhabi)' for a country or sea with a reference,
    else the name (brackets keep the list of names readable)."""
    return (f"{r['near']} ({r['near_ref']})" if r.get("near_kind") in ("country", "sea") and r.get("near_ref")
            else r["near"])


def _named(names, n, some, countries=False):
    """', near A and B' (', in A and B' when every name is a country) when the names cover all n areas; otherwise
    `some` (', among them ') and the names."""
    return (((", in " if countries else ", near ") if len(names) == n else some) + _and(names)) if names else ""


BRIEF_MEASURE = "The share of aircraft with severe GPS error was "   # the site's name for NACp below 8 (93 m or worse)


def brief(b):
    """The home page's bottom line, by fixed rules (not written by a person), in up to two sentences. It is also the
    headline other sites quote, so it names what it measures for a reader who has never seen Noisefloor.

    1. The watched areas: today's share of aircraft with severe GPS error (NACp below 8: the aircraft reports its
       position could be off by 93 m or more) against its median over the 30 days before, "its usual level". Areas
       below 5% both today and usually are left out. A difference of 5 points or more is "above" or "below" (not
       "rose" or "fell": the comparison is with the month, not with yesterday); anything less is "near". It never
       says interference fell, because a lower share can mean jammed aircraft stopped reporting a position at all,
       which the page's position-loss row shows.
    2. GPS interference by area (changes(): H3 res-2 regions with 3+ cells at jamming scale): it "started this week"
       in a region seen on any of the last 7 days and none of the 30 before. A region seen on 3+ of those 30 days and
       none of the last 7 "fell below jamming scale"; it "ended" only when it also passes ended_check() (enough
       aircraft on each of the last 7 days and a background-level severe-error share), because a region can drop
       under the 3-cell mark while degraded aircraft and graded events go on (suite review 15 Nov 2026, Mistake 2;
       Tom replaced "has stopped" on 16 Nov). "Fell" appears only in "fell below jamming scale". Neither says "this
       week", since it may have happened before the week began. Up to two new areas and one area of each other kind
       are named by tools/area_names.py: a listed place within 150 km, else the country most of the area lies in
       ("in Turkey" when every name is a country, "near Doha" otherwise); a country carries its reference in
       brackets, "Saudi Arabia (330 km W of Abu Dhabi)" (area_names.ref, Tom's choice 18 Nov 2026).
    A section that is missing leaves its sentence out."""
    out = []
    areas = [a for a in ((b.get("hotspots") or {}).get("areas") or [])
             if a.get("today") is not None and a.get("median30") is not None and a.get("change") is not None]
    big = sorted((a for a in areas if max(a["today"], a["median30"]) >= 5), key=lambda a: -a["today"])
    name = lambda a: SHORT.get(a["name"], a["name"])  # noqa: E731
    up = [name(a) for a in big if a["change"] >= 5][:2]
    down = [name(a) for a in big if a["change"] <= -5][:2]
    if up and down:
        comma = "," if len(up) > 1 or len(down) > 1 else ""
        out.append(f"{BRIEF_MEASURE}above its usual level over {_and(up)}{comma} and below it over {_and(down)}.")
    elif up or down:
        out.append(f"{BRIEF_MEASURE}{'above' if up else 'below'} its usual level over {_and(up or down)}.")
    elif big:
        out.append(f"{BRIEF_MEASURE}near its usual level over {_and([name(a) for a in big[:2]])}.")
    c = b.get("changes")
    if c:
        rows = [r for r in c.get("new") or [] if r.get("near")][:2]
        new = [_brief_name(r) for r in rows]
        n = c.get("new_count") or 0
        started = f"started in {_num(n)} area{'' if n == 1 else 's'} this week{_named(new, n, ', among them ', _countries(rows))}"
        tails = []
        for key, verb in (("ended", "ended in"), ("below", "fell below jamming scale in")):
            k = c.get(f"{key}_count") or 0
            if k:
                rows = [r for r in c.get(key) or [] if r.get("near")][:1]
                areas = "" if n or tails else f" area{'' if k == 1 else 's'}"
                tails.append(f"{verb} {_num(k)}{areas}{_named([_brief_name(r) for r in rows], k, ', including ', _countries(rows))}")
        tail = (", and " if "," in tails[0] else " and ").join(tails) if tails else ""
        if n and tails:
            out.append(f"GPS interference {started}; it {tail}.")
        elif n:
            out.append(f"GPS interference {started}; none fell below jamming scale.")
        elif tails:
            out.append(f"GPS interference {tail}; it started in none this week.")
        else:
            out.append("GPS interference has not started or fallen below jamming scale in any area this week.")
    return " ".join(out)


def summary_line(b):
    parts = []
    ch = b.get("changes")
    if ch:
        parts.append(f"{ch['regions_today']} areas with GPS interference on {_dayname(ch['day'])}"
                     + (f", {ch['new_count']} new this week" if ch["new_count"] else "")
                     + (f", {ch['ended_count']} ended" if ch.get("ended_count") else "")
                     + (f", {ch['below_count']} below jamming scale" if ch.get("below_count") else ""))
    hs = (b.get("hotspots") or {}).get("areas") or []
    rise = max((a for a in hs if a["change"] is not None), key=lambda a: a["change"], default=None)
    if rise and rise["change"] >= 5:
        parts.append(f"biggest rise: {rise['name']} (+{rise['change']:g} points)")
    lo = [a for a in ((b.get("loss") or {}).get("areas") or []) if not a.get("hexes") or a["hexes_with_mlat"] / a["hexes"] >= 0.5]
    if lo and lo[0]["share"] >= 20:
        parts.append(f"{lo[0]['name']}: {lo[0]['share']:g}% of aircraft heard sent no position")
    sp = b.get("spoofing")
    if sp and sp.get("active") is not None:
        parts.append(f"{sp['active']} active spoofing episodes ({_dayname(sp['day'])})")
        far = [x for x in ((sp.get("new_places") or {}).get("new") or []) if (x.get("km_from_aircraft") or 0) >= FAR_KM]
        if far:
            parts.append(f"aircraft shown at a new far-off false position near {far[0]['near'] or 'an unnamed place'}"
                         + (f" and {len(far) - 1} more" if len(far) > 1 else ""))
    sc = b.get("scintillation")
    if sc and sc.get("valid_utc"):
        try:
            age_h = (datetime.strptime(b["built_utc"], "%Y-%m-%dT%H:%MZ") - datetime.strptime(sc["valid_utc"], "%Y-%m-%d %H:%MZ")).total_seconds() / 3600
        except (KeyError, ValueError):
            age_h = 99
        if age_h <= 3:                    # ESA's nowcast sometimes stops updating; the card shows its time either way
            parts.append(f"scintillation {sc['level']}")
    return "; ".join(parts) + "." if parts else ""


def build(release, site, now=None):
    now = now or datetime.now(timezone.utc)
    places = Places(site)
    days = load(os.path.join(site, "data", "gnss", "days.json"), [])
    trend = load(os.path.join(site, "data", "trend.json"))
    board = {"built_utc": now.strftime("%Y-%m-%dT%H:%MZ"), "licence": "ODbL 1.0 for everything derived from adsb.lol; "
             "other sources as credited in each section", "problems": []}

    def section(key, fn, *args):
        try:
            board[key] = fn(*args)
        except Exception as e:          # one failing source must not stop the board or the deploy
            board["problems"].append(f"{key}: {type(e).__name__}: {str(e)[:160]}")

    if trend:
        section("hotspots", hotspots, trend)
    if days:
        section("changes", changes, site, days, places)
        section("top_events", top_events, site, days[-1]["day"], places)
    section("declared", declared, release, site, now)
    section("easa", easa_firs)
    if trend:
        section("loss", position_loss, release, trend)
    section("scintillation", scintillation)
    section("spoofing", spoofing, release, places)
    section("cygnss", cygnss, release, places)
    section("sentinel6", sentinel6, release, places)
    section("smap", smap, release, places)
    section("swx", swx_card, release, places)
    em = load(os.path.join(site, "data", "events-monthly.json"))

    def events_card():
        m = em["months"][-1]
        return {"month": m["month"], "days": m["days"], "effect_support": m["effect_support"],
                "effect_verdict": m["effect_verdict"], "version": em.get("version"), "last_day": em.get("last_day")}
    if em and em.get("months"):
        section("events", events_card)
    sea = load(os.path.join(site, "data", "vessels", "gnss_at_sea.json"))
    board["freshness"] = {
        "aircraft_day": days[-1]["day"] if days else None,
        "events_last_day": em.get("last_day") if em else None,
        "ships_built": (sea or {}).get("generated"),
        "scintillation_valid": (board.get("scintillation") or {}).get("valid_utc"),
        "easa_table": ((board.get("easa") or {}).get("tables") or [{}])[0].get("date"),
        "spoofing_day": (board.get("spoofing") or {}).get("day"),
        "cygnss_day": (board.get("cygnss") or {}).get("day"),
        "s6_day": (board.get("sentinel6") or {}).get("day"),
        "smap_day": (board.get("smap") or {}).get("day"),
        "limb_s4_day": ((board.get("swx") or {}).get("limb") or {}).get("day"),
        "roti_day": ((board.get("swx") or {}).get("roti") or {}).get("day"),
        "board_built": board["built_utc"],
    }
    board["summary"] = summary_line(board)
    board["brief"] = brief(board)
    return board


def main():
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    release = sys.argv[1]
    site = sys.argv[2] if len(sys.argv) == 3 else os.path.join(ROOT, "site")
    b = build(release, site)
    out = os.path.join(site, "data", "board.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(b, f, separators=(",", ":"), ensure_ascii=False)
    print(f"board: {os.path.getsize(out) // 1024} KB; sections {[k for k in b if k not in ('problems',)]}; "
          f"problems {b['problems'] or 'none'}")
    try:                                 # the contract v2 feed for COP is built from the same board; never fatal
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import feed_v2
        path, n = feed_v2.write(site, b)
        print(f"feed_v2: {n} items -> {path}")
    except Exception as e:
        print(f"::warning::contract v2 feed skipped: {type(e).__name__}: {str(e)[:200]}")


if __name__ == "__main__":
    main()
