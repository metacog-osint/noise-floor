"""Find emitters in the processor's per-block RFI tables (see tables.py).

1. Score each analysis block by the share of pulses hit at its most-hit frequency bin,
   ignoring the radar's own tones (present in every pass, everywhere).
2. Drop degenerate blocks (signal estimate near zero: open water edges, gaps), where the
   interference-to-signal ratio is meaningless.
3. Group hot blocks (8-connected, both polarizations pooled) into candidates.
4. For each candidate: hit-weighted centroid in (azimuth time, slant range), turned into
   latitude/longitude from the orbit; its extent; the frequency runs that were hit; and
   which GNSS signals those runs fall in.

The receive beam confines an emitter's interference to part of the swath in range, and the
azimuth beam to a few seconds along track, so one pass gives a position, not a streak.
"""
import warnings

import numpy as np
from scipy import ndimage

from . import bands, geoloc

# Tones present in >=50% of blocks in every pass we checked, in two regions
# (21 Oct 2026). Treated as the radar's own; re-check if the instrument tables change.
INSTRUMENT_TONES_MHZ = (1233.125, 1296.002)

DEFAULTS = {
    "tone_tol_mhz": 0.15,      # the tones leak into bins about 0.1 MHz either side
    "hit_min": 0.5,            # block is hot if some non-instrument bin is hit in >= half the pulses
    "min_blocks": 3,
    "mean_guard": 1e-3,        # blocks with signal mean below this x median are degenerate
    "run_min": 0.3,            # a frequency bin belongs to a candidate's signature at this mean hit share
    "height_m": 0.0,           # terrain height for geolocation
    "power_db_window": 6.0,    # locate on blocks within this of the candidate's peak RFI power
    "widespread_frac": 0.3,    # a candidate covering more of the frame than this is flagged widespread
}


def _keep_bins(f_mhz, cfg):
    keep = np.ones(f_mhz.shape, bool)
    for tone in INSTRUMENT_TONES_MHZ:
        keep &= np.abs(f_mhz - tone) > cfg["tone_tol_mhz"]
    return keep


def block_scores(d, cfg):
    """(score, peak_freq_mhz, guarded_isr, bad) per block for one channel table."""
    f = d["f"] / 1e6
    keep = _keep_bins(f, cfg)
    hits = d["hits"][:, :, keep].astype(np.float32)
    fk = f[keep]
    score = hits.max(axis=2)
    peak_f = fk[hits.argmax(axis=2)]
    mean = d["mean"].astype(np.float64)
    med = np.nanmedian(mean[mean > 0]) if np.any(mean > 0) else 0.0
    bad = ~(mean > cfg["mean_guard"] * med)
    isr = np.where(bad, np.nan, d["isr"].astype(np.float64))
    score = np.where(bad, 0.0, score)
    return score, peak_f, isr, bad


def _runs(f_mhz, prof, thr, gap=2):
    """Contiguous frequency runs where prof >= thr: [(lo, hi, peak)] sorted by peak."""
    idx = np.nonzero(prof >= thr)[0]
    if idx.size == 0:
        return []
    runs, s, p = [], idx[0], idx[0]
    for i in idx[1:]:
        if i - p > gap + 1:
            runs.append((s, p))
            s = i
        p = i
    runs.append((s, p))
    out = [(float(f_mhz[a]), float(f_mhz[b]), float(prof[a:b + 1].max())) for a, b in runs]
    return sorted(out, key=lambda x: -x[2])


def detect(tables, orbit, look="Left", cfg=None):
    """Candidates per band: {"A": [cand, ...], "B": [...]}. Each cand is a dict ready for detections."""
    cfg = {**DEFAULTS, **(cfg or {})}
    orb = geoloc.Orbit(orbit["t"], orbit["pos"], orbit["vel"])
    out = {}
    for band in sorted({k[0] for k in tables}):
        chans = {pol: d for (b, pol), d in tables.items() if b == band and d.get("hits") is not None}
        if not chans:
            continue
        ref = next(iter(chans.values()))
        shape = ref["isr"].shape
        per = {pol: block_scores(d, cfg) for pol, d in chans.items() if d["isr"].shape == shape}
        score = np.max([p[0] for p in per.values()], axis=0)
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)   # all-NaN columns are degenerate blocks
            isr = np.nanmax(np.stack([p[2] for p in per.values()]), axis=0)
            # absolute RFI power per block (ISR x signal mean): peaks where the emitter sits in the beam
            power = np.nanmax(np.stack([p[2] * chans[pol]["mean"] for pol, p in per.items()]), axis=0)
        hot = score >= cfg["hit_min"]
        lab, n = ndimage.label(hot, structure=np.ones((3, 3)))
        t, r = ref["t"], ref["r"]
        f = ref["f"] / 1e6
        keep = _keep_bins(f, cfg)
        cands = []
        for i, sl in enumerate(ndimage.find_objects(lab), start=1):
            m = lab == i
            nb = int(m.sum())
            if nb < cfg["min_blocks"]:
                continue
            rows, cols = np.nonzero(m)
            w = score[rows, cols]
            pw = power[rows, cols]
            ok = np.isfinite(pw) & (pw > 0)
            if ok.any():
                pdb = 10 * np.log10(np.where(ok, pw, np.nan))
                top = ok & (pdb >= np.nanmax(pdb) - cfg["power_db_window"])
                wl = pw[top]
                ti = float(np.sum(wl * t[rows[top]]) / wl.sum())
                ri = float(np.sum(wl * r[cols[top]]) / wl.sum())
                peak_power_db = float(np.nanmax(pdb))
            else:
                ti = float(np.sum(w * t[rows]) / w.sum())
                ri = float(np.sum(w * r[cols]) / w.sum())
                peak_power_db = None
            widespread = nb > cfg["widespread_frac"] * hot.size
            lat, lon = geoloc.rdr2geo(orb, ti, ri, h=cfg["height_m"], look=look)
            lat, lon = float(lat), float(lon)
            # outline: geolocated corners of the candidate's bounding box in radar coordinates
            tb = [t[rows.min()], t[rows.min()], t[rows.max()], t[rows.max()]]
            rb = [r[cols.min()], r[cols.max()], r[cols.max()], r[cols.min()]]
            olat, olon = geoloc.rdr2geo(orb, tb, rb, h=cfg["height_m"], look=look)
            outline = [[round(float(a), 4), round(float(b), 4)] for a, b in zip(olon, olat)]
            outline.append(outline[0])
            along = _km(olat[0], olon[0], olat[3], olon[3])
            across = _km(olat[0], olon[0], olat[1], olon[1])
            # frequency signature: mean hit share per bin over the candidate's blocks, best polarization
            prof = np.zeros(f.shape, np.float32)
            pols_hit = []
            for pol, d in chans.items():
                if d["isr"].shape != shape:
                    continue
                p = d["hits"][rows, cols, :].astype(np.float32).mean(axis=0)
                p[~keep] = 0
                prof = np.maximum(prof, p)
                if per[pol][0][rows, cols].max() >= cfg["hit_min"]:
                    pols_hit.append(pol)
            runs = _runs(f, prof, cfg["run_min"])[:4]
            gnss = []
            for lo, hi, _ in runs:
                gnss += [s for s in bands.gnss_in(lo - 0.05, hi + 0.05) if s not in gnss]
            peak_hit = float(w.max())
            peak_isr = float(np.nanmax(isr[rows, cols])) if np.isfinite(isr[rows, cols]).any() else float("nan")
            conf = ("HIGH" if nb >= 8 and peak_hit >= 0.9 and len(pols_hit) >= 2 else
                    "MEDIUM" if nb >= 4 or (len(pols_hit) >= 2 and peak_hit >= 0.7) else "LOW")
            if widespread and conf == "HIGH":
                conf = "MEDIUM"           # frame-wide interference: the position is the power peak only
            cands.append({
                "method": "tables", "band": band, "lat": round(lat, 4), "lon": round(lon, 4), "outline": outline,
                "blocks": nb, "peak_hit": round(peak_hit, 2), "peak_isr_db": round(10 * np.log10(peak_isr), 1) if peak_isr > 0 else None,
                "freq_runs_mhz": [[round(lo, 2), round(hi, 2), round(pk, 2)] for lo, hi, pk in runs],
                "gnss_overlap": gnss, "pols": sorted(pols_hit),
                "along_km": round(along, 1), "across_km": round(across, 1),
                "t_s": round(ti, 2), "range_km": round(ri / 1e3, 2), "confidence": conf,
                "peak_power_db": round(peak_power_db, 1) if peak_power_db is not None else None,
                "widespread": bool(widespread),
                # fields the site/report code shares with the image detector
                "peak_z": round(peak_hit * 10, 1), "area_km2": round(along * across, 1),
                "length_km": round(max(along, across), 1), "width_km": round(min(along, across), 1),
                "aligned_with_range": False, "axis_az": None,
            })
        out[band] = sorted(cands, key=lambda c: (-c["blocks"] * c["peak_hit"]))
    return out


def _km(la1, lo1, la2, lo2):
    from .geometry import km_between
    return km_between(float(la1), float(lo1), float(la2), float(lo2))


def describe_runs(runs):
    """'1227.4-1227.9 MHz (GPS L2)' style text for a candidate's frequency runs."""
    parts = []
    for lo, hi, _ in runs:
        sig = bands.gnss_in(lo - 0.05, hi + 0.05)
        txt = f"{lo:.1f} MHz" if hi - lo < 0.1 else f"{lo:.1f}-{hi:.1f} MHz"
        parts.append(txt + (f" ({', '.join(sig)})" if sig else ""))
    return "; ".join(parts)


def interpretation(d):
    """One line on what a table detection's frequencies are consistent with. A hint, not attribution."""
    runs = d.get("freq_runs_mhz") or []
    g = d.get("gnss_overlap") or []
    narrow = bool(runs) and all(hi - lo <= 1.0 for lo, hi, _ in runs)
    l2_centre = any(lo <= 1227.85 and hi >= 1227.35 for lo, hi, _ in runs)
    if l2_centre:
        first = "Energy at the GPS L2 centre frequency (1227.60 MHz)"
    elif g:
        first = f"Energy inside the {', '.join(g)} main lobe"
    else:
        first = "Energy outside the GNSS signals in this slice"
    shape = "narrowband tones (CW-like)" if narrow else "spread over several MHz"
    if g:
        tail = "Consistent with a GNSS jammer; an L-band radar or other emitter is also possible."
    else:
        tail = "More consistent with a radar or other L-band emitter."
    if d.get("widespread"):
        tail += " Seen across much of the frame, so the position is the interference-power peak only."
    return f"{first}, {shape}. {tail}"
