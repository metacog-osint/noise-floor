#!/usr/bin/env python3
"""smos_rfi.py: SMOS L-band brightness temperatures from ESA's browse product (MIR_BWLF1C), reduced to how often each
grid point reads hotter than any natural surface.

SMOS measures 1400-1427 MHz, the protected band SMAP also uses. The browse product gives one brightness temperature per
grid point and overpass at 42.5 degrees incidence, in the antenna's X and Y polarisations. Natural surfaces at L-band
stay below about 300 K, so a look above 320 K is taken as interference.

The product's own RFI flags are not used as the measure: in the browse product they are set for most of the globe
(about 63% of points on a 29 Oct 2026 half-orbit), and they draw on ESA's list of known sources (AUX_RFILST).

Format (facts only, from ESA's binX schema DBL_SM_XXXX_MIR_BWLF1C_0400 and flag table DBL_SM_XXXX_MIR_XXXF1C_0401_flags
as distributed with the SMOS toolbox, senbox-org/smos-box): a little-endian uint32 count, then per grid point
  Grid_Point_ID u32, latitude f32, longitude f32, altitude f32, mask u8, BT_Data_Counter u8,
  and BT_Data_Counter entries of: Flags u16, BT_Value f32, accuracy u16, azimuth u16, footprint axes u16 x 2.
Entry polarisation is in flag bits 0-1: 0 = X, 1 = Y, 2 = XY real, 3 = XY imaginary. Bit 6 (0x40) is RFI_POINT_SOURCE.

Data: Copernicus Data Space Ecosystem S3 (/eodata/SMOS/L1CL/MIR_BWLF1C/...), with the CDSE keys `sentinel_gnss` uses.
Licence: ESA T&C for ESA EO data and the ESA Data Policy (registry row `smos-rfi`).

  python tools/smos_rfi.py fetch 2026-10-01 2026-10-02     # data/smos/days/<day>.npz, one row per grid point
  python tools/smos_rfi.py share 2026-10-07 --days 7       # data/smos/share/<end>.d7.npz
  python tools/smos_rfi.py nws 2026-10-07 2026-10-26       # checks M1-M3 of docs/validation/smos-rfi.md
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
import urllib.request

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
DATA = os.path.join(ROOT, "data", "smos")
DAYS_DIR = os.path.join(DATA, "days")
SHARE_DIR = os.path.join(DATA, "share")
PRODUCT = "MIR_BWLF1C"
NAME_RE = re.compile(r"SM_(OPER|REPR)_MIR_BWLF1C_(\d{8}T\d{6})_(\d{8}T\d{6})_(\d{3})_(\d{3})_(\d)")
HOT_K = (300.0, 320.0, 350.0)        # 320 K is the measure; the others are reported alongside
MEASURE_K = 320.0
FLAG_RFI_POINT = 0x40
R_EARTH = 6371.0

BT = np.dtype([("flags", "<u2"), ("val", "<f4"), ("acc", "<u2"), ("az", "<u2"), ("ax1", "<u2"), ("ax2", "<u2")])
HEAD = np.dtype([("id", "<u4"), ("lat", "<f4"), ("lon", "<f4"), ("alt", "<f4"), ("mask", "u1"), ("cnt", "u1")])


# ---------------------------------------------------------------------------------------------- reading

def read_dbl(buf):
    """Grid points of one browse DBL as (id, lat, lon, X, Y, rfi_flag_x). Entries are matched by their polarisation
    bits, so the order inside a record doesn't matter; a missing polarisation reads NaN."""
    n = int(np.frombuffer(buf[:4], "<u4")[0])
    if n == 0:
        z = np.zeros(0)
        return z.astype("u4"), z, z, z, z, z.astype(bool)
    cnt_guess = buf[4 + HEAD.itemsize - 1]
    fixed = np.dtype(HEAD.descr + [("bt", BT, (cnt_guess,))]) if cnt_guess else None
    if fixed is not None and 4 + n * fixed.itemsize == len(buf):
        a = np.frombuffer(buf, fixed, count=n, offset=4)
        if (a["cnt"] == cnt_guess).all():
            return _split(a["id"], a["lat"], a["lon"], a["bt"])
    # variable-length records: walk them one by one
    ids, lat, lon, rows = [], [], [], []
    off = 4
    for _ in range(n):
        h = np.frombuffer(buf, HEAD, count=1, offset=off)[0]
        off += HEAD.itemsize
        e = np.frombuffer(buf, BT, count=int(h["cnt"]), offset=off)
        off += BT.itemsize * int(h["cnt"])
        ids.append(h["id"]); lat.append(h["lat"]); lon.append(h["lon"]); rows.append(e)
    if off != len(buf):
        raise ValueError(f"DBL length {len(buf)} doesn't match its records ({off})")
    width = max((len(r) for r in rows), default=0)
    bt = np.zeros((n, width), BT)
    bt["flags"] = 0xFFFF           # polarisation bits 3 on padding are overwritten below
    for i, r in enumerate(rows):
        bt[i, :len(r)] = r
        bt[i, len(r):]["val"] = np.nan
    return _split(np.array(ids, "u4"), np.array(lat, "f4"), np.array(lon, "f4"), bt)


def _split(ids, lat, lon, bt):
    pol = bt["flags"] & 3
    val = bt["val"].astype(float)
    x = np.where(pol == 0, val, np.nan)
    y = np.where(pol == 1, val, np.nan)
    with np.errstate(all="ignore"):
        bx = np.nanmax(np.where(np.isfinite(x), x, -np.inf), axis=1)
        by = np.nanmax(np.where(np.isfinite(y), y, -np.inf), axis=1)
    bx[~np.isfinite(bx)] = np.nan
    by[~np.isfinite(by)] = np.nan
    fx = ((bt["flags"] & FLAG_RFI_POINT) != 0) & (pol == 0)
    return ids.astype("u4"), lat.astype(float), lon.astype(float), bx, by, fx.any(axis=1)


def reduce_points(parts):
    """Per grid point over a list of read_dbl outputs: looks (X and Y both present), hot looks at each HOT_K (X or Y
    above), looks with the RFI_POINT_SOURCE flag on X, and the largest value."""
    ids = np.concatenate([p[0] for p in parts]) if parts else np.zeros(0, "u4")
    if not len(ids):
        return {k: np.zeros(0) for k in ("id", "lat", "lon", "looks", "flag", "max_k")} | \
            {f"hot{int(t)}": np.zeros(0) for t in HOT_K}
    lat = np.concatenate([p[1] for p in parts])
    lon = np.concatenate([p[2] for p in parts])
    x = np.concatenate([p[3] for p in parts])
    y = np.concatenate([p[4] for p in parts])
    fl = np.concatenate([p[5] for p in parts])
    ok = np.isfinite(x) & np.isfinite(y)
    ids, lat, lon, x, y, fl = ids[ok], lat[ok], lon[ok], x[ok], y[ok], fl[ok]
    u, first, inv = np.unique(ids, return_index=True, return_inverse=True)
    out = {"id": u.astype("u4"), "lat": lat[first].astype("f4"), "lon": lon[first].astype("f4"),
           "looks": np.bincount(inv, minlength=len(u)).astype("u2"),
           "flag": np.bincount(inv, weights=fl, minlength=len(u)).astype("u2")}
    m = np.maximum(x, y)
    for t in HOT_K:
        out[f"hot{int(t)}"] = np.bincount(inv, weights=(m > t), minlength=len(u)).astype("u2")
    mx = np.full(len(u), -np.inf)
    np.maximum.at(mx, inv, m)
    out["max_k"] = mx.astype("f4")
    return out


# ---------------------------------------------------------------------------------------------- fetching

def products(day):
    """OPER browse half-orbits starting on `day` (UTC); a reprocessed copy of the same half-orbit keeps the highest
    file counter."""
    import sentinel_gnss as SG
    d = dt.date.fromisoformat(day)
    lo = f"{d.isoformat()}T00:00:00.000Z"
    hi = f"{(d + dt.timedelta(days=1)).isoformat()}T00:00:00.000Z"
    q = (f"contains(Name,'SM_OPER_{PRODUCT}') and ContentDate/Start ge {lo} and ContentDate/Start lt {hi}")
    url = SG.CATALOGUE + "?" + urllib.parse.urlencode({"$filter": q, "$top": "100", "$orderby": "ContentDate/Start asc"})
    req = urllib.request.Request(url, headers={"User-Agent": SG.UA})
    with urllib.request.urlopen(req, timeout=180) as r:
        rows = json.load(r).get("value", [])
    best = {}
    for r in rows:
        m = NAME_RE.search(r.get("Name", ""))
        if not m or not m.group(2).startswith(d.strftime("%Y%m%d")):
            continue
        key = (m.group(2), m.group(3))
        rank = (m.group(4), m.group(5), m.group(6))
        if key not in best or rank > best[key][0]:
            best[key] = (rank, r)
    return [v[1] for k, v in sorted(best.items())]


def fetch(day, force=False):
    """Download a day's browse half-orbits, reduce them to grid points and keep only the reduction
    (data/smos/days/<day>.npz plus a .json list of products)."""
    import sentinel_gnss as SG
    path = os.path.join(DAYS_DIR, f"{day}.npz")
    if os.path.exists(path) and not force:
        print(f"{day}: have it")
        return path
    os.makedirs(DAYS_DIR, exist_ok=True)
    prods = products(day)
    parts, used, failed = [], [], []
    for p in prods:
        s3 = p["S3Path"].replace("/eodata", "", 1).lstrip("/")
        try:
            xml = SG.s3_get("/eodata/", query={"list-type": "2", "prefix": s3 + "/", "max-keys": "20"}).decode()
            keys = [k for k in re.findall(r"<Key>([^<]+)</Key>", xml) if k.upper().endswith(".DBL")]
            if not keys:
                raise ValueError("no DBL in the product folder")
            buf = SG.s3_get("/eodata/" + keys[0])
            parts.append(read_dbl(buf))
            used.append({"name": p["Name"], "source": f"https://{SG.S3_HOST}/eodata/{keys[0]}", "bytes": len(buf)})
        except Exception as e:           # one bad half-orbit is skipped and listed, not fatal
            failed.append({"name": p.get("Name"), "error": f"{type(e).__name__}: {e}"})
    red = reduce_points(parts)
    tmp = path + ".tmp.npz"
    np.savez_compressed(tmp, **red)
    os.replace(tmp, path)
    meta = {"day": day, "product": PRODUCT, "half_orbits": len(used), "failed": failed, "products": used,
            "grid_points": int(len(red["id"])), "looks": int(red["looks"].sum()),
            "hot320_share": round(float(red["hot320"].sum() / max(1, red["looks"].sum())), 4),
            "made_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    json.dump(meta, open(os.path.join(DAYS_DIR, f"{day}.json"), "w"), indent=1)
    print(f"{day}: {len(used)} half-orbits ({len(failed)} failed), {meta['grid_points']} points, "
          f"{meta['looks']} looks, {meta['hot320_share']:.3f} above 320 K")
    return path


# ---------------------------------------------------------------------------------------------- weekly share

def days_ending(end, n):
    e = dt.date.fromisoformat(end)
    return [(e - dt.timedelta(days=k)).isoformat() for k in range(n - 1, -1, -1)]


def share(end, ndays=7, min_looks=8):
    """Per grid point over the `ndays` days ending `end`: looks, and the share of looks above each HOT_K (`hot320`
    is the measure). Points with fewer than `min_looks` looks are dropped."""
    parts = []
    for d in days_ending(end, ndays):
        p = os.path.join(DAYS_DIR, f"{d}.npz")
        if not os.path.exists(p):
            fetch(d)
        z = np.load(p)
        parts.append({k: z[k] for k in z.files})
    ids = np.concatenate([p["id"] for p in parts])
    u, first, inv = np.unique(ids, return_index=True, return_inverse=True)
    lat = np.concatenate([p["lat"] for p in parts])[first]
    lon = np.concatenate([p["lon"] for p in parts])[first]
    looks = np.bincount(inv, weights=np.concatenate([p["looks"] for p in parts]), minlength=len(u))
    out = {"id": u, "lat": lat, "lon": lon, "looks": looks}
    for k in [f"hot{int(t)}" for t in HOT_K] + ["flag"]:
        n = np.bincount(inv, weights=np.concatenate([p[k] for p in parts]), minlength=len(u))
        out[f"share_{k}"] = n / np.maximum(looks, 1)
    keep = looks >= min_looks
    out = {k: v[keep] for k, v in out.items()}
    os.makedirs(SHARE_DIR, exist_ok=True)
    np.savez_compressed(os.path.join(SHARE_DIR, f"{end}.d{ndays}.npz"), **out)
    return out


def read_share(end, ndays=7):
    p = os.path.join(SHARE_DIR, f"{end}.d{ndays}.npz")
    if not os.path.exists(p):
        return share(end, ndays)
    z = np.load(p)
    return {k: z[k] for k in z.files}


# ---------------------------------------------------------------------------------------------- radar check

def nws_check(ends, ndays=7, near_km=40.0, far_km=150.0, pad=2.0, heard=0.25):
    """Checks M1-M3 of docs/validation/smos-rfi.md, pooled over the weeks ending at `ends`; same sites, groups and
    box as SMAP's check (tools/smap_rfi.py nws_check)."""
    from cygnss_rfi import auc
    from smap_rfi import NWS_EXCLUDED, NWS_LRR, unit_ll
    names = list(NWS_LRR)
    s_lat = np.array([NWS_LRR[n][0] for n in names])
    s_lon = np.array([NWS_LRR[n][1] for n in names])
    x_lat = np.array([v[0] for v in NWS_EXCLUDED.values()])
    x_lon = np.array([v[1] for v in NWS_EXCLUDED.values()])
    box = (s_lat.min() - pad, s_lat.max() + pad, s_lon.min() - pad, s_lon.max() + pad)
    keys = ["share_hot320", "share_hot300", "share_hot350", "share_flag"]
    pooled = {k: {"near": [], "far": []} for k in keys}
    per_site = {n: [] for n in names}
    far_share = []
    for end in ends:
        t = read_share(end, ndays)
        lat, lon = t["lat"].astype(float), t["lon"].astype(float)
        inbox0 = (lat >= box[0] - 1) & (lat <= box[1] + 1) & (lon >= box[2] - 3) & (lon <= box[3] + 3)
        t = {k: v[inbox0] for k, v in t.items()}
        lat, lon = lat[inbox0], lon[inbox0]
        u = unit_ll(lat, lon)
        d = np.degrees(np.arccos(np.clip(u @ unit_ll(s_lat, s_lon).T, -1, 1))) * 111.195
        dx = np.degrees(np.arccos(np.clip(u @ unit_ll(x_lat, x_lon).T, -1, 1))) * 111.195
        dmin = d.min(1)
        inbox = (lat >= box[0]) & (lat <= box[1]) & (lon >= box[2]) & (lon <= box[3])
        near = inbox & (dmin <= near_km)
        far = inbox & (dmin > far_km) & (dx.min(1) > far_km)
        for k in keys:
            v = np.asarray(t[k], float)
            pooled[k]["near"] += list(v[near])
            pooled[k]["far"] += list(v[far])
        sh = np.asarray(t["share_hot320"], float)
        far_share += list(sh[far])
        for j, n in enumerate(names):
            i = int(np.argmin(d[:, j])) if len(d) else None
            if i is not None and d[i, j] <= near_km:
                w = d[:, j] <= near_km
                per_site[n].append({"week_end": end, "km": round(float(d[i, j]), 1), "share": round(float(sh[i]), 3),
                                    "looks": int(t["looks"][i]), "max_within": round(float(sh[w].max()), 3)})
            else:
                per_site[n].append({"week_end": end, "km": None if i is None else round(float(d[i, j]), 1),
                                    "share": None})
    out = {"weeks": list(ends), "sites": len(names), "near_points": len(pooled["share_hot320"]["near"]),
           "far_points": len(pooled["share_hot320"]["far"]), "heard_at": heard}
    for k, g in pooled.items():
        out[f"auc_{k}"] = round(auc(g["near"], g["far"]), 3) if g["near"] and g["far"] else None
        out[f"near_median_{k}"] = round(float(np.median(g["near"])), 3) if g["near"] else None
        out[f"far_median_{k}"] = round(float(np.median(g["far"])), 3) if g["far"] else None
    out["sites_heard_all_weeks"] = sum(1 for n in names
                                       if all(w["share"] is not None and w["share"] >= heard for w in per_site[n]))
    out["far_share_at_heard"] = round(float(np.mean(np.array(far_share) >= heard)), 4) if far_share else None
    out["per_site"] = per_site
    return out


def verdicts(r):
    """M1-M3 marks as frozen in docs/validation/smos-rfi.md section 3."""
    a, s, f = r["auc_share_hot320"], r["sites_heard_all_weeks"], r["far_share_at_heard"]
    return {"M1": "holds" if a is not None and a >= 0.80 else "fails" if a is None or a < 0.65 else "weakened",
            "M2": "holds" if s >= 8 else "fails" if s <= 4 else "weakened",
            "M3": "holds" if f is not None and f <= 0.05 else "fails" if f is None or f > 0.15 else "weakened"}


# ---------------------------------------------------------------------------------------------- cli

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("days", nargs="+")
    f.add_argument("--force", action="store_true")
    g = sub.add_parser("share")
    g.add_argument("end")
    g.add_argument("--days", type=int, default=7)
    n = sub.add_parser("nws", help="North Warning System check (docs/validation/smos-rfi.md)")
    n.add_argument("ends", nargs="+", help="last day of each week")
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        for day in a.days:
            try:
                fetch(day, a.force)
            except Exception as e:
                print(f"{day}: FAILED {e}", file=sys.stderr)
    elif a.cmd == "share":
        s = share(a.end, a.days)
        print(f"{len(s['id'])} points; median share above 320 K {np.median(s['share_hot320']):.3f}")
    elif a.cmd == "nws":
        r = nws_check(a.ends)
        r["verdicts"] = verdicts(r)
        os.makedirs(DATA, exist_ok=True)
        json.dump(r, open(os.path.join(DATA, "nws_check.json"), "w"), indent=1)
        print(json.dumps({k: v for k, v in r.items() if k != "per_site"}, indent=1))


if __name__ == "__main__":
    main()
