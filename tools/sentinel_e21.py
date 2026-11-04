#!/usr/bin/env python3
"""sentinel_e21.py: step E2.1 (regional signal load) exactly as pre-registered in docs/validation/sentinel-gnss-e21.md
section 1 (committed 1 Nov 2026, 02:40 UTC). Run on the held-out windows of section 1.2.

Commands
  day DAY...   per unit and grid epoch (the E2 grid): L, the sum of sin(elevation) over the regional satellites above
               10 deg in the spacecraft frame; L_incl, its inclined-satellite part; the E2 index D, recomputed so that
               the cells E2's final pass leaves out of its baseline are known (and checked equal to the epoch file);
               the unit-day slope beta from least squares of D on L outside those cells; and D' = D - beta * L
               -> data/sentinel_gnss/e21/<day>.parquet (needs the day's E1 table, E2 epoch file and broadcast file)
  checks       the eight held-out windows: checks 1-5 for D' with their marks, the same quantities for D, and the
               descriptive results -> data/sentinel_gnss/e21_results.json

Implementation choices for points section 1 leaves open, fixed before any held-out result was seen:
  * Regional satellites: BeiDou records with semi-major axis above 36,000 km and health 0; every QZSS record; every
    SBAS record. SBAS and QZSS count whatever their health value, because those fields describe service or signal
    availability, not transmission (SBAS 31 or 63 = not for ranging; QZSS 1 or 16 = signal bits), and the section-0
    exploration counted every SBAS satellite. Nearest record within 4 h; SBAS positions are propagated from the record
    with its velocity and acceleration.
  * Inclined part of L: BeiDou satellites at 20 deg inclination or more (inclined geosynchronous) and QZSS satellites
    at 20 deg or more (quasi-zenith).
  * Fit: ordinary least squares with an intercept over the unit-day's scored epochs (present, D finite) whose cell is
    not among the cells E2's third pass left out of its baseline (those found after pass 2). beta = 0 when fewer than
    100 epochs qualify or L's standard deviation over them is under 0.05.
  * Check 1 uses 20-degree longitude bins from -180 deg with at least 100 epochs.
"""
import argparse
import datetime as dt
import gzip
import json
import math
import os
import subprocess
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import sentinel_gnss as SG  # noqa: E402
import sentinel_rfi as SR  # noqa: E402

E21_DIR = os.path.join(SG.DATA, "e21")
RESULTS = os.path.join(SG.DATA, "e21_results.json")
MIN_EL_LOAD = 10.0
MAX_AGE_S = 4 * 3600.0
GEOSYNC_SQRTA = 6000.0          # sqrt(36,000 km) in sqrt(m)
INCLINED_DEG = 20.0
FIT_MIN, FIT_MIN_STD = 100, 0.05
WINDOWS = [dt.date(2025, 10, 27) + dt.timedelta(weeks=6 * k) for k in range(8)]
QUIET_BAND = (-45.0, -10.0)
PLACE = (-45.0, -10.0, 90.0, 130.0)
BANDS = {"0-20N": (0.0, 20.0), "10-45S": (-45.0, -10.0), "45-62S": (-62.0, -45.0)}
BIN_MIN = 100
MARKS = {1: (0.50, 0.80), 4: (0.02, 0.05), 5: (0.05, 0.10)}      # "le" checks: holds if <= first, fails if > second


# ---------------------------------------------------------------------------------------------- regional satellites

def parse_sbas(text):
    """SBAS records of a RINEX 3 navigation file -> {sat: [{'t' GPS s, 'pos', 'vel', 'acc' (m, m/s, m/s^2), 'health'}]}."""
    import station_bands as B
    out = {}
    for rec in B._records(text):
        if rec[0][0] != "S" or len(rec) < 4:
            continue
        line = rec[0]
        y, mo, d, h, mi, s = (int(line[4:8]), int(line[9:11]), int(line[12:14]), int(line[15:17]), int(line[18:20]),
                              int(float(line[21:23])))
        t = _gps_seconds(y, mo, d, h, mi, s)          # RINEX 3 SBAS epochs are GPS time
        f = [[_f(r[4 + 19 * k:23 + 19 * k]) for k in range(4)] for r in rec[1:4]]
        pos = [f[0][0] * 1e3, f[1][0] * 1e3, f[2][0] * 1e3]
        if not 4.0e7 < math.sqrt(sum(p * p for p in pos)) < 4.4e7:
            continue
        out.setdefault(rec[0][:3].replace(" ", "0"), []).append({
            "t": t, "pos": pos, "vel": [f[0][1] * 1e3, f[1][1] * 1e3, f[2][1] * 1e3],
            "acc": [f[0][2] * 1e3, f[1][2] * 1e3, f[2][2] * 1e3], "health": f[0][3]})
    return out


def _f(s):
    s = s.strip().replace("D", "E").replace("d", "e")
    return float(s) if s else 0.0


def _gps_seconds(y, mo, d, h, mi, s):
    return (dt.datetime(y, mo, d, h, mi, s, tzinfo=dt.timezone.utc)
            - dt.datetime(1980, 1, 6, tzinfo=dt.timezone.utc)).total_seconds()


def regional_records(text):
    """(kepler {sat: [record]}, kinds {sat: kind}, sbas {sat: [record]}) for the regional satellites of one day.

    kinds: 'bds_geo', 'bds_igso', 'qzss_geo', 'qzss_incl', 'sbas'."""
    import station_bands as B
    kep, _ = B.parse_nav_all(text)
    keep, kinds = {}, {}
    for sat, recs in kep.items():
        if sat[0] == "C":
            recs = [r for r in recs if r["sqrta"] > GEOSYNC_SQRTA and r["health"] == 0]
        elif sat[0] != "J":
            continue
        if not recs:
            continue
        keep[sat] = recs
        incl = math.degrees(recs[0]["i0"]) >= INCLINED_DEG
        kinds[sat] = ("bds_" if sat[0] == "C" else "qzss_") + (("igso" if sat[0] == "C" else "incl") if incl else "geo")
    sbas = parse_sbas(text)
    kinds.update({s: "sbas" for s in sbas})
    return keep, kinds, sbas


def regional_positions(kep, sbas, t_abs, max_age=MAX_AGE_S):
    """{sat: Earth-fixed positions (N, 3)} at GPS seconds t_abs; NaN where no record lies within max_age."""
    import station_bands as B
    t_abs = np.asarray(t_abs, float)
    out = {}
    for sat, recs in kep.items():
        toe = np.array([r["toe_abs"] for r in recs])
        pick = np.argmin(np.abs(t_abs[:, None] - toe[None, :]), axis=1)
        xyz = np.full((len(t_abs), 3), np.nan)
        for k in np.unique(pick):
            m = (pick == k) & (np.abs(t_abs - toe[k]) <= max_age)
            if m.any():
                xyz[m] = B.kep_xyz(recs[k], t_abs[m])
        out[sat] = xyz
    for sat, recs in sbas.items():
        tr = np.array([r["t"] for r in recs])
        pick = np.argmin(np.abs(t_abs[:, None] - tr[None, :]), axis=1)
        dtk = t_abs - tr[pick]
        p0 = np.array([recs[k]["pos"] for k in pick])
        v0 = np.array([recs[k]["vel"] for k in pick])
        a0 = np.array([recs[k]["acc"] for k in pick])
        xyz = p0 + v0 * dtk[:, None] + 0.5 * a0 * dtk[:, None] ** 2
        xyz[np.abs(dtk) > max_age] = np.nan
        out[sat] = xyz
    return out


def load(pos, up, fwd, right, positions, kinds, min_el=MIN_EL_LOAD):
    """(L, L_incl) per row: sum of sin(elevation) over the regional satellites at min_el or more."""
    n = len(pos)
    L, Li = np.zeros(n), np.zeros(n)
    for sat, xyz in positions.items():
        el, _ = SG.look(pos, up, fwd, right, xyz)
        el = np.nan_to_num(el, nan=-90.0)
        s = np.where(el >= min_el, np.sin(np.radians(el)), 0.0)
        L += s
        if kinds.get(sat) in ("bds_igso", "qzss_incl"):
            Li += s
    return L, Li


# ---------------------------------------------------------------------------------------------- D, hot cells, fit

def index_with_hot(key, t, sat, el, val, cell_of_row, passes=SR.BASE_PASSES, hot_db=SR.HOT_DB):
    """sentinel_rfi.index_signal, unchanged, also returning the cells its final pass left out of its baseline."""
    import rx_rfi as R
    t, el, val = np.asarray(t), np.asarray(el, float), np.asarray(val, float)
    rx = np.full(len(t), key, dtype=object)
    hot = np.zeros(len(t), bool)
    hot_used = set()
    cell_of_row = np.asarray(cell_of_row, dtype=object)
    first_row = {}
    for i, tt in enumerate(t):
        first_row.setdefault(tt, i)
    ei, hot_cells = None, set()
    for _ in range(passes):
        hot_used = hot_cells
        base = R.baseline(rx[~hot], el[~hot], val[~hot], binw=SR.BINW, min_el=SR.MIN_EL, min_n=1)
        ei = R.epoch_index(t, rx, sat, el, val, base=base, binw=SR.BINW, min_el=SR.MIN_EL, min_links=SR.MIN_LINKS)
        if not len(ei["t"]):
            break
        ecell = np.array([cell_of_row[first_row[x]] for x in ei["t"]], dtype=object)
        hot_cells = {c for c in np.unique(ecell) if c and np.median(ei["idx"][ecell == c]) <= hot_db}
        hot = np.isin(cell_of_row, list(hot_cells)) if hot_cells else np.zeros(len(t), bool)
    return ei, set(hot_used)


def fit_beta(D, L, ok):
    """Least squares of D on L (with intercept) over rows ok. Returns (beta, intercept, n); beta 0 when undefined."""
    m = np.asarray(ok, bool) & np.isfinite(D) & np.isfinite(L)
    n = int(m.sum())
    if n < FIT_MIN or np.std(L[m]) < FIT_MIN_STD:
        return 0.0, float(np.median(D[m])) if n else 0.0, n
    beta, icpt = np.polyfit(L[m], D[m], 1)
    return float(beta), float(icpt), n


def unit_day(day, unit, rows, ep, sets, kep, kinds, sbas):
    import station_cn0 as SC
    t_rows = rows["t"].astype(float)
    off = SG.grid_offset(t_rows)
    n = len(ep["t"])
    grid = (off + np.arange(n) * SG.STEP).astype(float)
    if not np.array_equal(ep["t"], grid.astype(np.int32)):
        raise ValueError(f"{day} {unit}: the E2 epoch grid doesn't match this unit's rows")
    day_unix = dt.datetime.combine(day, dt.time(), dt.timezone.utc).timestamp()
    pos, vel, _ = SG.spacecraft_ecef(sets, day_unix + grid - SG.LEAP)
    up, fwd, right = SG.frames(pos, vel)
    t_abs = SC.gps_seconds(day.isoformat()) + grid
    L, Li = load(pos, up, fwd, right, regional_positions(kep, sbas, t_abs), kinds)
    gi = np.round((t_rows - off) / SG.STEP).astype(int)
    keep = (gi >= 0) & (gi < n)
    sat = rows["sat"].astype(str)[keep]
    el = rows["el"].astype(float)[keep]
    v = rows["s1c"].astype(float)[keep]
    tt, gi = t_rows[keep], gi[keep]
    m = np.char.startswith(sat, "G") & np.isfinite(v)
    D = np.full(n, np.nan)
    hot = set()
    if m.any():
        ei, hot = index_with_hot(f"{unit}|{day}|l1", tt[m], sat[m], el[m], v[m], ep["cell"][gi[m]])
        if ei is not None and len(ei["t"]):
            D[np.round((ei["t"] - off) / SG.STEP).astype(int)] = ei["idx"]
    e2 = ep["d_l1"].astype(float)
    same = np.isfinite(D) == np.isfinite(e2)
    if not (same.all() and np.allclose(D[np.isfinite(D)], e2[np.isfinite(e2)], atol=1e-5)):
        raise ValueError(f"{day} {unit}: recomputed D differs from the E2 epoch file")
    fit_ok = ep["present"] & ~np.isin(ep["cell"], list(hot))
    beta, icpt, n_fit = fit_beta(D, L, fit_ok)
    return {"unit": np.full(n, unit), "t": ep["t"], "lat": ep["lat"], "lon": ep["lon"], "cell": ep["cell"],
            "present": ep["present"], "d": D.astype(np.float32), "dp": (D - beta * L).astype(np.float32),
            "load": L.astype(np.float32), "load_incl": Li.astype(np.float32),
            "beta": np.full(n, beta, np.float32), "n_fit": np.full(n, n_fit, np.int32),
            "hot_cells": np.full(n, len(hot), np.int16)}


def build_day(day):
    import pyarrow as pa
    import pyarrow.parquet as pq
    p = os.path.join(SG.DAYS_DIR, f"{day}.parquet")
    e = os.path.join(SR.EPOCH_DIR, f"{day}.parquet")
    if not (os.path.exists(p) and os.path.exists(e)):
        raise SystemExit(f"{day}: needs the E1 table and the E2 epoch file")
    nav = SG.held_nav(day) or SG.fetch_nav(day)
    with gzip.open(nav, "rt", encoding="ascii", errors="replace") as f:
        kep, kinds, sbas = regional_records(f.read())
    T = pq.read_table(p)
    cols = {k: np.asarray(T.column(k).to_numpy(zero_copy_only=False)) for k in T.column_names}
    units = cols["unit"].astype(str)
    E = pq.read_table(e, columns=["unit", "t", "lat", "lon", "cell", "present", "d_l1"])
    ec = {k: np.asarray(E.column(k).to_numpy(zero_copy_only=False)) for k in E.column_names}
    ec["unit"], ec["cell"] = ec["unit"].astype(str), ec["cell"].astype(str)
    store = SG.load_elements()
    parts = []
    for u in sorted(set(units)):
        em = ec["unit"] == u
        if not em.any():
            continue
        order = np.argsort(ec["t"][em], kind="stable")
        ep = {k: v[em][order] for k, v in ec.items()}
        rows = {k: v[units == u] for k, v in cols.items() if k != "unit"}
        sets = (store.get(str(SG.UNITS[u][1])) or {}).get("sets", [])
        parts.append(unit_day(day, u, rows, ep, sets, kep, kinds, sbas))
    out = {k: np.concatenate([q[k] for q in parts]) for k in parts[0]}
    os.makedirs(E21_DIR, exist_ok=True)
    tbl = pa.table({k: (pa.array(v.astype(str)).dictionary_encode() if k in ("unit", "cell") else pa.array(v))
                    for k, v in out.items()})
    path = os.path.join(E21_DIR, f"{day}.parquet")
    pq.write_table(tbl, path + ".part", compression="zstd")
    SG.replace(path + ".part", path)
    regional = {k: sum(1 for x in kinds.values() if x == k) for k in sorted(set(kinds.values()))}
    betas = {u: round(float(out["beta"][out["unit"] == u][0]), 4) for u in sorted(set(out["unit"]))}
    return path, regional, betas


# ---------------------------------------------------------------------------------------------- checks

def verdict_le(check, value):
    if value is None:
        return "not judged"
    hold, fail = MARKS[check]
    return "holds" if value <= hold else "fails" if value > fail else "weakened"


def verdict_auc(a_p, a_d, hold=0.80, fail=0.70, max_drop_hold=0.01, max_drop_fail=0.03):
    """Check 2 (and, with max_drop_hold 0.02 and no drop rule for failing, check 3)."""
    if a_p is None or a_d is None:
        return "not judged"
    if a_p < fail or (max_drop_fail is not None and a_p < a_d - max_drop_fail):
        return "fails"
    if a_p >= hold and a_p >= a_d - max_drop_hold:
        return "holds"
    return "weakened"


def lon_profile(lat, lon, v, band, binw=20.0, min_n=BIN_MIN):
    """[(bin start, median, n)] of v over 20-degree longitude bins from -180, for rows inside the latitude band."""
    m = (lat >= band[0]) & (lat <= band[1]) & np.isfinite(v)
    out = []
    for b0 in np.arange(-180.0, 180.0, binw):
        k = m & (lon >= b0) & (lon < b0 + binw)
        out.append((float(b0), float(np.median(v[k])) if k.sum() >= min_n else None, int(k.sum())))
    return out


def flatness(profile):
    vals = [x[1] for x in profile if x[1] is not None]
    return max(vals) - min(vals) if vals else None


def load_window(start):
    import pyarrow.parquet as pq
    parts, days = [], []
    for k in range(7):
        d = start + dt.timedelta(days=k)
        p = os.path.join(E21_DIR, f"{d}.parquet")
        if not os.path.exists(p):
            continue
        T = pq.read_table(p)
        c = {n: np.asarray(T.column(n).to_numpy(zero_copy_only=False)) for n in T.column_names}
        c["unit"], c["cell"] = c["unit"].astype(str), c["cell"].astype(str)
        c["day"] = np.full(len(c["t"]), k, np.int8)
        parts.append(c)
        days.append(d)
    if not parts:
        return None, days
    return {k: np.concatenate([q[k] for q in parts]) for k in parts[0]}, days


def code_hash():
    try:
        blob = subprocess.run(["git", "hash-object", os.path.relpath(__file__, ROOT)], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
        head = subprocess.run(["git", "log", "-1", "--format=%H", "--", os.path.relpath(__file__, ROOT)], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
        return {"blob": blob, "last_commit": head}
    except Exception as ex:      # reported, never fatal
        return {"error": str(ex)}


def run_checks():
    import h3
    import cygnss_checks as K
    import cygnss_rfi as C
    rows = {"dp": [], "d": []}
    ep_all = {k: [] for k in ("lat", "lon", "d", "dp", "load_incl")}
    per_window, betas = [], {}
    boxes_all = {**SR.BOX, **SR.JUDGED_CONTROLS, **SR.SAA_CONTROLS,
                 **{k: v for kind in C.BOXES.values() for k, v in kind.items() if k not in SR.BOX}}
    box_table = {}
    for w in WINDOWS:
        ep, days = load_window(w)
        ac, ac_days = SR.window_aircraft([w + dt.timedelta(days=k) for k in range(7)])
        if ep is None:
            per_window.append({"window": str(w), "epoch_days": 0})
            continue
        units_per_day = [len(set(ep["unit"][(ep["day"] == k) & ep["present"]])) for k in sorted(set(ep["day"].tolist()))]
        for (u, k), b in {(u, int(k)): float(b) for u, k, b in zip(ep["unit"], ep["day"], ep["beta"])}.items():
            betas.setdefault(u, []).append(b)
        ok = ep["present"] & np.isfinite(ep["d"])
        for k in ep_all:
            ep_all[k].append(ep[k][ok])
        for col in ("dp", "d"):
            sc = ok & np.isfinite(ep[col])
            jv = SR.judged(SR.cell_values(ep["cell"], ep["unit"], ep["day"], ep["t"], ep[col], sc))
            for c, v in jv.items():
                lat, lon = h3.cell_to_latlng(c)
                a = ac.get(c)
                share = 100.0 * a[1] / a[0] if a and a[0] >= SR.PAIR_MIN_AIRCRAFT else None
                rows[col].append({"window": str(w), "h3": c, "lat": lat, "lon": lon, "value": v, "share": share})
            for name, b in boxes_all.items():
                vs = [v for c, v in jv.items() if SR.in_box(*h3.cell_to_latlng(c), b)]
                box_table.setdefault(name, {}).setdefault(str(w), {})[col] = {
                    "cells": len(vs), "median": SR._r(np.median(vs)) if vs else None,
                    "degraded": SR._r(np.mean(np.array(vs) <= SR.DEGRADED_DB)) if vs else None}
        per_window.append({"window": str(w), "epoch_days": len(days), "aircraft_days": ac_days,
                           "units_per_day": SR._r(np.mean(units_per_day), 2) if units_per_day else 0,
                           "thin": bool(units_per_day and np.mean(units_per_day) < 4)})
    E = {k: np.concatenate(v) for k, v in ep_all.items()}

    def quantities(col):
        rs = rows[col]
        pairs = [r for r in rs if r["share"] is not None]
        jam = [r for r in pairs if r["share"] >= SR.JAM_SHARE]
        clean = [r for r in pairs if r["share"] < SR.CLEAN_SHARE]
        q = {"pairs": len(pairs), "jammed": len(jam), "clean": len(clean)}
        prof = lon_profile(E["lat"], E["lon"], E[col].astype(float), QUIET_BAND)
        q["1_flatness_db"] = SR._r(flatness(prof))
        q["1_profile"] = prof
        q["2_pooled_auc"] = SR._r(C.auc([-r["value"] for r in jam], [-r["value"] for r in clean]))
        bj = [r for r in jam if SR.in_box(r["lat"], r["lon"], SR.BOX["Baltic"])]
        q["3_baltic_auc"] = SR._r(C.auc([-r["value"] for r in bj], [-r["value"] for r in clean])) if len(bj) >= 10 else None
        q["3_baltic_jammed"] = len(bj)
        cv = [r["value"] for r in rs if any(SR.in_box(r["lat"], r["lon"], b) for b in SR.JUDGED_CONTROLS.values())]
        q["4_controls_degraded"] = SR._r(np.mean(np.array(cv) <= SR.DEGRADED_DB), 4) if cv else None
        q["4_control_cell_windows"] = len(cv)
        q["4_by_box"] = {name: SR._r(np.mean(np.array(v) <= SR.DEGRADED_DB), 4) if v else None for name, v in
                         {name: [r["value"] for r in rs if SR.in_box(r["lat"], r["lon"], b)]
                          for name, b in SR.JUDGED_CONTROLS.items()}.items()}
        pm = ((E["lat"] >= PLACE[0]) & (E["lat"] <= PLACE[1]) & (E["lon"] >= PLACE[2]) & (E["lon"] <= PLACE[3])
              & np.isfinite(E[col]) & np.isfinite(E["load_incl"]))
        x, y = E["load_incl"][pm].astype(float), E[col][pm].astype(float)
        q["5_place_r"] = SR._r(np.corrcoef(x, y)[0, 1]) if pm.sum() > 30 and x.std() > 0 and y.std() > 0 else None
        q["5_place_epochs"] = int(pm.sum())
        q["profiles"] = {b: lon_profile(E["lat"], E["lon"], E[col].astype(float), r) for b, r in BANDS.items()}
        reg = K.region_heldout([{"day": r["window"], "h3": r["h3"], "lat": r["lat"], "lon": r["lon"],
                                 "med_db": -r["value"], "share": r["share"]} for r in pairs])
        q["region_heldout_min_auc"] = reg.get("min_judged_auc_without")
        return q

    qp, qd = quantities("dp"), quantities("d")
    res = {"preregistered": "docs/validation/sentinel-gnss-e21.md section 1", "code": code_hash(),
           "run_utc": dt.datetime.now(dt.timezone.utc).isoformat()[:19] + "Z", "windows": per_window,
           "checks": {
               "1_quiet_band_flatness": {"value": qp["1_flatness_db"], "d_value": qd["1_flatness_db"],
                                         "verdict": verdict_le(1, qp["1_flatness_db"])},
               "2_pooled_auc": {"value": qp["2_pooled_auc"], "d_value": qd["2_pooled_auc"],
                                "verdict": verdict_auc(qp["2_pooled_auc"], qd["2_pooled_auc"]),
                                "jammed": qp["jammed"], "clean": qp["clean"]},
               "3_baltic_auc": {"value": qp["3_baltic_auc"], "d_value": qd["3_baltic_auc"],
                                "verdict": verdict_auc(qp["3_baltic_auc"], qd["3_baltic_auc"], max_drop_hold=0.02,
                                                       max_drop_fail=None),
                                "baltic_jammed": qp["3_baltic_jammed"]},
               "4_controls_degraded": {"value": qp["4_controls_degraded"], "d_value": qd["4_controls_degraded"],
                                       "verdict": verdict_le(4, qp["4_controls_degraded"]),
                                       "by_box": qp["4_by_box"], "d_by_box": qd["4_by_box"],
                                       "cell_windows": qp["4_control_cell_windows"]},
               "5_place_r": {"value": qp["5_place_r"], "d_value": qd["5_place_r"],
                             "verdict": verdict_le(5, None if qp["5_place_r"] is None else abs(qp["5_place_r"])),
                             "epochs": qp["5_place_epochs"]}},
           "descriptive": {
               "beta_by_unit": {u: {"median": SR._r(np.median(b), 4), "min": SR._r(min(b), 4), "max": SR._r(max(b), 4),
                                    "unit_days": len(b)} for u, b in sorted(betas.items())},
               "profiles_dp": qp["profiles"], "profiles_d": qd["profiles"],
               "quiet_band_profile_dp": qp["1_profile"], "quiet_band_profile_d": qd["1_profile"],
               "region_heldout_min_auc": {"dp": qp["region_heldout_min_auc"], "d": qd["region_heldout_min_auc"]},
               "boxes": box_table}}
    return res


# ---------------------------------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("day")
    p.add_argument("days", nargs="+")
    p.add_argument("--force", action="store_true")
    sub.add_parser("checks")
    a = ap.parse_args(argv)
    if a.cmd == "day":
        for d in SG.days_arg(a.days):
            out = os.path.join(E21_DIR, f"{d}.parquet")
            if os.path.exists(out) and not a.force:
                print(f"{d} held")
                continue
            path, regional, betas = build_day(d)
            print(json.dumps({"day": str(d), "regional": regional, "beta": betas}), flush=True)
        return 0
    res = run_checks()
    with open(RESULTS, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, default=str)
    for k, v in res["checks"].items():
        print(f"  {k}: D' {v['value']} (D {v['d_value']}) -> {v['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
