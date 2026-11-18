#!/usr/bin/env python3
"""milair_job.py: the daily military air job -> <day>.milair.json on the release milair-data-YYYY.

  python tools/milair_job.py [DAYS ...] [--force] [--no-upload --out DIR]

DAYS are YYYY-MM-DD or START:END. With none, the job looks at the last three complete UTC days and makes any whose
file is not yet in the release (adsb.lol posts a day's archive about 03:25 UTC the next morning).

Each day streams the adsb.lol archive parts (adsblol/globe_history_YYYY, tag vYYYY.MM.DD-planes-readsb-prod-0,
about 3.7 GB) straight from their public download links into tools/milair.py's scan: nothing is written to disk but
the day file (aggregates per region and role, no aircraft identifiers). --no-upload --out DIR writes the files
locally instead (used to build the first reading on the PC). Method: docs/validation/milair.md.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import milair  # noqa: E402

REPO = os.environ.get("GITHUB_REPOSITORY", "metacog-osint/noise-floor")
UA = "noise-floor milair"
NOTES = ("Military aircraft seen on ADS-B and MLAT per region and role, one file per UTC day (tools/milair.py, "
         "docs/validation/milair.md). Every count is a lower bound. Licence: ODbL 1.0, derived from adsb.lol and "
         "plane-alert-db. " + milair.ATTRIBUTION)


def log(msg):
    print(f"{datetime.now(timezone.utc):%H:%M:%SZ} {msg}", flush=True)


def days_from(args, today, back=3):
    out = []
    for a in args or []:
        if ":" in a:
            s, e = (date.fromisoformat(x) for x in a.split(":"))
            out += [(s + timedelta(days=k)).isoformat() for k in range((e - s).days + 1)]
        else:
            out.append(date.fromisoformat(a).isoformat())
    return out or [(today - timedelta(days=k)).isoformat() for k in range(back, 0, -1)]


def data_tag(day):
    return f"milair-data-{day[:4]}"


def upstream(day):
    return f"adsblol/globe_history_{day[:4]}", f"v{day.replace('-', '.')}-planes-readsb-prod-0"


def gh(*args, check=True):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {(r.stderr or r.stdout).strip()[:300]}")
    return r


def release_assets(repo, tag):
    """{name: size}, or None when there is no such release. Network errors are retried three times."""
    for attempt in range(4):
        r = gh("release", "view", tag, "-R", repo, "--json", "assets", check=False)
        if not r.returncode:
            return {a["name"]: a["size"] for a in json.loads(r.stdout)["assets"]}
        if "not found" in (r.stderr or "").lower():
            return None
        if attempt == 3:
            raise RuntimeError(f"gh release view {tag} -R {repo}: {r.stderr.strip()[:300]}")
        time.sleep(15 * (attempt + 1))


def archive_parts(day):
    """Download URLs of the day's archive parts in order, or [] when adsb.lol has not posted it."""
    repo, tag = upstream(day)
    have = release_assets(repo, tag) or {}
    names = sorted(n for n in have if n.startswith(tag + ".tar"))
    return [f"https://github.com/{repo}/releases/download/{tag}/{n}" for n in names]


def upload(day, path):
    tag = data_tag(day)
    if gh("release", "view", tag, "-R", REPO, "--json", "tagName", check=False).returncode:
        gh("release", "create", tag, "-R", REPO, "--title", f"Military air {day[:4]}", "--notes", NOTES,
           "--latest=false")
    gh("release", "upload", tag, "-R", REPO, "--clobber", path)


def run(days, force=False, no_upload=False, out=None):
    out = out or os.path.join(milair.ROOT, "data", "milair")
    os.makedirs(out, exist_ok=True)
    made, skipped, missing, failed = [], [], [], []
    published = {}
    for day in days:
        name = f"{day}.milair.json"
        if no_upload:
            if os.path.exists(os.path.join(out, name)) and not force:
                skipped.append(day); continue
        else:
            tag = data_tag(day)
            if tag not in published:
                published[tag] = release_assets(REPO, tag) or {}
            if name in published[tag] and not force:
                skipped.append(day); continue
        try:
            parts = archive_parts(day)
            if not parts:
                log(f"{day}: adsb.lol archive not posted"); missing.append(day); continue
            log(f"{day}: {len(parts)} archive parts")
            doc = milair.run_day(day, [milair.url_opener(u) for u in parts],
                                 {"archive": upstream(day)[1], "parts": len(parts)})
        except Exception as e:          # a dropped download: log it, carry on, fail the run at the end
            log(f"{day}: failed: {type(e).__name__}: {str(e)[:200]}"); failed.append(day); continue
        path = os.path.join(out, name)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(doc, f, separators=(",", ":"))
        c = doc["counts"]
        log(f"{day}: {c['military']} military aircraft of {c['traces']} traces, {doc['source']['seconds']} s")
        if not no_upload:
            upload(day, path)
        made.append(day)
    log(f"made {len(made)}, skipped {len(skipped)} already there, not posted {len(missing)}, failed {len(failed)}"
        + (f" ({', '.join(failed)})" if failed else ""))
    return made, skipped, missing, failed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("days", nargs="*")
    ap.add_argument("--force", action="store_true", help="remake days already made")
    ap.add_argument("--no-upload", action="store_true", help="write the files locally only (needs --out)")
    ap.add_argument("--out", help="folder for the day files (default data/milair)")
    a = ap.parse_args(argv)
    if a.no_upload and not a.out:
        ap.error("--no-upload needs --out")
    failed = run(days_from(a.days, datetime.now(timezone.utc).date()), a.force, a.no_upload, a.out)[3]
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
