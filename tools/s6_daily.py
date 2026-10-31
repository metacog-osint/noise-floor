#!/usr/bin/env python3
"""s6_daily.py: the newest complete Sentinel-6A day -> a small public map file (step P of docs/space-sensors-plan.md).

Runs on this PC (needs EARTHDATA_TOKEN for PO.DAAC and the Space-Track account for the spacecraft's orbit; never
printed). PO.DAAC posts Sentinel-6A's hourly receiver files about three days late, so a day counts as complete when
CMR lists at least MIN_FILES of them and the day is at least MIN_AGE_DAYS old. For each complete day not yet done
(looking back LOOKBACK days) it runs `s6_rfi.py fetch`, `index` and `grid` with the method frozen and validated in
docs/validation/space-receivers.md (S1C, -2 dB, 3,800 km, H3 res 2), writes data/s6rfi/daily/<day>.s6.json and uploads
it to this repo's release `s6-data`, which the site deploy reads (tools/site_layers.py).

The file holds every judged cell's score only where it reaches the frozen threshold T (the 95th percentile of
aircraft-clean cells on the tuning days), as [h3, score, bins], plus counts. Aggregates only: no receiver data.

  python tools/s6_daily.py [--day 2026-10-27] [--no-upload]
  python tools/s6_daily.py --resummarise [--no-upload]    # rewrite (and upload) every day already gridded
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
OUT = os.path.join(ROOT, "data", "s6rfi", "daily")
REPO = "metacog-osint/noise-floor"
TAG = "s6-data"
LOOKBACK, MIN_FILES, MIN_AGE_DAYS = 10, 13, 2
THRESHOLD = 0.2409            # frozen in docs/validation/space-receivers.md section 3 (T)
CREDIT = ["Contains modified Copernicus Sentinel data {year}",
          "Sentinel-6A GNSS-RO-POD tracking data, PO.DAAC (doi:10.5067/S6AGN-1ROPD)",
          "Orbital data: USSPACECOM (space-track.org)", "Broadcast navigation: IGS"]
LICENCE = ("Derived from Copernicus Sentinel-6A data (PO.DAAC: openly shared without restriction; Copernicus: free, "
           "full and open, with credit)")
NOTES = ("Daily maps of GPS interference heard by Sentinel-6A's own GNSS receiver, by region (H3 res 2), made by "
         "tools/s6_rfi.py and tools/s6_daily.py. Aggregates only. Method and validation: "
         "docs/validation/space-receivers.md. " + "; ".join(c.format(year="2026") for c in CREDIT) + ".")


def complete(day, today):
    import s6_rfi as S
    n = len(S.files(day))
    age = (today - datetime.fromisoformat(day).date()).days
    return n >= MIN_FILES and age >= MIN_AGE_DAYS, n


def summarise(day):
    import s6_rfi as S
    g = S.read_grid(day)
    if g is None:
        raise SystemExit(f"{day}: no grid")
    rows = sorted(g.values(), key=lambda r: -r["score"])
    raised = [r for r in rows if r["score"] >= THRESHOLD]
    meta = json.load(open(os.path.join(S.DAYS_DIR, f"{day}.json"), encoding="utf-8"))
    return {"day": day, "licence": LICENCE, "credit": [c.format(year=day[:4]) for c in CREDIT],
            "judged_cells": len(rows), "raised_cells": len(raised), "threshold": THRESHOLD, "res": 2,
            "radius_km": S.RADIUS_KM, "drop_db": S.DROP_DB, "epochs": meta.get("epochs"),
            "cells": [[r["h3"], round(float(r["score"]), 3), int(r["n_vis"])] for r in raised],
            "method": "tools/s6_rfi.py (index: tools/rx_rfi.py; map: cosmic2_rfi back-projection); "
                      "docs/validation/space-receivers.md"}


def gh(*args, check=True):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"gh {' '.join(args[:2])}: {r.stderr.strip()[:300]}")
    return r


def ensure_release():
    if gh("release", "view", TAG, "-R", REPO, check=False).returncode:
        gh("release", "create", TAG, "-R", REPO, "--title", "Sentinel-6A receiver daily maps", "--notes", NOTES,
           "--latest=false")


def write(day, no_upload):
    s = summarise(day)
    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, f"{day}.s6.json")
    tmp = out + ".part"                         # kept as <day>.s6.json only once uploaded: a failed upload retries
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, separators=(",", ":"))
    os.replace(tmp, out)
    print(f"{day}: {s['raised_cells']} of {s['judged_cells']} judged cells at or above {THRESHOLD}")
    if not no_upload:
        try:
            ensure_release()
            gh("release", "upload", TAG, "-R", REPO, "--clobber", out)
        except Exception:
            os.replace(out, tmp)
            raise
        print(f"{day}: uploaded to release {TAG}")
    return out


def run_day(day):
    import s6_rfi as S
    if S.read_grid(day) is not None:
        return True
    for cmd in ("fetch", "index", "grid"):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "s6_rfi.py"), cmd, day],
                           capture_output=True, text=True, timeout=7200)
        if r.returncode or "FAILED" in (r.stderr or ""):
            print(f"{day}: s6_rfi {cmd} failed: {(r.stderr or r.stdout).strip()[-400:]}")
            return False
    return True


def main(argv=None):
    import s6_rfi as S
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--day", help="this day (default: every complete day in the last LOOKBACK days not yet done)")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--resummarise", action="store_true")
    a = ap.parse_args(argv)
    print(f"=== s6_daily {datetime.now(timezone.utc):%Y-%m-%dT%H:%MZ}")
    if a.resummarise:
        days = sorted(f[:10] for f in os.listdir(S.GRID_DIR) if f.endswith(f".r2.k{int(S.RADIUS_KM)}.parquet"))
        for d in days:
            write(d, a.no_upload)
        return 0
    if not os.environ.get("EARTHDATA_TOKEN"):
        print("EARTHDATA_TOKEN is not set: skipped")
        return 0
    today = datetime.now(timezone.utc).date()
    days = [a.day] if a.day else [(today - timedelta(days=k)).isoformat() for k in range(LOOKBACK, 1, -1)]
    for day in days:
        if os.path.exists(os.path.join(OUT, f"{day}.s6.json")) and not a.day:
            continue
        if not a.day:
            ok, n = complete(day, today)
            if not ok:
                print(f"{day}: {n} files listed so far, not complete")
                continue
        if run_day(day):
            write(day, a.no_upload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
