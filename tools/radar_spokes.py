#!/usr/bin/env python3
"""radar_spokes.py: interference spokes in open C-band weather-radar data (weather-radar lane, first pass).

Why weather radars see emitters
-------------------------------
European C-band weather radars receive in 5600-5650 MHz, a band shared with 5 GHz RLAN (Wi-Fi) that must detect
radars and move away. Any device or other radar transmitting into the receiver while the antenna points at it
adds power at every range gate of that ray, because the radar maps receive time to range. The processor turns
power into reflectivity with the radar equation, Z = P + C + 20 log10(r), so an interferer of constant power P
appears as a thin radial "spoke" whose dBZ rises by 20 dB per decade of range, also in clear air. The sun does
the same at sunrise and sunset, which gives a free check of the azimuths (Huuskonen and Holleman 2007).
DWD has detected such rays operationally since 2017 from SQI and power variance, which are not in the open data
(Schaper et al. 2022). Sources and literature: docs/validation/radar-spokes.md.

Data (licence-clean, no account)
--------------------------------
- DWD single-site volumes, opendata.dwd.de/weather/radar/sites/sweep_vol_z/<site>/unfiltered/: TH
  (uncorrected, unfiltered reflectivity) of the 0.5 deg sweep (volume index 05), 250 m x 1 deg, 180 km, every
  5 min, kept about 48 h. CC BY 4.0; "Datenbasis: Deutscher Wetterdienst". Registry id dwd-radar.
- FMI volumes, AWS bucket fmi-opendata-radar-volume-hdf5 (eu-west-1, public): the lowest sweep (0.1-0.5 deg,
  500 m x 1 deg, 250 km) of each 5-min PVOL. Only that sweep is read, by HTTP range requests (about 0.5 MB of a
  15-20 MB file). TH, DBZH and FMI's own Rack quality class (incl. EMITTER.LINE) are kept. CC BY 4.0. Registry
  id fmi-radar.
Downloads go to data/radar/ (gitignored), sequentially, with a User-Agent naming the project.

Detector (per sweep; PARAMS below)
----------------------------------
1. zc = Z - 20 log10(r) over 40-250 km (inside 40 km ground clutter dominates). zc is received power plus a
   constant, so it is flat along an interfered ray.
2. Per ray: level = median zc of gates with echo; cov = share of window gates within +-3 dB of the level.
3. Contrast: the median share of neighbouring rays (2 to 8 rays away on both sides) holding that same level must
   be at least 0.25 lower; cov >= 0.30; the level must hold in 3 of 4 range segments.
4. Background-subtracted check: the ray's power minus the gate-wise median power of those neighbours must also
   hold a constant level (this suppresses precipitation texture).
5. Rays next to blanked (not scanned) sectors are dropped. Adjacent candidate rays form one spoke.
6. Flags: "sun" when within 2.5 deg of the sun's azimuth with the sun within 2 deg of the beam elevation;
   "precip" when more than 10% of the neighbour gates at the spoke's own ranges are >= 15 dBZ (static clutter,
   >= 15 dBZ in 75% of the day's sampled sweeps, excluded). Precip-flagged spokes are kept in spokes.csv but
   left out of the sources (about half of them are rain bands, visual review).
Each spoke gets: azimuth, width, level (zc, and dBZ at 100 km), approximate received power (level minus the
file's radconstH; the noise floor found this way is within 1.3 dB of FMI's stated noise level on all 12 FMI
radars), excess over the sweep's noise floor (2nd percentile of zc beyond 60 km), and the slope of Z against
log10 r (expect about 20).

Aggregation
-----------
Per radar, non-sun, non-precip spokes are clustered by azimuth (+-1.5 deg) into sources: persistent (in >= 50% of
the radar's sweeps), recurrent (10-50%), occasional (3 sweeps up to 10%). Bearings of persistent and recurrent
sources from radar pairs within 500 km are intersected (forward, both within 300 km, crossing angle >= 15 deg);
a third radar supports a crossing when one of its sources points within 1.5 deg of it. A null test rotates each
radar's bearings by a random angle (300 trials) to give the chance level of 3+ radar crossings.

Long exposure ("stack"): echo occurrence per gate over the whole day, per radar; rays whose occurrence stays at
least 5 points above the neighbours' median across the range are listed. It catches weak, dotted or part-time
spokes that no single sweep passes, but saturates where speckle or clutter gives echo in nearly every sweep.

Outputs: data/radar/out/<day>/ sweeps.csv, spokes.csv, sources.csv, fixes.csv, sun.csv, radars.csv, stack.csv,
summary.json, stack_<radar>.npz.

Usage
  python tools/radar_spokes.py fetch --day 2026-10-23 --source dwd --step-dwd 10   # DWD keeps ~48 h only
  python tools/radar_spokes.py fetch --day 2026-10-23 --source fmi --step-fmi 15
  python tools/radar_spokes.py detect --day 2026-10-23 [--sites asb,fianj]
  python tools/radar_spokes.py aggregate --day 2026-10-23
  python tools/radar_spokes.py stack --day 2026-10-23
  python tools/radar_spokes.py plot --day 2026-10-23 --maps --timeaz dwd:eis,dwd:pro,fmi:anj
"""
from __future__ import annotations

import argparse
import io
import json
import math
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "radar"
UA = "noise-floor/0.1 (open-source research; https://github.com/metacog-osint/noise-floor)"
RULE_VERSION = "radar-spokes-0.1 (2026-10-24)"

DWD_BASE = "https://opendata.dwd.de/weather/radar/sites/sweep_vol_z"
# DWD volume sweep index 05 is the 0.5 degree sweep of the 10-elevation 5-minute volume
# (index 00 = 5.5 deg ... 05 = 0.5 deg, 06..09 = 8..25 deg). The elevation is read back from each file.
DWD_LOW_INDEX = "05"
DWD_SITES = ["asb", "boo", "drs", "eis", "ess", "fbg", "fld", "hnr", "isn", "mem", "neu", "nhb", "oft", "pro",
             "ros", "tur", "umd"]
FMI_BUCKET = "https://fmi-opendata-radar-volume-hdf5.s3.amazonaws.com"


# ----------------------------------------------------------------------------------------------------------------
# HTTP helpers
# ----------------------------------------------------------------------------------------------------------------

def _session():
    import requests
    s = requests.Session()
    s.headers["User-Agent"] = UA
    return s


def _get(s, url, tries=4, **kw):
    for k in range(tries):
        try:
            r = s.get(url, timeout=60, **kw)
            if r.status_code == 404:
                return r
            r.raise_for_status()
            return r
        except Exception as e:  # network hiccup: back off and retry
            if k == tries - 1:
                raise
            print(f"  retry {k + 1} {url}: {e}", file=sys.stderr)
            time.sleep(2 ** k * 2)


class RangeFile(io.RawIOBase):
    """Read-only file object over HTTP range requests with a block cache, so h5py can read one sweep of a
    15-20 MB FMI volume file while transferring about 1 MB."""

    def __init__(self, url, session, block=1 << 16, size=None):
        self.url, self.s, self.block = url, session, block
        self.cache, self.pos, self.nreq, self.nbytes = {}, 0, 0, 0
        if size is None:
            r = session.head(url, timeout=60)
            r.raise_for_status()
            size = int(r.headers["Content-Length"])
        self.size = size

    def readable(self):
        return True

    def seekable(self):
        return True

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else (self.pos + off if whence == 1 else self.size + off)
        return self.pos

    def tell(self):
        return self.pos

    def _fetch(self, b0, b1):
        start, end = b0 * self.block, min(self.size, (b1 + 1) * self.block) - 1
        r = _get(self.s, self.url, headers={"Range": f"bytes={start}-{end}"})
        data = r.content
        if len(data) != end - start + 1:
            raise IOError(f"short range read {len(data)} != {end - start + 1}")
        self.nreq += 1
        self.nbytes += len(data)
        for i, b in enumerate(range(b0, b1 + 1)):
            self.cache[b] = data[i * self.block:(i + 1) * self.block]

    def readinto(self, buf):
        n = len(buf)
        if self.pos >= self.size or n == 0:
            return 0
        n = min(n, self.size - self.pos)
        b0, b1 = self.pos // self.block, (self.pos + n - 1) // self.block
        missing = [b for b in range(b0, b1 + 1) if b not in self.cache]
        if missing:
            run = [missing[0]]
            for b in missing[1:]:
                if b == run[-1] + 1:
                    run.append(b)
                else:
                    self._fetch(run[0], run[-1])
                    run = [b]
            self._fetch(run[0], run[-1])
        out = b"".join(self.cache[b] for b in range(b0, b1 + 1))
        off = self.pos - b0 * self.block
        buf[:n] = out[off:off + n]
        self.pos += n
        return n


# ----------------------------------------------------------------------------------------------------------------
# Fetch
# ----------------------------------------------------------------------------------------------------------------

DWD_RE = re.compile(r'href="(ras07-vol5minng01_sweeph5onem_th_' + DWD_LOW_INDEX
                    + r'-(\d{14})\d{2}-([a-z]{3})-(\d{5})-hd5)"')


def fetch_dwd(day, sites, step, hours=None):
    """Download DWD unfiltered TH, 0.5 degree sweep, every `step` minutes of `day` (UTC)."""
    s = _session()
    ymd = day.replace("-", "")
    total = 0
    for site in sites:
        url = f"{DWD_BASE}/{site}/unfiltered/"
        r = _get(s, url)
        if r.status_code != 200:
            print(f"dwd {site}: listing {r.status_code}")
            continue
        names = []
        for m in DWD_RE.finditer(r.text):
            name, ts = m.group(1), m.group(2)
            if not ts.startswith(ymd):
                continue
            hh, mm = int(ts[8:10]), int(ts[10:12])
            slot = (hh * 60 + (mm // 5) * 5)
            if slot % step:
                continue
            if hours and not (hours[0] <= hh < hours[1]):
                continue
            names.append(name)
        outdir = DATA / "dwd" / day / site
        outdir.mkdir(parents=True, exist_ok=True)
        got = 0
        for name in sorted(set(names)):
            dest = outdir / (name + ".h5")
            if dest.exists() and dest.stat().st_size > 1000:
                continue
            rr = _get(s, url + name)
            if rr.status_code != 200 or len(rr.content) < 1000:
                print(f"  dwd {site} {name}: {rr.status_code}")
                continue
            dest.write_bytes(rr.content)
            got += 1
            total += len(rr.content)
            time.sleep(0.05)
        print(f"dwd {site}: {len(names)} files listed for {day}, {got} new, total so far {total / 1e6:.0f} MB", flush=True)


def _s3_list(s, prefix):
    keys, token = [], None
    while True:
        url = f"{FMI_BUCKET}/?list-type=2&prefix={prefix}&max-keys=1000"
        if token:
            from urllib.parse import quote
            url += "&continuation-token=" + quote(token, safe="")
        r = _get(s, url)
        root = ET.fromstring(r.content)
        ns = {"s3": root.tag.split("}")[0].strip("{")}
        for c in root.findall("s3:Contents", ns):
            keys.append((c.find("s3:Key", ns).text, int(c.find("s3:Size", ns).text)))
        if root.findtext("s3:IsTruncated", namespaces=ns) == "true":
            token = root.findtext("s3:NextContinuationToken", namespaces=ns)
        else:
            return keys


def _attr(g, k, default=None):
    v = g.attrs.get(k, default)
    if isinstance(v, (bytes, np.bytes_)):
        v = v.decode()
    return v


def fmi_extract(f):
    """From an open FMI PVOL h5py.File, pull the lowest-elevation sweep: TH, DBZH and FMI's own quality class."""
    import h5py  # noqa: F401
    # dataset1 is the lowest sweep in every FMI volume checked (0.1-0.5 deg, 250 km; 36 files, 12 radars,
    # 23 Oct 2026). Scanning every dataset's attributes to confirm costs ~3x the range requests, so trust it.
    g = f["dataset1"]
    out = {}
    q = {}
    # FMI puts TH in data1 and DBZH in data2; check those first, scanning all groups only if that fails
    # (every extra group's attributes costs range requests).
    for k in ("data1", "data2"):
        if k in g:
            q[_attr(g[k]["what"], "quantity")] = k
    if "TH" not in q or "DBZH" not in q:
        for k in g:
            if k.startswith("data"):
                q[_attr(g[k]["what"], "quantity")] = k
    for qty in ("TH", "DBZH"):
        if qty not in q:
            continue
        d = g[q[qty]]
        out[qty.lower()] = d["data"][()]
        w = d["what"]
        out[qty.lower() + "_scale"] = np.array([w.attrs["gain"], w.attrs["offset"], w.attrs["nodata"], w.attrs["undetect"]],
                                               dtype="f8")
    # FMI's Rack quality classification (CLASS) on DBZH, with its EMITTER.LINE code from the legend
    out["emitter_code"] = np.array(-1)
    if "DBZH" in q:
        d = g[q["DBZH"]]
        for qk in d:
            if not qk.startswith("quality"):
                continue
            if _attr(d[qk]["what"], "quantity") == "CLASS":
                out["cls"] = d[qk]["data"][()]
                legend = _attr(d[qk]["what"], "legend", "")
                for item in legend.split(","):
                    if ":" in item and item.split(":")[1].strip() == "EMITTER.LINE":
                        out["emitter_code"] = np.array(int(item.split(":")[0]))
    wh = g["where"].attrs
    out["elangle"] = np.array(float(wh["elangle"]))
    out["rscale"] = np.array(float(wh["rscale"]))
    out["rstart"] = np.array(float(wh.get("rstart", 0.0)))
    hw = g["how"].attrs if "how" in g else {}
    if "startazA" in hw and "stopazA" in hw:
        out["startaz"] = np.asarray(hw["startazA"], dtype="f4")
        out["stopaz"] = np.asarray(hw["stopazA"], dtype="f4")
    for k in ("NEZH", "MDSH", "radconstH", "highprf", "lowprf", "pulsewidth", "rpm"):
        if k in hw:
            v = np.asarray(hw[k])
            out["how_" + k] = v if v.size == 1 else v.mean()
    wt = g["what"]
    out["start"] = np.array(_attr(wt, "startdate") + _attr(wt, "starttime"))
    out["end"] = np.array(_attr(wt, "enddate") + _attr(wt, "endtime"))
    rw = f["where"].attrs
    out["lat"], out["lon"], out["height"] = (np.array(float(rw["lat"])), np.array(float(rw["lon"])),
                                              np.array(float(rw["height"])))
    out["source"] = np.array(_attr(f["what"], "source"))
    rh = f["how"].attrs if "how" in f else {}
    out["beamwidth"] = np.array(float(rh.get("beamwH", rh.get("beamwidth", 1.0))))
    out["wavelength"] = np.array(float(rh.get("wavelength", 5.3)))
    return out


def fetch_fmi(day, sites, step, hours=None):
    """Range-read the lowest sweep of each FMI volume every `step` minutes of `day` (UTC); save as .npz."""
    import h5py
    s = _session()
    y, m, d = day.split("-")
    if not sites:
        r = _get(s, f"{FMI_BUCKET}/?list-type=2&prefix={y}/{m}/{d}/&delimiter=/")
        sites = sorted(set(re.findall(r"<Prefix>\d{4}/\d{2}/\d{2}/([a-z]+)/</Prefix>", r.text)))
    total_req = total_bytes = 0
    for site in sites:
        keys = _s3_list(s, f"{y}/{m}/{d}/{site}/")
        outdir = DATA / "fmi" / day / site
        outdir.mkdir(parents=True, exist_ok=True)
        sel = []
        for key, size in keys:
            mm = re.search(r"/(\d{12})_" + site + r"_PVOL\.h5$", key)
            if not mm:
                continue
            ts = mm.group(1)
            hh, mi = int(ts[8:10]), int(ts[10:12])
            if (hh * 60 + mi) % step:
                continue
            if hours and not (hours[0] <= hh < hours[1]):
                continue
            sel.append((key, ts, size))
        got = 0
        for key, ts, size in sel:
            dest = outdir / f"{ts}_{site}_low.npz"
            if dest.exists():
                continue
            try:
                rf = RangeFile(f"{FMI_BUCKET}/{key}", s, size=size)
                with h5py.File(rf, "r") as f:
                    out = fmi_extract(f)
                np.savez_compressed(dest, **out)
                total_req += rf.nreq
                total_bytes += rf.nbytes
                got += 1
            except Exception as e:
                print(f"  fmi {key}: {e}", file=sys.stderr)
            time.sleep(0.05)
        print(f"fmi {site}: {len(sel)} volumes selected, {got} new; transferred so far {total_bytes / 1e6:.0f} MB "
              f"in {total_req} range requests", flush=True)


# ----------------------------------------------------------------------------------------------------------------
# Readers: one sweep as a dict with z (dBZ, NaN = no echo), az (deg), r_km, metadata
# ----------------------------------------------------------------------------------------------------------------

def _decode(raw, scale):
    gain, offset, nodata, undetect = scale
    z = raw.astype("f4") * np.float32(gain) + np.float32(offset)
    z[(raw == nodata) | (raw == undetect)] = np.nan
    return z


def _az_centres(nrays, startaz=None, stopaz=None):
    if startaz is not None and stopaz is not None and len(startaz) == nrays:
        a0 = np.radians(np.asarray(startaz, "f8"))
        a1 = np.radians(np.asarray(stopaz, "f8"))
        c = np.degrees(np.arctan2(np.sin(a0) + np.sin(a1), np.cos(a0) + np.cos(a1))) % 360
        return c
    return (np.arange(nrays) + 0.5) * 360.0 / nrays


def _parse_t(s):
    return datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def read_dwd(path):
    import h5py
    with h5py.File(path, "r") as f:
        g = f["dataset1"]
        d = g["data1"]
        w = d["what"].attrs
        raw = d["data"][()]
        z = _decode(raw, (w["gain"], w["offset"], w["nodata"], w["undetect"]))
        blank = (raw == w["nodata"]).all(axis=1)
        wh = g["where"].attrs
        hw = g["how"].attrs
        az = _az_centres(raw.shape[0], hw.get("startazA"), hw.get("stopazA"))
        rscale, rstart = float(wh["rscale"]), float(wh.get("rstart", 0.0))
        node = _attr(f["what"], "source")
        nod = re.search(r"NOD:([a-z]+)", node).group(1)
        rw = f["where"].attrs
        rh = f["how"].attrs
        return dict(radar="dwd:" + nod[2:], provider="dwd", lat=float(rw["lat"]), lon=float(rw["lon"]),
                    height=float(rw["height"]), elangle=float(wh["elangle"]),
                    start=_parse_t(_attr(g["what"], "startdate") + _attr(g["what"], "starttime")),
                    end=_parse_t(_attr(g["what"], "enddate") + _attr(g["what"], "endtime")),
                    az=az, r_km=(rstart + (np.arange(raw.shape[1]) + 0.5) * rscale / 1000.0), z=z,
                    beamwidth=float(rh.get("beamwH", rh.get("beamwidth", 1.0))), fmi_emitter=None, blank=blank,
                    radconst=float(hw.get("radconstH", np.nan)), nez=np.nan)


def read_fmi(path):
    a = np.load(path, allow_pickle=False)
    z = _decode(a["th"], a["th_scale"])
    blank = (a["th"] == a["th_scale"][2]).all(axis=1)
    nrays, nbins = z.shape
    az = _az_centres(nrays, a["startaz"] if "startaz" in a else None, a["stopaz"] if "stopaz" in a else None)
    emit = None
    if "cls" in a and int(a["emitter_code"]) >= 0:
        emit = a["cls"] == int(a["emitter_code"])
    nod = re.search(r"NOD:([a-z]+)", str(a["source"])).group(1)
    return dict(radar="fmi:" + nod[2:], provider="fmi", lat=float(a["lat"]), lon=float(a["lon"]),
                height=float(a["height"]), elangle=float(a["elangle"]), start=_parse_t(str(a["start"])),
                end=_parse_t(str(a["end"])), az=az,
                r_km=float(a["rstart"]) + (np.arange(nbins) + 0.5) * float(a["rscale"]) / 1000.0, z=z,
                beamwidth=float(a["beamwidth"]), fmi_emitter=emit, blank=blank,
                radconst=float(a["how_radconstH"]) if "how_radconstH" in a else np.nan,
                nez=float(a["how_NEZH"]) if "how_NEZH" in a else np.nan)


def iter_sweep_paths(day, providers=("dwd", "fmi")):
    for prov in providers:
        base = DATA / prov / day
        if not base.exists():
            continue
        pat = "*.h5" if prov == "dwd" else "*.npz"
        for site_dir in sorted(p for p in base.iterdir() if p.is_dir()):
            for p in sorted(site_dir.glob(pat)):
                yield prov, p


def read_sweep(prov, path):
    return read_dwd(path) if prov == "dwd" else read_fmi(path)


# ----------------------------------------------------------------------------------------------------------------
# Sun position (for the sun-spike check)
# ----------------------------------------------------------------------------------------------------------------

def sun_azel(lat, lon, t):
    """Sun azimuth and apparent elevation (deg) seen from lat/lon at datetime t (UTC).
    Meeus low-precision position (tools/sun_transit.py), plus Saemundsson's optical refraction (evaluated at no
    less than -1.5 deg, where the formula stops being monotonic). Radio refraction at C band is somewhat larger;
    the sun-match tolerance (PARAMS sun_del) absorbs the difference."""
    sys.path.insert(0, str(ROOT / "tools"))
    from sun_transit import sun_ecef, _ecef_to_enu  # noqa: E402
    e, n, u = _ecef_to_enu(math.radians(lat), math.radians(lon), sun_ecef(t))
    az = math.degrees(math.atan2(e, n)) % 360
    el = math.degrees(math.asin(max(-1.0, min(1.0, u))))
    if el > -5.0:
        h = max(el, -1.5)
        el += (1.02 / math.tan(math.radians(h + 10.3 / (h + 5.11)))) / 60.0
    return az, el


# ----------------------------------------------------------------------------------------------------------------
# Spoke detector (one sweep)
# ----------------------------------------------------------------------------------------------------------------

PARAMS = dict(
    r0_km=40.0,          # skip near range (ground clutter dominates inside ~40 km at 0.3-0.5 deg)
    r1_km=250.0,         # far limit (DWD 0.5 deg sweep ends at 180 km, FMI lowest sweep at 250 km)
    tol_db=3.0,          # a gate "holds the ray's level" when its range-normalised value is within this of it
    min_det=15,          # gates with echo needed before a ray's level is defined
    cov_min=0.30,        # share of window gates holding the level
    contrast_min=0.25,   # ... minus the median share of neighbouring rays at the same level
    nb_inner=2,          # neighbours start 2 rays away (spokes may be 2-3 rays wide)
    nb_outer=8,          # ... and end 8 rays away
    n_seg=4,             # the window is split into this many range segments ...
    seg_cov=0.15,        # ... and a segment counts when this share of its gates holds the level
    seg_need=3,          # segments that must count (the level must hold across the range)
    max_width=8,         # rays; wider groups are kept but flagged "wide"
    sun_daz=2.5,         # deg; spoke within this of the sun's azimuth ...
    sun_del=2.0,         # ... with the sun within this of the beam elevation -> sun spike
    wet_dbz=15.0,        # gates at or above this count towards the sweep's precipitation share
    nb_wet_max=0.10,     # neighbour-gate wet share above which a detection is flagged "precip"
    clutter_frac=0.75,   # gates at or above wet_dbz in this share of a day's sample sweeps count as static
                         # clutter, not precipitation (24 sweeps sampled per radar)
)


def _circ_mean_deg(a, w=None):
    a = np.radians(np.asarray(a, "f8"))
    w = np.ones_like(a) if w is None else np.asarray(w, "f8")
    return float(np.degrees(np.arctan2((w * np.sin(a)).sum(), (w * np.cos(a)).sum())) % 360)


def ray_scores(z, r_km, p=PARAMS, clutter=None, blank=None):
    """Per-ray spoke scores for one sweep. z: (nrays, nbins) dBZ with NaN for no echo.

    zc = Z - 20 log10(r): received power plus a constant. Interference adds roughly constant received power, so
    on an interfered ray zc is flat along range, while precipitation and clutter vary with range."""
    win = (r_km >= p["r0_km"]) & (r_km <= p["r1_km"])
    zc = z[:, win] - 20.0 * np.log10(r_km[win])[None, :]
    det = np.isfinite(zc)
    ndet = det.sum(1)
    with np.errstate(all="ignore"):
        level = np.nanmedian(np.where(det, zc, np.nan), axis=1)
    level[ndet < p["min_det"]] = np.nan
    tol = p["tol_db"]
    with np.errstate(invalid="ignore"):
        hold = np.abs(zc - level[:, None]) <= tol            # NaN compares False
    cov = hold.mean(1)
    offs = [o for o in range(-p["nb_outer"], p["nb_outer"] + 1) if abs(o) >= p["nb_inner"]]
    nb = np.empty((len(offs), zc.shape[0]), "f4")
    for k, o in enumerate(offs):
        zb = np.roll(zc, -o, axis=0)
        with np.errstate(invalid="ignore"):
            nb[k] = (np.abs(zb - level[:, None]) <= tol).mean(1)
    nb_cov = np.median(nb, 0)
    segs = np.array_split(np.arange(zc.shape[1]), p["n_seg"])
    seg_ok = np.zeros(zc.shape[0], "i4")
    for sidx in segs:
        seg_ok += (hold[:, sidx].mean(1) >= p["seg_cov"]).astype("i4")
    raw_ok = (np.isfinite(level) & (cov >= p["cov_min"]) & (cov - nb_cov >= p["contrast_min"])
              & (seg_ok >= p["seg_need"]))
    # Background-subtracted check (matters in precipitation): subtract the gate-wise median power of the
    # neighbouring rays (no echo = 0) and require the *excess* to hold a constant level along range too.
    # Interference adds a constant power on top of whatever is there; precipitation texture does not.
    bg_cov = np.zeros(zc.shape[0], "f4")
    bg_seg = np.zeros(zc.shape[0], "i4")
    bg_level = np.full(zc.shape[0], np.nan, "f4")
    idx = np.flatnonzero(raw_ok)
    if idx.size:
        pw = np.where(det, 10.0 ** (zc / 10.0), 0.0)
        nbp = np.stack([np.roll(pw, -o, axis=0)[idx] for o in offs])        # (k, ncand, gates)
        bgp = np.median(nbp, 0)
        exc = pw[idx] - bgp
        with np.errstate(divide="ignore", invalid="ignore"):
            e_db = np.where((exc > 0) & det[idx], 10.0 * np.log10(exc), np.nan)
            lev_e = np.nanmedian(e_db, axis=1)
            hold_e = np.abs(e_db - lev_e[:, None]) <= tol
        bg_cov[idx] = hold_e.mean(1)
        bg_level[idx] = lev_e
        for sidx in segs:
            bg_seg[idx] += (hold_e[:, sidx].mean(1) >= p["seg_cov"]).astype("i4")
    cand = raw_ok & (bg_cov >= p["cov_min"]) & (bg_seg >= p["seg_need"])
    # rays next to a blanked (not scanned) sector pass the contrast test trivially: drop them
    edge = np.zeros(zc.shape[0], bool)
    if blank is not None and blank.any():
        for o in range(-3, 4):
            edge |= np.roll(blank, -o)
        cand &= ~edge
    # Precipitation next to the spoke: share of neighbour gates (same rays as above) at or above wet_dbz,
    # counted only at the ranges where the candidate ray holds its level (so ground clutter at other ranges,
    # e.g. the Alps seen from Isen, does not count). Detections above nb_wet_max are flagged "precip" and left
    # out of the sources: in rain the detector also fires on radially aligned rain bands (visual review).
    nb_wet = np.zeros(zc.shape[0], "f4")
    idx = np.flatnonzero(cand)
    if idx.size:
        zw = z[:, win]
        with np.errstate(invalid="ignore"):
            wetg = zw >= p["wet_dbz"]
        if clutter is not None:
            wetg &= ~clutter[:, win]
        nbw = np.stack([np.roll(wetg, -o, axis=0)[idx] for o in offs]).mean(axis=0)   # (ncand, gates)
        h = hold[idx]
        nb_wet[idx] = (nbw * h).sum(1) / np.maximum(h.sum(1), 1)
    return dict(level=level, cov=cov, nb_cov=nb_cov, seg_ok=seg_ok, cand=cand, win=win, zc=zc, det=det,
                bg_cov=bg_cov, bg_level=bg_level, raw_ok=raw_ok, nb_wet=nb_wet, edge=edge)


def _groups(mask):
    """Contiguous runs of True in a circular boolean array -> list of index arrays."""
    n = len(mask)
    if mask.all():
        return [np.arange(n)]
    if not mask.any():
        return []
    start = int(np.argmin(mask))           # a False position: unroll from there
    idx = (np.arange(n) + start) % n
    out, cur = [], []
    for i in idx:
        if mask[i]:
            cur.append(i)
        elif cur:
            out.append(np.array(cur))
            cur = []
    if cur:
        out.append(np.array(cur))
    return out


def detect_sweep(sw, p=PARAMS, clutter=None):
    """Return (sweep_row, list_of_spoke_rows) for one sweep dict from read_sweep()."""
    z, r = sw["z"], sw["r_km"]
    if clutter is not None and clutter.shape != z.shape:
        clutter = None
    s = ray_scores(z, r, p, clutter, sw.get("blank"))
    zc, det, win = s["zc"], s["det"], s["win"]
    rw = r[win]
    mid = sw["start"] + (sw["end"] - sw["start"]) / 2
    sun_az, sun_el = sun_azel(sw["lat"], sw["lon"], mid)
    cand = s["cand"]
    # sweep context, excluding candidate rays: noise floor (2nd percentile of zc beyond 60 km) and wet share
    keep = ~cand
    far = rw >= 60.0
    vals = zc[keep][:, far]
    vals = vals[np.isfinite(vals)]
    nf = float(np.percentile(vals, 2)) if vals.size >= 500 else float("nan")
    near150 = rw <= 150.0
    with np.errstate(invalid="ignore"):
        wetg = z[:, win] >= p["wet_dbz"]
    if clutter is not None:
        wetg &= ~clutter[:, win]
    wet = float(wetg[keep][:, near150].mean())
    echo = float(det[keep].mean())
    # FMI's own emitter flags (Rack EMITTER.LINE on DBZH): rays with 10+ flagged gates in the window
    rack = None
    if sw.get("fmi_emitter") is not None:
        rack = sw["fmi_emitter"][:, win].sum(1) >= 10
    spokes = []
    for g in _groups(cand):
        contrast = s["cov"][g] - s["nb_cov"][g]
        best = g[int(np.argmax(contrast))]
        az = _circ_mean_deg(sw["az"][g], np.clip(contrast, 1e-3, None))
        lev = float(s["level"][best])
        # slope of Z against log10 r over gates near the level, as a check of the 20 log r signature
        m = det[best] & (np.abs(zc[best] - lev) <= 2 * p["tol_db"])
        slope = float("nan")
        if m.sum() >= 10:
            slope = float(np.polyfit(np.log10(rw[m]), zc[best][m] + 20 * np.log10(rw[m]), 1)[0])
        daz = (az - sun_az + 180) % 360 - 180
        row = dict(radar=sw["radar"], provider=sw["provider"], t=mid.strftime("%Y-%m-%dT%H:%M:%SZ"),
                   elangle=round(sw["elangle"], 2), az=round(az, 2), width=int(len(g)),
                   wide=bool(len(g) > p["max_width"]),
                   level_zc=round(lev, 2), z100=round(lev + 40.0, 2),
                   pr_dbm=round(lev - sw["radconst"], 1) if np.isfinite(sw["radconst"]) else None,
                   excess_db=round(lev - nf, 2) if np.isfinite(nf) else None,
                   cov=round(float(s["cov"][best]), 3), nb_cov=round(float(s["nb_cov"][best]), 3),
                   bg_cov=round(float(s["bg_cov"][best]), 3), exc_zc=round(float(s["bg_level"][best]), 2),
                   contrast=round(float(contrast.max()), 3), seg_ok=int(s["seg_ok"][best]),
                   slope=round(slope, 1), sun_daz=round(daz, 2), sun_el=round(sun_el, 2),
                   sun=bool(abs(daz) <= p["sun_daz"] and abs(sun_el - sw["elangle"]) <= p["sun_del"]),
                   wet=round(wet, 4), nb_wet=round(float(s["nb_wet"][g].max()), 3),
                   precip=bool(s["nb_wet"][g].max() > p["nb_wet_max"]), lat=sw["lat"], lon=sw["lon"])
        if rack is not None:
            near = np.zeros(len(rack), bool)
            for k in (-1, 0, 1):
                near |= np.roll(rack, k)
            row["rack_match"] = bool(near[g].any())
        spokes.append(row)
    srow = dict(radar=sw["radar"], provider=sw["provider"], t=mid.strftime("%Y-%m-%dT%H:%M:%SZ"),
                elangle=round(sw["elangle"], 2), lat=sw["lat"], lon=sw["lon"], height=sw["height"],
                range_km=round(float(r[-1]), 1), n_spokes=len(spokes),
                n_spokes_nosun=sum(1 for x in spokes if not x["sun"]),
                n_clear=sum(1 for x in spokes if not x["sun"] and not x["precip"]), cand_rays=int(cand.sum()),
                raw_rays=int(s["raw_ok"].sum()),
                nf_zc=round(nf, 2) if np.isfinite(nf) else None, nez=sw["nez"] if np.isfinite(sw["nez"]) else None,
                radconst=sw["radconst"], wet=round(wet, 4), echo=round(echo, 4),
                sun_az=round(sun_az, 2), sun_el=round(sun_el, 2))
    if rack is not None:
        ours = np.zeros(len(rack), bool)
        for k in (-1, 0, 1):
            ours |= np.roll(cand, k)
        rk = np.zeros(len(rack), bool)
        for k in (-1, 0, 1):
            rk |= np.roll(rack, k)
        srow.update(rack_rays=int(rack.sum()), rack_rays_matched=int((rack & ours).sum()),
                    cand_rays_matched=int((cand & rk).sum()))
    return srow, spokes


def _write_csv(path, rows):
    import csv
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _read_csv(path):
    import csv
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def clutter_map(paths, p=PARAMS, n_sample=24):
    """Static-echo mask for one radar: gates at or above wet_dbz in >= clutter_frac of up to n_sample sweeps
    spread over the day. Used only so that ground clutter does not count as precipitation next to a spoke."""
    sel = paths[:: max(1, len(paths) // n_sample)]
    cnt, n = None, 0
    for prov, path in sel:
        try:
            z = read_sweep(prov, path)["z"]
        except Exception:
            continue
        w = np.nan_to_num(z, nan=-99.0) >= p["wet_dbz"]
        if cnt is None:
            cnt = w.astype("i4")
        elif w.shape == cnt.shape:
            cnt += w
        else:
            continue
        n += 1
    if n < 6:
        return None
    return cnt >= p["clutter_frac"] * n


def run_detect(day, providers=("dwd", "fmi"), sites=None):
    sweeps, spokes = [], []
    t0 = time.time()
    n = 0
    by_site = {}
    for prov, path in iter_sweep_paths(day, providers):
        if sites and path.parent.name not in sites:
            continue
        by_site.setdefault((prov, path.parent.name), []).append((prov, path))
    work = []
    for key, paths in sorted(by_site.items()):
        cm = clutter_map(paths)
        work.extend((prov, path, cm) for prov, path in paths)
    for prov, path, cm in work:
        try:
            sw = read_sweep(prov, path)
        except Exception as e:
            print(f"  skip {path.name}: {e}", file=sys.stderr)
            continue
        srow, sp = detect_sweep(sw, clutter=cm)
        srow["file"] = path.name
        sweeps.append(srow)
        spokes.extend(sp)
        n += 1
        if n % 200 == 0:
            print(f"  {n} sweeps, {len(spokes)} spokes, {time.time() - t0:.0f} s", flush=True)
    out = DATA / "out" / day
    _write_csv(out / "sweeps.csv", sweeps)
    _write_csv(out / "spokes.csv", spokes)
    print(f"detect {day}: {len(sweeps)} sweeps, {len(spokes)} spokes "
          f"({sum(1 for s in spokes if s['sun'])} sun) -> {out.relative_to(ROOT)}")


# ----------------------------------------------------------------------------------------------------------------
# Long-exposure check: echo occurrence stacked over the day
# ----------------------------------------------------------------------------------------------------------------

STACK = dict(min_excess=0.05, seg_excess=0.03, seg_need=3)


def stack_rays(occ, r_km, p=PARAMS, s=STACK):
    """occ: (nrays, nbins) share of sweeps with echo. A weak emitter that is on for part of the day, or whose
    spoke is dotted, shows as a ray whose echo occurrence stays above its neighbours' along the whole range,
    even when no single sweep passes the per-sweep test. Returns per-ray excess (median over the window of the
    ray's occurrence minus the neighbours' median), segments passing, and the candidate mask."""
    win = (r_km >= p["r0_km"]) & (r_km <= p["r1_km"])
    o = occ[:, win]
    offs = [k for k in range(-p["nb_outer"], p["nb_outer"] + 1) if abs(k) >= p["nb_inner"]]
    nb = np.median(np.stack([np.roll(o, -k, axis=0) for k in offs]), 0)
    exc = o - nb
    ray_exc = np.median(exc, 1)
    seg_ok = np.zeros(o.shape[0], "i4")
    for sidx in np.array_split(np.arange(o.shape[1]), p["n_seg"]):
        seg_ok += (np.median(exc[:, sidx], 1) >= s["seg_excess"]).astype("i4")
    cand = (ray_exc >= s["min_excess"]) & (seg_ok >= s["seg_need"])
    # rays that never had echo in the window are a blanked sector: drop candidates within 3 rays of one
    blank = o.max(1) == 0
    if blank.any():
        edge = np.zeros_like(blank)
        for k in range(-3, 4):
            edge |= np.roll(blank, -k)
        cand &= ~edge
    return ray_exc, seg_ok, cand


def run_stack(day, providers=("dwd", "fmi")):
    """Stack echo occurrence per radar over the day and list long-exposure spokes; compare with the sources."""
    out = DATA / "out" / day
    by_site = {}
    for prov, path in iter_sweep_paths(day, providers):
        by_site.setdefault((prov, path.parent.name), []).append((prov, path))
    sources = _read_csv(out / "sources.csv") if (out / "sources.csv").exists() else []
    rows = []
    for (prov, site), paths in sorted(by_site.items()):
        cnt, n, meta = None, 0, None
        for prov_, path in paths:
            try:
                sw = read_sweep(prov_, path)
            except Exception:
                continue
            d = np.isfinite(sw["z"])
            if cnt is None:
                cnt, meta = d.astype("i4"), sw
            elif d.shape == cnt.shape:
                cnt += d
            else:
                continue
            n += 1
        if not n:
            continue
        occ = cnt / n
        np.savez_compressed(out / f"stack_{meta['radar'].replace(':', '_')}.npz", occ=occ.astype("f4"),
                            az=meta["az"], r_km=meta["r_km"], n=n)
        ray_exc, seg_ok, cand = stack_rays(occ, meta["r_km"])
        srcs = [x for x in sources if x["radar"] == meta["radar"]]
        for g in _groups(cand):
            best = g[int(np.argmax(ray_exc[g]))]
            az = _circ_mean_deg(meta["az"][g], np.clip(ray_exc[g], 1e-3, None))
            near = [x for x in srcs if abs((_f(x["az"]) - az + 180) % 360 - 180) <= 1.5]
            rows.append(dict(radar=meta["radar"], az=round(az, 1), width=len(g), sweeps=n,
                             occ_excess=round(float(ray_exc[best]), 3), seg_ok=int(seg_ok[best]),
                             source=(f"{near[0]['az']} ({near[0]['persist_class']})" if near else "")))
        print(f"stack {meta['radar']}: {n} sweeps, {int(cand.sum())} rays, "
              f"{sum(1 for r in rows if r['radar'] == meta['radar'])} spokes", flush=True)
    _write_csv(out / "stack.csv", rows)
    print(f"stack {day}: {len(rows)} long-exposure spokes, {sum(1 for r in rows if r['source'])} match a "
          f"per-sweep source -> {(out / 'stack.csv').relative_to(ROOT)}")


# ----------------------------------------------------------------------------------------------------------------
# Aggregation: sources per radar, sun check, bearing intersections
# ----------------------------------------------------------------------------------------------------------------

AGG = dict(
    src_tol=1.5,         # deg; spokes within this of a source azimuth belong to it
    src_min=3,           # sweeps needed for a source
    persistent=0.5,      # share of the radar's sweeps: persistent at or above this ...
    recurrent=0.1,       # ... recurrent at or above this, occasional below
    weak_db=6.0,         # excess over the sweep's noise floor: weak below, moderate below strong_db
    strong_db=15.0,
    pair_max_km=500.0,   # radar pairs further apart are not intersected
    fix_max_km=300.0,    # intersections further than this from either radar are dropped
    min_cross=15.0,      # deg; minimum crossing angle
    bearing_sd=0.5,      # deg; bearing uncertainty used for the error estimate (from the sun check)
    slot_min=15,         # minutes; time slot for co-occurrence
    fix_classes=("persistent", "recurrent"),   # sources used for crossings
    support_tol=1.5,     # deg; a third radar supports a crossing when one of its sources points within this
    null_trials=300,     # random-rotation trials for the chance level of 3+ radar crossings
)

R_EARTH = 6371.0


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def gc_dest(lat, lon, brg, d_km):
    la, lo, b, d = math.radians(lat), math.radians(lon), math.radians(brg), d_km / R_EARTH
    la2 = math.asin(math.sin(la) * math.cos(d) + math.cos(la) * math.sin(d) * math.cos(b))
    lo2 = lo + math.atan2(math.sin(b) * math.sin(d) * math.cos(la), math.cos(d) - math.sin(la) * math.sin(la2))
    return math.degrees(la2), (math.degrees(lo2) + 540) % 360 - 180


def gc_dist_brg(lat1, lon1, lat2, lon2):
    la1, la2 = math.radians(lat1), math.radians(lat2)
    dlo = math.radians(lon2 - lon1)
    a = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    d = 2 * R_EARTH * math.asin(min(1.0, math.sqrt(a)))
    b = math.degrees(math.atan2(math.sin(dlo) * math.cos(la2),
                                math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dlo))) % 360
    return d, b


def _vec(lat, lon):
    la, lo = math.radians(lat), math.radians(lon)
    return np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)])


def bearing_intersection(lat1, lon1, b1, lat2, lon2, b2):
    """Forward intersection of two great-circle bearings. Returns (lat, lon, d1_km, d2_km, cross_deg) or None."""
    p1, p2 = _vec(lat1, lon1), _vec(lat2, lon2)
    # a point a small distance along each bearing defines each great circle
    q1, q2 = _vec(*gc_dest(lat1, lon1, b1, 10.0)), _vec(*gc_dest(lat2, lon2, b2, 10.0))
    n1, n2 = np.cross(p1, q1), np.cross(p2, q2)
    x = np.cross(n1, n2)
    if np.linalg.norm(x) < 1e-12:
        return None
    x /= np.linalg.norm(x)
    best = None
    for c in (x, -x):
        lat = math.degrees(math.asin(max(-1, min(1, c[2]))))
        lon = math.degrees(math.atan2(c[1], c[0]))
        d1, bb1 = gc_dist_brg(lat1, lon1, lat, lon)
        d2, bb2 = gc_dist_brg(lat2, lon2, lat, lon)
        if abs((bb1 - b1 + 180) % 360 - 180) < 1.0 and abs((bb2 - b2 + 180) % 360 - 180) < 1.0:
            best = (lat, lon, d1, d2)
    if best is None:
        return None
    lat, lon, d1, d2 = best
    # crossing angle: difference of the back-bearings from the fix to the two radars
    _, back1 = gc_dist_brg(lat, lon, lat1, lon1)
    _, back2 = gc_dist_brg(lat, lon, lat2, lon2)
    cross = abs((back1 - back2 + 180) % 360 - 180)
    cross = min(cross, 180 - cross)
    return lat, lon, d1, d2, cross


def _slot(t, minutes):
    dt = datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ")
    return (dt.hour * 60 + dt.minute) // minutes


def find_sources(spokes, n_sweeps, a=AGG):
    """Greedy azimuth clustering of one radar's non-sun spokes. spokes: list of dicts with az, t, ..."""
    left = list(spokes)
    out = []
    while left:
        az = np.array([_f(s["az"]) for s in left])
        bins = np.zeros(360)
        for x in az:
            for k in (-1, 0, 1):
                bins[(int(round(x)) + k) % 360] += 1
        b = int(np.argmax(bins))
        near = [s for s in left if abs((_f(s["az"]) - b + 180) % 360 - 180) <= a["src_tol"] + 0.5]
        if len(set(s["t"] for s in near)) < a["src_min"]:
            break
        c = _circ_mean_deg([_f(s["az"]) for s in near])
        mem = [s for s in left if abs((_f(s["az"]) - c + 180) % 360 - 180) <= a["src_tol"]]
        if not mem:
            break
        c = _circ_mean_deg([_f(s["az"]) for s in mem])
        ids = set(id(s) for s in mem)
        left = [s for s in left if id(s) not in ids]
        ts = sorted(set(s["t"] for s in mem))
        if len(ts) < a["src_min"]:
            continue
        exc = np.array([_f(s["excess_db"]) for s in mem])
        pers = len(ts) / max(1, n_sweeps)
        med_exc = float(np.nanmedian(exc)) if np.isfinite(exc).any() else float("nan")
        row = dict(az=round(c, 1), az_sd=round(float(np.std([((_f(s["az"]) - c + 180) % 360 - 180) for s in mem])), 2),
                   n_det=len(ts), persistence=round(pers, 3),
                   first=ts[0], last=ts[-1], hours=len(set(t[11:13] for t in ts)),
                   z100=round(float(np.nanmedian([_f(s["z100"]) for s in mem])), 1),
                   pr_dbm=round(float(np.nanmedian([_f(s["pr_dbm"]) for s in mem])), 1),
                   excess_db=round(med_exc, 1), excess_max=round(float(np.nanmax(exc)), 1) if np.isfinite(exc).any() else None,
                   width=float(np.median([int(s["width"]) for s in mem])),
                   slope=round(float(np.nanmedian([_f(s["slope"]) for s in mem])), 1),
                   wet_share=round(float(np.mean([_f(s["wet"]) >= 0.1 for s in mem])), 2),
                   times=ts)
        if "rack_match" in mem[0] and mem[0].get("rack_match") not in (None, ""):
            row["rack_share"] = round(float(np.mean([s["rack_match"] == "True" for s in mem])), 2)
        row["persist_class"] = ("persistent" if pers >= a["persistent"] else
                                "recurrent" if pers >= a["recurrent"] else "occasional")
        row["strength"] = ("weak" if med_exc < a["weak_db"] else "moderate" if med_exc < a["strong_db"] else "strong")
        likely = []
        if row["persist_class"] != "occasional" and row["width"] <= 3 and row["strength"] != "strong":
            likely.append("RLAN-like (steady, narrow, low power)")
        if row["strength"] == "strong" or row["width"] > 3:
            likely.append("strong or wide: review")
        if row["persist_class"] == "occasional":
            likely.append("short-lived")
        row["note"] = "; ".join(likely)
        out.append(row)
    return out


def _places():
    p = ROOT / "data" / "natural_earth" / "ne_50m_populated_places_simple.geojson"
    if not p.exists():
        return []
    gj = json.loads(p.read_text(encoding="utf-8"))
    out = []
    for f in gj["features"]:
        pr = f["properties"]
        lon, lat = f["geometry"]["coordinates"][:2]
        out.append((lat, lon, pr.get("name"), pr.get("adm0name") or pr.get("sov0name"), pr.get("pop_max") or 0))
    return out


def _nearest_place(lat, lon, places, max_km=60):
    best = None
    for la, lo, name, ctry, pop in places:
        if abs(la - lat) > 1.5 or abs(lo - lon) > 3:
            continue
        d, _ = gc_dist_brg(lat, lon, la, lo)
        if d <= max_km and (best is None or d < best[0]):
            best = (d, name, ctry)
    return best


def intersect_sources(radars, srcs_by, a=AGG, places=None, rot=None):
    """Forward crossings of source bearings for every radar pair within pair_max_km, with third-radar support.
    rot: optional {radar: degrees} added to every source azimuth of that radar (null test)."""
    rot = rot or {}

    def az_of(rid, src):
        return (src["az"] + rot.get(rid, 0.0)) % 360

    fixes = []
    rlist = sorted(radars)
    sd = math.radians(a["bearing_sd"])
    for i, ra in enumerate(rlist):
        for rb in rlist[i + 1:]:
            A, B = radars[ra], radars[rb]
            dab, _ = gc_dist_brg(A["lat"], A["lon"], B["lat"], B["lon"])
            if dab > a["pair_max_km"]:
                continue
            common = A["slots"] & B["slots"]
            for sa in srcs_by.get(ra, []):
                for sb in srcs_by.get(rb, []):
                    x = bearing_intersection(A["lat"], A["lon"], az_of(ra, sa), B["lat"], B["lon"], az_of(rb, sb))
                    if not x:
                        continue
                    lat, lon, d1, d2, cross = x
                    if d1 > a["fix_max_km"] or d2 > a["fix_max_km"] or cross < a["min_cross"]:
                        continue
                    err = math.hypot(d1 * sd, d2 * sd) / math.sin(math.radians(cross))
                    support, silent = [], []
                    for rc in rlist:
                        if rc in (ra, rb):
                            continue
                        C = radars[rc]
                        dc, bc = gc_dist_brg(C["lat"], C["lon"], lat, lon)
                        if dc > a["fix_max_km"]:
                            continue
                        tol = a["support_tol"]
                        hit = [s for s in srcs_by.get(rc, []) if abs((az_of(rc, s) - bc + 180) % 360 - 180) <= tol]
                        if hit:
                            support.append(f"{rc}@{hit[0]['az']}")
                        elif dc <= C["range_km"]:
                            silent.append(rc)
                    row = dict(radar_a=ra, az_a=sa["az"], class_a=sa["persist_class"], radar_b=rb, az_b=sb["az"],
                               class_b=sb["persist_class"], lat=round(lat, 3), lon=round(lon, 3),
                               d_a_km=round(d1), d_b_km=round(d2), cross_deg=round(cross, 1), err_km=round(err, 1),
                               n_radars=2 + len(support), support=" ".join(support),
                               silent_in_range=" ".join(silent))
                    if places is not None:
                        ta = set(_slot(t, a["slot_min"]) for t in sa["times"]) & common
                        tb = set(_slot(t, a["slot_min"]) for t in sb["times"]) & common
                        union = len(ta | tb)
                        row.update(co_slots=len(ta & tb), co_share=round(len(ta & tb) / union, 2) if union else 0.0)
                        pl = _nearest_place(lat, lon, places)
                        row["near_place"] = f"{pl[1]} ({pl[2]}, {pl[0]:.0f} km)" if pl else ""
                    fixes.append(row)
    fixes.sort(key=lambda f: (-f["n_radars"], -f.get("co_share", 0), f["err_km"]))
    return fixes


def run_aggregate(day, a=AGG):
    out = DATA / "out" / day
    sweeps = _read_csv(out / "sweeps.csv")
    spokes = _read_csv(out / "spokes.csv")
    radars = {}
    for s in sweeps:
        r = radars.setdefault(s["radar"], dict(radar=s["radar"], provider=s["provider"], lat=_f(s["lat"]),
                                                 lon=_f(s["lon"]), height=_f(s["height"]),
                                                 range_km=_f(s["range_km"]), elangle=_f(s["elangle"]),
                                                 sweeps=0, wet_sweeps=0, slots=set(), spokes=0, sun_spokes=0,
                                                 precip_spokes=0))
        r["sweeps"] += 1
        r["wet_sweeps"] += _f(s["wet"]) >= 0.1
        r["slots"].add(_slot(s["t"], a["slot_min"]))
    by_radar = {}
    for s in spokes:
        radars[s["radar"]]["spokes"] += 1
        if s["sun"] == "True":
            radars[s["radar"]]["sun_spokes"] += 1
        elif s.get("precip") == "True":
            radars[s["radar"]]["precip_spokes"] += 1
        else:
            by_radar.setdefault(s["radar"], []).append(s)
    # --- sun check: sweeps with the sun inside the main beam, and whether a sun spike was found
    sun_rows = []
    sun_spokes = {(s["radar"], s["t"]): s for s in spokes if s["sun"] == "True"}
    for s in sweeps:
        dele = _f(s["sun_el"]) - _f(s["elangle"])
        if abs(dele) <= 0.6 and _f(s["sun_el"]) > -1.0:
            hit = sun_spokes.get((s["radar"], s["t"]))
            sun_rows.append(dict(radar=s["radar"], t=s["t"], sun_az=s["sun_az"], sun_el=s["sun_el"],
                                 elangle=s["elangle"], wet=s["wet"], found=bool(hit),
                                 daz=hit["sun_daz"] if hit else "", excess_db=hit["excess_db"] if hit else ""))
    # --- sources
    sources = []
    for rid, sp in sorted(by_radar.items()):
        for src in find_sources(sp, radars[rid]["sweeps"], a):
            src = dict(radar=rid, **src)
            sources.append(src)
    places = _places()
    # --- intersections between radar pairs (persistent and recurrent sources only)
    srcs_by = {}
    for s in sources:
        if s["persist_class"] in a["fix_classes"]:
            srcs_by.setdefault(s["radar"], []).append(s)
    fixes = intersect_sources(radars, srcs_by, a, places)
    # null test: rotate every radar's source azimuths by a random angle and count 3+ radar crossings again
    rng = np.random.default_rng(1)
    null3 = []
    for _ in range(a["null_trials"]):
        rot = {rid: float(rng.uniform(0, 360)) for rid in radars}
        null3.append(sum(1 for f in intersect_sources(radars, srcs_by, a, None, rot) if f["n_radars"] >= 3))
    # --- write
    for s in sources:
        s["times"] = len(s["times"])   # keep the CSV small: count only
    _write_csv(out / "sources.csv", sources)
    _write_csv(out / "fixes.csv", fixes)
    _write_csv(out / "sun.csv", sun_rows)
    radar_rows = []
    for rid, r in sorted(radars.items()):
        rs_ = [s for s in sources if s["radar"] == rid]
        rr = {k: v for k, v in r.items() if k != "slots"}
        clear = r["spokes"] - r["sun_spokes"] - r["precip_spokes"]
        rr.update(clear_spokes_per_sweep=round(clear / max(1, r["sweeps"]), 2),
                  sources=len(rs_),
                  persistent=sum(1 for s in rs_ if s["persist_class"] == "persistent"),
                  recurrent=sum(1 for s in rs_ if s["persist_class"] == "recurrent"),
                  occasional=sum(1 for s in rs_ if s["persist_class"] == "occasional"),
                  isolated_spokes=clear - sum(s["times"] for s in rs_))
        radar_rows.append(rr)
    _write_csv(out / "radars.csv", radar_rows)
    found = [x for x in sun_rows if x["found"]]
    daz = np.array([_f(x["daz"]) for x in found])
    summary = dict(day=day, sweeps=len(sweeps), spokes=len(spokes), sun_spokes=sum(1 for s in spokes if s["sun"] == "True"),
                   precip_spokes=sum(1 for s in spokes if s["sun"] != "True" and s.get("precip") == "True"),
                   radars=len(radars), sources=len(sources),
                   sources_by_class={c: sum(1 for s in sources if s["persist_class"] == c)
                                     for c in ("persistent", "recurrent", "occasional")},
                   sources_by_strength={c: sum(1 for s in sources if s["strength"] == c)
                                        for c in ("weak", "moderate", "strong")},
                   sun_in_beam_sweeps=len(sun_rows), sun_found=len(found),
                   sun_daz_mean=round(float(daz.mean()), 2) if daz.size else None,
                   sun_daz_sd=round(float(daz.std()), 2) if daz.size else None,
                   fixes=len(fixes), fixes_3plus=sum(1 for f in fixes if f["n_radars"] >= 3),
                   fixes_3plus_null_mean=round(float(np.mean(null3)), 1) if null3 else None,
                   fixes_3plus_null_p95=float(np.percentile(null3, 95)) if null3 else None,
                   fixes_3plus_null_p_value=(round(float(np.mean([n >= sum(1 for f in fixes if f["n_radars"] >= 3)
                                                                 for n in null3])), 3) if null3 else None),
                   # FMI only: rays flagged by FMI's own Rack EMITTER.LINE detector vs this detector (+-1 ray)
                   rack=dict(rack_rays=sum(int(s.get("rack_rays") or 0) for s in sweeps),
                             rack_rays_matched=sum(int(s.get("rack_rays_matched") or 0) for s in sweeps),
                             cand_rays_fmi=sum(int(s["cand_rays"]) for s in sweeps if s["provider"] == "fmi"),
                             cand_rays_matched=sum(int(s.get("cand_rays_matched") or 0) for s in sweeps)),
                   rule_version=RULE_VERSION, params=PARAMS, agg=a, stack=STACK)
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("params", "agg")}, indent=1))


# ----------------------------------------------------------------------------------------------------------------
# Figures (small PNGs for docs/validation/img/)
# ----------------------------------------------------------------------------------------------------------------

def _land(bbox):
    """Natural Earth land and borders clipped to bbox (lon0, lat0, lon1, lat1), as lists of (x, y) arrays."""
    from shapely.geometry import box, shape
    clip = box(*bbox)
    polys, lines = [], []
    p = ROOT / "data" / "natural_earth" / "ne_10m_land.geojson"
    if p.exists():
        for f in json.loads(p.read_text(encoding="utf-8"))["features"]:
            g = shape(f["geometry"]).intersection(clip)
            for part in getattr(g, "geoms", [g]):
                if part.geom_type == "Polygon" and not part.is_empty:
                    polys.append(np.asarray(part.exterior.coords))
    p = ROOT / "data" / "natural_earth" / "ne_50m_admin_0_boundary_lines_land.geojson"
    if p.exists():
        for f in json.loads(p.read_text(encoding="utf-8"))["features"]:
            g = shape(f["geometry"]).intersection(clip)
            for part in getattr(g, "geoms", [g]):
                if part.geom_type == "LineString" and not part.is_empty:
                    lines.append(np.asarray(part.coords))
    return polys, lines


def fig_map(day, provider, bbox, path, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    out = DATA / "out" / day
    radars = [r for r in _read_csv(out / "radars.csv") if r["provider"] == provider]
    sources = [s for s in _read_csv(out / "sources.csv") if s["radar"].startswith(provider + ":")]
    fixes = [f for f in _read_csv(out / "fixes.csv") if f["radar_a"].startswith(provider + ":")]
    polys, lines = _land(bbox)
    lat0 = (bbox[1] + bbox[3]) / 2
    fig, ax = plt.subplots(figsize=(6.4, 6.4 * (bbox[3] - bbox[1]) / ((bbox[2] - bbox[0]) * math.cos(math.radians(lat0)))))
    for pl in polys:
        ax.fill(pl[:, 0], pl[:, 1], color="#ececec", lw=0)
        ax.plot(pl[:, 0], pl[:, 1], color="#9a9a9a", lw=0.4)
    for ln in lines:
        ax.plot(ln[:, 0], ln[:, 1], color="#7a7a7a", lw=0.6, ls="--")
    colors = {"persistent": "#c0392b", "recurrent": "#e08e0b", "occasional": "#7f8c8d"}
    for s in sources:
        if s["persist_class"] == "occasional":
            continue
        r = next(x for x in radars if x["radar"] == s["radar"])
        la, lo = _f(r["lat"]), _f(r["lon"])
        pts = [gc_dest(la, lo, _f(s["az"]), d) for d in np.linspace(0, _f(r["range_km"]), 30)]
        ax.plot([p[1] for p in pts], [p[0] for p in pts], color=colors[s["persist_class"]],
                lw=1.4 if s["persist_class"] == "persistent" else 0.8, alpha=0.9)
    for r in radars:
        la, lo = _f(r["lat"]), _f(r["lon"])
        ring = [gc_dest(la, lo, b, _f(r["range_km"])) for b in range(0, 361, 5)]
        ax.plot([p[1] for p in ring], [p[0] for p in ring], color="#4a6fa5", lw=0.3, alpha=0.6)
        ax.plot(lo, la, "o", color="#1f3b73", ms=4)
        ax.text(lo + 0.05, la + 0.05, r["radar"].split(":")[1].upper(), fontsize=6.5, color="#1f3b73")
    shown = [f for f in fixes if int(f["n_radars"]) >= 3]
    for f in shown:
        ax.plot(_f(f["lon"]), _f(f["lat"]), "x", color="k", ms=6, mew=1.2)
    ax.plot([], [], color=colors["persistent"], lw=1.4, label="persistent spoke (≥50% of sweeps)")
    ax.plot([], [], color=colors["recurrent"], lw=0.8, label="recurrent spoke (10-50%)")
    if shown:
        ax.plot([], [], "x", color="k", label="bearing crossing seen by 3+ radars")
    ax.legend(fontsize=6.5, loc="lower left", framealpha=0.9)
    ax.set_xlim(bbox[0], bbox[2])
    ax.set_ylim(bbox[1], bbox[3])
    ax.set_aspect(1 / math.cos(math.radians(lat0)))
    ax.set_title(title, fontsize=8.5)
    ax.tick_params(labelsize=6.5)
    attrib = ("Data: Deutscher Wetterdienst (CC BY 4.0)" if provider == "dwd" else
              "Data: Finnish Meteorological Institute (CC BY 4.0)") + "; land: Natural Earth"
    ax.text(0.99, 0.005, attrib, transform=ax.transAxes, fontsize=5.5, ha="right", va="bottom", color="#555")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def fig_timeaz(day, radar_ids, path):
    """Azimuth against time for each radar: every detection, sun spikes and precip-flagged ones marked."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    out = DATA / "out" / day
    spokes = _read_csv(out / "spokes.csv")
    ncol = min(3, len(radar_ids))
    nrow = (len(radar_ids) + ncol - 1) // ncol
    fig, axes = plt.subplots(nrow, ncol, figsize=(3.3 * ncol, 3.1 * nrow), squeeze=False, sharey=True)
    for ax in axes.flat[len(radar_ids):]:
        ax.axis("off")
    for ax, rid in zip(axes.flat, radar_ids):
        sp = [s for s in spokes if s["radar"] == rid]
        def hh(s):
            return int(s["t"][11:13]) + int(s["t"][14:16]) / 60
        for sel, c, m, lab in (([s for s in sp if s["sun"] != "True" and s["precip"] != "True"], "#1f3b73", ".", "spoke"),
                               ([s for s in sp if s["sun"] != "True" and s["precip"] == "True"], "#bbbbbb", ".", "precip-flagged"),
                               ([s for s in sp if s["sun"] == "True"], "#e08e0b", "*", "sun")):
            ax.scatter([_f(s["az"]) for s in sel], [hh(s) for s in sel], s=6 if m == "." else 30, c=c, marker=m, label=lab, lw=0)
        ax.set_xlim(0, 360)
        ax.set_ylim(0, 24)
        ax.set_xticks(range(0, 361, 90))
        ax.set_title(rid, fontsize=8)
        if ax in axes[-1]:
            ax.set_xlabel("azimuth (deg)", fontsize=7)
        ax.tick_params(labelsize=6.5)
        ax.grid(lw=0.3, alpha=0.5)
    for row in axes:
        row[0].set_ylabel(f"hour UTC, {day}", fontsize=7)
    axes[0][0].legend(fontsize=6, loc="upper left", markerscale=1.5)
    fig.text(0.995, 0.003, "Data: Deutscher Wetterdienst; Finnish Meteorological Institute (both CC BY 4.0)",
             fontsize=5.5, ha="right", va="bottom", color="#555")
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


def fig_ppi(prov, sweep_path, path, rmax=None):
    """One sweep (TH) with detected spokes marked."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    sw = read_sweep(prov, sweep_path)
    _, spokes = detect_sweep(sw)
    az = np.radians(sw["az"])
    r = sw["r_km"]
    order = np.argsort(sw["az"])
    edges_az = np.radians(np.r_[sw["az"][order] - 0.5, sw["az"][order][-1] + 0.5])
    edges_r = np.r_[r - (r[1] - r[0]) / 2, r[-1] + (r[1] - r[0]) / 2]
    A, R = np.meshgrid(edges_az, edges_r, indexing="ij")
    fig, ax = plt.subplots(figsize=(4.6, 4.2))
    m = ax.pcolormesh(R * np.sin(A), R * np.cos(A), sw["z"][order], vmin=-20, vmax=40, cmap="turbo", shading="flat",
                      rasterized=True)
    for s in spokes:
        a = math.radians(s["az"])
        c = "#e08e0b" if s["sun"] else ("#888888" if s["precip"] else "k")
        ax.plot([1.03 * r[-1] * math.sin(a), 1.15 * r[-1] * math.sin(a)],
                [1.03 * r[-1] * math.cos(a), 1.15 * r[-1] * math.cos(a)], color=c, lw=2.2, solid_capstyle="butt")
    for rr in range(50, int(r[-1]) + 1, 50):
        ax.add_patch(plt.Circle((0, 0), rr, fill=False, lw=0.3, color="#555"))
    ax.set_aspect("equal")
    lim = 1.17 * (rmax or r[-1])
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_title(f"{sw['radar']} {sw['start']:%Y-%m-%d %H:%M} UTC, TH, el {sw['elangle']:.1f}°\n"
                 f"ticks outside the range ring: detected spokes (black), sun spike (orange)", fontsize=7.5)
    ax.tick_params(labelsize=6.5)
    ax.set_xlabel("km east", fontsize=7)
    ax.set_ylabel("km north", fontsize=7)
    cb = plt.colorbar(m, ax=ax, shrink=0.75)
    cb.set_label("dBZ", fontsize=7)
    cb.ax.tick_params(labelsize=6)
    src = "Deutscher Wetterdienst" if prov == "dwd" else "Finnish Meteorological Institute"
    ax.text(0.99, 0.01, f"Data: {src}, CC BY 4.0", transform=ax.transAxes, fontsize=5.5, ha="right", color="#333")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


# ----------------------------------------------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="download sweeps for one UTC day")
    f.add_argument("--day", required=True)
    f.add_argument("--source", choices=["dwd", "fmi", "all"], default="all")
    f.add_argument("--sites", default="", help="comma-separated site codes (default: all)")
    f.add_argument("--step-dwd", type=int, default=5, help="minutes between DWD sweeps kept (multiple of 5)")
    f.add_argument("--step-fmi", type=int, default=15, help="minutes between FMI volumes kept (multiple of 5)")
    f.add_argument("--hours", default="", help="UTC hour range, e.g. 0-24")
    d = sub.add_parser("detect", help="detect spokes in every downloaded sweep of one day")
    d.add_argument("--day", required=True)
    d.add_argument("--sites", default="")
    g = sub.add_parser("aggregate", help="sources per radar, sun check and bearing intersections")
    g.add_argument("--day", required=True)
    st = sub.add_parser("stack", help="long-exposure check: echo occurrence stacked over the day (after aggregate)")
    st.add_argument("--day", required=True)
    pl = sub.add_parser("plot", help="figures: maps, azimuth-time plots, example sweeps")
    pl.add_argument("--day", required=True)
    pl.add_argument("--outdir", default=str(ROOT / "docs" / "validation" / "img"))
    pl.add_argument("--timeaz", default="", help="radars for the azimuth-time figure, e.g. dwd:asb,fmi:anj")
    pl.add_argument("--ppi", default="", help="comma-separated sweep files under data/radar (e.g. dwd/<day>/boo/<file>)")
    pl.add_argument("--maps", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "plot":
        od = Path(args.outdir)
        od.mkdir(parents=True, exist_ok=True)
        if args.maps:
            fig_map(args.day, "dwd", (5.5, 47.0, 15.5, 55.6), od / f"radar_spokes_map_dwd_{args.day}.png",
                    f"DWD 0.5° sweeps, {args.day}: spoke bearings (drawn to each radar's 180 km range)")
            fig_map(args.day, "fmi", (19.0, 58.4, 31.8, 68.5), od / f"radar_spokes_map_fmi_{args.day}.png",
                    f"FMI lowest sweeps, {args.day}: spoke bearings (drawn to each radar's 250 km range)")
        if args.timeaz:
            fig_timeaz(args.day, args.timeaz.split(","), od / f"radar_spokes_timeaz_{args.day}.png")
        for k, rel in enumerate(x for x in args.ppi.split(",") if x):
            pth = DATA / rel
            prov = rel.split("/")[0]
            fig_ppi(prov, pth, od / f"radar_spokes_ppi_{pth.parent.name}_{args.day}.png")
    if args.cmd == "aggregate":
        run_aggregate(args.day)
    if args.cmd == "stack":
        run_stack(args.day)
    if args.cmd == "detect":
        run_detect(args.day, sites=[x for x in args.sites.split(",") if x] or None)
    if args.cmd == "fetch":
        sites = [x for x in args.sites.split(",") if x]
        hours = tuple(int(x) for x in args.hours.split("-")) if args.hours else None
        if args.source in ("dwd", "all"):
            fetch_dwd(args.day, [x for x in sites if len(x) == 3] or DWD_SITES, args.step_dwd, hours)
        if args.source in ("fmi", "all"):
            fetch_fmi(args.day, [x for x in sites if x.startswith("fi")], args.step_fmi, hours)


if __name__ == "__main__":
    main()
