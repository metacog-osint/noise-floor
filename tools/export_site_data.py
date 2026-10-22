#!/usr/bin/env python3
"""Export public visual data for the site from the processed GNSS days (data/pnt/, gitignored).

  python tools/export_site_data.py      # writes site/data/gnss/*.json, site/data/charts.json, site/data/land.json

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

DAILY = os.path.join(ROOT, "data", "pnt", "daily")
ANALYSIS = os.path.join(ROOT, "data", "pnt", "analysis")
OUT = os.path.join(ROOT, "site", "data")
LAND_SRC = os.path.join(ROOT, "nisar", "nisar_rfi", "assets", "land.geojson.gz")

DAYS = [f"2025-10-{d:02d}" for d in range(9, 26)] + ["2025-11-11", "2025-11-12", "2026-09-22"]
NOTES = {**{f"2025-10-{d}": "EGNOS outage" for d in range(13, 18)},
         "2025-10-18": "G2 geomagnetic storm", "2025-11-12": "G4 geomagnetic storm (00–06Z)",
         "2025-11-11": "Day before the G4 storm", "2026-09-22": "California GPS loss"}
NORTH_TIER = (43.0, 55.0, -125.0, -65.0)      # validation case A (tools/validate_cases.py)
BAY = (35.5, 38.5, -123.5, -119.5)            # validation case B
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


def map_days():
    index = []
    for day in DAYS:
        rows = [r for r in daily(day) if r["aircraft"] >= 3]
        cells = [[r["h3"], r["aircraft"], r["bad_nacp_live"], r["bad_nacp"], r["capable"], r["cap_bad_acc10"]] for r in rows]
        size = write(os.path.join(OUT, "gnss", f"{day}.json"),
                     {"day": day, "licence": "ODbL 1.0; derived from adsb.lol", "cols": ["h3", "aircraft", "bad_live", "bad_raw",
                                                                                         "capable", "capable_bad10"], "cells": cells})
        n5 = [r for r in rows if r["aircraft"] >= 5]
        jam = sum(1 for r in n5 if 100 * max(r["bad_nacp_live"] - 1, 0) / r["aircraft"] >= 10)
        index.append({"day": day, "note": NOTES.get(day, ""), "hexes": len(n5), "jam_hexes": jam, "kb": round(size / 1024)})
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


def hotspots():
    out = {name: [] for name in HOTSPOTS}
    for day in DAYS[:17]:
        rows = daily(day)
        for name in HOTSPOTS:
            box = SUBREGIONS[name]
            sel = [r for r in rows if in_box(r, box)]
            ac = sum(r["aircraft"] for r in sel)
            out[name].append({"day": day, "share": round(100 * sum(r["bad_nacp_live"] for r in sel) / ac, 1) if ac else None,
                              "aircraft_hexes": ac})
    return out


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


def main():
    idx = map_days()
    charts = {"licence": "ODbL 1.0; derived from adsb.lol (data/pnt). Aggregates only.",
              "egnos": egnos(), "storm": storm(), "bay": bay(), "hotspots": hotspots(), "types": types()}
    size = write(os.path.join(OUT, "charts.json"), charts)
    lsize = land()
    print(f"map days: {len(idx)} ({sum(d['kb'] for d in idx) / 1024:.1f} MB); charts.json {size // 1024} KB; land.json {lsize // 1024} KB")
    for d in idx:
        print(f"  {d['day']}  hexes(5+) {d['hexes']:6d}  jamming-scale hexes {d['jam_hexes']:5d}  {d['kb']} KB  {d['note']}")


if __name__ == "__main__":
    main()
