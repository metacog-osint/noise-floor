#!/usr/bin/env python3
"""leads_year.py: test the Phase 1 leads and validation windows against the full published history.

Reads each day's per-hex daily and hourly tables from this repo's data releases (cached in data/pnt/year/, gitignored)
and reports, for named boxes:
  daily   the share of aircraft-hexes worse than 93 m (live) per day, with rank and percentile of chosen days
  hourly  the share by UTC hour, to test hour-of-day patterns (e.g. a 02Z spike)
  window  the share inside given UTC windows against the same hours on other days (announced tests)

  python tools/leads_year.py fetch                    # download/refresh the cache (plain release links)
  python tools/leads_year.py baltic|malay|north02|kurils|jammertest
"""
import json, os, statistics, sys, urllib.request
from datetime import date, timedelta

import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "pnt", "year")
REPO = os.environ.get("GITHUB_REPOSITORY", "metacog-osint/noise-floor")
FIRST = date(2025, 10, 1)

BOXES = {   # (lat0, lat1, lon0, lon1)
    "south_baltic": (54.8, 57.0, 15.0, 19.0),        # open sea between Bornholm, Gotland and the Polish coast (lead 1)
    "malay": (1.0, 7.0, 99.0, 104.5),                # Malay Peninsula and Strait of Malacca (latched-onset lead)
    "north_europe": (50.0, 60.0, -5.0, 25.0),        # the 02Z lead
    "kurils": (43.0, 50.0, 145.0, 156.0),            # Kuril Islands, Fukuoka/Anchorage FIR edge (FAA report window)
    "andoya": (68.6, 69.9, 14.0, 17.8),              # Jammertest test areas on Andoya
}


def days():
    d, out = FIRST, []
    while d < date.today():
        out.append(d.isoformat()); d += timedelta(days=1)
    return out


def fetch():
    os.makedirs(CACHE, exist_ok=True)
    got = missing = 0
    for day in days():
        for kind in ("parquet", "hourly.parquet"):
            name = f"{day}.{kind}"
            dest = os.path.join(CACHE, name)
            if os.path.exists(dest):
                continue
            url = f"https://github.com/{REPO}/releases/download/pnt-data-{day[:7]}/{name}"
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "noise-floor"}), timeout=60) as r:
                    data = r.read()
                open(dest, "wb").write(data); got += 1
            except Exception:
                missing += 1
    print(json.dumps({"downloaded": got, "not_published": missing, "cache": CACHE}))


def inbox(lat, lon, b):
    return b[0] <= lat <= b[1] and b[2] <= lon <= b[3]


_LL = {}


def hourly_rows(day, box):
    """[(hour, aircraft, bad_live)] for hexes in the box, from the hourly table (lat/lon via the daily table)."""
    dp, hp = os.path.join(CACHE, f"{day}.parquet"), os.path.join(CACHE, f"{day}.hourly.parquet")
    if not (os.path.exists(dp) and os.path.exists(hp)):
        return None
    for r in pq.read_table(dp, columns=["h3", "lat", "lon"]).to_pylist():
        _LL[r["h3"]] = (r["lat"], r["lon"])
    out = []
    for r in pq.read_table(hp, columns=["h3", "hour", "aircraft", "bad_nacp_live"]).to_pylist():
        ll = _LL.get(r["h3"])
        if ll and inbox(ll[0], ll[1], box):
            out.append((r["hour"], r["aircraft"], r["bad_nacp_live"]))
    return out


def daily_share(day, box):
    p = os.path.join(CACHE, f"{day}.parquet")
    if not os.path.exists(p):
        return None
    ac = bad = 0
    for r in pq.read_table(p, columns=["lat", "lon", "aircraft", "bad_nacp_live"]).to_pylist():
        if inbox(r["lat"], r["lon"], box):
            ac += r["aircraft"]; bad += r["bad_nacp_live"]
    return (100 * bad / ac, ac) if ac else None


def rank_report(box_name, focus):
    box = BOXES[box_name]
    series = {d: v for d in days() if (v := daily_share(d, box))}
    vals = sorted(v[0] for v in series.values())
    print(f"{box_name} {box}: {len(series)} days; median {statistics.median(vals):.1f}%, p90 {vals[int(0.9 * (len(vals) - 1))]:.1f}%, max {vals[-1]:.1f}%")
    top = sorted(series.items(), key=lambda kv: -kv[1][0])[:10]
    print("  top 10 days:", ", ".join(f"{d} {v[0]:.1f}%" for d, v in top))
    for d in focus:
        if d in series:
            v = series[d][0]
            print(f"  {d}: {v:.1f}% ({series[d][1]} aircraft-hexes); rank {sorted(vals, reverse=True).index(v) + 1} of {len(vals)}; "
                  f"percentile {100 * sum(1 for x in vals if x <= v) / len(vals):.0f}")
    return series


def by_hour(box_name, day_list=None):
    box = BOXES[box_name]
    hours = {h: [0, 0] for h in range(24)}
    peak_counts, n = {h: 0 for h in range(24)}, 0
    for d in day_list or days():
        rows = hourly_rows(d, box)
        if not rows:
            continue
        per = {h: [0, 0] for h in range(24)}
        for h, a, b in rows:
            per[h][0] += a; per[h][1] += b; hours[h][0] += a; hours[h][1] += b
        shares = {h: 100 * b / a for h, (a, b) in per.items() if a >= 200}
        if shares:
            peak_counts[max(shares, key=shares.get)] += 1; n += 1
    print(f"{box_name}: {n} days with hourly data")
    print("  hour  share  aircraft-hexes  days it was the worst hour")
    for h in range(24):
        a, b = hours[h]
        print(f"  {h:02d}Z  {100 * b / a if a else 0:5.2f}%  {a:9d}  {peak_counts[h]:4d}")


def window_report(box_name, windows):
    """windows: [(day, h0, h1)] UTC hours inclusive; compare with the same hours on the other days."""
    box = BOXES[box_name]
    targets = {d for d, _, _ in windows}
    for d, h0, h1 in windows:
        rows = hourly_rows(d, box)
        if rows is None:
            print(f"  {d}: not published yet"); continue
        a = sum(x[1] for x in rows if h0 <= x[0] <= h1); b = sum(x[2] for x in rows if h0 <= x[0] <= h1)
        others = []
        for o in days():
            if o in targets:
                continue
            r = hourly_rows(o, box)
            if r:
                oa = sum(x[1] for x in r if h0 <= x[0] <= h1); ob = sum(x[2] for x in r if h0 <= x[0] <= h1)
                if oa:
                    others.append(100 * ob / oa)
        med = statistics.median(others) if others else float("nan")
        p95 = sorted(others)[int(0.95 * (len(others) - 1))] if others else float("nan")
        print(f"  {d} {h0:02d}-{h1:02d}Z: {100 * b / a if a else float('nan'):.1f}% of {a} aircraft-hexes; "
              f"other days same hours: median {med:.1f}%, p95 {p95:.1f}% (n={len(others)})")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "fetch":
        fetch()
    elif cmd == "baltic":
        rank_report("south_baltic", ["2025-10-23", "2025-10-22", "2025-10-24"])
    elif cmd == "malay":
        rank_report("malay", [])
    elif cmd == "north02":
        by_hour("north_europe")
    elif cmd == "kurils":
        s = rank_report("kurils", [])
        win = [(d, v[0]) for d, v in sorted(s.items()) if "2026-07-15" <= d <= "2026-08-10"]
        print("  15 Jul - 10 Aug 2026:", ", ".join(f"{d[5:]} {v:.1f}" for d, v in win))
    elif cmd == "jammertest":
        # 50 W tests from the NPRA transmission plan, local times (CEST, UTC+2) taken as given: hours in UTC below
        window_report("andoya", [("2026-09-14", 12, 13), ("2026-09-15", 7, 7), ("2026-09-15", 12, 14), ("2026-09-18", 7, 7)])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
