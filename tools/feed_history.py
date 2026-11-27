#!/usr/bin/env python3
"""feed_history.py: Noisefloor's feed history log, kept on the GitHub release `feed-history` (20 Nov 2026).

  python tools/feed_history.py pull DIR         download the log and state; a missing release is a first run
  python tools/feed_history.py run SITE DIR     log this build's changes and fill last_change in SITE/data/feed.geojson
  python tools/feed_history.py push DIR         upload what changed

Nothing is ever deleted from the release. A closed day's file is uploaded once and never replaced; only state.json,
health.json and today's open log are replaced. `pull` fails rather than start over when the release exists but its
state cannot be read, because a fresh state would log every open item as new.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "doctrine", "kit", "python"))
from tic_doctrine import contract, history  # noqa: E402

TAG = "feed-history"
REPO = os.environ.get("GITHUB_REPOSITORY", "metacog-osint/noise-floor")


def gh(*args, check=True):
    return subprocess.run(["gh", *args], check=check, capture_output=True, text=True)


def asset_name(rel):
    """log/2026/11/21.jsonl -> log-2026-11-21.jsonl: release assets have no folders."""
    return rel.replace("/", "-")


def asset_path(name):
    """The reverse of asset_name, for the log's files; state.json and health.json stay at the top."""
    if not name.startswith("log-"):
        return name
    y, m, rest = name[4:].split("-", 2)
    return f"log/{y}/{m}/{rest}"


def remote_assets():
    """Asset names on the release, or None when the release does not exist."""
    r = gh("release", "view", TAG, "-R", REPO, "--json", "assets", check=False)
    if r.returncode:
        if "release not found" in (r.stderr or "").lower():
            return None
        raise RuntimeError(f"cannot read release {TAG}: {r.stderr.strip()[:200]}")
    return [a["name"] for a in json.loads(r.stdout)["assets"]]


def wanted(names):
    """The assets to restore: a day's open .jsonl stays on the release after the day closes, and its .gz is the record."""
    return [n for n in names if not (n.endswith(".jsonl") and n + ".gz" in names)]


def pull(root):
    root.mkdir(parents=True, exist_ok=True)
    names = remote_assets()
    if names is None:
        print(f"feed_history: no release {TAG} yet; first run")
        return 0
    if "state.json" not in names:
        raise RuntimeError(f"release {TAG} has no state.json; refusing to start a new log over it")
    names = wanted(names)
    for name in names:
        out = root / asset_path(name)
        out.parent.mkdir(parents=True, exist_ok=True)
        gh("release", "download", TAG, "-R", REPO, "-p", name, "-O", str(out), "--clobber")
    json.loads((root / "state.json").read_text(encoding="utf-8"))     # a damaged state stops the run here
    print(f"feed_history: pulled {len(names)} files")
    return 0


def carry_stated(feed, state):
    """A change the item states itself keeps the time it was first stated: a region stays "new" for a week of
    readings, and that is one change, not seven."""
    for f in feed["features"]:
        p = f["properties"]
        if not p.get("last_change") or p["last_change"] == "none":
            continue
        e = ((state or {}).get("open") or {}).get(p.get("subject_id")) or {}
        was = (e.get("item") or {}).get("properties") or {}
        if was.get("last_change") == p["last_change"] and was.get("last_change_at"):
            p["last_change_at"] = min(was["last_change_at"], p["last_change_at"])


def previous_failures(feed, root):
    """Failed checks in a row, across runs."""
    path = root / "health.json"
    before = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for k, e in feed.get("health", {}).items():
        if e["state"] == "failing":
            e["failures"] = ((before.get(k) or {}).get("failures") or 0) + 1
    path.write_text(json.dumps(feed.get("health", {})), encoding="utf-8", newline="\n")


def apply(feed, root, now):
    """Log this build and fill last_change, in place. Separate from the file handling so a test can run it."""
    carry_stated(feed, history.load_state(root))
    previous_failures(feed, root)
    lines = history.run(feed, root, now, feed.get("health"), fill=True)
    published = feed["generated_at"]
    for f in feed["features"]:
        p = f["properties"]
        if p.get("last_change_at") and p["last_change_at"] > published:      # finding 4.2: never after publication
            p["last_change_at"] = published
    return lines


def run(site, root):
    path = Path(site) / "data" / "feed.geojson"
    feed = json.loads(path.read_text(encoding="utf-8"))
    now = history.run_time(feed)                                             # finding 4.3: the feed's own build time
    lines = apply(feed, root, now)
    errors = [(f["properties"]["id"], *x) for f in feed["features"] for x in contract.check(f) if x[1] == "error"]
    if errors:
        raise RuntimeError(f"{len(errors)} contract errors after the fill, first: {errors[0]}")
    path.write_text(json.dumps(feed, separators=(",", ":"), ensure_ascii=False), encoding="utf-8", newline="\n")
    n = {c: sum(1 for x in lines if x["change"] == c) for c in ("new", "changed", "ended")}
    print(f"feed_history: {n['new']} new, {n['changed']} changed, {n['ended']} ended; "
          f"last_change on {sum(1 for f in feed['features'] if f['properties'].get('last_change'))} of {len(feed['features'])}")
    return 0


def push(root):
    names = remote_assets()
    if names is None:
        gh("release", "create", TAG, "-R", REPO, "--title", "Feed history (tic-history/1)", "--latest=false",
           "--notes", "Noisefloor's feed history log: one line per new, changed or ended item, kept for good. "
                      "Licences as in the feed: ODbL 1.0 for items derived from adsb.lol, CC BY 4.0 for the rest.")
        names = []
    with tempfile.TemporaryDirectory() as tmp:          # an asset takes its file's name, so copy each to its flat name
        for f in sorted(root.rglob("*")):
            if not f.is_file():
                continue
            name = asset_name(f.relative_to(root).as_posix())
            if name.endswith(".gz") and name in names:                       # a closed day is never rewritten
                continue
            flat = Path(tmp) / name
            shutil.copyfile(f, flat)
            gh("release", "upload", TAG, str(flat), "-R", REPO, "--clobber")
    print(f"feed_history: pushed to {TAG}")
    return 0


def main():
    a = sys.argv[1:]
    if len(a) == 2 and a[0] == "pull":
        return pull(Path(a[1]))
    if len(a) == 3 and a[0] == "run":
        return run(a[1], Path(a[2]))
    if len(a) == 2 and a[0] == "push":
        return push(Path(a[1]))
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main())
