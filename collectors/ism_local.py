#!/usr/bin/env python3
"""ism_local.py: run the ESA scintillation capture from this PC and push each new hour to the private archive repo.

Why: ESA publishes only the current hour of its ionospheric scintillation nowcast. The archive repo's GitHub workflow is
scheduled twice an hour, but GitHub ran it only every 2-5 hours (21-26 Oct 2026: 25 of about 120 hours kept). Windows
Task Scheduler runs this every 30 minutes (task "noise-floor ESA scintillation capture", at :26 and :56, so it seldom
overlaps the GitHub run, which stays on as the backup for when this PC is off).

The clone (data/ism-archive, or NF_ISM_DIR; `tools/events.py fetch` makes it) is a working copy of the private repo,
where the capture script and ESA's terms live. Each run: fetch; commit any files an interrupted run left; rebase onto
the remote (summary.csv merges by union, set in that repo's .gitattributes); capture (an hour already captured is
skipped); commit; push. A run that can't reach GitHub or ESA exits non-zero and the next run tries again: an hour not
yet pushed stays in the local commit. Git uses this machine's credential manager; nothing here reads or prints a
credential. Data: (c) ESA, provided as part of ESA's Space Safety Programme (S2P).

  pythonw collectors/ism_local.py --log data/logs/ism_capture.log     (what the task runs: no console window)
  python collectors/ism_local.py                                        (by hand)
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLONE = os.environ.get("NF_ISM_DIR") or os.path.join(ROOT, "data", "ism-archive")
REPO = "https://github.com/metacog-osint/noise-floor-data.git"   # private: ESA's terms bar passing the raw grids on
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)           # pythonw must not flash a console for each git call


def run(cmd, timeout=300, cwd=None):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, creationflags=NO_WINDOW)


def git(*args, check=True):
    r = run(["git", "-C", CLONE, *args])
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args[:2])}: {(r.stderr or r.stdout).strip()[:300]}")
    return r


def ahead():
    return int(git("rev-list", "--count", "@{u}..HEAD").stdout.strip() or 0)


def dirty():
    return bool(git("status", "--porcelain", "--", "ism").stdout.strip())


def commit(message):
    git("add", "ism")
    git("commit", "--quiet", "-m", message)


def sync():
    """Level with the remote, keeping local commits not yet pushed. If a rebase conflicts (both sides captured the same
    hour), drop the local side: the remote already has that hour."""
    git("fetch", "--quiet", "origin")
    if dirty():
        commit("ism: files left by an interrupted run (local)")
    if git("rebase", "--quiet", "@{u}", check=False).returncode:
        git("rebase", "--abort", check=False)
        git("reset", "--quiet", "--hard", "@{u}")
        print("  rebase conflicted: reset to the remote (it already had the hour)")


def last_valid():
    with open(os.path.join(CLONE, "ism", "summary.csv"), encoding="utf-8") as f:
        rows = [l for l in f.read().splitlines() if l.strip()]
    return rows[-1].split(",")[0] if len(rows) > 1 else "?"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--log", help="append output to this file (the scheduled task uses pythonw, which has no console)")
    a = ap.parse_args()
    if a.log:
        os.makedirs(os.path.dirname(os.path.abspath(a.log)), exist_ok=True)
        sys.stdout = sys.stderr = open(a.log, "a", encoding="utf-8", buffering=1)
    print(f"=== {datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}")
    try:
        if not os.path.isdir(os.path.join(CLONE, ".git")):
            r = run(["git", "clone", "--quiet", "--depth", "1", REPO, CLONE], timeout=600)
            if r.returncode:
                raise RuntimeError(f"git clone: {r.stderr.strip()[:300]}")
        sync()
        r = run([sys.executable, os.path.join(CLONE, "capture", "ism_capture.py"), CLONE], timeout=600)
        out = (r.stdout + r.stderr).strip()
        print("  " + (out.replace("\n", "\n  ") or "(no output)"))
        if r.returncode:
            raise RuntimeError(f"capture exited {r.returncode}")
        if dirty():
            commit(f"ism: {last_valid()} (local)")
        for attempt in range(3):
            if not ahead():
                print("  nothing to push")
                return 0
            p = git("push", "--quiet", check=False)
            if not p.returncode:
                print(f"  pushed (newest hour {last_valid()})")
                return 0
            print(f"  push refused ({p.stderr.strip()[:120]}); syncing and retrying")
            sync()
        raise RuntimeError("push failed three times")
    except Exception as e:          # logged; the next run tries again
        print(f"  ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
