#!/usr/bin/env python3
"""notice_capture.py: keep a daily history of two official sources that show only what is current.

  python tools/notice_capture.py [--no-push]

1. EASA's tables of FIRs with GNSS interference reports (7 and 30 days, with the spoofing column), parsed by
   tools/board.py's easa_firs(). EASA allows reproduction with the source acknowledged. One file per UTC day goes into
   the public data repo's clone (data/ism-archive, made by tools/events.py fetch or collectors/ism_local.py) under
   notices/easa/, then commit and push.
2. The Swedish Maritime Administration's page of Baltic navigational warnings in force (BALTICO): the page itself
   (gzipped) and a parsed list of every warning, with the GNSS-related ones marked. The page states no terms, so new
   copies stay private: one pair of files per UTC day in data/notices/baltico/ (or NF_BALTICO_DIR), which the baltico
   lane of tools/pc_archive.py copies to the private archive. Earlier copies remain in the public data repo; any file
   only that repo holds is copied into the private folder too, so the private history is complete.

Run each morning from collectors/run_daily.cmd. A source that fails is logged and the other still runs. Git uses this
machine's credential manager; nothing here reads or prints a credential.
"""
import argparse
import gzip
import html
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
CLONE = os.environ.get("NF_ISM_DIR") or os.path.join(ROOT, "data", "ism-archive")
BALTICO_DIR = os.environ.get("NF_BALTICO_DIR") or os.path.join(ROOT, "data", "notices", "baltico")
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
    baltico_ok = capture_baltico(now, day)        # first, and outside the clone's lock: a busy clone can't cost a day
    return 0 if capture_easa_locked(a, now, day) == 0 or baltico_ok else 1


def seed_baltico(clone_dir, store):
    """Copy every file only the public clone holds into the private store. Never moves, deletes or overwrites."""
    os.makedirs(store, exist_ok=True)
    copied = 0
    if not os.path.isdir(clone_dir):
        return copied
    for name in sorted(os.listdir(clone_dir)):
        src, dest = os.path.join(clone_dir, name), os.path.join(store, name)
        if os.path.isfile(src) and not os.path.exists(dest):
            shutil.copy2(src, dest + ".tmp")
            os.replace(dest + ".tmp", dest)
            copied += 1
    return copied


def capture_baltico(now, day):
    """Today's BALTICO page and parsed warnings into the private folder. True when both files were written."""
    try:
        n = seed_baltico(os.path.join(CLONE, "notices", "baltico"), BALTICO_DIR)
        if n:
            print(f"BALTICO: copied {n} earlier files into the private folder")
    except OSError as ex:
        print(f"BALTICO: copying earlier files failed ({type(ex).__name__}: {ex}); the next run tries again")
    try:
        with urllib.request.urlopen(urllib.request.Request(BALTICO_URL, headers=UA), timeout=60) as r:
            page = r.read()
        os.makedirs(BALTICO_DIR, exist_ok=True)
        with open(os.path.join(BALTICO_DIR, f"{day}.html.gz"), "wb") as f:
            f.write(gzip.compress(page, mtime=0))
        ws = baltico_parse(page.decode("utf-8", "replace"))
        with open(os.path.join(BALTICO_DIR, f"{day}.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump({"day": day, "fetched_utc": now.strftime("%Y-%m-%dT%H:%MZ"), "url": BALTICO_URL, "warnings": ws}, f,
                      indent=1, ensure_ascii=False)
        g = [w for w in ws if w["gnss"]]
        print(f"BALTICO: {len(ws)} warnings in force, {len(g)} GNSS-related: {', '.join(w['id'] or '?' for w in g)}")
        return True
    except Exception as ex:
        print(f"BALTICO: failed ({type(ex).__name__}: {ex})")
        return False


def capture_easa_locked(a, now, day):
    if not os.path.isdir(os.path.join(CLONE, ".git")):
        print(f"no data repo clone at {CLONE}: run tools/events.py fetch first")
        return 1
    sys.path.insert(0, os.path.join(ROOT, "collectors"))
    import ism_local
    if not ism_local.take_lock():
        print("another task holds the data repo clone; EASA skipped")
        return 1
    try:
        return capture_easa(a, now, day)
    finally:
        ism_local.drop_lock()


def capture_easa(a, now, day):
    git("pull", "--ff-only", "--quiet", check=False)
    try:
        import board
        e = board.easa_firs()
        e["fetched_utc"] = now.strftime("%Y-%m-%dT%H:%MZ")
        p = os.path.join(CLONE, "notices", "easa", f"{day}.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            json.dump(e, f, indent=1, ensure_ascii=False)
        t = e["tables"][0]
        print(f"EASA: {t['days']}-day table of {t['date']}: {len(t['firs'])} FIRs, {sum(r['spoofing'] for r in t['firs'])} with spoofing")
    except Exception as ex:
        print(f"EASA: failed ({type(ex).__name__}: {ex})")
        return 1
    git("add", "notices/easa")
    if git("diff", "--cached", "--quiet", "--", "notices/easa", check=False).returncode:
        git("commit", "--quiet", "-m", f"notices: {day} (local)", "--", "notices/easa")
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
