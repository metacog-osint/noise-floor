#!/usr/bin/env python3
"""smap_rfi.py: interference at 1400-1427 MHz flagged by NASA SMAP's radiometer.

SMAP's radiometer listens in the protected passive band 1400-1427 MHz and flags radio frequency interference on board
and in processing. The L1C half-orbit product (SPL1CTB v006, 36 km EASE-Grid 2.0, about 5.5 MB a file, about 30 files
a day) carries a 16-bit quality word per cell, look (fore, aft) and polarization (H, V). Its flag_meanings attribute
names bit 2 "RFI_detection", bit 3 "RFI_correction", bit 14 "RFI_check" and bit 15 "RFI_clean". On 20 Oct 2026 bits 3
and 15 were set only where bit 2 was, so this tool reads bit 2 as "RFI detected" and bit 15 as "RFI left after
mitigation". The 0/1 sense is inferred from the data; the product specification was not read.

What it shows is emitters in or spilling into that band (radars, for example), not GPS jammers.

Commands
  fetch DAY...                  list the day's half-orbits in NASA CMR, download each with EARTHDATA_TOKEN, keep per-cell
                                counts -> data/smap/days/<day>.parquet (no SMAP file is kept)
  share END [--days 7]          sum the days ending at END -> data/smap/share/<END>.d<N>.parquet: share of looks with RFI
                                detected, and the contrast against the 100-300 km ring around each cell
  radars END [--days 7]         known-answer check against long-range radar sites (open-air-data/atc-radar); prints JSON

Data: NASA SMAP L1C (NSIDC DAAC; NASA open data, citation required). Registry row `smap-rfi`.
Plan: docs/space-sensors-plan.md (steps R0-R3).
"""
import argparse
import datetime as dt
import io
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "smap")
DAYS_DIR = os.path.join(DATA, "days")
SHARE_DIR = os.path.join(DATA, "share")
RADARS = os.path.join(ROOT, "data", "reference", "atc-radars.geojson")
RADARS_URL = "https://raw.githubusercontent.com/open-air-data/atc-radar/master/data/radars.geojson"
CMR = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
SHORT_NAME, VERSION = "SPL1CTB", "006"
LOOKS = ("h_fore", "v_fore", "h_aft", "v_aft")
FILL = 65534
BIT_DET, BIT_RESID = 2, 15
R_EARTH = 6371.0
RING = (100.0, 300.0)            # km, ring for the contrast


# ---------------------------------------------------------------------------------------------- fetch

def _session():
    import requests
    tok = os.environ.get("EARTHDATA_TOKEN")
    if not tok:
        raise SystemExit("EARTHDATA_TOKEN is not set (an Earthdata Login bearer token is needed for NSIDC).")
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {tok}"   # requests drops it on redirects to another host (the S3 bucket)
    return s


def granules(day):
    import requests
    p = {"short_name": SHORT_NAME, "version": VERSION, "page_size": 100,
         "temporal": f"{day}T00:00:00Z,{day}T23:59:59Z"}
    items = requests.get(CMR, params=p, timeout=60).json().get("items", [])
    out = []
    for it in items:
        urls = [u["URL"] for u in it["umm"].get("RelatedUrls", [])
                if u["URL"].startswith("https") and u["URL"].endswith(".h5")]
        if urls:
            out.append(urls[0])
    return sorted(set(out))


def reduce_file(buf):
    """One L1C half-orbit -> (key, lat, lon, land, looks, det, resid) per cell with at least one look."""
    import h5py
    with h5py.File(io.BytesIO(buf), "r") as f:
        g = f["Global_Projection"]
        row = g["cell_row"][:].astype(np.int64)
        col = g["cell_column"][:].astype(np.int64)
        lat = g["cell_lat"][:]
        lon = g["cell_lon"][:]
        surf = g["cell_grid_surface_status"][:] if "cell_grid_surface_status" in g else np.zeros(len(row))
        looks = np.zeros(len(row), np.int32)
        det = np.zeros(len(row), np.int32)
        res = np.zeros(len(row), np.int32)
        for k in LOOKS:
            q = g[f"cell_tb_qual_flag_{k}"][:].astype(np.int64)
            ok = q != FILL
            looks += ok
            det += ok & (((q >> BIT_DET) & 1) == 1)
            res += ok & (((q >> BIT_RESID) & 1) == 1)
    m = looks > 0
    return row[m] * 10000 + col[m], lat[m], lon[m], (surf[m] == 0), looks[m], det[m], res[m]


def fetch(day, force=False):
    import pyarrow as pa
    import pyarrow.parquet as pq
    os.makedirs(DAYS_DIR, exist_ok=True)
    out = os.path.join(DAYS_DIR, f"{day}.parquet")
    if os.path.exists(out) and not force:
        print(f"{day}: have it")
        return out
    urls = granules(day)
    if not urls:
        print(f"{day}: no SMAP L1C half-orbits listed")
        return None
    s = _session()
    acc = {}
    t0, nbytes = time.time(), 0
    for u in urls:
        for attempt in range(4):
            try:
                r = s.get(u, timeout=300)
                r.raise_for_status()
                break
            except Exception as e:
                if attempt == 3:
                    raise
                print(f"{day}: retry {os.path.basename(u)} after {e}")
                time.sleep(15 * (attempt + 1))
        nbytes += len(r.content)
        for k, la, lo, land, n, d, z in zip(*reduce_file(r.content)):
            a = acc.get(k)
            if a is None:
                acc[k] = [la, lo, land, n, d, z]
            else:
                a[3] += n
                a[4] += d
                a[5] += z
    keys = np.array(sorted(acc), dtype=np.int64)
    v = [acc[k] for k in keys]
    tab = {"cell": keys, "lat": np.array([x[0] for x in v], np.float32), "lon": np.array([x[1] for x in v], np.float32),
           "land": np.array([bool(x[2]) for x in v]), "looks": np.array([x[3] for x in v], np.int32),
           "det": np.array([x[4] for x in v], np.int32), "resid": np.array([x[5] for x in v], np.int32)}
    pq.write_table(pa.table(tab), out, compression="zstd")
    print(f"{day}: {len(urls)} half-orbits, {nbytes / 1e6:.0f} MB, {len(keys)} cells, "
          f"{tab['det'].sum() / max(tab['looks'].sum(), 1):.3f} of looks flagged, {time.time() - t0:.0f} s")
    return out


# ---------------------------------------------------------------------------------------------- share

def days_ending(end, n):
    e = dt.date.fromisoformat(end)
    return [(e - dt.timedelta(days=k)).isoformat() for k in range(n - 1, -1, -1)]


def unit_ll(lat, lon):
    la, lo = np.radians(np.asarray(lat, float)), np.radians(np.asarray(lon, float))
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], axis=-1)


def ring_median(lat, lon, val, ring=RING, chunk=2000):
    """Median of `val` over cells between ring[0] and ring[1] km from each cell (NaN where none)."""
    u = unit_ll(lat, lon)
    c0, c1 = np.cos(ring[0] / R_EARTH), np.cos(ring[1] / R_EARTH)
    out = np.full(len(lat), np.nan)
    for i in range(0, len(u), chunk):
        d = u[i:i + chunk] @ u.T
        m = (d <= c0) & (d >= c1)
        for j in range(m.shape[0]):
            vv = val[m[j]]
            if len(vv):
                out[i + j] = np.median(vv)
    return out


def share(end, ndays=7, min_looks=8):
    import pyarrow as pa
    import pyarrow.parquet as pq
    acc = {}
    used = []
    for d in days_ending(end, ndays):
        p = os.path.join(DAYS_DIR, f"{d}.parquet")
        if not os.path.exists(p):
            continue
        used.append(d)
        t = pq.read_table(p).to_pydict()
        for k, la, lo, land, n, de, z in zip(t["cell"], t["lat"], t["lon"], t["land"], t["looks"], t["det"], t["resid"]):
            a = acc.setdefault(k, [la, lo, land, 0, 0, 0])
            a[3] += n
            a[4] += de
            a[5] += z
    if not used:
        raise SystemExit(f"no SMAP day files for the {ndays} days ending {end} (run fetch)")
    keys = np.array([k for k, a in acc.items() if a[3] >= min_looks], dtype=np.int64)
    a = np.array([acc[k] for k in keys], dtype=float)
    lat, lon, land, looks, det, resid = a.T
    sh = det / looks
    rm = ring_median(lat, lon, sh)
    tab = {"cell": keys, "lat": lat.astype(np.float32), "lon": lon.astype(np.float32), "land": land.astype(bool),
           "looks": looks.astype(np.int32), "share": sh.astype(np.float32), "resid_share": (resid / looks).astype(np.float32),
           "ring": rm.astype(np.float32), "contrast": (sh - rm).astype(np.float32)}
    os.makedirs(SHARE_DIR, exist_ok=True)
    out = os.path.join(SHARE_DIR, f"{end}.d{ndays}.parquet")
    pq.write_table(pa.table(tab), out, compression="zstd")
    print(f"{end}: {len(used)} days, {len(keys)} cells, median share {np.median(sh):.3f}")
    return out


# ---------------------------------------------------------------------------------------------- radars

LONG_RANGE = ("ARSR", "FPS", "ENR-MDS")       # en-route Mode S sites sit with long-range (L-band) primary radars


def radar_sites(path=RADARS):
    if not os.path.exists(path):
        import requests
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").write(requests.get(RADARS_URL, timeout=60).content)
    fs = json.load(open(path, encoding="utf-8"))["features"]
    out = []
    for f in fs:
        typ = (f["properties"].get("type") or "").upper()
        if any(typ.startswith(t) or t in typ for t in LONG_RANGE):
            lon, lat = f["geometry"]["coordinates"][:2]
            out.append({"id": f["properties"].get("id"), "name": f["properties"].get("name"), "type": typ,
                        "lat": float(lat), "lon": float(lon)})
    return out


def radar_check(end, ndays=7, near_km=40.0, far_km=150.0):
    """Cells within near_km of a long-range radar site against land cells farther than far_km from every site, inside
    the sites' own box (so the comparison stays within the same country and RFI environment)."""
    import pyarrow.parquet as pq
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    from cygnss_rfi import auc
    p = os.path.join(SHARE_DIR, f"{end}.d{ndays}.parquet")
    if not os.path.exists(p):
        share(end, ndays)
    t = pq.read_table(p).to_pydict()
    lat, lon = np.array(t["lat"]), np.array(t["lon"])
    land = np.array(t["land"])
    sites = radar_sites()
    s_lat = np.array([s["lat"] for s in sites])
    s_lon = np.array([s["lon"] for s in sites])
    box = (s_lat.min() - 1, s_lat.max() + 1, s_lon.min() - 1, s_lon.max() + 1)
    inbox = (lat >= box[0]) & (lat <= box[1]) & (lon >= box[2]) & (lon <= box[3]) & land
    d = np.degrees(np.arccos(np.clip(unit_ll(lat, lon) @ unit_ll(s_lat, s_lon).T, -1, 1))) * 111.195
    dmin = d.min(1)
    near = inbox & (dmin <= near_km)
    far = inbox & (dmin > far_km)
    out = {"end": end, "days": ndays, "sites": len(sites), "near_cells": int(near.sum()), "far_cells": int(far.sum())}
    for key in ("share", "contrast", "resid_share"):
        v = np.array(t[key], float)
        ok = np.isfinite(v)
        out[key] = {"auc": round(auc(v[near & ok], v[far & ok]), 3) if (near & ok).any() and (far & ok).any() else None,
                    "near_median": round(float(np.nanmedian(v[near])), 3) if near.any() else None,
                    "far_median": round(float(np.nanmedian(v[far])), 3) if far.any() else None}
    return out


# ---------------------------------------------------------------------------------------------- cli

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("days", nargs="+")
    f.add_argument("--force", action="store_true")
    for name in ("share", "radars"):
        g = sub.add_parser(name)
        g.add_argument("end")
        g.add_argument("--days", type=int, default=7)
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        for day in a.days:
            try:
                fetch(day, a.force)
            except Exception as e:
                print(f"{day}: FAILED {e}", file=sys.stderr)
    elif a.cmd == "share":
        share(a.end, a.days)
    elif a.cmd == "radars":
        print(json.dumps(radar_check(a.end, a.days), indent=1))


if __name__ == "__main__":
    main()
