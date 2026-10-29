#!/usr/bin/env python3
"""station_cn0.py: GNSS interference at fixed ground reference stations, from C/N0 in RINEX observation files.

A jammer raises the noise floor for every satellite on the band it covers, so a station's C/N0 drops on all satellites at
once. Multipath, obstructions and scintillation hit a few satellites at a time. The rule below looks for the first pattern,
against the station's own behaviour at the same sidereal time on quiet days.

  python tools/station_cn0.py stations [--lat 54.8 --lon 20.0 --max-km 500 --day 2026-05-09]   # EPN stations by distance
  python tools/station_cn0.py stations --network noaa --lat 40.0 --lon -105.2 --max-km 150     # NOAA CORS stations
  python tools/station_cn0.py fetch LAMA00POL 2026-05-09 [2026-05-16 ...]                     # obs + broadcast nav
  python tools/station_cn0.py day LAMA00POL 2026-05-09 [--baseline d1,d2,...]                  # one station-day
  python tools/station_cn0.py test [--stations A,B --days d1,d2 --quiet q1,q2]                 # the pre-stated Baltic test
  python tools/station_cn0.py test --stations ... --days ... --quiet ... --exclude-file F --windows W.json --out R.json

Stations: a 9-character name (LAMA00POL) is an EPN/IGS station at BKG; a 4-character id (P041) is a NOAA CORS (NCN) station.

Data:
  * EPN/IGS: daily 30 s RINEX 3 observation files (Hatanaka-compressed) from the BKG GNSS Data Center (igs.bkg.bund.de,
    anonymous HTTPS). EPN data: CC BY 4.0 unless the station operator declares CC0 (EPN Data Access and Use Policy,
    2 Jul 2026); IGS data: open, attribution required.
  * NOAA CORS: daily 30 s RINEX 2.11 files ssssDDD0.YYd.gz (Hatanaka) from the NOAA Open Data Dissemination bucket
    noaa-cors-pds (anonymous HTTPS; NGS retires the geodesy.noaa.gov/corsdata/ paths on 1 Nov 2026). Station
    positions: the NGS NAD83(2011) composite on the same bucket. Open for any use; credit NOAA, don't imply endorsement,
    and don't present modified data as original NOAA data (AWS Registry of Open Data, noaa-ncn).
  * Broadcast navigation for both: the merged RINEX 3 file from BKG (IGS).
Outputs go to data/stations/ (gitignored): <STATION>/<day>.json and .png, and test_results.json (or --out).

Rule (docs/validation/ground-stations.md has the reasoning and sources):
  * Signals: GPS L1 C/A (S1C) decides. GPS L2 (S2W, else S2L/S2X), GPS L5 (S5Q/S5X/S5I), Galileo E1 (S1C/S1X) and
    Galileo E5a (S5Q/S5X) are reported only. Elevation mask 15 deg from the broadcast ephemeris.
  * GPS baseline, per satellite: the median, over the baseline days, of the C/N0 the satellite had at the same place in
    the station's sky. GPS sky tracks repeat about 247 s earlier each day; within +-15 min of a nominal 246 s/day shift,
    the baseline-day epoch whose az/el is closest (within 1 deg) is used. At least 3 baseline days are needed.
    A satellite the baseline days tracked there but which is missing on the test day counts as a drop (loss of lock,
    residual LOSS_DB). Galileo: pooled median of all Galileo satellites per 2.5 deg elevation bin; no loss counting.
  * Per epoch: D = median residual over satellites (at least 4); F = share of satellites at least 3 dB-Hz down.
  * Flag: centred 5-min running medians of D <= -3 dB-Hz and of F >= 0.75. Runs merge across gaps of up to 2 min and
    must last at least 2 min.
  * Baseline days: the 5 nearest days (+-21) that are quiet for that station in the aircraft daily tables (share of bad
    aircraft-hexes within 150 km at or below the station's median), excluding the listed jammed days and any days in
    --exclude-file. Without daily tables (before Oct 2025): the 6 nearest days, unscreened.
  * A station-day counts toward a verdict only if GPS L1 C/A was scored on at least half of its epochs (inside the
    windows, when --windows gives them for that day); otherwise it is NO DATA.
  * RINEX 2.11 (NOAA CORS) has no tracking-mode letter: S1 is taken as L1 C/A, S2 as L2 (semi-codeless P(Y) on the
    receivers checked), S5 as L5. RINEX 2 doesn't fix the signal-strength unit; NOAA's files carry dB-Hz (checked on
    a Trimble Alloy file), which is assumed for all.
Times: RINEX epochs are GPS time; aircraft minutes and outputs are UTC (GPS - 18 s since 2017).
"""
import argparse, gzip, json, math, os, re, statistics, sys, urllib.request, warnings
from datetime import date, datetime, timedelta, timezone

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "stations")
RAW = os.path.join(OUT, "raw")
CACHE = os.path.join(OUT, "cache")
TRACE = os.path.join(ROOT, "data", "trace_box")
YEAR = os.path.join(ROOT, "data", "pnt", "year")

BKG = "https://igs.bkg.bund.de/root_ftp"
EPN_LIST = "https://epncb.oma.be/pub/station/general/EPN_stations.txt"
NOAA = "https://noaa-cors-pds.s3.amazonaws.com"
NOAA_COORDS = NOAA + "/coord/coord_20/nad83_2011_geo.comp.txt"
UA = {"User-Agent": "noise-floor station_cn0 (+https://github.com/metacog-osint/noise-floor)"}
KALININGRAD = (54.8, 20.0)          # Kaliningrad coast reference point used throughout the Baltic validation

STEP = 30                           # s, daily RINEX sampling
NEP = 86400 // STEP
LEAP = 18                           # GPS - UTC, s (since 1 Jan 2017)
GPS0 = datetime(1980, 1, 6, tzinfo=timezone.utc)
MASK_DEG = 15.0
SHIFT_S = 246.0                     # centre of the search: GPS sky tracks repeat ~247 s earlier per day (Agnew & Larson 2007)
WINDOW_S = 900
TOL_DEG = 1.0
MIN_BASE = 3
MIN_SATS = 4
DROP_DB = 3.0                       # per-satellite drop that counts toward F
D_THR = -3.0                        # station median residual threshold, dB-Hz
F_THR = 0.75
WIN = 11                            # 5 min of 30 s epochs, centred
MERGE_S = 120
MIN_RUN_S = 120
LOSS_DB = -40.0                     # residual given to a lost satellite (acts as -inf in medians and thresholds)
RADIUS_KM = 150.0
MIN_REPORTS = 20                    # aircraft reports per minute for the share to count
MIN_SCORED = 0.5                    # share of epochs GPS L1 C/A must be scored on for a station-day to count

SIGNALS = {   # name: (system, codes by preference, baseline kind); 2-character codes are RINEX 2.11
    "GPS L1 C/A": ("G", ["S1C", "S1"], "sidereal"),
    "GPS L2": ("G", ["S2W", "S2L", "S2X", "S2"], "sidereal"),
    "GPS L5": ("G", ["S5Q", "S5X", "S5I", "S5"], "sidereal"),
    "Galileo E1": ("E", ["S1C", "S1X", "S1"], "elbin"),
    "Galileo E5a": ("E", ["S5Q", "S5X", "S5"], "elbin"),
}
PRIMARY = "GPS L1 C/A"
KEEP = {s: sorted({c for sy, cs, _ in SIGNALS.values() if sy == s for c in cs}) for s in "GE"}

# The pre-stated test (docs/validation/ground-stations.md)
TEST_STATIONS = ["LAMA00POL", "REDZ00POL", "VAIN00LVA", "VIS600SWE", "OSK600SWE", "BUDP00DNK"]
JAMMED = ["2026-05-09", "2026-01-02", "2026-02-01", "2026-02-24", "2025-06-15", "2025-05-25"]
QUIET = ["2026-05-16", "2026-01-17"]


# ---------- small helpers ----------

def iso(d):
    return d.isoformat() if isinstance(d, date) else d


def pday(s):
    return s if isinstance(s, date) else date.fromisoformat(s)


def haversine_km(lat1, lon1, lat2, lon2):
    la1, lo1, la2, lo2 = (np.radians(np.asarray(v, dtype=float)) for v in (lat1, lon1, lat2, lon2))
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(np.minimum(a, 1.0)))


def nanmedian(a, axis=None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmedian(a, axis=axis)


def gps_seconds(day):
    """GPS seconds (continuous since 6 Jan 1980) at 00:00:00 GPS time of the day."""
    d = pday(day)
    return (datetime(d.year, d.month, d.day, tzinfo=timezone.utc) - GPS0).total_seconds()


def unix_day0(day):
    d = pday(day)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()


def ecef_to_geodetic(x, y, z):
    a, f = 6378137.0, 1 / 298.257223563
    e2 = f * (2 - f)
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - e2))
    for _ in range(8):
        n = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
        h = p / math.cos(lat) - n
        lat = math.atan2(z, p * (1 - e2 * n / (n + h)))
    return math.degrees(lat), math.degrees(lon), h


# ---------- pure analysis functions (tested in tests/test_station_cn0.py) ----------

def sidereal_index(t_az, t_el, b_az, b_el, k_days, shift_s=SHIFT_S, window_s=WINDOW_S, tol_deg=TOL_DEG, step=STEP):
    """For each test-day epoch, the baseline-day epoch with the satellite at the same place in the sky (-1: none).

    The satellite is where it was on the test day at epoch t on a day k_days earlier at about t + k_days * shift_s.
    Within +-window_s of that, take the baseline epoch whose az/el is closest; reject matches further than tol_deg."""
    T, B = len(t_el), len(b_el)
    nominal = int(round(k_days * shift_s / step))
    w = int(window_s // step)
    offs = np.arange(-w, w + 1)
    idx = np.arange(T)[None, :] + nominal + offs[:, None]
    valid = (idx >= 0) & (idx < B)
    idc = np.clip(idx, 0, B - 1)
    with np.errstate(invalid="ignore"):
        d_el = b_el[idc] - t_el[None, :]
        d_az = (b_az[idc] - t_az[None, :] + 180.0) % 360.0 - 180.0
        dist = np.hypot(d_el, d_az * np.cos(np.radians(t_el))[None, :])
    dist[~valid | ~np.isfinite(dist)] = np.inf
    best = np.argmin(dist, axis=0)
    cols = np.arange(T)
    out = idc[best, cols]
    out[dist[best, cols] > tol_deg] = -1
    return out


def take(values, index):
    """values[index] with NaN where index is -1."""
    out = np.asarray(values, dtype=float)[np.clip(index, 0, None)]
    out[index < 0] = np.nan
    return out


def match_sidereal(t_az, t_el, b_az, b_el, b_val, k_days, **kw):
    """Baseline-day values aligned to test-day epochs by sky position (see sidereal_index)."""
    return take(b_val, sidereal_index(t_az, t_el, b_az, b_el, k_days, **kw))


def combine_baseline(stack, min_days=MIN_BASE):
    """(days, ...) aligned baseline values -> (median, count of days with a value); median is NaN below min_days."""
    stack = np.asarray(stack, dtype=float)
    count = np.sum(np.isfinite(stack), axis=0)
    med = nanmedian(stack, axis=0)
    med = np.where(count >= min_days, med, np.nan)
    return med, count


def elbin_baseline(base_vals, base_els, test_el, binw=2.5, min_days=MIN_BASE):
    """Pooled baseline by elevation bin: median over all satellites and baseline days in the bin.

    base_vals, base_els: lists (one per baseline day) of (nsat, T) arrays. Returns (baseline, days) shaped like test_el."""
    nb = int(90 // binw) + 1
    pooled = [[] for _ in range(nb)]
    days = np.zeros(nb, int)
    for v, e in zip(base_vals, base_els):
        ok = np.isfinite(v) & np.isfinite(e) & (e >= 0)
        b, vv = (e[ok] // binw).astype(int), v[ok]
        for k in np.unique(b):
            pooled[k].append(vv[b == k])
            days[k] += 1
    med = np.array([np.median(np.concatenate(p)) if p else np.nan for p in pooled])
    te = np.where(np.isfinite(test_el), test_el, -1.0)
    bi = np.clip((te // binw).astype(int), 0, nb - 1)
    base = np.where(te >= 0, med[bi], np.nan)
    cnt = np.where(te >= 0, days[bi], 0)
    base = np.where(cnt >= min_days, base, np.nan)
    return base, cnt


def residuals(test_vals, base, base_count, el, present, count_loss=True, mask=MASK_DEG, min_base=MIN_BASE):
    """Per-satellite residuals (nsat, T): test - baseline where the satellite is above the mask and has a baseline.

    A satellite with a baseline but no test value on an epoch that exists in the file is lost: LOSS_DB (if count_loss).
    Satellite-epochs that don't qualify are NaN."""
    test_vals = np.asarray(test_vals, dtype=float)
    with np.errstate(invalid="ignore"):
        ok = (np.asarray(el) >= mask) & (np.asarray(base_count) >= min_base) & np.isfinite(base) & np.asarray(present)[None, :]
    r = np.full(test_vals.shape, np.nan)
    have = ok & np.isfinite(test_vals)
    r[have] = test_vals[have] - base[have]
    if count_loss:
        r[ok & ~np.isfinite(test_vals)] = LOSS_DB
    return r


def station_stats(r, min_sats=MIN_SATS, drop_db=DROP_DB):
    """Residuals (nsat, T) -> D (median residual), F (share of satellites drop_db or more down), n (satellites used)."""
    n = np.sum(np.isfinite(r), axis=0)
    D = nanmedian(r, axis=0)
    with np.errstate(invalid="ignore"):
        F = np.sum(r <= -drop_db, axis=0) / np.where(n > 0, n, 1)
    D = np.where(n >= min_sats, D, np.nan)
    F = np.where(n >= min_sats, F, np.nan)
    return D, F, n


def rolling_median(x, win=WIN, min_valid=None):
    """Centred running median ignoring NaN; NaN where fewer than min_valid (default half the window, rounded up) values."""
    from numpy.lib.stride_tricks import sliding_window_view
    x = np.asarray(x, dtype=float)
    pad = win // 2
    min_valid = (win + 1) // 2 if min_valid is None else min_valid
    xp = np.concatenate([np.full(pad, np.nan), x, np.full(pad, np.nan)])
    w = sliding_window_view(xp, win)
    cnt = np.sum(np.isfinite(w), axis=1)
    med = nanmedian(w, axis=1)
    return np.where(cnt >= min_valid, med, np.nan)


def flag_epochs(D, F, win=WIN, d_thr=D_THR, f_thr=F_THR):
    """The drop rule: 5-min running medians of D <= d_thr and of F >= f_thr. Returns (flags, D5, F5)."""
    d5, f5 = rolling_median(D, win), rolling_median(F, win)
    with np.errstate(invalid="ignore"):
        flags = (d5 <= d_thr) & (f5 >= f_thr)
    return flags, d5, f5


def runs(flags, step=STEP, merge_s=MERGE_S, min_s=MIN_RUN_S):
    """Flagged epochs -> [(i0, i1)] inclusive runs, merged across gaps of up to merge_s, at least min_s long."""
    idx = np.flatnonzero(flags)
    if not len(idx):
        return []
    out, s, p = [], int(idx[0]), int(idx[0])
    for i in idx[1:]:
        i = int(i)
        if (i - p - 1) * step > merge_s:
            out.append((s, p)); s = i
        p = i
    out.append((s, p))
    return [(a, b) for a, b in out if (b - a + 1) * step >= min_s]


def run_mask(rs, n=NEP):
    m = np.zeros(n, bool)
    for a, b in rs:
        m[a:b + 1] = True
    return m


def epochs_to_minutes(x, how="mean", leap=LEAP, step=STEP):
    """Per-epoch series (GPS time, day start) -> 1440 UTC minutes (mean, or 'any' for booleans)."""
    x = np.asarray(x)
    t = np.arange(len(x)) * step - leap
    m = np.floor(t / 60).astype(int)
    ok = (m >= 0) & (m < 1440)
    if how == "any":
        out = np.zeros(1440, bool)
        np.logical_or.at(out, m[ok], x[ok].astype(bool))
        return out
    v = x[ok].astype(float)
    good = np.isfinite(v)
    s = np.bincount(m[ok][good], weights=v[good], minlength=1440)
    c = np.bincount(m[ok][good], minlength=1440)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(c > 0, s / np.maximum(c, 1), np.nan)


def aircraft_minutes(t, lat, lon, adsb, nacp, lat0, lon0, day, radius_km=RADIUS_KM):
    """ADS-B position reports within radius_km of a point -> (reports, reports with NACp < 8) per UTC minute."""
    t = np.asarray(t, dtype=float)
    d = haversine_km(lat, lon, lat0, lon0)
    m = np.asarray(adsb, bool) & (np.asarray(nacp) >= 0) & (d <= radius_km)
    mi = np.floor((t - unix_day0(day)) / 60).astype(int)
    m &= (mi >= 0) & (mi < 1440)
    n = np.bincount(mi[m], minlength=1440)
    bad = np.bincount(mi[m & (np.asarray(nacp) < 8)], minlength=1440)
    return n, bad


def lag_corr(x, y, maxlag=60, min_n=30):
    """Pearson r of x[t] against y[t + lag] for lag in -maxlag..maxlag (NaN-aware).

    Positive lag: y (aircraft) follows x (station). Returns (best_lag, best_r, r_at_0); None where undefined."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    best, r0 = (None, None), None
    for L in range(-maxlag, maxlag + 1):
        a, b = (x[:len(x) - L], y[L:]) if L >= 0 else (x[-L:], y[:len(y) + L])
        ok = np.isfinite(a) & np.isfinite(b)
        if ok.sum() < min_n:
            continue
        aa, bb = a[ok], b[ok]
        if aa.std() == 0 or bb.std() == 0:
            continue
        r = float(np.corrcoef(aa, bb)[0, 1])
        if L == 0:
            r0 = r
        if best[1] is None or r > best[1]:
            best = (L, r)
    return best[0], best[1], r0


def pick_baseline(test_day, shares, exclude=(), n=5, max_days=21, min_ac=50):
    """Quiet baseline days for one station: nearest first, share <= the station's median over all days with min_ac.

    shares: {iso day: (share %, aircraft-hexes)}. Returns (days, median) or (None, None) without usable shares."""
    vals = [s for s, ac in shares.values() if ac >= min_ac and s is not None]
    if not vals:
        return None, None
    med = statistics.median(vals)
    t, ex, out = pday(test_day), set(exclude) | {iso(test_day)}, []
    for k in range(1, max_days + 1):
        for d in (iso(t - timedelta(days=k)), iso(t + timedelta(days=k))):
            v = shares.get(d)
            if d not in ex and v and v[1] >= min_ac and v[0] is not None and v[0] <= med:
                out.append(d)
    return out[:n], med


def nearest_days(test_day, n=6, max_days=4, exclude=()):
    t, out = pday(test_day), []
    for k in range(1, max_days + 1):
        for d in (iso(t - timedelta(days=k)), iso(t + timedelta(days=k))):
            if d not in exclude:
                out.append(d)
    return out[:n]


# ---------- RINEX parsing ----------

def parse_obs(text, day):
    """RINEX 2.11, 3 or 4 observation text -> (header dict, {sat: {code: float32[NEP]}}, present bool[NEP]).

    Keeps the S codes in KEEP. Epochs off the STEP grid are ignored."""
    lines = text.splitlines()
    first = lines[0] if lines else ""
    if first[60:80].strip() == "RINEX VERSION / TYPE" and first[:9].strip().startswith("2"):
        return parse_obs2(lines, day)
    hdr, types, sysc, i = {}, {}, None, 0
    for i, line in enumerate(lines):
        label = line[60:80].strip()
        if label == "RINEX VERSION / TYPE":
            hdr["version"] = line[:9].strip()
        elif label == "SYS / # / OBS TYPES":
            if line[0] != " ":
                sysc = line[0]; types[sysc] = []
            types[sysc] += line[7:58].split()
        elif label == "APPROX POSITION XYZ":
            hdr["xyz"] = [float(line[0:14]), float(line[14:28]), float(line[28:42])]
        elif label == "MARKER NAME":
            hdr["marker"] = line[:60].strip()
        elif label == "REC # / TYPE / VERS":
            hdr["receiver"] = line[20:40].strip(); hdr["firmware"] = line[40:60].strip()
        elif label == "ANT # / TYPE":
            hdr["antenna"] = line[20:40].strip()
        elif label == "INTERVAL":
            hdr["interval"] = float(line[:10])
        elif label == "SIGNAL STRENGTH UNIT":
            hdr["ss_unit"] = line[:20].strip()
        elif label == "LICENSE OF USE":
            hdr.setdefault("licence", []).append(line[:60].strip())
        elif label == "DOI":
            hdr["doi"] = line[:60].strip()
        elif label == "STATION INFORMATION":
            hdr.setdefault("station_info", []).append(line[:60].strip())
        elif label == "END OF HEADER":
            break
    if not hdr.get("version", "").startswith(("3", "4")):
        raise ValueError(f"not RINEX 3/4 observation data (version {hdr.get('version')})")
    want = {s: [(c, k) for k, c in enumerate(types[s]) if c in KEEP.get(s, ())] for s in types}
    hdr["types"] = {s: [c for c, _ in w] for s, w in want.items() if w}
    d0 = pday(day)
    store, present = {}, np.zeros(NEP, bool)
    j, n = i + 1, len(lines)
    while j < n:
        line = lines[j]
        if not line.startswith(">"):
            j += 1
            continue
        flag = int(line[31]) if len(line) > 31 and line[31].isdigit() else 0
        ns = int(line[32:35])
        if flag > 1:
            j += 1 + ns
            continue
        sod = ((date(int(line[2:6]), int(line[7:9]), int(line[10:12])) - d0).days * 86400
               + int(line[13:15]) * 3600 + int(line[16:18]) * 60 + float(line[18:29]))
        k = sod / STEP
        ki = int(round(k))
        ok = abs(k - ki) < 1e-3 and 0 <= ki < NEP
        if ok:
            present[ki] = True
            for sl in lines[j + 1:j + 1 + ns]:
                sat = sl[:3].replace(" ", "0")
                for code, kk in want.get(sat[0], ()):
                    s = sl[3 + 16 * kk:17 + 16 * kk]
                    if s.strip():
                        arr = store.get((sat, code))
                        if arr is None:
                            arr = store[(sat, code)] = np.full(NEP, np.nan, np.float32)
                        arr[ki] = float(s)
        j += 1 + ns
    obs = {}
    for (sat, code), arr in store.items():
        obs.setdefault(sat, {})[code] = arr
    return hdr, obs, present


def _sat2(s, default="G"):
    """A RINEX 2 satellite id ('G05', 'G 5', ' 5') -> 'G05'; None if malformed. A blank system letter means GPS."""
    s = s.ljust(3)
    if not s[1:3].strip().isdigit():
        return None
    return f"{s[0] if s[0] != ' ' else default}{int(s[1:3]):02d}"


def parse_obs2(lines, day):
    """RINEX 2.11 observation lines -> (header dict, {sat: {code: float32[NEP]}}, present bool[NEP]), as parse_obs.

    One '# / TYPES OF OBSERV' list for all systems, five 16-column values per line, satellite ids on the epoch line
    (12 per line, continuation lines for more). Event records (flags 2-5) are skipped with their special records;
    cycle-slip records (flag 6) are read past and not stored. Only GPS system time is accepted."""
    hdr, types, ntypes, i = {}, [], None, 0
    for i, line in enumerate(lines):
        label = line[60:80].strip()
        if label == "RINEX VERSION / TYPE":
            hdr["version"] = line[:9].strip()
            if line[20:21] not in ("O", "o"):
                raise ValueError(f"not RINEX observation data (file type {line[20:21]!r})")
            hdr["system"] = line[40:41] if line[40:41] in ("G", "R", "E", "S") else "G"   # M (mixed) or blank: GPS
        elif label == "# / TYPES OF OBSERV":
            if ntypes is None:
                ntypes = int(line[:6])
            types += line[6:60].split()
        elif label == "TIME OF FIRST OBS":
            hdr["time_system"] = line[48:51].strip() or "GPS"
        elif label == "APPROX POSITION XYZ":
            hdr["xyz"] = [float(line[0:14]), float(line[14:28]), float(line[28:42])]
        elif label == "MARKER NAME":
            hdr["marker"] = line[:60].strip()
        elif label == "REC # / TYPE / VERS":
            hdr["receiver"] = line[20:40].strip(); hdr["firmware"] = line[40:60].strip()
        elif label == "ANT # / TYPE":
            hdr["antenna"] = line[20:40].strip()
        elif label == "INTERVAL":
            hdr["interval"] = float(line[:10])
        elif label == "END OF HEADER":
            break
    if not types:
        raise ValueError("RINEX 2 header has no observation types")
    if hdr.get("time_system", "GPS") != "GPS":
        raise ValueError(f"RINEX 2 time system {hdr['time_system']} (only GPS time is handled)")
    types = types[:ntypes]
    hdr["ss_unit"] = "DBHZ (assumed; RINEX 2)"
    nlines = (len(types) + 4) // 5
    want = {s: [(c, k) for k, c in enumerate(types) if c in KEEP.get(s, ())] for s in KEEP}
    d0 = pday(day)
    store, present = {}, np.zeros(NEP, bool)
    j, n = i + 1, len(lines)
    while j < n:
        line = lines[j]
        if len(line) < 32 or not line[29:32].strip():
            j += 1
            continue
        flag = int(line[28]) if line[28].isdigit() else 0
        ns = int(line[29:32])
        if 2 <= flag <= 5:                   # event: ns special records follow (header lines, comments)
            j += 1 + ns
            continue
        ids, j = line[32:68].ljust(36), j + 1
        for _ in range(max(ns - 1, 0) // 12):     # continuation lines: 12 more satellite ids each
            ids += (lines[j] if j < n else "")[32:68].ljust(36)
            j += 1
        sats = [_sat2(ids[3 * k:3 * k + 3], hdr.get("system", "G")) for k in range(ns)]
        recs = lines[j:j + ns * nlines]
        j += ns * nlines
        if flag == 6:                        # cycle-slip records: same layout, not observations
            continue
        yy = int(line[1:3])
        sod = ((date(1900 + yy if yy >= 80 else 2000 + yy, int(line[4:6]), int(line[7:9])) - d0).days * 86400
               + int(line[10:12]) * 3600 + int(line[13:15]) * 60 + float(line[15:26]))
        k = sod / STEP
        ki = int(round(k))
        if not (abs(k - ki) < 1e-3 and 0 <= ki < NEP):
            continue
        present[ki] = True
        for s, sat in enumerate(sats):
            w = want.get(sat[0]) if sat else None
            if not w:
                continue
            raw = "".join(r.ljust(80)[:80] for r in recs[s * nlines:(s + 1) * nlines])
            for code, kk in w:
                v = raw[16 * kk:16 * kk + 14]
                if v.strip():
                    arr = store.get((sat, code))
                    if arr is None:
                        arr = store[(sat, code)] = np.full(NEP, np.nan, np.float32)
                    arr[ki] = float(v)
    obs = {}
    for (sat, code), arr in store.items():
        obs.setdefault(sat, {})[code] = arr
    hdr["types"] = {s: sorted({c for (sat, c) in store if sat[0] == s}) for s in KEEP}
    hdr["types"] = {s: c for s, c in hdr["types"].items() if c}
    return hdr, obs, present


def _f(s):
    s = s.strip().replace("D", "E").replace("d", "e")
    return float(s) if s else 0.0


def parse_nav(text):
    """RINEX 3 navigation text -> {sat: [ephemeris dict]} for GPS and Galileo (Keplerian records)."""
    lines = text.splitlines()
    i = next((k + 1 for k, l in enumerate(lines) if l[60:80].strip() == "END OF HEADER"), 0)
    eph, n = {}, len(lines)
    while i < n:
        line = lines[i]
        if not line[:1].isalpha():
            i += 1
            continue
        j = i + 1
        while j < n and lines[j][:4] == "    ":
            j += 1
        rec, i = lines[i:j], j
        if line[0] not in "GE" or len(rec) < 8:
            continue
        v = [_f(rec[0][23 + 19 * k:42 + 19 * k]) for k in range(3)]
        for r in rec[1:8]:
            v += [_f(r[4 + 19 * k:23 + 19 * k]) for k in range(4)]
        sat = line[:3].replace(" ", "0")
        eph.setdefault(sat, []).append({
            "crs": v[4], "dn": v[5], "m0": v[6], "cuc": v[7], "e": v[8], "cus": v[9], "sqrta": v[10],
            "toe": v[11], "cic": v[12], "om0": v[13], "cis": v[14], "i0": v[15], "crc": v[16], "w": v[17],
            "omd": v[18], "idot": v[19], "week": v[21], "health": v[24]})
    return eph


def sat_xyz(e, t_abs, gal=False):
    """ECEF satellite positions (m) at GPS seconds t_abs from one broadcast ephemeris (IS-GPS-200 / Galileo OS SIS ICD)."""
    mu = 3.986004418e14 if gal else 3.986005e14
    we = 7.2921151467e-5
    a = e["sqrta"] ** 2
    tk = t_abs - (e["week"] * 604800.0 + e["toe"])
    m = e["m0"] + (math.sqrt(mu / a ** 3) + e["dn"]) * tk
    E = m.copy()
    for _ in range(12):
        E = m + e["e"] * np.sin(E)
    v = np.arctan2(math.sqrt(1 - e["e"] ** 2) * np.sin(E), np.cos(E) - e["e"])
    phi = v + e["w"]
    s2, c2 = np.sin(2 * phi), np.cos(2 * phi)
    u = phi + e["cus"] * s2 + e["cuc"] * c2
    r = a * (1 - e["e"] * np.cos(E)) + e["crs"] * s2 + e["crc"] * c2
    inc = e["i0"] + e["cis"] * s2 + e["cic"] * c2 + e["idot"] * tk
    xp, yp = r * np.cos(u), r * np.sin(u)
    om = e["om0"] + (e["omd"] - we) * tk - we * e["toe"]
    return np.stack([xp * np.cos(om) - yp * np.cos(inc) * np.sin(om),
                     xp * np.sin(om) + yp * np.cos(inc) * np.cos(om),
                     yp * np.sin(inc)], axis=-1)


def azel(sat, sta_xyz):
    lat, lon, _ = ecef_to_geodetic(*sta_xyz)
    la, lo = math.radians(lat), math.radians(lon)
    d = sat - np.asarray(sta_xyz)[None, :]
    e = -math.sin(lo) * d[:, 0] + math.cos(lo) * d[:, 1]
    n = -math.sin(la) * math.cos(lo) * d[:, 0] - math.sin(la) * math.sin(lo) * d[:, 1] + math.cos(la) * d[:, 2]
    u = math.cos(la) * math.cos(lo) * d[:, 0] + math.cos(la) * math.sin(lo) * d[:, 1] + math.sin(la) * d[:, 2]
    return np.degrees(np.arctan2(e, n)) % 360.0, np.degrees(np.arctan2(u, np.hypot(e, n)))


def sky(eph, sta_xyz, day, max_age=7200.0):
    """{sat: (az, el)} per epoch for every healthy GPS/Galileo satellite; NaN where no ephemeris within max_age."""
    t = gps_seconds(day) + np.arange(NEP) * STEP
    out = {}
    for sat, recs in eph.items():
        recs = [r for r in recs if r["health"] == 0 and r["sqrta"] > 1000]
        if not recs:
            continue
        toe = np.array([r["week"] * 604800.0 + r["toe"] for r in recs])
        pick = np.argmin(np.abs(t[:, None] - toe[None, :]), axis=1)
        age = np.abs(t - toe[pick])
        xyz = np.full((NEP, 3), np.nan)
        for k in np.unique(pick):
            m = (pick == k) & (age <= max_age)
            if m.any():
                xyz[m] = sat_xyz(recs[k], t[m], gal=sat[0] == "E")
        if np.isfinite(xyz).any():
            out[sat] = azel(xyz, sta_xyz)
    return out


# ---------- data access (BKG GNSS Data Center, anonymous HTTPS) ----------

_LISTINGS = {}


def http_get(url, timeout=120):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def listing(url):
    if url not in _LISTINGS:
        try:
            html = http_get(url).decode("latin-1")
            _LISTINGS[url] = set(re.findall(r'href="([^"?/][^"]*)"', html))
        except Exception:
            _LISTINGS[url] = set()
    return _LISTINGS[url]


def is_noaa(sta):
    """A 4-character id is a NOAA CORS (NCN) station; EPN/IGS stations use 9-character names."""
    return bool(re.fullmatch(r"[A-Za-z0-9]{4}", sta))


def norm(sta):
    return sta.upper() if is_noaa(sta) else sta


def obs_name(sta, day):
    d = pday(day)
    doy = d.timetuple().tm_yday
    if is_noaa(sta):              # direct path on the NODD bucket; a missing file is a 404 at download
        s = sta.lower()
        return f"{NOAA}/rinex/{d.year}/{doy:03d}/{s}/{s}{doy:03d}0.{d.year % 100:02d}d.gz"
    pat = re.compile(rf"^{sta}_[RSU]_{d.year}{doy:03d}0000_01D_30S_MO\.crx\.gz$")
    for net in ("EUREF", "IGS"):
        url = f"{BKG}/{net}/obs/{d.year}/{doy:03d}/"
        for f in sorted(listing(url)):
            if pat.match(f):
                return url + f
    return None


def nav_name(day):
    d = pday(day)
    doy = d.timetuple().tm_yday
    url = f"{BKG}/IGS/BRDC/{d.year}/{doy:03d}/"
    files = listing(url)
    for pre in ("BRDC00IGS_R", "BRDC00WRD_S", "BRDC00WRD_R", "BRDM00DLR_S"):
        f = f"{pre}_{d.year}{doy:03d}0000_01D_MN.rnx.gz"
        if f in files:
            return url + f
    return None


def download(url, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    data = http_get(url)
    tmp = f"{dest}.{os.getpid()}.part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, dest)
    return dest


def fetch(sta, day):
    """Download (if needed) one station-day and that day's broadcast nav. Returns (obs path or None, nav path or None)."""
    d = pday(day)
    sub = os.path.join(RAW, str(d.year), f"{d.timetuple().tm_yday:03d}")
    out = []
    for url in (obs_name(sta, d), nav_name(d)):
        if url is None:
            out.append(None)
            continue
        try:
            out.append(download(url, os.path.join(sub, url.rsplit("/", 1)[1])))
        except Exception as ex:
            print(f"  download failed: {url}: {ex}", file=sys.stderr)
            out.append(None)
    return tuple(out)


def load_station_day(sta, day, fetch_missing=True):
    """Parsed station-day from cache, else download + parse: dict(hdr, sats, codes, vals[nsat, ncode, NEP], present, sky)."""
    os.makedirs(CACHE, exist_ok=True)
    cp = os.path.join(CACHE, f"{sta}_{iso(day)}.npz")
    if os.path.exists(cp):
        z = np.load(cp, allow_pickle=False)
        hdr = json.loads(str(z["hdr"]))
        return {"hdr": hdr, "sats": list(z["sats"]), "codes": list(z["codes"]), "vals": z["vals"], "present": z["present"],
                "sky_sats": list(z["sky_sats"]), "az": z["az"], "el": z["el"]}
    if not fetch_missing:
        return None
    op, np_ = fetch(sta, day)
    if not op or not np_:
        return None
    import hatanaka
    with open(op, "rb") as f:
        text = hatanaka.decompress(f.read()).decode("latin-1")
    hdr, obs, present = parse_obs(text, day)
    del text
    with gzip.open(np_, "rb") as f:
        eph = parse_nav(f.read().decode("latin-1"))
    sk = sky(eph, hdr["xyz"], day)
    sats = sorted(obs)
    codes = sorted({c for s in obs.values() for c in s})
    vals = np.full((len(sats), len(codes), NEP), np.nan, np.float32)
    for i, s in enumerate(sats):
        for j, c in enumerate(codes):
            if c in obs[s]:
                vals[i, j] = obs[s][c]
    sky_sats = sorted(sk)
    az = np.array([sk[s][0] for s in sky_sats], np.float32).reshape(len(sky_sats), NEP)
    el = np.array([sk[s][1] for s in sky_sats], np.float32).reshape(len(sky_sats), NEP)
    hdr["obs_file"] = os.path.basename(op); hdr["nav_file"] = os.path.basename(np_)
    np.savez_compressed(cp, hdr=json.dumps(hdr), sats=np.array(sats), codes=np.array(codes), vals=vals, present=present,
                        sky_sats=np.array(sky_sats), az=az, el=el)
    return load_station_day(sta, day, fetch_missing=False)


def series(sd, sysc, code, sats):
    """(len(sats), NEP) values of one code and (az, el) for the listed satellites (NaN where absent)."""
    v = np.full((len(sats), NEP), np.nan)
    az = np.full((len(sats), NEP), np.nan)
    el = np.full((len(sats), NEP), np.nan)
    si = {s: i for i, s in enumerate(sd["sats"])}
    ki = {s: i for i, s in enumerate(sd["sky_sats"])}
    cj = sd["codes"].index(code) if code in sd["codes"] and code in sd["hdr"].get("types", {}).get(sysc, []) else None
    for i, s in enumerate(sats):
        if cj is not None and s in si:
            v[i] = sd["vals"][si[s], cj]
        if s in ki:
            az[i], el[i] = sd["az"][ki[s]], sd["el"][ki[s]]
    return v, az, el


# ---------- one station-day ----------

def window_minutes(windows, day):
    """[[start, end], ...] ISO UTC strings ('2026-03-06T07:15Z') -> bool[1440] of that day's minutes, ends inclusive."""
    m = np.zeros(1440, bool)
    t0 = unix_day0(day)
    for s, e in windows or ():
        a = (datetime.strptime(s, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc).timestamp() - t0) // 60
        b = (datetime.strptime(e, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc).timestamp() - t0) // 60
        a, b = int(max(a, 0)), int(min(b, 1439))
        if a <= b:
            m[a:b + 1] = True
    return m


def epoch_minutes(leap=LEAP, step=STEP):
    """UTC minute of each epoch of the day (-1 where the epoch falls on the day before)."""
    m = np.floor((np.arange(NEP) * step - leap) / 60).astype(int)
    return np.where((m >= 0) & (m < 1440), m, -1)


def analyse(sta, day, base_days, fetch_missing=True, windows=None):
    """Apply the rule to one station-day. Returns (summary dict, per-epoch series dict) or (None, reason).

    windows: optional [[start, end], ...] UTC strings; in-window counts are added for each signal."""
    test = load_station_day(sta, day, fetch_missing)
    if test is None:
        return None, "no data"
    bases = {d: load_station_day(sta, d, fetch_missing) for d in base_days}
    bases = {d: b for d, b in bases.items() if b is not None}
    lat, lon, h = ecef_to_geodetic(*test["hdr"]["xyz"])
    res = {"station": sta, "day": iso(day), "network": network(sta), "lat": round(lat, 4), "lon": round(lon, 4)}
    if network(sta) == "epn":
        res["km_from_kaliningrad_coast"] = round(float(haversine_km(lat, lon, *KALININGRAD)), 1)
    wm = window_minutes(windows, day) if windows else None
    em = epoch_minutes()
    we = (em >= 0) & wm[np.clip(em, 0, None)] if wm is not None else None
    res |= {"receiver": test["hdr"].get("receiver"), "antenna": test["hdr"].get("antenna"),
           "licence": " ".join(test["hdr"].get("licence", [])) or None, "doi": test["hdr"].get("doi"),
           "obs_file": test["hdr"].get("obs_file"), "nav_file": test["hdr"].get("nav_file"),
           "rinex_version": test["hdr"].get("version"),
           "epochs_present": int(test["present"].sum()), "baseline_days": sorted(bases), "signals": {}}
    if wm is not None:
        res["windows"] = windows
        res["window_minutes"] = int(wm.sum())
    per = {"present": test["present"]}
    match = {}                          # (baseline day, satellite) -> matched epoch index, shared by all GPS signals
    for name, (sysc, prefs, kind) in SIGNALS.items():
        code = next((c for c in prefs if c in test["hdr"].get("types", {}).get(sysc, [])), None)
        if code is None:
            continue
        sats = sorted({s for s in test["sky_sats"] if s[0] == sysc})
        tv, taz, tel = series(test, sysc, code, sats)
        if not np.isfinite(tv).any():
            continue
        if kind == "sidereal":
            stack = []
            for d, b in bases.items():
                bv, baz, bel = series(b, sysc, code, sats)
                k = (pday(day) - pday(d)).days
                rows = []
                for i, sat in enumerate(sats):
                    if (d, sat) not in match:
                        match[(d, sat)] = sidereal_index(taz[i], tel[i], baz[i], bel[i], k)
                    rows.append(take(bv[i], match[(d, sat)]))
                stack.append(np.array(rows))
            if not stack:
                continue
            base, cnt = combine_baseline(stack)
            r = residuals(tv, base, cnt, tel, test["present"], count_loss=True)
        else:
            bvs, bels = [], []
            for d, b in bases.items():
                bv, _, bel = series(b, sysc, code, sats)
                bvs.append(bv); bels.append(bel)
            if not bvs:
                continue
            base, cnt = elbin_baseline(bvs, bels, tel)
            r = residuals(tv, base, cnt, tel, test["present"], count_loss=False)
        D, F, n = station_stats(r)
        flags, d5, f5 = flag_epochs(D, F)
        rs = runs(flags)
        fm = epochs_to_minutes(run_mask(rs), how="any")
        with np.errstate(invalid="ignore"):
            lost = np.sum(r == LOSS_DB, axis=0)
        fin = d5[np.isfinite(d5)]
        res["signals"][name] = {
            "code": code, "baseline": kind, "epochs_scored": int(np.isfinite(D).sum()),
            "sats_median": float(np.median(n[np.isfinite(D)])) if np.isfinite(D).any() else 0.0,
            "d5_p50": round(float(np.percentile(fin, 50)), 2) if len(fin) else None,
            "d5_p5": round(float(np.percentile(fin, 5)), 2) if len(fin) else None,
            "d5_p1": round(float(np.percentile(fin, 1)), 2) if len(fin) else None,
            "d5_min": round(float(fin.min()), 2) if len(fin) else None,
            "lost_sat_epochs": int(lost.sum()),
            "flagged_minutes": int(fm.sum()),
            "runs": [{"start": utc_hhmm(a), "end": utc_hhmm(b), "minutes": round((b - a + 1) * STEP / 60, 1),
                      "d5_min": round(float(np.nanmin(d5[a:b + 1])), 1), "f5_max": round(float(np.nanmax(f5[a:b + 1])), 2)}
                     for a, b in rs]}
        sig = res["signals"][name]
        sig["scored_share"] = round(float(np.isfinite(D).sum()) / NEP, 3)
        if we is not None:
            fw = d5[we & np.isfinite(d5)]
            sig["flagged_minutes_in_windows"] = int((fm & wm).sum())
            sig["scored_share_in_windows"] = round(float(np.isfinite(D[we]).sum()) / max(int(we.sum()), 1), 3)
            sig["d5_p1_in_windows"] = round(float(np.percentile(fw, 1)), 2) if len(fw) else None
            sig["d5_min_in_windows"] = round(float(fw.min()), 2) if len(fw) else None
        per[name] = {"D": D, "F": F, "n": n, "d5": d5, "f5": f5, "flags": run_mask(rs), "minutes": fm}
    return res, per


def utc_hhmm(i):
    s = i * STEP - LEAP
    s = max(s, 0)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}Z"


# ---------- aircraft side (data/trace_box extracts) ----------

def trace_points(day):
    """All points of a trace_box extract as arrays (cached): t, lat, lon, adsb (bool), nacp (-1 = unknown)."""
    cp = os.path.join(CACHE, f"trace_{iso(day)}.npz")
    if os.path.exists(cp):
        z = np.load(cp)
        return z["t"], z["lat"], z["lon"], z["adsb"], z["nacp"]
    src = os.path.join(TRACE, f"{iso(day)}.jsonl.gz")
    if not os.path.exists(src):
        return None
    import orjson
    t, la, lo, ad, na = [], [], [], [], []
    with gzip.open(src, "rb") as f:
        for line in f:
            for p in orjson.loads(line)["pts"]:
                t.append(p[0]); la.append(p[1]); lo.append(p[2]); ad.append(p[4] == "a")
                na.append(-1 if p[5] is None else p[5])
    arr = (np.array(t), np.array(la, np.float32), np.array(lo, np.float32), np.array(ad, bool), np.array(na, np.int16))
    os.makedirs(CACHE, exist_ok=True)
    np.savez_compressed(cp, t=arr[0], lat=arr[1], lon=arr[2], adsb=arr[3], nacp=arr[4])
    return arr


def add_aircraft(res, per):
    pts = trace_points(res["day"])
    if pts is None:
        res["aircraft"] = None
        return
    n, bad = aircraft_minutes(*pts, res["lat"], res["lon"], res["day"])
    if not n.sum():                 # the extract doesn't cover this station
        res["aircraft"] = None
        return
    share = np.where(n >= MIN_REPORTS, 100.0 * bad / np.maximum(n, 1), np.nan)
    per["ac_n"], per["ac_bad"], per["ac_share"] = n, bad, share
    ac = {"radius_km": RADIUS_KM, "reports": int(n.sum()), "minutes_scored": int(np.isfinite(share).sum()),
          "share_day": round(100.0 * bad.sum() / n.sum(), 1) if n.sum() else None,
          "minutes_share_ge30": int(np.sum(share >= 30))}
    p = per.get(PRIMARY)
    if p is not None:
        fm = p["minutes"]
        ac["minutes_share_ge30_flagged"] = int(np.sum((share >= 30) & fm))
        sf, su = share[fm & np.isfinite(share)], share[~fm & np.isfinite(share)]
        ac["share_in_flagged_minutes"] = round(float(sf.mean()), 1) if len(sf) else None
        ac["share_in_unflagged_minutes"] = round(float(su.mean()), 1) if len(su) else None
        drop = np.maximum(0.0, -epochs_to_minutes(p["d5"]))
        lag, rbest, r0 = lag_corr(drop, share)
        ac["lag_min"], ac["r_best"], ac["r_lag0"] = lag, None if rbest is None else round(rbest, 3), None if r0 is None else round(r0, 3)
        res["timing_aligned"] = None
        if res["signals"][PRIMARY]["flagged_minutes"] >= 10 and ac["share_in_flagged_minutes"] is not None \
                and ac["share_in_unflagged_minutes"] is not None and lag is not None:
            res["timing_aligned"] = bool(ac["share_in_flagged_minutes"] - ac["share_in_unflagged_minutes"] >= 10 and abs(lag) <= 15)
    res["aircraft"] = ac


# ---------- outputs ----------

def write_outputs(res, per):
    d = os.path.join(OUT, res["station"])
    os.makedirs(d, exist_ok=True)
    mins = {}
    for name in SIGNALS:
        if name in per:
            mins[name] = [None if not np.isfinite(v) else round(float(v), 2) for v in epochs_to_minutes(per[name]["d5"])]
    if "ac_share" in per:
        mins["aircraft_share"] = [None if not np.isfinite(v) else round(float(v), 1) for v in per["ac_share"]]
        mins["aircraft_reports"] = [int(v) for v in per["ac_n"]]
        mins["aircraft_reports_nacp_lt8"] = [int(v) for v in per["ac_bad"]]
    out = dict(res, minutes_utc=mins, credit=CREDIT[res.get("network", "epn")])
    with open(os.path.join(d, f"{res['day']}.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    try:
        plot(res, per, os.path.join(d, f"{res['day']}.png"))
    except ImportError:
        pass


def plot(res, per, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    hrs = (np.arange(NEP) * STEP - LEAP) / 3600.0
    fig, ax = plt.subplots(3, 1, figsize=(11, 7.5), sharex=True, gridspec_kw={"height_ratios": [3, 1.4, 1.6]})
    colours = {"GPS L1 C/A": "#1f4e79", "GPS L2": "#6a9fd4", "GPS L5": "#2e8b57", "Galileo E1": "#c07020", "Galileo E5a": "#d9a066"}
    for name in SIGNALS:
        if name in per:
            y = np.clip(per[name]["d5"], -20, 6)
            ax[0].plot(hrs, y, lw=1.6 if name == PRIMARY else 0.8, color=colours[name], label=name, zorder=3 if name == PRIMARY else 2)
    if PRIMARY in per:
        for a, b in runs(per[PRIMARY]["flags"], min_s=0):
            for k in range(2):
                ax[k].axvspan(hrs[a], hrs[b] + STEP / 3600, color="#d62728", alpha=0.18, lw=0)
        ax[1].plot(hrs, per[PRIMARY]["n"], color="#1f4e79", lw=0.8, label="GPS satellites scored (>=15 deg)")
        ax2 = ax[1].twinx()
        ax2.plot(hrs, per[PRIMARY]["f5"], color="#d62728", lw=0.8, label="share of satellites >=3 dB down")
        ax2.set_ylim(0, 1.05); ax2.axhline(F_THR, color="#d62728", ls=":", lw=0.8); ax2.set_ylabel("F (5-min)", fontsize=8)
        h1, l1 = ax[1].get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
        ax[1].legend(h1 + h2, l1 + l2, fontsize=7, loc="lower left")
    ax[0].axhline(D_THR, color="#d62728", ls="--", lw=0.8)
    ax[0].axhline(0, color="#888", lw=0.5)
    ax[0].set_ylim(-20, 6); ax[0].set_ylabel("C/N0 vs quiet days, dB-Hz\n(median over satellites, 5-min)", fontsize=8)
    ax[0].legend(fontsize=7, ncol=5, loc="lower left")
    ax[1].set_ylabel("satellites", fontsize=8)
    if "ac_share" in per:
        sh = per["ac_share"]
        sm = np.array([np.nanmean(sh[max(0, i - 2):i + 3]) if np.isfinite(sh[max(0, i - 2):i + 3]).any() else np.nan
                       for i in range(1440)])
        ax[2].plot((np.arange(1440) + 0.5) / 60.0, sm, color="#555", lw=0.8)
        ax[2].set_ylim(0, 100)
    ax[2].set_ylabel(f"aircraft NACp<8, %\n(ADS-B within {RADIUS_KM:.0f} km,\n5-min mean)", fontsize=8)
    ax[2].set_xlabel("hour (UTC)"); ax[2].set_xlim(0, 24); ax[2].set_xticks(range(0, 25, 3))
    s = res["signals"].get(PRIMARY, {})
    where = (f"  ({res['km_from_kaliningrad_coast']:.0f} km from the Kaliningrad coast)"
             if "km_from_kaliningrad_coast" in res else f"  ({res['lat']:.2f}, {res['lon']:.2f})")
    if res.get("windows"):
        for a, b in runs(window_minutes(res["windows"], res["day"]), step=60, merge_s=0, min_s=0):
            for k in range(3):
                ax[k].axvspan(a / 60.0, (b + 1) / 60.0, color="#999", alpha=0.12, lw=0)
    fig.suptitle(f"{res['station']}  {res['day']}{where}  "
                 f"GPS L1 C/A flagged: {s.get('flagged_minutes', 'n/a')} min; baseline {len(res['baseline_days'])} quiet days",
                 fontsize=10)
    credit = {"epn": "Station data: EPN/IGS via BKG GNSS Data Center (CC BY 4.0). Aircraft: adsb.lol (ODbL 1.0).",
              "noaa": "Station data: NOAA NGS CORS (NCN) via NODD; residuals computed by Noisefloor, not original NOAA "
                      "data. Aircraft: adsb.lol (ODbL 1.0)."}[res.get("network", "epn")]
    fig.text(0.01, 0.005, credit + (" Grey: declared windows." if res.get("windows") else "")
             + " Noisefloor, tools/station_cn0.py", fontsize=6, color="#666")
    fig.tight_layout(rect=(0, 0.02, 1, 0.97))
    fig.savefig(path, dpi=110)
    plt.close(fig)


# ---------- station list and quiet-day screen ----------

def epn_stations():
    """Active EPN stations: [(name9, lat, lon, place)] from the EPN CB list (cached in data/stations/)."""
    p = os.path.join(OUT, "EPN_stations.txt")
    if not os.path.exists(p):
        os.makedirs(OUT, exist_ok=True)
        with open(p, "wb") as f:
            f.write(http_get(EPN_LIST))
    out = []
    for line in open(p, encoding="latin-1"):
        q = line.split()
        if len(q) < 7 or q[3] != "999/9999":
            continue
        try:
            out.append((q[4], float(q[5]), float(q[6]), " ".join(q[7:])))
        except ValueError:
            continue
    return out


def parse_noaa_coords(text):
    """NGS composite coordinate list -> [(ID, lat, lon, status)]. Rows: ID epoch d m s N d m s W height ... status."""
    out = []
    for line in text.splitlines():
        q = line.split()
        if len(q) < 11 or not re.fullmatch(r"[A-Za-z0-9]{4}", q[0]) or q[5] not in ("N", "S") or q[9] not in ("E", "W"):
            continue
        try:
            la = (int(q[2]) + int(q[3]) / 60 + float(q[4]) / 3600) * (1 if q[5] == "N" else -1)
            lo = (int(q[6]) + int(q[7]) / 60 + float(q[8]) / 3600) * (1 if q[9] == "E" else -1)
        except ValueError:
            continue
        out.append((q[0].upper(), la, lo, q[-1]))
    return out


def noaa_stations():
    """NOAA CORS stations with published coordinates: [(ID, lat, lon, status)] (list cached in data/stations/)."""
    p = os.path.join(OUT, "noaa_nad83_2011_geo.comp.txt")
    if not os.path.exists(p):
        os.makedirs(OUT, exist_ok=True)
        with open(p, "wb") as f:
            f.write(http_get(NOAA_COORDS))
    with open(p, encoding="latin-1") as f:
        return parse_noaa_coords(f.read())


def station_pos(sta):
    if is_noaa(sta):
        rows = [(n, la, lo, st) for n, la, lo, st in noaa_stations()]
    else:
        rows = epn_stations()
    for n, la, lo, _ in rows:
        if n == norm(sta):
            return la, lo
    return None


def network(sta):
    return "noaa" if is_noaa(sta) else "epn"


CREDIT = {
    "epn": "Station data: EPN/IGS via BKG GNSS Data Center (CC BY 4.0 unless stated); aircraft: adsb.lol (ODbL 1.0)",
    "noaa": "Station data: NOAA NGS CORS Network (NCN) via NOAA Open Data Dissemination; C/N0 residuals computed by "
            "Noisefloor (modified, not original NOAA data; no NOAA endorsement). Orbits: IGS via BKG. "
            "Aircraft: adsb.lol (ODbL 1.0)",
}


def year_shares(stas, radius_km=RADIUS_KM):
    """{station: {day: (share %, aircraft-hexes)}} within radius of each station, from the daily tables in data/pnt/year."""
    cp = os.path.join(OUT, "year_shares.json")
    have = json.load(open(cp)) if os.path.exists(cp) else {}
    need = [s for s in stas if s not in have]
    if need and os.path.isdir(YEAR):
        import pyarrow.parquet as pq
        pos = {s: station_pos(s) for s in need}
        for s in [s for s, p in pos.items() if p is None]:
            print(f"  {s}: no published position; baseline days will be unscreened", file=sys.stderr)
            del pos[s]
        for s in need:
            have[s] = {}
        for fn in sorted(os.listdir(YEAR)):
            if not fn.endswith(".parquet") or fn.endswith(".hourly.parquet"):
                continue
            t = pq.read_table(os.path.join(YEAR, fn), columns=["lat", "lon", "aircraft", "bad_nacp_live"])
            lat, lon = t["lat"].to_numpy(), t["lon"].to_numpy()
            ac, bad = t["aircraft"].to_numpy(), t["bad_nacp_live"].to_numpy()
            for s, (la, lo) in pos.items():
                m = haversine_km(lat, lon, la, lo) <= radius_km
                a = int(ac[m].sum())
                have[s][fn[:10]] = [round(100.0 * float(bad[m].sum()) / a, 2) if a else None, a]
        with open(cp, "w") as f:
            json.dump(have, f)
    return {s: {d: tuple(v) for d, v in have.get(s, {}).items()} for s in stas}


def baseline_for(sta, day, shares, exclude):
    days, med = pick_baseline(day, shares.get(sta, {}), exclude=exclude)
    if days and len(days) >= MIN_BASE:
        return days, f"quiet (150 km share <= station median {med:.1f}%)"
    return nearest_days(day, exclude=exclude), "nearest days, unscreened (no daily tables)"


# ---------- commands ----------

def exists(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA, method="HEAD"), timeout=30) as r:
            return r.status == 200
    except Exception:
        return False


def cmd_stations(a):
    rows = []
    src = noaa_stations() if a.network == "noaa" else epn_stations()
    for n, la, lo, place in src:
        d = float(haversine_km(la, lo, a.lat, a.lon))
        if d <= a.max_km:
            rows.append((d, n, la, lo, place))
    rows.sort()
    what = "NOAA CORS stations (NGS composite; last column = status)" if a.network == "noaa" else "EPN stations"
    print(f"{what} within {a.max_km:.0f} km of {a.lat}N {a.lon}E" + (f"; daily file for {a.day}" if a.day else ""))
    for d, n, la, lo, place in rows:
        where = ""
        if a.day:
            u = obs_name(n, a.day)
            if a.network == "noaa":
                where = "yes" if exists(u) else "-"
            else:
                where = u.split("/root_ftp/")[1].split("/")[0] if u else "-"
        print(f"  {d:6.0f} km  {n}  {la:7.3f} {lo:8.3f}  {place:28s} {where}")


def cmd_fetch(a):
    for d in a.days:
        print(a.station, d, fetch(norm(a.station), d))


def read_days(path):
    """ISO days from a text file, one per line ('#' comments and blank lines ignored)."""
    if not path:
        return set()
    with open(path, encoding="utf-8") as f:
        return {s for s in (line.split("#")[0].strip() for line in f) if s}


def run_one(sta, day, base_days, how, windows=None):
    res, per = analyse(sta, day, base_days, windows=windows)
    if res is None:
        print(f"  {sta} {day}: {per}")
        return None
    res["baseline_rule"] = how
    add_aircraft(res, per)
    write_outputs(res, per)
    s = res["signals"].get(PRIMARY, {})
    ac = res.get("aircraft") or {}
    inw = (f", in windows {s.get('flagged_minutes_in_windows')} of {res.get('window_minutes')} min "
           f"(scored {s.get('scored_share_in_windows')})" if windows else "")
    print(f"  {sta} {day}: L1 flagged {s.get('flagged_minutes')} min{inw}, D5 p5 {s.get('d5_p5')} min {s.get('d5_min')} "
          f"dB-Hz, lost {s.get('lost_sat_epochs')}, scored {s.get('scored_share')}; aircraft day share "
          f"{ac.get('share_day')}%, >=30% minutes {ac.get('minutes_share_ge30')} (flagged {ac.get('minutes_share_ge30_flagged')})")
    return res


def cmd_day(a):
    sta = norm(a.station)
    exclude = set(JAMMED) | set(QUIET) | read_days(a.exclude_file)
    if a.baseline:
        base, how = a.baseline.split(","), "given"
    else:
        base, how = baseline_for(sta, a.day, year_shares([sta]), exclude - {a.day})
    print(f"{sta} {a.day}: baseline {base} ({how})")
    run_one(sta, a.day, base, how)


def day_measure(res, windowed, min_scored=MIN_SCORED):
    """The verdict measure of one station-day: flagged GPS L1 C/A minutes (inside the windows when windowed), or None
    when the day is unusable (no result, no L1, or L1 scored on less than min_scored of the epochs counted)."""
    s = (res or {}).get("signals", {}).get(PRIMARY)
    if not s:
        return None
    if windowed:
        ok = s.get("scored_share_in_windows", 0) >= min_scored
        return s.get("flagged_minutes_in_windows") if ok else None
    return s.get("flagged_minutes") if s.get("scored_share", 1.0) >= min_scored else None


def verdict(per_day, jammed, quiet):
    fj = [per_day[d] for d in jammed if per_day.get(d) is not None]
    fq = [per_day[d] for d in quiet if per_day.get(d) is not None]
    if not fj:
        return "NO DATA"
    if sum(1 for v in fj if v >= 10) >= 2 and fq and all(v <= 2 for v in fq):
        return "PRESENT"
    if all(v < 10 for v in fj):
        return "NULL"
    return "MIXED"


def _load(args):
    try:
        return args, load_station_day(*args) is not None
    except Exception as ex:
        return args, f"{type(ex).__name__}: {ex}"


def prefetch(pairs, workers=4):
    """Download and parse station-days in parallel (each lands in the cache)."""
    from multiprocessing import Pool
    todo = [p for p in pairs if not os.path.exists(os.path.join(CACHE, f"{p[0]}_{p[1]}.npz"))]
    print(f"prefetch: {len(todo)} station-days to download and parse ({len(pairs) - len(todo)} cached)")
    with Pool(workers) as pool:
        for (sta, day), ok in pool.imap_unordered(_load, todo):
            if ok is not True:
                print(f"  {sta} {day}: {ok or 'no data'}")


def cmd_test(a):
    stas = [norm(s) for s in a.stations.split(",")] if a.stations else TEST_STATIONS
    jammed = a.days.split(",") if a.days else JAMMED
    quiet = a.quiet.split(",") if a.quiet else QUIET
    windows = {}
    if a.windows:
        with open(a.windows, encoding="utf-8") as f:
            windows = json.load(f)
        unknown = sorted(set(windows) - set(jammed))
        if unknown:
            sys.exit(f"--windows has days that are not test days: {unknown}")
    exclude = set(jammed) | set(quiet) | read_days(a.exclude_file)
    shares = year_shares(stas)
    plan = {(sta, day): baseline_for(sta, day, shares, exclude - {day}) for sta in stas for day in jammed + quiet}
    for (sta, day), (base, how) in plan.items():
        print(f"  {sta} {day}: baseline {', '.join(base)} ({how})")
    if a.plan_only:
        return
    prefetch(sorted({(s, d) for (s, day), (base, _) in plan.items() for d in [day] + base}))
    results = {"rule": a.rule, "stations": {}, "run_utc": datetime.now(timezone.utc).isoformat()[:19] + "Z",
               "jammed": jammed, "quiet": quiet, "windows": windows or None, "exclude_file": a.exclude_file,
               "measure": "flagged GPS L1 C/A minutes" + (" inside the windows on windowed days" if windows else "")}
    for sta in stas:
        print(sta)
        per_day, rows = {}, {}
        for day in jammed + quiet:
            base, how = plan[(sta, day)]
            res = run_one(sta, day, base, how, windows.get(day))
            per_day[day] = day_measure(res, day in windows)
            if res is None:
                continue
            rows[day] = {k: res.get(k) for k in ("baseline_days", "baseline_rule", "epochs_present", "network",
                                                 "km_from_kaliningrad_coast", "receiver", "antenna", "licence",
                                                 "rinex_version", "window_minutes") if k in res}
            rows[day]["signals"] = {n: {k: v for k, v in s.items() if k != "runs"} | {"runs": s["runs"][:12]}
                                    for n, s in res["signals"].items()}
            rows[day]["aircraft"] = res.get("aircraft")
            rows[day]["timing_aligned"] = res.get("timing_aligned")
        results["stations"][sta] = {"verdict": verdict(per_day, jammed, quiet), "flagged_minutes": per_day, "days": rows}
        print(f"  verdict: {results['stations'][sta]['verdict']}")
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, a.out), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)
    print(json.dumps({s: v["verdict"] for s, v in results["stations"].items()}))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("stations"); p.add_argument("--lat", type=float, default=KALININGRAD[0])
    p.add_argument("--lon", type=float, default=KALININGRAD[1]); p.add_argument("--max-km", type=float, default=500)
    p.add_argument("--network", choices=("epn", "noaa"), default="epn")
    p.add_argument("--day"); p.set_defaults(fn=cmd_stations)
    p = sub.add_parser("fetch"); p.add_argument("station"); p.add_argument("days", nargs="+"); p.set_defaults(fn=cmd_fetch)
    p = sub.add_parser("day"); p.add_argument("station"); p.add_argument("day"); p.add_argument("--baseline")
    p.add_argument("--exclude-file", help="days never used as baseline days, one ISO day per line")
    p.set_defaults(fn=cmd_day)
    p = sub.add_parser("test"); p.add_argument("--stations"); p.add_argument("--days"); p.add_argument("--quiet")
    p.add_argument("--exclude-file", help="days never used as baseline days, one ISO day per line")
    p.add_argument("--windows", help="JSON {day: [[start, end], ...]} (UTC, '2026-03-06T07:15Z'); jammed days listed "
                                     "here are scored on flagged minutes inside their windows")
    p.add_argument("--out", default="test_results.json", help="results file name in data/stations/")
    p.add_argument("--rule", default="docs/validation/ground-stations.md", help="where the pre-stated rule is written")
    p.add_argument("--plan-only", action="store_true", help="print the baseline days and stop")
    p.set_defaults(fn=cmd_test)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
