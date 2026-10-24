"""Sentinel-1 RFI board (prototype): C-band interference from the RFI annotation in Sentinel-1 Level-1 products.

Since IPF 3.40 (4 Nov 2021) every Sentinel-1 L1 product carries an RFI annotation data set (annotation/rfi/*.xml in
the SAFE) with the processor's own RFI pre-screening on noise pulses and, when mitigation runs, per-burst
time- and frequency-domain RFI reports. This tool reads only those small XML files, plus the end of the main
annotation file for geolocation and manifest.safe for the IPF version. It never reads the imagery.

Field meanings: Sentinel-1 Product Specification S1-RS-MDA-52-7441 issue 3.17.1 (30 Jul 2026), Tables 6-112 to
6-119; how to use them: SAR-MPC-0540 "Sentinel-1: Using the RFI annotations" v1.1 (31 May 2023).
See docs/validation/s1-rfi.md for the method and what it can and can't say.

Data sources (both anonymous apart from the token noted):
  pc   Microsoft Planetary Computer, collection sentinel-1-grd (default). Anonymous SAS token; per-file reads.
  asf  ASF DAAC SAFE zips, read by HTTP range requests into the remote zip. Needs EARTHDATA_TOKEN *and* the
       ASF Sentinel EULA accepted once on the Earthdata account (an owner action in a browser).
Copernicus Sentinel data are free for any use with attribution: "Contains modified Copernicus Sentinel data [year]".

Areas come from a private config (default private/watch/s1rfi.json, gitignored). Outputs that carry positions go
to private/s1rfi/<area>/; the raw annotation cache (public data, not tied to an area) goes to data/s1rfi/cache/.

Commands:
  python tools/s1_rfi.py search --area NAME [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--source pc|asf]
  python tools/s1_rfi.py fetch  --area NAME [--start ...] [--end ...] [--limit N] [--workers 6]
  python tools/s1_rfi.py sites  --area NAME
  python tools/s1_rfi.py map    --area NAME
  python tools/s1_rfi.py run    --area NAME|all      (search, fetch, sites, map)
  python tools/s1_rfi.py probe-asf SCENE_OR_URL       (list annotation/rfi entries in an ASF zip by range reads)
Times are stored in UTC; maps and KML show Central time with the zone named.
"""
import argparse
import bisect
import datetime as dt
import io
import json
import math
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "private", "watch", "s1rfi.json")
CACHE = os.path.join(ROOT, "data", "s1rfi", "cache")
OUT = os.path.join(ROOT, "private", "s1rfi")

PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
PC_SAS = "https://planetarycomputer.microsoft.com/api/sas/v1/token/{account}/{container}"
ASF_SEARCH = "https://api.daac.asf.alaska.edu/services/search/param"
UA = {"User-Agent": "noise-floor-s1rfi/0.1 (+https://github.com/metacog-osint/noise-floor)"}

# Defaults; the private config can override any of them under "detect" and "sites".
DETECT = {
    "td_lines_pct": 10.0,      # flag a burst when >= this % of its level-0 lines carry time-domain RFI
    "pers_blocks_pct": 1.0,    # ...or when >= this % of its processing blocks carry persistent (frequency-domain) RFI
    "iso_bw_pct": None,        # ...or (off by default) isolated RFI wider than this % of the bandwidth in some line
    "pols": None,              # None = any polarization; e.g. ["VV"] to use co-pol only
}
SITES = {
    "cell_deg": 0.05,          # accumulation grid
    "min_passes": 3,           # a site needs RFI on at least this many passes...
    "min_tracks": 2,           # ...from at least this many distinct geometries (relative orbit + direction)
    "min_frac": 0.3,           # ...and RFI on at least this share of the passes covering it
    "min_cover": 4,            # cells covered by fewer passes are not scored
    "min_score": 10.0,         # site score (median over geometries of mean affected-lines %) at the peak
    "min_prominence": 5.0,     # ...and this many points above the ring around it
    "min_prominence_ratio": 1.25,  # ...and this many times the ring (a region lit everywhere has no discrete sites)
    "radius_km": 30.0,         # one site per this radius (greedy, strongest first)
    "keep_frac": 0.8,          # cells within the radius scoring >= keep_frac * peak define the site position
    "max_sites": 50,
}
TAIL_BYTES = 170_000           # the geolocation grid and swath merge sit in the last ~130 kB of a GRD annotation


# ----------------------------------------------------------------------------------------------- small helpers
def utc(s):
    """ISO time from the annotation (no zone; UTC by definition) -> aware datetime."""
    s = s.strip().rstrip("Z")
    if "." in s:
        head, frac = s.split(".", 1)
        s = head + "." + (frac + "000000")[:6]
    return dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc)


def ts(s):
    return utc(s).timestamp()


def iso(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def central(t):
    """'2026-10-21 14:49 UTC (09:49 CDT)' for people."""
    from zoneinfo import ZoneInfo
    u = dt.datetime.fromtimestamp(t, dt.timezone.utc)
    c = u.astimezone(ZoneInfo("America/Chicago"))
    return "%s UTC (%s %s)" % (u.strftime("%Y-%m-%d %H:%M"), c.strftime("%H:%M"), c.tzname())


def km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, a)))


def _f(el, path, default=None):
    x = el.find(path)
    if x is None or x.text is None:
        return default
    try:
        return float(x.text)
    except ValueError:
        return default


def _t(el, path, default=None):
    x = el.find(path)
    return x.text.strip() if x is not None and x.text is not None else default


def norm_platform(name):
    """'sentinel-1c', 'SENTINEL-1A', 'Sentinel-1D' -> 'S1C' etc."""
    m = re.search(r"1([A-Da-d])", name or "")
    return "S1" + m.group(1).upper() if m else (name or "?")


def scrub(msg):
    """Drop query strings (SAS tokens, signed-URL signatures) from an error message before it is shown."""
    return re.sub(r"\?[^\s'\"]+", "?<redacted>", str(msg))


# ----------------------------------------------------------------------------------------------- parsers
def parse_rfi(text):
    """RFI annotation data set (PS Table 6-112) -> dict. Works for GRD (one file per polarization, all swaths) and
    SLC (one file per swath and polarization)."""
    root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    h = root.find("adsHeader")
    head = {k: _t(h, k) for k in ("missionId", "productType", "polarisation", "mode", "swath", "startTime",
                                  "stopTime", "absoluteOrbitNumber", "missionDataTakeId", "imageNumber")} if h is not None else {}
    noise = []
    for r in root.iter("rfiDetectionFromNoiseReport"):
        noise.append({
            "swath": _t(r, "swath"),
            "t": ts(_t(r, "noiseSensingTime")),
            "detected": (_t(r, "rfiDetected", "false").lower() == "true"),
            "max_kl": _f(r, "maxKLDivergence"),
            "max_fisher_z": _f(r, "maxFisherZ"),
            "max_rfi_psd": _f(r, "maxRfiPsd"),
        })
    bursts = []
    for r in root.iter("rfiBurstReport"):
        b = {"swath": _t(r, "swath"), "t0": ts(_t(r, "azimuthTime")),
             "in_out_ratio": _f(r, "inBandOutBandPowerRatio"),
             "td_lines_pct": None, "td_avg_samples_pct": None, "td_max_samples_pct": None,
             "iso_lines_pct": None, "iso_max_bw_pct": None, "pers_blocks_pct": None, "pers_max_bw_pct": None,
             "n_sub_blocks": None, "sub_block_size": None}
        td = r.find("timeDomainRfiReport")
        if td is not None:
            b["td_lines_pct"] = _f(td, "percentageAffectedLines")
            b["td_avg_samples_pct"] = _f(td, "avgPercentageAffectedSamples")
            b["td_max_samples_pct"] = _f(td, "maxPercentageAffectedSamples")
        fd = r.find("frequencyDomainRfiBurstReport")
        if fd is not None:
            b["n_sub_blocks"] = _f(fd, "numSubBlocks")
            b["sub_block_size"] = _f(fd, "subBlockSize")
            b["iso_lines_pct"] = _f(fd, "isolatedRfiReport/percentageAffectedLines")
            b["iso_max_bw_pct"] = _f(fd, "isolatedRfiReport/maxPercentageAffectedBW")
            b["pers_blocks_pct"] = _f(fd, "percentageBlocksPersistentRfi")
            b["pers_max_bw_pct"] = _f(fd, "maxPercentageBWAffectedPersistentRfi")
        bursts.append(b)
    return {"header": head, "mitigation": _t(root, "rfiMitigationApplied"), "noise": noise, "bursts": bursts,
            "has_block_reports": root.find("timeDomainRfiBlockReportList") is not None
            or root.find("frequencyDomainRfiBlockReportList") is not None}


def parse_manifest(text):
    """manifest.safe -> IPF version, mission, orbits, pass direction, footprint (lat, lon) list."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    out = {}
    m = re.search(r'<safe:software[^>]*name="Sentinel-1 IPF"[^>]*version="([^"]+)"', text) or \
        re.search(r'<safe:software[^>]*version="([^"]+)"[^>]*name="Sentinel-1 IPF"', text)
    out["ipf"] = m.group(1) if m else None
    for key, pat in (("abs_orbit", r'<safe:orbitNumber type="start">(\d+)<'),
                     ("rel_orbit", r'<safe:relativeOrbitNumber type="start">(\d+)<'),
                     ("direction", r"<s1:pass>(\w+)<"),
                     ("mission", r"<safe:familyName>SENTINEL-1</safe:familyName>\s*<safe:number>(\w+)<"),
                     ("product_type", r"<s1sarl1:productType>(\w+)<"),
                     ("mode", r"<s1sarl1:mode>(\w+)<")):
        m = re.search(pat, text)
        out[key] = m.group(1) if m else None
    for k in ("abs_orbit", "rel_orbit"):
        if out[k] is not None:
            out[k] = int(out[k])
    m = re.search(r"<gml:coordinates>([^<]+)</gml:coordinates>", text)
    fp = []
    if m:
        for pair in m.group(1).split():
            la, lo = pair.split(",")
            fp.append((float(la), float(lo)))
    out["footprint"] = fp
    return out


def geo_complete(data):
    """True when (a tail of) a main annotation holds the whole geolocation grid."""
    txt = data.decode("utf-8", "replace") if isinstance(data, bytes) else data
    return "<geolocationGrid>" in txt and "</geolocationGrid>" in txt


def _fragment(text, tag):
    i = text.find("<" + tag + ">")
    if i < 0:
        i = text.find("<" + tag + " ")
    j = text.find("</" + tag + ">")
    if i < 0 or j < 0:
        return None
    return ET.fromstring(text[i:j + len(tag) + 3])


class Geo:
    """Geolocation grid of one annotation file: (zero-Doppler azimuth time, image pixel) -> (lat, lon), bilinear,
    extrapolating linearly past the grid edges (bursts can start a second or two before a GRD slice)."""

    def __init__(self, points, swath_bounds=None, n_pixels=None):
        lines = sorted({p["line"] for p in points})
        pixels = sorted({p["pixel"] for p in points})
        idx = {(p["line"], p["pixel"]): p for p in points}
        if len(lines) < 2 or len(pixels) < 2 or len(idx) != len(lines) * len(pixels):
            raise ValueError("geolocation grid is not a complete lattice (%d lines x %d pixels, %d points)"
                             % (len(lines), len(pixels), len(idx)))
        self.pixels = [float(x) for x in pixels]
        self.times = [sum(idx[(ln, px)]["t"] for px in pixels) / len(pixels) for ln in lines]
        self.lat = [[idx[(ln, px)]["lat"] for px in pixels] for ln in lines]
        self.lon = [[idx[(ln, px)]["lon"] for px in pixels] for ln in lines]
        self.swath_bounds = swath_bounds or {}
        self.n_pixels = n_pixels or (pixels[-1] + 1)

    @staticmethod
    def _bracket(xs, x):
        i = bisect.bisect_right(xs, x) - 1
        i = max(0, min(len(xs) - 2, i))
        return i, (x - xs[i]) / (xs[i + 1] - xs[i])

    def latlon(self, t, p):
        i, wi = self._bracket(self.times, t)
        j, wj = self._bracket(self.pixels, p)

        def bil(a):
            return (a[i][j] * (1 - wi) * (1 - wj) + a[i + 1][j] * wi * (1 - wj)
                    + a[i][j + 1] * (1 - wi) * wj + a[i + 1][j + 1] * wi * wj)
        return bil(self.lat), bil(self.lon)

    def pixel_range(self, swath):
        if swath in self.swath_bounds:
            return self.swath_bounds[swath]
        return 0.0, float(self.n_pixels - 1)


def parse_geo(text):
    """Main annotation (whole file, or its tail from a range read) -> Geo. GRD: swath pixel bounds from
    swathMerging; SLC: the file is one swath, so the bounds are its whole pixel range."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    g = _fragment(text, "geolocationGrid")
    if g is None:
        raise ValueError("no geolocationGrid in annotation text")
    pts = []
    for p in g.iter("geolocationGridPoint"):
        pts.append({"t": ts(_t(p, "azimuthTime")), "line": int(_f(p, "line")), "pixel": int(_f(p, "pixel")),
                    "lat": _f(p, "latitude"), "lon": _f(p, "longitude")})
    bounds = {}
    sm = _fragment(text, "swathMerging")
    if sm is not None:
        for m in sm.iter("swathMerge"):
            sw = _t(m, "swath")
            lo, hi = [], []
            for b in m.iter("swathBounds"):
                lo.append(_f(b, "firstRangeSample"))
                hi.append(_f(b, "lastRangeSample"))
            if lo:
                bounds[sw] = (min(lo), max(hi))
    m = re.search(r"<numberOfSamples>(\d+)</numberOfSamples>", text)
    return Geo(pts, bounds, int(m.group(1)) if m else None)


# ----------------------------------------------------------------------------------------------- burst records
def burst_duration(bursts):
    """Median spacing between consecutive bursts of one swath (IW ~2.76 s). Falls back to 2.758 s."""
    by = {}
    for b in bursts:
        by.setdefault(b["swath"], []).append(b["t0"])
    d = []
    for v in by.values():
        v = sorted(set(round(x, 3) for x in v))
        d += [b - a for a, b in zip(v, v[1:]) if 0.5 < b - a < 6.0]
    if not d:
        return 2.758
    d.sort()
    return d[len(d) // 2]


def burst_records(rfi, geos, meta):
    """Per-burst rows with footprint. geos: {swath or '*': Geo}. meta: product facts (pass id, track, ...)."""
    rows = []
    dur = burst_duration(rfi["bursts"])
    pol = (rfi["header"].get("polarisation") or meta.get("pol") or "").upper()
    noise = rfi["noise"]
    for b in rfi["bursts"]:
        g = geos.get(b["swath"]) or geos.get("*")
        if g is None:
            continue
        t0, t1 = b["t0"], b["t0"] + dur
        p0, p1 = g.pixel_range(b["swath"])
        poly = [g.latlon(t0, p0), g.latlon(t0, p1), g.latlon(t1, p1), g.latlon(t1, p0)]
        c = g.latlon((t0 + t1) / 2, (p0 + p1) / 2)
        nz = [n for n in noise if n["swath"] == b["swath"] and t0 - 3.0 <= n["t"] <= t1 + 3.0]
        row = dict(meta)
        row.update(b)
        row.update({"pol": pol, "t1": t1, "lat": c[0], "lon": c[1], "poly": [[round(a, 5), round(o, 5)] for a, o in poly],
                    "mitigation": rfi["mitigation"],
                    "noise_detected": any(n["detected"] for n in nz),
                    "noise_max_psd": max([n["max_rfi_psd"] or 0.0 for n in nz], default=None)})
        rows.append(row)
    return rows


def flag(row, det=None):
    """True when the processor's own burst report shows RFI above the configured levels."""
    det = dict(DETECT, **(det or {}))
    if det.get("pols") and row.get("pol") not in det["pols"]:
        return False
    td, pb, bw = row.get("td_lines_pct"), row.get("pers_blocks_pct"), row.get("iso_max_bw_pct")
    if td is not None and det.get("td_lines_pct") is not None and td >= det["td_lines_pct"]:
        return True
    if pb is not None and det.get("pers_blocks_pct") is not None and pb >= det["pers_blocks_pct"]:
        return True
    if bw is not None and det.get("iso_bw_pct") is not None and bw >= det["iso_bw_pct"]:
        return True
    return False


def bw_pct(row):
    return max(row.get("iso_max_bw_pct") or 0.0, row.get("pers_max_bw_pct") or 0.0)


def dedupe(rows):
    """Adjacent GRD slices of one datatake repeat the bursts at their seam: keep one row per burst (the larger RFI)."""
    best = {}
    for r in rows:
        k = (r["pass"], r["pol"], r["swath"], round(r["t0"], 1))
        o = best.get(k)
        if o is None or (r.get("td_lines_pct") or 0) > (o.get("td_lines_pct") or 0):
            best[k] = r
    return list(best.values())


# ----------------------------------------------------------------------------------------------- sites
def _in_poly(lat, lon, poly):
    """Even-odd point-in-polygon on (lat, lon) arrays; poly is a list of (lat, lon). Vectorized with numpy."""
    import numpy as np
    inside = np.zeros(lat.shape, dtype=bool)
    n = len(poly)
    for i in range(n):
        y1, x1 = poly[i]
        y2, x2 = poly[(i + 1) % n]
        cond = ((y1 > lat) != (y2 > lat))
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
        inside ^= cond & (lon < xint)
    return inside


def track_of(row):
    """Geometry label: relative orbit plus A/D."""
    return "%s%s" % (row.get("rel_orbit"), (row.get("direction") or "?")[:1].upper())


def accumulate(rows, bbox, cell_deg, det=None):
    """Grid the area and back-project every pass's burst reports onto it.

    Per cell: passes covering it ('cover'), passes with a flagged burst over it ('hit', 'frac'), geometries, and
    the RFI level: per pass the largest time-domain affected-lines percentage of the bursts covering the cell
    (0 when the processor ran no burst-level detection), averaged per geometry. The site score is the median of
    those geometry means over the geometries covering the cell, so a cell scores high only where most geometries
    agree: the crossing of the stripes that one emitter leaves on passes from different directions. A stripe arm
    seen from one geometry only scores low."""
    import numpy as np
    import warnings
    det = dict(DETECT, **(det or {}))
    w, s, e, n = bbox
    nx, ny = max(1, int(round((e - w) / cell_deg))), max(1, int(round((n - s) / cell_deg)))
    lons = w + (np.arange(nx) + 0.5) * (e - w) / nx
    lats = s + (np.arange(ny) + 0.5) * (n - s) / ny
    LON, LAT = np.meshgrid(lons, lats)
    passes = {}
    for r in rows:
        passes.setdefault(r["pass"], []).append(r)

    def z():
        return np.zeros((ny, nx))
    g = {"lats": lats, "lons": lons, "bbox": bbox, "cell_deg": cell_deg,
         "cover": np.zeros((ny, nx), int), "hit": np.zeros((ny, nx), int),
         "td_sum": z(), "td_max": z(), "bw_max": z(), "psd_max": z(), "pass_info": {}}
    tsum, tcnt, thit = {}, {}, {}
    hit_sets = [[set() for _ in range(nx)] for _ in range(ny)]
    pol_sets = [[set() for _ in range(nx)] for _ in range(ny)]
    for pid, prs in sorted(passes.items()):
        cov = np.zeros((ny, nx), bool)
        hit = np.zeros((ny, nx), bool)
        val, bwm, psd = z(), z(), z()
        pols = {}
        for r in prs:
            if det.get("pols") and r.get("pol") not in det["pols"]:
                continue
            m = _in_poly(LAT, LON, r["poly"])
            if not m.any():
                continue
            cov |= m
            td = r.get("td_lines_pct") or 0.0
            val = np.where(m, np.maximum(val, td), val)
            if flag(r, det):
                hit |= m
                bwm = np.where(m, np.maximum(bwm, bw_pct(r)), bwm)
                psd = np.where(m, np.maximum(psd, r.get("noise_max_psd") or 0.0), psd)
                pols.setdefault(r["pol"], np.zeros((ny, nx), bool))
                pols[r["pol"]] |= m
        if not cov.any():
            continue
        tr = track_of(prs[0])
        g["pass_info"][pid] = {"t": min(r["t0"] for r in prs), "track": tr, "platform": prs[0].get("platform")}
        g["cover"] += cov
        g["hit"] += hit
        g["td_sum"] += val
        g["td_max"] = np.maximum(g["td_max"], np.where(hit, val, 0.0))
        g["bw_max"] = np.maximum(g["bw_max"], bwm)
        g["psd_max"] = np.maximum(g["psd_max"], psd)
        for d, v in ((tsum, val), (tcnt, cov.astype(float)), (thit, hit.astype(float))):
            d[tr] = d.get(tr, z()) + v
        for iy, ix in zip(*np.nonzero(hit)):
            hit_sets[iy][ix].add(pid)
            for p, pm in pols.items():
                if pm[iy, ix]:
                    pol_sets[iy][ix].add(p)
    tracks = sorted(tcnt)
    g["tracks"] = tracks
    if tracks:
        cnt = np.stack([tcnt[t] for t in tracks])
        gm = np.where(cnt > 0, np.stack([tsum[t] for t in tracks]) / np.maximum(cnt, 1), np.nan)
        hitk = np.stack([thit[t] for t in tracks]) > 0
        g["n_cover_tracks"] = (cnt > 0).sum(axis=0)
        g["n_hit_tracks"] = hitk.sum(axis=0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            med = np.nanmedian(gm, axis=0)
        g["score"] = np.where(g["n_cover_tracks"] >= 2, np.nan_to_num(med), 0.0)
    else:
        g["n_cover_tracks"] = np.zeros((ny, nx), int)
        g["n_hit_tracks"] = np.zeros((ny, nx), int)
        g["score"] = z()
    g["hit_sets"], g["pol_sets"] = hit_sets, pol_sets
    g["frac"] = np.where(g["cover"] > 0, g["hit"] / np.maximum(g["cover"], 1), 0.0)
    g["mean_td"] = np.where(g["cover"] > 0, g["td_sum"] / np.maximum(g["cover"], 1), 0.0)
    return g


def find_sites(g, cfg=None):
    """Greedy peak picking on the score grid: strongest eligible cell first, one site per radius_km. A peak must
    be persistent (min_passes, min_tracks, min_frac), reach min_score, and stand min_prominence above the median
    score of the ring radius_km..3*radius_km around it, so that a region lit everywhere doesn't tile into sites."""
    import numpy as np
    c = dict(SITES, **(cfg or {}))
    lats, lons = g["lats"], g["lons"]
    LON, LAT = np.meshgrid(lons, lats)
    covered = g["cover"] >= c["min_cover"]
    ok = ((g["hit"] >= c["min_passes"]) & (g["n_hit_tracks"] >= c["min_tracks"]) & (g["frac"] >= c["min_frac"])
          & covered & (g["n_cover_tracks"] >= 2) & (g["score"] >= c["min_score"]))
    score = np.where(ok, g["score"], -1.0)
    taken = np.zeros(score.shape, bool)
    sites, rejected = [], 0
    while len(sites) < c["max_sites"]:
        sc = np.where(taken, -1.0, score)
        k = int(np.argmax(sc))
        iy, ix = divmod(k, sc.shape[1])
        if sc[iy, ix] < 0:
            break
        plat, plon = lats[iy], lons[ix]
        d = 6371.0088 * 2 * np.arcsin(np.sqrt(np.sin(np.radians(LAT - plat) / 2) ** 2 + np.cos(np.radians(plat))
                                              * np.cos(np.radians(LAT)) * np.sin(np.radians(LON - plon) / 2) ** 2))
        near = d <= c["radius_km"]
        ring = covered & (d > c["radius_km"]) & (d <= 3 * c["radius_km"])
        bg = float(np.median(g["score"][ring])) if ring.sum() >= 10 else float(np.median(g["score"][covered]))
        peak = float(g["score"][iy, ix])
        core = near & ok & ~taken & (g["score"] >= c["keep_frac"] * peak)
        taken |= near
        if peak - bg < c["min_prominence"] or peak < c["min_prominence_ratio"] * bg:
            rejected += 1
            continue
        wts = np.where(core, g["score"], 0.0)
        lat = float((LAT * wts).sum() / wts.sum())
        lon = float((LON * wts).sum() / wts.sum())
        hp, pols = set(), set()
        for jy, jx in zip(*np.nonzero(core)):
            hp |= g["hit_sets"][jy][jx]
            pols |= g["pol_sets"][jy][jx]
        tr = sorted({g["pass_info"][p]["track"] for p in hp})
        times = sorted(g["pass_info"][p]["t"] for p in hp)
        ys, xs = np.nonzero(core)
        half = g["cell_deg"] / 2
        sites.append({
            "lat": round(lat, 4), "lon": round(lon, 4),
            "extent": [round(float(lons[xs.min()] - half), 3), round(float(lats[ys.min()] - half), 3),
                       round(float(lons[xs.max()] + half), 3), round(float(lats[ys.max()] + half), 3)],
            "score": round(peak, 2), "background": round(bg, 2), "frac": round(float(g["frac"][iy, ix]), 3),
            "n_passes": int(g["hit"][iy, ix]), "n_cover": int(g["cover"][iy, ix]), "n_passes_core": len(hp),
            "tracks": tr, "n_tracks": int(g["n_hit_tracks"][iy, ix]), "n_cover_tracks": int(g["n_cover_tracks"][iy, ix]),
            "first_seen": iso(times[0]) if times else None, "last_seen": iso(times[-1]) if times else None,
            "max_td_lines_pct": round(float(g["td_max"][core].max()), 2),
            "max_bw_pct": round(float(g["bw_max"][core].max()), 2),
            "max_noise_rfi_psd": round(float(g["psd_max"][core].max()), 2),
            "pols": sorted(pols), "n_cells": int(core.sum()),
            "edge": bool(xs.min() == 0 or ys.min() == 0 or xs.max() == len(lons) - 1 or ys.max() == len(lats) - 1),
        })
    for i, s in enumerate(sites, 1):
        s["id"] = "R%02d" % i
    g["n_rejected_peaks"] = rejected
    return sites


def cell_value(g, key, lat, lon):
    """Grid value at a point (None outside the grid)."""
    w, s, e, n = g["bbox"]
    if not (w <= lon <= e and s <= lat <= n):
        return None
    ix = min(len(g["lons"]) - 1, int((lon - w) / (e - w) * len(g["lons"])))
    iy = min(len(g["lats"]) - 1, int((lat - s) / (n - s) * len(g["lats"])))
    return float(g[key][iy, ix])


def percentile_rank(g, key, lat, lon):
    """Share of covered cells (cover >= min_cover) whose value is below the value at the point."""
    import numpy as np
    v = cell_value(g, key, lat, lon)
    if v is None:
        return None
    vals = g[key][g["cover"] >= SITES["min_cover"]]
    return float((vals < v).mean()) if vals.size else None


# ----------------------------------------------------------------------------------------------- network
def _requests():
    import requests
    s = requests.Session()
    s.headers.update(UA)
    return s


def earthdata_token():
    """EARTHDATA_TOKEN from the process, else from the Windows user environment. Never printed or stored."""
    tok = os.environ.get("EARTHDATA_TOKEN")
    if tok:
        return tok
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                return winreg.QueryValueEx(k, "EARTHDATA_TOKEN")[0]
        except OSError:
            pass
    raise SystemExit("EARTHDATA_TOKEN is not set (needed only for --source asf).")


class PC:
    """Planetary Computer: STAC search plus per-file blob reads with an anonymous SAS token."""

    def __init__(self):
        import threading
        self.s = _requests()
        self.tokens = {}
        self.lock = threading.Lock()

    def sas(self, account, container, refresh=False):
        k = (account, container)
        with self.lock:  # one token request for all worker threads (the endpoint rate-limits)
            if refresh or k not in self.tokens or self.tokens[k][1] < time.time() + 300:
                for attempt in range(6):
                    r = self.s.get(PC_SAS.format(account=account, container=container), timeout=60)
                    if r.status_code == 200:
                        break
                    if r.status_code != 429 or attempt == 5:
                        raise RuntimeError("Planetary Computer SAS token request failed: HTTP %d" % r.status_code)
                    time.sleep(5 * (attempt + 1))
                j = r.json()
                exp = utc(j["msft:expiry"]).timestamp() if j.get("msft:expiry") else time.time() + 3000
                self.tokens[k] = (j["token"], exp)
            return self.tokens[k][0]

    @staticmethod
    def split(href):
        m = re.match(r"https://([^.]+)\.blob\.core\.windows\.net/([^/]+)/(.+)", href)
        if not m:
            raise ValueError("not an Azure blob href")
        return m.group(1), m.group(2), m.group(3)

    def get(self, href, rng=None, _retry=True):
        acc, con, _ = self.split(href)
        h = {"Range": "bytes=%d-%d" % rng} if rng else {}
        for attempt in range(4):
            try:
                r = self.s.get(href + "?" + self.sas(acc, con), headers=h, timeout=90)
            except Exception as ex:  # network blip: retry, never echo the URL
                if attempt == 3:
                    raise RuntimeError("read failed: %s" % scrub(ex))
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 403 and _retry:
                self.sas(acc, con, refresh=True)
                _retry = False
                continue
            if r.status_code in (200, 206):
                return r.content
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(3 * (attempt + 1))
                continue
            raise RuntimeError("HTTP %d reading %s" % (r.status_code, href.rsplit("/", 3)[-3:]))
        raise RuntimeError("gave up reading %s" % href.rsplit("/", 2)[-2:])

    def size(self, href):
        acc, con, _ = self.split(href)
        r = self.s.head(href + "?" + self.sas(acc, con), timeout=60)
        if r.status_code != 200:
            raise RuntimeError("HTTP %d on HEAD" % r.status_code)
        return int(r.headers["Content-Length"])

    def list(self, base_href, prefix="annotation/"):
        acc, con, path = self.split(base_href)
        url = "https://%s.blob.core.windows.net/%s?restype=container&comp=list&prefix=%s/%s&%s" % (
            acc, con, path, prefix, self.sas(acc, con))
        r = self.s.get(url, timeout=60)
        if r.status_code != 200:
            raise RuntimeError("blob listing failed: HTTP %d" % r.status_code)
        names = re.findall(r"<Name>([^<]+)</Name>", r.text)
        return [n[len(path) + 1:] for n in names]

    def search(self, bbox, start, end):
        body = {"collections": ["sentinel-1-grd"], "bbox": bbox, "limit": 500,
                "datetime": "%sT00:00:00Z/%sT23:59:59Z" % (start, end)}
        out, url = [], PC_STAC + "/search"
        while url:
            r = self.s.post(url, json=body, timeout=120)
            if r.status_code != 200:
                raise RuntimeError("STAC search failed: HTTP %d" % r.status_code)
            j = r.json()
            out += j["features"]
            nxt = [l for l in j.get("links", []) if l.get("rel") == "next"]
            if not nxt:
                break
            url, body = nxt[0]["href"], nxt[0].get("body", body)
        prods = []
        for f in out:
            p = f["properties"]
            if p.get("sar:instrument_mode") not in ("IW", "EW"):
                continue
            prods.append({
                "id": f["id"], "source": "pc", "platform": norm_platform(p.get("platform", "")),
                "start": p.get("start_datetime") or p.get("datetime"), "end": p.get("end_datetime"),
                "rel_orbit": p.get("sat:relative_orbit"), "abs_orbit": p.get("sat:absolute_orbit"),
                "direction": p.get("sat:orbit_state"), "mode": p.get("sar:instrument_mode"),
                "pols": p.get("sar:polarizations"), "datatake": p.get("s1:datatake_id"),
                "base": f["assets"]["safe-manifest"]["href"].rsplit("/", 1)[0],
            })
        return prods


def pc_fetch(pc, prod, cdir):
    """Cache manifest, every rfi file and the tail of one main annotation for one PC product."""
    names = pc.list(prod["base"])
    rfi = [n for n in names if n.startswith("annotation/rfi/") and n.endswith(".xml")]
    main = [n for n in names if re.match(r"annotation/[^/]+\.xml$", n)]
    nbytes = 0
    data = pc.get(prod["base"] + "/manifest.safe")
    nbytes += len(data)
    _write(os.path.join(cdir, "manifest.safe"), data)
    for n in rfi:
        data = pc.get(prod["base"] + "/" + n)
        nbytes += len(data)
        _write(os.path.join(cdir, "rfi", os.path.basename(n)), data)
    # GRD geometry is the same for both polarizations: read the end of the first main annotation only.
    if main:
        href = prod["base"] + "/" + sorted(main)[0]
        size = pc.size(href)
        lo = max(0, size - TAIL_BYTES)
        data = pc.get(href, (lo, size - 1))
        if not geo_complete(data) and lo > 0:
            data = pc.get(href)
        nbytes += len(data)
        _write(os.path.join(cdir, "annot", os.path.basename(sorted(main)[0])), data)
    return nbytes, len(rfi)


# --- ASF: range reads into the remote SAFE zip
class AsfRefused(RuntimeError):
    """ASF said no. resolution_url (public Earthdata app-approval page) is set when the account still has to
    accept the ASF Sentinel EULA, which only the account owner can do, in a browser."""

    def __init__(self, msg, resolution_url=None):
        super().__init__(msg)
        self.resolution_url = resolution_url


class HttpRangeFile(io.RawIOBase):
    """Seekable read-only file over HTTP range requests, with a block cache, so zipfile can read the central
    directory and single members of a multi-GB remote zip. The signed URL is held in memory only."""

    def __init__(self, url, session, headers_for, block=256 * 1024):
        self.s, self.block, self.cache, self.pos = session, block, {}, 0
        self.nbytes = self.nreq = 0
        from urllib.parse import urljoin, urlparse
        u = url
        for _ in range(10):
            h = {"Range": "bytes=0-0"}
            h.update(headers_for(urlparse(u).hostname or ""))
            r = self.s.get(u, headers=h, allow_redirects=False, timeout=60)
            if r.status_code in (301, 302, 303, 307, 308):
                u = urljoin(u, r.headers["Location"])
                continue
            if r.status_code == 206:
                self.size = int(r.headers["Content-Range"].split("/")[1])
                self.url = u
                return
            detail, fix = "", None
            try:
                j = r.json()
                detail = "%s: %s" % (j.get("error", ""), j.get("error_description", ""))
                fix = j.get("resolution_url") if "EULA" in detail else None
            except Exception:
                pass
            raise AsfRefused("ASF download refused: HTTP %d %s" % (r.status_code, detail), fix)
        raise RuntimeError("too many redirects")

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def _blk(self, i):
        if i not in self.cache:
            a = i * self.block
            b = min(self.size, a + self.block) - 1
            r = self.s.get(self.url, headers={"Range": "bytes=%d-%d" % (a, b)}, timeout=90)
            if r.status_code != 206:
                raise RuntimeError("range read failed: HTTP %d" % r.status_code)
            self.cache[i] = r.content
            self.nbytes += len(r.content)
            self.nreq += 1
        return self.cache[i]

    def readinto(self, buf):
        if self.pos >= self.size:
            return 0
        n = min(len(buf), self.size - self.pos)
        out, p = bytearray(), self.pos
        while len(out) < n:
            i = p // self.block
            d = self._blk(i)
            take = d[p - i * self.block:p - i * self.block + (n - len(out))]
            out += take
            p += len(take)
        buf[:n] = out
        self.pos = p
        return n


def asf_open(url):
    tok = earthdata_token()

    def hdr(host):
        # The bearer token goes only to ASF and Earthdata Login hosts, never to the signed storage URL.
        if host.endswith(".asf.alaska.edu") or host == "urs.earthdata.nasa.gov":
            return {"Authorization": "Bearer " + tok}
        return {}
    f = HttpRangeFile(url, _requests(), hdr)
    return f, zipfile.ZipFile(io.BufferedReader(f, buffer_size=64 * 1024))


def asf_search(bbox, start, end, level="GRD_HD"):
    s = _requests()
    w, so, e, n = bbox
    r = s.get(ASF_SEARCH, params={"platform": "Sentinel-1", "processingLevel": level, "beamMode": "IW",
                                  "bbox": "%s,%s,%s,%s" % (w, so, e, n), "start": start + "T00:00:00Z",
                                  "end": end + "T23:59:59Z", "output": "geojson", "maxResults": 2000}, timeout=120)
    if r.status_code != 200:
        raise RuntimeError("ASF search failed: HTTP %d" % r.status_code)
    prods = []
    for f in r.json()["features"]:
        p = f["properties"]
        prods.append({"id": p["sceneName"], "source": "asf", "platform": norm_platform(p["platform"]),
                      "start": p["startTime"], "end": p["stopTime"], "rel_orbit": p.get("pathNumber"),
                      "abs_orbit": p.get("orbit"), "direction": (p.get("flightDirection") or "").lower(),
                      "mode": "IW", "pols": p.get("polarization"), "url": p["url"], "bytes": p.get("bytes")})
    return prods


def asf_fetch(prod, cdir):
    f, z = asf_open(prod["url"])
    names = z.namelist()
    rfi = [n for n in names if "/annotation/rfi/" in n and n.endswith(".xml")]
    main = [n for n in names if re.search(r"/annotation/[^/]+\.xml$", n)]
    man = [n for n in names if n.endswith("manifest.safe")]
    for n in man:
        _write(os.path.join(cdir, "manifest.safe"), z.read(n))
    for n in rfi:
        _write(os.path.join(cdir, "rfi", os.path.basename(n)), z.read(n))
    # SLC: one main annotation per swath (geometry is pol-independent: take one polarization); GRD: one file.
    pol0 = None
    for n in sorted(main):
        m = re.search(r"-(vv|vh|hh|hv)-", os.path.basename(n))
        pol0 = pol0 or (m.group(1) if m else None)
        if m and m.group(1) != pol0:
            continue
        _write(os.path.join(cdir, "annot", os.path.basename(n)), z.read(n))
    return f.nbytes, len(rfi)


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


# ----------------------------------------------------------------------------------------------- product -> rows
def product_rows(prod, cdir=None):
    """Parse one cached product into burst rows (empty if it has no RFI annotation)."""
    cdir = cdir or os.path.join(CACHE, prod["id"])
    man = parse_manifest(open(os.path.join(cdir, "manifest.safe"), "rb").read())
    adir, rdir = os.path.join(cdir, "annot"), os.path.join(cdir, "rfi")
    if not os.path.isdir(rdir) or not os.path.isdir(adir):
        return [], man
    geos = {}
    for fn in os.listdir(adir):
        try:
            g = parse_geo(open(os.path.join(adir, fn), "rb").read())
        except ValueError as ex:
            print("  skip %s: %s" % (prod["id"], ex))
            return [], man
        m = re.search(r"(?:^|-)(iw[1-3]|ew[1-5]|s[1-6])-", fn)
        geos[m.group(1).upper() if m else "*"] = g
    plat = prod.get("platform") or ("S1" + (man.get("mission") or "?"))
    meta = {"product": prod["id"], "platform": plat, "pass": "%s_%s" % (plat, prod.get("abs_orbit") or man.get("abs_orbit")),
            "rel_orbit": prod.get("rel_orbit") or man.get("rel_orbit"),
            "direction": (prod.get("direction") or man.get("direction") or "").lower(), "ipf": man.get("ipf")}
    rows = []
    for fn in sorted(os.listdir(rdir)):
        rfi = parse_rfi(open(os.path.join(rdir, fn), "rb").read())
        rows += burst_records(rfi, geos, meta)
    return rows, man


# ----------------------------------------------------------------------------------------------- commands
def load_config(path):
    if not os.path.exists(path):
        raise SystemExit("no config at %s (private; see docs/validation/s1-rfi.md for the shape)" % path)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def area_cfg(cfg, name):
    if name not in cfg["areas"]:
        raise SystemExit("unknown area %r; configured: %s" % (name, ", ".join(cfg["areas"])))
    a = dict(cfg.get("defaults", {}))
    a.update(cfg["areas"][name])
    a["name"] = name
    return a


def odir(name):
    d = os.path.join(OUT, name)
    os.makedirs(d, exist_ok=True)
    return d


def cmd_search(cfg, name, args):
    a = area_cfg(cfg, name)
    start, end = args.start or a.get("start"), args.end or a.get("end")
    src = args.source or a.get("source", "pc")
    prods = PC().search(a["bbox"], start, end) if src == "pc" else asf_search(a["bbox"], start, end)
    prods.sort(key=lambda p: p["start"])
    with open(os.path.join(odir(name), "products.json"), "w", encoding="utf-8") as fh:
        json.dump({"area": name, "source": src, "start": start, "end": end, "products": prods}, fh, indent=1)
    plats = {}
    for p in prods:
        plats[p["platform"]] = plats.get(p["platform"], 0) + 1
    tracks = sorted({"%s%s" % (p["rel_orbit"], (p["direction"] or "?")[:1].upper()) for p in prods})
    print("%s: %d products %s to %s from %s; platforms %s; geometries %s" % (
        name, len(prods), start, end, src, plats, " ".join(tracks)))
    return prods


def cmd_fetch(cfg, name, args):
    from concurrent.futures import ThreadPoolExecutor
    pj = os.path.join(odir(name), "products.json")
    if not os.path.exists(pj):
        cmd_search(cfg, name, args)
    prods = json.load(open(pj, encoding="utf-8"))["products"]
    if args.limit:
        prods = prods[:args.limit]
    todo = [p for p in prods if not os.path.exists(os.path.join(CACHE, p["id"], "done"))]
    pc = PC()
    stats = {"bytes": 0, "ok": 0, "fail": 0, "no_rfi": 0}

    def one(p):
        cdir = os.path.join(CACHE, p["id"])
        try:
            nb, nr = pc_fetch(pc, p, cdir) if p["source"] == "pc" else asf_fetch(p, cdir)
            _write(os.path.join(cdir, "meta.json"), json.dumps(p).encode())
            _write(os.path.join(cdir, "done"), b"")
            return nb, nr, None
        except Exception as ex:
            return 0, 0, scrub(ex)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for p, (nb, nr, err) in zip(todo, ex.map(one, todo)):
            if err:
                stats["fail"] += 1
                print("  fail %s: %s" % (p["id"], err))
                continue
            stats["ok"] += 1
            stats["bytes"] += nb
            stats["no_rfi"] += (nr == 0)
    print("%s: fetched %d products (%d already cached, %d failed, %d without RFI annotation), %.1f MB in %.0f s" % (
        name, stats["ok"], len(prods) - len(todo), stats["fail"], stats["no_rfi"], stats["bytes"] / 1e6, time.time() - t0))
    return stats


def area_rows(name):
    pj = os.path.join(odir(name), "products.json")
    prods = json.load(open(pj, encoding="utf-8"))["products"]
    rows, info = [], {"products": 0, "no_rfi": 0, "missing": 0, "ipf": {}, "platforms": {}, "mitigation": {}}
    for p in prods:
        cdir = os.path.join(CACHE, p["id"])
        if not os.path.exists(os.path.join(cdir, "done")):
            info["missing"] += 1
            continue
        r, man = product_rows(p, cdir)
        info["products"] += 1
        info["ipf"][man.get("ipf")] = info["ipf"].get(man.get("ipf"), 0) + 1
        info["platforms"][p["platform"]] = info["platforms"].get(p["platform"], 0) + 1
        if not r:
            info["no_rfi"] += 1
        for x in r:
            info["mitigation"][x["mitigation"]] = info["mitigation"].get(x["mitigation"], 0) + 1
        rows += r
    return dedupe(rows), info


def cmd_sites(cfg, name, args):
    a = area_cfg(cfg, name)
    det = dict(DETECT, **cfg.get("detect", {}), **a.get("detect", {}))
    sc = dict(SITES, **cfg.get("sites", {}), **a.get("sites", {}))
    rows, info = area_rows(name)
    g = accumulate(rows, a["bbox"], sc["cell_deg"], det)
    sites = find_sites(g, sc)
    flagged = [r for r in rows if flag(r, det)]
    passes = {r["pass"] for r in rows}
    fpasses = {r["pass"] for r in flagged}
    refs = []
    for ref in a.get("reference_sites", []):
        d = [(km(ref["lat"], ref["lon"], s["lat"], s["lon"]), s["id"]) for s in sites]
        d.sort()
        refs.append({"name": ref["name"], "nearest_site": d[0][1] if d else None,
                     "km": round(d[0][0], 1) if d else None,
                     "frac": cell_value(g, "frac", ref["lat"], ref["lon"]),
                     "score": cell_value(g, "score", ref["lat"], ref["lon"]),
                     "cover": cell_value(g, "cover", ref["lat"], ref["lon"]),
                     "frac_pct_rank": percentile_rank(g, "frac", ref["lat"], ref["lon"]),
                     "score_pct_rank": percentile_rank(g, "score", ref["lat"], ref["lon"])})
    covered = g["cover"] >= sc["min_cover"]
    import numpy as np
    LON, LAT = np.meshgrid(g["lons"], g["lats"])
    near_any = np.zeros(covered.shape, bool)
    for st in sites:
        near_any |= (6371.0088 * 2 * np.arcsin(np.sqrt(np.sin(np.radians(LAT - st["lat"]) / 2) ** 2 + np.cos(np.radians(st["lat"]))
                     * np.cos(np.radians(LAT)) * np.sin(np.radians(LON - st["lon"]) / 2) ** 2))) <= sc["radius_km"]
    chance = float(near_any[covered].mean()) if covered.any() else None
    summary = {
        "area": name, "role": a.get("role"), "made": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "detect": det, "sites_cfg": sc, "info": info,
        "n_passes": len(passes), "n_passes_with_rfi": len(fpasses), "n_bursts": len(rows), "n_bursts_flagged": len(flagged),
        "flagged_share": round(len(flagged) / len(rows), 4) if rows else None,
        "pols": sorted({r["pol"] for r in rows}),
        "median_frac_covered": float(__import__("numpy").median(g["frac"][covered])) if covered.any() else None,
        "n_sites": len(sites), "n_rejected_peaks": g.get("n_rejected_peaks"),
        "chance_within_radius": chance, "sites": sites, "reference": refs,
        "attribution": "Contains modified Copernicus Sentinel data %s" % "-".join(sorted({r["product"][17:21] for r in rows})) if rows else None,
    }
    d = odir(name)
    with open(os.path.join(d, "sites.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1)
    with open(os.path.join(d, "bursts.jsonl"), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps({k: (iso(v) if k in ("t0", "t1") else v) for k, v in r.items()}) + "\n")
    _save_grid(g, os.path.join(d, "grid.npz"))
    print("%s: %d passes (%d with RFI), %d bursts (%d flagged, %.1f%%), %d sites (%s peaks not prominent); "
          "chance a point is within %.0f km of a site %s; IPF %s; platforms %s" % (
              name, len(passes), len(fpasses), len(rows), len(flagged), 100.0 * len(flagged) / max(1, len(rows)),
              len(sites), g.get("n_rejected_peaks"), sc["radius_km"], _r(chance), info["ipf"], info["platforms"]))
    for s in sites[:15]:
        print("  %s %.3f,%.3f  score %.1f (ring %.1f)  passes %d/%d  tracks %s  frac %.2f  td<=%.0f%%  bw<=%.0f%%  %s  %s..%s%s" % (
            s["id"], s["lat"], s["lon"], s["score"], s["background"], s["n_passes"], s["n_cover"], ",".join(s["tracks"]), s["frac"],
            s["max_td_lines_pct"], s["max_bw_pct"], "/".join(s["pols"]), (s["first_seen"] or "")[:10],
            (s["last_seen"] or "")[:10], " (edge)" if s["edge"] else ""))
    for r in refs:
        print("  reference %s: nearest %s at %s km; frac %s (rank %s), score %s (rank %s), cover %s" % (
            r["name"], r["nearest_site"], r["km"], _r(r["frac"]), _r(r["frac_pct_rank"]), _r(r["score"]),
            _r(r["score_pct_rank"]), r["cover"]))
    return summary, g


def _r(x):
    return None if x is None else round(x, 2)


def _save_grid(g, path):
    import numpy as np
    np.savez_compressed(path, **{k: g[k] for k in ("lats", "lons", "cover", "hit", "frac", "score", "mean_td",
                                                    "n_cover_tracks", "n_hit_tracks", "td_max", "bw_max")},
                        bbox=np.array(g["bbox"]), cell_deg=np.array(g["cell_deg"]))


def _land(bbox):
    """Coastlines and borders for the quicklook, from the NISAR lane's bundled Natural Earth assets (read only)."""
    import gzip
    out = []
    for fn in ("land.geojson.gz", "borders.geojson.gz"):
        p = os.path.join(ROOT, "nisar", "nisar_rfi", "assets", fn)
        if not os.path.exists(p):
            continue
        gj = json.load(gzip.open(p, "rt", encoding="utf-8"))
        for f in gj.get("features", []):
            geom = f["geometry"]
            polys = []
            if geom["type"] == "Polygon":
                polys = geom["coordinates"]
            elif geom["type"] == "MultiPolygon":
                polys = [r for poly in geom["coordinates"] for r in poly]
            elif geom["type"] == "LineString":
                polys = [geom["coordinates"]]
            elif geom["type"] == "MultiLineString":
                polys = geom["coordinates"]
            for ring in polys:
                xs = [c[0] for c in ring]
                ys = [c[1] for c in ring]
                if max(xs) < bbox[0] - 1 or min(xs) > bbox[2] + 1 or max(ys) < bbox[1] - 1 or min(ys) > bbox[3] + 1:
                    continue
                out.append((xs, ys))
    return out


def cmd_map(cfg, name, args):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    a = area_cfg(cfg, name)
    d = odir(name)
    sj = json.load(open(os.path.join(d, "sites.json"), encoding="utf-8"))
    z = np.load(os.path.join(d, "grid.npz"))
    w, s, e, n = a["bbox"]
    fig, axes = plt.subplots(1, 2, figsize=(13, 6.2), constrained_layout=True)
    smax = max(20.0, float(np.nanmax(z["score"])) if z["score"].size else 20.0)
    for ax, key, title, cmap, vmax in (
            (axes[0], "frac", "Share of passes with a flagged RFI burst", "magma", 1.0),
            (axes[1], "score", "Site score: median over geometries of mean %% lines with RFI", "viridis", smax)):
        v = np.ma.masked_where(z["cover"] < SITES["min_cover"], z[key])
        im = ax.pcolormesh(z["lons"], z["lats"], v, cmap=cmap, vmin=0, vmax=vmax, shading="nearest")
        fig.colorbar(im, ax=ax, shrink=0.8)
        for xs, ys in _land(a["bbox"]):
            ax.plot(xs, ys, color="#9aa3ad", lw=0.6)
        for st in sj["sites"]:
            ax.plot(st["lon"], st["lat"], "o", mfc="none", mec="#00e5ff", ms=11, mew=1.6)
            ax.annotate(st["id"], (st["lon"], st["lat"]), xytext=(5, 5), textcoords="offset points", color="#00e5ff", fontsize=8)
        for ref in a.get("reference_sites", []):
            ax.plot(ref["lon"], ref["lat"], "*", color="#ff3b30", ms=12, mec="white", mew=0.6)
        ax.set_xlim(w, e)
        ax.set_ylim(s, n)
        ax.set_aspect(1 / math.cos(math.radians((s + n) / 2)))
        ax.set_title(title, fontsize=10)
    fig.suptitle("Sentinel-1 RFI annotation, %s: %d passes, %d with RFI, %d sites (cyan); stars = reference sites\n"
                 "%s. Private watch output." % (name, sj["n_passes"], sj["n_passes_with_rfi"], sj["n_sites"],
                                                sj.get("attribution") or "Contains modified Copernicus Sentinel data"),
                 fontsize=10)
    png = os.path.join(d, "%s_quicklook.png" % name)
    fig.savefig(png, dpi=110)
    plt.close(fig)
    kml = os.path.join(d, "%s_sites.kml" % name)
    with open(kml, "w", encoding="utf-8") as fh:
        fh.write(kml_doc(name, sj))
    print("%s: wrote %s and %s" % (name, os.path.relpath(png, ROOT), os.path.relpath(kml, ROOT)))


def kml_doc(name, sj):
    from xml.sax.saxutils import escape
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
           "<name>S1 RFI sites: %s</name>" % escape(name),
           "<description>%s</description>" % escape((sj.get("attribution") or "") + ". Private watch output. Every site is a lead, not an attribution."),
           '<Style id="site"><IconStyle><color>ffffe500</color><scale>1.1</scale></IconStyle>'
           '<LineStyle><color>ffffe500</color><width>2</width></LineStyle><PolyStyle><color>33ffe500</color></PolyStyle></Style>']
    for st in sj["sites"]:
        def when(x):
            return central(utc(x).timestamp()) if x else "?"
        desc = ("RFI on %d of %d passes covering the peak; geometries %s (%d of %d covering); first %s; last %s; "
                "max time-domain affected lines %.1f%%; max affected bandwidth %.1f%%; max noise RFI PSD %.1f; "
                "polarizations %s; extent %s" % (st["n_passes"], st["n_cover"], ", ".join(st["tracks"]), st["n_tracks"],
                                                 st["n_cover_tracks"], when(st["first_seen"]), when(st["last_seen"]),
                                                 st["max_td_lines_pct"], st["max_bw_pct"], st["max_noise_rfi_psd"],
                                                 "/".join(st["pols"]), st["extent"]))
        w, s, e, n = st["extent"]
        out.append('<Placemark><name>%s</name><styleUrl>#site</styleUrl><description>%s</description>'
                   '<MultiGeometry><Point><coordinates>%.5f,%.5f,0</coordinates></Point>'
                   '<Polygon><outerBoundaryIs><LinearRing><coordinates>%.4f,%.4f,0 %.4f,%.4f,0 %.4f,%.4f,0 %.4f,%.4f,0 %.4f,%.4f,0'
                   '</coordinates></LinearRing></outerBoundaryIs></Polygon></MultiGeometry></Placemark>' % (
                       escape(st["id"]), escape(desc), st["lon"], st["lat"], w, s, e, s, e, n, w, n, w, s))
    out.append("</Document></kml>")
    return "\n".join(out)


def cmd_probe_asf(arg):
    url = arg if arg.startswith("http") else None
    if url is None:
        r = _requests().get(ASF_SEARCH, params={"granule_list": arg, "output": "geojson"}, timeout=60)
        feats = [f for f in r.json()["features"] if f["properties"]["sceneName"] == arg]
        if not feats:
            raise SystemExit("scene not found at ASF: %s" % arg)
        url = feats[0]["properties"]["url"]
    t0 = time.time()
    try:
        f, z = asf_open(url)
    except RuntimeError as ex:
        print("ASF route: %s" % scrub(ex))
        if getattr(ex, "resolution_url", None) and ex.resolution_url.startswith("https://urs.earthdata.nasa.gov/approve_app"):
            print("  The account owner accepts the EULA once at: %s" % ex.resolution_url)
        return 2
    names = z.namelist()
    rfi = [n for n in names if "/annotation/rfi/" in n]
    print("zip %.2f GB, %d entries; central directory read with %d range requests (%.0f kB)" % (
        f.size / 1e9, len(names), f.nreq, f.nbytes / 1e3))
    for n in rfi:
        print("  %s  %d bytes" % (n.split("/", 1)[1], z.getinfo(n).file_size))
    man = [n for n in names if n.endswith("manifest.safe")]
    if man:
        print("  IPF %s" % parse_manifest(z.read(man[0])).get("ipf"))
    print("read %.0f kB in %d requests, %.1f s" % (f.nbytes / 1e3, f.nreq, time.time() - t0))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=["search", "fetch", "sites", "map", "run", "probe-asf"])
    ap.add_argument("target", nargs="?", help="probe-asf: scene name or URL")
    ap.add_argument("--area", help="area name from the config, or 'all'")
    ap.add_argument("--config", default=CONFIG)
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--source", choices=["pc", "asf"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args(argv)
    if args.command == "probe-asf":
        return cmd_probe_asf(args.target)
    cfg = load_config(args.config)
    names = list(cfg["areas"]) if args.area in (None, "all") else [args.area]
    for name in names:
        if args.command in ("search", "run"):
            cmd_search(cfg, name, args)
        if args.command in ("fetch", "run"):
            cmd_fetch(cfg, name, args)
        if args.command in ("sites", "run"):
            cmd_sites(cfg, name, args)
        if args.command in ("map", "run"):
            cmd_map(cfg, name, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
