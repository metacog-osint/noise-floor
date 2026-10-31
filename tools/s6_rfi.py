#!/usr/bin/env python3
"""s6_rfi.py: GPS interference heard by Sentinel-6A's GNSS receiver (step P of docs/space-sensors-plan.md).

Sentinel-6 Michael Freilich (NORAD 46984; 66 deg inclination, about 1,336 km) carries JPL's TriG receiver. PO.DAAC
publishes its RO-POD antenna's tracking data as hourly RINEX 3.03 files (collection JASON_CS_S6A_L1B_GNSS_RO_POD_HOURLY:
1 Hz, GPS S1C S1W S2W S2X; about 14 files and 195 MB a day; downloads with an Earthdata token). The header says the
signal strength is in dB-Hz, but the values (about 20 to 1,700) are amplitude ratios (V/V), as in COSMIC-2's TriG files,
so they are converted with 20 log10. A constant offset doesn't matter: the index works on residuals.

Geometry reuses tools/sentinel_gnss.py (step E): Space-Track element sets with SGP4 for the spacecraft, broadcast
ephemerides from BKG for GPS, elevation in a frame whose up axis points away from the Earth's centre. The index is
tools/rx_rfi.py (median residual across links against the receiver's elevation-bin baseline). The map uses the
back-projection of tools/cosmic2_rfi.py.

Commands
  fetch DAY...                  hourly files from PO.DAAC (in memory, not kept) -> data/s6rfi/days/<day>.parquet
                                (one row per link and second: t, sat, s1c, s1w, s2w, el, az, lat, lon, alt_km)
  index DAY... [--signal s1c]   -> data/s6rfi/days/<day>.idx.parquet (t, lat, lon, idx, n, down)
  grid DAY... [--radius-km R] [--drop-db D]
                                -> data/s6rfi/grid/<day>.r2.k<R>.parquet (same columns as cosmic2_rfi grids)
  pairs DAY... [--radius-km R]  aircraft-map scores (as cosmic2_rfi pairs)

Data: Sentinel-6 GNSS-RO-POD tracking data (EUMETSAT/NASA-JPL via PO.DAAC; registry row `sentinel6-ro`); orbital data
USSPACECOM (space-track.org); broadcast navigation IGS via BKG.
"""
import argparse
import datetime as dt
import gzip
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

DATA = os.path.join(ROOT, "data", "s6rfi")
DAYS_DIR = os.path.join(DATA, "days")
GRID_DIR = os.path.join(DATA, "grid")
CMR = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
SHORT_NAME = "JASON_CS_S6A_L1B_GNSS_RO_POD_HOURLY"
UNIT, NORAD = "S6A", 46984          # Space-Track satcat: "S6 MICHAEL FREILICH", launched 21 Nov 2020 (checked 31 Oct 2026)
SIGS = ("s1c", "s1w", "s2w")
RADIUS_KM = 3000.0                  # horizon from 1,336 km is about 3,800 km
DROP_DB = 3.0


def files(day):
    import requests
    p = {"short_name": SHORT_NAME, "page_size": 100, "temporal": f"{day}T00:00:00Z,{day}T23:59:59Z"}
    items = requests.get(CMR, params=p, timeout=60).json().get("items", [])
    urls = []
    for it in items:
        u = [x["URL"] for x in it["umm"].get("RelatedUrls", []) if x["URL"].startswith("https") and x["URL"].endswith(".rnx")]
        urls += u[:1]
    return sorted(set(urls))


def _session():
    import requests
    tok = os.environ.get("EARTHDATA_TOKEN")
    if not tok:
        raise SystemExit("EARTHDATA_TOKEN is not set (an Earthdata Login bearer token is needed for PO.DAAC).")
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {tok}"
    return s


def fetch(day, force=False):
    import pyarrow as pa
    import pyarrow.parquet as pq
    import sentinel_gnss as SG
    import station_cn0 as SC
    os.makedirs(DAYS_DIR, exist_ok=True)
    out = os.path.join(DAYS_DIR, f"{day}.parquet")
    if os.path.exists(out) and not force:
        print(f"{day}: have it")
        return out
    d = dt.date.fromisoformat(day)
    urls = files(day)
    if not urls:
        print(f"{day}: no Sentinel-6A tracking files listed")
        return None
    s = _session()
    t0, nbytes = time.time(), 0
    T, S, V = [], [], {c: [] for c in SIGS}
    for u in urls:
        for attempt in range(4):
            try:
                r = s.get(u, timeout=300)
                r.raise_for_status()
                break
            except Exception as e:
                if attempt == 3:
                    raise
                time.sleep(15 * (attempt + 1))
        nbytes += len(r.content)
        _, t, sat, vals = SG.parse_rinex(r.content.decode("ascii", "replace").splitlines(), d)
        m = (t >= 0) & (t < 86400) & np.char.startswith(sat, "G")
        T.append(t[m])
        S.append(sat[m])
        for c in SIGS:
            V[c].append(vals[c][m])
    t, sat = np.concatenate(T), np.concatenate(S)
    vals = {c: np.concatenate(V[c]) for c in SIGS}
    key = np.round(t).astype(np.int64) * 100 + np.array([int(x[1:]) for x in sat])
    _, first = np.unique(key, return_index=True)               # consecutive files overlap
    t, sat, vals = t[first], sat[first], {c: v[first] for c, v in vals.items()}
    # geometry, as tools/sentinel_gnss.py does it
    SG.UNITS.setdefault(UNIT, ("SENTINEL-6", NORAD))
    store = SG.ensure_elements(d, [UNIT])
    sets = (store.get(str(NORAD)) or {}).get("sets", [])
    nav = SG.held_nav(d) or SG.fetch_nav(d)
    with gzip.open(nav, "rt", encoding="ascii", errors="replace") as f:
        eph = SC.parse_nav(f.read())
    t_ep, g = np.unique(t, return_inverse=True)
    day_unix = dt.datetime.combine(d, dt.time(), dt.timezone.utc).timestamp()
    pos, vel, age = SG.spacecraft_ecef(sets, day_unix + t_ep - SG.LEAP)
    up, fwd, right = SG.frames(pos, vel)
    lat, lon, alt = SG.geodetic(pos)
    gx = SG.gnss_positions(eph, sat, SC.gps_seconds(day) + t)
    el, az = SG.look(pos[g], up[g], fwd[g], right[g], gx)
    tab = {"t": np.round(t).astype(np.int32), "sat": sat, **{c: vals[c].astype(np.float32) for c in SIGS},
           "el": el.astype(np.float32), "az": az.astype(np.float32), "lat": lat[g].astype(np.float32),
           "lon": lon[g].astype(np.float32), "alt_km": alt[g].astype(np.float32)}
    pq.write_table(pa.table(tab), out, compression="zstd")
    fin = np.isfinite(alt)
    meta = {"day": day, "files": len(urls), "bytes": nbytes, "rows": int(len(t)), "epochs": int(len(t_ep)),
            "rows_without_geometry": int(np.isnan(el).sum()),
            "alt_km": [round(float(alt[fin].min()), 1), round(float(alt[fin].max()), 1)] if fin.any() else None,
            "elset_max_age_h": round(float(age[np.isfinite(age)].max()), 2) if np.isfinite(age).any() else None,
            "nav": os.path.basename(nav), "seconds": round(time.time() - t0)}
    json.dump(meta, open(os.path.join(DAYS_DIR, f"{day}.json"), "w"), indent=1)
    print(f"{day}: {len(urls)} files, {nbytes / 1e6:.0f} MB, {meta['epochs']} epochs, {meta['rows']} rows, "
          f"alt {meta['alt_km']} km, {meta['seconds']} s")
    return out


def to_db(v):
    v = np.asarray(v, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(v > 0, 20.0 * np.log10(v), np.nan)


def index(day, signal="s1c", drop_db=DROP_DB):
    import pyarrow as pa
    import pyarrow.parquet as pq
    import rx_rfi as R
    t = pq.read_table(os.path.join(DAYS_DIR, f"{day}.parquet")).to_pydict()
    ep = R.epoch_index(np.asarray(t["t"]), np.full(len(t["t"]), UNIT), np.asarray(t["sat"]), np.asarray(t["el"]),
                       to_db(t[signal]), drop_db=drop_db)
    # position per epoch
    tt = np.asarray(t["t"])
    first = {}
    for i, x in enumerate(tt):
        first.setdefault(int(x), i)
    lat = np.array([t["lat"][first[int(x)]] for x in ep["t"]], np.float32)
    lon = np.array([t["lon"][first[int(x)]] for x in ep["t"]], np.float32)
    out = os.path.join(DAYS_DIR, f"{day}.idx.parquet")
    pq.write_table(pa.table({"t": ep["t"].astype(np.int32), "lat": lat, "lon": lon, "idx": ep["idx"].astype(np.float32),
                             "n": ep["n"].astype(np.int16), "down": ep["down"].astype(np.float32)}), out, compression="zstd")
    print(f"{day}: {len(ep['t'])} epochs indexed ({signal}); median {np.median(ep['idx']):+.2f} dB, "
          f"{np.mean(ep['idx'] <= -drop_db):.3f} at -{drop_db:g} dB or lower")
    return out


def grid(day, res=2, radius_km=RADIUS_KM, drop_db=DROP_DB):
    import pyarrow as pa
    import pyarrow.parquet as pq
    import cosmic2_rfi as C2
    t = pq.read_table(os.path.join(DAYS_DIR, f"{day}.idx.parquet")).to_pydict()
    day_unix = int(dt.datetime.combine(dt.date.fromisoformat(day), dt.time(), dt.timezone.utc).timestamp())
    tu = day_unix + np.asarray(t["t"], np.int64)
    n = len(tu)
    b = C2.bins(tu, np.full(n, 6), np.zeros(n, int), -np.asarray(t["idx"], float), t["lat"], t["lon"], thr=drop_db)
    ids, ll, cen = C2.cells(res, max_lat=85.0)
    n_vis, s = C2.backproject(b["pos"], b["f"], cen, radius_km)
    corr = C2.corr_score(n_vis, s, b["f"])
    ok = n_vis >= C2.MIN_VIS
    os.makedirs(GRID_DIR, exist_ok=True)
    out = grid_name(day, res, radius_km)
    pq.write_table(pa.table({"h3": [c for c, k in zip(ids, ok) if k], "lat": ll[ok, 0], "lon": ll[ok, 1],
                             "n_vis": n_vis[ok].astype(np.int32), "share": (s[ok] / n_vis[ok]).astype(np.float32),
                             "score": corr[ok].astype(np.float32)}), out, compression="zstd")
    print(f"{day}: {int(ok.sum())} cells scored, {len(b['f'])} bins, flagged share {np.mean(b['f']):.3f}")
    return out


def grid_name(day, res, radius_km, halves=False):
    return os.path.join(GRID_DIR, f"{day}.r{res}.k{int(radius_km)}.parquet")


def read_grid(day, res=2, radius_km=RADIUS_KM, halves=False):
    import pyarrow.parquet as pq
    p = grid_name(day, res, radius_km)
    return {r["h3"]: r for r in pq.read_table(p).to_pylist()} if os.path.exists(p) else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("days", nargs="+")
    f.add_argument("--force", action="store_true")
    i = sub.add_parser("index")
    i.add_argument("days", nargs="+")
    i.add_argument("--signal", default="s1c", choices=SIGS)
    i.add_argument("--drop-db", type=float, default=DROP_DB)
    for name in ("grid", "pairs"):
        g = sub.add_parser(name)
        g.add_argument("days", nargs="+")
        g.add_argument("--res", type=int, default=2)
        g.add_argument("--radius-km", type=float, default=RADIUS_KM)
        g.add_argument("--drop-db", type=float, default=DROP_DB)
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        for day in a.days:
            try:
                fetch(day, a.force)
            except Exception as e:
                print(f"{day}: FAILED {e}", file=sys.stderr)
    elif a.cmd == "index":
        for day in a.days:
            index(day, a.signal, a.drop_db)
    elif a.cmd == "grid":
        for day in a.days:
            grid(day, a.res, a.radius_km, a.drop_db)
    elif a.cmd == "pairs":
        import cosmic2_rfi as C2
        print(json.dumps(C2.summary(a.days, a.res, a.radius_km, reader=read_grid), indent=1))


if __name__ == "__main__":
    main()
