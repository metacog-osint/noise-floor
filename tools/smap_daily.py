#!/usr/bin/env python3
"""smap_daily.py: the newest complete SMAP day -> a public map file for the 7 days ending that day (step R3 of
docs/space-sensors-plan.md).

Runs on this PC (needs EARTHDATA_TOKEN; never printed). NSIDC posts SMAP L1C half-orbits (SPL1CTB v006) within a day or
two, so a day counts as complete when CMR lists at least MIN_ORBITS half-orbits and the day is at least MIN_AGE_DAYS
old. For each complete day not yet done (looking back LOOKBACK days) it runs `smap_rfi.py fetch` for the day and
`share` for the 7 days ending it (at least MIN_DAYS of them held), writes data/smap/daily/<day>.smap.json and uploads it
to this repo's release `smap-data`, which the site deploy reads (tools/site_layers.py).

What the file holds (validated in docs/validation/smap-rfi.md: the long-range radar check held, AUC 0.988):
  sources  SMAP cells whose looks were flagged at least half the time and at least 0.5 more often than the cells
           100-300 km around them, where those cells were flagged 10% of the time or less (single emitters standing
           out of a quiet background, as in the validated case; radars, for example), as
           [H3 res-4 cell of the SMAP cell's centre, share, contrast, looks]
  busy     H3 res-3 regions where the median SMAP cell was flagged at least half the time (the band is crowded; single
           emitters can't be told apart there), as [cell, median share, SMAP cells]
The cuts (0.5, 0.5, 0.10, 0.5) are display choices, not pre-registered.

  python tools/smap_daily.py [--day 2026-10-28] [--no-upload]
  python tools/smap_daily.py --resummarise [--no-upload]   # rewrite (and upload) every day with a 7-day share file
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
OUT = os.path.join(ROOT, "data", "smap", "daily")
REPO = "metacog-osint/noise-floor"
TAG = "smap-data"
LOOKBACK, MIN_ORBITS, MIN_AGE_DAYS, WINDOW, MIN_DAYS = 10, 25, 2, 7, 5
SOURCE_SHARE, SOURCE_CONTRAST, QUIET_RING, BUSY_SHARE, MIN_LOOKS = 0.5, 0.5, 0.10, 0.5, 8
CITE = ("SMAP L1C Radiometer Half-Orbit 36 km EASE-Grid Brightness Temperatures, Version 6. NASA NSIDC DAAC. "
        "doi:10.5067/DV7IX2DQ681Y")
LICENCE = "Derived from NASA SMAP L1C (NSIDC DAAC), NASA open data; cite " + CITE
NOTES = ("Daily maps, each covering 7 days, of interference flagged in 1400-1427 MHz by NASA SMAP's radiometer, made by "
         "tools/smap_rfi.py and tools/smap_daily.py: single emitters standing out of a quiet background (sources) and "
         "crowded regions (busy). Aggregates only. Source: " + CITE + ". Method and validation: "
         "docs/validation/smap-rfi.md.")


def window_days(day):
    e = datetime.fromisoformat(day).date()
    return [(e - timedelta(days=k)).isoformat() for k in range(WINDOW - 1, -1, -1)]


def complete(day, today):
    import smap_rfi as M
    n = len(M.granules(day))
    return n >= MIN_ORBITS and (today - datetime.fromisoformat(day).date()).days >= MIN_AGE_DAYS, n


def summarise(day):
    import h3
    import numpy as np
    import pyarrow.parquet as pq
    import smap_rfi as M
    held = [d for d in window_days(day) if os.path.exists(os.path.join(M.DAYS_DIR, f"{d}.parquet"))]
    t = pq.read_table(os.path.join(M.SHARE_DIR, f"{day}.d{WINDOW}.parquet")).to_pydict()
    sources, busy = {}, {}
    for la, lo, n, sh, co, rg in zip(t["lat"], t["lon"], t["looks"], t["share"], t["contrast"], t["ring"]):
        if n < MIN_LOOKS:
            continue
        busy.setdefault(h3.latlng_to_cell(float(la), float(lo), 3), []).append(float(sh))
        if (sh >= SOURCE_SHARE and co is not None and np.isfinite(co) and co >= SOURCE_CONTRAST
                and rg is not None and rg <= QUIET_RING):
            c = h3.latlng_to_cell(float(la), float(lo), 4)
            if c not in sources or sh > sources[c][0]:
                sources[c] = (float(sh), float(co), int(n))
    busy_rows = [[c, round(float(np.median(v)), 2), len(v)] for c, v in busy.items() if np.median(v) >= BUSY_SHARE]
    return {"day": day, "window": [window_days(day)[0], day], "days_held": len(held), "licence": LICENCE,
            "credit": [CITE], "band_mhz": [1400, 1427],
            "sources": [[c, round(s, 2), round(co, 2), n] for c, (s, co, n) in sorted(sources.items(), key=lambda kv: -kv[1][1])],
            "busy": sorted(busy_rows, key=lambda r: -r[1]),
            "cuts": {"source_share": SOURCE_SHARE, "source_contrast": SOURCE_CONTRAST, "quiet_ring": QUIET_RING, "busy_share": BUSY_SHARE,
                     "min_looks": MIN_LOOKS},
            "method": "tools/smap_rfi.py (L1C RFI-detection bit; 7-day share; contrast against the 100-300 km ring); "
                      "docs/validation/smap-rfi.md"}


def gh(*args, check=True):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"gh {' '.join(args[:2])}: {r.stderr.strip()[:300]}")
    return r


def write(day, no_upload):
    s = summarise(day)
    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, f"{day}.smap.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(s, f, separators=(",", ":"))
    print(f"{day}: {len(s['sources'])} stand-out cells, {len(s['busy'])} busy regions ({s['days_held']} of {WINDOW} days)")
    if not no_upload:
        if gh("release", "view", TAG, "-R", REPO, check=False).returncode:
            gh("release", "create", TAG, "-R", REPO, "--title", "SMAP 1400-1427 MHz interference maps", "--notes", NOTES,
               "--latest=false")
        gh("release", "upload", TAG, "-R", REPO, "--clobber", out)
        print(f"{day}: uploaded to release {TAG}")
    return out


def run_day(day):
    import smap_rfi as M
    M.fetch(day)
    held = [d for d in window_days(day) if os.path.exists(os.path.join(M.DAYS_DIR, f"{d}.parquet"))]
    if len(held) < MIN_DAYS:
        for d in window_days(day):                     # fill the window (each day about 45 s and 160 MB)
            M.fetch(d)
        held = [d for d in window_days(day) if os.path.exists(os.path.join(M.DAYS_DIR, f"{d}.parquet"))]
    if len(held) < MIN_DAYS:
        print(f"{day}: only {len(held)} of {WINDOW} days held, skipped")
        return False
    M.share(day, WINDOW)
    return True


def main(argv=None):
    import smap_rfi as M
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--day")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--resummarise", action="store_true")
    a = ap.parse_args(argv)
    print(f"=== smap_daily {datetime.now(timezone.utc):%Y-%m-%dT%H:%MZ}")
    if a.resummarise:
        for f in sorted(os.listdir(M.SHARE_DIR)):
            if f.endswith(f".d{WINDOW}.parquet"):
                write(f[:10], a.no_upload)
        return 0
    if not os.environ.get("EARTHDATA_TOKEN"):
        print("EARTHDATA_TOKEN is not set: skipped")
        return 0
    today = datetime.now(timezone.utc).date()
    days = [a.day] if a.day else [(today - timedelta(days=k)).isoformat() for k in range(LOOKBACK, 1, -1)]
    for day in days:
        if os.path.exists(os.path.join(OUT, f"{day}.smap.json")) and not a.day:
            continue
        if not a.day:
            ok, n = complete(day, today)
            if not ok:
                print(f"{day}: {n} half-orbits listed so far, not complete")
                continue
        if run_day(day):
            write(day, a.no_upload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
