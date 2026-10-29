"""Cross-pass bookkeeping: group detections into emitter sites, judge newness,
track coverage (imaged with nothing seen), and cross-fix sites seen from two
different viewing geometries."""
import json
import math
import os
from datetime import timedelta

from shapely.geometry import Point, Polygon

from . import geometry as geo

DEFAULTS = {
    "match_km": 25.0,          # a detection within this of a site belongs to it
    "quiet_after": 2,          # consecutive clean coverages before a site is called QUIET
    "fix_min_cross_deg": 20.0,
    "fix_max_offset_km": 40.0,
    "site_prefix": "S",
}


def load(path):
    if os.path.exists(path):
        return json.load(open(path))
    return {"version": 1, "processed": {}, "detections": [], "sites": {}, "health": {}}


def save(state, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    json.dump(state, open(tmp, "w"), indent=1)
    os.replace(tmp, path)


def pass_key(g):
    return f'{g["track"]:03d}{g["direction"]}{g["start"][:13]}'


def _covers(g, lat, lon):
    fp = g.get("footprint")
    if not fp or len(fp) < 3:
        return False
    try:
        return Polygon(fp).buffer(-0.02).contains(Point(lon, lat))
    except Exception:
        return False


L2_LO, L2_HI = 1226.6, 1228.6      # GPS L2 centre (1227.6 MHz) +- 1 MHz: the L2C main lobe


def signature(d):
    """'L2' for a GPS L2 signature, else 'other' (most likely a radar).

    L2: a tone run at the L2 centre, or broadband power in band A (1219-1239 MHz, which contains L2) with no
    tone: the noise-jammer pattern of the broadband detector's positive control. The public map uses the same rule.
    """
    if any(r[0] <= L2_HI and r[1] >= L2_LO for r in (d.get("freq_runs_mhz") or [])):
        return "L2"
    if "band A broadband" in (d.get("band_text") or ""):
        return "L2"
    if d.get("method") == "broadband" and "A" in (d.get("bands") or [d.get("band") or ""]):
        return "L2"
    return "other"


def _nearest_site(state, lat, lon, km, sig=None):
    """Nearest site within km with the same signature class (sites from before classes existed match any)."""
    best = None
    for s in state["sites"].values():
        if sig and s.get("sig") not in (None, sig):
            continue
        d = geo.km_between(lat, lon, s["lat"], s["lon"])
        if d <= km and (best is None or d < best[0]):
            best = (d, s)
    return best[1] if best else None


def _ignored(cfg, lat, lon):
    for z in cfg.get("ignore", []) or []:
        if geo.km_between(lat, lon, z["lat"], z["lon"]) <= z.get("radius_km", 10):
            return z.get("reason", "on ignore list")
    return None


def _settle(s, quiet_after):
    """Re-derive a site's status, clean streak and seen dates from its coverage in time order.

    Used when a pass arrives after newer ones (a retried failure, a backfill gap), so the running counters don't apply.
    """
    s["coverage"].sort(key=lambda cv: cv["start"])
    if s["coverage"]:
        streak = 0
        for cv in reversed(s["coverage"]):
            if cv["active"]:
                break
            streak += 1
        s["clean_streak"] = streak
        s["status"] = "QUIET" if streak >= quiet_after else "ACTIVE"
    seen = [cv["start"] for cv in s["coverage"] if cv["active"]]
    if seen:
        s["first_seen"] = min(s["first_seen"], seen[0])
        s["last_seen"] = max(s["last_seen"], seen[-1])


def update(state, g, detections, cfg, baseline_run=False):
    """Fold one granule's detections into the site table. Returns events.

    Passes normally arrive in time order. One older than a site's latest coverage re-derives that site's state from
    the time-ordered record and raises no RETURNED or QUIET event (it says nothing about now).
    """
    c = {**DEFAULTS, **cfg.get("sites", {})}
    pk = pass_key(g)
    events, touched = [], set()
    for d in detections:
        d["ignored"] = _ignored(cfg, d["lat"], d["lon"])
        sig = signature(d)                       # a jammer next to a radar stays its own site
        s = _nearest_site(state, d["lat"], d["lon"], c["match_km"], sig)
        is_new = s is None
        if is_new:
            n = len(state["sites"]) + 1
            sid = f'{c["site_prefix"]}-{n:04d}'
            s = state["sites"][sid] = {
                "id": sid, "sig": sig, "lat": d["lat"], "lon": d["lon"], "weight": 0.0,
                "first_seen": g["start"], "last_seen": g["start"], "detections": [], "coverage": [],
                "bands_seen": [], "geometries": [], "status": "ACTIVE", "clean_streak": 0, "fix": None,
                "where": d.get("where", ""), "country": d.get("country"), "baseline": baseline_run,
            }
        d["site"] = s["id"]
        if s["id"] in touched:                  # second blob for the same site in this granule
            s["detections"].append(d["id"])
            continue
        touched.add(s["id"])
        prior = next((cv for cv in s["coverage"] if cv["pass"] == pk), None)
        if prior is not None:                   # adjacent frame of a pass already counted
            s["detections"].append(d["id"])
            if not prior["active"]:
                prior.update(active=True, det=d["id"])
                _settle(s, c["quiet_after"])       # right for in-order and late passes alike
            continue
        was_quiet = s["status"] == "QUIET"
        late = any(cv["start"] > g["start"] for cv in s["coverage"])
        w = max(d["peak_z"], 1.0)
        s["lat"] = round((s["lat"] * s["weight"] + d["lat"] * w) / (s["weight"] + w), 4)
        s["lon"] = round((s["lon"] * s["weight"] + d["lon"] * w) / (s["weight"] + w), 4)
        s["weight"] += w
        s["first_seen"] = min(s["first_seen"], g["start"])
        s["last_seen"] = max(s["last_seen"], g["start"])
        s["detections"].append(d["id"])
        s["coverage"].append({"pass": pk, "start": g["start"], "active": True, "det": d["id"]})
        s["bands_seen"] = sorted(set(s["bands_seen"]) | set(d["bands"]))
        s["geometries"] = sorted(set(s["geometries"]) | {f'{g["track"]}{g["direction"]}'})
        if late:
            _settle(s, c["quiet_after"])
        else:
            s["status"], s["clean_streak"] = "ACTIVE", 0
        if d["ignored"]:
            s["ignored"] = d["ignored"]
        kind = "NEW" if is_new else "RETURNED" if was_quiet and not late else None
        if kind:
            events.append({"kind": kind, "site": s["id"], "det": d, "baseline": baseline_run})
    # sites this footprint covered without a detection
    for s in state["sites"].values():
        if s["id"] in touched or not _covers(g, s["lat"], s["lon"]):
            continue
        if any(cv["pass"] == pk for cv in s["coverage"]):
            continue
        late = any(cv["start"] > g["start"] for cv in s["coverage"])
        s["coverage"].append({"pass": pk, "start": g["start"], "active": False})
        if late:
            _settle(s, c["quiet_after"])
            continue
        s["clean_streak"] += 1
        if s["status"] == "ACTIVE" and s["clean_streak"] >= c["quiet_after"]:
            s["status"] = "QUIET"
            events.append({"kind": "QUIET", "site": s["id"], "det": None, "baseline": baseline_run})
    return events


def refresh_fixes(state, cfg):
    """Cross-fix each site from its two best-crossing streak axes (different geometries)."""
    c = {**DEFAULTS, **cfg.get("sites", {})}
    dets = {d["id"]: d for d in state["detections"]}
    for s in state["sites"].values():
        cand = [dets[i] for i in s["detections"] if i in dets and dets[i].get("aligned_with_range")]
        best = None
        for i in range(len(cand)):
            for j in range(i + 1, len(cand)):
                a, b = cand[i], cand[j]
                if (a["track"], a["direction"]) == (b["track"], b["direction"]):
                    continue
                r = geo.line_intersection(a["lat"], a["lon"], a["axis_az"], b["lat"], b["lon"], b["axis_az"])
                if not r or r[2] < c["fix_min_cross_deg"]:
                    continue
                lat, lon, cross = r
                if geo.km_between(lat, lon, s["lat"], s["lon"]) > c["fix_max_offset_km"]:
                    continue
                # ~1-sigma: blob widths are 4-sigma extents across each streak
                err = math.hypot(a["width_km"], b["width_km"]) / 4 / math.sin(math.radians(cross))
                if best is None or err < best["error_km"]:
                    best = {"lat": round(lat, 4), "lon": round(lon, 4), "error_km": round(err, 1),
                            "crossing_deg": round(cross, 1), "from": [a["id"], b["id"]]}
        s["fix"] = best


def prune(state, keep_days, now):
    cut = (now - timedelta(days=keep_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    state["detections"] = [d for d in state["detections"] if d["start"] >= cut]
    keep = {d["id"] for d in state["detections"]}
    for s in state["sites"].values():
        s["detections"] = [i for i in s["detections"] if i in keep]
        s["coverage"] = sorted((cv for cv in s["coverage"] if cv["start"] >= cut), key=lambda cv: cv["start"])[-60:]
    state["processed"] = {k: v for k, v in state["processed"].items()
                          if v.get("start", "9") >= (now - timedelta(days=max(keep_days, 120))).strftime("%Y-%m-%d")}
