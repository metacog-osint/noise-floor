#!/usr/bin/env python3
"""event_floor.py: the pre-registered event-grade test (docs/validation/event-floor.md, frozen 16 Nov 2026 in e285899).

  python tools/event_floor.py day 2026-11-13 [--daily data/pnt/daily] [--analysis data/pnt/analysis] [--out data/event_floor]
  python tools/event_floor.py score data/event_floor [--cache data/event_floor_cache] [--report report.json]

`day` reads one day's pnt_analysis anomalies (V0, the current grade), its hourly table (heavy_share) and its
region_hourly table (distinct aircraft per res-2 region-hour, pnt_daily from 17 Nov 2026), and writes the gross (93 m)
events under each variant:
  V0  the current grade
  F   gross region-hours with fewer than FLOOR distinct live gross-bad aircraft are dropped, then events regrouped
  H   V0, then events with heavy_share >= HEAVY drop one tier (major -> notable, notable -> minor)
  FH  F, then H's demotion
Each event keeps its region-hours, so a V0 event is followed into each variant exactly. Counts only: no addresses.

`score` applies the write-up's corroboration rules and pass marks P1-P6 to a folder of day files, reading the published
day maps, event files (declared tests) and spoofing files from the live site. The rules and marks below are copied from
the write-up and must not change after scoring starts.
"""
import argparse
import json
import math
import os
import sys
import urllib.request
from datetime import date, timedelta

import h3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

FLOOR, HEAVY = 3, 0.5
RANK = {"none": 0, "minor": 1, "notable": 2, "major": 3}
DOWN = {"major": "notable", "notable": "minor", "minor": "minor"}
SITE = "https://noisefloor.theintelligence.company"
UA = {"User-Agent": "noise-floor event-floor test (github.com/metacog-osint/noise-floor)"}

SET_A = [f"2025-10-{d:02d}" for d in range(9, 26)] + ["2025-11-11", "2025-11-12", "2026-09-22"]
SET_B = [(date(2026, 10, 25) + timedelta(k)).isoformat() for k in range(22)]       # 25 Oct - 15 Nov 2026
SET_C = [(date(2026, 11, 16) + timedelta(k)).isoformat() for k in range(14)]       # 16 - 29 Nov 2026, held out
# Validation hotspot boxes (lat0, lat1, lon0, lon1): tools/validate_phase1.py SUBREGIONS, the HOTSPOTS list of
# tools/export_site_data.py at 9ec9e6a without the high-latitude control.
HOTSPOT_BOXES = {
    "Kaliningrad and approaches": (54.0, 55.6, 19.0, 23.0),
    "Gulf of Finland / Estonia–Russia border": (58.5, 60.5, 24.0, 32.0),
    "Southern Black Sea offshore Turkey": (41.3, 42.5, 34.0, 41.0),
    "Western Black Sea coast": (42.0, 45.5, 27.0, 30.0),
    "Caucasus": (40.0, 43.5, 41.0, 49.0),
}
# P3: FAA flight advisory PMSRCA GPS 26-03 (Rev 2), 22 Sep 2026 18:30-20:29Z, centre 34.36N 121.69W, 623 NM at FL250
MUGU = {"day": "2026-09-22", "lat": 34.36, "lon": -121.69, "km": 623 * 1.852, "h0": 18, "h1": 20}
MARKS = {"P1": 0.90, "P2": 0.95, "P4": 0.90, "P5": 0.75, "P6": 0.50}
CASES = [("2026-11-13", 54.33, -4.25, "Irish Sea notable, 04 UTC, heavy share 1.0"),
         ("2026-11-13", 13.27, 81.24, "Bay of Bengal notable, 17-18 UTC, heavy share 1.0"),
         ("2026-11-15", 41.26, 41.05, "Turkish-Georgian Black Sea coast majors, heavy share 0.80 and 0.70")]


# ---------------------------------------------------------------------------------------------------------- day

def _linked(x, y):
    import pnt_analysis as PA
    return abs(x["hour"] - y["hour"]) <= 1 and PA._near(x["region"], y["region"], 1)


def events(found, hh):
    """Gross events from anomalous region-hours, as pnt_analysis.anomaly_events() grades them, each with its
    region-hours ("rh": [[region, hour], ...])."""
    import pnt_analysis as PA
    fs = [f for f in found if f["measure"] == "gross"]
    out = []
    for g in PA.group(fs, _linked):
        e = PA.anomaly_events(g, hh)[0]          # one connected group -> one event, graded by the analysis itself
        e["rh"] = sorted([f["region"], f["hour"]] for f in g)
        out.append(e)
    out.sort(key=lambda e: -e["region_hours"] * e["peak_excess"])
    return out


def demote(evs):
    out = []
    for e in evs:
        e = dict(e)
        if (e.get("heavy_share") or 0) >= HEAVY:
            e["tier_before"], e["tier"] = e["tier"], DOWN[e["tier"]]
        out.append(e)
    return out


def floor(found, distinct):
    """found without the gross region-hours under FLOOR distinct live gross-bad aircraft."""
    return [f for f in found if f["measure"] != "gross" or distinct.get((f["region"], f["hour"]), 0) >= FLOOR]


def read_distinct(path):
    import pyarrow.parquet as pq
    t = pq.read_table(path, columns=["h3", "hour", "bad_live_aircraft"]).to_pydict()
    return {(r, int(h)): int(n) for r, h, n in zip(t["h3"], t["hour"], t["bad_live_aircraft"])}


def slim(e, distinct=None):
    keep = ("tier", "tier_before", "start_hour", "end_hour", "regions", "region_hours", "peak_excess", "peak_share",
            "lat", "lon", "cells", "heavy_share", "rh")
    out = {k: e[k] for k in keep if k in e}
    if distinct is not None:
        out["distinct_min"] = min((distinct.get((r, h), 0) for r, h in e["rh"]), default=0)
        out["distinct_max"] = max((distinct.get((r, h), 0) for r, h in e["rh"]), default=0)
    return out


def day_cmd(a):
    import pnt_analysis as PA
    PA.DAILY = a.daily
    an = json.load(open(os.path.join(a.analysis, f"{a.day}.anomalies.json")))
    if an.get("error"):
        out = {"day": a.day, "error": an["error"]}
    else:
        found = an["anomalies"]
        hh = PA.heavy_hours(a.day)
        distinct = read_distinct(os.path.join(a.daily, f"{a.day}.region_hourly.parquet"))
        v0 = events(found, hh)
        ff = floor(found, distinct)
        f = events(ff, hh)
        gross = [x for x in found if x["measure"] == "gross"]
        out = {"day": a.day, "floor": FLOOR, "heavy": HEAVY, "heavy_share_available": hh is not None,
               "gross_region_hours": len(gross), "gross_region_hours_after_floor": sum(1 for x in ff if x["measure"] == "gross"),
               "variants": {"V0": [slim(e, distinct) for e in v0], "F": [slim(e, distinct) for e in f],
                            "H": [slim(e, distinct) for e in demote(v0)], "FH": [slim(e, distinct) for e in demote(f)]}}
    os.makedirs(a.out, exist_ok=True)
    p = os.path.join(a.out, f"{a.day}.event-floor.json")
    json.dump(out, open(p, "w"), indent=1)
    v = out.get("variants") or {}
    print(json.dumps({"day": a.day, "error": out.get("error"),
                      **{k: {t: sum(1 for e in v[k] if e["tier"] == t) for t in ("major", "notable")} for k in v}}))


# ---------------------------------------------------------------------------------------------------------- score

def outcome(e, variant_events):
    """The best tier a V0 event keeps under a variant: the highest tier among that variant's events sharing any of its
    region-hours ("none" if every region-hour was dropped)."""
    mine = {tuple(x) for x in e["rh"]}
    best = "none"
    for x in variant_events:
        if mine & {tuple(y) for y in x["rh"]} and RANK[x["tier"]] > RANK[best]:
            best = x["tier"]
    return best


def km(a, b, c, d):
    p = math.pi / 180
    h = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742 * math.asin(min(1.0, math.sqrt(h)))


class Site:
    """Published files from the live site, cached on disk."""

    def __init__(self, cache, base=SITE):
        self.cache, self.base, self.mem = cache, base, {}
        os.makedirs(cache, exist_ok=True)

    def get(self, path):
        if path in self.mem:
            return self.mem[path]
        f = os.path.join(self.cache, path.replace("/", "_"))
        if not os.path.exists(f):
            try:
                with urllib.request.urlopen(urllib.request.Request(f"{self.base}/{path}", headers=UA), timeout=120) as r:
                    data = r.read()
            except Exception:
                data = b"null"
            open(f, "wb").write(data)
        self.mem[path] = json.load(open(f, encoding="utf-8"))
        return self.mem[path]

    def jam_regions(self, day):
        import board
        m = self.get(f"data/gnss/{day}.json")
        key = ("jam", day)
        if key not in self.mem:
            self.mem[key] = set(board.jam_regions(m["cells"], m["cols"])) if m and m.get("cells") else None
        return self.mem[key]


def corroborated(e, day, site):
    """The write-up's three rules. Returns the list of rules that hold (empty: uncorroborated)."""
    why = []
    near = set()
    for c in e["cells"]:
        near |= set(h3.grid_disk(c, 1))
    d0 = date.fromisoformat(day)
    seen = 0
    for k in range(1, 31):
        r = site.jam_regions((d0 - timedelta(k)).isoformat())
        seen += bool(r and near & r)
    if seen >= 3:
        why.append(f"established ({seen} of 30 days)")
    ev = site.get(f"data/events/{day}.json") or {}
    for t in ev.get("tests") or []:
        try:
            radius = max(t["radii_nm"].values()) * 1.852
            far = km(e["lat"], e["lon"], t["centre"][0], t["centre"][1])
            hours = any(int(w0[11:13]) <= e["end_hour"] and int(w1[11:13]) >= e["start_hour"] for w0, w1 in t["windows"]
                        if w0[:10] <= day <= w1[:10])
        except (KeyError, TypeError, ValueError):
            continue
        if far <= radius and hours:
            why.append(f"declared test {t.get('id')}")
            break
    sp = site.get(f"data/spoof/{day}.json") or {}
    lv = sp.get("level2") or {}
    if any((lv.get(c) or [None, None])[1] == "above" for c in near):
        why.append("spoofing above usual")
    return why


def in_box(e):
    return next((n for n, (a0, a1, o0, o1) in HOTSPOT_BOXES.items() if a0 <= e["lat"] <= a1 and o0 <= e["lon"] <= o1), None)


def frac(xs):
    return (round(sum(xs) / len(xs), 3) if xs else None), len(xs)


def score_cmd(a):
    files = sorted(f for f in os.listdir(a.dir) if f.endswith(".event-floor.json"))
    days = {}
    for f in files:
        d = json.load(open(os.path.join(a.dir, f)))
        days[d["day"]] = d
    site = Site(a.cache)
    rows = []                                 # one per V0 major/notable event
    per_day = {}
    for day, d in sorted(days.items()):
        if d.get("error"):
            per_day[day] = {"error": d["error"]}
            continue
        v = d["variants"]
        per_day[day] = {k: {t: sum(1 for e in v[k] if e["tier"] == t) for t in ("major", "notable")} for k in v}
        per_day[day]["gross_region_hours"] = [d["gross_region_hours"], d["gross_region_hours_after_floor"]]
        st = "A" if day in SET_A else "B" if day in SET_B else "C" if day in SET_C else "-"
        for e in v["V0"]:
            if e["tier"] not in ("major", "notable"):
                continue
            row = {"day": day, "set": st, "tier": e["tier"], "lat": e["lat"], "lon": e["lon"], "hours": [e["start_hour"], e["end_hour"]],
                   "heavy_share": e.get("heavy_share"), "distinct_min": e.get("distinct_min"), "distinct_max": e.get("distinct_max"),
                   **{k: outcome(e, v[k]) for k in ("F", "H", "FH")}}
            if st == "A":
                row["box"] = in_box(e)
                row["mugu"] = (day == MUGU["day"] and km(e["lat"], e["lon"], MUGU["lat"], MUGU["lon"]) <= MUGU["km"]
                               and e["start_hour"] <= MUGU["h1"] and e["end_hour"] >= MUGU["h0"])
            elif st in ("B", "C"):
                row["corroboration"] = corroborated(e, day, site)
            rows.append(row)

    def marks(var):
        A = [r for r in rows if r["set"] == "A"]
        boxed = [r for r in A if r["box"] and r["tier"] == "major"]
        out = {"P1": frac([r[var] == "major" for r in boxed]), "P2": frac([RANK[r[var]] >= 2 for r in boxed])}
        mugu = [r for r in A if r["mugu"]]
        out["P3"] = (all(RANK[r[var]] >= 2 for r in mugu) if mugu else None, len(mugu))
        for s in ("B", "C"):
            S = [r for r in rows if r["set"] == s]
            cor = [r for r in S if r["corroboration"]]
            unc = [r for r in S if not r["corroboration"]]
            out[f"P4{s}"] = frac([RANK[r[var]] >= 2 for r in cor])
            out[f"P5{s}"] = frac([r[var] == "major" for r in cor if r["tier"] == "major"])
            out[f"P6{s}"] = frac([RANK[r[var]] < RANK[r["tier"]] for r in unc])
        verdict = {}
        for k, (val, n) in out.items():
            base = k[:2]
            if base == "P3":
                verdict[k] = "not scored" if val is None else "pass" if val else "fail"
            elif val is None:
                verdict[k] = "no cases"
            else:
                verdict[k] = "pass" if val >= MARKS[base] else "fail"
        return {"values": out, "verdict": verdict}

    cases = []
    for day, la, lo, what in CASES:
        hits = [r for r in rows if r["day"] == day and km(r["lat"], r["lon"], la, lo) <= 150]
        cases.append({"case": what, "day": day, "events": hits or "not in the scored days or not a V0 major/notable"})
    report = {"rules": "docs/validation/event-floor.md (e285899)", "floor": FLOOR, "heavy": HEAVY,
              "days": sorted(days), "per_day": per_day, "marks": {v: marks(v) for v in ("FH", "F", "H")},
              "cases": cases, "events": rows}
    if a.report:
        json.dump(report, open(a.report, "w"), indent=1)
    print(json.dumps({v: report["marks"][v]["verdict"] for v in report["marks"]}, indent=1))
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("day")
    d.add_argument("day")
    d.add_argument("--daily", default=os.path.join(ROOT, "data", "pnt", "daily"))
    d.add_argument("--analysis", default=os.path.join(ROOT, "data", "pnt", "analysis"))
    d.add_argument("--out", default=os.path.join(ROOT, "data", "event_floor"))
    s = sub.add_parser("score")
    s.add_argument("dir")
    s.add_argument("--cache", default=os.path.join(ROOT, "data", "event_floor_cache"))
    s.add_argument("--report")
    a = ap.parse_args()
    day_cmd(a) if a.cmd == "day" else score_cmd(a)


if __name__ == "__main__":
    main()
