#!/usr/bin/env python3
"""ops_tally.py: two running checks in one command each.

  python tools/ops_tally.py cosmic2 [--log data/logs/cosmic2_daily.log] [--since 2026-11-16]
      Each day this PC's COSMIC-2 run found GitHub's file already published and compared it ("Compared with it:
      {...}" in the log): match true/false per day, and the tally. A clean week of match: true is the case for
      retiring the PC run.

  python tools/ops_tally.py landing [--since 2026-11-16] [--until 2026-11-23]
      When each adsb.lol day's <day>.map.json (the daily job's done marker) reached its pnt-data-YYYY-MM release:
      the upload time (UTC) and hours after the day ended, with the median and latest. Reads the public GitHub API
      anonymously (60 requests an hour; one or two per month of days).
"""
import argparse
import json
import os
import re
import statistics
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "metacog-osint/noise-floor"
LOG = os.path.join(ROOT, "data", "logs", "cosmic2_daily.log")
COMPARED = re.compile(r"^(\d{4}-\d\d-\d\d): .*Compared with it: (\{.*\})\s*$")


def compared(lines, since=None):
    """[(day, result dict)] from the log's "Compared with it" lines, the last line per day winning, oldest first."""
    out = {}
    for line in lines:
        m = COMPARED.match(line.strip())
        if m and (since is None or m.group(1) >= since):
            try:
                out[m.group(1)] = json.loads(m.group(2))
            except ValueError:
                out[m.group(1)] = {"match": None, "error": "unreadable"}
    return sorted(out.items())


def cmd_cosmic2(a):
    with open(a.log, encoding="utf-8", errors="replace") as f:
        rows = compared(f, a.since)
    for day, r in rows:
        extra = {k: v for k, v in r.items() if k != "match"}
        print(f"{day}  match {r.get('match')}  {json.dumps(extra)}")
    n = sum(1 for _, r in rows if r.get("match") is True)
    print(f"{n} of {len(rows)} compared days match" + ("" if rows else " (no comparison lines yet)"))
    return 0 if n == len(rows) else 1


def api(path):
    req = urllib.request.Request(f"https://api.github.com/{path}",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "noisefloor-ops-tally"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def map_assets(month):
    """{day: uploaded datetime} for <day>.map.json in release pnt-data-<month>; {} if there is no such release."""
    try:
        rel = api(f"repos/{REPO}/releases/tags/pnt-data-{month}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        raise
    out, page = {}, 1
    while True:
        assets = api(f"repos/{REPO}/releases/{rel['id']}/assets?per_page=100&page={page}")
        for x in assets:
            m = re.fullmatch(r"(\d{4}-\d\d-\d\d)\.map\.json", x["name"])
            if m:
                out[m.group(1)] = datetime.fromisoformat(x["created_at"].replace("Z", "+00:00"))
        if len(assets) < 100:
            return out
        page += 1


def landing_rows(uploaded, since, until):
    """[(day, uploaded, hours after the day ended)] for days since..until (strings, inclusive)."""
    rows = []
    for day, t in sorted(uploaded.items()):
        if since <= day <= until:
            end = datetime.combine(date.fromisoformat(day) + timedelta(days=1), datetime.min.time(), timezone.utc)
            rows.append((day, t, (t - end).total_seconds() / 3600))
    return rows


def cmd_landing(a):
    until = a.until or (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    months = sorted({a.since[:7], until[:7]})
    uploaded = {}
    for m in months:
        uploaded.update(map_assets(m))
    rows = landing_rows(uploaded, a.since, until)
    for day, t, h in rows:
        print(f"{day}  landed {t:%Y-%m-%d %H:%MZ}  {h:5.1f} h after the day ended")
    want = [(date.fromisoformat(a.since) + timedelta(days=k)).isoformat()
            for k in range((date.fromisoformat(until) - date.fromisoformat(a.since)).days + 1)]
    missing = [d for d in want if d not in uploaded]
    if rows:
        hs = [h for _, _, h in rows]
        print(f"{len(rows)} day(s): median {statistics.median(hs):.1f} h, latest {max(hs):.1f} h after the day ended")
    if missing:
        print(f"no map.json yet: {', '.join(missing)}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cosmic2")
    c.add_argument("--log", default=LOG)
    c.add_argument("--since")
    g = sub.add_parser("landing")
    g.add_argument("--since", required=True)
    g.add_argument("--until")
    a = ap.parse_args(argv)
    return cmd_cosmic2(a) if a.cmd == "cosmic2" else cmd_landing(a)


if __name__ == "__main__":
    sys.exit(main())
