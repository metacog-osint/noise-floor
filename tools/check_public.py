#!/usr/bin/env python3
"""check_public.py — block private terms from entering this public repo.

Runs as the git pre-commit hook (checks the staged version of each added/changed file) or with --all (every tracked
file, for CI). Terms are case-insensitive substrings, one per line, from the FORBIDDEN_TERMS environment variable
(newline-separated; a CI secret) or private/forbidden_terms.txt (gitignored). With no term list it fails closed.
A term of fewer than 7 digits matches only where it isn't part of a longer number (no digit or decimal point directly
before or after it): the Sea map's tracks hold millions of digits, and a five-digit term turned up inside a coordinate
on 26 Oct 2026. Longer digit terms (a phone number, which may appear with a country code in front) and every other term
stay plain substrings.

Usage
  python tools/check_public.py          # staged files (pre-commit)
  python tools/check_public.py --all    # all tracked files
  python tools/check_public.py --message .git/COMMIT_EDITMSG   # a commit message (commit-msg hook)
  python tools/check_public.py --log    # every commit message in the history (CI)
"""
import gzip, os, re, subprocess, sys

ROOT = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip() or "."
TERMS_FILE = os.path.join(ROOT, "private", "forbidden_terms.txt")


def terms():
    raw = os.environ.get("FORBIDDEN_TERMS")
    if raw is None and os.path.exists(TERMS_FILE):
        raw = open(TERMS_FILE, encoding="utf-8").read()
    return [t.strip().lower() for t in (raw or "").splitlines() if t.strip() and not t.lstrip().startswith("#")]


def found(term, low):
    """Is the term in the (lower-cased) text? Short digit terms (under 7 digits) must stand apart from other digits and
    decimal points; everything else is a plain substring."""
    if term not in low:
        return False
    if not term.isdigit() or len(term) >= 7:
        return True
    return re.search(r"(?<![\d.])" + re.escape(term) + r"(?![\d]|\.\d)", low) is not None


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, cwd=ROOT).stdout


def main():
    ts = terms()
    if not ts:
        print("check_public: no term list (FORBIDDEN_TERMS or private/forbidden_terms.txt) — refusing to pass.", file=sys.stderr)
        return 1
    if "--message" in sys.argv:              # commit-msg hook: the message being committed
        path = sys.argv[sys.argv.index("--message") + 1]
        text = open(path, encoding="utf-8", errors="replace").read().lower()
        n = sum(1 for t in ts if found(t, text))
        if n:
            print(f"check_public: the commit message contains {n} private term(s); edit it and commit again.", file=sys.stderr)
            return 1
        return 0
    if "--log" in sys.argv:                  # CI: every commit message in the history (needs a full clone)
        bad = []
        for rec in git("log", "--format=%H%x00%B%x1e").decode("utf-8", "replace").split("\x1e"):
            sha, _, body = rec.strip().partition("\x00")
            if sha and any(found(t, body.lower()) for t in ts):
                bad.append(sha[:10])
        if bad:
            print(f"check_public: {len(bad)} commit message(s) contain private terms: {' '.join(bad)}", file=sys.stderr)
            return 1
        print(f"check_public: commit messages OK ({len(git('rev-list', 'HEAD').split())} commits, {len(ts)} terms)")
        return 0
    every = "--all" in sys.argv
    names =(git("ls-files", "-z") if every else git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")).decode().split("\0")
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
                if found(t, low):
                    hits.append(f"{n}:{i}: private term #{ts.index(t) + 1}")
    if hits:
        print("check_public: private terms found (see private/forbidden_terms.txt for the numbered list):", file=sys.stderr)
        print("\n".join(hits[:50]), file=sys.stderr)
        return 1
    print(f"check_public: OK ({len([n for n in names if n])} file(s), {len(ts)} terms)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
