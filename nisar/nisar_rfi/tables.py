"""Tier 1 of the screen: the processor's per-block RFI tables in NISAR RSLC products.

When the RSLC processor runs tone-rank (PROVISIONAL products), it writes, for every raw
data segment, a grid of analysis blocks (azimuth time x slant range) with:
  interferenceSignalRatio  RFI power / signal power per block (linear)
  signalMean               estimated signal power per block (linear, DN^2)
  hitCount                 fraction of pulses with RFI detected, per block and frequency bin
  frequency                frequency axis for hitCount (Hz, RF)
Source: isce3 `isce3/signal/rfi_tone_rank.py` (`remove_loud_tones`, `write_tone_rank_results`)
and `nisar/workflows/focus.py` (group `metadata/RFI/frequency{A,B}/{pol}/raw{t:05.0f}`).

These tables are computed on the raw data before mitigation, so the image filter can't
hide what they record, and they are small next to the image (tens of MB against GB).
"""
import numpy as np

ROOT = "/science/LSAR/RSLC"
RFI = f"{ROOT}/metadata/RFI"


def rslc_name(gcov_granule):
    """RSLC granule name for a GCOV granule (same acquisition, same naming otherwise)."""
    return gcov_granule.replace("_L2_PR_GCOV_", "_L1_PR_RSLC_").replace("_L2_GCOV_", "_L1_RSLC_")


def read_orbit(h):
    """Orbit state vectors (ECEF, m and m/s) and their time axis (s since the file's epoch)."""
    g = h[f"{ROOT}/metadata/orbit"]
    t = g["time"][()].astype(float)
    units = g["time"].attrs.get("units", b"")
    units = units.decode() if isinstance(units, bytes) else str(units)
    return {"t": t, "pos": g["position"][()].astype(float), "vel": g["velocity"][()].astype(float), "units": units}


def read_tables(h, freqs=("A", "B"), pols=None, with_hits=True):
    """{(freq, pol): {"t": (n_az,), "r": (n_rg,), "isr": (n_az, n_rg), "mean": (n_az, n_rg),
    "f": (n_bins,), "hits": (n_az, n_rg, n_bins) or None}} with raw segments stacked in time.
    Returns {} when the product has no tone-rank tables."""
    out = {}
    if RFI not in h:
        return out
    for fr in freqs:
        gf = f"{RFI}/frequency{fr}"
        if gf not in h:
            continue
        for pol in sorted(h[gf].keys()):
            if pols and pol not in pols:
                continue
            segs = [h[f"{gf}/{pol}/{k}"] for k in sorted(h[f"{gf}/{pol}"].keys())]
            segs = [s for s in segs if "interferenceSignalRatio" in s]
            if not segs:
                continue
            r = segs[0]["slantRange"][()].astype(float)
            # segments can differ in range-block count; keep the common length
            n_rg = min(s["slantRange"].shape[0] for s in segs)
            t = np.concatenate([s["nativeDopplerTime"][()].astype(float) for s in segs])
            isr = np.concatenate([s["interferenceSignalRatio"][:, :n_rg] for s in segs]).astype(np.float32)
            mean = np.concatenate([s["signalMean"][:, :n_rg] for s in segs]).astype(np.float32)
            f = segs[0]["frequency"][()].astype(float)
            hits = (np.concatenate([s["hitCount"][:, :n_rg, :] for s in segs]).astype(np.float16)
                    if with_hits else None)
            out[(fr, pol)] = {"t": t, "r": r[:n_rg], "isr": isr, "mean": mean, "f": f, "hits": hits}
    return out


def plan_tables(h, freqs=("A", "B"), pols=None):
    """Like read_tables, but leave each hitCount array unread and record where it sits in the file.
    Returns (tables_without_hits, hit_locations). hit_locations[(freq, pol)] is a list, one entry per
    segment, of (offset, nbytes, dtype, shape), or None where the dataset isn't contiguous and
    uncompressed (then read_hits_ranges falls back to h5py)."""
    tabs = read_tables(h, freqs, pols, with_hits=False)
    locs = {}
    for (fr, pol) in tabs:
        gp = f"{RFI}/frequency{fr}/{pol}"
        segs = [h[f"{gp}/{k}"] for k in sorted(h[gp].keys())]
        segs = [s for s in segs if "interferenceSignalRatio" in s]
        n_rg = tabs[(fr, pol)]["isr"].shape[1]
        out = []
        for s in segs:
            ds = s["hitCount"]
            off = ds.id.get_offset()
            if ds.chunks is not None or ds.compression is not None or off is None:
                out.append(None)
            else:
                out.append((int(off), int(ds.id.get_storage_size()), ds.dtype, ds.shape, n_rg, s.name))
        locs[(fr, pol)] = out
    return tabs, locs


def read_hits_ranges(fs, url, tabs, locs, h=None, part=8 << 20):
    """Fetch every hitCount array by concurrent byte-range requests and attach it to tabs (float16).
    Returns bytes fetched. A dataset with no recorded location is read through h5py file `h` instead."""
    starts, ends, owners = [], [], []
    for key, segs in locs.items():
        for i, loc in enumerate(segs):
            if loc is None:
                continue
            off, nb = loc[0], loc[1]
            for a in range(off, off + nb, part):
                starts.append(a)
                ends.append(min(a + part, off + nb))
                owners.append((key, i))
    parts = fs.cat_ranges([url] * len(starts), starts, ends, on_error="return") if starts else []
    for k, p in enumerate(parts):                     # one retry, sequential, for any part that failed
        if isinstance(p, Exception):
            parts[k] = fs.cat_file(url, start=starts[k], end=ends[k])
    buf = {}
    for (key, i), p in zip(owners, parts):
        buf.setdefault((key, i), []).append(p)
    fetched = sum(len(p) for p in parts)
    for key, segs in locs.items():
        arrs = []
        for i, loc in enumerate(segs):
            if loc is None:
                if h is None:
                    raise RuntimeError(f"{key}: hitCount segment {i} not contiguous and no h5py file given")
                gp = f"{RFI}/frequency{key[0]}/{key[1]}"
                name = sorted(k for k in h[gp].keys() if "interferenceSignalRatio" in h[f"{gp}/{k}"])[i]
                a = h[f"{gp}/{name}/hitCount"][()]
                n_rg = tabs[key]["isr"].shape[1]
            else:
                _, nb, dt, shape, n_rg, _ = loc
                raw = b"".join(buf[(key, i)])
                if len(raw) != nb:
                    raise RuntimeError(f"{key}: hitCount segment {i}: got {len(raw)} bytes, expected {nb}")
                a = np.frombuffer(raw, dtype=dt).reshape(shape)
            arrs.append(a[:, :n_rg, :].astype(np.float16))
        tabs[key]["hits"] = np.concatenate(arrs)
    return fetched


def save_npz(path, tables, orbit, meta):
    """Cache tables + orbit locally (private) so detection can be re-run without downloads."""
    arrs = {"orbit_t": orbit["t"], "orbit_pos": orbit["pos"], "orbit_vel": orbit["vel"]}
    keys = []
    for (fr, pol), d in tables.items():
        k = f"{fr}{pol}"
        keys.append(k)
        for name, v in d.items():
            if v is not None:
                arrs[f"{k}__{name}"] = v
    np.savez_compressed(path, keys=np.array(keys), meta=np.array([repr(meta)]), orbit_units=np.array([orbit["units"]]), **arrs)


def load_npz(path):
    z = np.load(path, allow_pickle=False)
    orbit = {"t": z["orbit_t"], "pos": z["orbit_pos"], "vel": z["orbit_vel"], "units": str(z["orbit_units"][0])}
    tables = {}
    for k in z["keys"]:
        k = str(k)
        d = {n: (z[f"{k}__{n}"] if f"{k}__{n}" in z else None) for n in ("t", "r", "isr", "mean", "f", "hits")}
        tables[(k[0], k[1:])] = d
    return tables, orbit, eval(str(z["meta"][0]), {"__builtins__": {}}) if "meta" in z else {}
