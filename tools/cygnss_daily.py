#!/usr/bin/env python3
"""cygnss_daily.py: the newest complete CYGNSS day -> a small public summary for the home board.

Runs on this PC from collectors/run_daily.cmd (the daily collectors task), because CYGNSS needs an Earthdata Login token
(EARTHDATA_TOKEN, a user environment variable that Tom set; never printed). CYGNSS L1 files for a day arrive over several
days, so a day counts as complete when NASA CMR lists files for at least MIN_SC spacecraft, or MIN_SC_LATE once it is
LATE_DAYS old. For each complete day not yet summarised (looking back up to LOOKBACK days, at most MAX_DAYS_PER_RUN a run), it runs
`cygnss_rfi.py fetch` and `grid` (the validated method, unchanged), writes data/cygnss/daily/<day>.cygnss.json and
uploads it to this repo's release `cygnss-data`, which the site deploy reads (tools/board.py).

Summary: judged cells (H3 res 3, 20+ DDMs), cells with a median noise-floor excess of 1 dB or more, the strongest
raised areas (one per H3 res-2 region, by median excess), and for the map layer every raised cell as
[h3, median dB, DDMs] (`cells`). Aggregates only; NASA CYGNSS L1 V3.2 is NASA open data.

  python tools/cygnss_daily.py --resummarise [--no-upload]      # rewrite (and upload) every day already gridded

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
MAX_DAYS_PER_RUN = 3                      # each day can take an hour or more; the rest wait for the next run
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
    return {"day": day, "licence": "Derived from NASA CYGNSS L1 V3.2 (NASA open data)", "judged_cells": len(judged),
            "raised_cells": len(raised), "raised_db": RAISED_DB,
            "top": [{"lat": round(r["lat"], 2), "lon": round(r["lon"], 2), "med_db": round(r["med_db"], 2), "n": r["n"]}
                    for r in top],
            "cells": [[r["h3"], round(r["med_db"], 1), r["n"]] for r in sorted(raised, key=lambda r: -r["med_db"])],
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


def resummarise(no_upload):
    """Every day with a grid -> a fresh summary; uploaded together (one gh call per 50 files) unless no_upload."""
    import glob
    os.makedirs(OUT, exist_ok=True)
    paths = []
    for g in sorted(glob.glob(os.path.join(GRID, "*.r3.parquet"))):
        day = os.path.basename(g)[:10]
        p = os.path.join(OUT, f"{day}.cygnss.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(summarise(day), f, separators=(",", ":"))
        paths.append(p)
    print(f"{len(paths)} days summarised")
    if not no_upload and paths:
        if gh("release", "view", TAG, "-R", REPO, check=False).returncode:
            gh("release", "create", TAG, "-R", REPO, "--title", "CYGNSS daily summaries", "--notes", NOTES, "--latest=false")
        for k in range(0, len(paths), 50):
            gh("release", "upload", TAG, "-R", REPO, "--clobber", *paths[k:k + 50])
            print(f"uploaded {min(k + 50, len(paths))} of {len(paths)}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--day", help="summarise this day (default: every complete day not yet done)")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--resummarise", action="store_true", help="rewrite the summary of every gridded day (adds map cells)")
    a = ap.parse_args()
    if a.resummarise:
        return resummarise(a.no_upload)
    print(f"=== cygnss_daily {datetime.now(timezone.utc):%Y-%m-%dT%H:%MZ}")
    if not os.environ.get("EARTHDATA_TOKEN") and not a.day:
        print("EARTHDATA_TOKEN is not set: skipped")
        return 0
    today = datetime.now(timezone.utc).date()
    os.makedirs(OUT, exist_ok=True)
    if a.day:
        return process_day(a.day, a.no_upload)
    days = pending_days(today)
    if not days:
        print("no complete undone day in the last", LOOKBACK, "days")
        return 0
    for day in days[:MAX_DAYS_PER_RUN]:
        rc = process_day(day, a.no_upload)
        if rc:
            return rc
    if len(days) > MAX_DAYS_PER_RUN:
        print(f"{len(days) - MAX_DAYS_PER_RUN} more complete days wait for the next run")
    return 0


def pending_days(today, exists=os.path.exists, is_complete=None):
    """Every complete day in LOOKBACK with no summary, newest first. A finished day never ends the search: stopping
    there is how CYGNSS lost a day whenever two days became complete between runs (database review, 23 Nov 2026)."""
    is_complete = is_complete or complete
    out = []
    for k in range(2, LOOKBACK + 1):
        day = (today - timedelta(days=k)).isoformat()
        if exists(os.path.join(OUT, f"{day}.cygnss.json")):
            continue
        ok, n = is_complete(day, today)
        if ok:
            out.append(day)
        else:
            print(f"{day}: {n} spacecraft files so far, not complete")
    return out


def process_day(day, no_upload):
    """Fetch, grid, summarise and upload one day. Returns 0, or 1 if the fetch or grid failed."""
    out = os.path.join(OUT, f"{day}.cygnss.json")
    if not os.path.exists(os.path.join(GRID, f"{day}.r3.parquet")):
        for cmd in ("fetch", "grid"):
            r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "cygnss_rfi.py"), cmd, day],
                               capture_output=True, text=True, timeout=7200)
            if r.returncode:
                print(f"{day}: cygnss_rfi {cmd} failed: {(r.stderr or r.stdout).strip()[-400:]}")
                return 1
    s = summarise(day)
    tmp = out + ".part"                       # kept as <day>.cygnss.json only once uploaded: a failed upload retries
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, separators=(",", ":"))
    print(f"{day}: {s['raised_cells']} of {s['judged_cells']} judged cells raised {RAISED_DB:g} dB or more")
    if not no_upload:
        final = os.path.join(os.path.dirname(tmp), f"{day}.cygnss.json")
        os.replace(tmp, final)
        try:
            upload(final)
        except Exception:
            os.replace(final, tmp)
            raise
        print(f"{day}: uploaded to release {TAG}")
    else:
        os.replace(tmp, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
