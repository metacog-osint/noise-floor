#!/usr/bin/env python3
"""board.py: the home page status board's data, built at deploy: SITE/data/board.json.

  python3 tools/board.py RELEASE_DIR [SITE]

Reads what the deploy already has (SITE/data/gnss/*.json day maps and days.json, trend.json, events/<day>.json,
events-monthly.json, vessels/gnss_at_sea.json, places.json; RELEASE_DIR/faa_gps_tests.json, <day>.loss_daily.parquet,
<day>.spoof.json, cygnss/<day>.cygnss.json), the public list of official notices (site_src/official_notices.json), and
two live snapshots taken at build time: EASA's table of FIRs with GNSS interference reports, and ESA's ionospheric
scintillation nowcast. Every section is built on its own: a source that fails leaves its section out and is named in
"problems", and the deploy carries on.

Sections: summary (one line), hotspots (named areas: today, against the 30 days before, 30-day series), changes (H3
res-2 regions at jamming scale: new, ended, long-running), declared (announced US GPS tests, official notices, EASA
FIRs), loss (aircraft heard by MLAT but sending no position), scintillation, spoofing, cygnss, events (this month's
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
LOOKBACK = 60                                                 # days of day maps read for the changes section
LOSS_BOXES = {"Suwałki–Ełk": (53.5, 54.35, 21.6, 23.0)}       # added to the trend's named areas (position-loss write-up)
EASA_URL = "https://www.easa.europa.eu/en/domains/air-operations/global-navigation-satellite-system-outages-and-alterations"
ESA_URL = "https://swe.ssa.esa.int/assets/ism/ism_nowcast/{}_nowcast_grid.xml"
ESA_REC = re.compile(r"<ns2:date>([^<]+)</ns2:date><ns2:stringValue>([^<]+)</ns2:stringValue><ns2:stringValue>([^<]+)"
                     r"</ns2:stringValue><ns2:stringValue>([^<]+)</ns2:stringValue><ns2:stringValue>([^<]+)</ns2:stringValue>")
# date, lon, lat, value, error (the same parse as the private archive's capture script)


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

    def near(self, lat, lon, limit=350):
        best, name = limit, None
        for p in self.pl:
            d = km((lat, lon), (p[1], p[2]))
            if d < best:
                best, name = d, p[0]
        return name


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


def changes(site, days, places):
    import h3
    recent = [d["day"] for d in days][-LOOKBACK:]
    per_day = {}
    for day in recent:
        m = load(os.path.join(site, "data", "gnss", f"{day}.json"))
        if m and m.get("cells"):
            per_day[day] = jam_regions(m["cells"], m["cols"])
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
        return {"region": r, "lat": round(la, 2), "lon": round(lo, 2), "near": places.near(la, lo), **extra}

    new = [row(r, {"days_in_last7": sum(1 for d in last7 if r in per_day[d])}) for r in seen7 if r not in seen_before]
    ended = [row(r, {"days_in_prior30": n}) for r, n in seen_before.items() if n >= 3 and r not in seen7]
    span = ds[-LOOKBACK:]
    long_running = [r for r in set().union(*(per_day[d] for d in span))
                    if sum(1 for d in span if r in per_day[d]) >= 0.9 * len(span)]
    new.sort(key=lambda x: -x["days_in_last7"])
    ended.sort(key=lambda x: -x["days_in_prior30"])
    return {"day": ds[-1], "regions_today": len(today), "new": new[:8], "new_count": len(new), "ended": ended[:8],
            "ended_count": len(ended), "long_running": len(long_running), "long_running_days": len(span),
            "rule": f"an H3 res-2 region with {REGION_HEXES}+ hexes at jamming scale; new = in the last 7 days and none of "
                    "the 30 before; ended = on 3+ of those 30 days and none of the last 7; long-running = 90% of the days "
                    f"read ({len(span)})"}


def top_events(site, day, places):
    ev = load(os.path.join(site, "data", "events", f"{day}.json"))
    if not ev:
        return None
    rows = []
    for e in ev.get("anomalies", []):
        if e.get("m") == "jam" and e.get("tier") in ("major", "notable"):
            rows.append({"tier": e["tier"], "peak": e.get("peak"), "excess": e.get("excess"), "h0": e.get("h0"),
                         "h1": e.get("h1"), "lat": e["lat"], "lon": e["lon"], "near": places.near(e["lat"], e["lon"]),
                         "heavy_share": e.get("hs"), "test": e.get("test")})
    return {"day": day, "events": rows[:6], "bursts": len(ev.get("bursts") or []), "tests": len(ev.get("tests") or [])}


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
    return {"day": last["day"], "version": last.get("version"), "active": last.get("active"),
            "episodes": last.get("episodes"), "aircraft": last.get("aircraft_with_episodes"), "victims": vic,
            "spoofed_to": (last.get("spoofed_to_top") or [])[:5],
            "series": [{"day": s["day"], "active": s.get("active")} for s in days],
            "note": "Where receivers were, not where a transmitter is. Offset tracks with no jump are missed."}


def cygnss(release, places):
    files = sorted(glob.glob(os.path.join(release, "*.cygnss.json")))
    if not files:
        raise ValueError("no CYGNSS summaries yet")
    s = load(files[-1])
    top = []
    for r in (s.get("top") or [])[:6]:
        top.append({**r, "near": places.near(r["lat"], r["lon"], limit=500)})
    return {"day": s["day"], "cells": s.get("cells"), "raised_cells": s.get("raised_cells"), "top": top,
            "note": "Noise floor of GPS reflections seen from orbit; the beam is a few hundred km wide, so this is "
                    "exposure, not a transmitter site. About 38°N to 38°S."}


# ---------------------------------------------------------------- the board
def geo_card(site):
    g = load(os.path.join(site, "data", "geo.json"))
    if not g:
        raise ValueError("no geo.json (tools/geo.py build runs first)")
    return {"at_utc": g["at_utc"], "snapshot_day": g["snapshot_day"], "snapshots": g["snapshots"], "counts": g["counts"],
            "close": g["close_other_owner"][:5], "close_count": len(g["close_other_owner"]),
            "manoeuvres": g["manoeuvres"][-4:], "manoeuvre_count": len(g["manoeuvres"]), "source": g["source"]}


def summary_line(b):
    parts = []
    ch = b.get("changes")
    if ch:
        parts.append(f"{ch['regions_today']} regions at jamming scale on {ch['day']}"
                     + (f", {ch['new_count']} new this week" if ch["new_count"] else "")
                     + (f", {ch['ended_count']} ended" if ch["ended_count"] else ""))
    hs = (b.get("hotspots") or {}).get("areas") or []
    rise = max((a for a in hs if a["change"] is not None), key=lambda a: a["change"], default=None)
    if rise and rise["change"] >= 5:
        parts.append(f"biggest rise: {rise['name']} (+{rise['change']:g} points)")
    lo = [a for a in ((b.get("loss") or {}).get("areas") or []) if not a.get("hexes") or a["hexes_with_mlat"] / a["hexes"] >= 0.5]
    if lo and lo[0]["share"] >= 20:
        parts.append(f"{lo[0]['name']}: {lo[0]['share']:g}% of aircraft heard sent no position")
    sp = b.get("spoofing")
    if sp and sp.get("active") is not None:
        parts.append(f"{sp['active']} active spoofing episodes ({sp['day']})")
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
    section("geo", geo_card, site)
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
        "geo_snapshot": (board.get("geo") or {}).get("snapshot_day"),
        "board_built": board["built_utc"],
    }
    board["summary"] = summary_line(board)
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


if __name__ == "__main__":
    main()
