#!/usr/bin/env python3
"""cygnss_rfi.py — GNSS L1 interference seen from orbit by NASA CYGNSS (spaceborne lane, first pass).

What CYGNSS measures
--------------------
CYGNSS is eight small satellites launched in Dec 2016 (L1 files exist for seven of them on the 2026 days
used here, six on 19 Oct 2026), in a 35° orbit at about 500–520 km. Each carries a GNSS-reflectometry receiver (the DDMI) fed by two nadir L1 antennas, tilted
28° to port and starboard, and a zenith navigation antenna. Every 0.5 s (1 s before July 2019) the DDMI
cross-correlates the nadir signal with the C/A codes of four GPS satellites and outputs four delay-Doppler maps
(DDMs), one per reflection. The specular points lie within about ±38–40° latitude.

Why the DDM noise floor sees jammers
------------------------------------
Reflected GPS power can only arrive at or after the specular delay, so the delay rows ahead of it (the
"forbidden zone") hold no surface signal. The L1 product's `ddm_noise_floor` is the mean raw count over the
first 45 delay rows of the uncompressed 20 x 128 DDM (netCDF variable comment, CYGNSS L1 V3.2). It measures all
L1-band power that enters the nadir antenna and does not correlate with the tracked code: scene brightness
temperature, receiver noise, background GPS energy, and any interference. A jammer's signal is spread by the
code correlation and lifts the whole map (wideband jammers) or a Doppler stripe (CW or narrowband), and both
raise the forbidden-zone mean. Chew, Roberts & Lowe (2023) mapped RFI hotspots worldwide from this quantity, and
Shin & Son (2026) built an epoch detector from the four channel values (sources: docs/validation/cygnss.md).

Normalisation and baseline (the choices made here)
--------------------------------------------------
1. Counts scale with instrument gain, which drifts with LNA temperature. The product's `inst_gain` (count/W,
   from the on-board black-body calibration) converts counts to power: x = 10 log10(ddm_noise_floor /
   inst_gain), in dB with an arbitrary offset. The gain settings were fixed (33 dB) on the spacecraft-day checked.
2. The expected value of x depends on the receiver (spacecraft and antenna) and on the scene in the antenna
   footprint. Footprints over land read 0.9–1.4 dB *lower* than open ocean in these data (empirical; the
   probable cause, background GPS energy scattered from the sea, is unverified). Each DDM's footprint land
   fraction comes from the Natural Earth land mask at 0.25°, smoothed with a 1.5° Gaussian (about the
   width of the antenna's main beam on the ground).
3. Baseline = that day's median of x for the same spacecraft, same antenna and same land-fraction decile.
   Regions where the median excess reaches 1 dB on a coarse H3 res-2 grid are left out and the baseline is
   recomputed (three passes), so that large interference areas don't raise their own reference.
4. Excess = x minus baseline, in dB. Per H3 cell (res 3 by default) we keep the median excess, the 90th
   percentile, the share of DDMs 1 dB and 2 dB above baseline, the shares carrying the product's own
   kurtosis-based `rfi_detected` and `poor_quality_bin_ratio` flags (for comparison only), and the number of
   separate overpasses. DDMs whose specular point is off the receiving antenna's main lobe are dropped (see
   QF2_EXCLUDE), because the noise belongs to the beam, not to the point.
5. Dropouts. Inside the strongest interference the L1 series often has no samples at all for minutes at a
   time (seen on every spacecraft over Iraq and Iran). Missing samples are placed along the ground track by
   interpolation and counted per cell by sub-satellite point: dropout = missing / (present + missing).
   Whether the cause is the spacecraft losing its own GPS fix or data being withheld is not confirmed.

Why not other variables: `ddm_snr` and NBRCS depend on surface reflectivity and so mix geophysics with RFI.
The kurtosis flag performs poorly over land (Chew et al. 2023) and is less specific than the noise floor
(Shin & Son 2026). The black-body counts per kelvin are only filled on black-body DDMs (about 1%).

Location caveat
---------------
The noise enters through the whole antenna beam, a few hundred km across on the ground, and a strong jammer
is also seen in the sidelobes out to the radio horizon (about 2,500 km from 520 km altitude). Gridding by
specular point therefore spreads one emitter over a region several hundred km wide. A high cell means the
footprints that sampled it were exposed; it is not the emitter location.

Data and access
---------------
CYGNSS Level 1 Science Data Record V3.2 (PO.DAAC, DOI 10.5067/CYGNS-L1X32; NASA open data). One file per
spacecraft per UTC day is about 1.1 GB, so this tool asks NASA's cloud OPeNDAP server for only the variables
it needs, every `--stride`-th sample (default 2, i.e. 1 Hz): about 6 MB per spacecraft-day. It needs an
Earthdata Login bearer token in the environment variable EARTHDATA_TOKEN, sent only in the Authorization
header and never printed or written.

Usage
  python tools/cygnss_rfi.py fetch 2026-05-10 2026-05-16          # CMR search + OPeNDAP subset into data/cygnss/l1/<day>/
  python tools/cygnss_rfi.py grid 2026-05-10 2026-05-16 [--res 3] # data/cygnss/grid/<day>.r3.parquet, plus
                                                                   # <day>.r3.passes.parquet (per cell and pass)
  python tools/cygnss_rfi.py validate 2026-05-10 2026-05-16 [--res 3] [--figures [--map-days 2026-05-10]]
  python tools/cygnss_rfi.py all 2026-05-10 2026-05-16            # fetch, grid, validate
  python tools/cygnss_rfi.py pass 2026-05-10 --sc 4 --hours 17.45 17.80   # one pass, per antenna, with gaps
validate compares with the aircraft tables data/pnt/year/<day>.parquet and writes data/cygnss/validation_r<res>.json
(or --out). Held-out, same-hour and FAA-test checks: tools/cygnss_checks.py.
"""
import argparse
import json
import os
import re
import time
from collections import defaultdict

import h3
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "cygnss")
L1_DIR = os.path.join(DATA, "l1")
GRID_DIR = os.path.join(DATA, "grid")
AIRCRAFT_DIR = os.path.join(ROOT, "data", "pnt", "year")
CACHE = os.path.join(ROOT, "data", "cache")
IMG = os.path.join(ROOT, "docs", "validation", "img")
NE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/{}.geojson"

CMR = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
SHORT_NAME = "CYGNSS_L1_V3.2"
PROVIDER = "POCLOUD"

SAMPLE_VARS = ("ddm_timestamp_utc", "sc_lat", "sc_lon")
DDM_VARS = ("ddm_noise_floor", "inst_gain", "sp_lat", "sp_lon", "ddm_ant", "quality_flags", "quality_flags_2")

# quality_flags bits that make a DDM unusable for a noise-floor measurement (bit values from the V3.2 netCDF).
QF_EXCLUDE = (8          # large_sc_attitude_err
              | 16       # black_body_ddm (noise floor is then the black-body load)
              | 32       # ddmi_reconfigured
              | 64       # spacewire_crc_invalid
              | 128      # ddm_is_test_pattern
              | 256      # channel_idle
              | 32768    # direct_signal_in_ddm
              | 268435456   # sc_altitude_out_of_nominal_range
              | 536870912   # anomalous_sampling_period
              | 1073741824)  # invalid_roll_state
QF_RFI = 131072          # rfi_detected: kurtosis of the noise floor departs from Gaussian by more than 1.0
QF2_EXCLUDE = (1         # incorrect_ddmi_antenna_selection: the specular point is on the other antenna's side
               | 4       # noise_floor_cal_error: the signal sits in the top rows, so no clean noise rows
               | 8)      # sp_in_sidelobe: the specular point is outside the antenna's main lobe
# Why 1 and 8 matter: the noise floor belongs to the antenna's main beam, not to the specular point. When the
# specular point lies off-beam, the point misplaces the noise by hundreds of km. Near the turning latitudes
# (about ±35°) this is common: on 9 May 2026 the starboard antenna, looking south from about 35°N, logged
# specular points at 36–40°N over the western US (97–99% flagged 1) at +2 dB while the port antenna on the same
# passes read -0.2 dB. Together the two flags drop about 24% of DDMs worldwide, more near ±35°.
QF2_BIN_RATIO = 512      # poor_quality_bin_ratio: the ADC bit-count ratio shows degraded input (recorded, not excluded)
# Not excluded on purpose: low_confidence_ddm_noise_floor (512) and large_step_noise_floor (8192) are set by
# noise-floor jumps between samples, which is what a jammer coming into view looks like.

# Data dropouts: samples missing from the 2 Hz series. Inside the strongest interference the L1 product often
# has no samples at all for minutes at a time, so missing samples are counted per cell as their own indicator.
GAP_MIN_SAMPLES = 5      # a gap is at least 5 missing cadence steps
MAX_GAP = 900.0          # seconds; longer gaps are not filled (outages, interpolation unreliable)
DROP_MIN_SAMPLES = 30    # present + missing sub-satellite samples for a cell's dropout share to count
DROPOUT_SHARE = 0.5      # a cell "drops out" when half or more of its expected samples are missing

LAND_RES = 0.25          # degrees, land mask grid
FOOTPRINT_SIGMA = 1.5    # degrees, Gaussian smoothing of the land mask to approximate the antenna footprint
LAND_BINS = 10
HOT_RES = 2              # H3 resolution of the cells excluded from the baseline
HOT_DB = 1.0             # median excess at which a res-2 cell is left out of the baseline
HOT_MIN_N = 30
BASE_PASSES = 3
MIN_DDM = 10             # DDMs per cell to write it
PASS_SECONDS = 600       # samples of one spacecraft within 10 minutes count as one overpass
PASS_MIN_DDM = 5         # DDMs of one pass in one cell for a pass-cell row (the per-pass table)

ELEVATED_DB = 1.0        # a priori: a cell is "elevated" at a median excess of 1 dB (26% more noise power)
PAIR_MIN_DDM = 20
PAIR_MIN_AIRCRAFT = 20   # summed aircraft over the res-4 children of a res-3 cell
JAM_SHARE = 10.0         # GPSJam-style share (per res-4 hex: (bad - 1) / aircraft) aggregated, percent
CLEAN_SHARE = 2.0

# Validation boxes (lat0, lat1, lon0, lon1). "known": regions with published reporting of GNSS interference
# in 2024–2026 (sources in docs/validation/cygnss.md); "control": no published persistent interference.
BOXES = {
    "known": {
        "Levant (Israel, Lebanon, Syria)": (31.0, 37.0, 34.0, 39.0),
        "Egypt / Sinai / Suez": (27.0, 31.0, 31.0, 34.5),
        "Iraq": (29.0, 37.0, 39.0, 48.5),
        "Persian Gulf": (23.5, 30.5, 47.5, 57.0),
        "Iran (interior)": (30.5, 37.5, 48.0, 61.0),
        "Red Sea": (12.5, 28.0, 33.0, 43.5),
        "India-Pakistan border": (24.0, 34.0, 69.0, 77.0),
        "Myanmar": (16.0, 26.0, 92.0, 99.0),
        "South China Sea": (5.0, 22.0, 108.0, 120.0),
    },
    "control": {
        "Central Pacific": (-20.0, 20.0, -160.0, -130.0),
        "South Atlantic": (-30.0, -10.0, -30.0, -10.0),
        "Brazil interior": (-20.0, -5.0, -60.0, -45.0),
        "Australia interior": (-32.0, -20.0, 120.0, 145.0),
        "Southern Africa interior": (-30.0, -18.0, 15.0, 30.0),
    },
}


# ---------------------------------------------------------------------------------------------- fetch

def _session():
    import requests
    token = os.environ.get("EARTHDATA_TOKEN")
    if not token:
        raise SystemExit("EARTHDATA_TOKEN is not set (an Earthdata Login bearer token is needed for OPeNDAP).")
    s = requests.Session()
    s.headers["Authorization"] = "Bearer " + token
    return s


def granules(day):
    """[(granule_ur, opendap_url)] for one UTC day, from NASA CMR (no login needed)."""
    import requests
    r = requests.get(CMR, params={"short_name": SHORT_NAME, "provider": PROVIDER, "page_size": 50,
                                  "temporal": f"{day}T00:00:00Z,{day}T23:59:59Z"}, timeout=60)
    r.raise_for_status()
    out = []
    for it in r.json().get("items", []):
        u = it["umm"]
        ur = u["GranuleUR"]
        if not ur.startswith(f"cyg") or f".s{day.replace('-', '')}-" not in ur:
            continue  # the temporal search also returns the neighbouring day's files at the edges
        od = [x["URL"] for x in u.get("RelatedUrls", []) if x.get("Subtype") == "OPENDAP DATA"]
        if od:
            out.append((ur, od[0]))
    return sorted(out)


def _get(sess, url, path=None, tries=4):
    for k in range(tries):
        try:
            r = sess.get(url, timeout=600, stream=path is not None)
            if r.status_code == 200:
                if path is None:
                    return r.content
                tmp = path + ".part"
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                os.replace(tmp, path)
                return path
            if r.status_code in (401, 403):
                raise SystemExit(f"HTTP {r.status_code} from OPeNDAP: token missing, expired or not authorised.")
            msg = f"HTTP {r.status_code}"
        except SystemExit:
            raise
        except Exception as e:  # network error; the message carries the URL only, never headers
            msg = type(e).__name__
        if k + 1 < tries:
            time.sleep(5 * (k + 1))
    raise RuntimeError(f"giving up on {url.split('?')[0]} ({msg})")


def sample_count(sess, opendap_url):
    xml = _get(sess, opendap_url + ".dmr.xml?dap4.ce=/sample").decode("latin-1")
    m = re.search(r'<Dimension name="sample" size="(\d+)"', xml)
    if not m:
        raise RuntimeError("no sample dimension in DMR")
    return int(m.group(1))


def subset_url(opendap_url, n, stride):
    s = f"%5B0:{stride}:{n - 1}%5D"
    parts = [f"/{v}{s}" for v in SAMPLE_VARS] + [f"/{v}{s}%5B0:3%5D" for v in DDM_VARS]
    return opendap_url + ".dap.nc4?dap4.ce=" + ";".join(parts)


def fetch(day, stride=2):
    sess = _session()
    out_dir = os.path.join(L1_DIR, day)
    os.makedirs(out_dir, exist_ok=True)
    gs = granules(day)
    if not gs:
        print(f"{day}: no CYGNSS L1 granules in CMR yet")
        return []
    got, total = [], 0
    for ur, url in gs:
        path = os.path.join(out_dir, f"{ur}.stride{stride}.nc4")
        if not os.path.exists(path):
            n = sample_count(sess, url)
            _get(sess, subset_url(url, n, stride), path)
        got.append(path)
        total += os.path.getsize(path)
    print(f"{day}: {len(got)} spacecraft files, {total / 1e6:.1f} MB in {os.path.relpath(out_dir, ROOT)}")
    return got


# ---------------------------------------------------------------------------------------------- land mask

_LAND = None


def footprint_land():
    """0.25° grid (rows from 90N) of land fraction smoothed to roughly the antenna footprint."""
    global _LAND
    if _LAND is not None:
        return _LAND
    cache = os.path.join(DATA, f"landfrac_{LAND_RES}_{FOOTPRINT_SIGMA}.npy")
    if os.path.exists(cache):
        _LAND = np.load(cache)
        return _LAND
    path = os.path.join(CACHE, "ne_50m_land.geojson")
    if not os.path.exists(path):
        import urllib.request
        os.makedirs(CACHE, exist_ok=True)
        with urllib.request.urlopen(NE_URL.format("ne_50m_land"), timeout=120) as r:
            open(path, "wb").write(r.read())
    land = json.load(open(path, encoding="utf-8"))
    _LAND = smooth(land_mask(land).astype("float32"), FOOTPRINT_SIGMA / LAND_RES)
    os.makedirs(DATA, exist_ok=True)
    np.save(cache, _LAND)
    return _LAND


def smooth(a, sigma):
    """Separable Gaussian filter (truncated at 4 sigma): edge values beyond the poles, wrap-around in longitude.
    Same as scipy.ndimage.gaussian_filter(a, sigma, mode=("nearest", "wrap")), without needing scipy."""
    r = int(4.0 * sigma + 0.5)
    x = np.arange(-r, r + 1)
    k = np.exp(-0.5 * (x / sigma) ** 2)
    k /= k.sum()
    ny, nx = a.shape
    p = np.pad(a, ((r, r), (0, 0)), mode="edge")
    a = sum(k[i] * p[i:i + ny] for i in range(2 * r + 1))
    p = np.pad(a, ((0, 0), (r, r)), mode="wrap")
    return sum(k[i] * p[:, i:i + nx] for i in range(2 * r + 1)).astype("float32")


def land_mask(geojson, max_lat=50.0):
    """Boolean LAND_RES grid (rows from 90N, columns from 180W): cell centres inside land polygons, holes removed.
    Only rows within ±max_lat are filled (CYGNSS sees about ±40°)."""
    from matplotlib.path import Path
    ny, nx = int(180 / LAND_RES), int(360 / LAND_RES)
    lats = 90.0 - LAND_RES * (np.arange(ny) + 0.5)
    lons = -180.0 + LAND_RES * (np.arange(nx) + 0.5)
    mask = np.zeros((ny, nx), dtype=bool)

    def fill(ring, value):
        ring = np.asarray(ring, dtype=float)
        x0, y0 = ring.min(axis=0)
        x1, y1 = ring.max(axis=0)
        cols = np.where((lons >= x0) & (lons <= x1))[0]
        rows = np.where((lats >= max(y0, -max_lat)) & (lats <= min(y1, max_lat)))[0]
        if not len(cols) or not len(rows):
            return
        xx, yy = np.meshgrid(lons[cols], lats[rows])
        inside = Path(ring).contains_points(np.column_stack([xx.ravel(), yy.ravel()])).reshape(xx.shape)
        sub = mask[np.ix_(rows, cols)]
        sub[inside] = value
        mask[np.ix_(rows, cols)] = sub

    for f in geojson["features"]:
        g = f["geometry"]
        for poly in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
            fill(poly[0], True)
            for hole in poly[1:]:
                fill(hole, False)
    return mask


def land_fraction(lat, lon):
    g = footprint_land()
    ny, nx = g.shape
    iy = np.clip(((90.0 - lat) / LAND_RES).astype(int), 0, ny - 1)
    ix = (((lon + 180.0) / LAND_RES).astype(int)) % nx
    return g[iy, ix]


# ---------------------------------------------------------------------------------------------- grid

def gaps(t, lat, lon, max_gap=MAX_GAP):
    """Sub-satellite positions of the samples missing from a time series (multi-sample gaps only).

    The cadence is the median spacing. Gaps longer than `max_gap` seconds are not filled (positions can't be
    interpolated reliably). Positions are interpolated along the great circle between the samples either side
    of the gap; Earth rotation during the gap is ignored (under 1° of error at 15 minutes)."""
    if len(t) < 3:
        return np.empty(0), np.empty(0), 1.0
    dt = np.diff(t)
    cad = float(np.median(dt))
    out_lat, out_lon = [], []
    for i in np.where((dt > GAP_MIN_SAMPLES * cad) & (dt <= max_gap))[0]:
        k = int(round(dt[i] / cad)) - 1
        f = np.arange(1, k + 1) / (k + 1)
        a, b = _unit(lat[i], lon[i]), _unit(lat[i + 1], lon[i + 1])
        om = np.arccos(np.clip(np.dot(a, b), -1, 1))
        if om < 1e-9:
            continue
        p = (np.sin((1 - f) * om)[:, None] * a + np.sin(f * om)[:, None] * b) / np.sin(om)
        out_lat.append(np.degrees(np.arcsin(np.clip(p[:, 2], -1, 1))))
        out_lon.append(np.degrees(np.arctan2(p[:, 1], p[:, 0])))
    if not out_lat:
        return np.empty(0), np.empty(0), cad
    return np.concatenate(out_lat), np.concatenate(out_lon), cad


def _unit(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.array([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])


def read_day(day):
    """Valid DDMs of one day as flat arrays (one entry per DDM), plus present and missing sub-satellite points."""
    import h5py
    d = os.path.join(L1_DIR, day)
    files = sorted(f for f in os.listdir(d) if f.endswith(".nc4")) if os.path.isdir(d) else []
    if not files:
        raise SystemExit(f"{day}: no subsets in {os.path.relpath(d, ROOT)} (run fetch first)")
    best = {}  # one file per granule: the densest stride fetched
    for fn in files:
        m = re.match(r"(.+)\.stride(\d+)\.nc4$", fn)
        key, stride = (m.group(1), int(m.group(2))) if m else (fn, 1)
        if key not in best or stride < best[key][0]:
            best[key] = (stride, fn)
    files = sorted(fn for _, fn in best.values())
    cols = defaultdict(list)
    for fn in files:
        sc = int(fn[3:5])
        with h5py.File(os.path.join(d, fn), "r") as f:
            v = {k: f[k][...] for k in DDM_VARS}
            t = f["ddm_timestamp_utc"][...].astype("float64")
            sclat = f["sc_lat"][...].astype("float64")
            sclon = f["sc_lon"][...].astype("float64")
        nf = v["ddm_noise_floor"].astype("float64")
        ig = v["inst_gain"].astype("float64")
        lat = v["sp_lat"].astype("float64")
        lon = v["sp_lon"].astype("float64")
        ant = v["ddm_ant"].astype("int16")
        qf = v["quality_flags"].astype("int64")
        qf2 = v["quality_flags_2"].astype("int64")
        ok = ((nf > 0) & (ig > 0) & np.isfinite(nf) & np.isfinite(ig) & (np.abs(lat) <= 45) & (lon >= -180)
              & ((ant == 2) | (ant == 3)) & ((qf & QF_EXCLUDE) == 0) & ((qf2 & QF2_EXCLUDE) == 0))
        tt = np.broadcast_to(t[:, None], nf.shape)
        cols["x"].append(10 * np.log10(nf[ok] / ig[ok]))
        cols["lat"].append(lat[ok])
        cols["lon"].append(np.where(lon[ok] > 180, lon[ok] - 360, lon[ok]))
        cols["ant"].append(ant[ok])
        cols["rfi"].append((qf[ok] & QF_RFI) > 0)
        cols["bin"].append((qf2[ok] & QF2_BIN_RATIO) > 0)
        cols["t"].append(tt[ok])
        cols["sc"].append(np.full(int(ok.sum()), sc, dtype="int16"))
        sclon = np.where(sclon > 180, sclon - 360, sclon)
        good = np.isfinite(sclat) & np.isfinite(sclon) & (np.abs(sclat) <= 90)
        mlat, mlon, _ = gaps(t[good], sclat[good], sclon[good])
        cols["sub_lat"].append(sclat[good])
        cols["sub_lon"].append(sclon[good])
        cols["miss_lat"].append(mlat)
        cols["miss_lon"].append(mlon)
    return {k: np.concatenate(v) for k, v in cols.items()}, len(files)


def _cells(lat, lon, res):
    """H3 cell per point (rounded to 0.01° first so repeated positions are computed once)."""
    key = (np.round(lat * 100).astype(np.int64) + 9000) * 40000 + (np.round(lon * 100).astype(np.int64) + 18000)
    uk, inv = np.unique(key, return_inverse=True)
    first = np.zeros(len(uk), dtype=np.int64)
    first[inv[::-1]] = np.arange(len(inv))[::-1]
    names = np.array([h3.latlng_to_cell(float(lat[i]), float(lon[i]), res) for i in first])
    return names[inv]


def group_median(values, groups):
    """Median of values per group id (dense ints)."""
    order = np.lexsort((values, groups))
    v, g = values[order], groups[order]
    ug, start, cnt = np.unique(g, return_index=True, return_counts=True)
    med = (v[start + (cnt - 1) // 2] + v[start + cnt // 2]) / 2
    out = np.full(groups.max() + 1, np.nan)
    out[ug] = med
    return out, ug, start, cnt, v


def excess(day_data, hot_cells_of):
    """Excess over the spacecraft/antenna/land-decile baseline, leaving out hot res-2 cells (iterated)."""
    x = day_data["x"]
    lf = land_fraction(day_data["lat"], day_data["lon"])
    lbin = np.minimum((lf * LAND_BINS).astype(int), LAND_BINS - 1)
    grp = (day_data["sc"].astype(int) * 2 + (day_data["ant"].astype(int) - 2)) * LAND_BINS + lbin
    hot = np.zeros(len(x), dtype=bool)
    parent_ids = hot_cells_of  # dense int id of the res-2 cell of each DDM
    for _ in range(BASE_PASSES):
        base, _, _, _, _ = group_median(x[~hot], grp[~hot])
        if len(base) <= grp.max():
            base = np.concatenate([base, np.full(grp.max() + 1 - len(base), np.nan)])
        ex = x - base[grp]
        med, ug, _, cnt, _ = group_median(np.nan_to_num(ex, nan=0.0), parent_ids)
        n = np.zeros(parent_ids.max() + 1, dtype=int)
        n[ug] = cnt
        hot_cell = (med >= HOT_DB) & (n >= HOT_MIN_N)
        hot = hot_cell[parent_ids]
    return ex, lf, hot.mean()


def _prepare(day, res):
    d, nfiles = read_day(day)
    cell = _cells(d["lat"], d["lon"], res)
    ucell, cid = np.unique(cell, return_inverse=True)
    par = np.array([h3.cell_to_parent(c, HOT_RES) if res > HOT_RES else c for c in ucell])
    _, pid_of_cell = np.unique(par, return_inverse=True)
    ex, lf, hot_share = excess(d, pid_of_cell[cid])
    return d, nfiles, ucell, cid, ex, lf, hot_share


def day_excess(day, res=3):
    """(DDM arrays, excess in dB) for one day, as used by grid()."""
    d, _, _, _, ex, _, _ = _prepare(day, res)
    return d, ex


def grid(day, res=3):
    d, nfiles, ucell, cid, ex, lf, hot_share = _prepare(day, res)
    ok = np.isfinite(ex)
    ex, cid2, lf, rfi, binf = ex[ok], cid[ok], lf[ok], d["rfi"][ok], d["bin"][ok]
    passes = d["sc"][ok].astype(np.int64) * 1000 + (d["t"][ok] // PASS_SECONDS).astype(np.int64)

    order = np.lexsort((ex, cid2))
    v, g = ex[order], cid2[order]
    ug, start, cnt = np.unique(g, return_index=True, return_counts=True)
    med = (v[start + (cnt - 1) // 2] + v[start + cnt // 2]) / 2
    p90 = v[start + np.floor(0.9 * (cnt - 1)).astype(int)]
    nn = np.bincount(cid2, minlength=len(ucell))
    f1 = np.bincount(cid2, weights=(ex >= 1.0), minlength=len(ucell))
    f2 = np.bincount(cid2, weights=(ex >= 2.0), minlength=len(ucell))
    fr = np.bincount(cid2, weights=rfi, minlength=len(ucell))
    fb = np.bincount(cid2, weights=binf, minlength=len(ucell))
    lm = np.bincount(cid2, weights=lf, minlength=len(ucell))
    npass = np.zeros(len(ucell), dtype=int)
    up = np.unique(cid2.astype(np.int64) * 10**9 + passes)
    np.add.at(npass, (up // 10**9).astype(int), 1)

    rows = {}
    for k, c in enumerate(ug):
        n = int(nn[c])
        if n < MIN_DDM:
            continue
        rows[ucell[c]] = {"n": n, "passes": int(npass[c]),
                          "med_db": round(float(med[k]), 3), "p90_db": round(float(p90[k]), 3),
                          "frac1": round(f1[c] / n, 4), "frac2": round(f2[c] / n, 4),
                          "rfi_flag": round(fr[c] / n, 4), "bin_flag": round(fb[c] / n, 4),
                          "land": round(lm[c] / n, 3)}
    # Dropouts, by sub-satellite point: the whole receiver stops, so the spacecraft position is the right place.
    present = defaultdict(int)
    missing = defaultdict(int)
    for name, n in zip(*np.unique(_cells(d["sub_lat"], d["sub_lon"], res), return_counts=True)):
        present[name] = int(n)
    if len(d["miss_lat"]):
        for name, n in zip(*np.unique(_cells(d["miss_lat"], d["miss_lon"], res), return_counts=True)):
            missing[name] = int(n)
    empty = {"n": 0, "passes": 0, "med_db": None, "p90_db": None, "frac1": None, "frac2": None,
             "rfi_flag": None, "bin_flag": None, "land": None}
    out = []
    for c in sorted(set(rows) | set(present) | set(missing)):
        la, lo = h3.cell_to_latlng(c)
        p, m = present.get(c, 0), missing.get(c, 0)
        r = {"h3": c, "lat": round(la, 4), "lon": round(lo, 4), **rows.get(c, empty),
             "sub_present": p, "sub_missing": m,
             "dropout": round(m / (p + m), 4) if p + m >= DROP_MIN_SAMPLES else None}
        out.append(r)
    write_rows(os.path.join(GRID_DIR, f"{day}.r{res}.parquet"), out)
    # Per pass: the same excess, split by spacecraft and 10-minute bucket, for same-hour comparisons. Leaves the
    # cell table above unchanged.
    write_rows(os.path.join(GRID_DIR, f"{day}.r{res}.passes.parquet"),
               pass_cells(ucell, cid2, d["sc"][ok], d["t"][ok], ex))
    nmiss, npres = len(d["miss_lat"]), len(d["sub_lat"])
    print(f"{day}: {nfiles} spacecraft, {len(ex):,} DDMs, {len(rows):,} res-{res} cells with {MIN_DDM}+ DDMs "
          f"(baseline left out {100 * hot_share:.1f}% of DDMs in hot res-2 cells); "
          f"missing samples {nmiss:,} of {nmiss + npres:,} ({100 * nmiss / max(nmiss + npres, 1):.2f}%)")
    return out


def pass_cells(ucell, cid, sc, t, ex, min_n=PASS_MIN_DDM):
    """Median excess per (cell, pass): a pass is one spacecraft in one PASS_SECONDS bucket of the UTC day, as grid()
    counts overpasses. Rows: h3, sc, bucket, t_mid (mean seconds since 00 UTC), n, med_db. Pass-cells with fewer
    than `min_n` DDMs are left out."""
    bucket = (np.asarray(t) // PASS_SECONDS).astype(np.int64)
    key = (np.asarray(cid).astype(np.int64) * 100 + np.asarray(sc).astype(np.int64)) * 1000 + bucket
    uk, gid = np.unique(key, return_inverse=True)
    if not len(uk):
        return []
    med, ug, _, cnt, _ = group_median(np.asarray(ex, dtype=float), gid)
    tsum = np.bincount(gid, weights=np.asarray(t, dtype=float), minlength=len(uk))
    n = np.bincount(gid, minlength=len(uk))
    rows = []
    for g in ug:
        if n[g] < min_n:
            continue
        k = int(uk[g])
        rows.append({"h3": ucell[k // 100000], "sc": int(k // 1000 % 100), "bucket": int(k % 1000),
                     "t_mid": round(float(tsum[g] / n[g]), 1), "n": int(n[g]), "med_db": round(float(med[g]), 3)})
    return rows


def read_passes(day, res=3):
    """The per-pass table written by grid(), as a list of dicts (None if absent)."""
    import pyarrow.parquet as pq
    p = os.path.join(GRID_DIR, f"{day}.r{res}.passes.parquet")
    return pq.read_table(p).to_pylist() if os.path.exists(p) else None


def write_rows(path, rows):
    import pyarrow as pa
    import pyarrow.parquet as pq
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def read_grid(day, res):
    import pyarrow.parquet as pq
    p = os.path.join(GRID_DIR, f"{day}.r{res}.parquet")
    return {r["h3"]: r for r in pq.read_table(p).to_pylist()} if os.path.exists(p) else None


# ---------------------------------------------------------------------------------------------- validate

def aircraft(day, res):
    """Aircraft per res-`res` cell from the res-4 daily table: summed aircraft, GPSJam-style bad, raw bad."""
    import pyarrow.parquet as pq
    p = os.path.join(AIRCRAFT_DIR, f"{day}.parquet")
    if not os.path.exists(p):
        return None
    t = pq.read_table(p, columns=["h3", "aircraft", "bad_nacp_live"]).to_pydict()
    out = defaultdict(lambda: [0, 0, 0])
    par = {}
    for c, a, b in zip(t["h3"], t["aircraft"], t["bad_nacp_live"]):
        if c not in par:
            par[c] = h3.cell_to_parent(c, res) if res < 4 else c
        o = out[par[c]]
        o[0] += a
        o[1] += max(b - 1, 0)
        o[2] += b
    return dict(out)


def in_box(lat, lon, b):
    return b[0] <= lat <= b[1] and b[2] <= lon <= b[3]


def auc(pos, neg):
    """Area under the ROC curve: the chance a random positive scores above a random negative (ties count half).
    Equal to the Mann-Whitney U statistic divided by n_pos * n_neg."""
    if not len(pos) or not len(neg):
        return None
    v = np.concatenate([np.asarray(pos, dtype=float), np.asarray(neg, dtype=float)])
    order = np.argsort(v, kind="mergesort")
    ranks = np.empty(len(v))
    sv = v[order]
    # average ranks over ties
    _, start, cnt = np.unique(sv, return_index=True, return_counts=True)
    avg = start + (cnt + 1) / 2.0
    ranks[order] = np.repeat(avg, cnt)
    n1 = len(pos)
    u = ranks[:n1].sum() - n1 * (n1 + 1) / 2.0
    return float(u) / (n1 * len(neg))


WINDOW = (0.0, 42.0, 20.0, 110.0)   # Middle East to South-East Asia, where both maps vary


def noise_ok(r):
    return r["n"] >= PAIR_MIN_DDM and r["med_db"] is not None


def drop_ok(r):
    return r["dropout"] is not None


def affected(r):
    """Combined CYGNSS call: elevated noise floor, or most of the expected samples missing."""
    return (noise_ok(r) and r["med_db"] >= ELEVATED_DB) or (drop_ok(r) and r["dropout"] >= DROPOUT_SHARE)


def score_table(pairs, key, ok, thresholds):
    """AUC (aircraft-jammed vs aircraft-clean) and hit / false-alarm rates for one CYGNSS indicator."""
    sel = [(r[key], s) for r, s, _ in pairs if ok(r)]
    jam = [v for v, s in sel if s >= JAM_SHARE]
    clean = [v for v, s in sel if s < CLEAN_SHARE]
    return {"pairs": len(sel), "jam": len(jam), "clean": len(clean), "auc": _r(auc(jam, clean)),
            "rates": {str(t): {"hit": _rate(jam, t), "fa": _rate(clean, t)} for t in thresholds}}


def combined_rates(pairs):
    sel = [(affected(r), s) for r, s, _ in pairs if noise_ok(r) or drop_ok(r)]
    jam = [a for a, s in sel if s >= JAM_SHARE]
    clean = [a for a, s in sel if s < CLEAN_SHARE]
    return {"pairs": len(sel), "jam": len(jam), "clean": len(clean),
            "hit": round(sum(jam) / len(jam), 3) if jam else None,
            "fa": round(sum(clean) / len(clean), 3) if clean else None}


def spearman_on(pairs, key, ok, box=None):
    from scipy.stats import spearmanr
    sel = [(r[key], s) for r, s, _ in pairs if ok(r) and (box is None or in_box(r["lat"], r["lon"], box))]
    if len(sel) <= 10:
        return None
    out = _rho(spearmanr([a for a, _ in sel], [b for _, b in sel]))
    out["n"] = len(sel)
    return out


def region_table(g, ac):
    regions = {}
    for kind, boxes in BOXES.items():
        for name, b in boxes.items():
            inside = [(c, r) for c, r in g.items() if in_box(r["lat"], r["lon"], b)]
            nz = [r["med_db"] for _, r in inside if noise_ok(r)]
            dr = [r["dropout"] for _, r in inside if drop_ok(r)]
            acs = [ac[c] for c, _ in inside if c in ac]
            a_sum = sum(a[0] for a in acs)
            regions[name] = {
                "kind": kind,
                "cyg_cells": len(nz),
                "cyg_med_db": round(float(np.median(nz)), 2) if nz else None,
                "cyg_elevated": _rate(nz, ELEVATED_DB),
                "drop_cells": len(dr),
                "drop_med": round(float(np.median(dr)), 3) if dr else None,
                "drop_cells_over_half": _rate(dr, DROPOUT_SHARE),
                "affected_cells": sum(1 for _, r in inside if affected(r)),
                "judged_cells": sum(1 for _, r in inside if noise_ok(r) or drop_ok(r)),
                "aircraft": a_sum,
                "air_share": round(100.0 * sum(a[1] for a in acs) / a_sum, 1) if a_sum else None,
                "air_cells": sum(1 for a in acs if a[0] >= PAIR_MIN_AIRCRAFT),
                "air_jam_cells": sum(1 for a in acs if a[0] >= PAIR_MIN_AIRCRAFT and 100.0 * a[1] / a[0] >= JAM_SHARE),
            }
    return regions


def validate(days, res=3, figures=False, map_days=None, out=None):
    grids = {d: read_grid(d, res) for d in days}
    missing = [d for d, g in grids.items() if g is None]
    if missing:
        raise SystemExit(f"no res-{res} grid for {', '.join(missing)} (run grid --res {res})")
    # Cell's own baseline from the other days (temporal anomaly), where the cell has 3+ other days.
    hist = defaultdict(dict)
    for d, g in grids.items():
        for c, r in g.items():
            if noise_ok(r):
                hist[c][d] = r["med_db"]
    report = {"res": res, "days": {}, "params": {
        "elevated_db": ELEVATED_DB, "dropout_share": DROPOUT_SHARE, "jam_share": JAM_SHARE,
        "clean_share": CLEAN_SHARE, "pair_min_ddm": PAIR_MIN_DDM, "pair_min_aircraft": PAIR_MIN_AIRCRAFT,
        "drop_min_samples": DROP_MIN_SAMPLES, "window": WINDOW}}
    pooled = []
    for d in days:
        g, ac = grids[d], aircraft(d, res)
        if ac is None:
            print(f"{d}: no aircraft table, skipped")
            continue
        for c, r in g.items():
            others = [v for dd, v in hist[c].items() if dd != d]
            r["anom_db"] = (round(r["med_db"] - float(np.median(others)), 3)
                            if noise_ok(r) and len(others) >= 3 else None)
            if r["land"] is None:
                r["land"] = float(land_fraction(np.array([r["lat"]]), np.array([r["lon"]]))[0])
        pairs = [(r, 100.0 * ac[c][1] / ac[c][0], ac[c][0]) for c, r in g.items()
                 if c in ac and ac[c][0] >= PAIR_MIN_AIRCRAFT]
        judged = [r for r in g.values() if noise_ok(r) or drop_ok(r)]
        hits = [r for r in judged if affected(r)]
        blind = [(c, r) for c, r in g.items() if affected(r) and (c not in ac or ac[c][0] < 5)]
        nz = [r["med_db"] for r in g.values() if noise_ok(r)]
        rep = {
            "cells_noise": len(nz), "cells_dropout": sum(1 for r in g.values() if drop_ok(r)),
            "global_median_db": round(float(np.median(nz)), 3),
            "elevated_cells": sum(1 for v in nz if v >= ELEVATED_DB),
            "dropout_cells": sum(1 for r in g.values() if drop_ok(r) and r["dropout"] >= DROPOUT_SHARE),
            "affected_cells": len(hits), "judged_cells": len(judged),
            "paired_cells": len(pairs),
            "noise": score_table(pairs, "med_db", noise_ok, (0.5, 1.0, 1.5, 2.0)),
            "dropout": score_table(pairs, "dropout", drop_ok, (0.25, 0.5)),
            "kurtosis_flag": score_table(pairs, "rfi_flag", noise_ok, (0.05, 0.1)),
            "bin_ratio_flag": score_table(pairs, "bin_flag", noise_ok, (0.25, 0.5)),
            "anomaly": score_table(pairs, "anom_db", lambda r: r.get("anom_db") is not None, (0.5, 1.0)),
            "combined": combined_rates(pairs),
            "spearman_noise": spearman_on(pairs, "med_db", noise_ok),
            "spearman_noise_window": spearman_on(pairs, "med_db", noise_ok, WINDOW),
            "spearman_anomaly": spearman_on(pairs, "anom_db", lambda r: r.get("anom_db") is not None),
            "regions": region_table(g, ac),
            "blind_affected": len(blind),
            "blind_affected_water": sum(1 for _, r in blind if r["land"] < 0.2),
            "blind_by_box": _by_box([r for _, r in blind]),
        }
        report["days"][d] = rep
        pooled.extend(pairs)
        if figures and (map_days is None or d in map_days):
            figure_day(d, g, ac, res)
            figure_world(d, g, res)
        print(f"{d}: paired {len(pairs)} | noise AUC {rep['noise']['auc']} hit/FA@1dB "
              f"{rep['noise']['rates']['1.0']['hit']}/{rep['noise']['rates']['1.0']['fa']} | dropout AUC "
              f"{rep['dropout']['auc']} | combined hit/FA {rep['combined']['hit']}/{rep['combined']['fa']} | "
              f"rho {rep['spearman_noise']} | blind affected {len(blind)}", flush=True)
    if pooled:
        report["pooled"] = {
            "paired_cells": len(pooled),
            "noise": score_table(pooled, "med_db", noise_ok, (0.5, 1.0, 1.5, 2.0)),
            "dropout": score_table(pooled, "dropout", drop_ok, (0.25, 0.5)),
            "kurtosis_flag": score_table(pooled, "rfi_flag", noise_ok, (0.05, 0.1)),
            "bin_ratio_flag": score_table(pooled, "bin_flag", noise_ok, (0.25, 0.5)),
            "anomaly": score_table(pooled, "anom_db", lambda r: r.get("anom_db") is not None, (0.5, 1.0)),
            "combined": combined_rates(pooled),
            "spearman_noise": spearman_on(pooled, "med_db", noise_ok),
            "spearman_noise_window": spearman_on(pooled, "med_db", noise_ok, WINDOW),
            "by_share_bin": _share_bins([(r["med_db"], s) for r, s, _ in pooled if noise_ok(r)]),
        }
        if figures:
            figure_box([(r["med_db"], s) for r, s, _ in pooled if noise_ok(r)], res)
    path = out or os.path.join(DATA, f"validation_r{res}.json")
    json.dump(report, open(path, "w"), indent=1)
    print(f"wrote {os.path.relpath(path, ROOT)}")
    return report


def _rate(vals, t):
    return round(sum(1 for v in vals if v >= t) / len(vals), 3) if vals else None


def _r(v):
    return round(v, 3) if v is not None else None


def _rho(r):
    if r is None:
        return None
    return {"rho": round(float(r.statistic), 3), "p": float(f"{r.pvalue:.2g}")}


def _by_box(cells):
    out = defaultdict(int)
    for r in cells:
        name = next((n for boxes in BOXES.values() for n, b in boxes.items() if in_box(r["lat"], r["lon"], b)),
                    "outside the boxes")
        out[name] += 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _share_bins(xy):
    bins = [(0, 2), (2, 5), (5, 10), (10, 25), (25, 101)]
    out = []
    for lo, hi in bins:
        v = sorted(a for a, b in xy if lo <= b < hi)
        if v:
            out.append({"share": f"{lo}-{hi if hi <= 100 else 100}%", "cells": len(v),
                        "med_db": round(float(np.median(v)), 2),
                        "q25": round(float(np.percentile(v, 25)), 2), "q75": round(float(np.percentile(v, 75)), 2),
                        "elevated": round(sum(1 for a in v if a >= ELEVATED_DB) / len(v), 3)})
    return out


# ---------------------------------------------------------------------------------------------- figures

def _land_polys():
    land = json.load(open(os.path.join(CACHE, "ne_50m_land.geojson"), encoding="utf-8"))
    for f in land["features"]:
        geom = f["geometry"]
        for p in (geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]):
            yield p[0]


def _hex_polys(cells):
    polys, keep = [], []
    for i, c in enumerate(cells):
        b = [(lo, la) for la, lo in h3.cell_to_boundary(c)]
        if max(p[0] for p in b) - min(p[0] for p in b) > 180:
            continue
        polys.append(b)
        keep.append(i)
    return polys, keep


# Figure colours: one-hue sequential ramps (blue for noise excess, orange for dropouts); the aircraft panel keeps
# the project's GPSJam-style classes (tools/validate_phase1.py). Text stays in neutral inks.
BLUES = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
ORANGES = ["#fdf1ea", "#f9c9b0", "#f29a72", "#eb6834", "#b8461b", "#7a2a0c"]
AIR = {"green": "#41ab5d", "amber": "#fdae3b", "red": "#d7301f"}
INK, INK2, COAST, SURFACE = "#0b0b0b", "#52514e", "#6b6a66", "#fcfcfb"
CREDIT = "Data: NASA CYGNSS L1 V3.2 (PO.DAAC, DOI 10.5067/CYGNS-L1X32) · aircraft: adsb.lol (ODbL 1.0) · basemap: Natural Earth"


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 8, "axes.edgecolor": "#b5b4ae", "axes.labelcolor": INK2,
                         "xtick.color": INK2, "ytick.color": INK2, "axes.titlecolor": INK,
                         "figure.facecolor": SURFACE, "axes.facecolor": SURFACE})
    return plt


def _basemap(ax, view):
    x0, x1, y0, y1 = view
    for p in _land_polys():
        xs, ys = zip(*p)
        if max(xs) < x0 - 5 or min(xs) > x1 + 5 or max(ys) < y0 - 5 or min(ys) > y1 + 5:
            continue
        ax.fill(xs, ys, color="#e9e6df", lw=0, zorder=0)
        ax.plot(xs, ys, color=COAST, lw=0.35, zorder=3)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect(1.0)


def _cmap(colors):
    from matplotlib.colors import LinearSegmentedColormap
    return LinearSegmentedColormap.from_list("ramp", colors)


def _excess_layer(ax, fig, g, view, res, shrink=0.85, label="dB above baseline (0 or less = lightest)"):
    from matplotlib.collections import PolyCollection
    x0, x1, y0, y1 = view
    sel = [r for r in g.values() if noise_ok(r) and x0 - 3 <= r["lon"] <= x1 + 3 and y0 - 3 <= r["lat"] <= y1 + 3]
    polys, keep = _hex_polys([r["h3"] for r in sel])
    pc = PolyCollection(polys, array=np.clip([sel[i]["med_db"] for i in keep], 0, 4), cmap=_cmap(BLUES),
                        edgecolors="none", zorder=1)
    pc.set_clim(0, 4)
    ax.add_collection(pc)
    cb = fig.colorbar(pc, ax=ax, shrink=shrink, pad=0.01, ticks=[0, 1, 2, 3, 4])
    cb.set_label(label, color=INK2)
    cb.outline.set_visible(False)


def figure_day(day, g, ac, res, view=(15.0, 110.0, 0.0, 42.0)):
    """Three panels over the Middle East and South Asia: noise-floor excess, dropout share, aircraft share."""
    from matplotlib.collections import PolyCollection
    from matplotlib.patches import Patch
    plt = _plt()
    fig, axes = plt.subplots(3, 1, figsize=(8.6, 11.2), dpi=80)
    for ax in axes:
        _basemap(ax, view)
    _excess_layer(axes[0], fig, g, view, res)
    axes[0].set_title(f"(a) CYGNSS DDM noise-floor excess, {day} UTC, median per H3 res-{res} cell", loc="left")
    x0, x1, y0, y1 = view
    dsel = [r for r in g.values() if drop_ok(r) and x0 - 3 <= r["lon"] <= x1 + 3 and y0 - 3 <= r["lat"] <= y1 + 3]
    polys, keep = _hex_polys([r["h3"] for r in dsel])
    pc = PolyCollection(polys, array=[dsel[i]["dropout"] for i in keep], cmap=_cmap(ORANGES), edgecolors="none", zorder=1)
    pc.set_clim(0, 1)
    axes[1].add_collection(pc)
    cb = fig.colorbar(pc, ax=axes[1], shrink=0.85, pad=0.01, ticks=[0, 0.25, 0.5, 0.75, 1])
    cb.set_label("share of expected samples missing", color=INK2)
    cb.outline.set_visible(False)
    axes[1].set_title("(b) CYGNSS data dropouts, by sub-satellite point (cells with 30+ expected samples)", loc="left")
    acs = [(c, a) for c, a in ac.items() if a[0] >= 5]
    apolys, akeep = _hex_polys([c for c, _ in acs])
    share = np.array([100.0 * acs[i][1][1] / acs[i][1][0] for i in akeep])
    colors = np.where(share >= 10, AIR["red"], np.where(share >= 2, AIR["amber"], AIR["green"]))
    axes[2].add_collection(PolyCollection(apolys, facecolors=colors, edgecolors="none", zorder=1))
    axes[2].set_title(f"(c) Aircraft share degraded (ADS-B NACp), same day, res {res}, cells with 5+ aircraft", loc="left")
    axes[2].legend(handles=[Patch(color=AIR["green"], label="< 2%"), Patch(color=AIR["amber"], label="2–10%"),
                            Patch(color=AIR["red"], label="10% or more")], loc="lower left", frameon=True,
                   fontsize=7, title="share", title_fontsize=7)
    spacer = fig.colorbar(pc, ax=axes[2], shrink=0.85, pad=0.01)  # keeps the three maps the same width
    spacer.ax.set_visible(False)
    fig.text(0.01, 0.004, CREDIT, fontsize=6.5, color=INK2)
    fig.tight_layout(rect=(0, 0.015, 1, 1))
    _save(fig, f"cygnss_{day}_r{res}.png")


def figure_world(day, g, res):
    """The whole CYGNSS band for one day: where the noise floor is raised, including the quiet controls."""
    from matplotlib.patches import Rectangle
    plt = _plt()
    view = (-180.0, 180.0, -42.0, 42.0)
    fig, ax = plt.subplots(figsize=(11, 3.9), dpi=80)
    _basemap(ax, view)
    _excess_layer(ax, fig, g, view, res, shrink=0.75, label="dB above baseline")
    for kind, boxes in BOXES.items():
        for name, b in boxes.items():
            ax.add_patch(Rectangle((b[2], b[0]), b[3] - b[2], b[1] - b[0], fill=False, lw=0.8, zorder=4,
                                   ec=INK if kind == "known" else INK2, ls="-" if kind == "known" else "--"))
    ax.set_title(f"CYGNSS DDM noise-floor excess, {day} UTC, H3 res {res}, cells with 20+ DDMs\n"
                 "Solid boxes: regions with published interference reports. Dashed boxes: quiet controls.", loc="left")
    fig.text(0.01, 0.01, CREDIT, fontsize=6.5, color=INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    _save(fig, f"cygnss_world_{day}_r{res}.png")


def figure_box(xy, res):
    plt = _plt()
    bins = [(0, 2), (2, 5), (5, 10), (10, 25), (25, 101)]
    data = [[a for a, b in xy if lo <= b < hi] for lo, hi in bins]
    labels = [f"{lo}–{min(hi, 100)}%\n{len(d):,} cells" for (lo, hi), d in zip(bins, data)]
    fig, ax = plt.subplots(figsize=(6.4, 3.6), dpi=90)
    ax.boxplot(data, showfliers=False, widths=0.5, patch_artist=True,
               boxprops={"facecolor": BLUES[1], "edgecolor": BLUES[5], "linewidth": 1},
               whiskerprops={"color": BLUES[5]}, capprops={"color": BLUES[5]},
               medianprops={"color": BLUES[6], "linewidth": 2})
    ax.set_xticks(range(1, len(labels) + 1), labels)
    ax.axhline(ELEVATED_DB, color=INK2, lw=0.8, ls="--", zorder=0)
    ax.text(5.45, ELEVATED_DB + 0.08, "1 dB: elevated", ha="right", va="bottom", color=INK2, fontsize=7)
    ax.grid(axis="y", color="#ecebe7", lw=0.6, zorder=0)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.set_xlabel("aircraft share degraded in the cell (GPSJam-style, ADS-B NACp)")
    ax.set_ylabel("CYGNSS noise-floor excess, dB")
    ax.set_title(f"CYGNSS excess against aircraft share: H3 res-{res} cells with 20+ aircraft, six days pooled",
                 loc="left", fontsize=8.5)
    fig.tight_layout()
    _save(fig, f"cygnss_vs_aircraft_r{res}.png")


def figure_pass(day, sc, h0, h1, res=3):
    """One spacecraft's noise-floor excess per antenna along a pass, with the gaps in the L1 series shaded."""
    import h5py
    plt = _plt()
    d, ex = day_excess(day, res)
    m = (d["sc"] == sc) & (d["t"] >= h0 * 3600) & (d["t"] <= h1 * 3600) & np.isfinite(ex)
    fn = next(f for f in sorted(os.listdir(os.path.join(L1_DIR, day))) if f.startswith(f"cyg{sc:02d}"))
    with h5py.File(os.path.join(L1_DIR, day, fn), "r") as f:
        t = f["ddm_timestamp_utc"][...]
        sclat, sclon = f["sc_lat"][...], f["sc_lon"][...]
    sclon = np.where(sclon > 180, sclon - 360, sclon)
    fig, ax = plt.subplots(figsize=(7.6, 3.4), dpi=90)
    for ant, name, color in ((3, "port antenna", "#2a78d6"), (2, "starboard antenna", "#eb6834")):
        k = m & (d["ant"] == ant)
        tt, vv = d["t"][k], ex[k]
        ut, inv = np.unique(tt, return_inverse=True)
        med = np.array([np.median(vv[inv == i]) for i in range(len(ut))])
        # break the line across gaps so it doesn't bridge missing data
        y = med.copy()
        brk = np.where(np.diff(ut) > 30)[0]
        xs, ys = np.insert(ut / 3600, brk + 1, np.nan), np.insert(y, brk + 1, np.nan)
        ax.plot(xs, ys, color=color, lw=1.4, label=name)
    sel = (t >= h0 * 3600) & (t <= h1 * 3600)
    ts = t[sel]
    for i in np.where(np.diff(ts) > 30)[0]:
        a, b = ts[i] / 3600, ts[i + 1] / 3600
        j = np.where(t == ts[i])[0][0]
        ax.axvspan(a, b, color="#e4e3de", zorder=0)
        ax.text((a + b) / 2, 5.6, f"no L1 samples\n{(b - a) * 60:.1f} min", ha="center", va="top", color=INK2, fontsize=7)
        ax.text(a, -1.35, f"{sclat[j]:.0f}°N {sclon[j]:.0f}°E", ha="right", va="bottom", color=INK2, fontsize=6.5)
        ax.text(b, -1.35, f"{sclat[j + 1]:.0f}°N {sclon[j + 1]:.0f}°E", ha="left", va="bottom", color=INK2, fontsize=6.5)
    ax.axhline(0, color="#b5b4ae", lw=0.6)
    ax.set_ylim(-1.5, 6)
    ax.set_xlim(h0, h1)
    ticks = np.arange(np.ceil(h0 * 12) / 12, h1, 1 / 12)
    ax.set_xticks(ticks, [f"{int(x):02d}:{int(round((x % 1) * 60)) % 60:02d}" for x in ticks])
    ax.set_xlabel(f"UTC, {day} (labels at the gap edges: sub-satellite point)")
    ax.set_ylabel("noise-floor excess, dB")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(loc="upper left", frameon=False)
    ax.set_title(f"CYGNSS FM{sc:02d}, one pass: median excess per antenna, 1 s samples", loc="left", fontsize=8.5)
    fig.tight_layout()
    _save(fig, f"cygnss_pass_{day}_fm{sc:02d}.png")


def _save(fig, name):
    os.makedirs(IMG, exist_ok=True)
    out = os.path.join(IMG, name)
    fig.savefig(out, facecolor=SURFACE)
    import matplotlib.pyplot as plt
    plt.close(fig)
    try:  # palette PNG: a third of the size, no visible change for flat map colours
        from PIL import Image
        Image.open(out).convert("RGB").quantize(colors=128, method=Image.Quantize.MEDIANCUT).save(out, optimize=True)
    except ImportError:
        pass
    print(f"wrote {os.path.relpath(out, ROOT)} ({os.path.getsize(out) / 1e3:.0f} kB)")


# ---------------------------------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("fetch", "grid", "validate", "all", "pass"))
    ap.add_argument("days", nargs="+", help="UTC days, YYYY-MM-DD")
    ap.add_argument("--res", type=int, default=3, help="H3 resolution of the grid (default 3)")
    ap.add_argument("--stride", type=int, default=2, help="keep every n-th 0.5 s sample when fetching (default 2)")
    ap.add_argument("--figures", action="store_true", help="write PNGs to docs/validation/img/")
    ap.add_argument("--map-days", nargs="*", help="with --figures: days to map (default: all)")
    ap.add_argument("--out", help="validate: JSON path (default data/cygnss/validation_r<res>.json)")
    ap.add_argument("--sc", type=int, default=4, help="pass: spacecraft number (1-8)")
    ap.add_argument("--hours", type=float, nargs=2, default=(17.45, 17.85), help="pass: UTC window, decimal hours")
    a = ap.parse_args(argv)
    for d in a.days:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            raise SystemExit(f"bad day {d!r}")
    if a.cmd == "pass":
        figure_pass(a.days[0], a.sc, a.hours[0], a.hours[1], a.res)
        return
    if a.cmd in ("fetch", "all"):
        for d in a.days:
            fetch(d, a.stride)
    if a.cmd in ("grid", "all"):
        for d in a.days:
            grid(d, a.res)
    if a.cmd in ("validate", "all"):
        validate(a.days, a.res, a.figures, a.map_days, a.out)


if __name__ == "__main__":
    main()
