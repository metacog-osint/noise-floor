#!/usr/bin/env python3
"""pc_archive.py: daily copy of the PC-only data into TIC's PRIVATE archive (metacog-osint/tic-archive).

Rule (Tom, 18 Nov 2026): no program loses data. Two kinds of Noisefloor data exist only on this PC's D: drive
(D: drops on sleep) and may not go public (watch configuration, private areas, licence terms):

  nisar       private/nisar: every detection, including LOW, widespread, ignored and private-area ones that
              the public gate (nisar/nisar_rfi/public.py) never publishes; per-site coverage; processed-granule
              records. sites.prune() drops detections older than keep_days (60) from about 20 Dec 2026, so a
              daily snapshot keeps every row before it is pruned. Left out: the */cache/*.npz granule tables
              (about 40 GB, re-derived from the NISAR archive).
  collectors  the collectors' raw replies and outputs: raw Bluesky, RSS and watch-poller replies, community and
              watch digests and alerts.jsonl, the NGA navigational-warnings archive, private AIS records and
              vessel tables, Sentinel receiver tables and private area products, the private watch config.
              Left out: raw ESA ISM (its own store, the nf-ism Worker's R2 bucket) and the downloaded Sentinel
              navigation products in data/sentinel_gnss/raw/<year>/ (Copernicus open data, re-fetchable).

Sizes measured 19 Nov 2026: nisar about 270 MB kept of 40.8 GB; collectors about 3.6 GB (AIS 1.4 GB, Sentinel
tables 2.1 GB, raw Bluesky 194 MB). First run uploads all of it; later runs upload what changed, about 100 MB a day.

Each lane is one snapshot a day (tools/tic_archive.py): only content new since the previous snapshot is uploaded,
and every snapshot can be restored. Uses this PC's gh login. Run last in collectors/run_daily.cmd, so nothing
waits on it; any failure exits 1 (the scheduled task's Last Run Result shows it) and writes
data/logs/ARCHIVE_FAILED.txt, removed again by the next good run.

    python tools/pc_archive.py              both lanes
    python tools/pc_archive.py --lane nisar --dry-run
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import tic_archive as ta  # noqa: E402

PROGRAM = "noisefloor"

# lane -> (sources [(name, path relative to ROOT)], exclude globs on the archived path)
LANES = {
    "nisar": ([("nisar", "private/nisar")],
              ["nisar/cache/*", "nisar/*/cache/*", "*.npz.tmp", "*.partial"]),
    "collectors": ([("raw-bluesky", "data/raw/bluesky"),
                    ("raw-feeds", "data/raw/feeds"),
                    ("raw-watch", "data/raw/watch"),
                    ("community", "data/community"),
                    ("watch", "data/watch"),
                    ("navwarn", "data/declared/navwarn"),
                    ("ais", "data/ais"),
                    ("vessels", "data/vessels"),
                    ("sentinel-gnss", "data/sentinel_gnss"),
                    ("sentinel-private", "private/sentinel"),
                    ("watch-config", "private/watch")],
                   ["*.tmp", "*.partial", "*.lock",
                    # Copernicus Sentinel navigation products as downloaded (12.8 GB on 19 Nov 2026), open data
                    # kept in the Copernicus archive; the derived tables and raw/index.jsonl are kept.
                    "sentinel-gnss/raw/20*"]),
}


def flag_path(root: Path) -> Path:
    return root / "data" / "logs" / "ARCHIVE_FAILED.txt"


def run(lanes, root: Path = ROOT, store=None, dry_run=False, now=None) -> int:
    store = store or ta.GhStore()
    problems = []
    if store.__class__ is ta.GhStore and not shutil.which("gh"):
        problems.append("the gh CLI is not on PATH")
        lanes = []
    for lane in lanes:
        sources, exclude = LANES[lane]
        present = [(n, root / p) for n, p in sources if (root / p).is_dir()]
        missing = [p for n, p in sources if not (root / p).is_dir()]
        if missing:
            # Archive what is there, then fail: a missing folder may mean the drive dropped or a lane stopped.
            problems.append(f"{lane}: missing folder(s) {', '.join(missing)}")
        if not present:
            continue
        try:
            ta.Archive(store, PROGRAM, lane).put(present, exclude=exclude, dry_run=dry_run, now=now)
        except (ta.ArchiveError, OSError) as e:
            problems.append(f"{lane}: {e}")
    flag = flag_path(root)
    if problems:
        for p in problems:
            ta.error(p)
        if not dry_run:
            flag.parent.mkdir(parents=True, exist_ok=True)
            stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
            flag.write_text(f"{stamp} private archive failed:\n" + "\n".join(problems) + "\n", encoding="utf-8")
        return 1
    if not dry_run and flag.exists():
        flag.unlink()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lane", choices=sorted(LANES), action="append")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    return run(a.lane or list(LANES), dry_run=a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
