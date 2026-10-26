#!/usr/bin/env python3
"""cygnss_daily.py: the newest complete CYGNSS day -> a small public summary for the home board.

Runs on this PC from collectors/run_daily.cmd (the daily collectors task), because CYGNSS needs an Earthdata Login token
(EARTHDATA_TOKEN, a user environment variable that Tom set; never printed). CYGNSS L1 files for a day arrive over several
days, so a day counts as complete when NASA CMR lists files for at least MIN_SC spacecraft, or MIN_SC_LATE once it is
LATE_DAYS old. For the newest complete day not yet summarised (looking back up to LOOKBACK days), it runs
`cygnss_rfi.py fetch` and `grid` (the validated method, unchanged), writes data/cygnss/daily/<day>.cygnss.json and
uploads it to this repo's release `cygnss-data`, which the site deploy reads (tools/board.py).

Summary: judged cells (H3 res 3, 20+ DDMs), cells with a median noise-floor excess of 1 dB or more, and the strongest
raised areas (one per H3 res-2 region, by median excess). Aggregates only; NASA CYGNSS L1 V3.2 is NASA open data.

  python tools/cygnss_daily.py [--day 2026-10-20] [--no-upload]
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
GRID = os.path.join(ROOT, "data", "cygnss", "grid")
OUT = os.path.join(ROOT, "data", "cygnss", "daily")
REPO = "metacog-osint/noise-floor"
TAG = "cygnss-data"
LOOKBACK, MIN_SC, MIN_SC_LATE, LATE_DAYS = 10, 7, 5, 6
MIN_DDM, RAISED_DB, TOP = 20, 1.0, 10
NOTES = ("Daily summaries of GNSS L1 interference seen from orbit by NASA CYGNSS (noise floor of the delay-Doppler maps), "
         "made by tools/cygnss_rfi.py and tools/cygnss_daily.py. Aggregates only. Source: NASA CYGNSS Level 1 Science Data "
         "Record V3.2 (PO.DAAC, doi:10.5067/CYGNS-L1X32), NASA open data. Method and validation: docs/validation/cygnss.md.")


def complete(day, today):
    import cygnss_rfi as C
    n = len({ur.split(".")[0] for ur, _ in C.granules(day)})       # one file per spacecraft: cyg0N...
    age = (today - datetime.fromisoformat(day).date()).days
    return n >= MIN_SC or (age >= LATE_DAYS and n >= MIN_SC_LATE), n


def summarise(day):
    import h3
    import pyarrow.parquet as pq
    t = pq.read_table(os.path.join(GRID, f"{day}.r3.parquet"), columns=["h3", "lat", "lon", "n", "med_db"]).to_pylist()
    judged = [r for r in t if (r["n"] or 0) >= MIN_DDM and r["med_db"] is not None]
    raised = [r for r in judged if r["med_db"] >= RAISED_DB]
    best = {}
    for r in raised:
        p = h3.cell_to_parent(r["h3"], 2)
        if p not in best or r["med_db"] > best[p]["med_db"]:
            best[p] = r
    top = sorted(best.values(), key=lambda r: -r["med_db"])[:TOP]
    return {"day": day, "licence": "Derived from NASA CYGNSS L1 V3.2 (NASA open data)", "cells": len(judged),
            "raised_cells": len(raised), "raised_db": RAISED_DB,
            "top": [{"lat": round(r["lat"], 2), "lon": round(r["lon"], 2), "med_db": round(r["med_db"], 2), "n": r["n"]}
                    for r in top],
            "method": "tools/cygnss_rfi.py grid (H3 res 3, 20+ DDMs per judged cell); docs/validation/cygnss.md"}


def gh(*args, check=True):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"gh {' '.join(args[:2])}: {r.stderr.strip()[:300]}")
    return r


def upload(path):
    if gh("release", "view", TAG, "-R", REPO, check=False).returncode:
        gh("release", "create", TAG, "-R", REPO, "--title", "CYGNSS daily summaries", "--notes", NOTES, "--latest=false")
    gh("release", "upload", TAG, "-R", REPO, "--clobber", path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--day", help="summarise this day (default: the newest complete day not yet done)")
    ap.add_argument("--no-upload", action="store_true")
    a = ap.parse_args()
    print(f"=== cygnss_daily {datetime.now(timezone.utc):%Y-%m-%dT%H:%MZ}")
    if not os.environ.get("EARTHDATA_TOKEN") and not a.day:
        print("EARTHDATA_TOKEN is not set: skipped")
        return 0
    today = datetime.now(timezone.utc).date()
    os.makedirs(OUT, exist_ok=True)
    days = [a.day] if a.day else [(today - timedelta(days=k)).isoformat() for k in range(2, LOOKBACK + 1)]
    for day in days:
        out = os.path.join(OUT, f"{day}.cygnss.json")
        if os.path.exists(out) and not a.day:
            print(f"{day}: done already; nothing newer is complete")
            return 0
        if not a.day:
            ok, n = complete(day, today)
            if not ok:
                print(f"{day}: {n} spacecraft files so far, not complete")
                continue
        if not os.path.exists(os.path.join(GRID, f"{day}.r3.parquet")):
            for cmd in ("fetch", "grid"):
                r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "cygnss_rfi.py"), cmd, day],
                                   capture_output=True, text=True, timeout=7200)
                if r.returncode:
                    print(f"{day}: cygnss_rfi {cmd} failed: {(r.stderr or r.stdout).strip()[-400:]}")
                    return 1
        s = summarise(day)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(s, f, separators=(",", ":"))
        print(f"{day}: {s['raised_cells']} of {s['cells']} judged cells raised {RAISED_DB:g} dB or more")
        if not a.no_upload:
            upload(out)
            print(f"{day}: uploaded to release {TAG}")
        return 0
    print("no complete day in the last", LOOKBACK, "days")
    return 0


if __name__ == "__main__":
    sys.exit(main())
