"""Tier 0 of the screen: the processor's own RFI score, from each granule's small QA file.

Every NISAR GCOV granule ships a QA statistics file (~0.1 MB) that repeats the
processor's per-channel `rfiLikelihood`. Its meaning depends on the RFI algorithm
the processor ran (isce3 `nisar/workflows/focus.py`, `process_rfi`):

- ST-EVD or frequency-notch (BETA products): fraction of radar blocks flagged, 0..1.
- tone-rank (PROVISIONAL products, which also mitigate): the maximum
  interference-to-signal power ratio over the observation's blocks (linear, unbounded),
  pulse-weighted over observations.

So scores are only comparable within one algorithm. The collection name tells them apart.
"""
import io
from concurrent.futures import ThreadPoolExecutor

import h5py
import numpy as np

QA_PATH = "/science/LSAR/RFI/data/frequency{f}/{pol}/rfiLikelihood"


def score_kind(collection_or_granule):
    """'max_isr' for PROVISIONAL (tone-rank), 'fraction' for BETA (ST-EVD)."""
    s = str(collection_or_granule).upper()
    if "BETA" in s or "_X0" in s:          # BETA CRIDs start with X (e.g. X05009)
        return "fraction"
    return "max_isr"


def read_qa_bytes(data):
    """Per-channel rfiLikelihood from a QA statistics file's bytes: {'AHH': 1.77, ...}."""
    out = {}
    with h5py.File(io.BytesIO(data), "r") as h:
        for f in ("A", "B"):
            g = f"/science/LSAR/RFI/data/frequency{f}"
            if g not in h:
                continue
            for pol in h[g].keys():
                try:
                    v = float(h[QA_PATH.format(f=f, pol=pol)][()])
                except Exception:
                    continue
                if np.isfinite(v):
                    out[f"{f}{pol}"] = v
    return out


def fetch_scores(granules, session, workers=8, log=print):
    """Add g['qa'] (per-channel scores) and g['qa_kind'] to each granule dict from cmr.parse.
    Granules without a QA link get qa=None. Returns the list."""
    def one(g):
        url = (g.get("links") or {}).get("qa_stats")
        if not url:
            return g, None, "no QA link"
        try:
            r = session.get(url, timeout=60)
            r.raise_for_status()
            return g, read_qa_bytes(r.content), None
        except Exception as e:
            return g, None, f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for g, qa, err in ex.map(one, granules):
            g["qa"] = qa
            g["qa_kind"] = score_kind(g["granule"])
            if err:
                log(f"QA {g['granule'][:60]}: {err}")
    return granules


def band_score(qa, band):
    """Highest score over the polarizations of one band (None if absent)."""
    vals = [v for k, v in (qa or {}).items() if k.startswith(band)]
    return max(vals) if vals else None
