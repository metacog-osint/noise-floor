"""Offline tests for tools/sentinel_rfi.py (Sentinel receivers, steps E2 and E3). No network, no data/ files."""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import sentinel_rfi as M  # noqa: E402


def synthetic_unit_day(jam_db=-4.0, n_ep=300, links=8, seed=1):
    """Epochs 0..n_ep-1 (10 s apart). The first 30% sit in cell 'A' with every link jam_db weaker; the rest in 'B'/'C'."""
    rng = np.random.default_rng(seed)
    t, sat, el, val, cell = [], [], [], [], []
    for e in range(n_ep):
        c = "A" if e < 0.3 * n_ep else ("B" if e % 2 else "C")
        for k in range(links):
            ee = rng.uniform(5, 85)
            v = 30 + 0.3 * ee + rng.normal(0, 0.2) + (jam_db if c == "A" else 0.0)
            t.append(e * 10)
            sat.append(f"G{k + 1:02d}")
            el.append(ee)
            val.append(v)
            cell.append(c)
    return (np.array(t), np.array(sat), np.array(el), np.array(val), np.array(cell, dtype=object))


def test_index_keeps_jammed_cells_out_of_the_baseline():
    t, sat, el, val, cell = synthetic_unit_day()
    ei = M.index_signal("S2C|2026-01-01|l1", t, sat, el, val, cell)
    ep_cell = {x: c for x, c in zip(t, cell)}
    d_a = [d for x, d in zip(ei["t"], ei["idx"]) if ep_cell[x] == "A"]
    d_o = [d for x, d in zip(ei["t"], ei["idx"]) if ep_cell[x] != "A"]
    assert abs(np.median(d_a) + 4.0) < 0.3, np.median(d_a)
    assert abs(np.median(d_o)) < 0.15, np.median(d_o)
    # links below 10 deg are not scored, and an epoch needs 4 scored links
    assert np.all(ei["n"] >= 4) and np.all(ei["n"] <= 8)


def test_one_pass_is_biased_three_are_not():
    t, sat, el, val, cell = synthetic_unit_day(jam_db=-8.0, n_ep=200)
    one = M.index_signal("x", t, sat, el, val, cell, passes=1)
    three = M.index_signal("x", t, sat, el, val, cell, passes=3)
    clean = np.array([c != "A" for c in cell[np.unique(t, return_index=True)[1]]])
    # the median baseline resists 30% jammed links, but the frozen three passes bring the clean epochs to 0 dB
    assert abs(np.median(three["idx"][clean])) <= abs(np.median(one["idx"][clean])) + 1e-9


def test_cell_values_and_passes():
    # unit S1C crosses cell X twice on day 0 (gap 600 s), S2B once on day 1; 5 epochs each pass
    cell = np.array(["X"] * 15 + ["Y"] * 3 + [""] * 2, dtype=object)
    unit = np.array(["S1C"] * 10 + ["S2B"] * 5 + ["S1C"] * 5)
    day = np.array([0] * 10 + [1] * 5 + [0] * 5)
    t = np.r_[np.arange(5) * 10, 600 + np.arange(5) * 10, np.arange(5) * 10, 2000 + np.arange(5) * 10]
    v = np.r_[np.full(10, -2.0), np.full(5, 0.5), np.full(3, -0.1), np.full(2, -9.0)]
    out = M.cell_values(cell, unit, day, t, v, np.ones(20, bool))
    assert out["X"] == (-2.0, 15, 3), out["X"]
    assert out["Y"] == (-0.1, 3, 1)
    assert "" not in out
    assert M.judged(out) == {"X": -2.0}              # Y has 3 epochs from 1 pass: not judged


def test_weighted_median():
    assert M.weighted_median([1.0, 2.0, 3.0], [1, 1, 1]) == 2.0
    assert M.weighted_median([1.0, 5.0], [10, 1]) == 1.0
    assert M.weighted_median([0.0, 4.0, 9.0], [1, 1, 5]) == 9.0


def test_verdicts_follow_the_marks():
    assert M.verdict(1, 0.85) == "holds" and M.verdict(1, 0.75) == "weakened" and M.verdict(1, 0.6) == "fails"
    assert M.verdict(4, -1.2) == "holds" and M.verdict(4, -0.7) == "weakened" and M.verdict(4, 0.1) == "fails"
    assert M.verdict(5, 0.01) == "holds" and M.verdict(5, 0.03) == "weakened" and M.verdict(5, 0.08) == "fails"
    assert M.verdict(2, None) == "not judged"


def test_frozen_windows_and_boxes():
    assert [str(w) for w in M.WINDOWS] == ["2025-10-06", "2025-11-17", "2025-12-29", "2026-02-09", "2026-03-23",
                                          "2026-05-04", "2026-06-15", "2026-07-27", "2026-09-07"]
    assert M.in_box(np.array([27.0]), np.array([52.0]), M.BOX["Persian Gulf"])[0]
    assert not M.in_box(np.array([-25.0]), np.array([-20.0]), M.JUDGED_CONTROLS["Central Pacific"])[0]
    assert set(M.SAA_CONTROLS) == {"South Atlantic", "Brazil interior"}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
