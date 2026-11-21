"""tools/notice_capture.py: BALTICO copies stay private, EASA still goes to the data repo, and no day is lost.
Runs offline against temporary folders. Run as a plain script: python tests/test_notice_capture.py"""
import argparse
import gzip
import json
import os
import subprocess
import sys
import tempfile
import types
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import notice_capture as N  # noqa: E402

NOW = datetime(2026, 11, 22, 11, 40, tzinfo=timezone.utc)
DAY = "2026-11-22"
PAGE = b"<p>Central Baltic</p><p>121209 UTC OCT 26 BALTIC SEA NAV WARN 030/26 GNSS INTERFERENCE OBSERVED IN AREA</p>"


class Reply:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return PAGE


def write(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def run_git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, check=True).stdout.strip()


def with_paths(td):
    N.CLONE = os.path.join(td, "clone")
    N.BALTICO_DIR = os.path.join(td, "private", "baltico")
    return os.path.join(N.CLONE, "notices", "baltico")


def test_seed_copies_missing_files_and_never_overwrites_or_removes():
    with tempfile.TemporaryDirectory() as td:
        public = with_paths(td)
        write(os.path.join(public, "2026-10-26.json"), b"public old")
        write(os.path.join(public, "2026-10-27.json"), b"public new")
        write(os.path.join(N.BALTICO_DIR, "2026-10-26.json"), b"private")
        assert N.seed_baltico(public, N.BALTICO_DIR) == 1
        with open(os.path.join(N.BALTICO_DIR, "2026-10-26.json"), "rb") as f:
            assert f.read() == b"private"
        with open(os.path.join(N.BALTICO_DIR, "2026-10-27.json"), "rb") as f:
            assert f.read() == b"public new"
        assert sorted(os.listdir(public)) == ["2026-10-26.json", "2026-10-27.json"]
        assert N.seed_baltico(public, N.BALTICO_DIR) == 0


def test_baltico_goes_to_the_private_folder_only():
    real = N.urllib.request.urlopen
    N.urllib.request.urlopen = lambda *a, **k: Reply()
    try:
        with tempfile.TemporaryDirectory() as td:
            public = with_paths(td)
            write(os.path.join(public, "2026-11-21.json"), b"earlier day")
            assert N.capture_baltico(NOW, DAY) is True
            assert sorted(os.listdir(public)) == ["2026-11-21.json"]
            assert sorted(os.listdir(N.BALTICO_DIR)) == ["2026-11-21.json", f"{DAY}.html.gz", f"{DAY}.json"]
            with open(os.path.join(N.BALTICO_DIR, f"{DAY}.html.gz"), "rb") as f:
                assert gzip.decompress(f.read()) == PAGE
            with open(os.path.join(N.BALTICO_DIR, f"{DAY}.json"), encoding="utf-8") as f:
                doc = json.load(f)
            assert doc["day"] == DAY and doc["warnings"][0]["gnss"] is True
    finally:
        N.urllib.request.urlopen = real


def test_failed_fetch_still_seeds_earlier_days():
    def down(*a, **k):
        raise OSError("network down")
    real = N.urllib.request.urlopen
    N.urllib.request.urlopen = down
    try:
        with tempfile.TemporaryDirectory() as td:
            public = with_paths(td)
            write(os.path.join(public, "2026-11-21.json"))
            assert N.capture_baltico(NOW, DAY) is False
            assert os.listdir(N.BALTICO_DIR) == ["2026-11-21.json"]
    finally:
        N.urllib.request.urlopen = real


def test_easa_commit_holds_only_easa_files():
    table = {"tables": [{"days": 7, "date": "2026-11-22", "firs": [{"spoofing": 1}]}]}
    real = sys.modules.get("board")
    sys.modules["board"] = types.SimpleNamespace(easa_firs=lambda: dict(table))
    try:
        with tempfile.TemporaryDirectory() as td:
            public = with_paths(td)
            subprocess.run(["git", "init", "--quiet", N.CLONE], check=True)
            run_git(N.CLONE, "config", "user.name", "test")
            run_git(N.CLONE, "config", "user.email", "test@example.invalid")
            write(os.path.join(N.CLONE, "README.md"), b"readme")
            run_git(N.CLONE, "add", "README.md")
            run_git(N.CLONE, "commit", "--quiet", "-m", "start")
            write(os.path.join(public, "stray.json"), b"must not be committed")
            assert N.capture_easa(argparse.Namespace(no_push=True), NOW, DAY) == 0
            assert run_git(N.CLONE, "show", "--name-only", "--format=", "HEAD") == f"notices/easa/{DAY}.json"
            assert "notices/baltico/stray.json" in run_git(N.CLONE, "status", "--porcelain", "--untracked-files=all")
    finally:
        if real is None:
            del sys.modules["board"]
        else:
            sys.modules["board"] = real


if __name__ == "__main__":
    for k, f in sorted(globals().items()):
        if k.startswith("test_"):
            f()
            print(k, "ok")
