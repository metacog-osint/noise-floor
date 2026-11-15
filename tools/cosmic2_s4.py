#!/usr/bin/env python3
"""cosmic2_s4.py: limb S4 from COSMIC-2's navigation-antenna links, per H3 cell and UTC hour.

What it measures: limb S4 measured along radio-occultation paths, which reads higher than a ground receiver's S4.

UCAR's level-1b `podTc2` files (one per receiver-GNSS link, 1 Hz; registry row `cosmic2-ro`) carry `S4` ("S4
scintillation index", unitless, fill -999) beside the RFI index that tools/cosmic2_rfi.py reads, and both satellites'
positions (`x_LEO`... at reception, `x_GPS`... at transmission, km, Earth-fixed). This tool keeps the samples of GPS
links (`conid` G) that pass below the receiver's horizon (`elevation` < 0), places each at the ray's tangent point (the
point of the straight LEO-GPS line closest to the Earth's centre) and keeps those whose tangent point lies 150-500 km
above the WGS84 ellipsoid. GLONASS links in the same archive are left out.

Each sample sits at a nominal place. The scintillation can come from anywhere the ray crosses the F region, which for
these heights is up to about 2,000 km either side of the tangent point along the line of sight (straight-line
geometry, F region taken as 250-450 km). Across the line of sight the place is good to tens of km.

UCAR's on-board S4 is one value per 10 s (computed from 50 Hz signal-to-noise ratio), repeated at each 1 Hz sample,
and a track is written again in each later dump; so seconds are made unique per link, the first 60 s of each track
are dropped (UCAR warns of spurious high values there), and each 10 s value counts once.

Per H3 res-1 cell (about 840 km across) and UTC hour, the day file gives the number of 10 s values, the number of
links, the 95th percentile (only from 10 values), the maximum, the local solar time at the cell centre and the share
of values taken while UCAR's RFI index was raised. Res 1 because the place along the ray is uncertain by about
2,000 km either side, and because at res 2 only 16% of cell-hours reach 10 values (66% at res 1; 13 Nov 2026).

Commands
  day DAY... [--no-upload]   stream the day's podTc2 archive from UCAR (no file is kept from the archive) and write
                             data/swx/<day>.cosmic2-limb-s4.json; tools/cosmic2_job.py is the daily job that also
                             makes the interference day file in the same pass

Data: UCAR CDAAC COSMIC-2 near-real-time level 1b (UCAR data terms, CC BY 4.0). Validation:
docs/validation/cosmic2-limb-s4.md.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
OUT = os.path.join(ROOT, "data", "swx")

FEED = "cosmic2-limb-s4"
VERSION = "1.0"                    # frozen in docs/validation/cosmic2-limb-s4.md section 2
LABEL = "Limb S4 measured along radio-occultation paths, which reads higher than a ground receiver's S4"
TANGENT_KM = (150.0, 500.0)        # tangent-point height band, km above the WGS84 ellipsoid
RES = 1                            # H3 resolution (cells about 840 km across)
MIN_P95 = 10                       # samples needed before a cell-hour gets a 95th percentile
SATS = [f"C2E{i}" for i in range(1, 7)]
FILL = -999.0
GPS_UNIX = 315964800               # GPS epoch (6 Jan 1980) in Unix seconds
LEAP = 18                          # GPS - UTC since 1 Jan 2017
A_WGS = 6378.137                   # WGS84, km
F_WGS = 1 / 298.257223563
E2 = F_WGS * (2 - F_WGS)
COLUMNS = ["cell", "lat", "lon", "n", "links", "p95", "max", "lst", "rfi"]
COLUMN_NOTES = {
    "cell": "H3 res-1 cell of the tangent points", "lat": "cell centre, deg", "lon": "cell centre, deg",
    "n": "10 s limb S4 values in the cell-hour (UCAR's on-board S4 is one value per 10 s)",
    "links": "receiver-GPS links that gave them",
    "p95": "95th percentile of the values (linear interpolation); null below 10 values",
    "max": "largest value",
    "lst": "mean local solar time at the cell centre at the cell-hour's median time, hours",
    "rfi": "share of the values taken while UCAR's RFI index was at or above its threshold (1e-4); interference can "
           "raise on-board S4, and the index does not always catch it"}
CREDIT = ["COSMIC-2 data: UCAR COSMIC Program (CDAAC), near-real-time level 1b podTc2 (CC BY 4.0)"]
LICENCE = "CC BY 4.0. Derived from UCAR CDAAC COSMIC-2 data (UCAR data terms: CC BY 4.0)"
LOCATION = ("Each sample is placed at the ray's tangent point: the point of the straight receiver-GPS line closest to "
            "the Earth's centre. The scintillation can lie anywhere the ray crosses the F region, up to about 2,000 km "
            "either side of that point along the line of sight, so a cell is a nominal place. Across the line of "
            "sight the place is good to tens of km.")


# ---------------------------------------------------------------------------------------------- geometry

def geodetic(xyz):
    """Earth-fixed km -> (lat deg, lon deg, height km above the WGS84 ellipsoid)."""
    xyz = np.asarray(xyz, float)
    x, y, z = xyz[..., 0], xyz[..., 1], xyz[..., 2]
    p = np.hypot(x, y)
    lat = np.arctan2(z, p * (1 - E2))
    for _ in range(6):
        n = A_WGS / np.sqrt(1 - E2 * np.sin(lat) ** 2)
        h = p * np.cos(lat) + z * np.sin(lat) - A_WGS * np.sqrt(1 - E2 * np.sin(lat) ** 2)
        lat = np.arctan2(z, p * (1 - E2 * n / (n + h)))
    h = p * np.cos(lat) + z * np.sin(lat) - A_WGS * np.sqrt(1 - E2 * np.sin(lat) ** 2)
    return np.degrees(lat), np.degrees(np.arctan2(y, x)), h


def tangent_point(leo, gps):
    """Closest point to the Earth's centre on each straight LEO->GPS segment, and whether it lies between the two
    (it does for every link below the receiver's horizon)."""
    leo, gps = np.asarray(leo, float), np.asarray(gps, float)
    d = gps - leo
    length = np.linalg.norm(d, axis=-1)
    u = d / length[..., None]
    s = -(leo * u).sum(-1)
    return leo + s[..., None] * u, (s > 0) & (s < length)


# ---------------------------------------------------------------------------------------------- one link

def _attr(a, k, default=None):
    v = a.get(k, default)
    return v.decode() if isinstance(v, bytes) else v


def constellation(name, attrs):
    """'G' for GPS: the file's `conid`, or the letter before the PRN in the file name (...0034.R18.02_...)."""
    c = _attr(attrs, "conid")
    if c:
        return str(c).strip()[:1]
    parts = name.split(".")
    return parts[5][:1] if len(parts) > 5 else ""


def sat_of(name):
    """'podTc2_C2E2.2026.317...' -> 'C2E2'."""
    return name.split("_")[1].split(".")[0] if "_" in name else ""


def link_key(name, attrs):
    """One integer per receiver antenna and GPS satellite: satellite * 1000 + antenna * 100 + PRN."""
    sat = int(sat_of(name)[3:] or 0)
    return sat * 1000 + int(attrs.get("antenna_id", 0)) * 100 + int(attrs.get("prn_id", 0))


def limb_samples(f, name, band=TANGENT_KM):
    """One podTc2 link (an open scipy netcdf_file) -> (dict of per-second arrays or None, reason). Keeps GPS seconds
    with a valid S4, the link below the receiver's horizon and the tangent point inside `band`. `t` is GPS seconds
    (whole); `since` counts seconds from the file's first sample (each file starts where its track starts); `rfi` is
    UCAR's RFI index in the same second (cosmic2_rfi.py)."""
    V, A = f.variables, f._attributes
    if constellation(name, A) != "G":
        return None, "not GPS"
    if "S4" not in V or "elevation" not in V:
        return None, "no S4"
    s4 = np.asarray(V["S4"][:], float)
    el = np.asarray(V["elevation"][:], float)
    t = np.round(float(A["start_time"]) + np.asarray(V["time"][:], float)).astype(np.int64)
    ok = np.isfinite(s4) & (s4 != FILL) & (s4 >= 0) & (s4 <= 9999) & np.isfinite(el) & (el < 0)
    if not ok.any():
        return None, "no limb samples"
    leo = np.stack([np.asarray(V[k][:], float) for k in ("x_LEO", "y_LEO", "z_LEO")], axis=1)
    gps = np.stack([np.asarray(V[k][:], float) for k in ("x_GPS", "y_GPS", "z_GPS")], axis=1)
    tp, between = tangent_point(leo[ok], gps[ok])
    lat, lon, h = geodetic(tp)
    keep = between & (h >= band[0]) & (h <= band[1])
    if not keep.any():
        return None, "no limb samples"
    rfi = np.asarray(V["RFI"][:], float) if "RFI" in V else np.full(len(t), FILL)
    idx = np.flatnonzero(ok)[keep]
    return {"t": t[idx], "since": (t[idx] - t.min()).astype(np.int64), "lat": lat[keep], "lon": lon[keep],
            "h": h[keep], "s4": s4[idx], "rfi": rfi[idx],
            "key": np.full(len(idx), link_key(name, A), np.int64)}, "ok"


WINDOW_S = 10                      # UCAR's on-board S4 is one value per 10 s, repeated at each 1 Hz sample
TRACK_SKIP_S = 60                  # seconds dropped at the start of each track (UCAR: spurious high S4 there)
RFI_THR = 1e-4                     # UCAR's RFI_threshold attribute


def windows(smp, skip_s=TRACK_SKIP_S, window_s=WINDOW_S):
    """Per-second limb samples (possibly repeated across overlapping link files) -> one row per 10 s S4 value.

    UCAR's link files overlap: a track is written again, from its start, in each later dump, with the same values in
    the shared seconds. So seconds are first made unique per link. Seconds within `skip_s` of the track's start are
    dropped. A window is a run of seconds of one link with the same S4 value, at most `window_s` long and with no gap
    longer than `window_s`; it is placed at its middle second. `rfi` is True when UCAR's RFI index reached its
    threshold in any of the window's seconds. Times are Unix seconds, UTC."""
    keys = ("t", "lat", "lon", "h", "s4", "rfi", "link")
    if not len(smp["t"]):
        return {k: np.zeros(0) for k in keys}
    key, t = np.asarray(smp["key"], np.int64), np.asarray(smp["t"], np.int64)
    order = np.lexsort((t, key))
    key, t = key[order], t[order]
    first = np.r_[True, (np.diff(key) != 0) | (np.diff(t) != 0)]
    # a second can appear with a smaller `since` in a file that started later; keep the largest
    since = np.maximum.reduceat(np.asarray(smp["since"])[order], np.flatnonzero(first))
    sel = order[first]
    key, t = key[first], t[first]
    s4 = np.asarray(smp["s4"], float)[sel]
    keep = since >= skip_s
    sel, key, t, s4 = sel[keep], key[keep], t[keep], s4[keep]
    if not len(t):
        return {k: np.zeros(0) for k in keys}
    # windows: a new one starts at a new link, a new value, a gap, or window_s after the current one began
    wid = np.zeros(len(t), np.int64)
    w, start = 0, t[0]
    for i in range(1, len(t)):
        if key[i] != key[i - 1] or s4[i] != s4[i - 1] or t[i] - t[i - 1] > window_s or t[i] - start >= window_s:
            w += 1
            start = t[i]
        wid[i] = w
    bounds = np.r_[0, np.flatnonzero(np.diff(wid)) + 1, len(t)]
    mid = np.array([(a + b - 1) // 2 for a, b in zip(bounds[:-1], bounds[1:])])
    rfi = np.asarray(smp["rfi"], float)[sel] >= RFI_THR
    flag = np.maximum.reduceat(rfi.astype(int), bounds[:-1]).astype(bool)
    pick = sel[mid]
    return {"t": t[mid] + GPS_UNIX - LEAP, "lat": np.asarray(smp["lat"])[pick], "lon": np.asarray(smp["lon"])[pick],
            "h": np.asarray(smp["h"])[pick], "s4": s4[mid], "rfi": flag, "link": key[mid]}


class Limb:
    """Collects limb samples from every link file of one streamed day (pass `add` as cosmic2_rfi.reduce_stream's
    on_link and `reset` as fetch's on_retry); `samples()` gives one row per 10 s S4 value."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.parts, self.reasons, self.sats = [], {}, {}

    def add(self, name, f):
        try:
            d, why = limb_samples(f, name)
        except Exception as e:                       # one odd file must not stop the day
            d, why = None, f"unreadable ({type(e).__name__})"
        self.reasons[why] = self.reasons.get(why, 0) + 1
        s = sat_of(name)
        self.sats.setdefault(s, 0)
        if d is None:
            return
        self.sats[s] += 1
        self.parts.append(d)

    def raw(self):
        if not self.parts:
            return {k: np.zeros(0) for k in ("t", "since", "lat", "lon", "h", "s4", "rfi", "key")}
        return {k: np.concatenate([p[k] for p in self.parts]) for k in self.parts[0]}

    def samples(self, skip_s=TRACK_SKIP_S):
        return windows(self.raw(), skip_s)


# ---------------------------------------------------------------------------------------------- one day

def day_start(day):
    return datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()


def cell_hours(smp, day, res=RES, min_p95=MIN_P95):
    """10 s S4 values (windows()) -> {hour: [[cell, lat, lon, n, links, p95, max, lst, rfi], ...]} for the UTC day;
    values of other days are dropped. n counts 10 s values; p95 is None below `min_p95` of them. lst is the mean local
    solar time (hours) at the cell centre at the cell-hour's median time. rfi is the share of the values taken while
    UCAR's RFI index was at or above its threshold."""
    import h3
    t = np.asarray(smp["t"], float)
    hr = np.floor((t - day_start(day)) / 3600.0).astype(np.int64)
    m = (hr >= 0) & (hr < 24)
    if not m.any():
        return {}
    t, hr = t[m], hr[m]
    lat, lon = np.asarray(smp["lat"], float)[m], np.asarray(smp["lon"], float)[m]
    s4, link = np.asarray(smp["s4"], float)[m], np.asarray(smp["link"])[m]
    rfi = np.asarray(smp["rfi"], bool)[m]
    cell = np.array([h3.latlng_to_cell(a, b, res) for a, b in zip(lat.tolist(), lon.tolist())])
    ucell, ci = np.unique(cell, return_inverse=True)
    key = hr * len(ucell) + ci
    order = np.argsort(key, kind="stable")
    key = key[order]
    starts = np.r_[0, np.flatnonzero(np.diff(key)) + 1]
    ends = np.r_[starts[1:], len(key)]
    centre = {c: h3.cell_to_latlng(c) for c in ucell.tolist()}
    out = {}
    for a, b in zip(starts.tolist(), ends.tolist()):
        idx = order[a:b]
        h, c = int(key[a] // len(ucell)), str(ucell[int(key[a] % len(ucell))])
        v = s4[idx]
        n = len(v)
        la, lo = centre[c]
        tm = float(np.median(t[idx]))
        lst = ((tm - day_start(day)) / 3600.0 + lo / 15.0) % 24.0
        out.setdefault(h, []).append([c, round(la, 2), round(lo, 2), n, int(len(np.unique(link[idx]))),
                                      round(float(np.percentile(v, 95)), 3) if n >= min_p95 else None,
                                      round(float(v.max()), 3), round(lst, 1), round(float(rfi[idx].mean()), 2)])
    return out


def build(day, limb, source=None, now=None, extra_problems=()):
    """The day file (a dict). `limb` is a filled Limb; `source` describes the UCAR archive (url, bytes, ...)."""
    now = now or datetime.now(timezone.utc)
    raw = limb.raw()
    smp = windows(raw)
    ch = cell_hours(smp, day)
    hours = [{"hour": f"{day}T{h:02d}:00Z", "cells": sorted(ch.get(h, []), key=lambda r: r[0])} for h in range(24)]
    problems = list(extra_problems)
    empty = [h["hour"][11:16] for h in hours if not h["cells"]]
    if empty:
        problems.append(f"no limb samples in {len(empty)} UTC hour(s): {', '.join(empty)}")
    silent = [s for s in SATS if not limb.sats.get(s)]
    if silent:
        problems.append(f"no GPS limb links from {', '.join(silent)}")
    bad = sum(v for k, v in limb.reasons.items() if k.startswith("unreadable"))
    if bad:
        problems.append(f"{bad} link file(s) could not be read")
    cells = [r for h in hours for r in h["cells"]]
    return {
        "feed": FEED, "version": VERSION, "day": day,
        "as_of": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "measure": LABEL,
        "sources": ["cosmic2-ro"], "credit": CREDIT, "licence": LICENCE,
        "method": {"tool": "tools/cosmic2_s4.py", "validation": "docs/validation/cosmic2-limb-s4.md",
                   "signal": "UCAR's podTc2 S4: computed on board the COSMIC-2 receiver every 10 s from 50 Hz GPS "
                             "signal-to-noise ratio, navigation antennas, no noise correction",
                   "links": "GPS links below the receiver's horizon (elevation < 0); GLONASS links left out",
                   "tangent_km": list(TANGENT_KM), "height": "above the WGS84 ellipsoid",
                   "track_start_dropped_s": TRACK_SKIP_S, "grid": f"H3 res {RES}", "p95_min_values": MIN_P95,
                   "location": LOCATION},
        "columns": COLUMNS, "column_notes": COLUMN_NOTES,
        "hours": hours,
        "satellites": sorted(s for s, n in limb.sats.items() if n),
        "counts": {"links": int(len(np.unique(smp["link"]))), "values": int(len(smp["t"])),
                   "seconds": int(len(np.unique(np.asarray(raw["key"]) * 10**10 + np.asarray(raw["t"])))),
                   "cell_hours": len(cells), "with_p95": sum(1 for r in cells if r[5] is not None),
                   "hours_with_data": 24 - len(empty), "link_files": dict(sorted(limb.reasons.items()))},
        "source": source or {},
        "problems": problems,
    }


def write(doc, out_dir=OUT):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{doc['day']}.{FEED}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"), ensure_ascii=False)
    return path


def keep_raw(day, limb, out_dir=OUT):
    """Diagnostics: the day's per-second limb samples -> data/swx/raw/<day>.parquet (not published)."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    d = os.path.join(out_dir, "raw")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"{day}.parquet")
    pq.write_table(pa.table(limb.raw()), p, compression="zstd")
    return p


def run_day(day, stream="nrt", raw=False):
    """Stream one day for limb S4 alone (the RFI table is written too, as cosmic2_rfi.fetch always does)."""
    import cosmic2_rfi as C2
    limb = Limb()
    t0 = time.time()
    C2.fetch(day, force=True, stream=stream, on_link=limb.add, on_retry=limb.reset)
    doc = build(day, limb, {"url": C2.url_for(day, stream), "read_seconds": round(time.time() - t0)})
    if raw:
        keep_raw(day, limb)
    return write(doc), doc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("day")
    d.add_argument("days", nargs="+")
    d.add_argument("--raw", action="store_true", help="also keep the per-second samples (diagnostics)")
    a = ap.parse_args(argv)
    for day in a.days:
        path, doc = run_day(day, raw=a.raw)
        c = doc["counts"]
        print(f"{day}: {c['links']} limb links, {c['values']} 10 s values, {c['cell_hours']} cell-hours "
              f"({c['with_p95']} with p95) -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
