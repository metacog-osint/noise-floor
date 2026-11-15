#!/usr/bin/env python3
"""ground_roti_job.py: the daily ground ROTI job -> <day>.ground-roti.json on the release swx-data-YYYY-MM.

ROTI, a measured TEC fluctuation index at fixed stations (tools/ground_roti.py; method and validation in
docs/validation/ground-roti.md). Runs on GitHub (.github/workflows/ground-roti.yml), so the day is published even when
this PC is off. BKG lists each IGS station's day-D file between about 00:05 and 13:00 UTC on D+1 (listing times for
the stations used, 16 Oct-14 Nov 2026: most by 09:10 UTC; on 14 Nov one batch came at 12:45 UTC). The day file is due
by 14:00 UTC on D+1.

For each day (default: yesterday, UTC):
  1. Gate. If the day file is already in its release: skip it when it lists no missing station, or when the day is
     more than --refresh-days old; otherwise look at BKG again and, if a station it lists as missing is now posted,
     remake the whole day and replace the file. So extra starts of the workflow cost about a minute.
  2. Not in the release yet. For the newest day before --publish-hour UTC, publish only once every station is
     posted; otherwise stop quietly (the next start looks again). From --publish-hour, wait up to --wait-minutes for
     missing stations, then publish what is posted. Older days are published with what is posted.
  3. Nothing posted at all (no station, or no broadcast navigation file): stop quietly, or fail from
     --deadline-hour UTC on the newest day, so GitHub mails the owner.

  python tools/ground_roti_job.py [DAY | START:END ...] [--force] [--no-upload] [--wait-minutes 30]
                                  [--publish-hour 9] [--deadline-hour 13] [--refresh-days 2]
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cosmic2_job as J  # noqa: E402  (release helpers shared with the COSMIC-2 job)
import ground_roti as R  # noqa: E402

POLL_S = 600
log, summary = J.log, J.summary


def published_doc(tag, name):
    """The published day file (dict), or None if it is not in the release."""
    if not J.published(tag, name, R.UA["User-Agent"]):
        return None
    req = urllib.request.Request(J.asset_url(tag, name), headers=R.UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def decide(doc, have, n_stations, newest, hour, a, day_age):
    """What to do with a day: 'skip', 'publish', 'refresh', 'wait' (wait for missing stations, then publish),
    'waiting' (stop quietly) or 'late' (fail). doc: the published file or None; have: stations posted now."""
    if doc is not None and not a.force:
        missing = set(doc.get("missing") or [])
        if not missing or day_age > a.refresh_days:
            return "skip"
        return "refresh" if missing & set(have) else "skip"
    if not have:
        return "late" if newest and hour >= a.deadline_hour else "waiting"
    if len(have) == n_stations or not newest:
        return "publish"
    if hour < a.publish_hour:
        return "waiting"
    return "wait"


def run_day(day, a, now=None, sleep=time.sleep):
    """Returns 'skipped', 'waiting', 'published', 'refreshed' or raises."""
    now = now or datetime.now(timezone.utc)
    stations = list(R.STATIONS)
    name = f"{day}.{R.FEED}.json"
    tag = J.s4_tag(day)
    doc = None if a.force else published_doc(tag, name)
    day_age = (now.date() - date.fromisoformat(day)).days - 1     # 0 on D+1
    newest = day_age <= 0
    have, nav, _ = R.available(day, stations)
    if not nav:
        have = {}
    what = decide(doc, have, len(stations), newest, datetime.now(timezone.utc).hour, a, day_age)
    if what == "skip":
        log(f"{day}: {name} is in {tag}" + (f" (missing {', '.join(doc['missing'])}, none posted since)"
                                            if doc.get("missing") else "") + "; nothing to do")
        return "skipped"
    if what in ("waiting", "late"):
        msg = f"{day}: nothing posted at BKG yet ({'no broadcast navigation file' if not nav else 'no station'})"
        if what == "late":
            raise RuntimeError(msg + f" and it is past {a.deadline_hour:02d}:00 UTC")
        log(msg if not have else f"{day}: {len(have)}/{len(stations)} stations posted; before "
                                 f"{a.publish_hour:02d}:00 UTC the day is published only when all are in")
        summary(f"- {day}: waiting for BKG ({len(have)}/{len(stations)} stations posted)")
        return "waiting"
    if what == "wait":
        deadline = time.time() + 60 * a.wait_minutes
        while len(have) < len(stations) and time.time() + POLL_S <= deadline:
            log(f"{day}: {len(have)}/{len(stations)} stations posted; looking again in {POLL_S // 60} min")
            sleep(POLL_S)
            have, nav, _ = R.available(day, stations)
    doc_new, path = R.make_day(day, stations, log=log)
    c = doc_new["counts"]
    if not c["stations"]:
        raise RuntimeError(f"{day}: no station could be read ({doc_new['failed']})")
    log(f"{day}: {c['stations']} stations, {c['station_hours']} station-hours ({c['with_p95']} with p95); "
        f"missing {doc_new['missing'] or 'none'}; failed {list(doc_new['failed']) or 'none'}")
    if not a.no_upload:
        J.upload(tag, path, J.S4_TITLE.format(month=day[:7]), J.S4_NOTES.format(month=day[:7]))
        log(f"{day}: uploaded {name} to {tag}")
    done = "refreshed" if what == "refresh" else "published"
    summary(f"- {day}: ROTI file `{name}` -> `{tag}` ({done}): {c['stations']} stations, {c['station_hours']} "
            f"station-hours; missing: {', '.join(doc_new['missing']) or 'none'}; problems: "
            f"{'; '.join(doc_new['problems']) or 'none'}")
    return done


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("days", nargs="*")
    ap.add_argument("--force", action="store_true", help="remake days already in the release")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--wait-minutes", type=float, default=0)
    ap.add_argument("--publish-hour", type=int, default=9,
                    help="UTC hour from which the newest day is published even if stations are missing")
    ap.add_argument("--deadline-hour", type=int, default=13, help="UTC hour from which nothing posted is an error")
    ap.add_argument("--refresh-days", type=int, default=2,
                    help="days after D+1 during which a file with missing stations is remade when they turn up")
    a = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    days = J.days_from(a.days, now.date())
    log(f"ground_roti_job: {len(days)} day(s): {days[0]}{'' if len(days) == 1 else ' .. ' + days[-1]}")
    failed = []
    for day in days:
        try:
            run_day(day, a, now)
        except Exception as e:                      # one bad day must not stop the others
            log(f"{day}: FAILED {e}")
            summary(f"- {day}: FAILED {str(e)[:200]}")
            failed.append(day)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
