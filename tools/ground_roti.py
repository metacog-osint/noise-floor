#!/usr/bin/env python3
"""ground_roti.py: ROTI, a measured TEC fluctuation index at fixed stations, per station and UTC hour.

What it measures: ROTI, a measured TEC fluctuation index at fixed stations. It is the standard deviation, over 5
minutes, of the rate of change of slant TEC along each station-satellite path (Pi et al. 1997, GRL 24, 2283). It is a
proxy for ionospheric irregularities, not a scintillation index: it is never an S4 value and is never read against the
alert levels used for S4.

Data: the daily 30 s RINEX 3/4 observation files of open IGS stations from the BKG GNSS Data Center (anonymous HTTPS;
registry row `cors-igs`) and the IGS merged broadcast navigation file for elevations. For each GPS and Galileo
satellite above 30 deg:
  * slant TEC change from the geometry-free carrier phase (GPS L1 C/A with L2, Galileo E1 with E5a), between
    consecutive 30 s epochs, as ROT in TECU/min;
  * ROT is not formed across a gap, at an epoch whose loss-of-lock indicator is set on either carrier, or where the
    Melbourne-Wubbena combination jumps (a cycle slip);
  * ROTI is the standard deviation of ROT in fixed 5-minute windows (at least 8 of the 10 ROT values);
  * each window is placed at its pierce point at 350 km.
Per station and UTC hour the day file gives n (5-minute ROTI values, all satellites), satellites, the 95th
percentile (only from 20 values), the maximum and the pierce point of the maximum, the station's mean local solar
time, the station's position and the count of arc breaks. The method is frozen in docs/validation/ground-roti.md.

Commands
  stations                              the station table (positions, validation partners)
  day DAY... [--stations A,B] [--raw]   fetch the station-days from BKG and write data/swx/<day>.ground-roti.json
                                        (tools/ground_roti_job.py is the daily job that also uploads it)
"""
import argparse
import gzip
import json
import math
import os
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import station_cn0 as SC  # noqa: E402

OUT = os.path.join(ROOT, "data", "swx")
FEED = "ground-roti"
VERSION = "1.0"                    # frozen in docs/validation/ground-roti.md section 1
LABEL = "ROTI, a measured TEC fluctuation index at fixed stations"
NEP, STEP, LEAP = SC.NEP, SC.STEP, SC.LEAP
C = 299792458.0
MASK_DEG = 30.0                    # elevation cutoff
WINDOW = 10                        # 5-minute ROTI windows of 30 s epochs
MIN_ROT = 8                        # ROT values a window needs
MIN_P95 = 20                       # ROTI values a station-hour needs before it gets a 95th percentile
MW_SLIP = 2.0                      # Melbourne-Wubbena jump between consecutive epochs, wide-lane cycles: a cycle slip
H_IPP = 350.0                      # pierce-point shell height, km
R_E = 6371.0
DT_MIN = STEP / 60.0

# system: (f1, band-1 attributes by preference, f2, band-2 attributes by preference); RINEX 3 codes are L/C + band
# + attribute. GPS L1 C/A with L2 (L2C L or X or S, or semi-codeless P(Y) W); Galileo E1 (C, X or B) with E5a.
SIGNALS = {
    "G": (1575.42e6, ["1C"], 1227.60e6, ["2L", "2X", "2S", "2W"]),
    "E": (1575.42e6, ["1C", "1X", "1B"], 1176.45e6, ["5Q", "5X", "5I"]),
}
WANT = {s: [k + a for _, b1, _, b2 in [v] for a in b1 + b2 for k in "LC"] for s, v in SIGNALS.items()}

# The stations (IGS names). Places are the country or island; positions are the files' own APPROX POSITION, rounded
# (read 13-14 Nov 2026). `partner`: the eSWua scintillation receiver this station is paired with in the validation
# (docs/validation/ground-roti.md section 3); None for the stations where no scintillation receiver sits.
STATIONS = {
    "CPVG00CPV": ("Cape Verde", 16.732, -22.935, None),
    "ACRG00GHA": ("Ghana", 5.641, -0.207, "lag0p"),
    "NKLG00GAB": ("Gabon", 0.354, 9.672, None),
    "ASCG00SHN": ("Ascension Island", -7.916, -14.333, None),
    "DJIG00DJI": ("Djibouti", 11.526, 42.847, None),
    "SEY200SYC": ("Seychelles", -4.674, 55.479, None),
    "VOIM00MDG": ("Madagascar", -21.906, 46.793, None),
    "DGAR00GBR": ("Diego Garcia", -7.270, 72.370, None),
    "MAL200KEN": ("Malindi, Kenya", -2.996, 40.194, "mal0p"),
    "MOIU00KEN": ("Eldoret, Kenya", 0.288, 35.290, "nai0p"),
    "UNSA00ARG": ("Salta, Argentina", -24.727, -65.408, "tuc0p"),
    "CHPG00BRA": ("Cachoeira Paulista, Brazil", -22.682, -45.002, "sao0p"),
    "SABY00BES": ("Saba", 17.646, -63.221, "sab0p"),
    "GDKG00IND": ("Gadanki, India", 13.460, 79.177, "klu0p"),
    "SHLG00IND": ("Shillong, India", 25.674, 91.913, "dha0p"),
    "NCKU00TWN": ("Tainan, Taiwan", 22.997, 120.223, "ken0p"),
    "HUMG00VNM": ("Hanoi, Vietnam", 21.072, 105.773, "han0p"),
}
COLUMNS = ["station", "lat", "lon", "n", "sats", "p95", "max", "max_lat", "max_lon", "lst", "breaks"]
COLUMN_NOTES = {
    "station": "IGS station name", "lat": "station latitude, deg", "lon": "station longitude, deg",
    "n": "5-minute ROTI values in the station-hour, all GPS and Galileo satellites above 30 deg",
    "sats": "satellites that gave them",
    "p95": "95th percentile of the ROTI values, TECU/min (linear interpolation); null below 20 values",
    "max": "largest ROTI value, TECU/min",
    "max_lat": "pierce point (350 km) of the largest value, latitude, deg",
    "max_lon": "pierce point (350 km) of the largest value, longitude, deg",
    "lst": "station mean local solar time at the middle of the hour, hours",
    "breaks": "arc breaks above 30 deg in the hour (loss-of-lock indicator or a Melbourne-Wubbena jump): ROT is not "
              "formed there; many breaks can themselves mean strong scintillation or interference"}
CREDIT = ["GNSS station data: International GNSS Service (IGS) and the station operators, via the BKG GNSS Data "
          "Center (igs.bkg.bund.de)",
          "Broadcast orbits: IGS merged broadcast navigation file (BRDC00IGS), via BKG"]
CREDIT_CDDIS = "Files BKG could not deliver: the same IGS files via NASA CDDIS (cddis.nasa.gov)"

LICENCE = ("CC BY 4.0. Derived from IGS station data (IGS terms of use: open to all users, attribution required); "
           "credit the IGS and the station operators")
LOCATION = ("Each 5-minute value is placed at the pierce point of its station-satellite path through a thin shell at "
            "350 km. At 30 deg elevation the pierce points lie within about 550 km of the station. The station-hour "
            "summary is placed at the station.")
UA = SC.UA


# ---------------------------------------------------------------------------------------------- reading RINEX

class SourceError(RuntimeError):
    """The station-day could not be read (bad or truncated file)."""


def rinex_text(path):
    """A .crx.gz (Hatanaka) or .rnx.gz file -> RINEX text, and a note. Compact RINEX 3.1 files (RNX2CRX 4.2.0) are
    read as 3.0, the newest version the bundled decoder accepts; checked on MAL200KEN, 13 Nov 2026 (2,880 epochs,
    code differences within 10 m)."""
    with open(path, "rb") as f:
        raw = f.read()
    if not path.endswith(".crx.gz"):
        return gzip.decompress(raw).decode("latin-1"), None
    import hatanaka
    try:
        return hatanaka.decompress(raw).decode("latin-1"), None
    except Exception as e:                           # hatanaka.HatanakaException and gzip errors
        body = gzip.decompress(raw)
        if body[:3] == b"3.1":
            try:
                return hatanaka.decompress(b"3.0" + body[3:]).decode("latin-1"), "compact RINEX 3.1 read as 3.0"
            except Exception as e2:
                raise SourceError(f"compact RINEX 3.1 not readable: {str(e2)[:120]}")
        raise SourceError(f"not readable: {str(e)[:120]}")


def parse_obs(text, day, want=WANT):
    """RINEX 3/4 observation text -> (header, values, lli, present).

    values: {sat: {code: float64[NEP]}} for the codes in `want` ({system: codes}); lli: {sat: {code: int8[NEP]}}
    (loss-of-lock indicator digit, 0 if blank; phase codes only). Epochs off the 30 s grid and event records (flag > 1)
    are ignored. Phases are kept as float64 (a carrier phase is about 1e8 cycles)."""
    lines = text.splitlines()
    hdr, types, sysc, i = {}, {}, None, 0
    for i, line in enumerate(lines):
        label = line[60:80].strip()
        if label == "RINEX VERSION / TYPE":
            hdr["version"] = line[:9].strip()
        elif label == "SYS / # / OBS TYPES":
            if line[0] != " ":
                sysc = line[0]
                types[sysc] = []
            types[sysc] += line[7:58].split()
        elif label == "APPROX POSITION XYZ":
            hdr["xyz"] = [float(line[0:14]), float(line[14:28]), float(line[28:42])]
        elif label == "MARKER NAME":
            hdr["marker"] = line[:60].strip()
        elif label == "REC # / TYPE / VERS":
            hdr["receiver"] = line[20:40].strip()
        elif label == "ANT # / TYPE":
            hdr["antenna"] = line[20:40].strip()
        elif label == "END OF HEADER":
            break
    if not hdr.get("version", "").startswith(("3", "4")):
        raise SourceError(f"not RINEX 3/4 observation data (version {hdr.get('version')})")
    cols = {s: [(c, k) for k, c in enumerate(types.get(s, [])) if c in want.get(s, ())] for s in want}
    d0 = SC.pday(day)
    store, flags, present = {}, {}, np.zeros(NEP, bool)
    j, n = i + 1, len(lines)
    while j < n:
        line = lines[j]
        if not line.startswith(">"):
            j += 1
            continue
        flag = int(line[31]) if len(line) > 31 and line[31].isdigit() else 0
        try:
            ns = int(line[32:35])
        except ValueError:
            j += 1
            continue
        if flag > 1:
            j += 1 + ns
            continue
        sod = ((date(int(line[2:6]), int(line[7:9]), int(line[10:12])) - d0).days * 86400
               + int(line[13:15]) * 3600 + int(line[16:18]) * 60 + float(line[18:29]))
        k = sod / STEP
        ki = int(round(k))
        if abs(k - ki) < 1e-3 and 0 <= ki < NEP:
            present[ki] = True
            for sl in lines[j + 1:j + 1 + ns]:
                cs = cols.get(sl[:1])
                if not cs:
                    continue
                sat = sl[:3].replace(" ", "0")
                for code, kk in cs:
                    s = sl[3 + 16 * kk:17 + 16 * kk]
                    if not s.strip():
                        continue
                    try:
                        v = float(s)
                    except ValueError:
                        continue
                    arr = store.get((sat, code))
                    if arr is None:
                        arr = store[(sat, code)] = np.full(NEP, np.nan)
                    arr[ki] = v
                    if code[0] == "L":
                        li = sl[17 + 16 * kk:18 + 16 * kk]
                        if li.strip().isdigit() and li.strip() != "0":
                            fl = flags.get((sat, code))
                            if fl is None:
                                fl = flags[(sat, code)] = np.zeros(NEP, np.int8)
                            fl[ki] = int(li)
        j += 1 + ns
    vals, lli = {}, {}
    for (sat, code), arr in store.items():
        vals.setdefault(sat, {})[code] = arr
    for (sat, code), arr in flags.items():
        lli.setdefault(sat, {})[code] = arr
    return hdr, vals, lli, present


# ---------------------------------------------------------------------------------------------- one satellite

def stec_scale(f1, f2):
    """Metres of geometry-free carrier phase (L1 - L2, in metres) per TECU: 40.308e16 (1/f2^2 - 1/f1^2)."""
    return 40.308e16 * (1.0 / f2 ** 2 - 1.0 / f1 ** 2)


def pick(obs, band_attrs):
    """The band attribute (e.g. '2L') with the most epochs holding both its phase and its code; ties go to the
    earlier one in the preference list. None if none."""
    best, best_n = None, 0
    for a in band_attrs:
        L, P = obs.get("L" + a), obs.get("C" + a)
        if L is None or P is None:
            continue
        nn = int((np.isfinite(L) & np.isfinite(P)).sum())
        if nn > best_n:
            best, best_n = a, nn
    return best


def rot_series(obs, lli, sysc, el, mask=MASK_DEG, mw_slip=MW_SLIP):
    """One satellite-day -> (rot float64[NEP] TECU/min, NaN where not formed; breaks bool[NEP]; signals used).

    ROT at epoch k uses epochs k-1 and k: both must hold both carriers and both codes, epoch k must have no
    loss-of-lock indicator (bit 0) on either carrier and no Melbourne-Wubbena jump larger than `mw_slip` wide-lane
    cycles, and the satellite must be at least `mask` deg up at epoch k. `breaks` marks epochs above the mask where a
    consecutive pair was refused for loss of lock or a jump."""
    f1, b1, f2, b2 = SIGNALS[sysc]
    a1, a2 = pick(obs, b1), pick(obs, b2)
    rot = np.full(NEP, np.nan)
    brk = np.zeros(NEP, bool)
    if a1 is None or a2 is None:
        return rot, brk, None
    l1, p1 = obs["L" + a1] * (C / f1), obs["C" + a1]
    l2, p2 = obs["L" + a2] * (C / f2), obs["C" + a2]
    ok = np.isfinite(l1) & np.isfinite(l2) & np.isfinite(p1) & np.isfinite(p2)
    stec = (l1 - l2) / stec_scale(f1, f2)
    lam_wl = C / (f1 - f2)
    mw = ((f1 * l1 - f2 * l2) / (f1 - f2) - (f1 * p1 + f2 * p2) / (f1 + f2)) / lam_wl
    lol = np.zeros(NEP, bool)
    for a in (a1, a2):
        fl = lli.get("L" + a)
        if fl is not None:
            lol |= (fl & 1).astype(bool)
    up = np.isfinite(el) & (el >= mask)
    pair = np.zeros(NEP, bool)
    pair[1:] = ok[1:] & ok[:-1]
    jump = np.zeros(NEP, bool)
    with np.errstate(invalid="ignore"):
        jump[1:] = np.abs(mw[1:] - mw[:-1]) > mw_slip
    bad = lol | jump
    good = pair & ~bad & up
    rot[1:] = np.where(good[1:], (stec[1:] - stec[:-1]) / DT_MIN, np.nan)
    brk = pair & bad & up
    return rot, brk, f"{sysc}:L{a1}+L{a2}"


def roti_windows(rot, window=WINDOW, min_rot=MIN_ROT):
    """ROT per epoch -> (ROTI per fixed window, NaN below min_rot values; ROT count per window). Population standard
    deviation, sqrt(<ROT^2> - <ROT>^2) (Pi et al. 1997)."""
    import warnings
    r = rot.reshape(-1, window)
    cnt = np.isfinite(r).sum(1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        sd = np.nanstd(r, axis=1)
    return np.where(cnt >= min_rot, sd, np.nan), cnt


def pierce(lat, lon, az, el, h=H_IPP, r=R_E):
    """Thin-shell pierce point (deg) for a station at lat/lon (deg) looking at az/el (deg)."""
    la, lo = math.radians(lat), math.radians(lon)
    az, el = np.radians(np.asarray(az, float)), np.radians(np.asarray(el, float))
    psi = np.pi / 2 - el - np.arcsin(r / (r + h) * np.cos(el))
    plat = np.arcsin(np.sin(la) * np.cos(psi) + np.cos(la) * np.sin(psi) * np.cos(az))
    plon = lo + np.arcsin(np.clip(np.sin(psi) * np.sin(az) / np.cos(plat), -1, 1))
    return np.degrees(plat), (np.degrees(plon) + 180.0) % 360.0 - 180.0


# ---------------------------------------------------------------------------------------------- one station-day

def station_day(vals, lli, sky, lat, lon):
    """Parsed observations and sky -> (rows: list of (window, sat, roti, ipp_lat, ipp_lon), breaks per epoch (int),
    signals used {sat: 'G:L1C+L2L'})."""
    rows, nbrk, used = [], np.zeros(NEP, int), {}
    nwin = NEP // WINDOW
    for sat in sorted(vals):
        sysc = sat[0]
        if sysc not in SIGNALS or sat not in sky:
            continue
        az, el = sky[sat]
        rot, brk, sig = rot_series(vals[sat], lli.get(sat, {}), sysc, el)
        if sig is None:
            continue
        nbrk += brk
        roti, _ = roti_windows(rot)
        ws = np.flatnonzero(np.isfinite(roti))
        if not len(ws):
            continue
        used[sat] = sig
        for w in ws.tolist():
            ks = np.flatnonzero(np.isfinite(rot[w * WINDOW:(w + 1) * WINDOW])) + w * WINDOW
            km = int(ks[len(ks) // 2])
            pla, plo = pierce(lat, lon, az[km], el[km])
            rows.append((w, sat, float(roti[w]), float(pla), float(plo)))
    assert nwin * WINDOW == NEP
    return rows, nbrk, used


def hour_rows(sta, rows, nbrk, lat, lon, min_p95=MIN_P95):
    """Window rows of one station-day -> {hour: [station, lat, lon, n, sats, p95, max, max_lat, max_lon, lst, breaks]}.
    Windows are fixed 5-minute blocks of GPS time; the middle of a window is at least 2 min from a block edge, so the
    18 s GPS-UTC offset moves no window into another UTC hour: window w is in hour w // 12."""
    per = {}
    for w, sat, v, pla, plo in rows:
        per.setdefault(w // 12, []).append((v, sat, pla, plo))
    out = {}
    for h in range(24):
        b = int(nbrk[h * 120:(h + 1) * 120].sum())
        rs = per.get(h, [])
        if not rs and not b:
            continue
        lst = round((h + 0.5 + lon / 15.0) % 24.0, 2)
        if not rs:
            out[h] = [sta, lat, lon, 0, 0, None, None, None, None, lst, b]
            continue
        v = np.array([r[0] for r in rs])
        top = rs[int(np.argmax(v))]
        out[h] = [sta, lat, lon, len(v), len({r[1] for r in rs}),
                  round(float(np.percentile(v, 95)), 3) if len(v) >= min_p95 else None,
                  round(float(v.max()), 3), round(top[2], 2), round(top[3], 2), lst, b]
    return out


# ---------------------------------------------------------------------------------------------- BKG access

def bkg_dir(day, kind="obs"):
    d = SC.pday(day)
    doy = d.timetuple().tm_yday
    return f"{SC.BKG}/IGS/{'obs' if kind == 'obs' else 'BRDC'}/{d.year}/{doy:03d}/"


def bkg_listing(day, kind="obs", tries=3):
    """{file name: listed time (UTC string) or ''} of one BKG day directory; {} if the directory is not there yet
    (404). Other errors are retried, then raised, so a network failure never reads as 'not posted'."""
    import urllib.error
    url = bkg_dir(day, kind)
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                html = r.read().decode("latin-1")
            out = {}
            for m in re.finditer(r'href="([^"?/][^"]*)".*?<td align="right">(\d{4}-\d\d-\d\d \d\d:\d\d)?', html):
                out[m.group(1)] = m.group(2) or ""
            return out
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {}
            err = e
        except OSError as e:
            err = e
        time.sleep(10 * (k + 1))
    raise RuntimeError(f"BKG listing {url}: {err}")


def obs_file(listing, sta, day):
    d = SC.pday(day)
    pat = re.compile(rf"^{sta}_[RSU]_{d.year}{d.timetuple().tm_yday:03d}0000_01D_30S_MO\.crx\.gz$")
    return next((f for f in sorted(listing) if pat.match(f)), None)


def nav_file(listing, day):
    d = SC.pday(day)
    for pre in ("BRDC00IGS_R", "BRDC00WRD_S", "BRDC00WRD_R", "BRDM00DLR_S"):
        f = f"{pre}_{d.year}{d.timetuple().tm_yday:03d}0000_01D_MN.rnx.gz"
        if f in listing:
            return f
    return None


def available(day, stations):
    """({station: file name} posted at BKG, nav file name or None, {file: listed time})."""
    lst = bkg_listing(day, "obs")
    nav = nav_file(bkg_listing(day, "nav"), day)
    have = {s: f for s in stations if (f := obs_file(lst, s, day))}
    return have, nav, lst


def download(url, dest, tries=3, headers=None):
    for k in range(tries):
        try:
            return SC.download(url, dest, headers=headers)
        except Exception as e:                       # urllib, timeouts, truncated reads
            if k == tries - 1:
                raise
            print(f"  retry {url.rsplit('/', 1)[1]}: {e}", file=sys.stderr)
            time.sleep(15 * (k + 1))


def fetch(bkg_url, dest_dir, cddis_url, log=print):
    """(path, "BKG" or "CDDIS"): the file from BKG, else the same IGS file from NASA CDDIS when an Earthdata token is
    set (EARTHDATA_TOKEN; station_cn0.cddis_headers). BKG often times out from GitHub's runners while answering this PC
    in seconds: 17 Nov 2026 had 13 of 17 stations. cddis_url is a function, so CDDIS is only asked after BKG fails."""
    name = bkg_url.rsplit("/", 1)[1]
    try:
        return download(bkg_url, os.path.join(dest_dir, name)), "BKG"
    except Exception as e:
        url = cddis_url() if SC.cddis_headers() else None
        if not url:
            raise
        log(f"  {name}: BKG failed ({type(e).__name__}: {str(e)[:80]}); trying NASA CDDIS")
        return download(url, os.path.join(dest_dir, url.rsplit("/", 1)[1]), tries=2, headers=SC.cddis_headers()), "CDDIS"


def raw_dir(day):
    d = SC.pday(day)
    return os.path.join(SC.RAW, str(d.year), f"{d.timetuple().tm_yday:03d}")


# ---------------------------------------------------------------------------------------------- one day

def run_station(sta, path, eph, day):
    """One downloaded station-day -> (hour rows, station info)."""
    text, note = rinex_text(path)
    hdr, vals, lli, present = parse_obs(text, day)
    del text
    name, _, _, partner = STATIONS.get(sta, (sta, None, None, None))
    xyz = hdr.get("xyz")
    if not xyz or math.hypot(*xyz) < 6.0e6:
        raise SourceError("no usable APPROX POSITION XYZ")
    lat, lon, hgt = SC.ecef_to_geodetic(*xyz)
    sky = SC.sky(eph, xyz, day)
    rows, nbrk, used = station_day(vals, lli, sky, lat, lon)
    lat, lon = round(lat, 3), round(lon, 3)
    hours = hour_rows(sta, rows, nbrk, lat, lon)
    info = {"id": sta, "place": name, "lat": lat, "lon": lon, "height_m": round(hgt, 1),
            "receiver": hdr.get("receiver"), "antenna": hdr.get("antenna"), "file": os.path.basename(path),
            "epochs": int(present.sum()), "satellites": len(used),
            "signals": sorted({u.split(":")[0] + ":" + u.split(":")[1] for u in used.values()}),
            "windows": len(rows), "partner": partner}
    if note:
        info["note"] = note
    return hours, info


def build(day, results, missing, failed, nav, now=None, posted=None, nav_from="BKG"):
    """The day file. results: {station: (hours, info)}; missing: stations not posted; failed: {station: reason}."""
    now = now or datetime.now(timezone.utc)
    hours = []
    for h in range(24):
        rows = [results[s][0][h] for s in sorted(results) if h in results[s][0]]
        hours.append({"hour": f"{day}T{h:02d}:00Z", "stations": rows})
    problems = []
    if missing:
        problems.append(f"not posted at BKG when this file was made: {', '.join(sorted(missing))}")
    for s, why in sorted(failed.items()):
        problems.append(f"{s}: {why}")
    for s, (hrs, info) in sorted(results.items()):
        empty = [h for h in range(24) if h not in hrs or hrs[h][3] == 0]
        if len(empty) == 24:
            problems.append(f"{s}: no ROTI values")
        elif len(empty) >= 6:
            problems.append(f"{s}: no ROTI values in {len(empty)} UTC hour(s)")
        if info.get("note"):
            problems.append(f"{s}: {info['note']}")
    rows = [r for hh in hours for r in hh["stations"]]
    stations = [results[s][1] for s in sorted(results)]
    via_cddis = sorted(s["id"] for s in stations if s.get("from") == "CDDIS") + (["nav"] if nav_from == "CDDIS" else [])
    for s in stations:
        if posted and s["file"] in posted:
            s["posted"] = posted[s["file"]] + " UTC" if posted[s["file"]] else None
    return {
        "feed": FEED, "version": VERSION, "day": day,
        "as_of": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "measure": LABEL,
        "not_s4": "A proxy for ionospheric irregularities from TEC fluctuations. It is not an S4 value and is never "
                  "read against S4 alert levels.",
        "units": "TECU/min",
        "sources": ["cors-igs"], "credit": CREDIT + ([CREDIT_CDDIS] if via_cddis else []), "licence": LICENCE,
        "method": {"tool": "tools/ground_roti.py", "validation": "docs/validation/ground-roti.md",
                   "signals": "geometry-free carrier phase: GPS L1 C/A with L2 (L2C, else P(Y)); Galileo E1 with E5a",
                   "rot": "slant TEC change between consecutive 30 s epochs, TECU/min",
                   "roti": "population standard deviation of ROT in fixed 5-minute windows of GPS time, at least "
                           f"{MIN_ROT} of 10 ROT values (Pi et al. 1997)",
                   "cycle_slips": "no ROT across a gap, at a loss-of-lock indicator, or at a Melbourne-Wubbena jump "
                                  f"over {MW_SLIP:g} wide-lane cycles",
                   "elevation_min_deg": MASK_DEG, "pierce_km": H_IPP, "p95_min_values": MIN_P95,
                   "orbits": "broadcast ephemeris (healthy satellites only)", "location": LOCATION},
        "columns": COLUMNS, "column_notes": COLUMN_NOTES,
        "stations": stations,
        "missing": sorted(missing),
        "failed": dict(sorted(failed.items())),
        "hours": hours,
        "counts": {"stations": len(results), "station_hours": len(rows),
                   "with_p95": sum(1 for r in rows if r[5] is not None),
                   "values": sum(r[3] for r in rows)},
        "source": {"obs": bkg_dir(day, "obs"), "nav": (bkg_dir(day, "nav") + nav) if nav else None,
                   **({"via_cddis": via_cddis} if via_cddis else {})},
        "problems": problems,
    }


def make_day(day, stations=None, log=print):
    """Fetch what BKG has for the day, compute every station and return (doc, path). Missing stations are listed."""
    stations = list(stations or STATIONS)
    have, nav, listing = available(day, stations)
    if not nav:
        raise SourceError(f"no broadcast navigation file at BKG for {day}")
    sub = raw_dir(day)
    navp, nav_from = fetch(bkg_dir(day, "nav") + nav, sub, lambda: SC.cddis_nav_url(day), log)
    with gzip.open(navp, "rb") as f:
        eph = SC.parse_nav(f.read().decode("latin-1"))
    results, failed = {}, {}
    for sta in stations:
        if sta not in have:
            continue
        t0 = time.time()
        try:
            p, src = fetch(bkg_dir(day, "obs") + have[sta], sub, lambda: SC.cddis_obs_url(sta, day), log)
            results[sta] = run_station(sta, p, eph, day)
            info = results[sta][1]
            if src != "BKG":
                info["from"] = src
            log(f"{day} {sta}: {info['windows']} ROTI values from {info['satellites']} satellites "
                f"({time.time() - t0:.0f} s)")
        except Exception as e:                       # one bad station must not stop the day
            failed[sta] = f"{type(e).__name__}: {str(e)[:150]}"
            log(f"{day} {sta}: FAILED {failed[sta]}")
    missing = [s for s in stations if s not in have]
    doc = build(day, results, missing, failed, nav, posted=listing, nav_from=nav_from)
    return doc, write(doc)


def write(doc, out_dir=OUT):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{doc['day']}.{FEED}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"), ensure_ascii=False)
    return path


def km(lat1, lon1, lat2, lon2):
    a, b, c, d = map(math.radians, (lat1, lon1, lat2, lon2))
    x = math.sin(a) * math.sin(c) + math.cos(a) * math.cos(c) * math.cos(b - d)
    return R_E * math.acos(max(-1.0, min(1.0, x)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stations")
    d = sub.add_parser("day")
    d.add_argument("days", nargs="+")
    d.add_argument("--stations")
    a = ap.parse_args(argv)
    if a.cmd == "stations":
        import cosmic2_s4_check as G
        for s, (name, lat, lon, partner) in STATIONS.items():
            extra = ""
            if partner:
                pn, pla, plo, _ = G.STATIONS[partner]
                extra = f"  partner {partner} ({pn}) {km(lat, lon, pla, plo):.0f} km"
            print(f"{s}  {name:28s} {lat:8.3f} {lon:9.3f}{extra}")
        return 0
    for day in a.days:
        doc, path = make_day(day, a.stations.split(",") if a.stations else None)
        c = doc["counts"]
        print(f"{day}: {c['stations']} stations, {c['station_hours']} station-hours ({c['with_p95']} with p95), "
              f"{c['values']} ROTI values; missing {doc['missing']}; failed {list(doc['failed'])} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
