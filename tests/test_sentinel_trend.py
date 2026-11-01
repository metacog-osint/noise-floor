"""Offline tests for tools/sentinel_trend.py (box trends from the Sentinel receiver index). No network, no data/ files."""
import datetime as dt
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import sentinel_trend as M  # noqa: E402


def test_in_box_and_dateline():
    b = [-50.0, -40.0, 170.0, -170.0]               # crosses 180
    assert list(M.in_box([-45, -45, -45, -35], [175, -175, 0, 175], b)) == [True, True, False, False]
    assert list(M.in_box([-45], [-165], [-50, -40, -170, -160])) == [True]


def test_pad_wraps_longitude():
    assert M.pad([10.0, 20.0, 150.0, 172.0], 12.0) == [-2.0, 32.0, 138.0, -176.0]
    assert M.pad([80.0, 85.0, -10.0, 10.0], 10.0)[:2] == [70.0, 90.0]


def test_stats():
    s = M.stats([-4.0, -2.0, -0.5, 0.2], ["S1C", "S1C", "S2B", "S3A"])
    assert s == {"epochs": 4, "units": 3, "median": -1.25, "deg1": 0.5, "deg3": 0.25}
    assert M.stats([], [])["median"] is None


def test_week_start_is_monday():
    assert M.week_start(dt.date(2026, 9, 20)) == dt.date(2026, 9, 14)      # Sunday -> Monday before
    assert M.week_start(dt.date(2026, 9, 14)) == dt.date(2026, 9, 14)


def test_series_on_synthetic_epochs():
    cfg = {"focus_areas": [{"id": "x", "name": "X", "box": [-40, -30, 60, 70]}],
           "references": [{"id": "r", "name": "R", "box": [-10, 10, -150, -140]}], "comparisons": []}
    days = {dt.date(2026, 9, 14): -2.0, dt.date(2026, 9, 15): -1.0, dt.date(2026, 9, 21): 0.0}

    def fake(day, signal="l1"):
        if day not in days:
            return None
        lat = np.array([-35.0] * 5 + [0.0] * 5)
        lon = np.array([65.0] * 5 + [-145.0] * 5)
        d = np.r_[np.full(5, days[day]), np.full(5, 0.1)].astype(np.float32)
        return {"unit": np.array(["S1C"] * 10), "lat": lat, "lon": lon, "cell": np.array(["c"] * 10),
                "present": np.ones(10, bool), "d": d}
    old = M.load_day
    M.load_day = fake
    try:
        res = M.series(cfg, "x", sorted(days) + [dt.date(2026, 9, 16)])
    finally:
        M.load_day = old
    assert [r["day"] for r in res["daily"]] == ["2026-09-14", "2026-09-15", "2026-09-21"]
    assert res["daily"][0]["x"]["median"] == -2.0 and abs(res["daily"][0]["anomaly"] + 2.1) < 1e-6
    wk = {r["week"]: r for r in res["weekly"]}
    assert set(wk) == {"2026-09-14", "2026-09-21"}
    assert wk["2026-09-14"]["x"]["median"] == -1.5 and wk["2026-09-14"]["x"]["days"] == 2
    assert wk["2026-09-14"]["x"]["deg1"] == 1.0 and wk["2026-09-21"]["x"]["deg1"] == 0.0
    assert res["signal"] == "l1"


def test_signals_and_stems():
    assert M.stem("far", "l1") == "far" and M.stem("far", "l2c") == "far_l2c"
    assert M.SIGNALS["l1"][:2] == (M.EPOCH_DIR, "d_l1")
    assert M.SIGNALS["l2c"][:2] == (M.BANDS_DIR, "d_l2c") and M.SIGNALS["e5a"][1] == "d_e5a"
    for name, (_, _, label, floor, caption) in M.SIGNALS.items():
        text = caption.format(year=2026)
        assert "2026" in text and "{" not in text, name
        assert floor < 0 and label
    assert "1227.60 MHz" in M.SIGNALS["l2c"][4] and "Sentinel-1C, 1D and 2C" in M.SIGNALS["e5a"][4]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
