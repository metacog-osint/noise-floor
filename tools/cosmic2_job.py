#!/usr/bin/env python3
"""cosmic2_job.py: one pass over UCAR's COSMIC-2 podTc2 day archive -> the limb S4 day file and the interference day file.

Runs on GitHub (.github/workflows/cosmic2.yml), so the day is published even when this PC is off. UCAR posts day D at
about 04:35 UTC on D+1 (measured 17 Oct-14 Nov 2026); Noisefloor publishes D's limb S4 file by 14:00 UTC on D+1, so the
board and COP have a same-morning picture.

For each day (default: yesterday, UTC):
  1. Gate: a day whose limb S4 file is already in its release is skipped (unless --force), so extra starts of the
     workflow cost about a minute and the day is never made twice.
  2. Wait for UCAR: if the archive is not posted yet, look again every 5 minutes for up to --wait-minutes, then stop
     quietly (the next start tries again), or fail at or after --deadline-hour UTC, so GitHub mails the owner.
  3. Stream the archive once (about 450-650 MB; nothing from it is kept): tools/cosmic2_rfi.py's reduction for the
     interference layer and tools/cosmic2_s4.py's limb samples in the same pass.
  4. Write <day>.cosmic2-limb-s4.json and upload it to the release swx-data-YYYY-MM (created if missing).
  5. Unless --s4-only: grid the interference day as tools/cosmic2_daily.py does (method frozen in
     docs/validation/space-receivers.md) and upload <day>.cosmic2.json to cosmic2-data, but only if that release does
     not have the day yet (this PC's own run, tools/cosmic2_daily.py, still makes it while the GitHub path is proven).
     If it is there already, the two are compared and the result printed.

  python tools/cosmic2_job.py [DAY | START:END ...] [--force] [--s4-only] [--no-upload] [--wait-minutes 45]
                              [--deadline-hour 13]
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
REPO = "metacog-osint/noise-floor"
S4_TAG = "swx-data-{month}"
S4_TITLE = "Space weather day files {month}"
S4_NOTES = ("Noisefloor's space weather day files for {month}, one per UTC day, published by 14:00 UTC the next day. "
            "<day>.cosmic2-limb-s4.json: limb S4 measured along radio-occultation paths, which reads higher than a "
            "ground receiver's S4 (COSMIC-2 navigation-antenna links whose ray passes 150-500 km above the ground), per "
            "H3 res-1 cell and UTC hour. Made by tools/cosmic2_s4.py and tools/cosmic2_job.py; method and validation "
            "in docs/validation/cosmic2-limb-s4.md. COSMIC-2 data: UCAR COSMIC Program (CDAAC), CC BY 4.0. "
            "These files are CC BY 4.0.")
POLL_S = 300


def log(msg):
    print(f"{datetime.now(timezone.utc):%H:%M:%SZ} {msg}", flush=True)


def summary(line):
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def days_from(args, today):
    """['2026-11-01:2026-11-03', '2026-11-09'] -> the days in order; [] -> [yesterday]."""
    out = []
    for a in args or []:
        if ":" in a:
            s, e = (date.fromisoformat(x) for x in a.split(":"))
            out += [(s + timedelta(days=k)).isoformat() for k in range((e - s).days + 1)]
        else:
            out.append(date.fromisoformat(a).isoformat())
    return out or [(today - timedelta(days=1)).isoformat()]


def s4_tag(day):
    return S4_TAG.format(month=day[:7])


def asset_url(tag, name):
    return f"https://github.com/{REPO}/releases/download/{tag}/{name}"


def http_status(url, ua, method="HEAD"):
    try:
        req = urllib.request.Request(url, method=method, headers={"User-Agent": ua})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, {}
    except OSError:
        return None, {}


def published(tag, name, ua):
    """True if the release asset answers (a public download URL; no token needed)."""
    st, _ = http_status(asset_url(tag, name), ua)
    return st == 200


def gh(*args, check=True):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"gh {' '.join(args[:2])}: {r.stderr.strip()[:300]}")
    return r


def upload(tag, path, title, notes):
    if gh("release", "view", tag, "-R", REPO, "--json", "tagName", check=False).returncode:
        gh("release", "create", tag, "-R", REPO, "--title", title, "--notes", notes, "--latest=false")
    gh("release", "upload", tag, "-R", REPO, "--clobber", path)


def wait_for_ucar(url, ua, wait_minutes, sleep=time.sleep):
    """(True, headers) once the archive answers, or (False, {}) after wait_minutes."""
    deadline = time.time() + 60 * wait_minutes
    while True:
        st, hd = http_status(url, ua)
        if st == 200:
            return True, hd
        if time.time() + POLL_S > deadline:
            return False, {}
        log(f"UCAR archive not posted yet (HTTP {st}); looking again in {POLL_S // 60} min")
        sleep(POLL_S)


def compare_rfi(ours, theirs):
    """Compare two <day>.cosmic2.json files on what the map reads (cells and peaks; place wording may differ)."""
    a = {c[0]: c[1:] for c in ours.get("cells", [])}
    b = {c[0]: c[1:] for c in theirs.get("cells", [])}
    same_cells = set(a) == set(b)
    max_diff = max((abs(a[k][0] - b[k][0]) for k in set(a) & set(b)), default=0.0)
    return {"same_cells": same_cells, "only_ours": len(set(a) - set(b)), "only_theirs": len(set(b) - set(a)),
            "max_score_diff": round(max_diff, 4),
            "match": same_cells and max_diff <= 0.001 and ours.get("judged_cells") == theirs.get("judged_cells")}


def interference(day, no_upload, ua):
    """Grid the interference day from the table just written and publish it unless cosmic2-data has it already."""
    import cosmic2_daily as D
    import cosmic2_rfi as C2
    C2.grid(day, 2, D.RADIUS_KM, D.HALVES)
    path = D.write(day, no_upload=True)
    name = os.path.basename(path)
    if published(D.TAG, name, ua):
        try:
            with urllib.request.urlopen(urllib.request.Request(asset_url(D.TAG, name),
                                                               headers={"User-Agent": ua}), timeout=60) as r:
                theirs = json.load(r)
            cmp = compare_rfi(json.load(open(path, encoding="utf-8")), theirs)
        except (OSError, ValueError) as e:
            cmp = {"match": None, "error": str(e)[:200]}
        log(f"{day}: {name} already in {D.TAG}; not replaced. Compared with it: {json.dumps(cmp)}")
        summary(f"- {day}: interference file already in `{D.TAG}` (kept). Same as this run: {cmp.get('match')}")
        return "kept", cmp
    if no_upload:
        return "written", None
    upload(D.TAG, path, "COSMIC-2 receiver daily maps", D.NOTES)
    log(f"{day}: uploaded {name} to {D.TAG}")
    summary(f"- {day}: interference file uploaded to `{D.TAG}`")
    return "uploaded", None


def run_day(day, a, now=None):
    """Returns 'skipped', 'waiting', 'done' or raises."""
    import cosmic2_rfi as C2
    import cosmic2_s4 as S
    now = now or datetime.now(timezone.utc)
    name = f"{day}.{S.FEED}.json"
    tag = s4_tag(day)
    if not a.force and published(tag, name, C2.UA):
        log(f"{day}: {name} is already in {tag}; nothing to do")
        return "skipped"
    url = C2.url_for(day)
    newest = date.fromisoformat(day) == now.date() - timedelta(1)
    ok, hd = wait_for_ucar(url, C2.UA, a.wait_minutes if newest else 0)     # an older day is there or it is not
    if not ok:
        late = newest and datetime.now(timezone.utc).hour >= a.deadline_hour
        msg = f"{day}: UCAR has not posted {os.path.basename(url)} yet"
        if late:
            raise RuntimeError(msg + f" and it is past {a.deadline_hour:02d}:00 UTC")
        log(msg + "; the next start will look again")
        summary(f"- {day}: UCAR archive not posted yet")
        return "waiting"
    limb = S.Limb()
    t0 = time.time()
    C2.fetch(day, force=True, on_link=limb.add, on_retry=limb.reset)
    source = {"url": url, "bytes": int(hd.get("Content-Length") or 0) or None,
              "posted": hd.get("Last-Modified"), "read_seconds": round(time.time() - t0)}
    doc = S.build(day, limb, source)
    path = S.write(doc)
    c = doc["counts"]
    log(f"{day}: limb S4: {c['links']} links, {c['values']} 10 s values, {c['cell_hours']} cell-hours "
        f"({c['with_p95']} with p95), {c['hours_with_data']} hours with data, {len(doc['problems'])} problem(s)")
    if not a.no_upload:
        upload(tag, path, S4_TITLE.format(month=day[:7]), S4_NOTES.format(month=day[:7]))
        log(f"{day}: uploaded {name} to {tag}")
    summary(f"- {day}: limb S4 file `{name}` -> `{tag}`: {c['cell_hours']} cell-hours, "
            f"{c['hours_with_data']}/24 hours with data; problems: {'; '.join(doc['problems']) or 'none'}")
    if not a.s4_only:
        try:
            interference(day, a.no_upload, C2.UA)
        except Exception as e:                      # the limb S4 file is out; the interference file is a by-product
            log(f"{day}: interference file FAILED: {e}")
            summary(f"- {day}: interference file failed: {str(e)[:200]}")
    return "done"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("days", nargs="*")
    ap.add_argument("--force", action="store_true", help="redo days already in the release")
    ap.add_argument("--s4-only", action="store_true", help="skip the interference day file")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--wait-minutes", type=float, default=0)
    ap.add_argument("--deadline-hour", type=int, default=13, help="UTC hour from which a missing archive is an error")
    a = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    days = days_from(a.days, now.date())
    log(f"cosmic2_job: {len(days)} day(s): {days[0]}{'' if len(days) == 1 else ' .. ' + days[-1]}")
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
