#!/usr/bin/env python3
"""cygnss_checks.py — held-out, same-hour and known-emitter checks for the CYGNSS lane.

The rules were pre-registered in docs/validation/cygnss.md, section 8, before the held-out days were fetched; the
results are in section 9. This file only reads what tools/cygnss_rfi.py writes (grids, per-pass tables, the L1
subsets) and the aircraft tables, the FAA advisory file and the events register. It changes none of them.

Commands
  python tools/cygnss_checks.py heldout DAYS...    per-day and pooled scores (cygnss_rfi.validate), control boxes and
                                                   region-held-out AUC  -> data/cygnss/heldout_r3.json
  python tools/cygnss_checks.py samehour DAYS...   pass-cell excess against the same-hour aircraft share
                                                   -> data/cygnss/samehour_r3.json
  python tools/cygnss_checks.py faa DAYS...        passes near FAA-announced GPS test sites, in and out of the windows
                                                   -> data/cygnss/faa_r3.json
  python tools/cygnss_checks.py s3 DAYS...         events-lane rule S3: 93 m observations against random land points
                                                   (reads data/events/register.sqlite) -> data/cygnss/s3_<tag>.json
DAYS are UTC days (YYYY-MM-DD). Times are UTC throughout.
"""
import argparse
import json
import math
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone

import h3
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cygnss_rfi as C  # noqa: E402

FAA_FILE = os.path.join(ROOT, "data", "declared", "faa_gps_tests.json")
REGISTER = os.path.join(ROOT, "data", "events", "register.sqlite")

# ---- pre-registered parameters (docs/validation/cygnss.md, section 8) ----
REGION_LINK_KM = 1000.0   # jammed cell-days within this distance form one region (single linkage)
REGION_MIN_JAM = 10       # a leave-one-region-out AUC is judged only with this many jammed cells left
HOUR_MIN_AIRCRAFT = 10    # summed aircraft in a res-3 cell-hour for a same-hour share
BAND_LAT = 38.0           # CYGNSS band for the FAA tests and the S3 points
SITE_LINK_KM = 100.0      # FAA test centres this close form one site
SITE_RADIUS_KM = 300.0    # DDMs with specular points this close to a site centre belong to its passes
PASS_GAP_S = 600.0        # a gap longer than this splits one spacecraft's DDMs into separate passes
FAA_PASS_MIN_DDM = 10
EDGE_MIN = 60             # out-of-window passes stay this many minutes from every nearby window
NEARBY_SITE_KM = 600.0
S3_KM = 300.0             # BEAM_LINK_KM in tools/events.py
S3_POINTS = 400           # random land points per day


# ---------------------------------------------------------------------------------------------- helpers

def km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km (numpy broadcasting)."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(np.asarray(lon2) - lon1) / 2) ** 2
    return 12742.0 * np.arcsin(np.minimum(1.0, np.sqrt(a)))


def single_linkage(lat, lon, link_km):
    """Cluster labels (0..k-1, in order of first member) for points linked within link_km (union-find)."""
    lat, lon = np.asarray(lat, dtype=float), np.asarray(lon, dtype=float)
    n = len(lat)
    up = list(range(n))

    def root(i):
        while up[i] != i:
            up[i] = up[up[i]]
            i = up[i]
        return i

    for i in range(n):
        d = km(lat[i], lon[i], lat[i + 1:], lon[i + 1:])
        for j in np.where(d <= link_km)[0] + i + 1:
            ri, rj = root(i), root(int(j))
            if ri != rj:
                up[rj] = ri
    labels, out = {}, []
    for i in range(n):
        out.append(labels.setdefault(root(i), len(labels)))
    return np.array(out, dtype=int)


def wilson(k, n, z=1.96):
    """Wilson score interval for k successes out of n, as (low, high)."""
    if n == 0:
        return None, None
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return round(mid - half, 4), round(mid + half, 4)


def _r(v, n=3):
    return None if v is None else round(float(v), n)


def box_name(lat, lon):
    for boxes in C.BOXES.values():
        for name, b in boxes.items():
            if C.in_box(lat, lon, b):
                return name
    return None


# ---------------------------------------------------------------------------------------------- held-out scores

def paired_cells(days, res=3):
    """Paired cell-days (20+ aircraft, judged noise value): dicts with day, h3, lat, lon, med_db, share, aircraft."""
    out = []
    for d in days:
        g, ac = C.read_grid(d, res), C.aircraft(d, res)
        if g is None or ac is None:
            print(f"{d}: no grid or no aircraft table, skipped")
            continue
        for c, r in g.items():
            if c in ac and ac[c][0] >= C.PAIR_MIN_AIRCRAFT and C.noise_ok(r):
                out.append({"day": d, "h3": c, "lat": r["lat"], "lon": r["lon"], "med_db": r["med_db"],
                            "share": 100.0 * ac[c][1] / ac[c][0], "aircraft": ac[c][0]})
    return out


def region_heldout(pairs, link_km=REGION_LINK_KM, min_jam=REGION_MIN_JAM):
    """Leave-one-region-out AUC. Regions are single-linkage clusters of the jammed cell-days at `link_km`; leaving
    one out drops every paired cell (jammed or clean) within `link_km` of any of its jammed cells."""
    jam = [p for p in pairs if p["share"] >= C.JAM_SHARE]
    clean = [p for p in pairs if p["share"] < C.CLEAN_SHARE]
    if not jam:
        return {"regions": [], "pooled_auc": None}
    lab = single_linkage([p["lat"] for p in jam], [p["lon"] for p in jam], link_km)
    plat = np.array([p["lat"] for p in pairs])
    plon = np.array([p["lon"] for p in pairs])
    regions = []
    for k in range(lab.max() + 1):
        mem = [p for p, l in zip(jam, lab) if l == k]
        near = np.zeros(len(pairs), dtype=bool)
        for m in mem:
            near |= km(m["lat"], m["lon"], plat, plon) <= link_km
        rest = [p for p, x in zip(pairs, near) if not x]
        rj = [p["med_db"] for p in rest if p["share"] >= C.JAM_SHARE]
        rc = [p["med_db"] for p in rest if p["share"] < C.CLEAN_SHARE]
        names = defaultdict(int)
        for m in mem:
            names[box_name(m["lat"], m["lon"]) or "outside the boxes"] += 1
        regions.append({
            "region": k, "jam": len(mem), "days": len({m["day"] for m in mem}),
            "lat": _r(np.mean([m["lat"] for m in mem]), 2), "lon": _r(np.mean([m["lon"] for m in mem]), 2),
            "boxes": dict(sorted(names.items(), key=lambda kv: -kv[1])),
            "own_auc": _r(C.auc([m["med_db"] for m in mem], [c["med_db"] for c in clean])),
            "own_hit_1db": C._rate([m["med_db"] for m in mem], C.ELEVATED_DB),
            "auc_without": _r(C.auc(rj, rc)), "jam_left": len(rj), "clean_left": len(rc),
            "judged": len(rj) >= min_jam,
        })
    regions.sort(key=lambda r: -r["jam"])
    return {"regions": regions, "pooled_auc": _r(C.auc([p["med_db"] for p in jam], [p["med_db"] for p in clean])),
            "jam": len(jam), "clean": len(clean),
            "min_judged_auc_without": min((r["auc_without"] for r in regions if r["judged"]), default=None)}


def control_boxes(days, res=3):
    """Control-box cell-days with a judged noise value: share at >= 1 dB, and each box's median per day."""
    vals, per = [], defaultdict(dict)
    for d in days:
        g = C.read_grid(d, res)
        if g is None:
            continue
        for name, b in C.BOXES["control"].items():
            v = [r["med_db"] for r in g.values() if C.noise_ok(r) and C.in_box(r["lat"], r["lon"], b)]
            vals += v
            per[name][d] = {"cells": len(v), "med_db": _r(np.median(v), 2) if v else None,
                            "elevated": C._rate(v, C.ELEVATED_DB)}
    flagged = [(n, d, x["med_db"]) for n, dd in per.items() for d, x in dd.items()
               if x["med_db"] is not None and x["med_db"] > 0.5]
    return {"cell_days": len(vals), "elevated": sum(1 for v in vals if v >= C.ELEVATED_DB),
            "rate": C._rate(vals, C.ELEVATED_DB), "boxes": dict(per), "flagged_over_half_db": flagged}


def cmd_heldout(days, res, out):
    rep = C.validate(days, res, out=os.path.join(C.DATA, f"validation_{out}_r{res}.json"))
    pairs = paired_cells(days, res)
    reg = region_heldout(pairs)
    ctl = control_boxes(days, res)
    known = {}
    for name, b in C.BOXES["known"].items():
        known[name] = {d: rep["days"][d]["regions"][name]["cyg_med_db"] for d in rep["days"]}
    res_out = {"days": days, "pooled": rep.get("pooled"), "regions_heldout": reg, "controls": ctl, "known_boxes": known,
               "per_day": {d: {k: rep["days"][d][k] for k in ("paired_cells", "noise", "combined", "spearman_noise",
                                                               "spearman_noise_window", "blind_affected",
                                                               "blind_affected_water", "elevated_cells",
                                                               "affected_cells", "judged_cells")}
                           for d in rep["days"]}}
    path = os.path.join(C.DATA, f"heldout_{out}_r{res}.json")
    json.dump(res_out, open(path, "w"), indent=1)
    p = rep["pooled"]["noise"]
    print(f"pooled: {p['pairs']} pairs, {p['jam']} jammed, {p['clean']} clean, AUC {p['auc']}, "
          f"hit/FA @1dB {p['rates']['1.0']['hit']}/{p['rates']['1.0']['fa']}")
    print(f"controls: {ctl['elevated']}/{ctl['cell_days']} = {ctl['rate']}; flagged {ctl['flagged_over_half_db']}")
    for r in reg["regions"]:
        print(f"region {r['region']}: {r['jam']} jammed on {r['days']} days near {r['lat']},{r['lon']} {r['boxes']} | "
              f"own AUC {r['own_auc']} | AUC without {r['auc_without']} ({r['jam_left']} jam left, judged {r['judged']})")
    print(f"wrote {os.path.relpath(path, ROOT)}")
    return res_out


# ---------------------------------------------------------------------------------------------- same hour

def hourly_aircraft(day, res=3):
    """{(res-`res` cell, hour): [aircraft, GPSJam-style bad]} from the hourly res-4 table (None if absent)."""
    import pyarrow.parquet as pq
    p = os.path.join(C.AIRCRAFT_DIR, f"{day}.hourly.parquet")
    if not os.path.exists(p):
        return None
    t = pq.read_table(p, columns=["h3", "hour", "aircraft", "bad_nacp_live"]).to_pydict()
    out = defaultdict(lambda: [0, 0])
    par = {}
    for c, hr, a, b in zip(t["h3"], t["hour"], t["aircraft"], t["bad_nacp_live"]):
        if c not in par:
            par[c] = h3.cell_to_parent(c, res) if res < 4 else c
        o = out[(par[c], int(hr))]
        o[0] += a
        o[1] += max(b - 1, 0)
    return dict(out)


def label(share):
    return "jam" if share >= C.JAM_SHARE else "clean" if share < C.CLEAN_SHARE else None


def pass_level(rows):
    """AUC and rates at 1 dB for pass-cell rows [(med_db, label)] with label 'jam', 'clean' or None."""
    jam = [v for v, l in rows if l == "jam"]
    clean = [v for v, l in rows if l == "clean"]
    return {"jam": len(jam), "clean": len(clean), "auc": _r(C.auc(jam, clean)),
            "hit_1db": C._rate(jam, C.ELEVATED_DB), "fa_1db": C._rate(clean, C.ELEVATED_DB)}


def cmd_samehour(days, res, focus_day="2026-01-02"):
    rep = {"days": days, "punjab": [], "false_alarms": None, "pass_level": None}
    pl_same, pl_daily = [], []
    fa_any2 = [0, 0]      # clean cell-days reading >= 1 dB: [with a pass hour at >= 2%, with any judged pass hour]
    ok_any2 = [0, 0]      # clean cell-days reading < 1 dB
    fa_any10 = [0, 0]
    ok_any10 = [0, 0]
    for d in days:
        g, ac, hac, ps = C.read_grid(d, res), C.aircraft(d, res), hourly_aircraft(d, res), C.read_passes(d, res)
        if None in (g, ac, hac, ps):
            print(f"{d}: missing grid, aircraft, hourly table or passes, skipped")
            continue
        by_cell = defaultdict(list)
        for p in ps:
            by_cell[p["h3"]].append(p)
        for c, plist in by_cell.items():
            daily = ac.get(c)
            for p in plist:
                hr = int(p["t_mid"] // 3600)
                a = hac.get((c, hr))
                if a and a[0] >= HOUR_MIN_AIRCRAFT and daily and daily[0] >= C.PAIR_MIN_AIRCRAFT:
                    pl_same.append((p["med_db"], label(100.0 * a[1] / a[0])))
                    pl_daily.append((p["med_db"], label(100.0 * daily[1] / daily[0])))
        for c, r in g.items():
            daily = ac.get(c)
            if not (daily and daily[0] >= C.PAIR_MIN_AIRCRAFT and C.noise_ok(r)):
                continue
            share = 100.0 * daily[1] / daily[0]
            hours = []
            for p in by_cell.get(c, ()):
                hr = int(p["t_mid"] // 3600)
                a = hac.get((c, hr))
                hours.append({"hour": hr, "sc": p["sc"], "n": p["n"], "pass_db": p["med_db"],
                              "aircraft": a[0] if a else 0,
                              "share": _r(100.0 * a[1] / a[0], 1) if a and a[0] >= HOUR_MIN_AIRCRAFT else None})
            judged = [x["share"] for x in hours if x["share"] is not None]
            if share < C.CLEAN_SHARE and judged:
                tgt2, tgt10 = (fa_any2, fa_any10) if r["med_db"] >= C.ELEVATED_DB else (ok_any2, ok_any10)
                tgt2[1] += 1
                tgt10[1] += 1
                tgt2[0] += any(s >= C.CLEAN_SHARE for s in judged)
                tgt10[0] += any(s >= C.JAM_SHARE for s in judged)
            if d == focus_day and share >= C.JAM_SHARE:
                hrs = defaultdict(lambda: [0, 0])
                for hr in range(24):
                    a = hac.get((c, hr))
                    if a:
                        hrs[hr] = a
                rep["punjab"].append({
                    "h3": c, "lat": r["lat"], "lon": r["lon"], "box": box_name(r["lat"], r["lon"]),
                    "day_share": _r(share, 1), "day_aircraft": daily[0], "med_db": r["med_db"], "passes": hours,
                    "hourly": {hr: {"aircraft": a[0], "share": _r(100.0 * a[1] / a[0], 1) if a[0] else None}
                               for hr, a in sorted(hrs.items())}})
    rep["false_alarms"] = {
        "fa_cells": fa_any2[1], "fa_with_pass_hour_ge2": fa_any2[0], "fa_rate_ge2": _r(fa_any2[0] / fa_any2[1]) if fa_any2[1] else None,
        "quiet_cells": ok_any2[1], "quiet_with_pass_hour_ge2": ok_any2[0], "quiet_rate_ge2": _r(ok_any2[0] / ok_any2[1]) if ok_any2[1] else None,
        "fa_with_pass_hour_ge10": fa_any10[0], "fa_rate_ge10": _r(fa_any10[0] / fa_any10[1]) if fa_any10[1] else None,
        "quiet_with_pass_hour_ge10": ok_any10[0], "quiet_rate_ge10": _r(ok_any10[0] / ok_any10[1]) if ok_any10[1] else None}
    rep["pass_level"] = {"same_hour": pass_level(pl_same), "daily": pass_level(pl_daily), "pass_cells": len(pl_same)}
    path = os.path.join(C.DATA, f"samehour_r{res}.json")
    json.dump(rep, open(path, "w"), indent=1)
    for x in rep["punjab"]:
        print(f"{focus_day} jammed {x['h3']} {x['lat']},{x['lon']} day share {x['day_share']}% ({x['day_aircraft']} ac) "
              f"med {x['med_db']} dB; passes: " + "; ".join(
                  f"{p['hour']:02d}h sc{p['sc']} {p['pass_db']} dB share {p['share']} ({p['aircraft']} ac)" for p in x["passes"]))
    print("false alarms:", rep["false_alarms"])
    print("pass level:", rep["pass_level"])
    print(f"wrote {os.path.relpath(path, ROOT)}")
    return rep


# ---------------------------------------------------------------------------------------------- FAA tests

def _epoch_min(s):
    return int(datetime.strptime(s, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc).timestamp()) // 60


def faa_sites(tests, band=BAND_LAT, link_km=SITE_LINK_KM):
    """Sites from announced tests inside the band: centres within link_km merge (single linkage). Each site:
    name (most common place), lat, lon (mean of its test centres), tests (ids), windows (epoch minutes, merged)."""
    ts = [t for t in tests if abs(t["centre"][0]) <= band and t.get("windows")]
    if not ts:
        return []
    lab = single_linkage([t["centre"][0] for t in ts], [t["centre"][1] for t in ts], link_km)
    sites = []
    for k in range(lab.max() + 1):
        mem = [t for t, l in zip(ts, lab) if l == k]
        wins = sorted((_epoch_min(a), _epoch_min(b)) for t in mem for a, b in t["windows"])
        merged = []
        for a, b in wins:
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        places = defaultdict(int)
        for t in mem:
            places[t.get("place") or t["id"]] += 1
        sites.append({"site": k, "name": max(places.items(), key=lambda kv: kv[1])[0],
                      "lat": float(np.mean([t["centre"][0] for t in mem])),
                      "lon": float(np.mean([t["centre"][1] for t in mem])),
                      "tests": sorted(t["id"] for t in mem), "windows": merged})
    return sites


def window_class(t_min, own, nearby, edge=EDGE_MIN):
    """'in' if t_min is inside one of the site's own windows; 'out' if it is more than `edge` minutes from every
    window in `nearby` (which includes the site's own); otherwise None (near an edge, or in a nearby site's window)."""
    if any(a <= t_min <= b for a, b in own):
        return "in"
    if all(t_min < a - edge or t_min > b + edge for a, b in nearby):
        return "out"
    return None


def split_passes(t, gap=PASS_GAP_S):
    """Index arrays of consecutive runs in sorted times t, split where the gap exceeds `gap` seconds."""
    if not len(t):
        return []
    cut = np.where(np.diff(t) > gap)[0] + 1
    return np.split(np.arange(len(t)), cut)


def site_passes(day, d, ex, sites, radius=SITE_RADIUS_KM, min_n=FAA_PASS_MIN_DDM):
    """Passes near each site on one day: dicts with site, sc, t_mid (epoch minutes), n, med_db."""
    day0 = _epoch_min(f"{day}T00:00Z")
    ok = np.isfinite(ex)
    lat, lon, t, sc, x = d["lat"][ok], d["lon"][ok], d["t"][ok], d["sc"][ok], ex[ok]
    out = []
    for s in sites:
        box = (np.abs(lat - s["lat"]) <= radius / 111.0 + 0.1)
        if not box.any():
            continue
        idx = np.where(box)[0]
        idx = idx[km(s["lat"], s["lon"], lat[idx], lon[idx]) <= radius]
        for k in np.unique(sc[idx]):
            j = idx[sc[idx] == k]
            j = j[np.argsort(t[j], kind="mergesort")]
            for run in split_passes(t[j]):
                jj = j[run]
                if len(jj) < min_n:
                    continue
                out.append({"day": day, "site": s["site"], "sc": int(k), "t_mid": day0 + float(np.mean(t[jj])) / 60.0,
                            "n": int(len(jj)), "med_db": round(float(np.median(x[jj])), 3)})
    return out


def faa_score(passes, sites):
    """In-window vs out-of-window comparison, overall and per site."""
    from scipy.stats import fisher_exact, mannwhitneyu
    by_id = {s["site"]: s for s in sites}
    nearby = {}
    for s in sites:
        near = [o for o in sites if km(s["lat"], s["lon"], o["lat"], o["lon"]) <= NEARBY_SITE_KM]
        nearby[s["site"]] = sorted(w for o in near for w in map(tuple, o["windows"]))
    for p in passes:
        p["cls"] = window_class(p["t_mid"], by_id[p["site"]]["windows"], nearby[p["site"]])

    def stats(ps):
        a = [p["med_db"] for p in ps if p["cls"] == "in"]
        b = [p["med_db"] for p in ps if p["cls"] == "out"]
        r = {"in": len(a), "out": len(b), "auc": _r(C.auc(a, b)),
             "in_med": _r(np.median(a), 2) if a else None, "out_med": _r(np.median(b), 2) if b else None,
             "in_ge1": C._rate(a, C.ELEVATED_DB), "out_ge1": C._rate(b, C.ELEVATED_DB)}
        if a and b:
            r["mw_p"] = float(f"{mannwhitneyu(a, b, alternative='greater').pvalue:.3g}")
            k1, k2 = sum(v >= C.ELEVATED_DB for v in a), sum(v >= C.ELEVATED_DB for v in b)
            r["fisher_p"] = float(f"{fisher_exact([[k1, len(a) - k1], [k2, len(b) - k2]], alternative='greater')[1]:.3g}")
        return r

    overall = stats(passes)
    overall["detected"] = bool(overall["in"] >= 10 and (overall["auc"] or 0) >= 0.70 and overall.get("mw_p", 1) < 0.01)
    uniq = {}
    for p in passes:
        if p["cls"] in ("in", "out"):
            key = (p["day"], p["sc"], round(p["t_mid"]))
            uniq[key] = "in" if p["cls"] == "in" or uniq.get(key) == "in" else "out"
    overall["unique_in"] = sum(1 for v in uniq.values() if v == "in")
    overall["unique_out"] = sum(1 for v in uniq.values() if v == "out")
    per = {}
    for sid in sorted({p["site"] for p in passes}):
        ps = [p for p in passes if p["site"] == sid]
        st = stats(ps)
        if st["in"]:
            per[by_id[sid]["name"] + f" (site {sid})"] = st
    return {"overall": overall, "per_site": per}


def cmd_faa(days, res):
    tests = list(json.load(open(FAA_FILE, encoding="utf-8"))["tests"].values())
    sites = faa_sites(tests)
    passes = []
    for day in days:
        if not os.path.isdir(os.path.join(C.L1_DIR, day)):
            print(f"{day}: no L1 subsets, skipped")
            continue
        d, ex = C.day_excess(day, res)
        ps = site_passes(day, d, ex, sites)
        passes += ps
        print(f"{day}: {len(ps)} site passes", flush=True)
    sc = faa_score(passes, sites)
    rep = {"days": days, "sites": [{k: s[k] for k in ("site", "name", "lat", "lon", "tests")} for s in sites],
           "score": sc, "passes": [p for p in passes if p["cls"] in ("in", "out")]}
    path = os.path.join(C.DATA, f"faa_r{res}.json")
    json.dump(rep, open(path, "w"), indent=1)
    print("overall:", sc["overall"])
    for k, v in sc["per_site"].items():
        print(f"  {k}: {v}")
    print(f"wrote {os.path.relpath(path, ROOT)}")
    return rep


# ---------------------------------------------------------------------------------------------- rule S3

_RAW_LAND = None


def raw_land():
    """Unsmoothed 0.25° Natural Earth land mask (rows from 90N), cached next to the smoothed one."""
    global _RAW_LAND
    if _RAW_LAND is None:
        cache = os.path.join(C.DATA, f"landmask_{C.LAND_RES}.npy")
        if os.path.exists(cache):
            _RAW_LAND = np.load(cache)
        else:
            C.footprint_land()       # makes sure the Natural Earth file is cached
            land = json.load(open(os.path.join(C.CACHE, "ne_50m_land.geojson"), encoding="utf-8"))
            _RAW_LAND = C.land_mask(land)
            np.save(cache, _RAW_LAND)
    return _RAW_LAND


def random_points(day, n=S3_POINTS, band=BAND_LAT, land=True):
    """n points uniform by area within ±band, on land (raw mask) if `land`; the seed is the date as an integer."""
    rng = np.random.default_rng(int(day.replace("-", "")))
    m = raw_land() if land else None
    out = []
    s = math.sin(math.radians(band))
    while len(out) < n:
        la = np.degrees(np.arcsin(rng.uniform(-s, s, 4 * n)))
        lo = rng.uniform(-180.0, 180.0, 4 * n)
        if land:
            iy = np.clip(((90.0 - la) / C.LAND_RES).astype(int), 0, m.shape[0] - 1)
            ix = ((lo + 180.0) / C.LAND_RES).astype(int) % m.shape[1]
            keep = m[iy, ix]
            la, lo = la[keep], lo[keep]
        out += list(zip(la.tolist(), lo.tolist()))
    return out[:n]


def cmd_s3(days, tag):
    import sqlite3
    import events as E
    db = sqlite3.connect(f"file:{REGISTER}?mode=ro", uri=True)
    groups = {k: [0, 0, 0] for k in ("gross", "capable", "random_land", "random_any")}  # [n, any raised, field >= 1]
    per_day = {}
    for day in days:
        rows, _ = E.cygnss_input(day)
        if rows is None:
            print(f"{day}: no CYGNSS grid, skipped")
            continue
        field = E.cygnss_field(rows)
        raised = defaultdict(list)
        for r in rows:
            if (r.get("n") or 0) >= E.CYG_MIN_DDM and r.get("med_db") is not None and r["med_db"] >= E.CYG_ELEVATED_DB:
                raised[h3.cell_to_parent(r["h3"], E.REGION_RES)].append((r["lat"], r["lon"]))

        def any_raised(o):
            pts = E.anchors(o)
            for c in {c2 for c in o["cells"] for c2 in E.disk(c, 2)}:
                for la, lo in raised.get(c, ()):
                    if min(E.km(a, (la, lo)) for a in pts) <= S3_KM:
                        return True
            return False

        dd = {k: [0, 0, 0] for k in groups}
        obs = db.execute("SELECT kind, measure, lat, lon, cells, detail FROM observations WHERE family='adsb' AND day=?",
                         (day,)).fetchall()
        for kind, measure, lat, lon, cells, detail in obs:
            cells = json.loads(cells)
            if measure not in ("gross", "capable") or lat is None or abs(lat) > BAND_LAT or not cells:
                continue
            o = {"kind": kind, "lat": lat, "lon": lon, "cells": cells}
            med = json.loads(detail).get("cyg_local_med")
            for tgt in (groups[measure], dd[measure]):
                tgt[0] += 1
                tgt[1] += any_raised(o)
                tgt[2] += med is not None and med >= E.CYG_ELEVATED_DB
        for key, land in (("random_land", True), ("random_any", False)):
            for la, lo in random_points(day, land=land):
                o = {"kind": "random", "lat": la, "lon": lo, "cells": [h3.latlng_to_cell(la, lo, E.REGION_RES)]}
                med, _ = E.local_cygnss(o, field)
                for tgt in (groups[key], dd[key]):
                    tgt[0] += 1
                    tgt[1] += any_raised(o)
                    tgt[2] += med is not None and med >= E.CYG_ELEVATED_DB
        per_day[day] = dd
        print(f"{day}: " + "  ".join(f"{k} {v[2]}/{v[0]}" for k, v in dd.items()), flush=True)
    rep = {"days": days, "groups": {}, "per_day": per_day}
    for k, (n, a, f) in groups.items():
        rep["groups"][k] = {"n": n, "any_raised": _r(a / n) if n else None, "field_ge1": _r(f / n) if n else None,
                            "field_ge1_k": f, "field_ge1_wilson": wilson(f, n), "any_raised_wilson": wilson(a, n)}
    g, r = rep["groups"]["gross"], rep["groups"]["random_land"]
    if g["n"] and r["n"]:
        rep["ratio"] = _r(g["field_ge1"] / r["field_ge1"], 2) if r["field_ge1"] else None
        rep["holds"] = bool(rep["ratio"] is not None and rep["ratio"] >= 2 and g["field_ge1_wilson"][0] > r["field_ge1_wilson"][1])
        rep["fails"] = bool(rep["ratio"] is not None and rep["ratio"] < 1.5)
    path = os.path.join(C.DATA, f"s3_{tag}.json")
    json.dump(rep, open(path, "w"), indent=1)
    for k, v in rep["groups"].items():
        print(f"{k}: n {v['n']}, any raised {v['any_raised']}, field >= 1 dB {v['field_ge1']} {v['field_ge1_wilson']}")
    print(f"ratio {rep.get('ratio')}, holds {rep.get('holds')}, fails {rep.get('fails')}")
    print(f"wrote {os.path.relpath(path, ROOT)}")
    return rep


# ---------------------------------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("heldout", "samehour", "faa", "s3"))
    ap.add_argument("days", nargs="+")
    ap.add_argument("--res", type=int, default=3)
    ap.add_argument("--tag", default="heldout", help="heldout and s3: name used in the output file")
    a = ap.parse_args(argv)
    for d in a.days:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            raise SystemExit(f"bad day {d!r}")
    if a.cmd == "heldout":
        cmd_heldout(a.days, a.res, a.tag)
    elif a.cmd == "samehour":
        cmd_samehour(a.days, a.res)
    elif a.cmd == "faa":
        cmd_faa(a.days, a.res)
    else:
        cmd_s3(a.days, a.tag)


if __name__ == "__main__":
    main()
