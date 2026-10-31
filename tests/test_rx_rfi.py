"""Offline tests for tools/rx_rfi.py (receiver signal-strength interference index). No network, no data/ files."""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import rx_rfi as R  # noqa: E402


def synthetic(drop=(400, 460), drop_db=6.0, seed=3):
    """Two receivers, eight links each, 1,000 epochs; strength rises with elevation; receiver A loses drop_db on every
    link during `drop` (a jammer raising its noise floor)."""
    rng = np.random.default_rng(seed)
    t, rx, sat, el, s = [], [], [], [], []
    for r in ("A", "B"):
        for k in range(8):
            e = 10 + 70 * np.abs(np.sin(np.linspace(0, np.pi, 1000) + k))       # 10-80 deg
            v = 30 + 0.25 * e + rng.normal(0, 0.5, 1000)
            if r == "A":
                v[drop[0]:drop[1]] -= drop_db
            t.append(np.arange(1000))
            rx.append(np.full(1000, r))
            sat.append(np.full(1000, f"G{k:02d}"))
            el.append(e)
            s.append(v)
    return (np.concatenate(t), np.concatenate(rx), np.concatenate(sat), np.concatenate(el), np.concatenate(s))


def test_baseline_tracks_elevation():
    t, rx, sat, el, s = synthetic(drop_db=0.0)
    base = R.baseline(rx, el, s)
    lo, hi = base[("A", 2)], base[("A", 15)]                 # 10-15 deg and 75-80 deg bins
    assert 32 < lo < 35 and 48 < hi < 51, (lo, hi)


def test_epoch_index_finds_the_drop():
    t, rx, sat, el, s = synthetic()
    ep = R.epoch_index(t, rx, sat, el, s)
    a = ep["rx"] == "A"
    inside = a & (ep["t"] >= 400) & (ep["t"] < 460)
    outside = a & ((ep["t"] < 380) | (ep["t"] >= 480))
    assert np.all(ep["n"] == 8)
    assert abs(np.median(ep["idx"][inside]) + 6.0) < 0.6, np.median(ep["idx"][inside])
    assert abs(np.median(ep["idx"][outside])) < 0.3
    assert np.all(ep["down"][inside] >= 0.75) and np.mean(ep["down"][outside]) < 0.05
    b = ep["rx"] == "B"                                      # the other receiver is unaffected
    assert np.all(np.abs(ep["idx"][b]) < 1.5)


def test_min_links_and_mask():
    t, rx, sat, el, s = synthetic(drop_db=0.0)
    keep = sat < "G03"                                       # three links only
    ep = R.epoch_index(t[keep], rx[keep], sat[keep], el[keep], s[keep])
    assert len(ep["t"]) == 0
    el2 = el.copy()
    el2[:] = 5.0                                             # everything below the 10 deg mask
    assert len(R.epoch_index(t, rx, sat, el2, s)["t"]) == 0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
