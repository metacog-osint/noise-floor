#!/usr/bin/env python3
"""release_archive.py: append-only history files on a GitHub release (retention rule, 18 Nov 2026).

A live file that is overwritten each run (a store, a 7-day window) keeps what readers see. This module keeps what the
overwrite would drop: each new or changed record goes, once, into a NEW asset with a unique name
(`<prefix>-<UTC stamp>.jsonl[.gz]`). Nothing is ever clobbered, so a bad run cannot damage an earlier file, and a
record is written again only when its content hash changes. One line per record:
  {"key": "<id>:<hash>", "seen_utc": "...", "record": {...}}
Standard library only; needs the GitHub CLI signed in or GH_TOKEN set. Upload failures raise, so callers fail loudly.
"""
import gzip, hashlib, json, os, re, subprocess, tempfile
from datetime import datetime, timezone

REPO = os.environ.get("GITHUB_REPOSITORY", "metacog-osint/noise-floor")


def gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {(r.stderr or r.stdout).strip()[:400]}")
    return r.stdout


def release_assets(tag, repo=None):
    """{name: size} of a release's assets, or None if there is no such release."""
    r = subprocess.run(["gh", "release", "view", tag, "-R", repo or REPO, "--json", "assets"],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        if "not found" not in (r.stderr or "").lower():
            raise RuntimeError(f"gh release view {tag}: {(r.stderr or '').strip()[:400]}")
        return None
    return {a["name"]: a["size"] for a in json.loads(r.stdout)["assets"]}


def ensure_release(tag, title, notes, repo=None):
    """Assets of the release, creating it first if missing."""
    have = release_assets(tag, repo)
    if have is None:
        gh("release", "create", tag, "-R", repo or REPO, "--title", title, "--notes", notes, "--latest=false")
        have = {}
    return have


def record_hash(rec):
    return hashlib.sha256(json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def read_keys(path):
    """The keys already written in one history file (.jsonl or .jsonl.gz; a gzip file may hold several members)."""
    op = gzip.open if path.endswith(".gz") else open
    keys = set()
    with op(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                keys.add(json.loads(line)["key"])
    return keys


def stamp(now=None):
    return (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")


def archive_new(tag, prefix, records, key_of, ext=".jsonl.gz", repo=None, now=None, title=None, notes=None, create=False, scan=None):
    """Append `records` (dicts) that no earlier history asset holds, as one new asset `<prefix>-<stamp><ext>`.
    key_of(rec) -> the record's identity (id); the content hash is added. `scan` is a regex for every earlier history
    asset to read keys from (default: names starting with prefix; pass one that spans months). Returns (n_written, name)."""
    repo = repo or REPO
    now = now or datetime.now(timezone.utc)
    have = ensure_release(tag, title or tag, notes or "", repo) if create else release_assets(tag, repo)
    if have is None:
        raise RuntimeError(f"release {tag} does not exist")
    known = set()
    pat = re.compile((scan or re.escape(prefix) + r"-") + r".*\.jsonl(\.gz)?$")
    with tempfile.TemporaryDirectory() as tmp:
        for name in sorted(n for n in have if pat.match(n)):
            gh("release", "download", tag, "-R", repo, "-p", name, "-D", tmp, "--clobber")
            known |= read_keys(os.path.join(tmp, name))
        lines, seen = [], set()
        for rec in records:
            key = f"{key_of(rec)}:{record_hash(rec)}"
            if key in known or key in seen:
                continue
            seen.add(key)
            lines.append(json.dumps({"key": key, "seen_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "record": rec},
                                    separators=(",", ":"), ensure_ascii=False))
        if not lines:
            return 0, None
        name = f"{prefix}-{stamp(now)}{ext}"
        if name in have:                      # two runs in one second: never overwrite
            name = f"{prefix}-{stamp(now)}-{len(have)}{ext}"
        path = os.path.join(tmp, name)
        data = ("\n".join(lines) + "\n").encode("utf-8")
        if ext.endswith(".gz"):
            with gzip.open(path, "wb") as f:
                f.write(data)
        else:
            with open(path, "wb") as f:
                f.write(data)
        gh("release", "upload", tag, "-R", repo, path)          # no --clobber: a name clash fails loudly
    return len(lines), name
