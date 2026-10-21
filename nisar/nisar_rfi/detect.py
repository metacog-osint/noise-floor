"""Find and grade RFI blobs in coarse GCOV grids.

Signature: an emitter inside NISAR's receive band adds noise-like, unpolarized
power, which lands equally in co-pol (HH) and cross-pol (HV). Where it is strong,
HV/HH climbs above what natural surfaces with the same HH level produce.

1. Candidates. Learn the scene's own HH -> HV/HH relationship (median and spread per
   1 dB HH bin), score each cell's cross-pol excess as a z-score, smooth along the
   radar range direction (interference streaks run cross-track), and keep connected
   regions that clear a hysteresis threshold.

2. Evidence. Natural ground looks the same to both NISAR sub-bands; interference is
   band-specific unless it is wideband. Each candidate is checked against:
     - band specificity: is the excess absent in the other sub-band at the same cells?
     - shape: is it a streak along the range direction?
     - change since the previous pass of the same frame: did HH and HV rise by about
       the same linear power (unpolarized, RFI-like) or in the surface's natural ratio
       (wetness, wind, vegetation)?
   Points add up to a confidence; candidates with no supporting evidence are dropped.

No history is required, so an emitter that is always on is found on the first pass.
"""
import math

import numpy as np
from scipy import ndimage
from scipy.spatial import ConvexHull

from . import geometry as geo

DEFAULTS = {
    "bin_db": 1.0,          # HH bin width for the scene relationship
    "min_bin_cells": 40,
    "sigma_floor_db": 0.6,
    "line_km": 4.5,         # length of the along-range smoothing line
    "seed_z": 5.0,          # a candidate must contain a cell at least this anomalous
    "grow_z": 2.0,          # smoothed (line-mean) score that defines the candidate's extent
    "min_cells": 4,
    "min_excess_db": 1.5,   # candidate mean cross-pol excess over the scene relationship
    "aligned_deg": 30.0,    # PCA axis within this of the range direction = streak-shaped
    "other_band_quiet_db": 0.6,   # other sub-band mean excess below this = band-specific
    "unpol_k": 0.5,         # dHV/dHH (linear) at or above this = unpolarized change
    "natural_k": 0.35,      # at or below this (with a real HH rise) = natural change
}


def _scene_relationship(co, ratio, cfg):
    """Median and robust spread of HV/HH per HH bin."""
    ok = np.isfinite(co) & np.isfinite(ratio)
    c, r = co[ok], ratio[ok]
    if c.size < 200:
        return None
    lo, hi = np.floor(np.percentile(c, 0.5)), np.ceil(np.percentile(c, 99.5))
    edges = np.arange(lo, hi + cfg["bin_db"], cfg["bin_db"])
    mids, mu, sd = [], [], []
    idx = np.digitize(c, edges)
    for i in range(1, len(edges)):
        v = r[idx == i]
        if v.size < cfg["min_bin_cells"]:
            continue
        med = np.median(v)
        mids.append((edges[i - 1] + edges[i]) / 2)
        mu.append(med)
        sd.append(max(1.4826 * np.median(np.abs(v - med)), cfg["sigma_floor_db"]))
    if len(mids) < 3:
        return None
    return np.array(mids), np.array(mu), np.array(sd)


def _line_kernel(length_cells, angle_from_grid_north):
    """Normalized line kernel in (row, col) space; rows run south."""
    n = int(length_cells) | 1
    k = np.zeros((n, n), np.float32)
    c = n // 2
    a = math.radians(angle_from_grid_north)
    dc, dr = math.sin(a), -math.cos(a)
    for t in np.linspace(-c, c, 4 * n):
        r, q = c + t * dr, c + t * dc
        r0, q0 = int(math.floor(r)), int(math.floor(q))
        fr, fq = r - r0, q - q0
        for rr, qq, w in ((r0, q0, (1 - fr) * (1 - fq)), (r0 + 1, q0, fr * (1 - fq)),
                          (r0, q0 + 1, (1 - fr) * fq), (r0 + 1, q0 + 1, fr * fq)):
            if 0 <= rr < n and 0 <= qq < n:
                k[rr, qq] += w
    return k / k.sum()


def _nanconv(a, k):
    ok = np.isfinite(a)
    num = ndimage.convolve(np.where(ok, a, 0), k, mode="constant")
    den = ndimage.convolve(ok.astype(np.float32), k, mode="constant")
    with np.errstate(invalid="ignore", divide="ignore"):
        out = num / den
    out[den < 0.3] = np.nan
    return out


def score_grid(grid, direction, cfg=None):
    """Cross-pol excess z-score map, smoothed along range. Adds keys to grid."""
    cfg = {**DEFAULTS, **(cfg or {})}
    co, cx = grid["co_db"], grid["cx_db"]
    ratio = cx - co
    rel = _scene_relationship(co, ratio, cfg)
    if rel is None:
        return None
    mids, mu, sd = rel
    excess = ratio - np.interp(co, mids, mu)
    z = excess / np.interp(co, mids, sd)
    lat, lon = geo.grid_center_ll(grid)
    true_az = geo.range_line_azimuth(lat, direction)
    gaz = geo.grid_angle(lat, lon, true_az, grid["epsg"])
    k = _line_kernel(max(3, round(cfg["line_km"] / (abs(grid["dx"]) / 1000))), gaz)
    grid.update(excess_db=excess, z=z, z_smooth=_nanconv(z, k), range_az_true=true_az, range_az_grid=gaz,
                relationship={"hh_db": mids.round(2).tolist(), "ratio_db": mu.round(2).tolist(),
                              "sigma_db": sd.round(2).tolist()})
    return grid


def _axis(xs, ys, w):
    """Weighted PCA of cell positions: (angle from grid north in [0,180), major km, minor km)."""
    w = w / w.sum()
    mx, my = (w * xs).sum(), (w * ys).sum()
    cov = np.cov(np.vstack([xs - mx, ys - my]), aweights=w) if len(xs) > 2 else np.eye(2)
    vals, vecs = np.linalg.eigh(cov)
    major = vecs[:, 1]
    ang = math.degrees(math.atan2(major[0], major[1])) % 180
    return ang, 4 * math.sqrt(max(vals[1], 0)) / 1000, 4 * math.sqrt(max(vals[0], 0)) / 1000


def find_blobs(grid, cfg=None):
    """Candidate regions. Each carries its cell coordinates (`_xy`) for the evidence checks."""
    cfg = {**DEFAULTS, **(cfg or {})}
    z, zs, ex = grid["z"], grid["z_smooth"], grid["excess_db"]
    grow = ndimage.binary_closing(np.nan_to_num(zs, nan=-9) >= cfg["grow_z"], structure=np.ones((3, 3)))
    lab, n = ndimage.label(grow, structure=np.ones((3, 3)))
    if n == 0:
        return []
    seeds = np.nan_to_num(z, nan=-9) >= cfg["seed_z"]
    epsg, dx, dy = grid["epsg"], grid["dx"], grid["dy"]
    cell_area = abs(dx * dy) / 1e6
    blobs = []
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        m = lab[sl] == i
        if m.sum() < cfg["min_cells"] or not (seeds[sl] & m).any():
            continue
        rows, cols = np.nonzero(m)
        rows, cols = rows + sl[0].start, cols + sl[1].start
        e = ex[rows, cols]
        if np.nanmean(e) < cfg["min_excess_db"]:
            continue
        xs, ys = geo.cell_to_xy(grid, rows, cols)
        w = np.clip(10 ** (np.nan_to_num(e) / 10) - 1, 1e-3, None)
        cxw, cyw = float((w * xs).sum() / w.sum()), float((w * ys).sum() / w.sum())
        clat, clon = geo.xy_to_ll(epsg, cxw, cyw)
        gang, major_km, minor_km = _axis(xs.astype(float), ys.astype(float), w)
        a = math.radians(gang)
        la2, lo2 = geo.xy_to_ll(epsg, cxw + 1000 * math.sin(a), cyw + 1000 * math.cos(a))
        axis_true = geo.GEOD.inv(clon, clat, lo2, la2)[0] % 180
        elong = major_km / max(minor_km, abs(dx) / 1000)
        off = abs((axis_true - grid["range_az_true"] + 90) % 180 - 90)
        hx = np.concatenate([xs + s * dx / 2 for s in (-1, 1, 1, -1)])
        hy = np.concatenate([ys + s * dy / 2 for s in (-1, -1, 1, 1)])
        pts = np.column_stack([hx, hy])
        try:
            hull = pts[ConvexHull(pts).vertices]
        except Exception:
            hull = pts[:4]
        hlat, hlon = geo.xy_to_ll(epsg, hull[:, 0], hull[:, 1])
        outline = [[round(float(o), 4), round(float(t), 4)] for o, t in zip(hlon, hlat)]
        outline.append(outline[0])
        blobs.append({
            "band": grid["freq"],
            "lat": round(clat, 4), "lon": round(clon, 4), "outline": outline,
            "axis_az": round(axis_true, 1), "range_az": round(grid["range_az_true"], 1),
            "aligned_with_range": bool(elong >= 1.5 and off <= cfg["aligned_deg"]),
            "length_km": round(major_km, 1), "width_km": round(minor_km, 1),
            "area_km2": round(len(rows) * cell_area, 1), "cells": int(len(rows)),
            "peak_z": round(float(np.nanmax(z[rows, cols])), 1),
            "mean_z": round(float(np.nanmean(z[rows, cols])), 1),
            "peak_excess_db": round(float(np.nanmax(e)), 1), "mean_excess_db": round(float(np.nanmean(e)), 1),
            "_xy": (xs, ys),
        })
    blobs.sort(key=lambda b: -b["peak_z"])
    return blobs


def _sample(grid, key, xs, ys):
    """Values of grid[key] at map coordinates (nearest cell); NaN outside."""
    c = np.rint((np.asarray(xs) - grid["x0"]) / grid["dx"]).astype(int)
    r = np.rint((np.asarray(ys) - grid["y0"]) / grid["dy"]).astype(int)
    a = grid[key]
    ok = (r >= 0) & (r < a.shape[0]) & (c >= 0) & (c < a.shape[1])
    out = np.full(len(c), np.nan, np.float32)
    out[ok] = a[r[ok], c[ok]]
    return out


def evaluate(blob, grids, prev=None, cfg=None):
    """Attach evidence and a confidence to a candidate. Returns False to drop it."""
    cfg = {**DEFAULTS, **(cfg or {})}
    xs, ys = blob["_xy"]
    pts, why = 0, []
    if blob["peak_z"] >= 8:
        pts += 2; why.append("strong anomaly")
    elif blob["peak_z"] >= 6:
        pts += 1; why.append("clear anomaly")
    if blob["peak_excess_db"] >= cfg.get("very_strong_db", 8.0):
        pts += 1; why.append("cross-pol excess beyond natural range")
    # band specificity
    other = [g for f, g in grids.items() if f != blob["band"] and "excess_db" in g]
    blob["other_band_excess_db"] = None
    if other:
        oe = _sample(other[0], "excess_db", xs, ys)
        if np.isfinite(oe).mean() >= 0.5:
            v = float(np.nanmean(oe))
            blob["other_band_excess_db"] = round(v, 1)
            if v < cfg["other_band_quiet_db"]:
                pts += 2; why.append(f"absent in band {other[0]['freq']}")
            elif abs(v - blob["mean_excess_db"]) < 1.5 and blob["peak_excess_db"] < cfg.get("very_strong_db", 8.0):
                pts -= 2; why.append("same in both bands (ground-like)")
            else:
                why.append(f"also in band {other[0]['freq']} (wideband)")
    if blob["aligned_with_range"]:
        pts += 1; why.append("streak along range")
    # change since the previous pass of this frame
    blob["change"], blob["k_temporal"] = None, None
    g = grids[blob["band"]]
    if prev is not None and prev.get("epsg") == g["epsg"] and abs(prev["dx"] - g["dx"]) < 1:
        hh0 = 10 ** (_sample(prev, "co_db", xs, ys) / 10)
        hv0 = 10 ** (_sample(prev, "cx_db", xs, ys) / 10)
        hh1 = 10 ** (_sample(g, "co_db", xs, ys) / 10)
        hv1 = 10 ** (_sample(g, "cx_db", xs, ys) / 10)
        ok = np.isfinite(hh0) & np.isfinite(hv0) & np.isfinite(hh1) & np.isfinite(hv1)
        if ok.mean() >= 0.5:
            dhh, dhv = float((hh1 - hh0)[ok].sum()), float((hv1 - hv0)[ok].sum())
            base_hv = float(hv0[ok].sum())
            if dhv > 0.5 * base_hv:                         # HV clearly rose since last pass
                k = dhv / dhh if dhh > 0 else 9.9
                blob["k_temporal"] = round(min(k, 9.9), 2)
                if k >= cfg["unpol_k"]:
                    blob["change"] = "unpolarized"; pts += 2; why.append("new since last pass, unpolarized")
                elif k <= cfg["natural_k"]:
                    blob["change"] = "natural"; pts -= 3; why.append("change looks natural")
            elif abs(dhv) <= 0.5 * base_hv:
                blob["change"] = "none"; why.append("present on the last pass too")
    blob["evidence"] = why
    blob["score"] = pts
    if pts <= 0:
        return False
    blob["confidence"] = "HIGH" if pts >= 4 else "MEDIUM" if pts >= 2 else "LOW"
    return True


def baseline_grid(grid):
    """The parts of a grid worth keeping for next pass's change check (float16)."""
    return {k: grid[k] for k in ("epsg", "x0", "y0", "dx", "dy", "freq")} | {
        "co_db": grid["co_db"].astype(np.float16), "cx_db": grid["cx_db"].astype(np.float16)}
