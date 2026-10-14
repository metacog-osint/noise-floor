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
from collections import defaultdict
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
STORM_KP = 5.0

BASE_DAYS, BASE_WINDOW, BASE_MIN_DAYS = 14, 30, 5
REGION_RES = 2
ANOM_MIN_AIRCRAFT = 30   # aircraft-hex-hours in the region-hour
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
        d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "emso-tracker (research)"}), timeout=30))
        return {int(t[11:13]) + i: k for t, k in zip(d["datetime"], d["Kp"]) for i in range(3)}
    except Exception:
        return None


def sbas(day, use_kp=True):
    rows = _read(day, "hourly")
    agg = {a: [[0, 0] for _ in range(24)] for a in SBAS_AREAS}
    for r in rows:
        la, lo = ll(r["h3"])
        for a, (a0, a1, o0, o1) in SBAS_AREAS.items():
            if a0 <= la <= a1 and o0 <= lo <= o1:
                x = agg[a][r["hour"]]; x[0] += r["capable"]; x[1] += r["cap_bad_acc10"]
    kp = kp_hours(day) if use_kp else None
    out = {"day": day, "kp_source": "GFZ Potsdam (CC BY 4.0)" if kp else None, "areas": {}}
    for a, hours in agg.items():
        flags = []
        for h, (n, b) in enumerate(hours):
            if n < SBAS_MIN_CAPABLE:
                flags.append(None); continue
            share = 100 * b / n
            state = "outage" if share >= SBAS_OUTAGE else "degraded" if share >= SBAS_DEGRADED else "ok"
            if state != "ok" and kp is not None:
                state += " (storm)" if kp.get(h, 0) >= STORM_KP else " (quiet Kp: probable SBAS service problem)"
            flags.append({"hour": h, "capable": n, "share": round(share, 1), "state": state})
        bad = [f for f in flags if f and not f["state"].startswith("ok")]
        out["areas"][a] = {"flagged_hours": len(bad), "hours": flags}
    return out


def flagged_hours(sb):
    """{(area, hour)} flagged in an sbas() result."""
    return {(a, f["hour"]) for a, v in sb["areas"].items() for f in v["hours"] if f and not f["state"].startswith("ok")}


def area_of(cell):
    la, lo = ll(cell)
    return next((a for a, (a0, a1, o0, o1) in SBAS_AREAS.items() if a0 <= la <= a1 and o0 <= lo <= o1), None)


def region_hours(day, sbas_flags):
    """{(region, hour): [aircraft, gross bad, capable (unflagged), capable bad (unflagged)]}."""
    rows = _read(day, "hourly")
    out = defaultdict(lambda: [0, 0, 0, 0])
    for r in rows:
        x = out[(parent(r["h3"]), r["hour"])]
        x[0] += r["aircraft"]; x[1] += r["bad_nacp"]
        if (area_of(r["h3"]), r["hour"]) not in sbas_flags:
            x[2] += r["capable"]; x[3] += r["cap_bad_acc10"]
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
            if cur > med + max(floor, ANOM_K * m):
                la, lo = h3.cell_to_latlng(reg)
                found.append({"region": reg, "lat": round(la, 2), "lon": round(lo, 2), "hour": hour, "measure": name,
                              "share": round(cur, 1), "baseline_median": round(med, 1), "baseline_mad": round(m, 2),
                              "n": den, "baseline_n_days": len(xs)})
    found.sort(key=lambda f: (f["measure"], -(f["share"] - f["baseline_median"])))
    return {"day": day, "baseline_days": bdays, "anomalies": found}


def bursts(day):
    rows = _read(day, "minute")
    if rows is None:
        return {"day": day, "error": "no minute data (processor < 1.2)"}
    series = defaultdict(lambda: [0] * 1440)
    for r in rows:
        series[parent(r["h3"])][r["minute"]] += r["bad_nacp"]
    found = []
    for reg, s in series.items():
        med = statistics.median(s); m = mad(s, med)
        thr = max(BURST_MIN_COUNT, med + BURST_K * max(m, 1.0))
        run = None
        for minute, v in enumerate(s + [0]):
            if v >= thr and minute < 1440:
                run = run or [minute, minute, 0]; run[1] = minute; run[2] = max(run[2], v)
            elif run:
                if run[1] - run[0] + 1 >= BURST_MIN_MINUTES:
                    la, lo = h3.cell_to_latlng(reg)
                    found.append({"region": reg, "lat": round(la, 2), "lon": round(lo, 2),
                                  "start": f"{run[0] // 60:02d}:{run[0] % 60:02d}Z", "end": f"{run[1] // 60:02d}:{run[1] % 60:02d}Z",
                                  "minutes": run[1] - run[0] + 1, "peak_aircraft": run[2], "day_median": med, "threshold": round(thr, 1)})
                run = None
    found.sort(key=lambda f: -f["peak_aircraft"])
    return {"day": day, "bursts": found}


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
            cache[d] = json.load(open(p)) if os.path.exists(p) else sbas(d, not a.no_kp)
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
                          "anomalies": len(an.get("anomalies", [])), "bursts": len(bu.get("bursts", []))}))


if __name__ == "__main__":
    main()
