"""rx_rfi.py: an interference index from a spacecraft GNSS receiver's signal strength, on plain arrays.

A ground jammer in view raises the receiver's noise floor, so the signal-to-noise ratio of every link drops at the same
time. This module measures that. Each link's signal strength (dB) is compared with a baseline: the median, for the same
receiver and signal, of everything it logged in the same elevation bin (5 deg by default). The index for one receiver
and epoch is the median of those residuals over its links. Near 0 dB means normal; a drop of several dB on most links
means added noise.

Used by tools/s6_rfi.py (Sentinel-6A, step P of docs/space-sensors-plan.md) and the Sentinel-1/2/3 receivers of step E
(tools/sentinel_gnss.py rows). The back-projection that turns flagged epochs into a map is in tools/cosmic2_rfi.py
(`bins`, `backproject`, `corr_score`, `cells`).

Functions
  baseline(rx, el, snr_db, binw, min_el)          -> {(rx, bin): median dB}
  residuals(rx, el, snr_db, base, binw, min_el)   -> per-row residual dB (NaN where no baseline or below min_el)
  epoch_index(t, rx, sat, el, snr_db, ...)        -> per receiver and epoch: median residual, links, share of links
                                                     down by drop_db or more
"""
import numpy as np

BINW = 5.0            # deg, elevation bin of the baseline
MIN_EL = 10.0         # deg, links below this are left out (multipath, low gain)
MIN_LINKS = 4         # links an epoch needs before it gets an index
MIN_BIN_N = 30        # rows a baseline bin needs
DROP_DB = 3.0         # a link counts as "down" at this drop


def _bin(el, binw):
    return np.floor(np.asarray(el, float) / binw).astype(np.int64)


def _rx_codes(rx):
    rx = np.asarray(rx)
    u, inv = np.unique(rx, return_inverse=True)
    return u, inv


def baseline(rx, el, snr_db, binw=BINW, min_el=MIN_EL, min_n=MIN_BIN_N):
    """Median signal strength per (receiver, elevation bin), from finite rows at or above min_el."""
    el = np.asarray(el, float)
    s = np.asarray(snr_db, float)
    u, code = _rx_codes(rx)
    ok = np.isfinite(el) & np.isfinite(s) & (el >= min_el)
    key = code[ok] * 1000 + _bin(el[ok], binw)
    out = {}
    if not ok.any():
        return out
    order = np.argsort(key, kind="stable")
    k, v = key[order], s[ok][order]
    edges = np.r_[0, np.nonzero(np.diff(k))[0] + 1, len(k)]
    for a, b in zip(edges[:-1], edges[1:]):
        if b - a >= min_n:
            out[(u[k[a] // 1000], int(k[a] % 1000))] = float(np.median(v[a:b]))
    return out


def residuals(rx, el, snr_db, base, binw=BINW, min_el=MIN_EL):
    """Signal strength minus the receiver's baseline for the row's elevation bin (dB)."""
    el = np.asarray(el, float)
    s = np.asarray(snr_db, float)
    rx = np.asarray(rx)
    b = _bin(np.where(np.isfinite(el), el, -1e9), binw)
    ref = np.array([base.get((r, int(k)), np.nan) for r, k in zip(rx, b)]) if len(rx) else np.array([])
    out = s - ref
    out[~(np.isfinite(el) & (el >= min_el))] = np.nan
    return out


def epoch_index(t, rx, sat, el, snr_db, base=None, binw=BINW, min_el=MIN_EL, min_links=MIN_LINKS, drop_db=DROP_DB):
    """Index per (receiver, epoch).

    t: epoch times (any unit, equal for links of one epoch); rx: receiver id per row; sat: GNSS satellite per row
    (only used to count distinct links); el: elevation of the link in the spacecraft frame (deg); snr_db: one signal's
    strength in dB. base: a baseline from `baseline` (by default built from these rows).

    Returns a dict of arrays, one entry per receiver-epoch with at least min_links usable links:
      rx, t, idx (median residual, dB; negative = weaker than usual), n (links), down (share of links down by drop_db).
    """
    t = np.asarray(t)
    rx = np.asarray(rx)
    if base is None:
        base = baseline(rx, el, snr_db, binw, min_el)
    r = residuals(rx, el, snr_db, base, binw, min_el)
    ok = np.isfinite(r)
    u, code = _rx_codes(rx[ok])
    tt, rr = t[ok], r[ok]
    _, tcode = np.unique(tt, return_inverse=True)
    key = code.astype(np.int64) * (tcode.max() + 1 if len(tcode) else 1) + tcode
    order = np.argsort(key, kind="stable")
    k, v, ts, cs = key[order], rr[order], tt[order], code[order]
    edges = np.r_[0, np.nonzero(np.diff(k))[0] + 1, len(k)] if len(k) else np.array([0])
    out = {"rx": [], "t": [], "idx": [], "n": [], "down": []}
    for a, b in zip(edges[:-1], edges[1:]):
        if b - a < min_links:
            continue
        seg = v[a:b]
        out["rx"].append(u[cs[a]])
        out["t"].append(ts[a])
        out["idx"].append(float(np.median(seg)))
        out["n"].append(int(b - a))
        out["down"].append(float(np.mean(seg <= -drop_db)))
    return {k: np.asarray(v) for k, v in out.items()}
