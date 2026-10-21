#!/usr/bin/env python3
"""check_public.py — block private terms from entering this public repo.

Runs as the git pre-commit hook (checks the staged version of each added/changed file) or with --all (every tracked
file, for CI). Terms are case-insensitive substrings, one per line, from the FORBIDDEN_TERMS environment variable
(newline-separated; a CI secret) or private/forbidden_terms.txt (gitignored). With no term list it fails closed.

Usage
  python tools/check_public.py          # staged files (pre-commit)
  python tools/check_public.py --all    # all tracked files
"""
import gzip, os, subprocess, sys

ROOT = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip() or "."
TERMS_FILE = os.path.join(ROOT, "private", "forbidden_terms.txt")


def terms():
    raw = os.environ.get("FORBIDDEN_TERMS")
    if raw is None and os.path.exists(TERMS_FILE):
        raw = open(TERMS_FILE, encoding="utf-8").read()
    return [t.strip().lower() for t in (raw or "").splitlines() if t.strip() and not t.lstrip().startswith("#")]


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, cwd=ROOT).stdout


def main():
    ts = terms()
    if not ts:
        print("check_public: no term list (FORBIDDEN_TERMS or private/forbidden_terms.txt) — refusing to pass.", file=sys.stderr)
        return 1
    every = "--all" in sys.argv
    names = (git("ls-files", "-z") if every else git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")).decode().split("\0")
    hits = []
    for n in filter(None, names):
        for t in ts:
            if t in n.lower():
                hits.append(f"{n}: file name contains a private term")
        data = open(os.path.join(ROOT, n), "rb").read() if every else git("show", f":{n}")
        if n.lower().endswith(".gz"):  # check compressed assets as text too
            try:
                data = gzip.decompress(data)
            except Exception:
                hits.append(f"{n}: could not decompress to check")
                continue
        if b"\0" in data[:8192]:
            continue  # binary
        for i, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
            low = line.lower()
            for t in ts:
                if t in low:
                    hits.append(f"{n}:{i}: private term #{ts.index(t) + 1}")
    if hits:
        print("check_public: private terms found (see private/forbidden_terms.txt for the numbered list):", file=sys.stderr)
        print("\n".join(hits[:50]), file=sys.stderr)
        return 1
    print(f"check_public: OK ({len([n for n in names if n])} file(s), {len(ts)} terms)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
