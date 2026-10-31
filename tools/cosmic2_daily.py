#!/usr/bin/env python3
"""cosmic2_daily.py: the newest complete COSMIC-2 day -> a small public map file (step C4 of docs/space-sensors-plan.md).

Runs on this PC from the 06:30 collectors task; no account is needed. UCAR posts each day's near-real-time `podTc2`
archive (about 450-650 MB) early the next day, so a day counts as complete once the archive answers and the day is at
least MIN_AGE_DAYS old. For each complete day not yet done (looking back LOOKBACK days) it runs `cosmic2_rfi.py fetch`
and `grid` with the method frozen and validated in docs/validation/space-receivers.md (UCAR's RFI index, 10 s bins,
2,500 km with the fore/aft split, H3 res 2), writes data/cosmic2/daily/<day>.cosmic2.json and uploads it to this repo's
release `cosmic2-data`, which the site deploy reads (tools/site_layers.py).

The file holds every cell whose score reaches the frozen threshold T (the 95th percentile of aircraft-clean cells on
the tuning days) as [h3, score, bins], the strongest regions by name, counts, and the satellites that delivered data.

  python tools/cosmic2_daily.py [--day 2026-10-30] [--no-upload]
  python tools/cosmic2_daily.py --resummarise [--no-upload]   # rewrite (and upload) every day already gridded
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
OUT = os.path.join(ROOT, "data", "cosmic2", "daily")
REPO = "metacog-osint/noise-floor"
TAG = "cosmic2-data"
LOOKBACK, MIN_AGE_DAYS = 7, 1
RADIUS_KM, HALVES = 2500.0, True             # frozen in docs/validation/space-receivers.md section 4
THRESHOLD = 0.23                             # T: clean cells' 95th percentile on the six tuning days
CREDIT = ["COSMIC-2 data: UCAR COSMIC Program (CDAAC), near-real-time level 1b podTc2 (CC BY 4.0)"]
LICENCE = "Derived from UCAR CDAAC COSMIC-2 data (UCAR data terms: CC BY 4.0)"
NOTES = ("Daily maps of GPS interference heard by the COSMIC-2 satellites' navigation antennas (UCAR's per-antenna RFI "
         "index), by region (H3 res 2), made by tools/cosmic2_rfi.py and tools/cosmic2_daily.py. Aggregates only. "
         "Method and validation: docs/validation/space-receivers.md. " + CREDIT[0] + ".")


def complete(day, today):
    import cosmic2_rfi as C2
    if (today - datetime.fromisoformat(day).date()).days < MIN_AGE_DAYS:
        return False
    try:
        req = urllib.request.Request(C2.url_for(day), method="HEAD", headers={"User-Agent": C2.UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status == 200
    except OSError:
        return False


def summarise(day):
    import cosmic2_rfi as C2
    from s6_daily import _apart, _describe
    g = C2.read_grid(day, 2, RADIUS_KM, HALVES)
    if g is None:
        raise SystemExit(f"{day}: no grid")
    rows = sorted(g.values(), key=lambda r: -r["score"])
    raised = [r for r in rows if r["score"] >= THRESHOLD]
    peaks = _apart([(r["lat"], r["lon"], r["score"]) for r in raised], 1500.0, 3)
    meta = json.load(open(os.path.join(C2.DAYS_DIR, f"{day}.pointing.json"), encoding="utf-8"))
    sats = sorted({k.split(".")[0] for k in meta.get("pointing", {})})
    return {"day": day, "licence": LICENCE, "credit": CREDIT, "judged_cells": len(rows), "raised_cells": len(raised),
            "threshold": THRESHOLD, "res": 2, "radius_km": RADIUS_KM, "fore_aft": HALVES,
            "satellites": ["C2E" + s for s in sats],
            "cells": [[r["h3"], round(float(r["score"]), 3), int(r["n_vis"])] for r in raised],
            "peaks": [{"lat": round(float(la), 2), "lon": round(float(lo), 2), "score": round(float(sc), 3),
                       "where": _describe(float(la), float(lo))} for la, lo, sc in peaks],
            "method": "tools/cosmic2_rfi.py (UCAR RFI index; back-projection with the fore/aft split); "
                      "docs/validation/space-receivers.md"}


def gh(*args, check=True):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"gh {' '.join(args[:2])}: {r.stderr.strip()[:300]}")
    return r


def write(day, no_upload):
    s = summarise(day)
    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, f"{day}.cosmic2.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(s, f, separators=(",", ":"), ensure_ascii=False)
    print(f"{day}: {s['raised_cells']} of {s['judged_cells']} judged cells at or above {THRESHOLD} "
          f"({len(s['satellites'])} satellites)")
    if not no_upload:
        if gh("release", "view", TAG, "-R", REPO, check=False).returncode:
            gh("release", "create", TAG, "-R", REPO, "--title", "COSMIC-2 receiver daily maps", "--notes", NOTES,
               "--latest=false")
        gh("release", "upload", TAG, "-R", REPO, "--clobber", out)
        print(f"{day}: uploaded to release {TAG}")
    return out


def run_day(day):
    import cosmic2_rfi as C2
    if C2.read_grid(day, 2, RADIUS_KM, HALVES) is not None:
        return True
    if C2.fetch(day) is None:
        return False
    C2.grid(day, 2, RADIUS_KM, HALVES)
    return True


def main(argv=None):
    import cosmic2_rfi as C2
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--day")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--resummarise", action="store_true")
    a = ap.parse_args(argv)
    print(f"=== cosmic2_daily {datetime.now(timezone.utc):%Y-%m-%dT%H:%MZ}")
    if a.resummarise:
        suffix = f".r2.k{int(RADIUS_KM)}{'h' if HALVES else ''}.parquet"
        for f in sorted(os.listdir(C2.GRID_DIR)):
            if f.endswith(suffix):
                write(f[:10], a.no_upload)
        return 0
    today = datetime.now(timezone.utc).date()
    days = [a.day] if a.day else [(today - timedelta(days=k)).isoformat() for k in range(LOOKBACK, 0, -1)]
    for day in days:
        if os.path.exists(os.path.join(OUT, f"{day}.cosmic2.json")) and not a.day:
            continue
        if not a.day and not complete(day, today):
            print(f"{day}: not posted yet")
            continue
        try:
            if run_day(day):
                write(day, a.no_upload)
        except Exception as e:                    # one bad day must not stop the others
            print(f"{day}: FAILED {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
