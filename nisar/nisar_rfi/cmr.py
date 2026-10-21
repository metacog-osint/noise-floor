"""Granule search against NASA CMR. Search needs no login; downloads do."""
import time
from datetime import datetime, timezone

import requests

CMR = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
UA = {"User-Agent": "nisar-rfi (research; daily poll)"}


def _attrs(umm):
    out = {}
    for a in umm.get("AdditionalAttributes", []) or []:
        v = a.get("Values") or []
        out[a.get("Name")] = v[0] if len(v) == 1 else v
    return out


def _polygon(umm):
    geo = (umm.get("SpatialExtent", {}).get("HorizontalSpatialDomain", {}).get("Geometry", {}))
    polys = geo.get("GPolygons") or []
    if not polys:
        return None
    pts = polys[0].get("Boundary", {}).get("Points", [])
    return [[round(p["Longitude"], 5), round(p["Latitude"], 5)] for p in pts]


def _links(umm):
    out = {"data": None, "runconfig": None, "qa_summary": None, "qa_stats": None, "browse": {}}
    for u in umm.get("RelatedUrls", []) or []:
        url, typ = u.get("URL", ""), u.get("Type", "")
        if not url.startswith("https://"):
            continue
        if typ == "GET DATA" and url.endswith(".h5"):
            out["data"] = url
        elif url.endswith(".rc.yaml"):
            out["runconfig"] = url
        elif url.endswith("_QA_SUMMARY.csv"):
            out["qa_summary"] = url
        elif url.endswith("_QA_STATS.h5"):
            out["qa_stats"] = url
        elif typ == "GET RELATED VISUALIZATION" and url.endswith(".png"):
            out["browse"][url.rsplit("/", 1)[-1]] = url
    return out


def parse(item):
    umm = item["umm"]
    t = umm.get("TemporalExtent", {}).get("RangeDateTime", {})
    a = _attrs(umm)
    return {
        "granule": umm["GranuleUR"],
        "concept_id": item.get("meta", {}).get("concept-id"),
        "start": t.get("BeginningDateTime", "")[:19] + "Z",
        "end": t.get("EndingDateTime", "")[:19] + "Z",
        "track": int(a.get("TRACK_NUMBER", 0) or 0),
        "frame": int(a.get("FRAME_NUMBER", 0) or 0),
        "direction": (a.get("ASCENDING_DESCENDING") or "")[:1].upper(),   # A / D
        "stack": a.get("STACK_ID") or f'{a.get("TRACK_NUMBER")}_{a.get("ASCENDING_DESCENDING", "")[:1]}_{a.get("FRAME_NUMBER")}',
        "mode": a.get("RANGE_BANDWIDTH_CONCAT") or "",
        "frequencies": a.get("FREQUENCIES") if isinstance(a.get("FREQUENCIES"), list) else [a.get("FREQUENCIES")],
        "pols_a": a.get("FREQUENCY_A_POLARIZATION_CONCAT", ""),
        "full_frame": str(a.get("FULL_FRAME", "")).upper() == "TRUE",
        "footprint": _polygon(umm),
        "links": _links(umm),
    }


def search(short_name, bbox, start, end=None, max_items=2000, session=None):
    """Granules intersecting bbox=(W,S,E,N) with start time in [start, end]."""
    s = session or requests.Session()
    end = end or datetime.now(timezone.utc)
    params = {
        "short_name": short_name,
        "bounding_box": ",".join(str(v) for v in bbox),
        "temporal": f"{start:%Y-%m-%dT%H:%M:%SZ},{end:%Y-%m-%dT%H:%M:%SZ}",
        "page_size": 200,
        "sort_key": "start_date",
    }
    out, headers = [], dict(UA)
    while len(out) < max_items:
        for attempt in range(3):
            r = s.get(CMR, params=params, headers=headers, timeout=60)
            if r.status_code < 500:
                break
            time.sleep(5 * (attempt + 1))
        r.raise_for_status()
        items = r.json().get("items", [])
        out += [parse(i) for i in items]
        after = r.headers.get("CMR-Search-After")
        if not items or not after:
            break
        headers = {**UA, "CMR-Search-After": after}
    return out[:max_items]


def find_granule(name, short_names=("NISAR_L1_RSLC_PROVISIONAL_V1", "NISAR_L2_GCOV_PROVISIONAL_V1",
                                     "NISAR_L1_RSLC_BETA_V1", "NISAR_L2_GCOV_BETA_V1"), session=None):
    """One granule by its GranuleUR, from the first collection that has it (None if absent)."""
    s = session or requests.Session()
    for short in short_names:
        r = s.get(CMR, params={"short_name": short, "readable_granule_name": name}, headers=UA, timeout=60)
        r.raise_for_status()
        items = r.json().get("items", [])
        if items:
            return parse(items[0])
    return None


def search_url(granule):
    """Vertex link for a granule, for reports."""
    return f"https://search.asf.alaska.edu/#/?dataset=NISAR&searchType=List%20Search&searchList={granule}"
