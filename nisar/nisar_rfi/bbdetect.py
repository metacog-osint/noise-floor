"""Broadband detector on the processor's per-block signal power (tone-rank `signalMean`).

Tone-rank flags loud narrowband tones. A broadband noise jammer raises the whole spectrum
instead, so it shows up in `signalMean`, the block's estimated background power, not as tones.

Signature used: the cross-polarized receive channel. Natural echo comes back much weaker in HV
than in HH; thermal noise is similar in both. An outside transmitter is unrelated to the radar's
transmit polarization, so a vertical or slant-polarized source raises HV about as much as HH,
pushing the HV/HH power ratio far above what the ground produces.

Steps per pass and band (HH and HV both needed):
1. Drop degenerate blocks (signal estimate near zero).
2. Learn the frame's own relationship between HH power and the HV-HH ratio (median and robust
   spread per 1 dB HH bin). That captures echo-dominated and noise-dominated blocks alike.
3. Score each block's excess ratio E (dB) and z-score against that relationship.
4. Group blocks with z >= grow_z and E >= e_min_db into candidates (8-connected); keep those
   with a seed block at z >= seed_z.
5. Locate each candidate at the centroid of its excess HV power (HV minus what the ratio predicts
   from HH), over blocks within power_db_window of the peak, from the orbit.

Limits: no frequency information (the power is broadband over the sub-band); a horizontally
polarized emitter raises HH more than HV and is under-detected; strong natural cross-pol
scatterers can raise the ratio a little, which the z-score and E floor are there to absorb.
"""
import warnings

import numpy as np
from scipy import ndimage

from . import geoloc
from .geometry import km_between

DEFAULTS = {
    "mean_guard": 1e-3,
    "bin_db": 1.0,
    "min_bin_blocks": 30,
    "sigma_floor_db": 0.5,
    "grow_z": 3.0,
    "seed_z": 6.0,
    "e_min_db": 2.0,
    "x_min_db": -1.0,          # MEDIUM/HIGH need HV within this of HH at the peak (vegetation stays below ~-5 dB)
    "min_blocks": 3,
    "power_db_window": 6.0,
    "widespread_frac": 0.3,
    "height_m": 0.0,
}


def _relationship(p_hh, x, cfg):
    ok = np.isfinite(p_hh) & np.isfinite(x)
    if ok.sum() < 200:
        return None
    c, v = p_hh[ok], x[ok]
    lo, hi = np.floor(np.percentile(c, 0.5)), np.ceil(np.percentile(c, 99.5))
    edges = np.arange(lo, hi + cfg["bin_db"], cfg["bin_db"])
    idx = np.digitize(c, edges)
    mids, med, sd = [], [], []
    for i in range(1, len(edges)):
        vv = v[idx == i]
        if vv.size < cfg["min_bin_blocks"]:
            continue
        m = np.median(vv)
        mids.append((edges[i - 1] + edges[i]) / 2)
        med.append(m)
        sd.append(max(1.4826 * np.median(np.abs(vv - m)), cfg["sigma_floor_db"]))
    if len(mids) < 3:
        return None
    return np.array(mids), np.array(med), np.array(sd)


def score(hh, hv, cfg=None):
    """Excess HV-HH ratio E (dB), its z-score, excess HV power (linear) and the guard mask."""
    cfg = {**DEFAULTS, **(cfg or {})}
    m_hh = hh["mean"].astype(np.float64)
    m_hv = hv["mean"].astype(np.float64)
    bad = np.zeros(m_hh.shape, bool)
    for m in (m_hh, m_hv):
        pos = m[m > 0]
        med = np.median(pos) if pos.size else 0.0
        bad |= ~(m > cfg["mean_guard"] * med)
    with np.errstate(divide="ignore", invalid="ignore"):
        p_hh = np.where(bad, np.nan, 10 * np.log10(m_hh))
        p_hv = np.where(bad, np.nan, 10 * np.log10(m_hv))
    x = p_hv - p_hh
    rel = _relationship(p_hh, x, cfg)
    if rel is None:
        return None
    mids, med, sd = rel
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        exp_x = np.interp(p_hh, mids, med)
        e = x - exp_x
        z = e / np.interp(p_hh, mids, sd)
        excess = np.where(bad, np.nan, m_hv - m_hh * 10 ** (exp_x / 10))
    return {"e": e, "z": z, "excess": excess, "bad": bad, "p_hv": p_hv, "p_hh": p_hh,
            "relationship": {"hh_db": mids.round(1).tolist(), "ratio_db": med.round(2).tolist(), "sigma_db": sd.round(2).tolist()}}


def detect(tables, orbit, look="Left", cfg=None):
    """Broadband candidates per band: {"A": [cand, ...], "B": [...]}."""
    cfg = {**DEFAULTS, **(cfg or {})}
    orb = geoloc.Orbit(orbit["t"], orbit["pos"], orbit["vel"])
    out = {}
    for band in sorted({k[0] for k in tables}):
        hh, hv = tables.get((band, "HH")), tables.get((band, "HV"))
        if hh is None or hv is None or hh["mean"].shape != hv["mean"].shape:
            continue
        s = score(hh, hv, cfg)
        if s is None:
            continue
        e, z, excess = s["e"], s["z"], s["excess"]
        hot = np.nan_to_num(z, nan=-9) >= cfg["grow_z"]
        hot &= np.nan_to_num(e, nan=-9) >= cfg["e_min_db"]
        lab, _ = ndimage.label(hot, structure=np.ones((3, 3)))
        t, r = hh["t"], hh["r"]
        frame_hv = np.nanmedian(10 ** (s["p_hv"] / 10))
        cands = []
        for i, sl in enumerate(ndimage.find_objects(lab), start=1):
            m = lab == i
            nb = int(m.sum())
            if nb < cfg["min_blocks"]:
                continue
            rows, cols = np.nonzero(m)
            zc = z[rows, cols]
            if np.nanmax(zc) < cfg["seed_z"]:
                continue
            ex = excess[rows, cols]
            ok = np.isfinite(ex) & (ex > 0)
            if ok.any():
                exdb = 10 * np.log10(np.where(ok, ex, np.nan))
                top = ok & (exdb >= np.nanmax(exdb) - cfg["power_db_window"])
                w = ex[top]
                ti = float(np.sum(w * t[rows[top]]) / w.sum())
                ri = float(np.sum(w * r[cols[top]]) / w.sum())
                peak_excess_db = float(np.nanmax(exdb) - 10 * np.log10(frame_hv))
            else:
                w = np.clip(zc, 0, None) + 1e-6
                ti = float(np.sum(w * t[rows]) / w.sum())
                ri = float(np.sum(w * r[cols]) / w.sum())
                peak_excess_db = None
            lat, lon = (float(v) for v in geoloc.rdr2geo(orb, ti, ri, h=cfg["height_m"], look=look))
            tb = [t[rows.min()], t[rows.min()], t[rows.max()], t[rows.max()]]
            rb = [r[cols.min()], r[cols.max()], r[cols.max()], r[cols.min()]]
            olat, olon = geoloc.rdr2geo(orb, tb, rb, h=cfg["height_m"], look=look)
            outline = [[round(float(a), 4), round(float(b), 4)] for a, b in zip(olon, olat)]
            outline.append(outline[0])
            along = km_between(float(olat[0]), float(olon[0]), float(olat[3]), float(olon[3]))
            across = km_between(float(olat[0]), float(olon[0]), float(olat[1]), float(olon[1]))
            pe = float(np.nanmax(e[rows, cols]))
            px = float(np.nanmax((s["p_hv"] - s["p_hh"])[rows, cols]))
            widespread = nb > cfg["widespread_frac"] * hot.size
            pp = peak_excess_db if peak_excess_db is not None else -99.0
            # thresholds tuned on a 30-day, 335-pass regional set (21 Oct 2026): repeat sites carry more
            # excess power than one-offs, and forested countries with no known jamming stayed near zero
            conf = ("HIGH" if nb >= 8 and pe >= 6.0 and pp >= 8.0 else
                    "MEDIUM" if nb >= 4 and pe >= 4.0 and pp >= 5.0 else "LOW")
            if px < cfg["x_min_db"]:
                conf = "LOW"              # HV still well under HH: natural cross-pol, not an outside source
            if widespread and conf == "HIGH":
                conf = "MEDIUM"
            cands.append({
                "method": "broadband", "band": band, "lat": round(lat, 4), "lon": round(lon, 4), "outline": outline,
                "blocks": nb, "peak_ratio_excess_db": round(pe, 1), "peak_bb_z": round(float(np.nanmax(zc)), 1),
                "peak_hv_minus_hh_db": round(px, 1),
                "peak_excess_power_db": round(peak_excess_db, 1) if peak_excess_db is not None else None,
                "along_km": round(along, 1), "across_km": round(across, 1), "t_s": round(ti, 2),
                "range_km": round(ri / 1e3, 2), "widespread": bool(widespread), "confidence": conf,
                # shared fields
                "peak_z": round(float(np.nanmax(zc)), 1), "area_km2": round(along * across, 1),
                "length_km": round(max(along, across), 1), "width_km": round(min(along, across), 1),
                "aligned_with_range": False, "axis_az": None, "gnss_overlap": [], "freq_runs_mhz": [],
                "pols": ["HH", "HV"],
            })
        out[band] = sorted(cands, key=lambda c: -(c["blocks"] * c["peak_ratio_excess_db"]))
    return out
