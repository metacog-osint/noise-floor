#!/usr/bin/env python3
"""sentinel_bands.py: the lower L-band from the Sentinel navigation receivers (step X3 of docs/multi-gnss-plan.md),
exactly as pre-registered in docs/validation/sentinel-gnss-x3.md section 1 (commit 5a718af, 1 Nov 2026 14:06 UTC).

Commands
  bands DAY...  per PODRIX unit (Sentinel-1C, 1D, 2C) and grid epoch: the frozen E2 index for six signals
                -> data/sentinel_gnss/bands/<day>.parquet. Needs the day's E1 table and E2 epoch file (positions
                and cells come from the epoch file, so they match E2 exactly).
  checks        the nine E3 windows: X3-1 and X3-2 with their marks, the band ratios with bootstrap intervals and
                fixed readings, and the descriptive results -> data/sentinel_gnss/x3_results.json

Signals (system, value column, required partner column):
  l1   GPS s1c              l1p  GPS s1c where s2l exists   l2c  GPS s2l
  e1   Galileo s1c          e1p  Galileo s1c where s5q exists   e5a  Galileo s5q
The index is sentinel_rfi.index_signal (tools/rx_rfi.py underneath), unchanged, run on each signal on its own.
"""
import argparse
import datetime as dt
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import sentinel_gnss as SG  # noqa: E402
import sentinel_rfi as SR  # noqa: E402

BANDS_DIR = os.path.join(SG.DATA, "bands")
RESULTS = os.path.join(SG.DATA, "x3_results.json")
SIGNALS = {"l1": ("G", "s1c", None), "l1p": ("G", "s1c", "s2l"), "l2c": ("G", "s2l", None),
           "e1": ("E", "s1c", None), "e1p": ("E", "s1c", "s5q"), "e5a": ("E", "s5q", None)}
PAIRS = {"E5a / E1 paired": ("e5a", "e1p"), "L2C / L1 paired": ("l2c", "l1p")}
MARKS = {"X3-1": ("e5a", 0.75, 0.65), "X3-2": ("l2c", 0.75, 0.65)}
READ_LOW, READ_HIGH = 0.33, 0.67
BOOT, SEED = 2000, 1
MIN_BOX_JAMMED = 10
OWN_BACKGROUND_DB, PAIRED_QUIET_DB = -0.5, -0.25


# ---------------------------------------------------------------------------------------------- bands

def unit_bands(day, unit, rows, ep):
    """One PODRIX unit-day: per grid epoch, d_<signal> and n_<signal> for the six signals, on the E2 epoch grid."""
    t_rows = rows["t"].astype(float)
    off = SG.grid_offset(t_rows)
    n = len(ep["t"])
    expect = (off + np.arange(n) * SG.STEP).astype(np.int32)
    if not np.array_equal(ep["t"], expect):
        raise ValueError(f"{day} {unit}: the E2 epoch grid doesn't match this unit's rows (offset {off})")
    gi = np.round((t_rows - off) / SG.STEP).astype(int)
    keep = (gi >= 0) & (gi < n)
    rows = {k: v[keep] for k, v in rows.items()}
    gi, t_rows = gi[keep], t_rows[keep]
    sat = rows["sat"].astype(str)
    el = rows["el"].astype(float)
    row_cell = ep["cell"][gi]
    out = {"unit": np.full(n, unit), "t": ep["t"], "lat": ep["lat"], "lon": ep["lon"], "cell": ep["cell"],
           "present": ep["present"]}
    for name, (sysc, col, partner) in SIGNALS.items():
        v = rows[col].astype(float)
        m = np.char.startswith(sat, sysc) & np.isfinite(v)
        if partner:
            m &= np.isfinite(rows[partner].astype(float))
        d = np.full(n, np.nan, np.float32)
        cnt = np.bincount(gi[m & np.isfinite(el) & (el >= SR.MIN_EL)], minlength=n).astype(np.int16)
        if m.any():
            ei = SR.index_signal(f"{unit}|{day}|{name}", t_rows[m], sat[m], el[m], v[m], row_cell[m])
            if ei is not None and len(ei["t"]):
                d[np.round((ei["t"] - off) / SG.STEP).astype(int)] = ei["idx"]
        out[f"d_{name}"], out[f"n_{name}"] = d, cnt
    return out


def build_bands(day):
    import pyarrow as pa
    import pyarrow.parquet as pq
    p = os.path.join(SG.DAYS_DIR, f"{day}.parquet")
    e = os.path.join(SR.EPOCH_DIR, f"{day}.parquet")
    if not (os.path.exists(p) and os.path.exists(e)):
        raise SystemExit(f"{day}: needs the E1 table and the E2 epoch file")
    T = pq.read_table(p)
    cols = {k: np.asarray(T.column(k).to_numpy(zero_copy_only=False)) for k in T.column_names}
    units = cols["unit"].astype(str)
    E = pq.read_table(e, columns=["unit", "t", "lat", "lon", "cell", "present"])
    ec = {k: np.asarray(E.column(k).to_numpy(zero_copy_only=False)) for k in E.column_names}
    ec["unit"], ec["cell"] = ec["unit"].astype(str), ec["cell"].astype(str)
    parts = []
    for u in SR.PODRIX:
        m = units == u
        if not m.any() or not (ec["unit"] == u).any():
            continue
        rows = {k: v[m] for k, v in cols.items() if k != "unit"}
        em = ec["unit"] == u
        order = np.argsort(ec["t"][em], kind="stable")
        ep = {k: v[em][order] for k, v in ec.items()}
        parts.append(unit_bands(day, u, rows, ep))
    if not parts:
        return None, {}
    out = {k: np.concatenate([q[k] for q in parts]) for k in parts[0]}
    os.makedirs(BANDS_DIR, exist_ok=True)
    tbl = pa.table({k: (pa.array(v.astype(str)).dictionary_encode() if k in ("unit", "cell") else pa.array(v))
                    for k, v in out.items()})
    path = os.path.join(BANDS_DIR, f"{day}.parquet")
    pq.write_table(tbl, path + ".part", compression="zstd")
    SG.replace(path + ".part", path)
    return path, {u: int((out["unit"] == u).sum()) for u in sorted(set(out["unit"]))}


# ---------------------------------------------------------------------------------------------- checks

def load_window(start):
    import pyarrow.parquet as pq
    parts, days = [], []
    for k in range(7):
        d = start + dt.timedelta(days=k)
        p = os.path.join(BANDS_DIR, f"{d}.parquet")
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


def reading(r):
    if r is None or not np.isfinite(r):
        return None
    return "mostly L1" if r < READ_LOW else "wideband" if r > READ_HIGH else "partial"


def interval_reading(lo, hi):
    a, b = reading(lo), reading(hi)
    if a is None or b is None:
        return None
    order = ["mostly L1", "partial", "wideband"]
    a, b = sorted((a, b), key=order.index)
    return a if a == b else f"{a} to {b}"


def ratio(jl, kl, jh, kh, rng=None, boot=BOOT):
    """Drop ratio low/high band: (median jl - median kl) / (median jh - median kh), with a bootstrap interval.

    jl, jh: the jammed cell-windows' values on the lower band and on its paired L1 signal (same cell-windows);
    kl, kh: the clean ones. Returns (R, lo, hi, drop_low, drop_l1)."""
    jl, kl, jh, kh = (np.asarray(x, float) for x in (jl, kl, jh, kh))
    if not len(jl) or not len(kl):
        return None, None, None, None, None
    dl = np.median(jl) - np.median(kl)
    dh = np.median(jh) - np.median(kh)
    r = dl / dh if dh else np.nan
    rng = rng or np.random.default_rng(SEED)
    bs = []
    for _ in range(boot):
        a = rng.integers(0, len(jl), len(jl))
        b = rng.integers(0, len(kl), len(kl))
        h = np.median(jh[a]) - np.median(kh[b])
        if h:
            bs.append((np.median(jl[a]) - np.median(kl[b])) / h)
    lo, hi = (np.percentile(bs, [2.5, 97.5]) if bs else (np.nan, np.nan))
    return float(r), float(lo), float(hi), float(dl), float(dh)


def run_checks():
    import h3
    import cygnss_rfi as C
    cellwin = {}            # (window, cell) -> {signal: value}
    labels = {}             # (window, cell) -> share (paired cells only)
    links, scored_share = {s: [] for s in SIGNALS}, {s: [0, 0] for s in SIGNALS}
    per_window = []
    for w in SR.WINDOWS:
        ep, days = load_window(w)
        ac, ac_days = SR.window_aircraft([w + dt.timedelta(days=k) for k in range(7)])
        for c, a in ac.items():
            if a[0] >= SR.PAIR_MIN_AIRCRAFT:
                labels[(str(w), c)] = 100.0 * a[1] / a[0]
        if ep is None:
            per_window.append({"window": str(w), "band_days": 0})
            continue
        counts = {}
        for s in SIGNALS:
            d = ep[f"d_{s}"]
            sc = np.isfinite(d) & ep["present"]
            scored_share[s][0] += int(sc.sum())
            scored_share[s][1] += int(ep["present"].sum())
            links[s].append(ep[f"n_{s}"][sc])
            jv = SR.judged(SR.cell_values(ep["cell"], ep["unit"], ep["day"], ep["t"], d, sc))
            counts[s] = len(jv)
            for c, v in jv.items():
                cellwin.setdefault((str(w), c), {})[s] = v
        per_window.append({"window": str(w), "band_days": len(days), "aircraft_days": ac_days,
                           "units": sorted(set(ep["unit"].tolist())), "cells_judged": counts})
    latlng = {c: h3.cell_to_latlng(c) for (_, c) in cellwin}

    def group(sig, which, box=None):
        out = []
        for k, vals in cellwin.items():
            if sig not in vals or k not in labels:
                continue
            sh = labels[k]
            if (which == "jam" and sh >= SR.JAM_SHARE) or (which == "clean" and sh < SR.CLEAN_SHARE):
                if box is None or SR.in_box(*latlng[k[1]], box):
                    out.append(k)
        return out

    res = {"preregistered": "docs/validation/sentinel-gnss-x3.md section 1 (commit 5a718af)", "windows": per_window,
           "checks": {}, "ratios": {}, "descriptive": {}}
    aucs = {}
    for s in SIGNALS:
        j, k = group(s, "jam"), group(s, "clean")
        a = C.auc([-cellwin[x][s] for x in j], [-cellwin[x][s] for x in k])
        aucs[s] = {"auc": SR._r(a), "jammed": len(j), "clean": len(k),
                   "hit_at_-1": SR._r(np.mean([cellwin[x][s] <= -1.0 for x in j])) if j else None,
                   "false_alarm_at_-1": SR._r(np.mean([cellwin[x][s] <= -1.0 for x in k])) if k else None}
    for chk, (s, hold, fail) in MARKS.items():
        a = aucs[s]["auc"]
        v = None if a is None else "holds" if a >= hold else "fails" if a < fail else "weakened"
        res["checks"][chk] = {"signal": s, "value": a, "verdict": v or "not judged",
                              "jammed": aucs[s]["jammed"], "clean": aucs[s]["clean"]}
    res["descriptive"]["auc_by_signal"] = aucs
    rng = np.random.default_rng(SEED)
    for pname, (lo_s, hi_s) in PAIRS.items():
        def both(keys, lo_s=lo_s, hi_s=hi_s):
            return [x for x in keys if lo_s in cellwin[x] and hi_s in cellwin[x]]
        kc = both(group(lo_s, "clean"))
        res["ratios"][pname] = {}
        for where, box in (("pooled", None), ("Baltic", SR.BOX["Baltic"]), ("Persian Gulf", SR.BOX["Persian Gulf"])):
            jc = both(group(lo_s, "jam", box))
            if where != "pooled" and len(jc) < MIN_BOX_JAMMED:
                res["ratios"][pname][where] = {"jammed": len(jc), "reading": "not judged"}
                continue
            r, lo, hi, dl, dh = ratio([cellwin[x][lo_s] for x in jc], [cellwin[x][lo_s] for x in kc],
                                      [cellwin[x][hi_s] for x in jc], [cellwin[x][hi_s] for x in kc], rng=rng)
            res["ratios"][pname][where] = {
                "jammed": len(jc), "clean": len(kc), "drop_lower_db": SR._r(dl), "drop_l1_db": SR._r(dh),
                "ratio": SR._r(r), "interval_95": [SR._r(lo), SR._r(hi)],
                "reading": reading(r), "interval_reading": interval_reading(lo, hi)}
    # descriptive: own background over busy airspace, regional dip, links
    D = res["descriptive"]
    cp = SR.JUDGED_CONTROLS["Central Pacific"]
    au = SR.JUDGED_CONTROLS["Australia interior"]
    bg, boxes = {}, {}
    for s in SIGNALS:
        clean = [cellwin[x][s] for x in group(s, "clean")]
        cpv = [v[s] for (w_, c), v in cellwin.items() if s in v and SR.in_box(*latlng[c], cp)]
        auv = [v[s] for (w_, c), v in cellwin.items() if s in v and SR.in_box(*latlng[c], au)]
        bg[s] = SR._r(np.median(clean) - np.median(cpv)) if clean and cpv else None
        boxes[s] = {"central_pacific": SR._r(np.median(cpv)) if cpv else None, "central_pacific_cells": len(cpv),
                    "australia_interior": SR._r(np.median(auv)) if auv else None, "australia_cells": len(auv),
                    "clean_busy_airspace": SR._r(np.median(clean)) if clean else None}
    D["clean_minus_central_pacific_db"] = bg
    D["own_background_flag"] = {lo_s: bool(bg[lo_s] is not None and bg[hi_s] is not None and bg[lo_s] <= OWN_BACKGROUND_DB
                                           and bg[hi_s] > PAIRED_QUIET_DB) for lo_s, hi_s in PAIRS.values()}
    D["boxes"] = boxes
    D["links_per_scored_epoch_median"] = {s: SR._r(np.median(np.concatenate(v))) if v and sum(len(x) for x in v) else None
                                          for s, v in links.items()}
    D["podrix_epochs_scored_share"] = {s: SR._r(a / b) if b else None for s, (a, b) in scored_share.items()}
    return res


# ---------------------------------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("bands")
    p.add_argument("days", nargs="+")
    p.add_argument("--force", action="store_true")
    sub.add_parser("checks")
    a = ap.parse_args(argv)
    if a.cmd == "bands":
        for d in SG.days_arg(a.days):
            out = os.path.join(BANDS_DIR, f"{d}.parquet")
            if os.path.exists(out) and not a.force:
                print(f"{d} held")
                continue
            path, counts = build_bands(d)
            print(json.dumps({"day": str(d), "file": os.path.relpath(path, ROOT) if path else None, "epochs": counts}),
                  flush=True)
        return 0
    res = run_checks()
    with open(RESULTS, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, default=str)
    for k, v in res["checks"].items():
        print(f"  {k} ({v['signal']}): AUC {v['value']} -> {v['verdict']} ({v['jammed']} jammed, {v['clean']} clean)")
    for p_, rows in res["ratios"].items():
        for where, r in rows.items():
            print(f"  {p_} {where}: R {r.get('ratio')} {r.get('interval_95')} -> {r.get('reading')} "
                  f"[{r.get('interval_reading')}] (jammed {r.get('jammed')})")
    print("  own background (clean - Central Pacific, dB):", res["descriptive"]["clean_minus_central_pacific_db"],
          res["descriptive"]["own_background_flag"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
