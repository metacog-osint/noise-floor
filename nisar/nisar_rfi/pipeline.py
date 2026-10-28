"""One watch cycle: find new granules, score them, update sites, write outputs."""
import glob
import hashlib
import json
import os
import traceback
from datetime import datetime, timedelta, timezone

import numpy as np
from shapely.geometry import Polygon, box

from . import bands, bbdetect, cmr, detect, geometry as geo, places, product, qa, report, sites, tabdetect, tables

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
    if cfg.get("emitters_file"):                                          # known emitters for the map (private)
        cfg["emitters_file"] = os.path.normpath(os.path.join(REPO, cfg["emitters_file"]))
    # tables need tone-rank (PROVISIONAL); BETA products only support the image method
    cols = cfg.get("collections", ["NISAR_L2_GCOV_PROVISIONAL_V1"])
    cfg.setdefault("method", "image" if any("BETA" in c for c in cols) else "tables")
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


def token_days_left(token=None):
    """Days until the Earthdata user token expires, from its own expiry claim (None if unreadable).
    Reads only the claim; the token is never logged or stored."""
    import base64
    import time
    tok = token if token is not None else os.environ.get("EARTHDATA_TOKEN", "")
    parts = tok.split(".")
    if len(parts) != 3:
        return None
    try:
        body = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        exp = float(body["exp"])
    except Exception:
        return None
    return (exp - time.time()) / 86400.0


def earthdata_session():
    """Authenticated requests session (QA files, runconfigs). Call after earthdata_fs()."""
    import earthaccess
    return earthaccess.get_requests_https_session()


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


def fetch_tables(g, cfg, fs):
    """Tier 1 read: the RSLC's per-block RFI tables, orbit and look side. (tab, orb, meta); tab may be {}."""
    name = tables.rslc_name(g["granule"])
    cpath = os.path.join(cfg["state_dir"], "cache", f"{name}.npz")
    t0 = datetime.now(timezone.utc)
    if cfg.get("cache_tables") and os.path.exists(cpath):
        tab, orb, cmeta = tables.load_npz(cpath)
        return tab, orb, {"tier": "tables", "rslc": name, "rslc_mb": 0.0, "look": cmeta.get("look", "Left"),
                          "status": "from cache", "channels": sorted(f"{b}{p}" for b, p in tab)}
    rg = cmr.find_granule(name)
    if rg is None or not rg["links"].get("data"):
        return {}, None, {"tier": "tables", "rslc": name, "status": "no RSLC in CMR"}
    import h5py
    url = rg["links"]["data"]
    # Resolve the Earthdata redirect once and read from the signed file URL: each request through the
    # redirect costs ~1 s. The signed URL carries a temporary credential: keep it in memory, never log it.
    try:
        import fsspec
        r = earthdata_session().get(url, headers={"Range": "bytes=0-0"}, allow_redirects=True, timeout=60)
        if r.status_code in (200, 206) and r.url != url:
            url, fs = r.url, fsspec.filesystem("https")
    except Exception:
        pass                                                # fall back to the authenticated session
    with fs.open(url, "rb", block_size=256 << 10, cache_type="blockcache") as f:
        with h5py.File(f, "r") as h:
            orb = tables.read_orbit(h)
            look = h["/science/LSAR/identification/lookDirection"][()] if "/science/LSAR/identification/lookDirection" in h else b"Left"
            tab, locs = tables.plan_tables(h)               # metadata and small arrays only
            if any(loc is None for segs in locs.values() for loc in segs):
                hits_mb = tables.read_hits_ranges(fs, url, tab, locs, h=h) / 1e6
            else:
                hits_mb = None
        meta_mb = f.cache.total_requested_bytes / 1e6
    if hits_mb is None:                                     # bulk arrays: concurrent range requests, no h5py lock
        hits_mb = tables.read_hits_ranges(fs, url, tab, locs) / 1e6
    mb = meta_mb + hits_mb
    look = look.decode() if isinstance(look, bytes) else str(look)
    meta = {"tier": "tables", "rslc": name, "rslc_mb": round(mb, 1), "look": look,
            "channels": sorted(f"{b}{p}" for b, p in tab),
            "read_s": round((datetime.now(timezone.utc) - t0).total_seconds(), 1)}
    if not tab:
        meta["status"] = "no tone-rank tables (processor ran another RFI algorithm)"
        return {}, orb, meta
    if cfg.get("cache_tables"):
        cdir = os.path.join(cfg["state_dir"], "cache")
        os.makedirs(cdir, exist_ok=True)
        tables.save_npz(os.path.join(cdir, f"{name}.npz"), tab, orb,
                        {"rslc": name, "gcov": g["granule"], "track": g["track"], "direction": g["direction"],
                         "frame": g["frame"], "start": g["start"], "footprint": g.get("footprint"),
                         "mode": g.get("mode"), "look": look})
    return tab, orb, meta


def process_granule_tables(g, cfg, fs, fetched=None):
    """Tier 1: candidates per band from the RSLC tables (fetched now unless passed in), and meta."""
    tab, orb, meta = fetched if fetched is not None else fetch_tables(g, cfg, fs)
    if not tab:
        return {}, meta
    look = meta.get("look", "Left")
    cands = tabdetect.detect(tab, orb, look, cfg.get("tables"))
    bbc = cfg.get("broadband", {})
    if bbc.get("enabled", True):
        bb = bbdetect.detect(tab, orb, look, {"height_m": (cfg.get("tables") or {}).get("height_m", 0.0),
                                              **{k: v for k, v in bbc.items() if k != "enabled"}})
        meta["broadband_candidates"] = {b: len(c) for b, c in bb.items()}
        cands = combine_methods(cands, bb, keep_low=bbc.get("keep_low", False))
    meta["candidates"] = {b: len(c) for b, c in cands.items()}
    return cands, meta


def prefetch(items, cfg, fs, workers):
    """Fetch tables for a batch of granules in parallel: {granule: (tab, orb, meta) or Exception}."""
    from concurrent.futures import ThreadPoolExecutor

    def one(g):
        try:
            return g["granule"], fetch_tables(g, cfg, fs)
        except Exception as e:                       # reported per granule in the main loop
            return g["granule"], e

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        return dict(ex.map(one, items))


CONF = ["LOW", "MEDIUM", "HIGH"]


def combine_methods(tone, broad, match_km=20.0, keep_low=False):
    """Per band: a broadband candidate within match_km of a tone candidate becomes evidence on it
    (and can raise its confidence); the rest become broadband detections (LOW ones dropped unless
    keep_low, to keep the site table to what can alert)."""
    out = {}
    for band in sorted(set(tone) | set(broad)):
        t = [dict(c) for c in tone.get(band, [])]
        for b in broad.get(band, []):
            near = min(t, key=lambda c: geo.km_between(c["lat"], c["lon"], b["lat"], b["lon"]), default=None)
            if near is not None and geo.km_between(near["lat"], near["lon"], b["lat"], b["lon"]) <= match_km:
                ev = {k: b[k] for k in ("lat", "lon", "blocks", "peak_ratio_excess_db", "peak_excess_power_db",
                                        "peak_bb_z", "confidence")}
                prev = near.get("broadband")
                if prev is None or ev["blocks"] > prev["blocks"]:
                    near["broadband"] = ev
                near["confidence"] = max(near["confidence"], b["confidence"], key=CONF.index)
            elif keep_low or b["confidence"] != "LOW":
                t.append(dict(b))
        out[band] = t
    return out


def merge_table_bands(cands_by_band, g, cfg, pair_km=20.0):
    """Table candidates to detections; an A and a B candidate within pair_km are one emitter."""
    a = list(cands_by_band.get("A", []))
    b = list(cands_by_band.get("B", []))
    pairs = []
    for x in a:
        y = min(b, key=lambda y: geo.km_between(x["lat"], x["lon"], y["lat"], y["lon"]), default=None)
        if y is not None and geo.km_between(x["lat"], x["lon"], y["lat"], y["lon"]) <= pair_km:
            b.remove(y)
            pairs.append((x, y))
        else:
            pairs.append((x, None))
    pairs += [(y, None) for y in b]
    dets = []
    for main, other, in pairs:
        d = dict(main)
        bl = sorted({main["band"]} | ({other["band"]} if other else set()))
        runs = main.get("freq_runs_mhz", []) + (other.get("freq_runs_mhz", []) if other else [])
        d["bands"] = bl
        d["freq_runs_mhz"] = runs
        # a broadband-only band contributes its whole sub-band (no frequency detail)
        spans = [(r[0], r[1]) for r in runs]
        gn = set(main.get("gnss_overlap", [])) | set(other.get("gnss_overlap", []) if other else [])
        bb_bands = [x["band"] for x in (main, other) if x and x.get("method") == "broadband"]
        for band in bb_bands:
            e = bands.band_edges(g.get("mode", "20+5"), band)
            if e:
                spans.append(e)
                gn |= set(bands.gnss_in(*e))
        texts = [tabdetect.describe_runs(runs)] if runs else []
        texts += [f"band {b} broadband ({'%.0f-%.0f' % bands.band_edges(g.get('mode', '20+5'), b)} MHz)"
                  for b in bb_bands if bands.band_edges(g.get("mode", "20+5"), b)]
        d["band_text"] = "; ".join(t for t in texts if t) or " + ".join(bl)
        d["gnss_overlap"] = sorted(gn)
        d["freq_low_mhz"] = min((s[0] for s in spans), default=0.0)
        d["freq_high_mhz"] = max((s[1] for s in spans), default=0.0)
        d["interpretation"] = tabdetect.interpretation(d)
        if other:
            d["band_b"] = {k: other.get(k) for k in ("lat", "lon", "blocks", "peak_hit", "peak_isr_db", "freq_runs_mhz",
                                                     "method", "peak_ratio_excess_db")}
            d["confidence"] = max(d["confidence"], other["confidence"], key=CONF.index)
            if other.get("broadband") and not d.get("broadband"):
                d["broadband"] = other["broadband"]
        # shared field: ISR in dB for tones, HV/HH ratio excess in dB for broadband-only detections
        d["peak_excess_db"] = d.get("peak_isr_db") if main.get("method") == "tables" else main.get("peak_ratio_excess_db")
        d["mean_excess_db"] = None
        d["where"], d["country"] = places.describe(d["lat"], d["lon"])
        d.update({k: g[k] for k in ("granule", "start", "end", "track", "frame", "direction", "stack") if k in g})
        d["mode"] = g.get("mode", "")
        d["id"] = _det_id(g, "+".join(bl), d["lat"], d["lon"])
        d["url"] = cmr.search_url(g["granule"]) if not g.get("path") else ""
        dets.append(d)
    return dets


def screen_decision(g, state, cfg):
    """Tier 0: read the tables for this pass? (QA score above the floor, or the frame is due a look)."""
    c = {"min_score": 10.0, "every": 3, **cfg.get("screen", {})}
    stack = g.get("stack") or f'{g["track"]:03d}_{g["direction"]}_{g["frame"]:03d}'
    st = state.setdefault("stacks", {}).setdefault(stack, {"since_tables": None})
    q = g.get("qa")
    if q is None:
        return True, "no QA score"
    top = max(q.values()) if q else 0.0
    if top >= c["min_score"]:
        return True, f"QA score {top:.3g} >= {c['min_score']}"
    if st["since_tables"] is None or st["since_tables"] + 1 >= c["every"]:
        return True, "rotation"
    return False, f"QA score {top:.3g} below {c['min_score']}"


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
        # new passes, plus any that failed earlier (a transient 503 from the archive shouldn't lose a pass for good);
        # the lookback window bounds the retries
        todo = sorted((g for g in found if g["granule"] not in state["processed"]
                       or state["processed"][g["granule"]].get("status") == "error"), key=lambda g: g["start"])
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
    days = None if local_dir else token_days_left()
    if days is not None:
        until = (now + timedelta(days=days)).strftime("%Y-%m-%d")
        health["token"] = {"days_left": round(days, 1), "expires": until}
        if days < 14:
            log(f"WARNING: Earthdata token expires in {max(days, 0):.0f} day(s), on {until} (UTC). "
                "Generate a new one at urs.earthdata.nasa.gov and update the EARTHDATA_TOKEN user variable.")
    if todo and not local_dir:
        try:
            fs = earthdata_fs()
        except Exception as e:
            health["download"] = {"status": "ERROR", "msg": str(e)[:300]}
            log(f"login failed: {e}" + (" (Earthdata token has expired)" if days is not None and days <= 0 else ""))
            todo = []

    # 2. score each granule
    method = "image" if local_dir else cfg.get("method", "tables")
    if method == "tables" and todo and fs is not None:
        try:
            qa.fetch_scores(todo, earthdata_session(), log=log)       # tier 0: ~0.1 MB per pass
        except Exception as e:
            log(f"QA scores failed: {e}")
    events, new_dets, errors = [], [], 0
    plan = {}
    if method == "tables":
        for g in todo:                               # decide in time order, so the rotation counts right
            read, why = screen_decision(g, state, cfg)
            st = state["stacks"][g.get("stack") or f'{g["track"]:03d}_{g["direction"]}_{g["frame"]:03d}']
            st["since_tables"] = 0 if read else (st["since_tables"] or 0) + 1
            plan[g["granule"]] = (read, why)
    workers = int(cfg.get("workers", 4))
    fetched = {}
    for i, g in enumerate(todo):
        if method == "tables" and g["granule"] not in fetched:
            batch = [x for x in todo[i:i + 2 * workers] if plan[x["granule"]][0] and x["granule"] not in fetched]
            if batch:
                fetched.update(prefetch(batch, cfg, fs, workers))
        t0 = datetime.now(timezone.utc)
        try:
            if method == "tables":
                read, why = plan[g["granule"]]
                if read:
                    got = fetched.pop(g["granule"])
                    if isinstance(got, Exception):
                        raise got
                    cands, meta = process_granule_tables(g, cfg, fs, got)     # tier 1: tens of MB
                    dets = merge_table_bands(cands, g, cfg)
                else:
                    dets, meta = [], {"tier": "screened"}
                meta["why"] = why
                meta["rfi"] = {"likelihood": g.get("qa") or {}, "kind": g.get("qa_kind", "max_isr")}
            else:
                blobs, meta = process_granule(g, cfg, fs)
                dets = merge_bands(blobs, g, cfg)
                meta["rfi"]["kind"] = "fraction"
            for d in dets:
                d["rfi_likelihood"] = meta["rfi"]["likelihood"]
                d["rfi_kind"] = meta["rfi"].get("kind")
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
                "tier": meta.get("tier", "image"), "why": meta.get("why"), "rslc_mb": meta.get("rslc_mb"),
                "read_s": meta.get("read_s"),
                "table_status": meta.get("status"),
                "seconds": round((datetime.now(timezone.utc) - t0).total_seconds(), 1),
            }
            log(f'{g["granule"][:60]}… {meta.get("tier", "image")}: {len(dets)} detection(s)'
                + (f' ({meta["why"]})' if meta.get('why') else '')
                + (f', {meta["rslc_mb"]} MB' if meta.get('rslc_mb') else '')
                + (f', {meta["status"]}' if meta.get('status') else ''))
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
