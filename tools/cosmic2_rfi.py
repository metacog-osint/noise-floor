#!/usr/bin/env python3
"""cosmic2_rfi.py: GPS interference heard by COSMIC-2's navigation antennas (UCAR's RFI index).

COSMIC-2 (six satellites, 24 deg inclination, about 550 km) tracks GPS on two navigation (POD) antennas per satellite.
UCAR's level-1b `podTc2` files (one per satellite-GPS link, 1 Hz) carry `RFI`, a "Radio Frequency Interference index"
with the attribute RFI_threshold = 1e-4. Checked on 30 Oct 2026: the value is the same on every link of one antenna in
the same second, so it describes the antenna, not the link. A ground emitter raises it while the satellite is in view.

Commands
  fetch DAY...            stream the day's podTc2 archive from UCAR, keep one row per satellite, antenna and second
                          -> data/cosmic2/days/<day>.parquet and <day>.pointing.json (no file is kept from the archive)
  grid DAY... [--radius-km R] [--res 2]
                          back-project: for each H3 cell, the mean flagged share of the 10 s bins whose satellite could
                          see the cell (within R km of the sub-satellite point) -> data/cosmic2/grid/<day>.r<res>.k<R>.parquet
  pairs DAY... [--radius-km R] [--res 2]
                          score each grid against the aircraft map (jammed >= 10%, clean < 2%, 20+ aircraft), the
                          control boxes and CYGNSS; prints JSON

Data: UCAR CDAAC COSMIC-2 near-real-time level 1b (UCAR data terms, CC BY 4.0). Registry row `cosmic2-ro`.
Plan: docs/space-sensors-plan.md (steps C1-C5). Validation: docs/validation/cosmic2.md.
"""
import argparse
import datetime as dt
import io
import json
import os
import sys
import tarfile
import time
import urllib.request

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "cosmic2")
DAYS_DIR = os.path.join(DATA, "days")
GRID_DIR = os.path.join(DATA, "grid")
URL = "https://data.cosmic.ucar.edu/gnss-ro/cosmic2/{stream}/level1b/{y}/{doy:03d}/podTc2_{stream}_{y}_{doy:03d}.tar.gz"
UA = "noisefloor/1.0 (+https://github.com/metacog-osint/noise-floor)"

GPS_UNIX = 315964800            # GPS epoch (6 Jan 1980) in Unix seconds
LEAP = 18                       # GPS - UTC since 1 Jan 2017
FILL = -999.0
THR = 1e-4                      # UCAR's RFI_threshold attribute
BIN_S = 10                      # seconds per bin of one satellite antenna
R_EARTH = 6371.0
RADIUS_KM = 2500.0              # default back-projection radius (the horizon from 550 km is about 2,560 km)
MIN_VIS = 30                    # bins (5 minutes) that could see a cell before it is scored
MAX_ABS_LAT = 60.0              # cells beyond this are never in view (24 deg inclination + horizon)


# ---------------------------------------------------------------------------------------------- reduce

def sat_of(name):
    """'podTc2_C2E2.2026.302...' -> 2."""
    return int(name.split("_")[1].split(".")[0][3:])


def _unit(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def link_frame(leo, gps):
    """Unit LEO->GPS vectors in the satellite's along-track, cross-track and radial axes (velocity from the track)."""
    r = _unit(leo)
    v = np.gradient(leo, axis=0) if len(leo) > 1 else np.zeros_like(leo)
    a = v - (v * r).sum(1, keepdims=True) * r
    n = np.linalg.norm(a, axis=1, keepdims=True)
    a = np.divide(a, n, out=np.zeros_like(a), where=n > 0)
    c = np.cross(r, a)
    u = _unit(gps - leo)
    return np.stack([(u * a).sum(1), (u * c).sum(1), (u * r).sum(1)], axis=1)


def read_link(buf):
    """One podTc2 file -> dict of arrays (valid RFI samples only) and its antenna id; None if unreadable."""
    from scipy.io import netcdf_file
    try:
        f = netcdf_file(io.BytesIO(buf), "r", mmap=False)
    except Exception:
        return None
    V, A = f.variables, f._attributes
    if "RFI" not in V:
        return None
    rfi = np.asarray(V["RFI"][:], dtype=float)
    ok = np.isfinite(rfi) & (rfi != FILL)
    t = float(A["start_time"]) + np.asarray(V["time"][:], dtype=float)
    leo = np.stack([np.asarray(V[k][:], dtype=float) for k in ("x_LEO", "y_LEO", "z_LEO")], axis=1)
    gps = np.stack([np.asarray(V[k][:], dtype=float) for k in ("x_GPS", "y_GPS", "z_GPS")], axis=1)
    frame = link_frame(leo, gps)
    return {"ant": int(A["antenna_id"]), "t": np.round(t[ok]).astype(np.int64), "rfi": rfi[ok],
            "leo": leo[ok], "frame": frame[ok]}


def reduce_stream(fobj):
    """Read a podTc2 tar.gz stream. Returns (table dict, pointing dict, counts)."""
    cols = {k: [] for k in ("sat", "ant", "t", "rfi", "x", "y", "z")}
    point = {}
    files = bad = 0
    with tarfile.open(fileobj=fobj, mode="r|gz") as tf:
        for m in tf:
            name = os.path.basename(m.name)
            if not m.isfile() or not name.startswith("podTc2_"):
                continue
            files += 1
            d = read_link(tf.extractfile(m).read())
            if d is None:
                bad += 1
                continue
            if not len(d["t"]):
                continue
            s = sat_of(name)
            n = len(d["t"])
            cols["sat"].append(np.full(n, s, np.int8))
            cols["ant"].append(np.full(n, d["ant"], np.int8))
            cols["t"].append(d["t"])
            cols["rfi"].append(d["rfi"].astype(np.float32))
            for i, k in enumerate("xyz"):
                cols[k].append(d["leo"][:, i].astype(np.float32))
            p = point.setdefault(f"{s}.{d['ant']}", [0.0, 0.0, 0.0, 0])
            p[0] += float(d["frame"][:, 0].sum())
            p[1] += float(d["frame"][:, 1].sum())
            p[2] += float(d["frame"][:, 2].sum())
            p[3] += n
    if not cols["t"]:
        return None, {}, {"files": files, "bad": bad, "rows": 0}
    c = {k: np.concatenate(v) for k, v in cols.items()}
    # one row per satellite, antenna and second (every link of one antenna carries the same value)
    key = (c["sat"].astype(np.int64) * 10 + c["ant"]) * 10**10 + c["t"]
    _, first = np.unique(key, return_index=True)
    c = {k: v[first] for k, v in c.items()}
    xyz = np.stack([c.pop("x"), c.pop("y"), c.pop("z")], axis=1).astype(float)
    c["lat"] = np.degrees(np.arctan2(xyz[:, 2], np.hypot(xyz[:, 0], xyz[:, 1]))).astype(np.float32)
    c["lon"] = np.degrees(np.arctan2(xyz[:, 1], xyz[:, 0])).astype(np.float32)
    c["alt"] = (np.linalg.norm(xyz, axis=1) - R_EARTH).astype(np.float32)
    c["t"] = c["t"] + GPS_UNIX - LEAP                     # Unix seconds, UTC
    pointing = {k: {"along": round(v[0] / v[3], 3), "cross": round(v[1] / v[3], 3), "radial": round(v[2] / v[3], 3),
                    "samples": v[3]} for k, v in sorted(point.items())}
    return c, pointing, {"files": files, "bad": bad, "rows": int(len(c["t"]))}


def url_for(day, stream="nrt"):
    d = dt.date.fromisoformat(day)
    return URL.format(stream=stream, y=d.year, doy=d.timetuple().tm_yday)


def fetch(day, force=False, stream="nrt"):
    import pyarrow as pa
    import pyarrow.parquet as pq
    os.makedirs(DAYS_DIR, exist_ok=True)
    out = os.path.join(DAYS_DIR, f"{day}.parquet")
    if os.path.exists(out) and not force:
        print(f"{day}: have it")
        return out
    url = url_for(day, stream)
    t0 = time.time()
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as resp:
                size = int(resp.headers.get("Content-Length") or 0)
                c, pointing, n = reduce_stream(resp)
            break
        except (OSError, tarfile.TarError, EOFError) as e:
            if attempt == 3:
                raise
            print(f"{day}: retry after {e}")
            time.sleep(20 * (attempt + 1))
    if c is None:
        print(f"{day}: no RFI rows ({n})")
        return None
    pq.write_table(pa.table(c), out, compression="zstd")
    meta = {"day": day, "url": url, "bytes": size, "seconds": round(time.time() - t0), **n, "pointing": pointing}
    json.dump(meta, open(os.path.join(DAYS_DIR, f"{day}.pointing.json"), "w"), indent=1)
    print(f"{day}: {n['files']} links, {n['rows']} antenna-seconds, {size / 1e6:.0f} MB in {meta['seconds']} s")
    return out


def read_day(day):
    import pyarrow.parquet as pq
    p = os.path.join(DAYS_DIR, f"{day}.parquet")
    return pq.read_table(p).to_pydict() if os.path.exists(p) else None


# ---------------------------------------------------------------------------------------------- grid

def unit_ll(lat, lon):
    la, lo = np.radians(np.asarray(lat, float)), np.radians(np.asarray(lon, float))
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], axis=-1)


def bins(t, sat, ant, rfi, lat, lon, bin_s=BIN_S, thr=THR):
    """10 s bins per satellite antenna: flagged share, seconds, mean sub-satellite unit vector, and the along-track
    unit vector (from the same series' neighbouring bins; zero where a bin has no neighbour within a minute)."""
    t = np.asarray(t, np.int64)
    key = (np.asarray(sat, np.int64) * 10 + np.asarray(ant)) * 10**10 + t // bin_s
    u, inv = np.unique(key, return_inverse=True)
    n = np.bincount(inv)
    f = np.bincount(inv, weights=(np.asarray(rfi) > thr).astype(float)) / n
    xyz = unit_ll(lat, lon)
    pos = _unit(np.stack([np.bincount(inv, weights=xyz[:, i]) for i in range(3)], axis=1))
    series, tb = u // 10**10, u % 10**10                   # keys are sorted by series, then time
    along = np.zeros_like(pos)
    nxt = np.r_[np.arange(1, len(u)), len(u) - 1]
    prv = np.r_[0, np.arange(len(u) - 1)]
    ok_n = (series[nxt] == series) & (tb[nxt] - tb > 0) & (tb[nxt] - tb <= 6)
    ok_p = (series[prv] == series) & (tb - tb[prv] > 0) & (tb - tb[prv] <= 6)
    d = np.where(ok_n[:, None], pos[nxt], pos) - np.where(ok_p[:, None], pos[prv], pos)
    d -= (d * pos).sum(1, keepdims=True) * pos
    nd = np.linalg.norm(d, axis=1, keepdims=True)
    along = np.divide(d, nd, out=along, where=nd > 0)
    return {"key": u, "ant": (series % 10).astype(int), "f": f, "n": n, "pos": pos, "along": along}


def look_sign(ant, pointing):
    """+1 for a forward-looking antenna, -1 for aft, 0 if unknown (from the day's mean link direction)."""
    out = np.zeros(len(ant), int)
    for k, v in (pointing or {}).items():
        a = int(k.split(".")[1])
        s = 1 if v["along"] > 0.3 else -1 if v["along"] < -0.3 else 0
        out[(ant == a) & (out == 0)] = s                    # every satellite's antenna k looks the same way
    return out


_CELLS = {}


def cells(res=2, max_lat=MAX_ABS_LAT):
    if res not in _CELLS:
        import h3
        ids = sorted(c for r0 in h3.get_res0_cells() for c in h3.cell_to_children(r0, res))
        ll = np.array([h3.cell_to_latlng(c) for c in ids])
        keep = np.abs(ll[:, 0]) <= max_lat
        _CELLS[res] = ([c for c, k in zip(ids, keep) if k], ll[keep], unit_ll(ll[keep, 0], ll[keep, 1]))
    return _CELLS[res]


def backproject(pos, f, centres, radius_km=RADIUS_KM, chunk=4000, along=None, sign=None):
    """For each centre: bins that could see it (central angle within radius) and the sum of their flagged shares.
    With `along` and `sign`, a forward antenna (+1) sees only centres ahead of the satellite, an aft one (-1) only
    centres behind; sign 0 sees both."""
    cosr = np.cos(radius_km / R_EARTH)
    n_vis = np.zeros(len(centres))
    s = np.zeros(len(centres))
    for i in range(0, len(pos), chunk):
        m = (pos[i:i + chunk] @ centres.T) >= cosr
        if along is not None:
            sg = sign[i:i + chunk][:, None]
            m &= (sg == 0) | ((along[i:i + chunk] @ centres.T) * sg > 0)
        n_vis += m.sum(0)
        s += f[i:i + chunk] @ m
    return n_vis, s


def corr_score(n_vis, s, f):
    """Matched filter: correlation across all bins between 'this bin could see the cell' and the bin's flagged share.
    The plain flagged share (s / n_vis) is biased toward the edge of coverage: cells there are seen only by satellites
    at the top of their orbit, which may sit near an emitter (offline test, 30 Oct 2026)."""
    f = np.asarray(f, float)
    N = len(f)
    pf = f.mean()
    var_f = (f * f).mean() - pf * pf
    pi = n_vis / N
    cov = s / N - pf * pi
    den = np.sqrt(np.maximum(pi * (1 - pi), 0) * max(var_f, 0))
    return np.divide(cov, den, out=np.zeros_like(cov, dtype=float), where=den > 0)


def grid_name(day, res, radius_km, halves):
    return os.path.join(GRID_DIR, f"{day}.r{res}.k{int(radius_km)}{'h' if halves else ''}.parquet")


def grid(day, res=2, radius_km=RADIUS_KM, halves=False):
    import pyarrow as pa
    import pyarrow.parquet as pq
    d = read_day(day)
    if d is None:
        raise SystemExit(f"{day}: no day file (run fetch)")
    b = bins(d["t"], d["sat"], d["ant"], d["rfi"], d["lat"], d["lon"])
    ids, ll, cen = cells(res)
    if halves:
        meta = json.load(open(os.path.join(DAYS_DIR, f"{day}.pointing.json")))
        n_vis, s = backproject(b["pos"], b["f"], cen, radius_km, along=b["along"],
                               sign=look_sign(b["ant"], meta["pointing"]))
    else:
        n_vis, s = backproject(b["pos"], b["f"], cen, radius_km)
    corr = corr_score(n_vis, s, b["f"])
    ok = n_vis >= MIN_VIS
    os.makedirs(GRID_DIR, exist_ok=True)
    out = grid_name(day, res, radius_km, halves)
    pq.write_table(pa.table({"h3": [c for c, k in zip(ids, ok) if k], "lat": ll[ok, 0], "lon": ll[ok, 1],
                             "n_vis": n_vis[ok].astype(np.int32), "share": (s[ok] / n_vis[ok]).astype(np.float32),
                             "score": corr[ok].astype(np.float32)}),
                   out, compression="zstd")
    print(f"{day}: {int(ok.sum())} cells scored, {len(b['f'])} bins, flagged share {np.mean(b['f']):.3f}")
    return out


def read_grid(day, res=2, radius_km=RADIUS_KM, halves=False):
    import pyarrow.parquet as pq
    p = grid_name(day, res, radius_km, halves)
    return {r["h3"]: r for r in pq.read_table(p).to_pylist()} if os.path.exists(p) else None


# ---------------------------------------------------------------------------------------------- score

def pairs_for(days, res=2, radius_km=RADIUS_KM, halves=False):
    """[(score, aircraft share %, aircraft, lat, lon, day, cell)] for cells with a score and 20+ aircraft."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import cygnss_rfi as C
    out = []
    for day in days:
        g = read_grid(day, res, radius_km, halves)
        ac = C.aircraft(day, res)
        if g is None or ac is None:
            print(f"{day}: missing {'grid' if g is None else 'aircraft table'}", file=sys.stderr)
            continue
        for c, r in g.items():
            a = ac.get(c)
            if a and a[0] >= C.PAIR_MIN_AIRCRAFT:
                out.append((r["score"], 100.0 * a[1] / a[0], a[0], r["lat"], r["lon"], day, c))
    return out


def summary(days, res=2, radius_km=RADIUS_KM, halves=False, thresholds=(0.05, 0.1, 0.2)):
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import cygnss_rfi as C
    P = pairs_for(days, res, radius_km, halves)
    jam = [p[0] for p in P if p[1] >= C.JAM_SHARE]
    clean = [p[0] for p in P if p[1] < C.CLEAN_SHARE]
    ctrl = []
    for day in days:
        g = read_grid(day, res, radius_km, halves) or {}
        ctrl += [r["score"] for r in g.values()
                 if any(C.in_box(r["lat"], r["lon"], b) for b in C.BOXES["control"].values())]
    rate = lambda v, t: round(float(np.mean(np.asarray(v) >= t)), 3) if len(v) else None
    return {"days": len(days), "res": res, "radius_km": radius_km, "halves": halves, "pairs": len(P), "jam": len(jam),
            "clean": len(clean), "auc": None if not jam or not clean else round(C.auc(jam, clean), 3),
            "jam_median": round(float(np.median(jam)), 3) if jam else None,
            "clean_median": round(float(np.median(clean)), 3) if clean else None,
            "control_cells": len(ctrl), "control_median": round(float(np.median(ctrl)), 3) if ctrl else None,
            "control_p95": round(float(np.percentile(ctrl, 95)), 3) if ctrl else None,
            "rates": {str(t): {"hit": rate(jam, t), "fa": rate(clean, t), "control": rate(ctrl, t)} for t in thresholds}}


# ---------------------------------------------------------------------------------------------- cli

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("days", nargs="+")
    f.add_argument("--force", action="store_true")
    f.add_argument("--stream", default="nrt", choices=["nrt", "rapid", "postProc"])
    for name in ("grid", "pairs"):
        g = sub.add_parser(name)
        g.add_argument("days", nargs="+")
        g.add_argument("--res", type=int, default=2)
        g.add_argument("--radius-km", type=float, default=RADIUS_KM)
        g.add_argument("--halves", action="store_true", help="fore/aft antenna sees only cells ahead/behind")
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        for day in a.days:
            try:
                fetch(day, a.force, a.stream)
            except Exception as e:                      # one bad day must not stop a batch
                print(f"{day}: FAILED {e}", file=sys.stderr)
    elif a.cmd == "grid":
        for day in a.days:
            grid(day, a.res, a.radius_km, a.halves)
    elif a.cmd == "pairs":
        print(json.dumps(summary(a.days, a.res, a.radius_km, a.halves), indent=1))


if __name__ == "__main__":
    main()
