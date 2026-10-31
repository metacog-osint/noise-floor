#!/usr/bin/env python3
"""sentinel_gnss.py: what the Sentinel satellites' own navigation receivers heard (step E1 of docs/space-sensors-plan.md).

Sentinel-1, -2 and -3 carry GNSS receivers for precise orbit determination. The Copernicus POD Service publishes their
observations as "L1B Rinex" (AUX_GNSSRD): one TGZ per satellite and day, RINEX 3.03 with signal strength (C/N0, dB-Hz).
A ground jammer in view lowers the signal strength on every tracked link at once. SAT-JAM (K. Bostani Nezhad, DTU;
sat-jam.com) maps the same files. This tool only reduces them to a table; indicators come in step E2.

Commands
  fetch DAY...   download each unit's file for the day from the Copernicus Data Space Ecosystem (signed S3 GET), the
                 day's broadcast navigation (BKG, the cache station_cn0.py uses) and the units' element sets
                 (Space-Track) -> data/sentinel_gnss/raw/YYYY/MM/DD/*.TGZ, with raw/index.jsonl (source, fetched_at,
                 sha256) written before anything is parsed
  day DAY...     one row per link and epoch on each unit's own 10 s grid (Sentinel-2B samples at 4, 14, 24 s...;
                 Sentinel-3's 1 s files are thinned to every 10th second): unit, GNSS satellite, signal strength by
                 signal, the GNSS satellite's elevation and azimuth in the spacecraft frame, and where it was
                 -> data/sentinel_gnss/days/<day>.parquet and <day>.json (fetches what is missing unless --offline)
  latest         the newest day that every default unit has posted (catalogue only, no account)
DAY is YYYY-MM-DD (a GPS day, as in the files) or FIRST..LAST for a range.

Columns: t (seconds of the GPS day), unit, sat (G01, E02...), s1c (GPS L1 C/A or Galileo E1C), s1w, s2w, s2l (GPS),
s5q (Galileo E5a), el and az (deg), lat, lon (deg) and alt_km of the spacecraft.

Frame: the antenna is assumed to point away from the Earth's centre. Elevation is measured from the plane normal to that
direction. Azimuth is measured from the spacecraft's direction of travel toward its right-hand side (90 = right, 270 =
left). Spacecraft positions and velocities come from Space-Track element sets with SGP4 (the set nearest each epoch;
TEME rotated by Greenwich mean sidereal time, polar motion ignored; a few km of error). GNSS positions come from
broadcast ephemerides.

Units: S1C, S1D and S2C carry PODRIX receivers (GPS S1C S1W S2W S2L; Galileo S1C S5Q); S2B, S3A and S3B carry RUAG
receivers (GPS S1C S1W S2W). S1A published until 30 Jun 2026 and can be added for earlier days with --units.

Accounts (environment, or on Windows the user variables; never printed): Copernicus S3 keys CDSE_S3_ACCESS_KEY and
CDSE_S3_SECRET_KEY; Space-Track SPACETRACK_USER and SPACETRACK_PASSWORD. Space-Track: gp_history is fetched for spans
not yet held and never twice for the same span, up to two days before the query (late-published sets are not missed).

Data: Copernicus Sentinel data (free incl. commercial; "Contains modified Copernicus Sentinel data [year]"); orbital
data USSPACECOM (space-track.org); broadcast navigation IGS via BKG. Registry rows `sentinel-gnss-rinex`, `sat-jam`.
"""
import argparse
import datetime as dt
import gzip
import hashlib
import hmac
import io
import json
import os
import re
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

DATA = os.path.join(ROOT, "data", "sentinel_gnss")
RAW = os.path.join(DATA, "raw")
DAYS_DIR = os.path.join(DATA, "days")
ELEMENTS = os.path.join(DATA, "elements", "gp_history.json")

CATALOGUE = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
S3_HOST, S3_REGION = "eodata.dataspace.copernicus.eu", "default"
UA = "noisefloor/1.0 (+https://github.com/metacog-osint/noise-floor)"
VERSION = "e1-1.0"

UNITS = {   # unit: (catalogue collection, NORAD number; Space-Track satcat, checked 31 Oct 2026)
    "S1A": ("SENTINEL-1", 39634),
    "S1C": ("SENTINEL-1", 62261),
    "S1D": ("SENTINEL-1", 66315),
    "S2B": ("SENTINEL-2", 42063),
    "S2C": ("SENTINEL-2", 60989),
    "S3A": ("SENTINEL-3", 41335),
    "S3B": ("SENTINEL-3", 43437),
}
DEFAULT_UNITS = ["S1C", "S1D", "S2B", "S2C", "S3A", "S3B"]
SIGNALS = {"G": ("S1C", "S1W", "S2W", "S2L"), "E": ("S1C", "S5Q")}
COLS = ("s1c", "s1w", "s2w", "s2l", "s5q")
STEP = 10                       # s, the output grid (the Sentinel-1/2 files' own sampling)
NEP = 86400 // STEP
LEAP = 18                       # GPS - UTC, s (since 1 Jan 2017)
HISTORY_START = dt.date(2025, 3, 1)
HOLD_LAG_DAYS = 2               # gp_history is held only to two days before the query
MAX_ELSET_AGE_H = 72.0          # no spacecraft position from an element set older or newer than this
MAX_EPH_AGE_S = 7200.0          # broadcast ephemeris used up to 2 h from its time of ephemeris
OMEGA_E = 7.292115146706979e-5  # rad/s, Earth's rotation rate as used with GMST (Vallado)
MIN_COVER_S = 3600              # a product must cover at least an hour of the day
EMPTY_SHA = hashlib.sha256(b"").hexdigest()
CREDIT = ["Contains modified Copernicus Sentinel data {year}", "Orbital data: USSPACECOM (space-track.org)",
          "Broadcast navigation: IGS via BKG GNSS Data Center"]
NAME_RE = re.compile(r"^(S\d[A-Z])_OPER_AUX_GNSSRD_POD__(\d{8}T\d{6})_V(\d{8}T\d{6})_(\d{8}T\d{6})")


# ---------------------------------------------------------------------------------------------- small helpers

def days_arg(items):
    out = []
    for it in items:
        if ".." in it:
            a, b = (dt.date.fromisoformat(x) for x in it.split("..", 1))
            out += [a + dt.timedelta(days=k) for k in range((b - a).days + 1)]
        else:
            out.append(dt.date.fromisoformat(it))
    return out


def secret(name):
    """An account value from the environment or, on Windows, the user variables (set after this process started)."""
    v = os.environ.get(name)
    if not v and sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                v = winreg.QueryValueEx(k, name)[0]
        except OSError:
            v = None
    if not v:
        raise SystemExit(f"{name} is not set")
    return v


def utc(s):
    return dt.datetime.strptime(s, "%Y%m%dT%H%M%S").replace(tzinfo=dt.timezone.utc)


def gps_day_start_utc(day):
    """UTC instant of 00:00:00 GPS time on `day`."""
    return dt.datetime.combine(day, dt.time(), dt.timezone.utc) - dt.timedelta(seconds=LEAP)


# ---------------------------------------------------------------------------------------------- S3 (SigV4)

def sigv4(method, host, path, query, ak, sk, region, service="s3", amz_date=None, extra=None, payload=EMPTY_SHA):
    """AWS Signature Version 4 for a path-style request. Returns (headers to send, encoded path, encoded query)."""
    amz = amz_date or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    day = amz[:8]
    h = {"host": host, "x-amz-content-sha256": payload, "x-amz-date": amz}
    for k, v in (extra or {}).items():
        h[k.lower()] = " ".join(str(v).split())
    names = sorted(h)
    cpath = urllib.parse.quote(path, safe="/-_.~")
    cq = "&".join(f"{urllib.parse.quote(k, safe='-_.~')}={urllib.parse.quote(str(v), safe='-_.~')}"
                  for k, v in sorted((query or {}).items()))
    canon = "\n".join([method, cpath, cq, "".join(f"{n}:{h[n]}\n" for n in names), ";".join(names), payload])
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz, scope, hashlib.sha256(canon.encode()).hexdigest()])
    key = ("AWS4" + sk).encode()
    for part in (day, region, service, "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    sig = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    out = {k: v for k, v in h.items() if k != "host"}
    out["Authorization"] = (f"AWS4-HMAC-SHA256 Credential={ak}/{scope}, SignedHeaders={';'.join(names)}, "
                            f"Signature={sig}")
    return out, cpath, cq


def s3_get(path, query=None, rng=None, timeout=600, tries=3, pause=10.0):
    """Signed GET; a dropped connection is retried (signed afresh) up to `tries` times. HTTP errors are not retried."""
    import http.client
    import time
    for k in range(tries):
        hdrs, cpath, cq = sigv4("GET", S3_HOST, path, query, secret("CDSE_S3_ACCESS_KEY"),
                                secret("CDSE_S3_SECRET_KEY"), S3_REGION, extra={"Range": rng} if rng else None)
        hdrs["User-Agent"] = UA
        url = f"https://{S3_HOST}{cpath}" + (f"?{cq}" if cq else "")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=hdrs), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError:
            raise
        except (http.client.IncompleteRead, urllib.error.URLError, ConnectionError, TimeoutError) as ex:
            if k == tries - 1:
                raise
            print(f"  S3 read failed ({type(ex).__name__}); retry {k + 2} of {tries} in {pause * (k + 1):.0f} s",
                  file=sys.stderr)
            time.sleep(pause * (k + 1))


# ---------------------------------------------------------------------------------------------- catalogue

def catalogue(filt, top=200, order="ContentDate/Start asc"):
    q = urllib.parse.urlencode({"$filter": filt, "$orderby": order, "$top": str(top), "$expand": "Attributes"})
    req = urllib.request.Request(f"{CATALOGUE}?{q}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r).get("value", [])


def parse_name(name):
    m = NAME_RE.match(name or "")
    if not m:
        return None
    return {"unit": m.group(1), "created": utc(m.group(2)), "start": utc(m.group(3)), "stop": utc(m.group(4))}


def choose(rows, day, units):
    """Per unit, the product covering most of the GPS day (at least MIN_COVER_S); the newest wins a tie."""
    t0 = gps_day_start_utc(day)
    t1 = t0 + dt.timedelta(days=1)
    best = {}
    for r in rows:
        p = parse_name(r.get("Name"))
        if not p or p["unit"] not in units:
            continue
        cover = (min(p["stop"], t1) - max(p["start"], t0)).total_seconds()
        if cover < MIN_COVER_S:
            continue
        key = (round(cover / 60.0), p["created"])
        if p["unit"] not in best or key > best[p["unit"]][0]:
            best[p["unit"]] = (key, {**r, "_meta": p, "_cover_s": cover})
    return {u: v[1] for u, v in sorted(best.items())}


def day_filter(day, units):
    t0 = dt.datetime.combine(day, dt.time())
    lo, hi = (t0 - dt.timedelta(days=1)).isoformat() + ".000Z", (t0 + dt.timedelta(days=1)).isoformat() + ".000Z"
    colls = sorted({UNITS[u][0] for u in units})
    return ("(" + " or ".join(f"Collection/Name eq '{c}'" for c in colls) + ")"
            f" and contains(Name,'AUX_GNSSRD') and ContentDate/Start gt {lo} and ContentDate/Start lt {hi}")


def products_for(day, units):
    return choose(catalogue(day_filter(day, units)), day, units)


def latest(units=DEFAULT_UNITS):
    """The newest GPS day every unit has posted, and each unit's newest day."""
    newest = {}
    for u in units:
        rows = catalogue(f"startswith(Name,'{u}_OPER_AUX_GNSSRD')", top=3, order="ContentDate/Start desc")
        days = []
        for r in rows:
            p = parse_name(r["Name"])
            if p:
                d = (p["start"] + dt.timedelta(seconds=LEAP + 60)).date()
                if choose([r], d, [u]):
                    days.append(d)
        newest[u] = max(days) if days else None
    have = [d for d in newest.values() if d]
    return (min(have) if len(have) == len(units) else None), newest


# ---------------------------------------------------------------------------------------------- raw files

def raw_path(day, name):
    base = name if name.upper().endswith(".TGZ") else name + ".TGZ"
    return os.path.join(RAW, f"{day:%Y}", f"{day:%m}", f"{day:%d}", base)


def md5_of(prod):
    for c in prod.get("Checksum") or []:
        if str(c.get("Algorithm", "")).upper() == "MD5":
            return c.get("Value")
    return None


def fetch_product(day, prod, force=False):
    """Download one product (signed S3 GET), check size and MD5 when the catalogue gives them, index it, keep it."""
    dest = raw_path(day, prod["Name"])
    if os.path.exists(dest) and os.path.getsize(dest) > 0 and not force:
        return dest
    data = s3_get(prod["S3Path"])
    if prod.get("ContentLength") and len(data) != int(prod["ContentLength"]):
        raise ValueError(f"{prod['Name']}: got {len(data)} bytes, catalogue says {prod['ContentLength']}")
    md5 = md5_of(prod)
    if md5 and hashlib.md5(data).hexdigest().lower() != md5.lower():
        raise ValueError(f"{prod['Name']}: MD5 does not match the catalogue")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = f"{dest}.{os.getpid()}.part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, dest)
    rec = {"name": prod["Name"], "source": f"https://{S3_HOST}{prod['S3Path']}", "catalogue_id": prod.get("Id"),
           "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "md5_checked": bool(md5)}
    with open(os.path.join(RAW, "index.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return dest


def rinex_lines(tgz):
    """Lines of the RINEX member (.DBL) of a product TGZ, read in place (nothing is extracted to disk)."""
    with tarfile.open(tgz, "r:gz") as tf:
        for m in tf:
            if m.isfile() and m.name.upper().endswith(".DBL") and "/" not in m.name and ".." not in m.name:
                with tf.extractfile(m) as f:
                    for line in io.TextIOWrapper(f, encoding="ascii", errors="replace"):
                        yield line.rstrip("\r\n")
                return
    raise ValueError(f"{os.path.basename(tgz)}: no RINEX (.DBL) member")


def fetch_nav(day):
    import station_cn0 as SC
    url = SC.nav_name(day.isoformat())
    if url is None:
        raise SystemExit(f"no broadcast navigation file at BKG for {day}")
    dest = os.path.join(SC.RAW, str(day.year), f"{day.timetuple().tm_yday:03d}", url.rsplit("/", 1)[1])
    return SC.download(url, dest)


# ---------------------------------------------------------------------------------------------- element sets

def load_elements():
    if os.path.exists(ELEMENTS):
        with open(ELEMENTS, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_elements(store):
    os.makedirs(os.path.dirname(ELEMENTS), exist_ok=True)
    tmp = ELEMENTS + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f)
    os.replace(tmp, ELEMENTS)


def spans_needed(held, day, today):
    """Date spans [a, b] of gp_history still to fetch so `day` +-2 days is covered, never re-fetching a held span and
    holding only to HOLD_LAG_DAYS before today."""
    lo, hi = day - dt.timedelta(days=2), day + dt.timedelta(days=2)
    cap = today - dt.timedelta(days=HOLD_LAG_DAYS)
    if not held:
        a = min(HISTORY_START, lo)
        return [(a, cap)] if a < cap else []
    h0, h1 = dt.date.fromisoformat(held["from"]), dt.date.fromisoformat(held["to"])
    out = []
    if lo < h0:
        out.append((lo, h0))
    if hi > h1 and h1 < cap:
        out.append((h1, cap))
    return out


def ensure_elements(day, units, today=None):
    """Hold Space-Track element sets covering `day` for every unit; returns the store."""
    import geo_region as G
    today = today or dt.datetime.now(dt.timezone.utc).date()
    store = load_elements()
    plan = {}
    for u in units:
        n = str(UNITS[u][1])
        for a, b in spans_needed(store.get(n), day, today):
            plan.setdefault((a, b), []).append(n)
    if not plan:
        return store
    with G.SpaceTrack() as st:
        for (a, b), ids in sorted(plan.items()):
            rows = st.query(G.history_path(ids, a.isoformat(), b.isoformat()))
            for n in ids:
                got = [G.elset_row(g) for g in rows if str(g.get("NORAD_CAT_ID")) == n]
                held = store.get(n) or {"from": a.isoformat(), "to": b.isoformat(), "sets": []}
                seen = {(s["epoch"], s["elset"]) for s in held["sets"]}
                held["sets"] += [s for s in got if (s["epoch"], s["elset"]) not in seen]
                held["sets"].sort(key=lambda s: s["epoch"])
                held["from"] = min(held["from"], a.isoformat())
                held["to"] = max(held["to"], b.isoformat())
                store[n] = held
    save_elements(store)
    return store


def epoch_unix(s):
    return dt.datetime.fromisoformat(s[:26]).replace(tzinfo=dt.timezone.utc).timestamp()


# ---------------------------------------------------------------------------------------------- geometry

def gmst(jd_ut1):
    """Greenwich mean sidereal time (rad), IAU 1982, as sgp4.propagation.gstime, for arrays."""
    t = (np.asarray(jd_ut1, float) - 2451545.0) / 36525.0
    s = -6.2e-6 * t ** 3 + 0.093104 * t ** 2 + (876600.0 * 3600.0 + 8640184.812866) * t + 67310.54841
    return np.mod(np.radians(s / 240.0), 2.0 * np.pi)


def spacecraft_ecef(sets, t_unix, max_age_h=MAX_ELSET_AGE_H):
    """Earth-fixed position (m) and velocity (m/s) at UTC Unix seconds from the nearest element set; NaN where none is
    within max_age_h. Returns (xyz[N,3], vel[N,3], age_h[N])."""
    import geo_globe
    t_unix = np.asarray(t_unix, float)
    xyz = np.full((len(t_unix), 3), np.nan)
    vel = np.full((len(t_unix), 3), np.nan)
    age = np.full(len(t_unix), np.inf)
    if not sets:
        return xyz, vel, age
    ep = np.array([epoch_unix(s["epoch"]) for s in sets])
    pick = np.argmin(np.abs(t_unix[:, None] - ep[None, :]), axis=1)
    age = np.abs(t_unix - ep[pick]) / 3600.0
    whole = np.floor(t_unix / 86400.0)
    jd, fr = 2440587.5 + whole, (t_unix - whole * 86400.0) / 86400.0
    for k in np.unique(pick):
        m = (pick == k) & (age <= max_age_h)
        if not m.any():
            continue
        err, r, v = geo_globe.satrec(sets[k]).sgp4_array(jd[m], fr[m])
        ok = (err == 0)[:, None]
        r, v = np.where(ok, r, np.nan) * 1000.0, np.where(ok, v, np.nan) * 1000.0
        g = gmst(jd[m] + fr[m])
        c, s = np.cos(g), np.sin(g)
        rp = np.stack([r[:, 0] * c + r[:, 1] * s, -r[:, 0] * s + r[:, 1] * c, r[:, 2]], axis=1)
        vp = np.stack([v[:, 0] * c + v[:, 1] * s, -v[:, 0] * s + v[:, 1] * c, v[:, 2]], axis=1)
        vp += OMEGA_E * np.stack([rp[:, 1], -rp[:, 0], np.zeros(len(rp))], axis=1)    # minus omega x r
        xyz[m], vel[m] = rp, vp
    return xyz, vel, age


def geodetic(xyz):
    """Earth-fixed m -> (lat deg, lon deg, alt km) on WGS84, for arrays."""
    a, f = 6378137.0, 1 / 298.257223563
    e2 = f * (2 - f)
    x, y, z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    lon = np.arctan2(y, x)
    p = np.hypot(x, y)
    lat = np.arctan2(z, p * (1 - e2))
    for _ in range(8):                      # this form stays finite at the poles
        n = a / np.sqrt(1 - e2 * np.sin(lat) ** 2)
        lat = np.arctan2(z + e2 * n * np.sin(lat), p)
    n = a / np.sqrt(1 - e2 * np.sin(lat) ** 2)
    h = p * np.cos(lat) + z * np.sin(lat) - a * a / n
    return np.degrees(lat), np.degrees(lon), h / 1000.0


def frames(pos, vel=None):
    """Unit vectors (up, forward, right) from Earth-fixed positions and velocities (NaN allowed). Without velocities,
    the direction of travel comes from differences of consecutive positions (evenly sampled tracks only)."""
    up = pos / np.linalg.norm(pos, axis=1, keepdims=True)
    if vel is None:
        vel = np.gradient(pos, axis=0)
    fwd = vel - (vel * up).sum(1, keepdims=True) * up
    fwd = fwd / np.linalg.norm(fwd, axis=1, keepdims=True)
    return up, fwd, np.cross(fwd, up)


def look(pos, up, fwd, right, target):
    """Elevation and azimuth (deg) of target positions seen from pos in the spacecraft frame (rows aligned)."""
    los = target - pos
    los = los / np.linalg.norm(los, axis=1, keepdims=True)
    el = np.degrees(np.arcsin(np.clip((los * up).sum(1), -1.0, 1.0)))
    az = np.degrees(np.arctan2((los * right).sum(1), (los * fwd).sum(1))) % 360.0
    return el, az


def gnss_positions(eph, sats, t_abs, max_age=MAX_EPH_AGE_S):
    """Earth-fixed GNSS positions (m) for rows (sat id, GPS seconds); NaN without a healthy ephemeris near the time."""
    import station_cn0 as SC
    out = np.full((len(sats), 3), np.nan)
    sats = np.asarray(sats)
    for sat in np.unique(sats):
        recs = [r for r in eph.get(sat, []) if r["health"] == 0 and r["sqrta"] > 1000]
        if not recs:
            continue
        idx = np.nonzero(sats == sat)[0]
        t = t_abs[idx]
        toe = np.array([r["week"] * 604800.0 + r["toe"] for r in recs])
        pick = np.argmin(np.abs(t[:, None] - toe[None, :]), axis=1)
        ok = np.abs(t - toe[pick]) <= max_age
        for k in np.unique(pick[ok]):
            m = ok & (pick == k)
            out[idx[m]] = SC.sat_xyz(recs[k], t[m], gal=sat[0] == "E")
    return out


# ---------------------------------------------------------------------------------------------- RINEX

def parse_rinex(lines, day):
    """RINEX 3 observation lines -> (header, t[N] seconds of `day` (GPS), sat[N], {col: float32[N]}), one row per
    satellite and epoch that has at least one wanted signal-strength value. Epochs flagged as events are skipped."""
    it = iter(lines)
    hdr, types, sysc = {}, {}, None
    for line in it:
        label = line[60:80].strip()
        if label == "RINEX VERSION / TYPE":
            hdr["version"] = line[:9].strip()
        elif label == "SYS / # / OBS TYPES":
            if line[:1] != " ":
                sysc = line[0]
                types[sysc] = []
            types[sysc] += line[7:58].split()
        elif label == "MARKER NAME":
            hdr["marker"] = line[:60].strip()
        elif label == "REC # / TYPE / VERS":
            hdr["receiver"] = line[20:40].strip()
        elif label == "TIME OF FIRST OBS":
            hdr["time_system"] = line[48:51].strip()
        elif label == "END OF HEADER":
            break
    if not hdr.get("version", "").startswith("3"):
        raise ValueError(f"not RINEX 3 observation data (version {hdr.get('version')})")
    if hdr.get("time_system", "GPS") not in ("GPS", ""):
        raise ValueError(f"time system {hdr['time_system']} (GPS expected)")
    hdr["types"] = types
    want = {s: [(k, c.lower()) for k, c in enumerate(types[s]) if c in SIGNALS.get(s, ())] for s in types}
    t, sat, vals = [], [], {c: [] for c in COLS}
    pend = 0
    sod = None
    for line in it:
        if pend:
            pend -= 1
            if sod is None:
                continue
            w = want.get(line[:1])
            if not w:
                continue
            row, got = {}, False
            for k, col in w:
                s = line[3 + 16 * k:17 + 16 * k]
                if s.strip():
                    row[col] = float(s)
                    got = True
            if got:
                t.append(sod)
                sat.append(line[:3].replace(" ", "0"))
                for c in COLS:
                    vals[c].append(row.get(c, np.nan))
            continue
        if not line.startswith(">"):
            continue
        flag = int(line[31]) if len(line) > 31 and line[31].isdigit() else 0
        pend = int(line[32:35])
        if flag > 1:
            sod = None
            continue
        d = dt.date(int(line[2:6]), int(line[7:9]), int(line[10:12]))
        sod = ((d - day).days * 86400 + int(line[13:15]) * 3600 + int(line[16:18]) * 60 + float(line[18:29]))
    return (hdr, np.asarray(t, float), np.asarray(sat, dtype="<U3"),
            {c: np.asarray(v, np.float32) for c, v in vals.items()})


# ---------------------------------------------------------------------------------------------- day table

def grid_offset(t, step=STEP):
    """Where a unit's epochs sit within the STEP grid (s): 0 when they fall on whole multiples of STEP (or when the
    file is sampled faster, as Sentinel-3's 1 s files are), else the most common remainder (Sentinel-2B: 4 s)."""
    r = np.mod(np.round(np.asarray(t, float), 3), step)
    vals, counts = np.unique(r, return_counts=True)
    if not len(vals):
        return 0.0
    zero = counts[vals == 0.0]
    if zero.size and zero[0] >= 0.1 * counts.max():
        return 0.0
    return float(vals[np.argmax(counts)])


def unit_day(day, unit, tgz, eph, sets):
    """One unit's rows for the day (dict of arrays, one row per link on the unit's own 10 s grid) and its summary."""
    import station_cn0 as SC
    hdr, t, sat, vals = parse_rinex(rinex_lines(tgz), day)
    inday = (t >= 0) & (t < 86400)
    t, sat, vals = t[inday], sat[inday], {c: v[inday] for c, v in vals.items()}
    native = float(np.median(np.diff(np.unique(t)))) if len(t) > 1 else None
    off = grid_offset(t)
    k = (t - off) / STEP
    on = np.abs(k - np.round(k)) < 1e-6
    t, sat, vals = t[on], sat[on], {c: v[on] for c, v in vals.items()}
    t_ep, g = np.unique(t, return_inverse=True)
    day_unix = dt.datetime.combine(day, dt.time(), dt.timezone.utc).timestamp()
    pos, vel, age = spacecraft_ecef(sets, day_unix + t_ep - LEAP)
    up, fwd, right = frames(pos, vel)
    lat, lon, alt = geodetic(pos)
    gx = gnss_positions(eph, sat, SC.gps_seconds(day.isoformat()) + t)
    el, az = look(pos[g], up[g], fwd[g], right[g], gx)
    rows = {"t": np.round(t).astype(np.int32), "unit": np.full(len(t), unit), "sat": sat, **vals,
            "el": el.astype(np.float32), "az": az.astype(np.float32), "lat": lat[g].astype(np.float32),
            "lon": lon[g].astype(np.float32), "alt_km": alt[g].astype(np.float32)}
    per_epoch = np.bincount(g) if len(g) else np.array([])
    fin = np.isfinite(age) & np.isfinite(alt)
    summ = {"receiver": hdr.get("receiver"), "marker": hdr.get("marker"),
            "signals": {s: [c for c in ty if c in SIGNALS.get(s, ())] for s, ty in hdr["types"].items()},
            "native_step_s": native, "grid_offset_s": off, "epochs": int(len(t_ep)), "rows": int(len(t)),
            "median_sats_per_epoch": float(np.median(per_epoch)) if len(per_epoch) else None,
            "rows_without_geometry": int(np.isnan(el).sum()),
            "elset_max_age_h": round(float(age[fin].max()), 2) if fin.any() else None,
            "alt_km": [round(float(alt[fin].min()), 1), round(float(alt[fin].max()), 1)] if fin.any() else None}
    return rows, summ


def write_day(day, rows, summary):
    import pyarrow as pa
    import pyarrow.parquet as pq
    os.makedirs(DAYS_DIR, exist_ok=True)
    cols = {"t": pa.array(rows["t"], pa.int32()),
            "unit": pa.array(rows["unit"]).dictionary_encode(),
            "sat": pa.array(rows["sat"]).dictionary_encode()}
    for c in (*COLS, "el", "az", "lat", "lon", "alt_km"):
        cols[c] = pa.array(rows[c], pa.float32(), from_pandas=True)
    path = os.path.join(DAYS_DIR, f"{day}.parquet")
    pq.write_table(pa.table(cols), path + ".part", compression="zstd")
    os.replace(path + ".part", path)
    with open(os.path.join(DAYS_DIR, f"{day}.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1, default=str)
    return path


def fetch(day, units, force=False):
    """Download what `day` needs and isn't held (everything with force); returns ({unit: (product, tgz path)}, nav
    path). The catalogue is asked only when a unit's file is missing, so a rerun needs no network beyond Space-Track
    spans not yet held."""
    got = {} if force else held_products(day, units)
    if force or set(units) - set(got):
        for u, p in products_for(day, units).items():
            if force or u not in got:
                got[u] = (p, fetch_product(day, p, force=force))
    nav = (None if force else held_nav(day)) or fetch_nav(day)
    ensure_elements(day, units)
    return got, nav


def held_products(day, units):
    """Products already on disk for `day` (offline mode): {unit: (minimal product, path)}; newest file per unit."""
    d = os.path.dirname(raw_path(day, "x"))
    out = {}
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        p = parse_name(name)
        if p and p["unit"] in units and name.upper().endswith(".TGZ") and choose([{"Name": name}], day, [p["unit"]]):
            out[p["unit"]] = ({"Name": name[:-4]}, os.path.join(d, name))
    return out


def held_nav(day):
    """A broadcast navigation file already held for `day` (offline mode), or None."""
    import station_cn0 as SC
    d = os.path.join(SC.RAW, str(day.year), f"{day.timetuple().tm_yday:03d}")
    names = sorted(n for n in os.listdir(d) if n.startswith("BRD") and "_MN." in n) if os.path.isdir(d) else []
    return os.path.join(d, names[0]) if names else None


def build_day(day, units, offline=False, force=False):
    import station_cn0 as SC
    if offline:
        got, nav = held_products(day, units), held_nav(day)
        if nav is None:
            raise SystemExit(f"{day}: no broadcast navigation held (run fetch first)")
    else:
        got, nav = fetch(day, units, force=force)
    with gzip.open(nav, "rt", encoding="ascii", errors="replace") as f:
        eph = SC.parse_nav(f.read())
    store = load_elements()
    parts, summ = [], {"day": day.isoformat(), "version": VERSION,
                       "built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                       "nav": os.path.basename(nav), "units": {}, "missing": sorted(set(units) - set(got)),
                       "frame": "antenna to zenith; az from direction of travel toward the right",
                       "credit": [c.format(year=day.year) for c in CREDIT]}
    for u in sorted(got):
        prod, tgz = got[u]
        sets = (store.get(str(UNITS[u][1])) or {}).get("sets", [])
        rows, s = unit_day(day, u, tgz, eph, sets)
        s.update(product=prod["Name"], norad=UNITS[u][1], bytes=os.path.getsize(tgz))
        summ["units"][u] = s
        parts.append(rows)
        print(f"  {day} {u}: {s['epochs']} epochs, {s['rows']} rows, {s['receiver']}, "
              f"alt {s['alt_km']} km, elset age <= {s['elset_max_age_h']} h", file=sys.stderr)
    if not parts:
        raise SystemExit(f"{day}: no products for {', '.join(units)}")
    rows = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
    summ["rows"] = int(len(rows["t"]))
    return write_day(day, rows, summ), summ


# ---------------------------------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("fetch", "day"):
        p = sub.add_parser(name)
        p.add_argument("days", nargs="+")
        p.add_argument("--units", default=",".join(DEFAULT_UNITS))
        p.add_argument("--force", action="store_true", help="download again even if held")
        if name == "day":
            p.add_argument("--offline", action="store_true", help="use only files already held")
    sub.add_parser("latest")
    a = ap.parse_args(argv)
    if a.cmd == "latest":
        d, per = latest()
        print(json.dumps({"all_units": d, "per_unit": per}, default=str))
        return 0
    units = [u.strip().upper() for u in a.units.split(",") if u.strip()]
    bad = [u for u in units if u not in UNITS]
    if bad:
        raise SystemExit(f"unknown units: {', '.join(bad)} (known: {', '.join(UNITS)})")
    for day in days_arg(a.days):
        if a.cmd == "fetch":
            got, nav = fetch(day, units, force=a.force)
            print(json.dumps({"day": day, "units": {u: os.path.basename(p) for u, (_, p) in got.items()},
                              "missing": sorted(set(units) - set(got)), "nav": os.path.basename(nav)}, default=str))
        else:
            path, s = build_day(day, units, offline=a.offline, force=a.force)
            print(json.dumps({"day": day, "file": os.path.relpath(path, ROOT), "rows": s["rows"],
                              "units": sorted(s["units"]), "missing": s["missing"]}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
