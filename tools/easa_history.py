#!/usr/bin/env python3
"""easa_history.py: EASA's FIR tables from Internet Archive copies of its GNSS page, for the events register.

  python tools/easa_history.py [--since 2025-09-01] [--no-push]

EASA's page "GNSS outages and alterations" shows only its current tables of FIRs with GNSS interference (7 and 30 days,
with spoofing and reported columns; "src: ads-b data and reports"). tools/notice_capture.py keeps a copy each day from
26 Oct 2026. For the time before that, this reads the copies the Internet Archive holds (its CDX index, one copy per
distinct page), parses each with tools/board.py's easa_parse(), and writes notices/easa/wayback-<timestamp>.json in the
private archive clone (data/ism-archive), then commits and pushes. A copy already written is skipped; a copy without
the tables (before EASA added them, or a page that didn't render) is noted and skipped.

EASA allows reproduction with the source acknowledged; the copies stay in the private archive with the rest of the
notice history. tools/events.py reads them for rule D1 (load_easa_notices).
"""
import argparse
import gzip
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
CLONE = os.environ.get("NF_ISM_DIR") or os.path.join(ROOT, "data", "ism-archive")
PAGE = "https://www.easa.europa.eu/en/domains/air-operations/global-navigation-satellite-system-outages-and-alterations"
CDX = ("https://web.archive.org/cdx/search/cdx?url=easa.europa.eu/en/domains/air-operations/"
       "global-navigation-satellite-system-outages-and-alterations&output=json&fl=timestamp,digest"
       "&filter=statuscode:200&collapse=digest")
UA = {"User-Agent": "noise-floor easa history (github.com/metacog-osint/noise-floor)"}


def get(url, timeout=120):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                b = r.read()
            return gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b       # the archive returns some copies gzipped
        except Exception:
            if attempt == 2:
                raise
            time.sleep(10 * (attempt + 1))


def git(*args, check=True):
    r = subprocess.run(["git", "-C", CLONE, *args], capture_output=True, text=True, timeout=300)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args[:2])}: {(r.stderr or r.stdout).strip()[:300]}")
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", default="2025-09-01", help="skip copies older than this (YYYY-MM-DD)")
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args()
    import board
    if not os.path.isdir(os.path.join(CLONE, ".git")):
        sys.exit(f"no private archive clone at {CLONE}: run tools/events.py fetch first")
    sys.path.insert(0, os.path.join(ROOT, "collectors"))
    import ism_local
    if not ism_local.take_lock():
        sys.exit("another task holds the private clone; try again shortly")
    try:
        out = os.path.join(CLONE, "notices", "easa")
        os.makedirs(out, exist_ok=True)
        rows = json.loads(get(CDX))[1:]
        since = a.since.replace("-", "")
        wrote = 0
        for ts, _ in rows:
            if ts[:8] < since:
                continue
            path = os.path.join(out, f"wayback-{ts}.json")
            if os.path.exists(path):
                continue
            url = f"https://web.archive.org/web/{ts}/{PAGE}"
            try:
                d = board.easa_parse(get(f"https://web.archive.org/web/{ts}id_/{PAGE}").decode("utf-8", "replace"), url)
            except ValueError:
                print(f"{ts}: no FIR tables in this copy; skipped")
                continue
            d["fetched_utc"] = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime())
            d["archived_utc"] = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}T{ts[8:10]}:{ts[10:12]}Z"
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(d, f, indent=1, ensure_ascii=False)
            wrote += 1
            print(f"{ts}: " + "; ".join(f"{t['days']}-day table of {t['date']}, {len(t['firs'])} FIRs, "
                                        f"{sum(r['spoofing'] for r in t['firs'])} with spoofing" for t in d["tables"]))
            time.sleep(3)                                      # gentle on the archive
        if wrote:
            git("add", "notices")
            git("commit", "--quiet", "-m", f"notices: {wrote} EASA table copies from the Internet Archive (local)")
            if not a.no_push and git("push", "--quiet", check=False).returncode:
                print("push failed; the commit stays local and goes with the next push")
        print(f"{wrote} new copies written")
    finally:
        ism_local.drop_lock()


if __name__ == "__main__":
    main()
