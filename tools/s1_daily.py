#!/usr/bin/env python3
"""s1_daily.py: the newest complete Sentinel-1 day -> a public map file of C-band radar activity over the 28 days
ending that day (option S of docs/space-sensors-plan.md).

Runs on this PC from the 06:30 collectors task; no account (Microsoft Planetary Computer, anonymous). For each day at
least MIN_AGE_DAYS old that isn't done yet (looking back LOOKBACK days), it runs `s1_rfi_global.py day` (about 950 IW GRD
products and 3 minutes a day; a day where more than 5% of reads fail is not saved and is retried next time) and `week`
for the 28 days ending it (at least MIN_DAYS of them held). It writes data/s1rfi/global/daily/<day>.s1.json and uploads it
to this repo's release `s1-data`, which the site deploy reads (tools/site_layers.py).

What the file holds (docs/validation/s1-rfi.md sections 9-10):
  cells    H3 res-3 cells (about 110 km across) that Sentinel-1 passed over at least MIN_PASSES times in the window and
           whose share of passes with RFI in the satellite's own annotation is at least MIN_SHARE, as
           [cell, share, passes]
  busiest  up to six places, at least 800 km apart, where every or nearly every pass carried RFI
The measure is C-band (5.4 GHz) interference, mostly radars. It is not GPS interference, and it shows regions, not
transmitter sites: the location check against known sites failed (docs/validation/s1-rfi.md section 3). The cuts
(MIN_PASSES, MIN_SHARE) are display choices, not pre-registered.

  python tools/s1_daily.py [--day 2026-10-29] [--no-upload]
  python tools/s1_daily.py --resummarise [--no-upload]   # rewrite (and upload) every day with a 28-day window file
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import s1_rfi_global as G  # noqa: E402

OUT = os.path.join(G.OUT, "daily")
REPO = "metacog-osint/noise-floor"
TAG = "s1-data"
LOOKBACK, MIN_AGE_DAYS, MIN_PRODUCTS, WINDOW, MIN_DAYS, RES = 6, 2, 400, 28, 21, 3
MIN_PASSES, MIN_SHARE, BUSY_SHARE, BUSY_PASSES = 4, 0.25, 0.9, 8
CREDIT = "Contains modified Copernicus Sentinel data {year}"
LICENCE = ("Derived from Copernicus Sentinel-1 Level-1 GRD annotations (free for any use, including commercial, with "
           "attribution), read through Microsoft Planetary Computer. " + CREDIT)
NOTES = ("Daily maps, each covering 28 days, of C-band (5.4 GHz) interference reported in the Copernicus Sentinel-1 "
         "radar's own RFI annotation, made by tools/s1_rfi_global.py and tools/s1_daily.py: per H3 res-3 cell, the share "
         "of passes with RFI. Mostly radars; not GPS interference; regions, not sites. Aggregates only. "
         "Contains modified Copernicus Sentinel data 2026. Method: docs/validation/s1-rfi.md.")


def window_days(day):
    e = datetime.fromisoformat(day).date()
    return [(e - timedelta(days=k)).isoformat() for k in range(WINDOW - 1, -1, -1)]


def held(day):
    return [d for d in window_days(day) if os.path.exists(os.path.join(G.OUT, f"{d}.parquet"))]


def _describe(lat, lon):
    """Place wording from the NISAR lane's offline gazetteer ("36 km S of Kramatorsk (UA)"); None if unavailable."""
    try:
        sys.path.insert(0, os.path.join(ROOT, "nisar"))
        from nisar_rfi import places
        return places.describe(lat, lon)[0]
    except Exception:
        return None


def _apart(rows, km_apart, top):
    """The first `top` rows (lat, lon, ...) at least km_apart from each other, in the order given."""
    import math
    out = []
    for r in rows:
        if all(6371.0 * math.acos(min(1.0, math.sin(math.radians(r[0])) * math.sin(math.radians(o[0])) +
               math.cos(math.radians(r[0])) * math.cos(math.radians(o[0])) * math.cos(math.radians(r[1] - o[1]))))
               >= km_apart for o in out):
            out.append(r)
        if len(out) == top:
            break
    return out


def summarise(day, week_path=None):
    import pyarrow.parquet as pq
    p = week_path or os.path.join(G.OUT, "week", f"{day}.d{WINDOW}.r{RES}.parquet")
    t = pq.read_table(p).to_pydict()
    rows = [(c, la, lo, int(n), float(s)) for c, la, lo, n, s in
            zip(t["cell"], t["lat"], t["lon"], t["passes"], t["share"]) if n >= MIN_PASSES]
    shown = sorted([r for r in rows if r[4] >= MIN_SHARE], key=lambda r: (-r[4], -r[3]))
    busy = [r for r in shown if r[4] >= BUSY_SHARE and r[3] >= BUSY_PASSES]
    top = _apart([(la, lo, s, n) for c, la, lo, n, s in busy], 800.0, 6)
    days = held(day)
    year = day[:4]
    return {"day": day, "window": [window_days(day)[0], day], "days_held": len(days), "res": RES,
            "licence": LICENCE.format(year=year), "credit": [CREDIT.format(year=year)], "band_ghz": 5.405,
            "covered": len(rows), "shown": len(shown),
            "cells": [[c, round(s, 2), n] for c, la, lo, n, s in shown],
            "busiest": [{"lat": round(la, 2), "lon": round(lo, 2), "share": round(s, 2), "passes": n,
                         "where": _describe(la, lo)} for la, lo, s, n in top],
            "cuts": {"min_passes": MIN_PASSES, "min_share": MIN_SHARE, "busy_share": BUSY_SHARE,
                     "busy_passes": BUSY_PASSES},
            "method": "tools/s1_rfi_global.py (Sentinel-1 RFI annotation, flag rule s1_rfi.DETECT, per pass and cell); "
                      "docs/validation/s1-rfi.md"}


def window_file(day):
    """The 28-day res-3 window file for `day` (s1_rfi_global.week writes <day>.r3.parquet; kept under a name that
    says its length)."""
    src = G.week(day, WINDOW, RES)
    dst = os.path.join(G.OUT, "week", f"{day}.d{WINDOW}.r{RES}.parquet")
    os.replace(src, dst)
    return dst


def gh(*args, check=True):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"gh {' '.join(args[:2])}: {r.stderr.strip()[:300]}")
    return r


def write(day, no_upload):
    s = summarise(day)
    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, f"{day}.s1.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(s, f, separators=(",", ":"))
    print(f"{day}: {s['shown']} of {s['covered']} covered cells shown ({s['days_held']} of {WINDOW} days)")
    if not no_upload:
        if gh("release", "view", TAG, "-R", REPO, check=False).returncode:
            gh("release", "create", TAG, "-R", REPO, "--title", "Sentinel-1 C-band radar activity maps", "--notes",
               NOTES, "--latest=false")
        gh("release", "upload", TAG, "-R", REPO, "--clobber", out)
        print(f"{day}: uploaded to release {TAG}")
    return out


def listed(day):
    import s1_rfi as S
    return len([p for p in S.PC().search([-180, -90, 180, 90], day, day) if p["mode"] == "IW"])


def run_day(day):
    try:
        G.day(day)
    except RuntimeError as e:            # too many failed reads: no day file, so the next run tries again
        print(e)
        return False
    if len(held(day)) < MIN_DAYS:
        print(f"{day}: only {len(held(day))} of {WINDOW} days held, skipped")
        return False
    window_file(day)
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--day")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--resummarise", action="store_true")
    a = ap.parse_args(argv)
    print(f"=== s1_daily {datetime.now(timezone.utc):%Y-%m-%dT%H:%MZ}")
    if a.resummarise:
        wk = os.path.join(G.OUT, "week")
        for f in sorted(os.listdir(wk)):
            if f.endswith(f".d{WINDOW}.r{RES}.parquet"):
                write(f[:10], a.no_upload)
        return 0
    today = datetime.now(timezone.utc).date()
    days = [a.day] if a.day else [(today - timedelta(days=k)).isoformat()
                                  for k in range(LOOKBACK, MIN_AGE_DAYS - 1, -1)]
    for day in days:
        if os.path.exists(os.path.join(OUT, f"{day}.s1.json")) and not a.day:
            continue
        if not a.day and not os.path.exists(os.path.join(G.OUT, f"{day}.parquet")):
            n = listed(day)
            if n < MIN_PRODUCTS:
                print(f"{day}: {n} products listed so far, not complete")
                continue
        if run_day(day):
            write(day, a.no_upload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
