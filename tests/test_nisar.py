"""Offline tests for the NISAR L-band lane (nisar/). No network.

Runs the unit checks, then the end-to-end self-test on synthetic GCOV files in a temp folder
(about a minute; needs nisar/requirements.txt).
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NISAR = os.path.join(ROOT, "nisar")


def run(script, *args):
    r = subprocess.run([sys.executable, os.path.join(NISAR, "tests", script), *args], cwd=NISAR,
                       capture_output=True, text=True)
    print(r.stdout[-3000:], end="")
    if r.returncode:
        print(r.stderr[-3000:], file=sys.stderr)
        raise SystemExit(f"FAIL {script}")


def test_units():
    run("test_units.py")


def test_tables():
    run("test_tables.py")


def test_public():
    run("test_public.py")


def test_community():
    run("test_community.py")


def test_selftest():
    work = tempfile.mkdtemp(prefix="nisar_selftest_")
    try:
        run("selftest.py", work)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    test_units()
    test_tables()
    test_public()
    test_community()
    test_selftest()
    print("PASS test_nisar")
