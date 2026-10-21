"""One watch cycle: find new granules, score them, update sites, write outputs."""
import glob
import hashlib
import json
import os
import traceback
from datetime import datetime, timedelta, timezone

import numpy as np
from shapely.geometry import Polygon, box

from . import bands, cmr, detect, geometry as geo, places, product, report, sites

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
# Watch configuration (the AOI) is private: it lives in private/ (gitignored), never in tracked files.
DEFAULT_CONFIG = os.path.join(REPO, "private", "watch", "nisar.json")


def load_config(path=None):
    path = path or DEFAULT_CONFIG
    if not os.path.exists(path):
        raise SystemExit(f"No config at {path}. Copy nisar/config.example.json to private/watch/nisar.json "
                         "and set your area there (private/ is gitignored).")
    cfg = json.load(open(path))
    for k, d in (("state_dir", "private/nisar/state"), ("out_dir", "private/nisar/out")):
        cfg[k] = os.path.normpath(os.path.join(REPO, cfg.get(k, d)))     # relative to the repo root
    return cfg


def aoi_shape(cfg):
    a = cfg["aoi"]
    if a.get("polygon"):
        return Polygon(a["polygon"])
    return box(*a["bbox"])


def earthdata_fs():
    import earthaccess
    if not (os.environ.get("EARTHDATA_TOKEN") or os.environ.get("EARTHDATA_USERNAME")):
        raise RuntimeError("set EARTHDATA_TOKEN (or EARTHDATA_USERNAME / EARTHDATA_PASSWORD)")
    earthaccess.login(strategy="environment")
    return earthaccess.get_fsspec_https_session()


def local_granules(folder):
    out = []
    for p in sorted(glob.glob(os.path.join(folder, "*.h5"))):
        with product.open_product(p) as h:
            i = product.identification(h)
        i["granule"] = i["granule"] or os.path.basename(p)[:-3]
        i.update(path=p, stack=f'{i["track"]:03d}_{i["direction"]}_{i["frame"]:03d}',
                 mode=os.environ.get("NISAR_MODE", "20+5"), links={"data": p})
        out.append(i)
    return out


def _det_id(g, band, lat, lon):
    return hashlib.sha1(f'{g["granule"]}|{band}|{lat:.3f}|{lon:.3f}'.encode()).hexdigest()[:12]


def merge_bands(blobs_by_band, g, cfg):
    """Pair A and B blobs that are the same emitter; return detections."""
    a = blobs_by_band.get("A", [])
    b = list(blobs_by_band.get("B", []))
    out = []
    for x in a:
        partner = None
        for y in b:
            lim = max(10.0, 0.5 * max(x["length_km"], y["length_km"]))
            if geo.km_between(x["lat"], x["lon"], y["lat"], y["lon"]) <= lim:
                partner = y
                break
        if partner:
            b.remove(partner)
        out.append((x, partner, ["A", "B"] if partner else ["A"]))
    out += [(y, None, ["B"]) for y in b]
    dets = []
    for main, other, bl in out:
        d = dict(main)
        d["bands"] = bl
        d.update(bands.describe(bl, g.get("mode", "20+5")))
        d["interpretation"] = bands.interpretation(bl, g.get("mode", "20+5"))
        if other:
            d["band_b"] = {k: other[k] for k in ("peak_z", "peak_excess_db", "area_km2", "lat", "lon")}
            d["confidence"] = max(d["confidence"], other["confidence"], key=["LOW", "MEDIUM", "HIGH"].index)
        d["where"], d["country"] = places.describe(d["lat"], d["lon"])
        d.update({k: g[k] for k in ("granule", "start", "end", "track", "frame", "direction", "stack")})
        d["mode"] = g.get("mode", "")
        d["id"] = _det_id(g, "+".join(bl), d["lat"], d["lon"])
        d["url"] = cmr.search_url(g["granule"]) if not g.get("path") else ""
        dets.append(d)
    return dets


def _baseline_path(cfg, stack, f):
    return os.path.join(cfg["state_dir"], "baselines", f"{stack}_{f}.npz")


def load_baseline(cfg, stack, f):
    p = _baseline_path(cfg, stack, f)
    if not os.path.exists(p):
        return None
    z = np.load(p, allow_pickle=False)
    out = {k: z[k] for k in ("co_db", "cx_db")}
    out.update({k: float(z[k]) for k in ("x0", "y0", "dx", "dy")})
    out["epsg"] = int(z["epsg"])
    out["start"] = str(z["start"])
    return out


def save_baseline(cfg, stack, f, grid, start):
    p = _baseline_path(cfg, stack, f)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    b = detect.baseline_grid(grid)
    np.savez_compressed(p, co_db=b["co_db"], cx_db=b["cx_db"], x0=b["x0"], y0=b["y0"], dx=b["dx"], dy=b["dy"],
                        epsg=b["epsg"], start=start)


def process_granule(g, cfg, fs=None):
    src = g.get("path") or g["links"]["data"]
    det_cfg = cfg.get("detect", {})
    grids, blobs, meta = {}, {}, {"rejected": 0}
    with product.open_product(src, fs=fs) as h:
        ident = product.identification(h)
        ptype = ident.get("product") or "GCOV"
        meta["rfi"] = product.rfi_metadata(h, ptype)
        meta["crid"] = ident.get("crid")
        freqs = [f for f in (g.get("frequencies") or ident.get("frequencies") or ["A", "B"]) if f in ("A", "B")]
        if not g.get("direction"):
            g["direction"] = ident["direction"]
        for f in freqs:
            if f not in cfg.get("frequencies", ["A", "B"]):
                continue
            grid = product.coarse_grid(h, f, cfg.get("cell_m", 500), ptype)
            if grid is not None and detect.score_grid(grid, g["direction"], det_cfg) is not None:
                grids[f] = grid
    stack = g.get("stack") or f'{g["track"]:03d}_{g["direction"]}_{g["frame"]:03d}'
    for f, grid in grids.items():
        prev = load_baseline(cfg, stack, f)
        if prev is not None and prev["start"] >= g["start"]:
            prev = None                                  # never compare against a later pass
        kept = []
        for b in detect.find_blobs(grid, det_cfg):
            if detect.evaluate(b, grids, prev, det_cfg):
                kept.append(b)
            else:
                meta["rejected"] += 1
        blobs[f] = kept
        meta.setdefault("range_az", round(grid["range_az_true"], 1))
        meta.setdefault("relationship", {})[f] = grid["relationship"]
        meta.setdefault("baseline_from", {})[f] = prev["start"] if prev else None
        save_baseline(cfg, stack, f, grid, g["start"])
    for bl in blobs.values():
        for b in bl:
            b.pop("_xy", None)
    return blobs, meta


def run(cfg, local_dir=None, seed=False, max_granules=None, days=None, now=None, log=print, start=None, end=None):
    now = now or datetime.now(timezone.utc)
    os.makedirs(cfg["state_dir"], exist_ok=True)
    os.makedirs(cfg["out_dir"], exist_ok=True)
    spath = os.path.join(cfg["state_dir"], "state.json")
    state = sites.load(spath)
    health = state.setdefault("health", {})
    aoi = aoi_shape(cfg)
    baseline_run = seed or not state["processed"]

    # 1. what's new
    try:
        if local_dir:
            found = local_granules(local_dir)
        else:
            look = days or cfg.get("lookback_days", 10)
            t0, t1 = start or now - timedelta(days=look), end or now
            found = []
            for short in cfg.get("collections", ["NISAR_L2_GCOV_PROVISIONAL_V1"]):
                found += cmr.search(short, aoi.bounds, t0, t1)
        found = [g for g in found if g.get("footprint") and Polygon(g["footprint"]).intersects(aoi)]
        if cfg.get("full_frame_only", False):
            found = [g for g in found if g.get("full_frame", True)]
        todo = sorted((g for g in found if g["granule"] not in state["processed"]), key=lambda g: g["start"])
        health["search"] = {"status": "OK", "found": len(found), "new": len(todo), "at": now.strftime("%Y-%m-%dT%H:%MZ")}
    except Exception as e:
        health["search"] = {"status": "ERROR", "msg": f"{e.__class__.__name__}: {e}"[:300], "at": now.strftime("%Y-%m-%dT%H:%MZ")}
        log(f"search failed: {e}")
        todo = []
    cap = max_granules or cfg.get("max_granules_per_run", 40)
    if len(todo) > cap:
        log(f"{len(todo)} new granules; processing the oldest {cap} this run")
        todo = todo[:cap]

    fs = None
    if todo and not local_dir:
        try:
            fs = earthdata_fs()
        except Exception as e:
            health["download"] = {"status": "ERROR", "msg": str(e)[:300]}
            log(f"login failed: {e}")
            todo = []

    # 2. score each granule
    events, new_dets, errors = [], [], 0
    for g in todo:
        t0 = datetime.now(timezone.utc)
        try:
            blobs, meta = process_granule(g, cfg, fs)
            dets = merge_bands(blobs, g, cfg)
            for d in dets:
                d["rfi_likelihood"] = meta["rfi"]["likelihood"]
            ev = sites.update(state, g, dets, cfg, baseline_run=baseline_run)
            state["detections"] += dets
            new_dets += dets
            events += ev
            state["processed"][g["granule"]] = {
                "start": g["start"], "end": g.get("end"), "stack": g.get("stack"), "track": g["track"],
                "frame": g["frame"], "direction": g["direction"], "mode": g.get("mode"),
                "footprint": g["footprint"], "detections": len(dets), "status": "ok",
                "rfi": meta["rfi"], "crid": meta.get("crid"), "range_az": meta.get("range_az"),
                "rejected": meta.get("rejected", 0), "baseline_from": meta.get("baseline_from"),
                "seconds": round((datetime.now(timezone.utc) - t0).total_seconds(), 1),
            }
            log(f'{g["granule"][:60]}… {len(dets)} detection(s), rfiLikelihood {meta["rfi"]["likelihood"]}')
        except Exception as e:
            errors += 1
            state["processed"][g["granule"]] = {"start": g["start"], "status": "error", "footprint": g.get("footprint"),
                                                "track": g.get("track"), "direction": g.get("direction"),
                                                "msg": f"{e.__class__.__name__}: {e}"[:300]}
            log(f'ERROR {g["granule"]}: {e}')
            if os.environ.get("NISAR_DEBUG"):
                traceback.print_exc()
    if todo:
        health["download"] = {"status": "OK" if errors < len(todo) else "ERROR",
                              "processed": len(todo) - errors, "errors": errors, "at": now.strftime("%Y-%m-%dT%H:%MZ")}

    # 3. sites, fixes, outputs
    sites.refresh_fixes(state, cfg)
    sites.prune(state, cfg.get("keep_days", 60), now)
    alerts = report.alerts_from_events(events, state, cfg, now)
    report.write_all(state, cfg, new_dets, alerts, now, demo=cfg.get("demo", False), truth=cfg.get("truth"))
    state["last_run"] = now.strftime("%Y-%m-%dT%H:%MZ")
    sites.save(state, spath)
    log(f"{now:%Y-%m-%d %H:%MZ}: {len(todo)} granule(s), {len(new_dets)} detection(s), "
        f"{sum(1 for e in events if e['kind'] == 'NEW')} new site(s), {len(alerts)} alert(s)"
        + (" [baseline run: alerts held]" if baseline_run and events else ""))
    return state, alerts
