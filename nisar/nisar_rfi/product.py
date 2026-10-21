"""Read what the RFI watch needs from a NISAR GCOV (or RSLC) HDF5 product.

Works on a local file or a remote HTTPS URL (streamed with byte-range reads, so
only the layers we touch are transferred). Paths follow the NISAR L2 GCOV
product specification as encoded in isce3's product XML.
"""
import math
import re

import h5py
import numpy as np

ROOT = "/science/LSAR"
MB = 1024 * 1024


def _s(v):
    if isinstance(v, (bytes, np.bytes_)):
        return v.decode("utf-8", "replace").strip()
    if isinstance(v, np.ndarray):
        if v.dtype.kind in "SO":
            return [_s(x) for x in v.tolist()]
        return v.tolist()
    if isinstance(v, np.generic):
        return v.item()
    return v


def _get(h, path, default=None):
    try:
        return _s(h[path][()])
    except Exception:
        return default


def open_product(src, fs=None):
    """h5py.File for a local path, or for an HTTPS URL through an fsspec session."""
    kw = dict(rdcc_nbytes=256 * MB, rdcc_nslots=100003)
    if str(src).startswith(("http://", "https://")):
        if fs is None:
            raise RuntimeError("remote product needs an authenticated fsspec session (Earthdata login)")
        fobj = fs.open(src, mode="rb", block_size=16 * MB, cache_type="background")
        return h5py.File(fobj, "r", **kw)
    return h5py.File(src, "r", **kw)


def identification(h):
    ident = f"{ROOT}/identification"
    poly = _get(h, f"{ident}/boundingPolygon", "")
    pts = re.findall(r"(-?\d+\.?\d*)\s+(-?\d+\.?\d*)(?:\s+-?\d+\.?\d*)?", poly or "")
    start = _get(h, f"{ident}/zeroDopplerStartTime", "")
    end = _get(h, f"{ident}/zeroDopplerEndTime", "")
    direction = (_get(h, f"{ident}/orbitPassDirection", "") or "")[:1].upper()
    track, frame = _get(h, f"{ident}/trackNumber"), _get(h, f"{ident}/frameNumber")
    return {
        "granule": _get(h, f"{ident}/granuleId", ""),
        "product": _get(h, f"{ident}/productType", "GCOV"),
        "start": (start or "")[:19] + "Z",
        "end": (end or "")[:19] + "Z",
        "direction": direction,
        "track": int(track) if track is not None else 0,
        "frame": int(frame) if frame is not None else 0,
        "frequencies": _get(h, f"{ident}/listOfFrequencies", []) or [],
        "footprint": [[round(float(x), 5), round(float(y), 5)] for x, y in pts] or None,
        "crid": _get(h, f"{ident}/compositeReleaseId", ""),
    }


def rfi_metadata(h, product="GCOV"):
    """Processor RFI fields: per-channel rfiLikelihood (fraction of radar blocks the
    processor flagged), whether mitigation was applied, which algorithm, and
    whether a per-block RFI group (tone-rank results) is present."""
    base = f"{ROOT}/{product}"
    out = {"likelihood": {}, "mitigation_applied": None, "detection_algorithm": None,
           "mitigation_algorithm": None, "block_group": None}
    for f in ("A", "B"):
        cal = f"{base}/metadata/calibrationInformation/frequency{f}"
        if cal not in h:
            continue
        for pol in h[cal].keys():
            v = _get(h, f"{cal}/{pol}/rfiLikelihood")
            if v is not None and not (isinstance(v, float) and math.isnan(v)):
                out["likelihood"][f"{f}{pol}"] = round(float(v), 4)
    out["mitigation_applied"] = _get(h, f"{base}/metadata/processingInformation/parameters/rfiMitigationApplied")
    for k, p in (("detection_algorithm", "rfiDetection"), ("mitigation_algorithm", "rfiMitigation")):
        out[k] = (_get(h, f"{base}/metadata/sourceData/processingInformation/algorithms/{p}")
                  or _get(h, f"{base}/metadata/processingInformation/algorithms/{p}"))
    for p in (f"{base}/metadata/RFI", f"{ROOT}/RSLC/metadata/RFI"):
        if p in h:
            out["block_group"] = p
            break
    return out


def rfi_block_grid(h, group, freq="A", pol=None):
    """Per-block tone-rank RFI results if the product carries them (RSLC only, and only
    when the processor ran tone-rank): azimuth time x slant range ISR plus the
    fraction of pulses hit per frequency bin."""
    g = h[f"{group}/frequency{freq}"]
    pol = pol or sorted(g.keys())[0]
    g = g[pol]
    return {k: g[k][()] for k in ("nativeDopplerTime", "slantRange", "frequency",
                                   "interferenceSignalRatio", "hitCount", "signalMean") if k in g}


def list_rfi_paths(h, limit=80):
    """Every dataset/group whose name mentions RFI (for `inspect`)."""
    hits = []

    def visit(name, obj):
        if re.search(r"rfi", name, re.I) and len(hits) < limit:
            shape = getattr(obj, "shape", None)
            hits.append(f"/{name}" + (f"  shape={shape}" if shape is not None else "  (group)"))
    h[ROOT].visititems(lambda n, o: visit(f"science/LSAR/{n}", o))
    return hits


def block_mean(ds, factor):
    """Mean of positive finite samples in factor x factor blocks, streamed by row strips."""
    ny, nx = ds.shape
    nyb, nxb = ny // factor, nx // factor
    out = np.full((nyb, nxb), np.nan, np.float32)
    chunk_rows = ds.chunks[0] if ds.chunks else 512
    step = factor * max(1, math.ceil(chunk_rows / factor))
    for r0 in range(0, nyb * factor, step):
        r1 = min(r0 + step, nyb * factor)
        a = ds[r0:r1, : nxb * factor].astype(np.float32)
        a = a.reshape((r1 - r0) // factor, factor, nxb, factor)
        ok = np.isfinite(a) & (a > 0)
        n = ok.sum(axis=(1, 3))
        s = np.where(ok, a, 0).sum(axis=(1, 3))
        m = s / np.maximum(n, 1)
        m[n < 0.5 * factor * factor] = np.nan
        out[r0 // factor: r1 // factor] = m
    return out


def coarse_grid(h, freq, target_m=500.0, product="GCOV"):
    """Co- and cross-pol backscatter (dB) block-averaged to ~target_m, plus geotransform."""
    g = h[f"{ROOT}/{product}/grids/frequency{freq}"]
    pols = _s(g["listOfPolarizations"][()]) if "listOfPolarizations" in g else []
    if "HHHH" in g and "HVHV" in g:
        co, cx = "HHHH", "HVHV"
    elif "VVVV" in g and "VHVH" in g:
        co, cx = "VVVV", "VHVH"
    else:
        return None          # single-pol: no cross-pol channel, skip this frequency
    x = g["xCoordinates"][()]
    y = g["yCoordinates"][()]
    dx = float(_get(h, f"{g.name}/xCoordinateSpacing", x[1] - x[0]))
    dy = float(_get(h, f"{g.name}/yCoordinateSpacing", y[1] - y[0]))
    epsg = int(np.asarray(g["projection"][()]).item())
    k = max(1, int(round(target_m / abs(dx))))
    co_lin = block_mean(g[co], k)
    cx_lin = block_mean(g[cx], k)
    with np.errstate(divide="ignore", invalid="ignore"):
        co_db = (10 * np.log10(co_lin)).astype(np.float32)
        cx_db = (10 * np.log10(cx_lin)).astype(np.float32)
    return {
        "freq": freq, "pols": pols, "terms": [co, cx], "epsg": epsg,
        "x0": float(x[0] + (k - 1) / 2 * dx), "y0": float(y[0] + (k - 1) / 2 * dy),
        "dx": dx * k, "dy": dy * k, "factor": k, "native_spacing_m": abs(dx),
        "co_db": co_db, "cx_db": cx_db,
    }
