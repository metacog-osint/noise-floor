"""Offline tests for tools/sentinel_bands.py (step X3): the per-band index on a synthetic unit-day, the drop ratio and
its bootstrap, and the fixed readings. Synthetic data only. Run as a plain script: python tests/test_sentinel_bands.py
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import sentinel_bands as X  # noqa: E402


def synthetic_unit(n=120, drop_band="s5q", drop_db=5.0, lo=40, hi=70):
    """One unit-day: 8 GPS and 8 Galileo links per 10 s epoch; L2C on 6 GPS satellites, E5a on all Galileo ones.

    Epochs lo..hi-1 sit in cell 'B' (all others in 'A') and drop_band is drop_db weaker there."""
    rng = np.random.default_rng(3)
    t, sat, el, s1c, s2l, s5q, s1w, s2w = [], [], [], [], [], [], [], []
    for k in range(n):
        for j in range(8):
            for sysc in "GE":
                e = 15.0 + 8.0 * j
                base = 40.0 + 0.2 * e
                t.append(k * 10.0); sat.append(f"{sysc}{j + 1:02d}"); el.append(e)
                s1c.append(base + rng.normal(0, 0.2))
                s2l.append(base - 3 + rng.normal(0, 0.2) if sysc == "G" and j < 6 else np.nan)
                s5q.append(base + 2 + rng.normal(0, 0.2) if sysc == "E" else np.nan)
                s1w.append(np.nan); s2w.append(np.nan)
    rows = {"t": np.array(t), "sat": np.array(sat), "el": np.array(el), "s1c": np.array(s1c), "s2l": np.array(s2l),
            "s5q": np.array(s5q), "s1w": np.array(s1w), "s2w": np.array(s2w)}
    k_of_row = (rows["t"] / 10).astype(int)
    hit = (k_of_row >= lo) & (k_of_row < hi)
    rows[drop_band] = np.where(hit, rows[drop_band] - drop_db, rows[drop_band])
    cell = np.where((np.arange(n) >= lo) & (np.arange(n) < hi), "B", "A").astype(object)
    ep = {"t": (np.arange(n) * 10).astype(np.int32), "lat": np.zeros(n, np.float32), "lon": np.zeros(n, np.float32),
          "cell": cell, "present": np.ones(n, bool)}
    return rows, ep


def test_unit_bands_lower_band_only():
    rows, ep = synthetic_unit()
    out = X.unit_bands("2026-01-01", "S2C", rows, ep)
    inside = slice(40, 70)
    outside = np.r_[0:40, 70:120]
    assert np.nanmedian(out["d_e5a"][inside]) < -4.5, np.nanmedian(out["d_e5a"][inside])
    assert abs(np.nanmedian(out["d_e5a"][outside])) < 0.2
    for s in ("l1", "l1p", "l2c", "e1", "e1p"):                    # only E5a was hit
        assert abs(np.nanmedian(out[f"d_{s}"][inside])) < 0.3, (s, np.nanmedian(out[f"d_{s}"][inside]))
    assert int(np.median(out["n_l1"])) == 8 and int(np.median(out["n_l1p"])) == 6 and int(np.median(out["n_l2c"])) == 6
    assert int(np.median(out["n_e5a"])) == 8 and int(np.median(out["n_e1p"])) == 8


def test_unit_bands_paired_links():
    rows, ep = synthetic_unit(drop_band="s1c", drop_db=4.0)
    out = X.unit_bands("2026-01-01", "S1C", rows, ep)
    inside = slice(40, 70)
    for s in ("l1", "l1p", "e1", "e1p"):
        assert np.nanmedian(out[f"d_{s}"][inside]) < -3.5, s
    assert abs(np.nanmedian(out["d_l2c"][inside])) < 0.3 and abs(np.nanmedian(out["d_e5a"][inside])) < 0.3


def test_unit_bands_grid_mismatch():
    rows, ep = synthetic_unit()
    ep["t"] = ep["t"] + 4
    try:
        X.unit_bands("2026-01-01", "S2C", rows, ep)
        raise AssertionError("a shifted grid was accepted")
    except ValueError:
        pass


def test_ratio_and_bootstrap():
    rng = np.random.default_rng(0)
    kh, kl = rng.normal(0, 0.3, 400), rng.normal(0, 0.3, 400)
    jh = rng.normal(-3.0, 0.5, 60)
    jl = 0.5 * jh + rng.normal(0, 0.1, 60)                  # the lower band drops half as far
    r, lo, hi, dl, dh = X.ratio(jl, kl, jh, kh, rng=np.random.default_rng(1), boot=500)
    assert 0.4 < r < 0.6 and lo < r < hi and 0.3 < lo and hi < 0.7, (r, lo, hi)
    assert dh < -2.5 and -2.0 < dl < -1.0
    assert X.ratio([], kl, [], kh)[0] is None
    # Same inputs, same seed, same interval
    a = X.ratio(jl, kl, jh, kh, rng=np.random.default_rng(1), boot=200)
    b = X.ratio(jl, kl, jh, kh, rng=np.random.default_rng(1), boot=200)
    assert a == b


def test_readings():
    assert X.reading(0.1) == "mostly L1" and X.reading(0.5) == "partial" and X.reading(0.9) == "wideband"
    assert X.reading(0.33) == "partial" and X.reading(0.67) == "partial"
    assert X.reading(None) is None and X.reading(float("nan")) is None
    assert X.interval_reading(0.2, 0.25) == "mostly L1"
    assert X.interval_reading(0.6, 0.8) == "partial to wideband"
    assert X.interval_reading(0.1, 0.9) == "mostly L1 to wideband"


def test_frozen_constants():
    assert X.MARKS == {"X3-1": ("e5a", 0.75, 0.65), "X3-2": ("l2c", 0.75, 0.65)}
    assert (X.READ_LOW, X.READ_HIGH, X.BOOT, X.SEED, X.MIN_BOX_JAMMED) == (0.33, 0.67, 2000, 1, 10)
    assert X.PAIRS == {"E5a / E1 paired": ("e5a", "e1p"), "L2C / L1 paired": ("l2c", "l1p")}


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
        except Exception as ex:          # report every failure, then exit non-zero
            failed += 1
            print(f"FAIL {fn.__name__}: {type(ex).__name__}: {ex}")
    if failed:
        sys.exit(f"test_sentinel_bands: {failed} of {len(tests)} failed")
    print(f"test_sentinel_bands: ok ({len(tests)} tests)")


if __name__ == "__main__":
    main()
