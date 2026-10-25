"""tools/year_trends.py: step detection, spikes and spike runs on synthetic series."""
import os, sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import year_trends as Y  # noqa: E402


def main():
    rng = np.random.default_rng(7)
    days = [f"2026-{m:02d}-{d:02d}" for m in range(1, 13) for d in range(1, 29)][:200]
    flat = 5 + rng.normal(0, 0.8, 200)
    assert Y.segments(flat) == [], Y.segments(flat)                       # noise alone: no steps
    step = flat.copy(); step[120:] += 6
    s = Y.segments(step)
    assert len(s) == 1 and abs(s[0] - 120) <= 3, s                          # one step, found within 3 days
    gap = step.copy(); gap[40:55] = np.nan                                   # gaps are skipped, positions stay in the original index
    s = Y.segments(gap)
    assert len(s) == 1 and abs(s[0] - 120) <= 3, s
    two = flat.copy(); two[60:] += 5; two[150:] -= 8
    s = Y.segments(two)
    assert len(s) == 2 and abs(s[0] - 60) <= 3 and abs(s[1] - 150) <= 3, s
    short = flat.copy(); short[100:104] += 15                                # a 4-day surge is a spike run, not a step
    assert Y.segments(short) == []
    r = Y.runs(Y.spikes(short, days))
    assert len(r) == 1 and r[0]["days"] == 4 and r[0]["start"] == days[100], r
    assert Y.runs([{"day": "2026-01-01", "share": 9, "usual": 2}, {"day": "2026-01-03", "share": 8, "usual": 2}])[1]["start"] == "2026-01-03"
    name, km = Y.nearest_place([["A", 54.7, 20.5, 1, 0], ["B", 10, 10, 1, 0]], 54.9, 20.1)
    assert name == "A" and 25 < km < 40, (name, km)
    assert Y.nearest_place([["B", 10, 10, 1, 0]], 54.9, 20.1) == (None, None)
    print("test_year_trends: ok")


if __name__ == "__main__":
    main()
