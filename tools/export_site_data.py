#!/usr/bin/env python3
"""Export public visual data for the site from the processed GNSS days (data/pnt/, gitignored).

  python tools/export_site_data.py      # writes site/data/gnss/*.json, site/data/events/*.json, charts.json, land.json
  python tools/export_site_data.py --map-day 2026-10-21 OUT.json   # one day's map file (the daily workflow)
  python tools/export_site_data.py --hotspot-day 2026-10-21 OUT.json   # one day's shares in the named areas
  python tools/export_site_data.py --basemap   # only borders.json and places.json (Natural Earth 50m, v5.1.2)

Everything written here is derived from the adsb.lol archive and published under ODbL 1.0 with
attribution (the site footer and map credit it). Only aggregates per H3 hex (no aircraft identifiers)
and per region are exported. Run tools/build_site.py afterwards.
"""
import gzip
import json
import math
import os
import sys
from collections import Counter

import h3
import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from validate_phase1 import SUBREGIONS, in_box  # noqa: E402
from site_days import stats, write_events  # noqa: E402

DAILY = os.path.join(ROOT, "data", "pnt", "daily")
ANALYSIS = os.path.join(ROOT, "data", "pnt", "analysis")
OUT = os.path.join(ROOT, "site", "data")
LAND_SRC = os.path.join(ROOT, "nisar", "nisar_rfi", "assets", "land.geojson.gz")
NE_DIR = os.path.join(ROOT, "data", "natural_earth")          # downloaded on demand (gitignored)
NE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/{}.geojson"

DAYS = [f"2025-10-{d:02d}" for d in range(9, 26)] + ["2025-11-11", "2025-11-12", "2026-09-22"]
NOTES = {**{f"2025-10-{d}": "EGNOS outage" for d in range(13, 18)},
         "2025-10-18": "G2 geomagnetic storm", "2025-11-12": "G4 geomagnetic storm (00–06Z)",
         "2025-11-11": "Day before the G4 storm", "2026-09-22": "California GPS loss"}
NORTH_TIER = (43.0, 55.0, -125.0, -65.0)      # validation case A (tools/validate_cases.py)
BAY = (35.5, 38.5, -123.5, -119.5)            # validation case B
# Areas on the charts page's daily trend: the validation areas plus ones added for the daily run. Kept apart from
# SUBREGIONS, which the validation scripts treat as the known hotspots (changing it would change their results).
# Strait of Hormuz / Gulf of Oman added 22 Oct 2026 (Tom): sized to the 7-21 Oct 2026 events; leaves out the
# Dubai/Sharjah approaches and Muscat.
DAILY_AREAS = {**{k: v for k, v in SUBREGIONS.items() if not k.startswith("High latitude")},
               "Strait of Hormuz / Gulf of Oman": (24.0, 27.0, 56.0, 60.0),
               **{k: v for k, v in SUBREGIONS.items() if k.startswith("High latitude")}}
HOTSPOTS = ["Kaliningrad and approaches", "Gulf of Finland / Estonia–Russia border", "Southern Black Sea offshore Turkey",
            "Western Black Sea coast", "Caucasus", "High latitude excl. Baltic/Russia"]
_LL = {}


def ll(cell):
    if cell not in _LL:
        _LL[cell] = h3.cell_to_latlng(cell)
    return _LL[cell]


def daily(day):
    return pq.read_table(os.path.join(DAILY, f"{day}.parquet")).to_pylist()


def write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, separators=(",", ":"), ensure_ascii=False)
    return os.path.getsize(path)


def map_day(day, path):
    """One day's map file: hexes with 3+ aircraft. Returns (bytes, site_days.stats() counts)."""
    rows = [r for r in daily(day) if r["aircraft"] >= 3]
    obj = {"day": day, "licence": "ODbL 1.0; derived from adsb.lol",
           "cols": ["h3", "aircraft", "bad_live", "bad_raw", "capable", "capable_bad10"],
           "cells": [[r["h3"], r["aircraft"], r["bad_nacp_live"], r["bad_nacp"], r["capable"], r["cap_bad_acc10"]] for r in rows]}
    return write(path, obj), stats(obj)


def map_days():
    index = []
    for day in DAYS:
        size, st = map_day(day, os.path.join(OUT, "gnss", f"{day}.json"))
        index.append({"day": day, "note": NOTES.get(day, ""), **st, "kb": round(size / 1024)})
    write(os.path.join(OUT, "gnss", "days.json"), index)
    return index


def egnos():
    out = []
    for day in DAYS[:17]:
        a = (json.load(open(os.path.join(ANALYSIS, f"{day}.sbas.json")))["areas"] or {}).get("EGNOS (Europe)") or {}
        for h in a.get("hours") or []:
            if not h or h.get("share") is None:
                continue
            out.append({"t": f"{day}T{h['hour']:02d}Z", "share": h["share"], "base": h.get("baseline_median"),
                        "state": h.get("state"), "capable": h.get("capable")})
    return out


def hourly_region(day, box):
    s = [[0, 0, 0, 0] for _ in range(24)]
    for r in pq.read_table(os.path.join(DAILY, f"{day}.hourly.parquet")).to_pylist():
        la, lo = ll(r["h3"])
        if in_box({"lat": la, "lon": lo}, box):
            a = s[r["hour"]]
            a[0] += r["aircraft"]; a[1] += r["bad_nacp"]; a[2] += r["capable"]; a[3] += r["cap_bad_acc10"]
    return s


def pct(a, b):
    return round(100 * a / b, 1) if b >= 20 else None


def storm():
    ser = [h for d in ("2025-11-11", "2025-11-12") for h in hourly_region(d, NORTH_TIER)]
    quiet = [hourly_region(d, NORTH_TIER) for d in ("2025-10-16", "2025-10-22")]
    base = [[sum(q[h][k] for q in quiet) for k in range(4)] for h in range(24)] * 2
    days = ["2025-11-11"] * 24 + ["2025-11-12"] * 24
    return [{"t": f"{days[i]}T{i % 24:02d}Z", "acc10": pct(s[3], s[2]), "acc10_base": pct(b[3], b[2]),
             "gross": pct(s[1], s[0]), "gross_base": pct(b[1], b[0])} for i, (s, b) in enumerate(zip(ser, base))]


def bay():
    t = pq.read_table(os.path.join(DAILY, "2026-09-22.minute.parquet")).to_pylist()
    per = Counter()
    for r in t:
        la, lo = ll(r["h3"])
        if in_box({"lat": la, "lon": lo}, BAY):
            per[r["minute"]] += r["bad_nacp"]
    lo_m, hi_m = 17 * 60 + 30, 20 * 60 + 45
    return [{"m": m, "t": f"{m // 60:02d}:{m % 60:02d}Z", "aircraft": per.get(m, 0)} for m in range(lo_m, hi_m + 1)]


def region_share(rows, box):
    """Share of aircraft-hexes in a box worse than 93 m, live (post-exposure aircraft left out)."""
    sel = [r for r in rows if in_box(r, box)]
    ac, bad = sum(r["aircraft"] for r in sel), sum(r["bad_nacp_live"] for r in sel)
    return {"share": round(100 * bad / ac, 1) if ac else None, "aircraft_hexes": ac, "bad_live": bad}


def hotspots():
    out = {name: [] for name in HOTSPOTS}
    for day in DAYS[:17]:
        rows = daily(day)
        for name in HOTSPOTS:
            s = region_share(rows, SUBREGIONS[name])
            out[name].append({"day": day, "share": s["share"], "aircraft_hexes": s["aircraft_hexes"]})
    return out


def hotspot_day(day, path):
    """One day's shares in every daily-trend area (DAILY_AREAS), for the charts page."""
    rows = daily(day)
    return write(path, {"day": day, "licence": "ODbL 1.0; derived from adsb.lol",
                        "measure": "share of aircraft-hexes worse than 93 m, live",
                        "regions": {name: {**region_share(rows, box), "box": list(box)} for name, box in DAILY_AREAS.items()}})


def types():
    pe, al = Counter(), Counter()
    for day in DAYS[:17]:
        s = json.load(open(os.path.join(DAILY, f"{day}.summary.json")))
        pe.update((s.get("latching") or {}).get("post_exposure_types", {}))
        al.update(s.get("type_counts_all", {}))
    npe, nal = sum(pe.values()), sum(al.values())
    rows = []
    for t, n in pe.items():
        if t == "?" or n < 40 or not al.get(t):
            continue
        rows.append({"type": t, "post_exposure": n, "pe_share": round(100 * n / npe, 1), "all_share": round(100 * al[t] / nal, 2),
                     "ratio": round((n / npe) / (al[t] / nal), 1)})
    rows.sort(key=lambda r: -r["ratio"])
    return {"post_exposure_total": npe, "aircraft_days_total": nal, "rows": rows[:12]}


def land():
    g = json.load(gzip.open(LAND_SRC, "rt", encoding="utf-8"))

    def rnd(c):
        if isinstance(c[0], (int, float)):
            return [round(c[0], 2), round(c[1], 2)]
        return [rnd(x) for x in c]
    for f in g["features"]:
        f["geometry"]["coordinates"] = rnd(f["geometry"]["coordinates"])
        f["properties"] = {}
    return write(os.path.join(OUT, "land.json"), g)


def natural_earth(name):
    """A Natural Earth 50m layer, downloaded once into data/natural_earth/ (public domain)."""
    import urllib.request
    path = os.path.join(NE_DIR, f"{name}.geojson")
    if not os.path.exists(path):
        os.makedirs(NE_DIR, exist_ok=True)
        with urllib.request.urlopen(NE_URL.format(name), timeout=120) as r:
            open(path, "wb").write(r.read())
    return json.load(open(path, encoding="utf-8"))


def borders():
    """Land boundaries as [class, [[lat, lon], ...]] lines; class 1 = disputed, line of control or indefinite."""
    from shapely.geometry import shape
    out = []
    for f in natural_earth("ne_50m_admin_0_boundary_lines_land")["features"]:
        cls = 0 if f["properties"].get("FEATURECLA", "").startswith("International") else 1
        g = shape(f["geometry"]).simplify(0.02, preserve_topology=False)
        for line in getattr(g, "geoms", [g]):
            pts = [[round(y, 2), round(x, 2)] for x, y in line.coords]
            if len(pts) >= 2:
                out.append([cls, pts])
    return write(os.path.join(OUT, "borders.json"),
                 {"source": "Natural Earth 50m admin-0 boundary lines (public domain)", "lines": out})


def places():
    """Place labels [name, lat, lon, rank, capital] (rank: Natural Earth scalerank, 0 = most prominent) and the
    monitored areas of the daily trend [name, lat0, lat1, lon0, lon1]."""
    pl = []
    for f in natural_earth("ne_50m_populated_places_simple")["features"]:
        p = f["properties"]
        if p["scalerank"] <= 7 or p.get("adm0cap"):
            pl.append([" ".join(p["name"].split()), round(p["latitude"], 2), round(p["longitude"], 2), p["scalerank"], 1 if p.get("adm0cap") else 0])
    pl.sort(key=lambda r: (r[3], -r[4]))
    areas = [[name] + list(box) for name, box in DAILY_AREAS.items()]
    return write(os.path.join(OUT, "places.json"),
                 {"source": "Natural Earth 50m populated places (public domain); monitored areas from the daily trend",
                  "places": pl, "areas": areas})


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--basemap":
        print(json.dumps({"borders_kb": borders() // 1024, "places_kb": places() // 1024}))
        return
    if len(sys.argv) == 4 and sys.argv[1] == "--map-day":
        size, st = map_day(sys.argv[2], sys.argv[3])
        print(json.dumps({"day": sys.argv[2], "kb": round(size / 1024), **st}))
        return
    if len(sys.argv) == 4 and sys.argv[1] == "--hotspot-day":
        hotspot_day(sys.argv[2], sys.argv[3])
        print(open(sys.argv[3], encoding="utf-8").read())
        return
    idx = map_days()
    for day in DAYS:                                   # the map page's events panel
        if not write_events(day, ANALYSIS, os.path.join(OUT, "events")):
            sys.exit(f"{day}: analysis files missing in {ANALYSIS} (run pipeline/pnt_analysis.py)")
    charts ={"licence": "ODbL 1.0; derived from adsb.lol (data/pnt). Aggregates only.",
              "egnos": egnos(), "storm": storm(), "bay": bay(), "hotspots": hotspots(), "types": types()}
    size = write(os.path.join(OUT, "charts.json"), charts)
    lsize = land()
    borders(); places()
    print(f"map days: {len(idx)} ({sum(d['kb'] for d in idx) / 1024:.1f} MB); charts.json {size // 1024} KB; land.json {lsize // 1024} KB")
    for d in idx:
        print(f"  {d['day']}  hexes(5+) {d['hexes']:6d}  jamming-scale hexes {d['jam_hexes']:5d}  {d['kb']} KB  {d['note']}")


if __name__ == "__main__":
    main()
