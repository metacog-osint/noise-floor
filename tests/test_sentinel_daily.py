"""Offline tests for tools/sentinel_daily.py (the daily Sentinel receiver job). No network, no data/ files."""
import datetime as dt
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import sentinel_daily as M  # noqa: E402

D = dt.date


def test_days_to_build():
    held = [D(2026, 10, 20), D(2026, 10, 21)]
    assert M.days_to_build(D(2026, 10, 25), held, 4, 8) == [D(2026, 10, 22), D(2026, 10, 23), D(2026, 10, 24),
                                                           D(2026, 10, 25)]
    assert M.days_to_build(D(2026, 10, 25), held, 2, 8) == [D(2026, 10, 22), D(2026, 10, 23)], "oldest first, capped"
    assert M.days_to_build(D(2026, 10, 21), held, 4, 8) == [], "nothing newer than held"
    assert M.days_to_build(D(2026, 10, 25), [], 3, 1) == [D(2026, 10, 18), D(2026, 10, 19), D(2026, 10, 20)]
    assert M.days_to_build(D(2026, 10, 25), [D(2025, 1, 1)], 2, 1) == [D(2026, 10, 18), D(2026, 10, 19)], \
        "an old held day doesn't pull in months of history"



def test_bands_missing():
    held = [D(2026, 10, d) for d in range(20, 29)]
    bands = [D(2026, 10, 20), D(2026, 10, 25)]
    assert M.bands_missing(held, bands, 8, 3) == [D(2026, 10, 28), D(2026, 10, 27), D(2026, 10, 26)], "newest first"
    assert M.bands_missing(held, held, 8, 3) == []
    assert M.bands_missing([], bands, 8, 3) == []
    old = [D(2026, 1, 1)] + held
    assert D(2026, 1, 1) not in M.bands_missing(old, bands, 1, 20), "outside the window"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
