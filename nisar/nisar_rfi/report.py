"""Outputs: alerts, observations (event-model rows), GeoJSON, map."""
import gzip
import hashlib
import math
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import h3
from shapely.geometry import Polygon, box, mapping, shape

from . import bands

HERE = os.path.dirname(os.path.abspath(__file__))
CONF_ORDER = ["LOW", "MEDIUM", "HIGH"]
SOURCE = "NISAR L-band"


CENTRAL = ZoneInfo("America/Chicago")


def central(ts):
    """'2026-10-19T18:23:12Z' -> '19 Oct 1:23 PM CDT' (store UTC, show Central with the zone named)."""
    t = datetime.strptime(ts[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc).astimezone(CENTRAL)
    return f"{t.day} {t:%b} {t.hour % 12 or 12}:{t:%M} {'AM' if t.hour < 12 else 'PM'} {t:%Z}"


def _t(ts):
    return ts[:16] + "Z" if ts and not ts.endswith("Z") else (ts[:16] + "Z" if ts else "")


def _rfi_flag_text(d):
    """The processor's per-channel RFI score in its own units: fraction (ST-EVD) or ISR in dB (tone-rank)."""
    lk = d.get("rfi_likelihood") or {}
    if d.get("rfi_kind") == "max_isr":
        return ", ".join(f"{k} {10 * math.log10(v):.0f} dB" for k, v in lk.items() if v and v > 0)
    return ", ".join(f"{k} {v * 100:.1f}%" for k, v in lk.items())


def alerts_from_events(events, state, cfg, now):
    min_conf = cfg.get("alert_min_confidence", "MEDIUM")
    out = []
    for e in events:
        if e["baseline"] or e["kind"] == "QUIET" and not cfg.get("alert_on_quiet", False):
            continue
        s = state["sites"][e["site"]]
        d = e["det"]
        if d is not None and (d.get("ignored") or CONF_ORDER.index(d["confidence"]) < CONF_ORDER.index(min_conf)):
            continue
        if e["kind"] == "QUIET":
            title = f'{s["id"]} quiet on {s["clean_streak"]} straight passes — {s.get("where", "")}'
            detail = "Previously active L-band emitter site imaged without a detection. Could be off-air, moved, or filtered."
            when, url = now.strftime("%Y-%m-%dT%H:%MZ"), ""
        else:
            word = "New" if e["kind"] == "NEW" else "Back on"
            sig = f' ({", ".join(d["gnss_overlap"])})' if d["gnss_overlap"] else ""
            title = f'{word} L-band emitter {s["id"]}: {d["where"]} — band {"+".join(d["bands"])}{sig}'
            fix = (f' Cross-fix {s["fix"]["lat"]}, {s["fix"]["lon"]} ±{s["fix"]["error_km"]} km.' if s.get("fix") else "")
            lk = _rfi_flag_text(d)
            if d.get("method") == "tables":
                measure = (f'Processor RFI table: {d["band_text"]}; {int(d["peak_hit"] * 100)}% of pulses hit, '
                           f'interference {d["peak_isr_db"]} dB over the signal, {d["blocks"]} blocks '
                           f'({d["along_km"]} x {d["across_km"]} km), {"+".join(d["pols"])}, ')
                if d.get("broadband"):
                    measure += f'broadband HV/HH +{d["broadband"]["peak_ratio_excess_db"]} dB nearby, '
            elif d.get("method") == "broadband":
                measure = (f'Processor signal power: HV/HH ratio {d["peak_ratio_excess_db"]} dB above the ground\'s, '
                           f'excess power {d["peak_excess_power_db"]} dB over the frame, {d["blocks"]} blocks '
                           f'({d["along_km"]} x {d["across_km"]} km), ')
            else:
                measure = (f'Cross-pol excess peak {d["peak_excess_db"]} dB over {d["area_km2"]} km², '
                           f'{"streak along range" if d["aligned_with_range"] else "not range-aligned"}, ')
            detail = (f'NISAR pass {central(d["start"])}, track {d["track"]}{d["direction"]} frame {d["frame"]}. '
                      f'{d["interpretation"]} {measure}'
                      f'{d["confidence"].lower()} confidence. Processor RFI score: {lk or "n/a"}.{fix} '
                      "One radar snapshot: a lead for triage, not a finding.")
            when, url = _t(d["start"]), d.get("url", "")
        out.append({
            "id": hashlib.sha1(f'NISAR|{e["kind"]}|{s["id"]}|{(d or {}).get("id", now.date())}'.encode()).hexdigest()[:16],
            "source": SOURCE, "grade": "EFFECT", "title": title[:200], "detail": detail[:600], "url": url,
            "event_time": when, "first_seen": now.strftime("%Y-%m-%dT%H:%MZ"), "country": s.get("country"),
            "service": "L-band RFI", "kind": e["kind"], "site": s["id"],
            "lat": (d or s)["lat"], "lon": (d or s)["lon"], "bands": (d or {}).get("bands", s["bands_seen"]),
        })
    return out


def observation(d):
    """One detection as an observation row (event model, DESIGN.md merged plan), ready for D1."""
    tab = d.get("method") in ("tables", "broadband")
    bb = d.get("method") == "broadband"
    return {
        "source_id": "nisar_rslc_rfi_tables" if tab else "nisar_gcov_rfi", "raw_item_id": d["granule"],
        "observed_start": d["start"], "observed_end": d.get("end") or d["start"],
        "geom": {"type": "Polygon", "coordinates": [d["outline"]]},
        "h3_index": h3.latlng_to_cell(d["lat"], d["lon"], 6),
        "domain": "GNSS" if d["gnss_overlap"] else "RADAR",
        "freq_low_mhz": d["freq_low_mhz"], "freq_high_mhz": d["freq_high_mhz"],
        "metric": "bb_ratio_excess_db" if bb else "isr_db" if tab else "crosspol_excess_db", "value": d["peak_excess_db"],
        "baseline": ("scene HH-to-HV/HH power relationship" if bb else
                     "processor tone-rank table" if tab else "scene HH-ratio relationship"),
        "anomaly_score": d.get("peak_bb_z") if bb else d.get("peak_hit") if tab else d["peak_z"],
        "claim_text": None, "language": None, "extracted_systems": [],
        "link": d.get("url"), "confidence": d["confidence"],
        "extra": {"site": d.get("site"), "bands": d["bands"], "where": d["where"], "track": d["track"],
                  "direction": d["direction"], "frame": d["frame"], "axis_az": d["axis_az"],
                  "aligned_with_range": d["aligned_with_range"], "rfi_likelihood": d.get("rfi_likelihood"),
                  "method": d.get("method", "image"), "freq_runs_mhz": d.get("freq_runs_mhz"), "det_id": d["id"],
                  "peak_hit": d.get("peak_hit"), "pols": d.get("pols"), "widespread": d.get("widespread"),
                  "broadband": d.get("broadband"), "peak_excess_power_db": d.get("peak_excess_power_db")},
    }


def push(alerts):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic or not os.environ.get("NISAR_PUSH"):
        return
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    for a in alerts:
        # ntfy topics are public by name: no place, coordinates or link in the push. Details stay in the private outputs.
        word = {"NEW": "New", "RETURNED": "Returning", "QUIET": "Quiet"}.get(a.get("kind"), "")
        body = f'{word} L-band emitter site {a["site"]}, band {"+".join(a.get("bands") or [])}. Open the private map.'
        req = urllib.request.Request(f"{server}/{topic}", data=body.encode(),
                                     headers={"Title": "Noisefloor: NISAR lane", "Tags": "satellite_antenna"})
        try:
            urllib.request.urlopen(req, timeout=15).read()
        except Exception as e:
            print(f"push failed: {e}", file=sys.stderr)


def write_observations(path, dets, rebuild=False):
    """Append observation rows for detections not already in the log (by detection id), or rewrite
    the log from `dets` when rebuild=True. Re-running a window never duplicates rows."""
    seen = set()
    if not rebuild and os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            try:
                seen.add(json.loads(line).get("extra", {}).get("det_id"))
            except Exception:
                continue
    with open(path, "w" if rebuild else "a", encoding="utf-8") as f:
        for d in dets:
            if d["id"] not in seen:
                f.write(json.dumps(observation(d)) + "\n")
                seen.add(d["id"])


def _fc(features):
    return {"type": "FeatureCollection", "features": features}


def write_all(state, cfg, new_dets, alerts, now, demo=False, truth=None):
    out = cfg["out_dir"]
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "alerts.jsonl"), "a") as f:
        for a in alerts:
            f.write(json.dumps(a) + "\n")
    write_observations(os.path.join(out, "observations.jsonl"), new_dets)
    push(alerts)

    dets = sorted(state["detections"], key=lambda d: d["start"])
    json.dump(_fc([{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [d["outline"]]},
                    "properties": {k: v for k, v in d.items() if k != "outline"}} for d in dets]),
              open(os.path.join(out, "detections.geojson"), "w"))
    json.dump(_fc([{"type": "Feature", "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
                    "properties": {k: v for k, v in s.items() if k not in ("coverage",)}} for s in state["sites"].values()]),
              open(os.path.join(out, "sites.geojson"), "w"))

    sites_active = [s for s in state["sites"].values() if s["status"] == "ACTIVE" and s["detections"]]
    latest = {
        "generated": now.strftime("%Y-%m-%dT%H:%MZ"), "source": SOURCE, "aoi": cfg["aoi"]["name"],
        "health": state.get("health", {}), "alerts": alerts,
        "active_sites": [{k: s[k] for k in ("id", "lat", "lon", "where", "last_seen", "bands_seen", "fix")} for s in sites_active],
        "counts": {"granules_tracked": len(state["processed"]), "detections_kept": len(dets), "sites": len(state["sites"])},
    }
    json.dump(latest, open(os.path.join(out, "latest.json"), "w"), indent=1)
    write_map(state, cfg, now, os.path.join(out, "map.html"), demo=demo, truth=truth)


def write_map(state, cfg, now, path, demo=False, truth=None):
    keep = cfg.get("keep_days", 60)
    cut = (now - timedelta(days=keep)).strftime("%Y-%m-%dT%H:%M:%SZ")
    a = cfg["aoi"]
    w0, s0, e0, n0 = a["bbox"] if a.get("bbox") else Polygon(a["polygon"]).bounds
    view = box(w0 - 4, s0 - 3, e0 + 4, n0 + 3)
    fc = json.load(gzip.open(os.path.join(HERE, "assets", "land.geojson.gz"), "rt", encoding="utf-8"))
    land = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": mapping(shape(f["geometry"]).intersection(view))}
        for f in fc["features"] if shape(f["geometry"]).intersects(view)]}
    bl = json.load(gzip.open(os.path.join(HERE, "assets", "borders.geojson.gz"), "rt", encoding="utf-8"))
    borders = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": f["properties"], "geometry": mapping(shape(f["geometry"]).intersection(view))}
        for f in bl["features"] if shape(f["geometry"]).intersects(view)]}
    gz = json.load(gzip.open(os.path.join(HERE, "assets", "gazetteer.json.gz"), "rt", encoding="utf-8"))
    vw, vs, ve, vn = view.bounds
    places = sorted(([" ".join(p[0].split()), p[1], p[2], p[4]] for p in gz["places"] if vs <= p[1] <= vn and vw <= p[2] <= ve),
                    key=lambda p: -(p[3] or 0))[:600]           # [name, lat, lon, population], largest first
    countries = []
    for f in gz["countries"]["features"]:                 # one label per country, inside the view
        g = shape(f["geometry"])
        if g.intersects(view):
            part = g.intersection(view)
            pt = part.representative_point()
            countries.append((part.area, [f["properties"]["name"], round(pt.y, 2), round(pt.x, 2)]))
    countries = [c for _, c in sorted(countries, key=lambda x: -x[0])]   # biggest first: they win label collisions
    emitters = None
    if cfg.get("emitters_file") and os.path.exists(cfg["emitters_file"]):
        emitters = json.load(open(cfg["emitters_file"], encoding="utf-8"))
        emitters = {"flag_km": emitters.get("flag_km", 20), "list": emitters.get("emitters", [])}
    aoi_geom = mapping(box(*a["bbox"])) if not a.get("polygon") else {"type": "Polygon", "coordinates": [a["polygon"]]}
    w, s_, e, n = w0, s0, e0, n0
    dets = [d for d in state["detections"] if d["start"] >= cut]
    det_meta = {d["id"]: {"start": d["start"], "bands": d["bands"]} for d in dets}
    sites = []
    for s in state["sites"].values():
        m = [det_meta[i] for i in s["detections"] if i in det_meta]
        if m:
            sites.append({**{k: v for k, v in s.items() if k != "detections"}, "detections_meta": m})
    passes = [{"granule": g, **{k: v.get(k) for k in ("start", "track", "frame", "direction", "mode", "footprint",
                                                       "detections", "status")},
               "rfi_likelihood": (v.get("rfi") or {}).get("likelihood", {}),
               "rfi_kind": (v.get("rfi") or {}).get("kind")}
              for g, v in state["processed"].items() if v.get("start", "") >= cut and v.get("footprint")]
    mode = next((p["mode"] for p in passes if p.get("mode")), "20+5")
    bt = {f: f"{lo:.0f}–{hi:.0f} MHz" + (f" ({', '.join(bands.gnss_in(lo, hi))})" if bands.gnss_in(lo, hi) else "")
          for f in ("A", "B") for lo, hi in [bands.band_edges(mode, f) or (0, 0)] if hi}
    data = {
        "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "demo": demo, "truth": truth or [],
        "aoi": {"name": a["name"], "center": [(s_ + n) / 2, (w + e) / 2], "geojson": aoi_geom},
        "land": land, "borders": borders, "places": places, "countries": countries, "emitters": emitters,
        "passes": passes, "detections": dets, "sites": sites, "band_text": bt,
        "footer": f"Generated {central(now.strftime('%Y-%m-%dT%H:%M'))}. NISAR data: NASA/JPL-ISRO via ASF DAAC "
                  "(NASA open data). Land and places: Natural Earth (public domain).",
    }
    html = open(os.path.join(HERE, "map_template.html")).read()
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    open(path, "w").write(html.replace("/*__DATA__*/null", blob))
