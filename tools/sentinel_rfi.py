#!/usr/bin/env python3
"""sentinel_rfi.py: the Sentinel navigation-receiver interference indicator (step E2) and its pre-registered checks
(step E3), exactly as frozen in docs/validation/sentinel-gnss.md, section 1 (31 Oct 2026, 18:21 UTC).

Commands
  epochs DAY...  per unit and grid epoch (each unit's own 10 s grid): where the spacecraft was, the GPS L1 index
                 (median residual against the unit-day baseline in 5 deg bins from 10 deg, three passes keeping res-2
                 cells at <= -1 dB out of the baseline), links scored, healthy GPS satellites above 10 deg from the
                 broadcast ephemeris, SAT-JAM's flagged share, and the Galileo E1 and GPS L2 indices
                 -> data/sentinel_gnss/epochs/<day>.parquet (reads the E1 tables from tools/sentinel_gnss.py)
  checks         the nine pre-registered windows: checks 1-6 with their marks and the descriptive results
                 -> data/sentinel_gnss/e3_results.json, and a printed summary

The index itself comes from tools/rx_rfi.py (shared with step P): `baseline` with no minimum count per bin (the
pre-registration sets none) and `epoch_index` with that baseline. Aircraft labels, the AUC, boxes and the region test
come from the CYGNSS lane (tools/cygnss_rfi.py, tools/cygnss_checks.py); back-projection from tools/cosmic2_rfi.py.
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.request

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import sentinel_gnss as SG  # noqa: E402

EPOCH_DIR = os.path.join(SG.DATA, "epochs")
RESULTS = os.path.join(SG.DATA, "e3_results.json")

# ---- frozen in docs/validation/sentinel-gnss.md, section 1
RES = 2
MIN_EL, BINW, MIN_LINKS = 10.0, 5.0, 4
BASE_PASSES, HOT_DB = 3, -1.0
DEGRADED_DB = -1.0
MIN_EPOCHS, MIN_PASSES, PASS_GAP_S = 12, 2, 60
PAIR_MIN_AIRCRAFT, JAM_SHARE, CLEAN_SHARE = 140, 10.0, 2.0
WINDOWS = [dt.date(2025, 10, 6) + dt.timedelta(weeks=6 * k) for k in range(9)]
BEFORE, DURING = dt.date(2026, 2, 9), dt.date(2026, 3, 23)
GULF_WINDOWS = [dt.date(2026, 3, 23), dt.date(2026, 5, 4), dt.date(2026, 6, 15)]
PODRIX, RUAG = ("S1C", "S1D", "S2C"), ("S2B", "S3A", "S3B")
BOX = {
    "Persian Gulf": (23.5, 30.5, 47.5, 57.0),
    "Baltic": (53.5, 61.0, 17.0, 30.0),
}
JUDGED_CONTROLS = {
    "Central Pacific": (-20.0, 20.0, -160.0, -130.0),
    "Australia interior": (-32.0, -20.0, 120.0, 145.0),
    "Southern Africa interior": (-30.0, -18.0, 15.0, 30.0),
}
SAA_CONTROLS = {
    "South Atlantic": (-30.0, -10.0, -30.0, -10.0),
    "Brazil interior": (-20.0, -5.0, -60.0, -45.0),
}
KALININGRAD, GULF_CENTRE = (54.8, 20.0), (27.0, 52.25)
BP_RADII = (500.0, 1000.0, 1500.0)
MARKS = {   # check: (holds if, fails if, direction) -- "ge": higher is better; "le": lower is better
    1: (0.80, 0.70, "ge"), 2: (0.75, 0.65, "ge"), 3: (0.80, 0.70, "ge"),
    4: (-1.0, -0.5, "le"), 5: (0.02, 0.05, "le"), 6: (0.20, 0.10, "ge"),
}
VIS_MIN = 6


# ---------------------------------------------------------------------------------------------- E2: epochs

def cell_ids(lat, lon, res=RES):
    """H3 cell per point; '' where the position is unknown."""
    import cygnss_rfi as C
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    out = np.full(len(lat), "", dtype=object)
    ok = np.isfinite(lat) & np.isfinite(lon)
    if ok.any():
        out[ok] = C._cells(lat[ok], lon[ok], res)
    return out


def index_signal(key, t, sat, el, val, cell_of_row, passes=BASE_PASSES, hot_db=HOT_DB):
    """The frozen E2 index for one unit-day and signal: baseline per 5 deg bin, three passes, each leaving out the
    res-2 cells whose median epoch index is <= hot_db. Returns rx_rfi.epoch_index's dict from the last pass."""
    import rx_rfi as R
    t, el, val = np.asarray(t), np.asarray(el, float), np.asarray(val, float)
    rx = np.full(len(t), key, dtype=object)
    hot = np.zeros(len(t), bool)
    cell_of_row = np.asarray(cell_of_row, dtype=object)
    first_row = {}
    for i, tt in enumerate(t):
        first_row.setdefault(tt, i)
    ei = None
    for _ in range(passes):
        base = R.baseline(rx[~hot], el[~hot], val[~hot], binw=BINW, min_el=MIN_EL, min_n=1)
        ei = R.epoch_index(t, rx, sat, el, val, base=base, binw=BINW, min_el=MIN_EL, min_links=MIN_LINKS)
        if not len(ei["t"]):
            break
        ecell = np.array([cell_of_row[first_row[x]] for x in ei["t"]], dtype=object)
        hot_cells = {c for c in np.unique(ecell) if c and np.median(ei["idx"][ecell == c]) <= hot_db}
        hot = np.isin(cell_of_row, list(hot_cells)) if hot_cells else np.zeros(len(t), bool)
    return ei


def unit_epochs(day, unit, rows, eph, sets):
    """One unit-day: dict of per-grid-epoch arrays (see the module docstring)."""
    t_rows = rows["t"].astype(float)
    off = SG.grid_offset(t_rows)
    grid = off + np.arange(SG.NEP) * SG.STEP
    grid = grid[grid < 86400]
    day_unix = dt.datetime.combine(day, dt.time(), dt.timezone.utc).timestamp()
    pos, vel, _ = SG.spacecraft_ecef(sets, day_unix + grid - SG.LEAP)
    lat, lon, _ = SG.geodetic(pos)
    cell = cell_ids(lat, lon)
    gi = np.round((t_rows - off) / SG.STEP).astype(int)
    n = len(grid)
    present = np.zeros(n, bool)
    present[gi] = True

    # healthy GPS satellites above MIN_EL in the spacecraft frame, from the broadcast ephemeris
    import station_cn0 as SC
    up, fwd, right = SG.frames(pos, vel)
    t_abs = SC.gps_seconds(day.isoformat()) + grid
    n_vis = np.zeros(n, np.int16)
    for s in sorted(k for k in eph if k.startswith("G")):
        xyz = SG.gnss_positions(eph, np.full(n, s), t_abs)
        el, _ = SG.look(pos, up, fwd, right, xyz)
        n_vis += (np.nan_to_num(el, nan=-90.0) >= MIN_EL).astype(np.int16)

    sat = rows["sat"].astype(str)
    is_g, is_e = np.char.startswith(sat, "G"), np.char.startswith(sat, "E")
    el = rows["el"].astype(float)
    row_cell = cell[gi]
    out = {"unit": np.full(n, unit), "t": grid.astype(np.int32), "lat": lat.astype(np.float32),
           "lon": lon.astype(np.float32), "cell": cell, "present": present, "n_vis": n_vis}
    for name, m, col in (("l1", is_g, "s1c"), ("gal", is_e, "s1c"), ("l2", is_g, "s2w")):
        v = rows[col].astype(float)
        mm = m & np.isfinite(v)
        d = np.full(n, np.nan, np.float32)
        cnt = np.bincount(gi[mm & (el >= MIN_EL) & np.isfinite(el)], minlength=n).astype(np.int16)
        if mm.any():
            ei = index_signal(f"{unit}|{day}|{name}", t_rows[mm], sat[mm], el[mm], v[mm], row_cell[mm])
            if ei is not None and len(ei["t"]):
                d[np.round((ei["t"] - off) / SG.STEP).astype(int)] = ei["idx"]
        out[f"d_{name}"], out[f"n_{name}"] = d, cnt
    # SAT-JAM's indicator: z against the unit-day mean of all GPS L1 links, no elevation term; z < -1 flagged
    v = rows["s1c"].astype(float)
    mm = is_g & np.isfinite(v)
    z = (v[mm] - v[mm].mean()) / v[mm].std() if mm.sum() > 1 else np.zeros(0)
    out["sj_n"] = np.bincount(gi[mm], minlength=n).astype(np.int16)
    out["sj_flag"] = np.bincount(gi[mm], weights=(z < -1).astype(float), minlength=n).astype(np.int16)
    return out


def build_epochs(day):
    import gzip
    import pyarrow as pa
    import pyarrow.parquet as pq
    import station_cn0 as SC
    p = os.path.join(SG.DAYS_DIR, f"{day}.parquet")
    if not os.path.exists(p):
        raise SystemExit(f"{day}: no E1 table (run tools/sentinel_gnss.py day {day})")
    T = pq.read_table(p)
    cols = {k: T.column(k).to_numpy(zero_copy_only=False) for k in T.column_names}
    units = np.asarray(cols["unit"]).astype(str)
    nav = SG.held_nav(day) or SG.fetch_nav(day)
    with gzip.open(nav, "rt", encoding="ascii", errors="replace") as f:
        eph = SC.parse_nav(f.read())
    store = SG.load_elements()
    parts = []
    for u in sorted(set(units)):
        m = units == u
        rows = {k: np.asarray(v)[m] for k, v in cols.items() if k != "unit"}
        sets = (store.get(str(SG.UNITS[u][1])) or {}).get("sets", [])
        parts.append(unit_epochs(day, u, rows, eph, sets))
    out = {k: np.concatenate([q[k] for q in parts]) for k in parts[0]}
    os.makedirs(EPOCH_DIR, exist_ok=True)
    tbl = pa.table({k: (pa.array(v.astype(str)).dictionary_encode() if k in ("unit", "cell") else pa.array(v))
                    for k, v in out.items()})
    path = os.path.join(EPOCH_DIR, f"{day}.parquet")
    pq.write_table(tbl, path + ".part", compression="zstd")
    os.replace(path + ".part", path)
    return path, {u: int((out["unit"] == u).sum()) for u in sorted(set(units))}


# ---------------------------------------------------------------------------------------------- E3: windows

def in_box(lat, lon, b):
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    return (lat >= b[0]) & (lat <= b[1]) & (lon >= b[2]) & (lon <= b[3])


def load_window(start):
    import pyarrow.parquet as pq
    parts, days = [], []
    for k in range(7):
        d = start + dt.timedelta(days=k)
        p = os.path.join(EPOCH_DIR, f"{d}.parquet")
        if not os.path.exists(p):
            continue
        T = pq.read_table(p)
        c = {n: np.asarray(T.column(n).to_numpy(zero_copy_only=False)) for n in T.column_names}
        c["unit"] = c["unit"].astype(str)
        c["cell"] = c["cell"].astype(str)
        c["day"] = np.full(len(c["t"]), k, np.int8)
        parts.append(c)
        days.append(d)
    if not parts:
        return None, days
    return {k: np.concatenate([q[k] for q in parts]) for k in parts[0]}, days


def cell_values(cell, unit, day, t, value, scored):
    """Per cell: median value over scored epochs, epoch count and pass count (a pass is one unit's consecutive
    epochs on one day with no gap over PASS_GAP_S). Returns {cell: (median, n_epochs, n_passes)}."""
    m = np.asarray(scored) & (np.asarray(cell) != "")
    c, u, d, tt, v = (np.asarray(x)[m] for x in (cell, unit, day, t, value))
    if not len(c):
        return {}
    _, cc = np.unique(c, return_inverse=True)
    _, uc = np.unique(u, return_inverse=True)
    order = np.lexsort((tt, d, uc, cc))
    c, cc, uc, d, tt, v = c[order], cc[order], uc[order], d[order], tt[order], v[order]
    new = np.r_[True, (cc[1:] != cc[:-1]) | (uc[1:] != uc[:-1]) | (d[1:] != d[:-1]) | (np.diff(tt) > PASS_GAP_S)]
    edges = np.r_[np.nonzero(np.r_[True, cc[1:] != cc[:-1]])[0], len(cc)]
    out = {}
    for a, b in zip(edges[:-1], edges[1:]):
        out[c[a]] = (float(np.median(v[a:b])), int(b - a), int(new[a:b].sum()))
    return out


def judged(vals):
    return {c: v[0] for c, v in vals.items() if v[1] >= MIN_EPOCHS and v[2] >= MIN_PASSES}


def window_aircraft(days):
    """{res-2 cell: (aircraft, GPSJam-style bad)} summed over the window's aircraft days."""
    import cygnss_rfi as C
    tot, n_days = {}, 0
    for d in days:
        ac = C.aircraft(d.isoformat(), RES)
        if ac is None:
            continue
        n_days += 1
        for c, (a, b, _) in ac.items():
            o = tot.setdefault(c, [0, 0])
            o[0] += a
            o[1] += b
    return tot, n_days


def weighted_median(v, w):
    v, w = np.asarray(v, float), np.asarray(w, float)
    o = np.argsort(v)
    cw = np.cumsum(w[o])
    return float(v[o][np.searchsorted(cw, cw[-1] / 2.0)])


def window_cygnss(days):
    """{res-2 cell: CYGNSS value} for a window: the n-weighted median of the res-3 children's daily med_db; 20+ DDMs."""
    import h3
    import pyarrow.parquet as pq
    acc = {}
    for d in days:
        p = os.path.join(ROOT, "data", "cygnss", "grid", f"{d}.r3.parquet")
        if not os.path.exists(p):
            continue
        t = pq.read_table(p, columns=["h3", "n", "med_db"]).to_pydict()
        for c, n, m in zip(t["h3"], t["n"], t["med_db"]):
            if m is None or not n:
                continue
            acc.setdefault(h3.cell_to_parent(c, RES), []).append((m, n))
    return {c: weighted_median([x[0] for x in v], [x[1] for x in v]) for c, v in acc.items()
            if sum(x[1] for x in v) >= 20}


def verdict(check, value):
    if value is None:
        return "not judged"
    hold, fail, how = MARKS[check]
    if how == "ge":
        return "holds" if value >= hold else "fails" if value < fail else "weakened"
    return "holds" if value <= hold else "fails" if value > fail else "weakened"


def _r(x, n=3):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), n)


def kp_storm_days(first, last):
    """Days with a 3-hourly Kp >= 5 (GFZ Potsdam, the events lane's source)."""
    import events
    url = events.KP_URL.format(first.isoformat(), last.isoformat())
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": SG.UA}), timeout=120) as r:
        d = json.load(r)
    days = sorted({ts[:10] for ts, k in zip(d.get("datetime", []), d.get("Kp", [])) if k is not None and k >= 5.0})
    return days


def run_checks():
    import h3
    import cygnss_checks as K
    import cygnss_rfi as C
    from scipy.stats import spearmanr
    rows, per_window, cyg_pairs = [], [], []
    bp = {r: [] for r in BP_RADII}
    by_type = {"PODRIX": [], "RUAG": []}
    other = {"gal": [], "l2": []}
    sj, lowlink = [], []
    reach_k, reach_g = [], []
    ctrl_all, ctrl_gulf = [], []
    box_table = {}
    import cosmic2_rfi as B
    for w in WINDOWS:
        ep, days = load_window(w)
        all_days = [w + dt.timedelta(days=k) for k in range(7)]
        ac, ac_days = window_aircraft(all_days)
        if ep is None:
            per_window.append({"window": str(w), "epoch_days": 0})
            continue
        scored = np.isfinite(ep["d_l1"]) & ep["present"]
        vals = cell_values(ep["cell"], ep["unit"], ep["day"], ep["t"], ep["d_l1"], scored)
        jv = judged(vals)
        # per-window units
        units_per_day = [len(set(ep["unit"][ep["day"] == k][ep["present"][ep["day"] == k]]))
                         for k in sorted(set(ep["day"].tolist()))]
        # SAT-JAM share, low-link and missing shares per cell
        sjn, sjf, ll_n, ll_k, gm_n, gm_k = {}, {}, {}, {}, {}, {}
        for c, p, a, b, nl, nv in zip(ep["cell"], ep["present"], ep["sj_n"], ep["sj_flag"], ep["n_l1"], ep["n_vis"]):
            if not c:
                continue
            gm_n[c] = gm_n.get(c, 0) + 1
            if not p:
                gm_k[c] = gm_k.get(c, 0) + 1
                continue
            sjn[c] = sjn.get(c, 0) + int(a)
            sjf[c] = sjf.get(c, 0) + int(b)
            if nv >= VIS_MIN:
                ll_n[c] = ll_n.get(c, 0) + 1
                ll_k[c] = ll_k.get(c, 0) + int(nl < MIN_LINKS)
        # cell rows
        for c, v in jv.items():
            lat, lon = h3.cell_to_latlng(c)
            a = ac.get(c)
            share = 100.0 * a[1] / a[0] if a and a[0] >= PAIR_MIN_AIRCRAFT else None
            rows.append({"window": str(w), "h3": c, "lat": lat, "lon": lon, "value": v, "share": share,
                         "aircraft": a[0] if a else 0,
                         "sj": sjf.get(c, 0) / sjn[c] if sjn.get(c) else None,
                         "lowlink": ll_k.get(c, 0) / ll_n[c] if ll_n.get(c) else None,
                         "missing": gm_k.get(c, 0) / gm_n[c] if gm_n.get(c) else None})
        # boxes, every window
        for name, b in {**BOX, **JUDGED_CONTROLS, **SAA_CONTROLS,
                        **{k: v for kind in C.BOXES.values() for k, v in kind.items() if k not in BOX}}.items():
            vs = [v for c, v in jv.items() if in_box(*h3.cell_to_latlng(c), b)]
            box_table.setdefault(name, {})[str(w)] = {
                "cells": len(vs), "median": _r(np.median(vs)) if vs else None,
                "degraded": _r(np.mean(np.array(vs) <= DEGRADED_DB)) if vs else None}
        # per receiver type, other signals
        for typ, us in (("PODRIX", PODRIX), ("RUAG", RUAG)):
            m = np.isin(ep["unit"], us)
            jt = judged(cell_values(ep["cell"][m], ep["unit"][m], ep["day"][m], ep["t"][m], ep["d_l1"][m],
                                    scored[m]))
            by_type[typ] += [(str(w), c, v) for c, v in jt.items()]
        for sig in ("gal", "l2"):
            s2 = np.isfinite(ep[f"d_{sig}"]) & ep["present"]
            jo = judged(cell_values(ep["cell"], ep["unit"], ep["day"], ep["t"], ep[f"d_{sig}"], s2))
            other[sig] += [(str(w), c, v) for c, v in jo.items()]
        # back-projection over this window's paired cells
        pc = [c for c, a in ac.items() if a[0] >= PAIR_MIN_AIRCRAFT]
        if pc:
            cl = np.array([h3.cell_to_latlng(c) for c in pc])
            cen = B.unit_ll(cl[:, 0], cl[:, 1])
            ok = scored & np.isfinite(ep["lat"])
            pos = B.unit_ll(ep["lat"][ok], ep["lon"][ok])
            f = -ep["d_l1"][ok].astype(float)
            for R_ in BP_RADII:
                n_vis, s = B.backproject(pos, f, cen, radius_km=R_)
                cs = B.corr_score(n_vis, s, f)
                for c, nv, sv, cv in zip(pc, n_vis, s, cs):
                    a = ac[c]
                    if nv >= MIN_EPOCHS:
                        bp[R_].append({"share": 100.0 * a[1] / a[0], "mean": sv / nv, "corr": cv})
        # detection reach
        ok = scored & np.isfinite(ep["lat"])
        dk = K.km(KALININGRAD[0], KALININGRAD[1], ep["lat"][ok], ep["lon"][ok])
        reach_k.append((dk, ep["d_l1"][ok]))
        cm = ok & np.any([in_box(ep["lat"], ep["lon"], b) for b in JUDGED_CONTROLS.values()], axis=0)
        ctrl_all.append(ep["d_l1"][cm])
        if w in GULF_WINDOWS:
            dg = K.km(GULF_CENTRE[0], GULF_CENTRE[1], ep["lat"][ok], ep["lon"][ok])
            reach_g.append((dg, ep["d_l1"][ok]))
            ctrl_gulf.append(ep["d_l1"][cm])
        # CYGNSS pairs
        cy = window_cygnss(all_days)
        for c, v in jv.items():
            if c in cy and abs(h3.cell_to_latlng(c)[0]) <= 38.0:
                cyg_pairs.append((-v, cy[c]))
        per_window.append({"window": str(w), "epoch_days": len(days), "aircraft_days": ac_days,
                           "units_per_day": _r(np.mean(units_per_day), 2) if units_per_day else 0,
                           "thin": bool(units_per_day and np.mean(units_per_day) < 4),
                           "cells_scored": len(vals), "cells_judged": len(jv),
                           "paired": sum(1 for c in jv if ac.get(c) and ac[c][0] >= PAIR_MIN_AIRCRAFT)})

    pairs = [r for r in rows if r["share"] is not None]
    jam = [r for r in pairs if r["share"] >= JAM_SHARE]
    clean = [r for r in pairs if r["share"] < CLEAN_SHARE]
    score = lambda rs, k="value": [-r[k] for r in rs]
    res = {"frozen": "docs/validation/sentinel-gnss.md section 1", "windows": per_window,
           "pairs": len(pairs), "jammed": len(jam), "clean": len(clean), "checks": {}, "descriptive": {}}
    # 1
    a1 = C.auc(score(jam), score(clean))
    res["checks"]["1_pooled_auc"] = {"value": _r(a1), "verdict": verdict(1, a1)}
    # 2
    reg = K.region_heldout([{"day": r["window"], "h3": r["h3"], "lat": r["lat"], "lon": r["lon"],
                             "med_db": -r["value"], "share": r["share"]} for r in pairs])
    a2 = reg.get("min_judged_auc_without")
    res["checks"]["2_region_heldout_min_auc"] = {"value": _r(a2), "verdict": verdict(2, a2), "regions": reg["regions"]}
    # 3
    bj = [r for r in jam if in_box(r["lat"], r["lon"], BOX["Baltic"])]
    a3 = C.auc(score(bj), score(clean)) if len(bj) >= 10 else None
    res["checks"]["3_baltic_own_auc"] = {"value": _r(a3), "verdict": verdict(3, a3), "baltic_jammed": len(bj)}
    # 4
    gm = {wn: [r["value"] for r in rows if r["window"] == str(wn) and in_box(r["lat"], r["lon"], BOX["Persian Gulf"])]
          for wn in (BEFORE, DURING)}
    cm4 = {wn: [r["value"] for r in rows if r["window"] == str(wn)
                and any(in_box(r["lat"], r["lon"], b) for b in JUDGED_CONTROLS.values())] for wn in (BEFORE, DURING)}
    d4 = (np.median(gm[DURING]) - np.median(gm[BEFORE])) if gm[DURING] and gm[BEFORE] else None
    dc = (np.median(cm4[DURING]) - np.median(cm4[BEFORE])) if cm4[DURING] and cm4[BEFORE] else None
    res["checks"]["4_gulf_change_db"] = {
        "value": _r(d4), "verdict": verdict(4, None if d4 is None else float(d4)),
        "gulf_cells": {str(k): len(v) for k, v in gm.items()},
        "gulf_median": {str(k): _r(np.median(v)) if v else None for k, v in gm.items()},
        "controls_change_db": _r(dc), "controls_flag": bool(dc is not None and abs(dc) > 0.5)}
    # 5
    cv = [r["value"] for r in rows if any(in_box(r["lat"], r["lon"], b) for b in JUDGED_CONTROLS.values())]
    s5 = float(np.mean(np.array(cv) <= DEGRADED_DB)) if cv else None
    res["checks"]["5_controls_degraded_share"] = {"value": _r(s5, 4), "verdict": verdict(5, s5),
                                                   "cell_windows": len(cv)}
    # 6
    if len(cyg_pairs) >= 3:
        rho, p = spearmanr([x[0] for x in cyg_pairs], [x[1] for x in cyg_pairs])
        v6 = verdict(6, float(rho))
        if v6 == "holds" and p >= 0.01:
            v6 = "weakened (p >= 0.01)"
        res["checks"]["6_cygnss_spearman"] = {"value": _r(rho), "p": float(p), "cells": len(cyg_pairs),
                                              "verdict": v6}
    else:
        res["checks"]["6_cygnss_spearman"] = {"value": None, "verdict": "not judged", "cells": len(cyg_pairs)}

    # ---- descriptive
    D = res["descriptive"]
    D["rates"] = {str(t): {"hit": _r(np.mean([r["value"] <= t for r in jam])) if jam else None,
                           "false_alarm": _r(np.mean([r["value"] <= t for r in clean])) if clean else None}
                  for t in (-0.5, -1.0, -2.0)}
    sjj = [r["sj"] for r in jam if r["sj"] is not None]
    sjc = [r["sj"] for r in clean if r["sj"] is not None]
    D["satjam_auc"] = _r(C.auc(sjj, sjc))
    llj = [r["lowlink"] for r in jam if r["lowlink"] is not None]
    llc = [r["lowlink"] for r in clean if r["lowlink"] is not None]
    D["lowlink"] = {"auc": _r(C.auc(llj, llc)), "median_jammed": _r(np.median(llj)) if llj else None,
                    "median_clean": _r(np.median(llc)) if llc else None}
    mj = [r["missing"] for r in jam if r["missing"] is not None]
    mc = [r["missing"] for r in clean if r["missing"] is not None]
    D["missing"] = {"median_jammed": _r(np.median(mj)) if mj else None,
                    "median_clean": _r(np.median(mc)) if mc else None, "auc": _r(C.auc(mj, mc))}
    D["backprojection"] = {}
    for R_, xs in bp.items():
        bj_ = [x for x in xs if x["share"] >= JAM_SHARE]
        bc_ = [x for x in xs if x["share"] < CLEAN_SHARE]
        D["backprojection"][str(int(R_))] = {
            "jammed": len(bj_), "clean": len(bc_),
            "auc_mean": _r(C.auc([x["mean"] for x in bj_], [x["mean"] for x in bc_])),
            "auc_corr": _r(C.auc([x["corr"] for x in bj_], [x["corr"] for x in bc_]))}
    lab = {(r["window"], r["h3"]): r["share"] for r in pairs}

    def sub_auc(items):
        j = [-v for w_, c, v in items if lab.get((w_, c)) is not None and lab[(w_, c)] >= JAM_SHARE]
        k = [-v for w_, c, v in items if lab.get((w_, c)) is not None and lab[(w_, c)] < CLEAN_SHARE]
        return {"auc": _r(C.auc(j, k)), "jammed": len(j), "clean": len(k)}
    D["receiver_type"] = {t: sub_auc(v) for t, v in by_type.items()}
    D["galileo_e1"] = sub_auc(other["gal"])
    D["gps_l2"] = sub_auc(other["l2"])
    j60 = [r for r in jam if abs(r["lat"]) <= 60]
    c60 = [r for r in clean if abs(r["lat"]) <= 60]
    D["within_60"] = {"auc": _r(C.auc(score(j60), score(c60))), "jammed": len(j60), "clean": len(c60)}

    def reach(pairs_, ctrl):
        d = np.concatenate([p[0] for p in pairs_]) if pairs_ else np.zeros(0)
        v = np.concatenate([p[1] for p in pairs_]) if pairs_ else np.zeros(0)
        cmed = float(np.median(np.concatenate(ctrl))) if ctrl and sum(len(c) for c in ctrl) else None
        prof, best = [], None
        for a in range(0, 3000, 100):
            m = (d >= a) & (d < a + 100)
            med = float(np.median(v[m])) if m.any() else None
            prof.append({"km": f"{a}-{a + 100}", "n": int(m.sum()), "median": _r(med)})
            if med is not None and cmed is not None and med <= cmed - 0.5:
                best = a + 100
        return {"control_median": _r(cmed), "reach_km": best, "profile": prof}
    D["reach_kaliningrad"] = reach(reach_k, ctrl_all)
    D["reach_gulf"] = reach(reach_g, ctrl_gulf)
    fa = {"0-500": [0, 0], "500-1000": [0, 0], "1000-2000": [0, 0], ">2000": [0, 0]}
    for r in clean:
        js = [q for q in jam if q["window"] == r["window"]]
        dmin = min((float(K.km(r["lat"], r["lon"], q["lat"], q["lon"])) for q in js), default=1e9)
        k = "0-500" if dmin < 500 else "500-1000" if dmin < 1000 else "1000-2000" if dmin < 2000 else ">2000"
        fa[k][0] += 1
        fa[k][1] += int(r["value"] <= DEGRADED_DB)
    D["false_alarms_by_distance"] = {k: {"clean": v[0], "degraded": v[1], "rate": _r(v[1] / v[0]) if v[0] else None}
                                     for k, v in fa.items()}
    D["boxes"] = box_table
    try:
        D["kp5_days"] = [d for d in kp_storm_days(WINDOWS[0], WINDOWS[-1] + dt.timedelta(days=6))
                         if any(dt.date.fromisoformat(d) - w_ < dt.timedelta(days=7) and
                                dt.date.fromisoformat(d) >= w_ for w_ in WINDOWS)]
        D["kp_source"] = "GFZ Potsdam (CC BY 4.0), as the events lane"
    except Exception as ex:   # reported, never fatal
        D["kp5_days"], D["kp_source"] = None, f"not fetched: {ex}"
    D["eks_events"] = "unchecked (arXiv:2606.03673 not read before the run)"
    return res


# ---------------------------------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("epochs")
    p.add_argument("days", nargs="+")
    p.add_argument("--force", action="store_true")
    sub.add_parser("checks")
    a = ap.parse_args(argv)
    if a.cmd == "epochs":
        for d in SG.days_arg(a.days):
            out = os.path.join(EPOCH_DIR, f"{d}.parquet")
            if os.path.exists(out) and not a.force:
                print(f"{d} held")
                continue
            path, counts = build_epochs(d)
            print(json.dumps({"day": str(d), "file": os.path.relpath(path, ROOT), "epochs": counts}))
        return 0
    res = run_checks()
    with open(RESULTS, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, default=str)
    print(json.dumps({k: res[k] for k in ("pairs", "jammed", "clean")}))
    for k, v in res["checks"].items():
        print(f"  {k}: {v.get('value')} -> {v.get('verdict')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
