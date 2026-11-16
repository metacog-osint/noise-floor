#!/usr/bin/env python3
"""spoof_cache_release.py: keep the spoofing day caches in a private GitHub release, so a detector variant can be
scored on GitHub Actions (.github/workflows/spoof-variant.yml) instead of on this PC.

  python tools/spoof_cache_release.py upload --test-days --cache data/spoof_cache --baseline data/spoofing_v06
  python tools/spoof_cache_release.py fetch --heldout --dest cache --baseline-dest base      (in the workflow)
  python tools/spoof_cache_release.py check                                                 (list the release)

Each day's cache folder (tools/spoof_day.py run --cache) becomes one uncompressed tar asset, <day>.spoof-cache.tar
(its files are compressed already); the baseline's events files for the held-out days (H6 of tools/spoof_heldout.py)
become baseline-<name>.tar. manifest.json records each asset's bytes and sha256, and fetch refuses an asset that
doesn't match. The tar holds only the cache's own files; nothing is written outside the destination on extract.

The caches and events hold ICAO addresses, so the release lives in a PRIVATE repository (Tom, 16 Nov 2026). Uploads
use the local gh login; the workflow reads with a read-only token (GH_TOKEN). Never upload these to a public release.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "metacog-osint/noise-floor-archive"
TAG = "spoof-cache"
NOV = ["2026-11-07", "2026-11-08", "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"]


def heldout_days():
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    from spoof_heldout import DAYS  # noqa: E402
    return list(DAYS)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def pack_dir(src, tar_path, arc_root):
    """Tar every file directly in src (a day cache: meta.json, records, candidate traces) under arc_root/."""
    names = sorted(n for n in os.listdir(src) if os.path.isfile(os.path.join(src, n)))
    if "meta.json" not in names:
        raise SystemExit(f"{src}: no meta.json, not a day cache")
    with tarfile.open(tar_path, "w", format=tarfile.PAX_FORMAT) as t:
        for n in names:
            t.add(os.path.join(src, n), arcname=f"{arc_root}/{n}", recursive=False)
    return names


def pack_files(paths, tar_path, arc_root):
    with tarfile.open(tar_path, "w", format=tarfile.PAX_FORMAT) as t:
        for p in paths:
            t.add(p, arcname=f"{arc_root}/{os.path.basename(p)}", recursive=False)


def extract(tar_path, dest, arc_root):
    """Extract arc_root/* from tar_path into dest/ (flat). Refuses links, devices and anything outside arc_root."""
    os.makedirs(dest, exist_ok=True)
    with tarfile.open(tar_path, "r") as t:
        for m in t.getmembers():
            parts = m.name.split("/")
            if not m.isfile() or len(parts) != 2 or parts[0] != arc_root or parts[1] in ("", ".", ".."):
                raise SystemExit(f"{tar_path}: unexpected member {m.name!r}")
            with t.extractfile(m) as src, open(os.path.join(dest, parts[1]), "wb") as out:
                while True:
                    b = src.read(1 << 20)
                    if not b:
                        break
                    out.write(b)


def gh(*args, capture=True):
    r = subprocess.run(["gh", *args], capture_output=capture, text=True, encoding="utf-8")
    if r.returncode:
        raise SystemExit(f"gh {' '.join(args[:3])} failed: {(r.stderr or '').strip()[:300]}")
    return r.stdout


def assets(repo, tag):
    try:
        j = json.loads(gh("release", "view", tag, "-R", repo, "--json", "assets"))
    except SystemExit:
        return None
    return {a["name"]: a["size"] for a in j["assets"]}


def upload(a):
    days = a.days or []
    if a.test_days:
        days = heldout_days() + NOV
    if a.heldout:
        days = heldout_days()
    have = assets(a.repo, a.tag)
    if have is None:
        gh("release", "create", a.tag, "-R", a.repo, "--title", "Spoofing day caches",
           "--notes", "Day caches for spoofing variant scoring (tools/spoof_cache_release.py). Private: holds ICAO "
                      "addresses. Derived from adsb.lol data (ODbL).")
        have = {}
    man_path = None
    with tempfile.TemporaryDirectory(dir=a.work) as tmp:
        man = {"repo": a.repo, "tag": a.tag, "assets": {}}
        if "manifest.json" in have:     # keep the other assets' entries; a failed read must not drop them
            gh("release", "download", a.tag, "-R", a.repo, "-p", "manifest.json", "-D", tmp)
            man = json.load(open(os.path.join(tmp, "manifest.json"), encoding="utf-8"))
            os.remove(os.path.join(tmp, "manifest.json"))
        todo = []
        for d in days:
            src = os.path.join(a.cache, d)
            name = f"{d}.spoof-cache.tar"
            tp = os.path.join(tmp, name)
            files = pack_dir(src, tp, d)
            meta = json.load(open(os.path.join(src, "meta.json"), encoding="utf-8"))
            man["assets"][name] = {"day": d, "kind": "cache", "bytes": os.path.getsize(tp), "sha256": sha256(tp),
                                   "files": files, "candidates": meta.get("candidates"),
                                   "envelope": meta.get("envelope"), "v06": meta.get("v06")}
            todo.append(tp)
            print(f"packed {name} {os.path.getsize(tp) / 1e6:.0f} MB", flush=True)
        if a.baseline:
            name = f"baseline-{a.baseline_name}.tar"
            tp = os.path.join(tmp, name)
            paths = [os.path.join(a.baseline, f"{d}.events.json.gz") for d in heldout_days()]
            pack_files(paths, tp, "baseline")
            man["assets"][name] = {"kind": "baseline", "name": a.baseline_name, "bytes": os.path.getsize(tp),
                                   "sha256": sha256(tp), "files": [os.path.basename(p) for p in paths]}
            todo.append(tp)
            print(f"packed {name} {os.path.getsize(tp) / 1e6:.1f} MB", flush=True)
        man_path = os.path.join(tmp, "manifest.json")
        with open(man_path, "w", encoding="utf-8") as f:
            json.dump(man, f, indent=1, sort_keys=True)
        for tp in todo:
            gh("release", "upload", a.tag, tp, "-R", a.repo, "--clobber", capture=False)
            print(f"uploaded {os.path.basename(tp)}", flush=True)
        gh("release", "upload", a.tag, man_path, "-R", a.repo, "--clobber", capture=False)
        have = assets(a.repo, a.tag) or {}
        bad = [n for n in [os.path.basename(t) for t in todo] if have.get(n) != man["assets"][n]["bytes"]]
        if bad:
            raise SystemExit(f"size mismatch after upload: {bad}")
        print(f"ok: {len(todo)} assets in {a.repo} release {a.tag}")


def fetch(a):
    days = a.days or []
    if a.test_days:
        days = heldout_days() + NOV
    if a.heldout:
        days = heldout_days()
    with tempfile.TemporaryDirectory() as tmp:
        gh("release", "download", a.tag, "-R", a.repo, "-p", "manifest.json", "-D", tmp)
        man = json.load(open(os.path.join(tmp, "manifest.json"), encoding="utf-8"))["assets"]
        want = [(f"{d}.spoof-cache.tar", d, os.path.join(a.dest, d)) for d in days]
        if a.baseline_dest:
            want.append((f"baseline-{a.baseline_name}.tar", "baseline", a.baseline_dest))
        for name, root, dest in want:
            if name not in man:
                raise SystemExit(f"{name} is not in the release manifest")
            gh("release", "download", a.tag, "-R", a.repo, "-p", name, "-D", tmp)
            tp = os.path.join(tmp, name)
            if os.path.getsize(tp) != man[name]["bytes"] or sha256(tp) != man[name]["sha256"]:
                raise SystemExit(f"{name}: bytes or sha256 differ from the manifest")
            extract(tp, dest, root)
            os.remove(tp)
            print(f"fetched {name}", flush=True)


def check(a):
    have = assets(a.repo, a.tag)
    if have is None:
        raise SystemExit(f"no release {a.tag} in {a.repo}")
    for n, s in sorted(have.items()):
        print(f"{n}\t{s / 1e6:.1f} MB")
    print(f"{len(have)} assets, {sum(have.values()) / 1e9:.2f} GB")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["upload", "fetch", "check"])
    ap.add_argument("days", nargs="*")
    ap.add_argument("--test-days", action="store_true", help="the 12 held-out days and 7-12 Nov 2026")
    ap.add_argument("--heldout", action="store_true", help="the 12 held-out days (tools/spoof_heldout.py DAYS)")
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--tag", default=TAG)
    ap.add_argument("--cache", default=os.path.join(ROOT, "data", "spoof_cache"), help="upload: day cache root")
    ap.add_argument("--baseline", help="upload: spoof_day output folder whose held-out events are the H6 baseline")
    ap.add_argument("--baseline-name", default="v06")
    ap.add_argument("--work", help="upload: folder for the temporary tars (default: system temp)")
    ap.add_argument("--dest", default="cache", help="fetch: day caches go to DEST/<day>/")
    ap.add_argument("--baseline-dest", help="fetch: also fetch baseline-<name>.tar into this folder")
    a = ap.parse_args()
    {"upload": upload, "fetch": fetch, "check": check}[a.cmd](a)


if __name__ == "__main__":
    main()
