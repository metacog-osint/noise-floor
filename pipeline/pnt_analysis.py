#!/usr/bin/env python3
"""pnt_analysis.py — post-processing of pnt_daily outputs (Phase 1.2).

  sbas   SBAS service flag per service area and UTC hour, from our own data. When most 10 m-capable aircraft across
         a whole SBAS service area fall below 10 m at once, the cause is the augmentation service (outage) or a
         storm, not local interference. Kp labels which. Flagged hours are excluded from 10 m baselines.
  base   Same-hour baselines per H3 res-2 region over up to BASE_DAYS earlier days (within BASE_WINDOW days), and
         anomalies for the target day on the gross (93 m) and capable (10 m) shares.
  burst  Minute-level bursts per H3 res-2 region: runs of minutes where aircraft with a gross-bad report exceed the
         region's own robust level for the day.

Outputs go to data/pnt/analysis/<day>.{sbas,anomalies,bursts}.json (gitignored).

Usage
  python pipeline/pnt_analysis.py 2025-10-23 [--kp]     # all three analyses for one day
"""
import argparse, json, os, statistics, urllib.request
from collections import Counter, defaultdict
from datetime import date, timedelta

import h3
import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY = os.path.join(ROOT, "data", "pnt", "daily")
OUT = os.path.join(ROOT, "data", "pnt", "analysis")

# Approximate SBAS service areas (lat_min, lat_max, lon_min, lon_max). Boxes, not official coverage polygons.
SBAS_AREAS = {
    "EGNOS (Europe)": (36.0, 71.0, -10.0, 30.0),
    "WAAS (CONUS)": (25.0, 49.0, -124.0, -67.0),
    "WAAS (Canada)": (49.0, 62.0, -130.0, -55.0),
    "MSAS (Japan)": (30.0, 45.0, 129.0, 146.0),
    "KASS (Korea)": (33.0, 38.5, 125.0, 130.0),
    "GAGAN (India)": (8.0, 32.0, 68.0, 90.0),
    "SouthPAN (Australia/NZ)": (-44.0, -12.0, 113.0, 178.0),
}
SBAS_OUTAGE = 60.0      # % of capable aircraft below 10 m, area-wide
SBAS_DEGRADED = 35.0
SBAS_MIN_CAPABLE = 200  # capable aircraft-hex-hours in the area for the hour to count
SBAS_OUTAGE_EXCESS = 30.0    # with a baseline: points above the area's same-hour median
SBAS_DEGRADED_EXCESS = 20.0
SBAS_K = 4.0                 # and more than 4 x the area-hour's MAD
STORM_KP = 5.0

BASE_DAYS, BASE_WINDOW, BASE_MIN_DAYS = 14, 30, 5
REGION_RES = 2
ANOM_MIN_AIRCRAFT = 50   # aircraft-hex-hours in the region-hour
ANOM_Z = 4.0             # binomial z against the baseline rate (floored at 0.5%)
ANOM_FLOOR_GROSS = 2.0   # percentage points above the median, at least
ANOM_FLOOR_CAP = 10.0
ANOM_K = 4.0             # times the MAD

BURST_MIN_COUNT = 5      # aircraft with a gross-bad report in a minute, at least
BURST_K = 5.0
BURST_MIN_MINUTES = 3


def _read(day, kind):
    p = os.path.join(DAILY, f"{day}.{kind}.parquet" if kind else f"{day}.parquet")
    return pq.read_table(p).to_pylist() if os.path.exists(p) else None


_LL, _PAR = {}, {}


def ll(cell):
    if cell not in _LL:
        _LL[cell] = h3.cell_to_latlng(cell)
    return _LL[cell]


def parent(cell):
    if cell not in _PAR:
        _PAR[cell] = h3.cell_to_parent(cell, REGION_RES)
    return _PAR[cell]


def kp_hours(day):
    """GFZ Kp (CC BY 4.0) for the day as {hour: kp}, None if unreachable."""
    try:
        url = f"https://kp.gfz.de/app/json/?start={day}T00:00:00Z&end={day}T23:59:59Z&index=Kp"
        d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "noise-floor (research)"}), timeout=30))
        return {int(t[11:13]) + i: k for t, k in zip(d["datetime"], d["Kp"]) for i in range(3)}
    except Exception:
        return None


_AS = {}


def area_shares(day):
    """{area: [(capable, share %) or None] * 24}, cached per day."""
    if day not in _AS:
        agg = {a: [[0, 0] for _ in range(24)] for a in SBAS_AREAS}
        for r in _read(day, "hourly"):
            la, lo = ll(r["h3"])
            for a, (a0, a1, o0, o1) in SBAS_AREAS.items():
                if a0 <= la <= a1 and o0 <= lo <= o1:
                    x = agg[a][r["hour"]]; x[0] += r["capable"]; x[1] += r["cap_bad_acc10"]
        _AS[day] = {a: [(n, 100 * b / n) if n >= SBAS_MIN_CAPABLE else None for n, b in hrs] for a, hrs in agg.items()}
    return _AS[day]


def sbas(day, use_kp=True, prior=None):
    """Flag SBAS service hours. With `prior` (day -> sbas result), compare each area-hour with the median of the same
    hour on earlier unflagged days, so areas where most capable aircraft routinely lose 10 m (e.g. where airliners
    can't use the local SBAS) aren't flagged every day. Without enough history, fall back to absolute thresholds."""
    cur = area_shares(day)
    hist = {a: [[] for _ in range(24)] for a in SBAS_AREAS}
    if prior:
        for d in baseline_days(day):
            # leave out hours flagged against a baseline; keep hours flagged only on absolute thresholds (no history
            # yet), or an area that is always high would never get a baseline
            fl = {(a, f["hour"]) for a, v in prior(d)["areas"].items() for f in v["hours"]
                  if f and not f["state"].startswith("ok") and f.get("basis") == "baseline"}
            for a, hrs in area_shares(d).items():
                for h, x in enumerate(hrs):
                    if x and (a, h) not in fl:
                        hist[a][h].append(x[1])
    kp = kp_hours(day) if use_kp else None
    out = {"day": day, "kp_source": "GFZ Potsdam (CC BY 4.0)" if kp else None, "areas": {}}
    for a, hrs in cur.items():
        flags = []
        for h, x in enumerate(hrs):
            if not x:
                flags.append(None); continue
            n, share = x
            med = statistics.median(hist[a][h]) if len(hist[a][h]) >= BASE_MIN_DAYS else None
            if med is None:
                state = "outage" if share >= SBAS_OUTAGE else "degraded" if share >= SBAS_DEGRADED else "ok"
            else:
                spread = SBAS_K * mad(hist[a][h], med)
                state = ("outage" if share >= SBAS_OUTAGE and share - med >= max(SBAS_OUTAGE_EXCESS, spread) else
                         "degraded" if share >= SBAS_DEGRADED and share - med >= max(SBAS_DEGRADED_EXCESS, spread) else "ok")
            if state != "ok" and kp is not None:
                # storm effects lag and outlast the 3-hourly index: look 3 h either side
                state += " (storm)" if max(kp.get(h + k, 0) for k in range(-3, 4)) >= STORM_KP else " (quiet Kp: probable SBAS service problem)"
            flags.append({"hour": h, "capable": n, "share": round(share, 1), "state": state,
                          "baseline_median": None if med is None else round(med, 1),
                          "basis": "absolute" if med is None else "baseline"})
        bad = [f for f in flags if f and not f["state"].startswith("ok")]
        out["areas"][a] = {"flagged_hours": len(bad), "hours": flags}
    return out


def flagged_hours(sb):
    """{(area, hour)} flagged in an sbas() result."""
    return {(a, f["hour"]) for a, v in sb["areas"].items() for f in v["hours"] if f and not f["state"].startswith("ok")}


def area_of(cell):
    la, lo = ll(cell)
    return next((a for a, (a0, a1, o0, o1) in SBAS_AREAS.items() if a0 <= la <= a1 and o0 <= lo <= o1), None)


_RH = {}


def region_hours(day, sbas_flags):
    """{(region, hour): [aircraft, gross bad, capable (unflagged), capable bad (unflagged)]}. Cached per day."""
    if day in _RH:
        return _RH[day]
    rows = _read(day, "hourly")
    out = defaultdict(lambda: [0, 0, 0, 0])
    for r in rows:
        x = out[(parent(r["h3"]), r["hour"])]
        x[0] += r["aircraft"]; x[1] += r.get("bad_nacp_live", r["bad_nacp"])   # latched aircraft aren't new interference
        if (area_of(r["h3"]), r["hour"]) not in sbas_flags:
            x[2] += r["capable"]; x[3] += r["cap_bad_acc10"]
    _RH[day] = out
    return out


def baseline_days(day):
    d0 = date.fromisoformat(day)
    days = []
    for k in range(1, BASE_WINDOW + 1):
        d = (d0 - timedelta(days=k)).isoformat()
        if os.path.exists(os.path.join(DAILY, f"{d}.hourly.parquet")):
            days.append(d)
        if len(days) == BASE_DAYS:
            break
    return days


def mad(xs, med):
    return statistics.median(abs(x - med) for x in xs) if xs else 0.0


def _near(a, b, k):
    try:
        return h3.grid_distance(a, b) <= k
    except Exception:
        return False


def _mins(hhmm):
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


def group(items, linked):
    """Union-find: connected groups of items under the pairwise predicate `linked`."""
    up = list(range(len(items)))

    def root(i):
        while up[i] != i:
            up[i] = up[up[i]]; i = up[i]
        return i
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if linked(items[i], items[j]):
                up[root(i)] = root(j)
    out = defaultdict(list)
    for i, it in enumerate(items):
        out[root(i)].append(it)
    return list(out.values())


def anomaly_events(found):
    """Adjacent region-hours (ring 1, within one hour) on the same measure -> events, ranked by size x excess."""
    ev = []
    for measure in ("gross", "capable_10m"):
        fs = [f for f in found if f["measure"] == measure]
        for g in group(fs, lambda x, y: abs(x["hour"] - y["hour"]) <= 1 and _near(x["region"], y["region"], 1)):
            ex = max(f["share"] - f["baseline_median"] for f in g)
            ev.append({"measure": measure, "start_hour": min(f["hour"] for f in g), "end_hour": max(f["hour"] for f in g),
                       "regions": len({f["region"] for f in g}), "region_hours": len(g), "peak_excess": round(ex, 1),
                       "peak_share": max(f["share"] for f in g),
                       "lat": round(sum(f["lat"] for f in g) / len(g), 2), "lon": round(sum(f["lon"] for f in g) / len(g), 2),
                       "tier": "major" if ex >= 25 else "notable" if ex >= 10 else "minor",
                       "cells": sorted({f["region"] for f in g})})
    ev.sort(key=lambda e: -e["region_hours"] * e["peak_excess"])
    return ev


def anomalies(day, sbas_cache):
    bdays = baseline_days(day)
    if len(bdays) < BASE_MIN_DAYS:
        return {"day": day, "baseline_days": bdays, "error": f"need >= {BASE_MIN_DAYS} baseline days"}
    hist = defaultdict(lambda: ([], []))   # (region, hour) -> (gross shares, capable shares)
    for d in bdays:
        for key, (n, b, cn, cb) in region_hours(d, flagged_hours(sbas_cache(d))).items():
            if n >= ANOM_MIN_AIRCRAFT:
                hist[key][0].append(100 * b / n)
            if cn >= ANOM_MIN_AIRCRAFT:
                hist[key][1].append(100 * cb / cn)
    found = []
    for (reg, hour), (n, b, cn, cb) in region_hours(day, flagged_hours(sbas_cache(day))).items():
        g, c = hist.get((reg, hour), ([], []))
        for name, num, den, xs, floor in (("gross", b, n, g, ANOM_FLOOR_GROSS), ("capable_10m", cb, cn, c, ANOM_FLOOR_CAP)):
            if den < ANOM_MIN_AIRCRAFT or len(xs) < BASE_MIN_DAYS:
                continue
            cur = 100 * num / den; med = statistics.median(xs); m = mad(xs, med)
            p0 = min(max(med / 100, 0.005), 0.995)
            z = (num - den * p0) / (den * p0 * (1 - p0)) ** 0.5
            if cur > med + max(floor, ANOM_K * m) and z >= ANOM_Z:
                la, lo = h3.cell_to_latlng(reg)
                found.append({"region": reg, "lat": round(la, 2), "lon": round(lo, 2), "hour": hour, "measure": name,
                              "share": round(cur, 1), "baseline_median": round(med, 1), "baseline_mad": round(m, 2),
                              "n": den, "z": round(z, 1), "baseline_n_days": len(xs)})
    found.sort(key=lambda f: (f["measure"], -(f["share"] - f["baseline_median"])))
    return {"day": day, "baseline_days": bdays, "anomalies": found, "events": anomaly_events(found)}


_MS = {}


def minute_series(day, level):
    """{region: [aircraft with a gross-bad report] * 1440}, cached; None without minute data.
    level "2": H3 res-2 cells. level "2n": each active res-2 cell plus its ring-1 neighbours (events that straddle
    cell edges)."""
    key = (day, level)
    if key not in _MS:
        rows = _read(day, "minute")
        if rows is None:
            _MS[key] = None
        elif level == "2":
            s = defaultdict(lambda: [0] * 1440)
            for r in rows:   # live: leave out aircraft whose degradation is latched from earlier in the flight
                s[parent(r["h3"])][r["minute"]] += r["bad_nacp"] - r.get("latched", 0)
            _MS[key] = dict(s)
        else:
            base = minute_series(day, "2")
            _MS[key] = {c: [sum(col) for col in zip(*(base[x] for x in h3.grid_disk(c, 1) if x in base))] for c in base}
    return _MS[key]


def bursts(day):
    """Runs of >= BURST_MIN_MINUTES minutes above a threshold, per region, at H3 res 2 and res 1. With >= 5 earlier
    days of minute data the threshold follows the same 15-minute slot on those days (daily traffic waves through
    regions with persistent interference stay below it); otherwise it is the day's own median + 5 x MAD."""
    if minute_series(day, "2") is None:
        return {"day": day, "error": "no minute data (processor < 1.2)"}
    prior_days = [d for d in baseline_days(day) if os.path.exists(os.path.join(DAILY, f"{d}.minute.parquet"))]
    found = []
    for res in ("2", "2n"):
        series = minute_series(day, res)
        hist = [minute_series(d, res) for d in prior_days] if len(prior_days) >= BASE_MIN_DAYS else None
        for reg, s in series.items():
            if hist:
                thr = []
                for slot in range(96):
                    vals = [sum((h.get(reg) or [0] * 1440)[slot * 15:(slot + 1) * 15]) / 15 for h in hist]
                    med = statistics.median(vals); m = mad(vals, med)
                    thr += [max(BURST_MIN_COUNT, med + BURST_K * max(m, 1.0))] * 15
                basis, med_day = f"prior {len(hist)} days, same 15-min slot", None
            else:
                med_day = statistics.median(s); m = mad(s, med_day)
                thr = [max(BURST_MIN_COUNT, med_day + BURST_K * max(m, 1.0))] * 1440
                basis = "within day"
            run = None
            for minute in range(1441):
                v = s[minute] if minute < 1440 else 0
                if minute < 1440 and v >= thr[minute]:
                    run = run or [minute, minute, 0]; run[1] = minute; run[2] = max(run[2], v)
                elif run:
                    if run[1] - run[0] + 1 >= BURST_MIN_MINUTES:
                        la, lo = h3.cell_to_latlng(reg)
                        found.append({"res": res, "region": reg, "lat": round(la, 2), "lon": round(lo, 2),
                                      "start": f"{run[0] // 60:02d}:{run[0] % 60:02d}Z", "end": f"{run[1] // 60:02d}:{run[1] % 60:02d}Z",
                                      "minutes": run[1] - run[0] + 1, "peak_aircraft": run[2], "basis": basis,
                                      "day_median": med_day, "threshold": round(thr[run[0]], 1)})
                    run = None
    found.sort(key=lambda f: (f["res"], -f["peak_aircraft"]))
    groups = group(found, lambda x, y: _near(x["region"], y["region"], 2) and _mins(x["start"]) <= _mins(y["end"]) + 5
                   and _mins(y["start"]) <= _mins(x["end"]) + 5)
    ev = []
    for g in groups:
        ev.append({"start": min(f["start"] for f in g), "end": max(f["end"] for f in g),
                   "peak_aircraft": max(f["peak_aircraft"] for f in g),
                   "lat": round(sum(f["lat"] for f in g) / len(g), 2), "lon": round(sum(f["lon"] for f in g) / len(g), 2),
                   "detections": len(g), "regions": len({f["region"] for f in g}), "basis": g[0]["basis"],
                   "cells": sorted({f["region"] for f in g})})
    ev.sort(key=lambda e: -e["peak_aircraft"])
    return {"day": day, "bursts": found, "events": ev}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("days", nargs="+")
    ap.add_argument("--no-kp", action="store_true")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    cache = {}

    def sbas_cache(d):
        if d not in cache:
            p = os.path.join(OUT, f"{d}.sbas.json")
            cache[d] = json.load(open(p)) if os.path.exists(p) else sbas(d, not a.no_kp, prior=sbas_cache)
            json.dump(cache[d], open(p, "w"), indent=1)
        return cache[d]

    for day in a.days:
        sb = sbas_cache(day)
        an = anomalies(day, sbas_cache)
        bu = bursts(day)
        json.dump(an, open(os.path.join(OUT, f"{day}.anomalies.json"), "w"), indent=1)
        json.dump(bu, open(os.path.join(OUT, f"{day}.bursts.json"), "w"), indent=1)
        flagged = {k: v["flagged_hours"] for k, v in sb["areas"].items() if v["flagged_hours"]}
        print(json.dumps({"day": day, "sbas_flagged_hours": flagged, "baseline_days": len(an.get("baseline_days", [])),
                          "anomaly_region_hours": len(an.get("anomalies", [])),
                          "anomaly_events": dict(Counter(e["tier"] for e in an.get("events", []))),
                          "burst_events": len(bu.get("events", []))}))


if __name__ == "__main__":
    main()
