"""Offline tests for tools/s1_daily.py (Sentinel-1 C-band activity map file). No network, no data/ files."""
import os
import sys
import tempfile

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import s1_daily as D  # noqa: E402


def week_file(rows):
    """rows: (cell, lat, lon, passes, rfi_passes)"""
    d = tempfile.mkdtemp()
    p = os.path.join(d, "w.parquet")
    pq.write_table(pa.table({"cell": [r[0] for r in rows], "lat": [r[1] for r in rows], "lon": [r[2] for r in rows],
                             "passes": [r[3] for r in rows], "rfi_passes": [r[4] for r in rows],
                             "share": [r[4] / r[3] for r in rows]}), p)
    return p


def test_cuts_and_order():
    p = week_file([("a", 33.0, 44.0, 10, 10),     # busy, shown first
                   ("b", 33.5, 44.5, 10, 9),      # busy, but within 800 km of a: not a second "busiest"
                   ("c", 26.0, 52.0, 8, 8),       # busy, far away: second busiest
                   ("d", 50.0, 10.0, 12, 2),      # share 0.17: covered, not shown
                   ("e", 10.0, 10.0, 3, 3),       # too few passes: not covered
                   ("f", 40.0, -100.0, 6, 2)])    # share 0.33: shown, not busy (passes < 8)
    s = D.summarise("2026-10-29", week_path=p)
    assert s["covered"] == 5 and s["shown"] == 4
    assert [c[0] for c in s["cells"]] == ["a", "c", "b", "f"]
    assert s["cells"][0] == ["a", 1.0, 10]
    assert [(b["lat"], b["lon"]) for b in s["busiest"]] == [(33.0, 44.0), (26.0, 52.0)]
    assert s["window"] == ["2026-10-02", "2026-10-29"]
    assert "Copernicus Sentinel data 2026" in s["credit"][0]


def test_window_days():
    w = D.window_days("2026-11-03")
    assert len(w) == D.WINDOW and w[0] == "2026-10-07" and w[-1] == "2026-11-03"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
