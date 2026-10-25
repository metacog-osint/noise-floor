#!/usr/bin/env python3
"""A year of the daily GNSS tables, read three ways: dated step changes in each named area, weekday and hour-of-day
profiles, and the places where jamming-scale interference started or stopped during the year.

  python tools/year_trends.py                      # reads data/pnt/year/<day>.parquet and .hourly.parquet
  python tools/year_trends.py --no-hourly          # skip the hour-of-day profiles (the slow part)

Writes data/pnt/year_trends.json (aggregates only, ODbL 1.0 as derived from adsb.lol). The write-up is
docs/assessment/year-trends.md.

Measures (the same as the site's):
- Area share: aircraft-hexes in the area's box whose aircraft reported live gross degradation (NACp < 8 after the
  post-exposure tag), divided by all aircraft-hexes in the box. The charts page's daily hotspot trend uses this.
- Jamming-scale hex: a res-4 hex-day with 5 or more aircraft and 100 * max(bad_live - 1, 0) / aircraft >= 10
  (the map's top two classes; the one-aircraft subtraction keeps a single faulty receiver out).
- Active res-3 cell-day: 2 or more of its res-4 children at jamming scale that day.

Step changes: binary segmentation (least squares, segments of at least 21 days) of each area's daily share after a
9-day running median, so surges of 4 days or fewer don't split it. A split is kept when it cuts the squared error by
more than PENALTY * sigma^2 * ln(n) (sigma from the raw series' median absolute day-to-day difference), and when the
raw medians either side differ by 2 points or more and by 30% or more of the lower one; splits failing that are merged
away, smallest first. Days with fewer than MIN_AREA_AC aircraft-hexes are left out. Short surges are listed apart as
spikes: days above the rolling 28-day median by 3 or more robust deviations and by 5 points.

Started / stopped (res-3 cells): compared over the first and last 92 days of the year. A cell counts only if it had
5-aircraft hexes on at least 70% of days in both windows, so a change in coverage isn't read as a change in
interference. Started: active on 10% of days or fewer in the first window and 40% or more in the last. Stopped: the
reverse. Persistent: active on 50% or more of all days with coverage.
"""
import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date

import h3
import numpy as np
import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from export_site_data import DAILY_AREAS  # noqa: E402

YEAR = os.path.join(ROOT, "data", "pnt", "year")
OUT = os.path.join(ROOT, "data", "pnt", "year_trends.json")
PLACES = os.path.join(ROOT, "site", "data", "places.json")
COUNTRIES = os.path.join(ROOT, "data", "cache", "ne_50m_admin_0_countries.geojson")   # Natural Earth, public domain
MIN_AREA_AC = 200          # aircraft-hexes in an area for its day to count
MIN_SEG, PENALTY, SMOOTH = 21, 3.0, 9
MIN_STEP_PTS, MIN_STEP_REL = 2.0, 0.30
WINDOW = 92


def days_available():
    return sorted(f[:10] for f in os.listdir(YEAR) if f.endswith(".parquet") and not f.endswith(".hourly.parquet"))


def area_index(cells, latlng):
    """For each unique cell: index of the first DAILY_AREAS box containing it, or -1."""
    names = list(DAILY_AREAS)
    out = np.full(len(cells), -1, dtype=np.int16)
    for i, c in enumerate(cells):
        la, lo = latlng(c)
        for j, n in enumerate(names):
            b = DAILY_AREAS[n]
            if b[0] <= la <= b[1] and b[2] <= lo <= b[3]:
                out[i] = j
                break
    return out


class LatLng:
    def __init__(self):
        self.c = {}

    def __call__(self, cell):
        if cell not in self.c:
            self.c[cell] = h3.cell_to_latlng(cell)
        return self.c[cell]


def read_daily(days, latlng):
    """Per day: area aircraft-hexes and bad (live), and the set of active res-3 cells and covered res-3 cells."""
    names = list(DAILY_AREAS)
    ac = np.zeros((len(days), len(names))); bad = np.zeros((len(days), len(names)))
    active, covered, jam_hexes = [], [], np.zeros(len(days), dtype=int)
    parent = {}
    for k, day in enumerate(days):
        t = pq.read_table(os.path.join(YEAR, f"{day}.parquet"), columns=["h3", "aircraft", "bad_nacp_live"])
        h = t.column("h3").to_pylist()
        a = t.column("aircraft").to_numpy(zero_copy_only=False).astype(float)
        b = t.column("bad_nacp_live").to_numpy(zero_copy_only=False).astype(float)
        idx = area_index(h, latlng)
        for j in range(len(names)):
            m = idx == j
            ac[k, j], bad[k, j] = a[m].sum(), b[m].sum()
        n5 = a >= 5
        jam = n5 & (100 * np.maximum(b - 1, 0) / np.maximum(a, 1) >= 10)
        jam_hexes[k] = int(jam.sum())
        per = defaultdict(int)
        cov = set()
        for i in np.flatnonzero(n5):
            p = parent.get(h[i]) or parent.setdefault(h[i], h3.cell_to_parent(h[i], 3))
            cov.add(p)
            if jam[i]:
                per[p] += 1
        active.append({p for p, n in per.items() if n >= 2})
        covered.append(cov)
        if k % 50 == 0:
            print(f"  daily {day}", flush=True)
    return ac, bad, active, covered, jam_hexes


def read_hourly(days, latlng):
    """Area x UTC hour: summed aircraft-hexes and bad (live) over the year, from the hourly tables."""
    names = list(DAILY_AREAS)
    ac = np.zeros((len(names), 24)); bad = np.zeros((len(names), 24))
    known = {}
    for k, day in enumerate(days):
        p = os.path.join(YEAR, f"{day}.hourly.parquet")
        if not os.path.exists(p):
            continue
        t = pq.read_table(p, columns=["h3", "hour", "aircraft", "bad_nacp_live"])
        enc = t.column("h3").combine_chunks().dictionary_encode()
        dic = enc.dictionary.to_pylist()
        new = [c for c in dic if c not in known]
        if new:
            for c, j in zip(new, area_index(new, latlng)):
                known[c] = int(j)
        lut = np.array([known[c] for c in dic], dtype=np.int16)
        aidx = lut[enc.indices.to_numpy(zero_copy_only=False)]
        hr = t.column("hour").to_numpy(zero_copy_only=False).astype(int)
        a = t.column("aircraft").to_numpy(zero_copy_only=False).astype(float)
        b = t.column("bad_nacp_live").to_numpy(zero_copy_only=False).astype(float)
        m = aidx >= 0
        np.add.at(ac, (aidx[m], hr[m]), a[m])
        np.add.at(bad, (aidx[m], hr[m]), b[m])
        if k % 50 == 0:
            print(f"  hourly {day}", flush=True)
    return ac, bad


def running_median(y, w):
    h = w // 2
    return np.array([np.median(y[max(0, i - h):i + h + 1]) for i in range(len(y))])


def segments(x, min_seg=MIN_SEG, penalty=PENALTY, smooth=SMOOTH):
    """Binary segmentation of a series with NaN gaps (gaps dropped). Returns split positions in the original index."""
    pos = np.flatnonzero(~np.isnan(x))
    raw = x[pos]
    n = len(raw)
    if n < 2 * min_seg:
        return []
    sigma = 1.4826 * np.median(np.abs(np.diff(raw))) / math.sqrt(2) or 1e-9
    y = running_median(raw, smooth) if smooth > 1 else raw
    thresh = penalty * sigma ** 2 * math.log(n)
    splits = []

    def cost(a, b):
        s = y[a:b]
        return float(((s - s.mean()) ** 2).sum())

    def go(a, b):
        if b - a < 2 * min_seg:
            return
        c0, best, at = cost(a, b), 0.0, None
        cs, cs2 = np.cumsum(y[a:b]), np.cumsum(y[a:b] ** 2)
        tot, tot2, m = cs[-1], cs2[-1], b - a
        for i in range(min_seg, m - min_seg + 1):
            l1, l2 = cs[i - 1], cs2[i - 1]
            r1, r2 = tot - l1, tot2 - l2
            gain = c0 - ((l2 - l1 * l1 / i) + (r2 - r1 * r1 / (m - i)))
            if gain > best:
                best, at = gain, a + i
        if at is not None and best > thresh:
            splits.append(at)
            go(a, at)
            go(at, b)

    go(0, n)
    splits.sort()
    while splits:                                   # merge away steps too small to matter, smallest first
        b = [0] + splits + [n]
        med = [float(np.median(raw[b[i]:b[i + 1]])) for i in range(len(b) - 1)]
        size = [(abs(med[i + 1] - med[i]), i) for i in range(len(splits))]
        weak = [(d, i) for d, i in size if d < MIN_STEP_PTS or d < MIN_STEP_REL * max(min(med[i], med[i + 1]), 0.1)]
        if not weak:
            break
        splits.pop(min(weak)[1])
    return [int(pos[s]) for s in splits]


def spikes(x, days, k=3.0, min_pts=5.0):
    out = []
    for i in range(len(x)):
        if np.isnan(x[i]):
            continue
        w = x[max(0, i - 28):i]
        w = w[~np.isnan(w)]
        if len(w) < 14:
            continue
        med = float(np.median(w))
        mad = 1.4826 * float(np.median(np.abs(w - med))) or 0.5
        if x[i] - med >= max(k * mad, min_pts):
            out.append({"day": days[i], "share": round(float(x[i]), 1), "usual": round(med, 1)})
    return out


def runs(items):
    """Group consecutive spike days into runs."""
    out = []
    for s in items:
        d = date.fromisoformat(s["day"])
        if out and (d - date.fromisoformat(out[-1]["end"])).days == 1:
            out[-1]["end"] = s["day"]; out[-1]["days"] += 1; out[-1]["peak"] = max(out[-1]["peak"], s["share"])
        else:
            out.append({"start": s["day"], "end": s["day"], "days": 1, "peak": s["share"], "usual": s["usual"]})
    return out


def kruskal(groups):
    try:
        from scipy.stats import kruskal as kw
        g = [x for x in groups if len(x) >= 5]
        return float(kw(*g).pvalue) if len(g) >= 2 else None
    except Exception:
        return None


def nearest_place(places, la, lo, limit=400):
    best, name = limit, None
    for p in places:
        d = 12742 * math.asin(min(1.0, math.sqrt(math.sin(math.radians(p[1] - la) / 2) ** 2 + math.cos(math.radians(la)) *
                                                  math.cos(math.radians(p[1])) * math.sin(math.radians(p[2] - lo) / 2) ** 2)))
        if d < best:
            best, name = d, p[0]
    return name, (round(best) if name else None)


class Countries:
    """Country for a point (Natural Earth admin-0), or "sea off <nearest>" within about 300 km; None without the file."""
    def __init__(self, path=COUNTRIES):
        self.shapes = []
        if not os.path.exists(path):
            return
        from shapely.geometry import shape
        for f in json.load(open(path, encoding="utf-8"))["features"]:
            self.shapes.append((f["properties"].get("NAME") or f["properties"].get("ADMIN"), shape(f["geometry"])))

    def __call__(self, la, lo):
        if not self.shapes:
            return None
        from shapely.geometry import Point
        p = Point(lo, la)
        for name, g in self.shapes:
            if g.contains(p):
                return name
        d, name = min((g.distance(p), n) for n, g in self.shapes)
        return f"sea off {name}" if d < 3 else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-hourly", action="store_true")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    days = days_available()
    print(f"{len(days)} days, {days[0]} to {days[-1]}")
    latlng = LatLng()
    names = list(DAILY_AREAS)
    ac, bad, active, covered, jam_hexes = read_daily(days, latlng)
    share = np.where(ac >= MIN_AREA_AC, 100 * bad / np.maximum(ac, 1), np.nan)
    wd = np.array([date.fromisoformat(d).weekday() for d in days])
    areas = {}
    for j, n in enumerate(names):
        x = share[:, j]
        sp = segments(x)
        bounds = [0] + sp + [len(days)]
        segs = []
        for a, b in zip(bounds[:-1], bounds[1:]):
            s = x[a:b]; s = s[~np.isnan(s)]
            n_ac = ac[a:b, j]
            segs.append({"start": days[a], "end": days[b - 1], "days": int(len(s)),
                         "median": round(float(np.median(s)), 1) if len(s) else None,
                         "mean": round(float(np.mean(s)), 1) if len(s) else None,
                         "aircraft_hexes_median": int(np.median(n_ac)) if len(n_ac) else None})
        by_wd = [x[(wd == w) & ~np.isnan(x)] for w in range(7)]
        months = defaultdict(list)
        for i, d in enumerate(days):
            if not np.isnan(x[i]):
                months[d[:7]].append(x[i])
        areas[n] = {
            "box": list(DAILY_AREAS[n]), "days_counted": int((~np.isnan(x)).sum()),
            "median": round(float(np.nanmedian(x)), 1) if (~np.isnan(x)).any() else None,
            "segments": segs, "spike_runs": runs(spikes(x, days)),
            "weekday_median": [round(float(np.median(g)), 1) if len(g) else None for g in by_wd],
            "weekday_n": [int(len(g)) for g in by_wd], "weekday_kruskal_p": kruskal(by_wd),
            "monthly_median": {m: round(float(np.median(v)), 1) for m, v in sorted(months.items())},
            "daily_share": [None if np.isnan(v) else round(float(v), 2) for v in x],
            "daily_aircraft_hexes": [int(v) for v in ac[:, j]],
        }
    # started / stopped / persistent res-3 cells
    nd = len(days)
    w1, w2 = range(0, min(WINDOW, nd)), range(max(0, nd - WINDOW), nd)
    cells = set().union(*covered)
    places = []
    if os.path.exists(PLACES):
        places = [p for p in json.load(open(PLACES, encoding="utf-8")).get("places", []) if p[3] <= 6]
    started, stopped, persistent = [], [], []
    where = Countries()
    for c in cells:
        cov1 = sum(1 for i in w1 if c in covered[i]); cov2 = sum(1 for i in w2 if c in covered[i])
        act1 = sum(1 for i in w1 if c in active[i]); act2 = sum(1 for i in w2 if c in active[i])
        cov_all = sum(1 for i in range(nd) if c in covered[i]); act_all = sum(1 for i in range(nd) if c in active[i])
        la, lo = h3.cell_to_latlng(c)
        rec = None
        if cov1 >= 0.7 * len(w1) and cov2 >= 0.7 * len(w2):
            f1, f2 = act1 / cov1, act2 / cov2
            if f1 <= 0.10 and f2 >= 0.40:
                rec = started
            elif f1 >= 0.40 and f2 <= 0.10:
                rec = stopped
            if rec is not None:
                first = next((days[i] for i in range(nd) if c in active[i]), None)
                last = next((days[i] for i in range(nd - 1, -1, -1) if c in active[i]), None)
                name, dist = nearest_place(places, la, lo)
                rec.append({"cell": c, "lat": round(la, 2), "lon": round(lo, 2), "country": where(la, lo), "near": name, "near_km": dist,
                            "first_window": round(100 * f1, 1), "last_window": round(100 * f2, 1),
                            "first_active": first, "last_active": last})
        if cov_all >= 0.5 * nd and act_all >= 0.5 * cov_all:
            name, dist = nearest_place(places, la, lo)
            persistent.append({"cell": c, "lat": round(la, 2), "lon": round(lo, 2), "country": where(la, lo), "near": name, "near_km": dist,
                               "active_share": round(100 * act_all / cov_all, 1), "days_covered": cov_all})
    started.sort(key=lambda r: -r["last_window"]); stopped.sort(key=lambda r: -r["first_window"])
    persistent.sort(key=lambda r: -r["active_share"])
    out = {"licence": "ODbL 1.0; derived from adsb.lol", "days": [days[0], days[-1], nd], "day_list": days,
           "measure": "area share: aircraft-hexes with live gross degradation / all aircraft-hexes in the box",
           "areas": areas, "jam_hexes_daily": dict(zip(days, map(int, jam_hexes))),
           "windows": {"first": [days[w1[0]], days[w1[-1]]], "last": [days[w2[0]], days[w2[-1]]]},
           "started": started, "stopped": stopped, "persistent": persistent,
           "active_cells_daily": {d: len(a) for d, a in zip(days, active)}}
    if not args.no_hourly:
        hac, hbad = read_hourly(days, latlng)
        out["hourly"] = {n: [round(100 * hbad[j, h] / hac[j, h], 2) if hac[j, h] else None for h in range(24)] for j, n in enumerate(names)}
        out["hourly_aircraft_hexes"] = {n: [int(hac[j, h]) for h in range(24)] for j, n in enumerate(names)}
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"wrote {args.out}: started {len(started)}, stopped {len(stopped)}, persistent {len(persistent)}")
    for n, a in areas.items():
        print(f"  {n}: median {a['median']}%; steps " + "; ".join(f"{s['start']}..{s['end']} {s['median']}%" for s in a["segments"]))


if __name__ == "__main__":
    main()
