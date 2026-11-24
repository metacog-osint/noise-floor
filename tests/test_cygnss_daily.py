"""tools/cygnss_daily.py: which days a run takes. Run as a plain script: python tests/test_cygnss_daily.py"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import cygnss_daily as C  # noqa: E402

TODAY = date(2026, 11, 23)


def done(*days):
    names = {f"{d}.cygnss.json" for d in days}
    return lambda path: os.path.basename(path) in names


def test_a_finished_day_does_not_end_the_search():
    days = C.pending_days(TODAY, exists=done("2026-11-21"), is_complete=lambda d, t: (True, 7))
    assert "2026-11-21" not in days
    assert days[0] == "2026-11-20", days
    assert len(days) == C.LOOKBACK - 2, days


def test_an_incomplete_day_is_left_for_later():
    days = C.pending_days(TODAY, exists=done(), is_complete=lambda d, t: (d != "2026-11-20", 3))
    assert "2026-11-20" not in days and "2026-11-19" in days


def test_nothing_to_do():
    every = [f"2026-11-{d:02d}" for d in range(13, 22)]
    assert C.pending_days(TODAY, exists=done(*every), is_complete=lambda d, t: (True, 7)) == []


if __name__ == "__main__":
    test_a_finished_day_does_not_end_the_search()
    test_an_incomplete_day_is_left_for_later()
    test_nothing_to_do()
    print("test_cygnss_daily: ok")
