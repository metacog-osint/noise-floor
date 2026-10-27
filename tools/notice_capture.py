#!/usr/bin/env python3
"""notice_capture.py: keep a daily history of two official sources that show only what is current.

  python tools/notice_capture.py [--no-push]

1. EASA's tables of FIRs with GNSS interference reports (7 and 30 days, with the spoofing column), parsed by
   tools/board.py's easa_firs(). EASA allows reproduction with the source acknowledged.
2. The Swedish Maritime Administration's page of Baltic navigational warnings in force (BALTICO): the page itself
   (gzipped) and a parsed list of every warning, with the GNSS-related ones marked. The page states no terms, so the
   copies stay in the private archive.

Both go into the private data repo's clone (data/ism-archive, made by tools/events.py fetch or collectors/ism_local.py)
under notices/easa/ and notices/baltico/, one file per UTC day, then commit and push. Run each morning from
collectors/run_daily.cmd. A source that fails is logged and the other still runs. Git uses this machine's credential
manager; nothing here reads or prints a credential.
"""
import argparse
import gzip
import html
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
CLONE = os.environ.get("NF_ISM_DIR") or os.path.join(ROOT, "data", "ism-archive")
BALTICO_URL = "https://navvarn.sjofartsverket.se/en/Navigationsvarningar/"
UA = {"User-Agent": "noise-floor notices (github.com/metacog-osint/noise-floor)"}
DTG = re.compile(r"(\d{6}) UTC ([A-Z]{3})(?: (\d{2,4}))?")
WARN_ID = re.compile(r"\b((?:[A-Z]+ )*(?:NAV WARN|NAVAREA I|NAVTEX)[A-Z ]*?\s*\d+/\d+)")
GNSS = re.compile(r"\b(GNSS|GPS|GLONASS|GALILEO|BEIDOU|DGPS|SATELLITE NAVIGATION)\b")
AREAS = ("Skagerrak", "Kattegat", "The Sound", "Western Baltic", "Southern Baltic", "South-eastern Baltic", "Central Baltic",
         "Northern Baltic", "Sea of Åland and Archipelago Sea", "Sea of Bothnia", "Bay of Bothnia",
         "Lake Vänern and Trollhätte Canal", "Lake Mälaren", "Other lakes and canals")


def baltico_parse(page):
    """Warnings on the page: [{id, dtg, text, areas, gnss}]. A warning listed under several sea areas appears once."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", page))
    text = re.sub(r"\s+", " ", text)
    marks = list(DTG.finditer(text))
    out = {}
    for k, m in enumerate(marks):
        end = marks[k + 1].start() if k + 1 < len(marks) else len(text)
        body = text[m.end():end].strip()
        before = text[max(0, m.start() - 60):m.start()]
        area = max(((before.rfind(n), n) for n in AREAS if n in before), default=(-1, None))[1]
        wid = WARN_ID.search(body[:80])
        if not wid and "function" in body:
            continue                      # the page's script, not a warning
        key = (wid.group(1).strip() if wid else body[:60])
        w = out.setdefault(key, {"id": wid.group(1).strip() if wid else None, "dtg": m.group(0), "text": body[:1200],
                                 "areas": [], "gnss": bool(GNSS.search(body))})
        if area and area not in w["areas"]:
            w["areas"].append(area)
    return list(out.values())


def git(*args, check=True):
    r = subprocess.run(["git", "-C", CLONE, *args], capture_output=True, text=True, timeout=300)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args[:2])}: {(r.stderr or r.stdout).strip()[:300]}")
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args()
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    print(f"=== notice_capture {now:%Y-%m-%dT%H:%MZ}")
    if not os.path.isdir(os.path.join(CLONE, ".git")):
        print(f"no private archive clone at {CLONE}: run tools/events.py fetch first")
        return 1
    sys.path.insert(0, os.path.join(ROOT, "collectors"))
    import ism_local
    if not ism_local.take_lock():
        print("another task holds the private clone; skipped")
        return 1
    try:
        return capture(a, now, day)
    finally:
        ism_local.drop_lock()


def capture(a, now, day):
    git("pull", "--ff-only", "--quiet", check=False)
    wrote = []
    try:
        import board
        e = board.easa_firs()
        e["fetched_utc"] = now.strftime("%Y-%m-%dT%H:%MZ")
        p = os.path.join(CLONE, "notices", "easa", f"{day}.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            json.dump(e, f, indent=1, ensure_ascii=False)
        wrote.append(p)
        t = e["tables"][0]
        print(f"EASA: {t['days']}-day table of {t['date']}: {len(t['firs'])} FIRs, {sum(r['spoofing'] for r in t['firs'])} with spoofing")
    except Exception as ex:
        print(f"EASA: failed ({type(ex).__name__}: {ex})")
    try:
        with urllib.request.urlopen(urllib.request.Request(BALTICO_URL, headers=UA), timeout=60) as r:
            page = r.read()
        d = os.path.join(CLONE, "notices", "baltico")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{day}.html.gz"), "wb") as f:
            f.write(gzip.compress(page, mtime=0))
        ws = baltico_parse(page.decode("utf-8", "replace"))
        with open(os.path.join(d, f"{day}.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump({"day": day, "fetched_utc": now.strftime("%Y-%m-%dT%H:%MZ"), "url": BALTICO_URL, "warnings": ws}, f,
                      indent=1, ensure_ascii=False)
        wrote += [os.path.join(d, f"{day}.html.gz"), os.path.join(d, f"{day}.json")]
        g = [w for w in ws if w["gnss"]]
        print(f"BALTICO: {len(ws)} warnings in force, {len(g)} GNSS-related: {', '.join(w['id'] or '?' for w in g)}")
    except Exception as ex:
        print(f"BALTICO: failed ({type(ex).__name__}: {ex})")
    if not wrote:
        return 1
    git("add", "notices")
    if git("diff", "--cached", "--quiet", check=False).returncode:
        git("commit", "--quiet", "-m", f"notices: {day} (local)")
        if not a.no_push:
            for _ in range(2):
                if not git("push", "--quiet", check=False).returncode:
                    print("pushed")
                    break
                if git("pull", "--rebase", "-X", "ours", "--quiet", check=False).returncode:
                    git("rebase", "--abort", check=False)
            else:
                print("push failed; the commit stays local and goes with the next push")
    else:
        print("nothing new")
    return 0


if __name__ == "__main__":
    sys.exit(main())
