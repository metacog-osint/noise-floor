#!/usr/bin/env python3
"""station_bands.py: interference on every GNSS constellation and band at a fixed reference station (step X1 of
docs/multi-gnss-plan.md). A companion to tools/station_cn0.py, whose GPS L1 rule and pre-stated Baltic test it leaves
unchanged.

  python tools/station_bands.py signals STATION DAY                          # what the station's file tracks
  python tools/station_bands.py day STATION DAY [--baseline d1,d2,...] [--window HH:MM-HH:MM ...] [--exclude-file F]

Every signal-strength (S) code in a RINEX 3/4 daily file is scored with station_cn0's rule: per epoch, D = median
residual over satellites (at least 4) and F = share of satellites 3 dB-Hz or more down; an epoch is flagged where the
centred 5-minute medians reach D <= -3 dB-Hz and F >= 0.75 (runs merge across 2-minute gaps and last 2+ minutes).
Residuals are against quiet baseline days, with a baseline suited to each constellation's orbit:
  * GPS: per satellite, the same place in the sky about 246 s earlier per day (station_cn0's sidereal match).
  * QZSS, BeiDou GEO and IGSO: per satellite, one sidereal day (about 236 s earlier per day). A GEO stays put.
  * GLONASS, Galileo and BeiDou MEO repeat their sky tracks only every 8, 10 and 7 sidereal days: per satellite, the
    median per 2.5 deg elevation bin over the baseline days.
A satellite missing on an epoch where it was expected counts as lost (residual -40 dB-Hz). Sky-matched satellites are
expected where the baseline days tracked them at that place. Elevation-binned ones are expected where the baseline days
tracked at least 90% of that system's satellites in that part of the sky (10 deg azimuth x 2.5 deg elevation), so
obstructions don't count as losses. A satellite the test day hardly tracked on a signal (under 10% of its epochs above
the mask) is left out of that signal.
Orbits come from the merged broadcast file: Keplerian elements for GPS, Galileo, QZSS and BeiDou (BeiDou time is GPS
- 14 s, BDT week 0 = GPS week 1356; GEO satellites use the ICD's extra rotation), and for GLONASS the broadcast state
vectors integrated with RK4 (GLONASS ICD 2008, A.3.1.2: J2 plus the broadcast lunisolar accelerations). Satellites
broadcast as unhealthy are dropped for GPS, Galileo, BeiDou and GLONASS. QZSS health values are recorded but not
applied, because their bits refer to individual signals.

Outputs (data/stations/<STATION>/, gitignored): <day>.bands.json and <day>.bands.png. For each signal: the summary and
flagged runs. For each --window and each event (flagged runs of any signal, merged): the band signature, i.e. the
median D of every signal in the window, plus each GLONASS satellite's residual by FDMA channel.
Times: RINEX epochs are GPS time; windows and outputs are UTC (GPS - 18 s).
"""
import argparse
import gzip
import json
import math
import os
import sys
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import station_cn0 as SC  # noqa: E402

NEP, STEP, LEAP = SC.NEP, SC.STEP, SC.LEAP
MASK = SC.MASK_DEG
SIDEREAL_DAY_S = 86164.0905
SHIFT_1SD = 86400.0 - SIDEREAL_DAY_S        # ~235.9 s: one-sidereal-day orbits come back this much earlier each day
ELBIN = 2.5
TRACK_MIN = 0.10                             # share of above-mask epochs a satellite must be tracked on the test day
SKY_AZ, SKY_EL, SKY_SHARE, SKY_MIN = 10.0, 2.5, 0.90, 20

# name, system, RINEX signal-strength codes by preference, carrier MHz (None: GLONASS FDMA, per satellite)
SIGNALS = [
    ("GPS L1 C/A", "G", ["S1C"], 1575.42),
    ("GPS L1C", "G", ["S1L", "S1X", "S1S"], 1575.42),
    ("GPS L2C", "G", ["S2L", "S2S", "S2X"], 1227.60),
    ("GPS L2 P(Y)", "G", ["S2W", "S2D"], 1227.60),
    ("GPS L5", "G", ["S5Q", "S5X", "S5I"], 1176.45),
    ("GLONASS G1 C/A", "R", ["S1C"], None),
    ("GLONASS G1 P", "R", ["S1P"], None),
    ("GLONASS G2 C/A", "R", ["S2C"], None),
    ("GLONASS G2 P", "R", ["S2P"], None),
    ("GLONASS G3", "R", ["S3Q", "S3X", "S3I"], 1202.025),
    ("Galileo E1", "E", ["S1C", "S1X", "S1B"], 1575.42),
    ("Galileo E5a", "E", ["S5Q", "S5X", "S5I"], 1176.45),
    ("Galileo E5b", "E", ["S7Q", "S7X", "S7I"], 1207.14),
    ("Galileo E5 AltBOC", "E", ["S8Q", "S8X", "S8I"], 1191.795),
    ("Galileo E6", "E", ["S6C", "S6X", "S6B"], 1278.75),
    ("BeiDou B1I", "C", ["S2I", "S2X", "S2Q"], 1561.098),
    ("BeiDou B1C", "C", ["S1P", "S1X", "S1D"], 1575.42),
    ("BeiDou B2a", "C", ["S5P", "S5X", "S5D"], 1176.45),
    ("BeiDou B2I", "C", ["S7I", "S7X", "S7Q"], 1207.14),
    ("BeiDou B2b", "C", ["S7D", "S7P", "S7Z"], 1207.14),
    ("BeiDou B3I", "C", ["S6I", "S6X", "S6Q"], 1268.52),
    ("QZSS L1 C/A", "J", ["S1C"], 1575.42),
    ("QZSS L1C", "J", ["S1L", "S1X", "S1S"], 1575.42),
    ("QZSS L1S", "J", ["S1Z"], 1575.42),
    ("QZSS L2C", "J", ["S2L", "S2S", "S2X"], 1227.60),
    ("QZSS L5", "J", ["S5Q", "S5X", "S5I"], 1176.45),
    ("QZSS L6", "J", ["S6L", "S6X", "S6S", "S6E", "S6Z"], 1278.75),
]
NAMES = {"G": "GPS", "R": "GLONASS", "E": "Galileo", "C": "BeiDou", "J": "QZSS"}

MU_GPS, WE_GPS = 3.986005e14, 7.2921151467e-5
MU_GAL = 3.986004418e14
MU_BDS, WE_BDS = 3.986004418e14, 7.2921150e-5
BDT_WEEK0, BDT_OFFSET = 1356, 14.0            # BDT week 0 = GPS week 1356; BDT = GPS - 14 s
GLO_MU, GLO_AE, GLO_J2, GLO_WE = 3.986004418e14, 6378136.0, 1.08262575e-3, 7.292115e-5


def glonass_mhz(k, band):
    """FDMA carrier (MHz) of GLONASS channel k on G1 or G2 (GLONASS ICD 2008, 3.3.1.4)."""
    return 1602.0 + 0.5625 * k if band == 1 else 1246.0 + 0.4375 * k


def pick_code(types, sysc, prefs):
    """The first preferred code the file carries for that system, or None."""
    have = set(types.get(sysc, ()))
    return next((c for c in prefs if c in have), None)


# ---------- broadcast orbits ----------

def _records(text):
    lines = text.splitlines()
    i = next((k + 1 for k, l in enumerate(lines) if l[60:80].strip() == "END OF HEADER"), 0)
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line[:1].isalpha():
            i += 1
            continue
        j = i + 1
        while j < n and lines[j][:4] == "    ":
            j += 1
        yield lines[i:j]
        i = j


def _utc_gps_seconds(line):
    """GPS seconds of a RINEX 3 navigation epoch given in UTC (GLONASS records)."""
    y, mo, d, h, mi, s = (int(line[4:8]), int(line[9:11]), int(line[12:14]), int(line[15:17]), int(line[18:20]),
                          int(float(line[21:23])))
    return (datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc) - SC.GPS0).total_seconds() + LEAP


def parse_nav_all(text):
    """RINEX 3 merged navigation -> (kepler {sat: [record]}, glonass {sat: [record]}).

    Kepler records (G, E, J, C) carry the IS-GPS-200 field set plus 'sys' and 'toe_abs' (GPS seconds). GLONASS records
    carry 't' (GPS seconds), 'pos', 'vel', 'acc' (m, m/s, m/s^2), 'health' and the FDMA channel 'k'."""
    kep, glo = {}, {}
    for rec in _records(text):
        sysc, sat = rec[0][0], rec[0][:3].replace(" ", "0")
        if sysc in "GEJC" and len(rec) >= 8:
            v = [SC._f(rec[0][23 + 19 * k:42 + 19 * k]) for k in range(3)]
            for r in rec[1:8]:
                v += [SC._f(r[4 + 19 * k:23 + 19 * k]) for k in range(4)]
            e = {"crs": v[4], "dn": v[5], "m0": v[6], "cuc": v[7], "e": v[8], "cus": v[9], "sqrta": v[10],
                 "toe": v[11], "cic": v[12], "om0": v[13], "cis": v[14], "i0": v[15], "crc": v[16], "w": v[17],
                 "omd": v[18], "idot": v[19], "week": v[21], "health": v[24], "sys": sysc}
            if e["sqrta"] < 1000:
                continue
            e["toe_abs"] = ((e["week"] + BDT_WEEK0) * 604800.0 + e["toe"] + BDT_OFFSET if sysc == "C"
                            else e["week"] * 604800.0 + e["toe"])
            kep.setdefault(sat, []).append(e)
        elif sysc == "R" and len(rec) >= 4:
            f = [[SC._f(r[4 + 19 * k:23 + 19 * k]) for k in range(4)] for r in rec[1:4]]
            glo.setdefault(sat, []).append({
                "t": _utc_gps_seconds(rec[0]),
                "pos": [f[0][0] * 1e3, f[1][0] * 1e3, f[2][0] * 1e3],
                "vel": [f[0][1] * 1e3, f[1][1] * 1e3, f[2][1] * 1e3],
                "acc": [f[0][2] * 1e3, f[1][2] * 1e3, f[2][2] * 1e3],
                "health": f[0][3], "k": int(round(f[1][3]))})
    return kep, glo


def orbit_class(e):
    """'geo', 'igso' or 'meo' from the semi-major axis and inclination."""
    if e["sqrta"] < 6000:
        return "meo"
    return "geo" if e["i0"] < math.radians(20) else "igso"


def kep_xyz(e, t_abs):
    """Earth-fixed position (m) at GPS seconds t_abs from one Keplerian broadcast record (GPS, Galileo, QZSS, BeiDou)."""
    if e["sys"] in "GE":
        return SC.sat_xyz(e, np.asarray(t_abs, float), gal=e["sys"] == "E")
    bds = e["sys"] == "C"
    mu, we = (MU_BDS, WE_BDS) if bds else (MU_GPS, WE_GPS)
    tk = np.asarray(t_abs, float) - e["toe_abs"]
    a = e["sqrta"] ** 2
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
    geo = bds and orbit_class(e) == "geo"
    if geo:     # BeiDou ICD (B1I 3.0, 5.2.4.12): an inertial-like frame, then Rz(we*tk) Rx(-5 deg)
        om = e["om0"] + e["omd"] * tk - we * e["toe"]
    else:
        om = e["om0"] + (e["omd"] - we) * tk - we * e["toe"]
    X = xp * np.cos(om) - yp * np.cos(inc) * np.sin(om)
    Y = xp * np.sin(om) + yp * np.cos(inc) * np.cos(om)
    Z = yp * np.sin(inc)
    if geo:
        f = math.radians(-5.0)
        Y, Z = Y * math.cos(f) + Z * math.sin(f), -Y * math.sin(f) + Z * math.cos(f)
        g = we * tk
        X, Y = X * np.cos(g) + Y * np.sin(g), -X * np.sin(g) + Y * np.cos(g)
    return np.stack([X, Y, Z], axis=-1)


def _glo_deriv(s, acc):
    x, y, z, vx, vy, vz = (s[:, k] for k in range(6))
    r2 = x * x + y * y + z * z
    r = np.sqrt(r2)
    mr3 = GLO_MU / (r2 * r)
    j = 1.5 * GLO_J2 * GLO_MU * GLO_AE ** 2 / (r2 * r2 * r)
    q = 5.0 * z * z / r2
    w2 = GLO_WE ** 2
    ax = -mr3 * x - j * x * (1.0 - q) + w2 * x + 2.0 * GLO_WE * vy + acc[:, 0]
    ay = -mr3 * y - j * y * (1.0 - q) + w2 * y - 2.0 * GLO_WE * vx + acc[:, 1]
    az = -mr3 * z - j * z * (3.0 - q) + acc[:, 2]
    return np.stack([vx, vy, vz, ax, ay, az], axis=1)


def glo_rk4(s, acc, h):
    """One RK4 step of h seconds (one value per row) for GLONASS states s (N, 6) in PZ-90 (m, m/s)."""
    h = np.asarray(h, float)[:, None]
    k1 = _glo_deriv(s, acc)
    k2 = _glo_deriv(s + 0.5 * h * k1, acc)
    k3 = _glo_deriv(s + 0.5 * h * k2, acc)
    k4 = _glo_deriv(s + h * k3, acc)
    return s + h / 6.0 * (k1 + 2 * k2 + 2 * k3 + k4)


def glo_propagate(recs, dts, max_step=30.0):
    """Positions (N, M, 3) of N GLONASS records at offsets dts (N, M) seconds from each record's epoch (NaN: none).

    Each row's offsets must be sorted away from zero (all >= 0, or all <= 0); steps are at most max_step."""
    dts = np.asarray(dts, float)
    s = np.array([r["pos"] + r["vel"] for r in recs], float)
    acc = np.array([r["acc"] for r in recs], float)
    out = np.full(dts.shape + (3,), np.nan)
    tau = np.zeros(len(recs))
    for j in range(dts.shape[1]):
        tgt = dts[:, j]
        h = np.where(np.isfinite(tgt), tgt - tau, 0.0)
        nsub = max(1, int(math.ceil(np.max(np.abs(h)) / max_step))) if len(h) else 1
        for _ in range(nsub):
            s = glo_rk4(s, acc, h / nsub)
        tau = tau + h
        ok = np.isfinite(tgt)
        out[ok, j] = s[ok, :3]
    return out


def glonass_xyz(recs, t, max_age=1800.0):
    """(T, 3) positions at GPS seconds t from one satellite's healthy GLONASS records (nearest record, within max_age)."""
    recs = [r for r in recs if r["health"] == 0]
    xyz = np.full((len(t), 3), np.nan)
    if not recs:
        return xyz
    tb = np.array([r["t"] for r in recs])
    pick = np.argmin(np.abs(t[:, None] - tb[None, :]), axis=1)
    age = t - tb[pick]
    use = np.abs(age) <= max_age
    for sign in (1, -1):
        rows, offs, where = [], [], []
        for k in np.unique(pick[use]):
            m = use & (pick == k) & ((age >= 0) if sign > 0 else (age < 0))
            idx = np.flatnonzero(m)
            if not len(idx):
                continue
            order = np.argsort(np.abs(age[idx]))
            rows.append(recs[k]); offs.append(age[idx][order]); where.append(idx[order])
        if not rows:
            continue
        width = max(len(o) for o in offs)
        D = np.full((len(rows), width), np.nan)
        for i, o in enumerate(offs):
            D[i, :len(o)] = o
        P = glo_propagate(rows, D)
        for i, idx in enumerate(where):
            xyz[idx] = P[i, :len(idx)]
    return xyz


def sky_all(kep, glo, sta_xyz, day, max_age=7200.0, max_age_glo=1800.0):
    """{sat: (az, el)} per epoch for every satellite with a usable orbit, and {sat: metadata}.

    GPS, Galileo, BeiDou and GLONASS records broadcast as unhealthy are skipped; QZSS health values are kept in the
    metadata only."""
    t = SC.gps_seconds(day) + np.arange(NEP) * STEP
    out, meta = {}, {}
    for sat, recs in kep.items():
        health = sorted({r["health"] for r in recs})
        if sat[0] != "J":
            recs = [r for r in recs if r["health"] == 0]
        if not recs:
            meta[sat] = {"unhealthy": True, "health": health}
            continue
        toe = np.array([r["toe_abs"] for r in recs])
        pick = np.argmin(np.abs(t[:, None] - toe[None, :]), axis=1)
        age = np.abs(t - toe[pick])
        xyz = np.full((NEP, 3), np.nan)
        for k in np.unique(pick):
            m = (pick == k) & (age <= max_age)
            if m.any():
                xyz[m] = kep_xyz(recs[k], t[m])
        if np.isfinite(xyz).any():
            out[sat] = SC.azel(xyz, sta_xyz)
            meta[sat] = {"orbit": orbit_class(recs[0]), "health": health}
    for sat, recs in glo.items():
        ks = sorted({r["k"] for r in recs})
        xyz = glonass_xyz(recs, t, max_age_glo)
        if np.isfinite(xyz).any():
            out[sat] = SC.azel(xyz, sta_xyz)
            meta[sat] = {"orbit": "meo", "k": ks[0] if len(ks) == 1 else ks, "health": sorted({r["health"] for r in recs})}
        else:
            meta[sat] = {"unhealthy": True, "k": ks[0] if len(ks) == 1 else ks,
                         "health": sorted({r["health"] for r in recs})}
    return out, meta


# ---------- station-day loading (all systems, all S codes) ----------

def load_day(sta, day, fetch_missing=True):
    """Parsed station-day (every S code, every system) from cache, else download + parse.

    Returns dict(hdr, keys [(sat, code)], vals (N, NEP), present, sky_sats, az, el, meta) or None."""
    os.makedirs(SC.CACHE, exist_ok=True)
    cp = os.path.join(SC.CACHE, f"{sta}_{SC.iso(day)}.bands.npz")
    if os.path.exists(cp):
        z = np.load(cp, allow_pickle=False)
        return {"hdr": json.loads(str(z["hdr"])), "keys": [tuple(k.split("|")) for k in z["keys"]], "vals": z["vals"],
                "present": z["present"], "sky_sats": list(z["sky_sats"]), "az": z["az"], "el": z["el"],
                "meta": json.loads(str(z["meta"]))}
    if not fetch_missing:
        return None
    op, nav = SC.fetch(sta, day)
    if not op or not nav:
        return None
    import hatanaka
    with open(op, "rb") as f:
        text = hatanaka.decompress(f.read()).decode("latin-1")
    hdr, obs, present = SC.parse_obs(text, day, keep="all")
    del text
    if not str(hdr.get("version", "")).startswith(("3", "4")):
        raise ValueError(f"{sta} {day}: RINEX {hdr.get('version')} has no tracking-mode letters; use station_cn0.py")
    with gzip.open(nav, "rb") as f:
        kep, glo = parse_nav_all(f.read().decode("latin-1"))
    sk, meta = sky_all(kep, glo, hdr["xyz"], day)
    keys = sorted((s, c) for s in obs for c in obs[s])
    vals = np.array([obs[s][c] for s, c in keys], np.float32).reshape(len(keys), NEP)
    sky_sats = sorted(sk)
    az = np.array([sk[s][0] for s in sky_sats], np.float32).reshape(len(sky_sats), NEP)
    el = np.array([sk[s][1] for s in sky_sats], np.float32).reshape(len(sky_sats), NEP)
    hdr["obs_file"], hdr["nav_file"] = os.path.basename(op), os.path.basename(nav)
    np.savez_compressed(cp, hdr=json.dumps(hdr), keys=np.array([f"{s}|{c}" for s, c in keys]), vals=vals,
                        present=present, sky_sats=np.array(sky_sats), az=az, el=el, meta=json.dumps(meta))
    return load_day(sta, day, fetch_missing=False)


def series(sd, code, sats):
    """(len(sats), NEP) values of one code and (az, el), NaN where absent."""
    ki = {k: i for i, k in enumerate(sd["keys"])}
    si = {s: i for i, s in enumerate(sd["sky_sats"])}
    v = np.full((len(sats), NEP), np.nan)
    az = np.full((len(sats), NEP), np.nan)
    el = np.full((len(sats), NEP), np.nan)
    for i, s in enumerate(sats):
        if (s, code) in ki:
            v[i] = sd["vals"][ki[(s, code)]]
        if s in si:
            az[i], el[i] = sd["az"][si[s]], sd["el"][si[s]]
    return v, az, el


# ---------- baselines and residuals ----------

def kind_of(sat, meta):
    """('sky', shift s/day) for GPS, QZSS and BeiDou GEO/IGSO; ('elbin', None) for GLONASS, Galileo and BeiDou MEO."""
    if sat[0] == "G":
        return ("sky", SC.SHIFT_S)
    if sat[0] == "J" or (sat[0] == "C" and meta.get(sat, {}).get("orbit") in ("geo", "igso")):
        return ("sky", SHIFT_1SD)
    return ("elbin", None)


def sat_elbin_baseline(base_vals, base_els, test_el, binw=ELBIN, min_days=SC.MIN_BASE):
    """One satellite's own median C/N0 per elevation bin over the baseline days, looked up at the test-day elevations.

    base_vals, base_els: lists (one per baseline day) of (T,) arrays. Returns (baseline, days) shaped like test_el."""
    nb = int(90 // binw) + 1
    pooled = [[] for _ in range(nb)]
    days = np.zeros(nb, int)
    for v, e in zip(base_vals, base_els):
        ok = np.isfinite(v) & np.isfinite(e) & (e >= 0)
        if not ok.any():
            continue
        b, vv = np.minimum((e[ok] // binw).astype(int), nb - 1), v[ok]
        for k in np.unique(b):
            pooled[k].append(vv[b == k])
            days[k] += 1
    med = np.array([np.median(np.concatenate(p)) if p else np.nan for p in pooled])
    te = np.where(np.isfinite(test_el), test_el, -1.0)
    bi = np.clip((te // binw).astype(int), 0, nb - 1)
    base = np.where(te >= 0, med[bi], np.nan)
    cnt = np.where(te >= 0, days[bi], 0)
    return np.where(cnt >= min_days, base, np.nan), cnt


def sky_cells(az, el):
    """Cell index of each (az, el) on a SKY_AZ x SKY_EL grid (-1 where undefined)."""
    az, el = np.asarray(az, float), np.asarray(el, float)
    ok = np.isfinite(az) & np.isfinite(el) & (el >= 0)
    na = int(360 // SKY_AZ)
    ai = np.where(ok, (np.nan_to_num(az) % 360.0) // SKY_AZ, 0).astype(int)
    ei = np.where(ok, np.minimum(np.nan_to_num(el) // SKY_EL, 90 // SKY_EL), 0).astype(int)
    return np.where(ok, ei * na + ai, -1)


def tracked_sky(base_triples, mask=MASK):
    """Where the baseline days tracked the system: bool per sky cell, True where at least SKY_SHARE of the above-mask
    satellite-epochs were tracked (and SKY_MIN or more were seen). base_triples: [(vals, az, el)] of (nsat, T) arrays."""
    ncell = int(360 // SKY_AZ) * (int(90 // SKY_EL) + 1)
    seen, got = np.zeros(ncell), np.zeros(ncell)
    for v, az, el in base_triples:
        with np.errstate(invalid="ignore"):
            up = np.isfinite(el) & (el >= mask)
        c = sky_cells(az, el)[up]
        seen += np.bincount(c, minlength=ncell)
        got += np.bincount(c[np.isfinite(v[up])], minlength=ncell)
    with np.errstate(invalid="ignore", divide="ignore"):
        return (seen >= SKY_MIN) & (got / np.maximum(seen, 1) >= SKY_SHARE)


def score(test_vals, base, cnt, el, present, loss_ok, keep, mask=MASK, min_base=SC.MIN_BASE):
    """Per-satellite residuals (nsat, T): test - baseline where scored; SC.LOSS_DB where a satellite was expected but
    missing (loss_ok); NaN otherwise. keep: (nsat,) satellites tracked enough on the test day to score."""
    test_vals = np.asarray(test_vals, float)
    with np.errstate(invalid="ignore"):
        ok = ((np.asarray(el) >= mask) & (np.asarray(cnt) >= min_base) & np.isfinite(base)
              & np.asarray(present)[None, :] & np.asarray(keep)[:, None])
    r = np.full(test_vals.shape, np.nan)
    have = ok & np.isfinite(test_vals)
    r[have] = test_vals[have] - base[have]
    r[ok & ~np.isfinite(test_vals) & np.asarray(loss_ok, bool)] = SC.LOSS_DB
    return r


def tracked_enough(test_vals, el, mask=MASK, share=TRACK_MIN):
    with np.errstate(invalid="ignore"):
        up = np.isfinite(el) & (el >= mask)
    n_up = up.sum(axis=1)
    n_tr = (up & np.isfinite(test_vals)).sum(axis=1)
    return (n_up > 0) & (n_tr >= share * np.maximum(n_up, 1))


def signal_residuals(test, bases, day, sysc, code, meta):
    """Residuals (nsat, NEP) of one signal, its satellites, and their (az, el) on the test day."""
    sats = sorted(s for s in test["sky_sats"] if s[0] == sysc)
    tv, taz, tel = series(test, code, sats)
    if not np.isfinite(tv).any():
        return None
    keep = tracked_enough(tv, tel)
    base = np.full(tv.shape, np.nan)
    cnt = np.zeros(tv.shape, int)
    loss_ok = np.zeros(tv.shape, bool)
    bser = {d: series(b, code, sats) for d, b in bases.items()}
    sky_ok = None
    for i, sat in enumerate(sats):
        kind, shift = kind_of(sat, meta)
        if kind == "sky":
            stack = []
            for d, (bv, baz, bel) in bser.items():
                k = (SC.pday(day) - SC.pday(d)).days
                stack.append(SC.take(bv[i], SC.sidereal_index(taz[i], tel[i], baz[i], bel[i], k, shift_s=shift)))
            if stack:
                base[i], c = SC.combine_baseline(np.array(stack))
                cnt[i] = c
                loss_ok[i] = np.isfinite(base[i])
        else:
            if sky_ok is None:
                sky_ok = tracked_sky([(bv, baz, bel) for bv, baz, bel in bser.values()])
            base[i], cnt[i] = sat_elbin_baseline([bv[i] for bv, _, _ in bser.values()],
                                                 [bel[i] for _, _, bel in bser.values()], tel[i])
            cells = sky_cells(taz[i], tel[i])
            loss_ok[i] = np.where(cells >= 0, sky_ok[np.clip(cells, 0, None)], False)
    r = score(tv, base, cnt, tel, test["present"], loss_ok, keep)
    return r, sats, taz, tel


# ---------- signatures ----------

def utc_epochs(hhmm_window):
    """'HH:MM-HH:MM' (UTC) -> inclusive epoch indices (a, b) of the GPS-time day grid."""
    a, b = hhmm_window.split("-")
    s0 = int(a[:2]) * 3600 + int(a[3:5]) * 60 + LEAP
    s1 = int(b[:2]) * 3600 + int(b[3:5]) * 60 + LEAP
    return max(0, int(math.ceil(s0 / STEP))), min(NEP - 1, int(s1 // STEP))


def merge_runs(run_lists, step=STEP, merge_s=SC.MERGE_S):
    """Union of [(a, b)] runs from several signals, merged across gaps of up to merge_s."""
    spans = sorted(r for rl in run_lists for r in rl)
    out = []
    for a, b in spans:
        if out and (a - out[-1][1] - 1) * step <= merge_s:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def signature(per, a, b):
    """Band signature over epochs a..b: per signal, median D, lowest 5-min D, median satellites and lost share."""
    rows = []
    for name, p in per.items():
        D, d5, n, r = p["D"][a:b + 1], p["d5"][a:b + 1], p["n"][a:b + 1], p["r"][:, a:b + 1]
        fin = np.isfinite(D)
        scored = np.isfinite(r)
        with np.errstate(invalid="ignore"):
            lost = float(np.sum(r == SC.LOSS_DB)) / max(int(scored.sum()), 1)
        rows.append({"signal": name, "code": p["code"], "mhz": p["mhz"],
                     "d_median": round(float(np.median(D[fin])), 2) if fin.any() else None,
                     "d5_min": round(float(np.nanmin(d5)), 2) if np.isfinite(d5).any() else None,
                     "sats": int(np.median(n[fin])) if fin.any() else 0, "lost_share": round(lost, 3)})
    rows.sort(key=lambda x: (x["mhz"][0] if isinstance(x["mhz"], list) else (x["mhz"] or 0), x["signal"]))
    return rows


def glonass_ladder(per, meta, a, b):
    """Per GLONASS satellite and FDMA signal: channel k, carrier MHz and median residual over epochs a..b."""
    out = []
    for name, p in per.items():
        if not name.startswith("GLONASS G1") and not name.startswith("GLONASS G2"):
            continue
        band = 1 if "G1" in name else 2
        for i, sat in enumerate(p["sats"]):
            seg = p["r"][i, a:b + 1]
            seg = seg[np.isfinite(seg)]
            k = meta.get(sat, {}).get("k")
            if len(seg) < 3 or not isinstance(k, int):
                continue
            out.append({"signal": name, "sat": sat, "k": k, "mhz": round(glonass_mhz(k, band), 4),
                        "residual": round(float(np.median(seg)), 2), "epochs": int(len(seg)),
                        "lost": int(np.sum(seg == SC.LOSS_DB))})
    return sorted(out, key=lambda x: (x["mhz"], x["signal"]))


def hhmm(i):
    return SC.utc_hhmm(i)


# ---------- one station-day ----------

def analyse(sta, day, base_days, windows=(), fetch_missing=True):
    """Score every signal of one station-day. Returns (result dict, per-signal arrays) or (None, reason)."""
    test = load_day(sta, day, fetch_missing)
    if test is None:
        return None, "no data"
    bases = {}
    for d in base_days:
        try:
            b = load_day(sta, d, fetch_missing)
        except Exception as ex:            # one bad baseline file shouldn't stop the day
            print(f"  baseline {d}: {type(ex).__name__}: {ex}", file=sys.stderr)
            b = None
        if b is not None:
            bases[d] = b
    meta = test["meta"]
    lat, lon, _ = SC.ecef_to_geodetic(*test["hdr"]["xyz"])
    types = {}
    for s, c in test["keys"]:
        types.setdefault(s[0], set()).add(c)
    res = {"station": sta, "day": SC.iso(day), "lat": round(lat, 4), "lon": round(lon, 4),
           "receiver": test["hdr"].get("receiver"), "firmware": test["hdr"].get("firmware"),
           "antenna": test["hdr"].get("antenna"), "obs_file": test["hdr"].get("obs_file"),
           "nav_file": test["hdr"].get("nav_file"), "rinex_version": test["hdr"].get("version"),
           "epochs_present": int(test["present"].sum()), "baseline_days": sorted(bases),
           "unhealthy": sorted(s for s, m in meta.items() if m.get("unhealthy")),
           "qzss_health": {s: m.get("health") for s, m in meta.items() if s[0] == "J"},
           "signals": {}, "windows": [], "events": []}
    per = {}
    for name, sysc, prefs, mhz in SIGNALS:
        code = pick_code(types, sysc, prefs)
        if code is None:
            continue
        out = signal_residuals(test, bases, day, sysc, code, meta)
        if out is None:
            continue
        r, sats, taz, tel = out
        D, F, n = SC.station_stats(r)
        flags, d5, f5 = SC.flag_epochs(D, F)
        rs = SC.runs(flags)
        fm = SC.epochs_to_minutes(SC.run_mask(rs), how="any")
        fin = d5[np.isfinite(d5)]
        if mhz is None:
            ks = sorted({meta[s]["k"] for s in sats if isinstance(meta.get(s, {}).get("k"), int)})
            band = 1 if "G1" in name else 2
            mhz_v = [round(glonass_mhz(ks[0], band), 3), round(glonass_mhz(ks[-1], band), 3)] if ks else None
        else:
            mhz_v = mhz
        with np.errstate(invalid="ignore"):
            lost = int(np.sum(r == SC.LOSS_DB))
        res["signals"][name] = {
            "system": NAMES[sysc], "code": code, "mhz": mhz_v,
            "baseline": sorted({kind_of(s, meta)[0] for s in sats}),
            "epochs_scored": int(np.isfinite(D).sum()), "scored_share": round(float(np.isfinite(D).sum()) / NEP, 3),
            "sats_median": float(np.median(n[np.isfinite(D)])) if np.isfinite(D).any() else 0.0,
            "d5_p50": round(float(np.percentile(fin, 50)), 2) if len(fin) else None,
            "d5_p1": round(float(np.percentile(fin, 1)), 2) if len(fin) else None,
            "d5_min": round(float(fin.min()), 2) if len(fin) else None,
            "lost_sat_epochs": lost, "flagged_minutes": int(fm.sum()),
            "runs": [{"start": hhmm(a), "end": hhmm(b), "minutes": round((b - a + 1) * STEP / 60, 1),
                      "d5_min": round(float(np.nanmin(d5[a:b + 1])), 1), "f5_max": round(float(np.nanmax(f5[a:b + 1])), 2)}
                     for a, b in rs]}
        if np.isfinite(D).any():         # a signal never scored (too few satellites) stays out of the signatures
            per[name] = {"D": D, "F": F, "n": n, "d5": d5, "f5": f5, "r": r, "sats": sats, "code": code, "mhz": mhz_v,
                         "runs": rs}
    for w in windows:
        a, b = utc_epochs(w)
        res["windows"].append({"window_utc": w, "signature": signature(per, a, b), "glonass": glonass_ladder(per, meta, a, b)})
    for a, b in merge_runs([p["runs"] for p in per.values()]):
        res["events"].append({"start": hhmm(a), "end": hhmm(b), "flagged_on": sorted(n for n, p in per.items()
                                                                                    if any(x <= b and y >= a for x, y in p["runs"])),
                              "signature": signature(per, a, b), "glonass": glonass_ladder(per, meta, a, b)})
    return res, per


# ---------- outputs ----------

def write_outputs(res, per):
    d = os.path.join(SC.OUT, res["station"])
    os.makedirs(d, exist_ok=True)
    mins = {name: [None if not np.isfinite(v) else round(float(v), 2) for v in SC.epochs_to_minutes(p["d5"])]
            for name, p in per.items()}
    out = dict(res, minutes_utc=mins, credit=SC.CREDIT.get("epn"), tool="tools/station_bands.py",
               method="docs/multi-gnss-plan.md (step X1)")
    with open(os.path.join(d, f"{res['day']}.bands.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    try:
        plot(res, per, os.path.join(d, f"{res['day']}.bands.png"))
    except ImportError:
        pass


def plot(res, per, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    hrs = (np.arange(NEP) * STEP - LEAP) / 3600.0
    sig = (res["windows"][0] if res["windows"] else (res["events"][0] if res["events"] else None))
    fig, ax = plt.subplots(2, 1, figsize=(11, 9), gridspec_kw={"height_ratios": [1.2, 1]})
    cmap = plt.get_cmap("viridis")

    def mhz_of(p):
        m = p["mhz"]
        return (m[0] + m[1]) / 2 if isinstance(m, list) else m

    lo, hi = 1160.0, 1610.0
    for name, p in sorted(per.items(), key=lambda kv: mhz_of(kv[1])):
        c = cmap((mhz_of(p) - lo) / (hi - lo))
        ax[0].plot(hrs, np.clip(p["d5"], -20, 3), lw=0.8, color=c, label=name)
    for e in res["events"]:
        a = int(e["start"][:2]) + int(e["start"][3:5]) / 60
        b = int(e["end"][:2]) + int(e["end"][3:5]) / 60
        ax[0].axvspan(a, b + 1 / 60, color="#d62728", alpha=0.15, lw=0)
    for w in res["windows"]:
        a, b = w["window_utc"].split("-")
        ax[0].axvspan(int(a[:2]) + int(a[3:5]) / 60, int(b[:2]) + int(b[3:5]) / 60, color="#999", alpha=0.2, lw=0)
    ax[0].axhline(SC.D_THR, color="#d62728", ls="--", lw=0.8)
    ax[0].axhline(0, color="#888", lw=0.5)
    lows = [np.nanmin(p["d5"]) for p in per.values() if np.isfinite(p["d5"]).any()]
    ymin = max(-20.0, min([-6.0] + [math.floor(v) - 1 for v in lows]))
    ax[0].set_xlim(0, 24); ax[0].set_xticks(range(0, 25, 3)); ax[0].set_ylim(ymin, 3)
    ax[0].set_xlabel("hour (UTC)")
    ax[0].set_ylabel("C/N0 vs quiet days, dB-Hz\n(median over satellites, 5-min)", fontsize=8)
    ax[0].legend(fontsize=6, ncol=4, loc="lower left")
    if sig:
        rows = [r for r in sig["signature"] if r["d_median"] is not None]
        y = np.arange(len(rows))
        ax[1].barh(y, [r["d_median"] for r in rows], color=[cmap((((r["mhz"][0] + r["mhz"][1]) / 2 if isinstance(r["mhz"], list)
                                                                    else r["mhz"]) - lo) / (hi - lo)) for r in rows])
        ax[1].set_yticks(y, [f"{r['signal']} ({r['code']})  "
                             f"{(str(r['mhz'][0]) + '-' + str(r['mhz'][1])) if isinstance(r['mhz'], list) else r['mhz']} MHz"
                             for r in rows], fontsize=7)
        ax[1].axvline(0, color="#888", lw=0.5)
        ax[1].axvline(SC.D_THR, color="#d62728", ls="--", lw=0.8)
        ax[1].set_xlabel("median C/N0 change in the window, dB-Hz")
        when = sig.get("window_utc") or f"{sig['start']}-{sig['end']}"
        ax[1].set_title(f"Band signature, {when} UTC (lowest carrier at top)", fontsize=9)
        ax[1].invert_yaxis()
    else:
        ax[1].axis("off")
    fig.suptitle(f"{res['station']}  {res['day']}  every tracked signal against {len(res['baseline_days'])} quiet days",
                 fontsize=10)
    fig.text(0.01, 0.005, "Station data: EPN/IGS (CC BY 4.0). Broadcast orbits: IGS. Noisefloor, tools/station_bands.py. "
             "Red: flagged on some signal. Grey: requested window.", fontsize=6, color="#666")
    fig.tight_layout(rect=(0, 0.02, 1, 0.97))
    fig.savefig(path, dpi=110)
    plt.close(fig)


def print_summary(res):
    print(f"{res['station']} {res['day']}: {res.get('receiver')} {res.get('firmware')}, {res.get('antenna')}; "
          f"baseline {', '.join(res['baseline_days'])}")
    if res["unhealthy"]:
        print(f"  unhealthy (left out): {' '.join(res['unhealthy'])}")
    print(f"  {'signal':20s} {'code':4s} {'MHz':>17s} {'sats':>4s} {'scored':>6s} {'p1':>6s} {'min':>6s} {'flag min':>8s}")
    for name, s in res["signals"].items():
        m = f"{s['mhz'][0]}-{s['mhz'][1]}" if isinstance(s["mhz"], list) else f"{s['mhz']}"
        print(f"  {name:20s} {s['code']:4s} {m:>17s} {s['sats_median']:4.0f} {s['scored_share']:6.2f} "
              f"{s['d5_p1'] if s['d5_p1'] is not None else '-':>6} {s['d5_min'] if s['d5_min'] is not None else '-':>6} "
              f"{s['flagged_minutes']:8d}")
    for blk in res["windows"] + res["events"]:
        when = blk.get("window_utc") or f"event {blk['start']}-{blk['end']} (flagged on {', '.join(blk['flagged_on'])})"
        print(f"  {when}: median D per signal, dB-Hz")
        for r in blk["signature"]:
            m = f"{r['mhz'][0]}-{r['mhz'][1]}" if isinstance(r["mhz"], list) else f"{r['mhz']}"
            d = "-" if r["d_median"] is None else f"{r['d_median']:+.1f}"
            print(f"    {m:>17s} MHz  {r['signal']:20s} {d:>6s}  (lowest 5-min {r['d5_min']}, sats {r['sats']}, "
                  f"lost {r['lost_share']:.0%})")
        lad = [g for g in blk["glonass"] if g["signal"].endswith("C/A")]
        if lad:
            print("    GLONASS C/A by channel: " + "; ".join(f"{g['sat']} k={g['k']:+d} {g['mhz']} MHz {g['residual']:+.1f}"
                                                         for g in lad))


# ---------- commands ----------

def cmd_signals(a):
    sd = load_day(SC.norm(a.station), a.day)
    if sd is None:
        sys.exit("no data")
    types = {}
    for s, c in sd["keys"]:
        types.setdefault(s[0], set()).add(c)
    print(f"{a.station} {a.day}: {sd['hdr'].get('receiver')} {sd['hdr'].get('firmware')}, {sd['hdr'].get('antenna')}")
    for name, sysc, prefs, mhz in SIGNALS:
        code = pick_code(types, sysc, prefs)
        if code:
            nsat = len({s for s, c in sd["keys"] if s[0] == sysc and c == code})
            print(f"  {name:20s} {code}  {nsat:3d} satellites")
    left = sorted(f"{s}:{c}" for s, cs in types.items() for c in cs
                  if not any(sy == s and c in p for _, sy, p, _ in SIGNALS))
    if left:
        print(f"  not scored (no signal entry): {' '.join(left)}")


def cmd_day(a):
    sta = SC.norm(a.station)
    if a.baseline:
        base, how = a.baseline.split(","), "given"
    else:
        exclude = set(SC.JAMMED) | set(SC.QUIET) | SC.read_days(a.exclude_file)
        base, how = SC.baseline_for(sta, a.day, SC.year_shares([sta]), exclude - {a.day})
    res, per = analyse(sta, a.day, base, windows=a.window or ())
    if res is None:
        sys.exit(f"{sta} {a.day}: {per}")
    res["baseline_rule"] = how
    write_outputs(res, per)
    print_summary(res)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("signals"); p.add_argument("station"); p.add_argument("day"); p.set_defaults(fn=cmd_signals)
    p = sub.add_parser("day"); p.add_argument("station"); p.add_argument("day"); p.add_argument("--baseline")
    p.add_argument("--window", action="append", help="HH:MM-HH:MM (UTC); a band signature is reported for each")
    p.add_argument("--exclude-file", help="days never used as baseline days, one ISO day per line")
    p.set_defaults(fn=cmd_day)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
