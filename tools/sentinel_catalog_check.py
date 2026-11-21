#!/usr/bin/env python3
"""sentinel_catalog_check.py: once a month, check that the Sentinel navigation files we hold are still in Copernicus.

The downloaded AUX_GNSSRD files (data/sentinel_gnss/raw/<year>/) stay out of the private archive because Copernicus
holds them. Copernicus publishes no retention period for them and has removed superseded baselines of other products,
so this check tests that assumption (Tom, 21 Nov 2026). It reads raw/index.jsonl, lists each unit's products from the
public catalogue (no account) and sorts every held catalogue id:

  present    in the catalogue and online
  offline    in the catalogue, not immediately downloadable
  replaced   id gone, another product covers the same unit and validity period (a reprocessing)
  gone       id gone, nothing covers that period

An id missing from the listing is looked up on its own before it counts as gone. Writes
data/sentinel_gnss/catalog_check/YYYY-MM.json only after a complete check, so a failed run tries again the next day.
Any offline, replaced or gone file writes data/logs/SENTINEL_CATALOG_ALERT.txt; a clean check removes it.

Run from collectors/run_daily.cmd; it does nothing once the month's report exists.

    python tools/sentinel_catalog_check.py [--force] [--dry-run] [--root PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
HEADERS = {"User-Agent": "noisefloor-catalog-check/1.0"}
PAGE = 1000
MAX_PAGES = 30
SCHEMA = "noisefloor-sentinel-catalog-check/1"


class CheckError(RuntimeError):
    pass


def http_get(url: str):
    """(status, parsed JSON or None). 404 is an answer; anything else that fails is retried, then raises."""
    err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=90) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return 404, None
            err = f"HTTP {e.code}"
        except (OSError, ValueError) as e:
            err = type(e).__name__
        time.sleep(3 + attempt * 5)
    raise CheckError(f"catalogue request failed: {err}")


def held_files(index: Path) -> dict:
    """name -> catalogue id; the newest row wins when a file was fetched again."""
    held = {}
    for line in index.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("catalogue_id"):
                held[row["name"]] = row["catalogue_id"]
    return held


def unit_of(name: str) -> str:
    return name[:3]


def validity(name: str) -> str:
    return name.rsplit("_V", 1)[-1]


def period_start(name: str) -> datetime:
    return datetime.strptime(validity(name)[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)


def list_unit(unit: str, since: datetime, get) -> list[dict]:
    flt = (f"startswith(Name,'{unit}_OPER_AUX_GNSSRD') and "
           f"ContentDate/Start ge {since.strftime('%Y-%m-%dT%H:%M:%S.000Z')}")
    url = BASE + "?" + urllib.parse.urlencode({"$filter": flt, "$orderby": "ContentDate/Start asc", "$top": str(PAGE)})
    rows = []
    for _ in range(MAX_PAGES):
        status, doc = get(url)
        if status != 200 or not isinstance(doc, dict) or "value" not in doc:
            raise CheckError(f"{unit}: unexpected catalogue reply ({status})")
        rows += doc["value"]
        url = doc.get("@odata.nextLink")
        if not url:
            return rows
    raise CheckError(f"{unit}: listing did not end within {MAX_PAGES} pages")


def stem(name: str) -> str:
    return name[:-4] if name.upper().endswith(".TGZ") else name


def classify(held: dict, get, pause: float = 0.2) -> dict:
    if not held:
        raise CheckError("the index holds no catalogue ids")
    since = min(period_start(n) for n in held) - timedelta(days=2)
    by_id, periods = {}, set()
    for unit in sorted({unit_of(n) for n in held}):
        for row in list_unit(unit, since, get):
            by_id[row["Id"]] = row
            periods.add((unit, validity(stem(row["Name"]))))
    out = {"present": [], "offline": [], "replaced": [], "gone": []}
    for name, cid in sorted(held.items()):
        row = by_id.get(cid)
        if row is None:
            status, row = get(f"{BASE}({urllib.parse.quote(cid)})")
            if pause:
                time.sleep(pause)
            if status == 404:
                out["replaced" if (unit_of(name), validity(name)) in periods else "gone"].append(name)
                continue
            if status != 200 or not isinstance(row, dict):
                raise CheckError(f"unexpected reply ({status}) for a held id")
        out["present" if row.get("Online") else "offline"].append(name)
    return out


def run(root: Path = ROOT, get=http_get, now: datetime | None = None, force=False, dry_run=False) -> int:
    now = now or datetime.now(timezone.utc)
    index = root / "data" / "sentinel_gnss" / "raw" / "index.jsonl"
    report = root / "data" / "sentinel_gnss" / "catalog_check" / f"{now:%Y-%m}.json"
    flag = root / "data" / "logs" / "SENTINEL_CATALOG_ALERT.txt"
    if report.exists() and not force:
        return 0
    try:
        res = classify(held_files(index), get)
    except (CheckError, OSError, ValueError, KeyError) as e:
        print(f"sentinel catalog check: incomplete, will retry: {e}", flush=True)
        return 1
    counts = {k: len(v) for k, v in res.items()}
    print(f"sentinel catalog check {now:%Y-%m-%d}: {sum(counts.values())} held, {counts}", flush=True)
    if dry_run:
        return 0
    report.parent.mkdir(parents=True, exist_ok=True)
    doc = {"schema": SCHEMA, "checked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "held": sum(counts.values()),
           "counts": counts, "offline": res["offline"], "replaced": res["replaced"], "gone": res["gone"]}
    tmp = report.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    tmp.replace(report)
    if counts["offline"] or counts["replaced"] or counts["gone"]:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(f"{doc['checked_at']} held Sentinel files no longer plainly available: offline "
                        f"{counts['offline']}, replaced {counts['replaced']}, gone {counts['gone']}. "
                        f"Names in {report.relative_to(root).as_posix()}. Decide on an off-drive copy.\n",
                        encoding="utf-8")
    elif flag.exists():
        flag.unlink()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true", help="check even if this month's report exists")
    ap.add_argument("--dry-run", action="store_true", help="print the counts, write nothing")
    ap.add_argument("--root", type=Path, default=ROOT)
    a = ap.parse_args(argv)
    return run(a.root, force=a.force or a.dry_run, dry_run=a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
