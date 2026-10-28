"""Public export: repeat emitter sites for the public map, from one or more area states.

What goes out (Tom, 28 Oct 2026):
- sites with at least MIN_PASSES MEDIUM or HIGH detections on different passes,
  leaving out frame-wide ("widespread") and ignored detections;
- per site, its qualifying detections and the passes that covered it;
- each public area's box and the date its history starts.

What stays private: alert history and NEW/RETURNED/QUIET state, LOW detections, the vessel page,
and any area whose config says "public": false.

Each detection is a lead, not attribution: something transmitted inside NISAR's receive band there.
"""
import glob
import json
import math
import os
from datetime import datetime, timezone

LICENCE = "Derived from NASA-ISRO NISAR (ASF DAAC), NASA open data, CC0"
MIN_PASSES = 2
KEEP = ("MEDIUM", "HIGH")
TAG = "nisar-data"
REPO_SLUG = "metacog-osint/noise-floor"
NOTES = ("Daily public export of repeat L-band emitter sites seen in NASA-ISRO NISAR radar data (the RSLC processor's "
         "own RFI tables), made by nisar/nisar_rfi/public.py. Leads, not attribution. Source: NISAR L1 RSLC and L2 GCOV "
         "PROVISIONAL products via ASF DAAC, NASA open data (CC0). Method: nisar/README.md; validation: docs/validation/nisar.md.")


def qualifying(d):
    return d.get("confidence") in KEEP and not d.get("widespread") and not d.get("ignored")


def pass_of(d):
    """Same key as sites.pass_key: track, direction and start hour of the pass."""
    return f'{int(d["track"]):03d}{d["direction"]}{d["start"][:13]}'


def _km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(a)))


def detection_record(d):
    return {
        "t": d["start"], "track": int(d["track"]), "dir": d["direction"], "band": d.get("band"),
        "freq": d.get("band_text"), "runs_mhz": d.get("freq_runs_mhz"), "hit": d.get("peak_hit"),
        "blocks": d.get("blocks"), "pols": d.get("pols"), "conf": d.get("confidence"), "method": d.get("method"),
        "lat": round(d["lat"], 3), "lon": round(d["lon"], 3), "granule": d.get("granule"),
    }


def site_record(s, dets):
    """The public record for one site, or None if it doesn't pass the gate."""
    if s.get("ignored"):
        return None
    q = sorted((d for d in dets if qualifying(d)), key=lambda d: d["start"])
    passes = {pass_of(d) for d in q}
    if len(passes) < MIN_PASSES:
        return None
    spread = max(_km(s["lat"], s["lon"], d["lat"], d["lon"]) for d in q)
    coverage = sorted(s.get("coverage", []), key=lambda cv: cv["start"])
    return {
        "id": s["id"], "lat": round(s["lat"], 3), "lon": round(s["lon"], 3),
        "where": s.get("where", ""), "country": s.get("country"),
        "spread_km": round(spread, 1),
        "first_seen": q[0]["start"], "last_seen": q[-1]["start"],
        "bands": sorted({b for d in q for b in (d.get("bands") or [d.get("band")]) if b}),
        "geometries": sorted({f'{int(d["track"])}{d["direction"]}' for d in q}),
        "passes_seen": len(passes),
        # passes whose footprint covered the site: [start, 1 if a qualifying detection was made on it].
        # sites.prune keeps each site's latest 60, so count "seen of covered" only from coverage_from on.
        "coverage_from": coverage[0]["start"] if coverage else None,
        "coverage": [[cv["start"], 1 if cv["pass"] in passes else 0] for cv in coverage],
        "detections": [detection_record(d) for d in q],
    }


def area_record(cfg, state):
    aoi = cfg.get("aoi", {})
    bbox = aoi.get("bbox")
    if not bbox and aoi.get("polygon"):
        xs, ys = [p[0] for p in aoi["polygon"]], [p[1] for p in aoi["polygon"]]
        bbox = [min(xs), min(ys), max(xs), max(ys)]
    starts = sorted(p["start"] for p in state.get("processed", {}).values() if p.get("status") == "ok")
    return {"name": aoi.get("public_name") or aoi.get("name", ""), "bbox": bbox,
            "since": starts[0][:10] if starts else None, "last_pass": starts[-1] if starts else None,
            "passes": len(starts)}


def build(cfgs, now=None):
    """Public document from loaded configs (pipeline.load_config). Areas marked "public": false are skipped."""
    now = now or datetime.now(timezone.utc)
    areas, sites = [], []
    for cfg in cfgs:
        if cfg.get("public") is False:
            continue
        spath = os.path.join(cfg["state_dir"], "state.json")
        if not os.path.exists(spath):
            continue
        state = json.load(open(spath, encoding="utf-8"))
        dets = {d["id"]: d for d in state.get("detections", [])}
        areas.append(area_record(cfg, state))
        for s in state.get("sites", {}).values():
            r = site_record(s, [dets[i] for i in s.get("detections", []) if i in dets])
            if r:
                sites.append(r)
    sites.sort(key=lambda r: r["last_seen"], reverse=True)
    return {
        "day": now.strftime("%Y-%m-%d"), "generated": now.strftime("%Y-%m-%dT%H:%MZ"), "licence": LICENCE,
        "gate": {"min_passes": MIN_PASSES, "confidence": list(KEEP), "excludes": ["widespread", "ignored", "LOW"]},
        "note": "Leads, not attribution: each site is a place where something transmitted inside NISAR's L-band "
                "receive slices (1219-1239 MHz, which contains GPS L2, and 1291-1296 MHz) on repeated passes.",
        "areas": areas, "sites": sites,
    }


def default_configs(load_config, repo):
    """The main config plus every private/watch/nisar.d/*.json, loaded."""
    cfgs = [load_config(None)]
    cfgs += [load_config(p) for p in sorted(glob.glob(os.path.join(repo, "private", "watch", "nisar.d", "*.json")))]
    return cfgs


def write(doc, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f'{doc["day"]}.nisar.json')
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    return path


def upload(path, log=print):
    """Upload to the nisar-data release (created once if missing). Needs the gh CLI, signed in."""
    import subprocess

    def gh(*args, check=True):
        r = subprocess.run(["gh", *args], capture_output=True, text=True)
        if check and r.returncode:
            raise RuntimeError(f"gh {' '.join(args[:2])}: {r.stderr.strip()[:300]}")
        return r

    if gh("release", "view", TAG, "-R", REPO_SLUG, check=False).returncode:
        gh("release", "create", TAG, "-R", REPO_SLUG, "--title", "NISAR L-band emitter sites (daily)",
           "--notes", NOTES, "--latest=false")
        log(f"created release {TAG}")
    gh("release", "upload", TAG, "-R", REPO_SLUG, "--clobber", path)
    log(f"uploaded {os.path.basename(path)} to {TAG}")
