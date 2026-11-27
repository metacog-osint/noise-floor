"""Tests for tools/check_public.py: its matching rule, and finding the term list from a linked worktree.
Run as a plain script: python tests/test_check_public.py"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import check_public as C  # noqa: E402


def test_found():
    f = C.found
    assert f("acme", "made by acme corp") and f("acme", "acmeco")             # text terms: plain substrings
    assert not f("acme", "nothing here")
    assert f("12345", "zip 12345 here") and f("12345", "12345") and f("12345", "(12345)") and f("12345", "12345.")
    assert f("12345", "code:12345,")                                           # punctuation around it still counts
    assert not f("12345", "60.123456")                                          # inside a decimal
    assert not f("12345", "[1793012345, 59.1, 24.2]")                           # inside a longer number
    assert not f("12345", "112345") and not f("12345", "123456")
    assert not f("12345", "3.12345") and not f("12345", "12345.6")             # decimal digits either side
    assert f("7015551234", "+17015551234") and f("7015551234", "tel 7015551234")  # long digit terms: plain substrings


def _run(cwd, *args, env=None):
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, env=env)


def test_worktree_finds_main_term_list():
    """A commit from a linked worktree is checked against the main checkout's private/forbidden_terms.txt, and with no
    list anywhere the check still fails closed."""
    script = os.path.join(ROOT, "tools", "check_public.py")
    env = {k: v for k, v in os.environ.items() if k != "FORBIDDEN_TERMS"}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@example.invalid")
    with tempfile.TemporaryDirectory() as tmp:
        main, wt = os.path.join(tmp, "main"), os.path.join(tmp, "wt")
        os.makedirs(main)
        for cmd in (["git", "init", "-q", "-b", "main"], ["git", "commit", "-q", "--allow-empty", "-m", "start"],
                    ["git", "worktree", "add", "-q", wt, "-b", "side"]):
            assert _run(main, *cmd, env=env).returncode == 0, cmd
        with open(os.path.join(wt, "notes.txt"), "w", encoding="utf-8") as f:
            f.write("a line naming zzqprivateterm\n")
        assert _run(wt, "git", "add", "notes.txt", env=env).returncode == 0

        r = _run(wt, sys.executable, script, env=env)                 # no list anywhere: fail closed
        assert r.returncode == 1 and "no term list" in r.stderr, r.stderr

        os.makedirs(os.path.join(main, "private"))
        with open(os.path.join(main, "private", "forbidden_terms.txt"), "w", encoding="utf-8") as f:
            f.write("# test list\nzzqprivateterm\n")
        r = _run(wt, sys.executable, script, env=env)                 # main checkout's list is found and used
        assert r.returncode == 1 and "notes.txt:1: private term #1" in r.stderr, r.stderr

        with open(os.path.join(wt, "notes.txt"), "w", encoding="utf-8") as f:
            f.write("a clean line\n")
        assert _run(wt, "git", "add", "notes.txt", env=env).returncode == 0
        r = _run(wt, sys.executable, script, env=env)                 # clean staged file passes
        assert r.returncode == 0 and "check_public: OK (1 file(s), 1 terms)" in r.stdout, r.stdout + r.stderr


NOTES_FILES = ("CLAUDE.md", "HISTORY.md", "HANDOFF.md")


def test_no_pointer_to_untracked_notes():
    """Contributor notes files are not part of this repository, so no tracked file may send a reader to one: a rule a
    comment relies on is stated in the comment itself."""
    tracked = set(subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines())
    names = [n for n in NOTES_FILES if n not in tracked]
    assert names, "every notes file is tracked; nothing to check"
    bad = []
    for path in sorted(tracked):
        if path == "tests/test_check_public.py":
            continue
        full = os.path.join(ROOT, path)
        if not os.path.isfile(full) or os.path.getsize(full) > 2_000_000:
            continue
        try:
            text = open(full, encoding="utf-8").read()
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if any(n in line for n in names):
                bad.append(f"{path}:{i}")
    assert not bad, "points at a notes file the repo does not hold: " + ", ".join(bad)


def main():
    test_found()
    test_worktree_finds_main_term_list()
    test_no_pointer_to_untracked_notes()
    print("test_check_public: ok (3 tests)")


if __name__ == "__main__":
    main()
