"""NISAR against announced US GPS tests (pre-registered 26 Oct 2026; docs/validation/nisar.md, section 6).

  python validation/faa_tests.py configs   # from nisar/: one config per test site with a PROVISIONAL frame inside a window
  python validation/faa_tests.py score     # after the runs: in-window vs control passes, and position errors

Sites: announced FAA GPS test centres (data/declared/faa_gps_tests.json, FAA SPANS, US public domain) with at least one
PROVISIONAL GCOV frame acquired inside a test window (CMR search of 26 Oct 2026); centres within 20 km merge into one site.
Run each config with: python -m nisar_rfi run --config validation/faa/<site>.json --start 2026-06-17 --end 2026-10-26 --seed
"""
import glob
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NISAR = os.path.dirname(HERE)
ROOT = os.path.dirname(NISAR)
CFG_DIR = os.path.join(HERE, "faa")
HITS = os.path.join(HERE, "faa", "frames_in_window.json")
NEAR_KM = 50.0                  # a detection this close to the announced centre counts
WIN_PAD_MIN = 5
BOX_DEG = 0.6
P = lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)  # noqa: E731


def km(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    x = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 12742 * math.asin(min(1.0, math.sqrt(x)))


def tests():
    return list(json.load(open(os.path.join(ROOT, "data", "declared", "faa_gps_tests.json"), encoding="utf-8"))["tests"].values())


def sites(hits):
    """Group the in-window frames' test centres into sites (centres within 20 km merge)."""
    out = []
    for h in hits:
        if "PROVISIONAL" not in h["product"]:
            continue
        c = tuple(h["centre"])
        s = next((s for s in out if km(s["centre"], c) <= 20), None)
        if s is None:
            s = {"centre": list(c), "place": h["place"], "tests": set(), "centres": set()}
            out.append(s)
        s["tests"].add(h["test"])
        s["centres"].add(c)
    for k, s in enumerate(out):
        s["id"] = f"US{k + 1:02d}"
        s["tests"], s["centres"] = sorted(s["tests"]), sorted(s["centres"])
    return out


def windows_for(site, all_tests):
    """Every announced window of every test whose centre lies within 20 km of the site (not only the in-window ones)."""
    w = []
    for t in all_tests:
        if any(km(t["centre"], c) <= 20 for c in site["centres"]):
            w += [(P(a), P(b), t["id"]) for a, b in t.get("windows", [])]
    return w


def cmd_configs():
    hits = json.load(open(HITS, encoding="utf-8"))
    base = json.load(open(os.path.join(HERE, "shiraz_provisional.json"), encoding="utf-8"))
    for s in sites(hits):
        lat, lon = s["centre"]
        cfg = dict(base)
        cfg["_about"] = (f"Pre-registered NISAR test against announced US GPS tests (docs/validation/nisar.md section 6): site {s['id']}, "
                         f"{s['place']}, tests {', '.join(s['tests'])} (FAA SPANS). Run from nisar/: python -m nisar_rfi run --config "
                         f"validation/faa/{s['id']}.json --start 2026-06-17 --end 2026-10-26 --seed")
        cfg["aoi"] = {"name": f"FAA test site {s['id']} ({s['place']})",
                      "bbox": [round(lon - BOX_DEG, 3), round(lat - BOX_DEG, 3), round(lon + BOX_DEG, 3), round(lat + BOX_DEG, 3)]}
        cfg["max_granules_per_run"] = 200
        cfg["sites"] = dict(base["sites"], site_prefix=s["id"])
        cfg["state_dir"] = f"private/nisar/validation-faa/{s['id']}/state"
        cfg["out_dir"] = f"private/nisar/validation-faa/{s['id']}/out"
        cfg["faa_site"] = {"centre": s["centre"], "centres": s["centres"], "tests": s["tests"], "place": s["place"]}
        with open(os.path.join(CFG_DIR, f"{s['id']}.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(cfg, f, indent=2)
        print(s["id"], s["place"], s["centre"], s["tests"])


def inside(poly, lat, lon):
    pts = [(p[1], p[0]) for p in poly]
    res = False
    for (a1, o1), (a2, o2) in zip(pts, pts[1:] + pts[:1]):
        if (a1 > lat) != (a2 > lat) and lon < (o2 - o1) * (lat - a1) / (a2 - a1) + o1:
            res = not res
    return res


def cmd_score():
    all_tests = tests()
    rows, per_site = [], {}
    for path in sorted(glob.glob(os.path.join(CFG_DIR, "US*.json"))):
        cfg = json.load(open(path, encoding="utf-8"))
        sid, site = cfg["sites"]["site_prefix"], cfg["faa_site"]
        wins = windows_for({"centres": [tuple(c) for c in site["centres"]]}, all_tests)
        state = json.load(open(os.path.join(ROOT, cfg["state_dir"], "state.json"), encoding="utf-8"))
        obs_path = os.path.join(ROOT, cfg["out_dir"], "observations.jsonl")
        obs = [json.loads(l) for l in open(obs_path, encoding="utf-8")] if os.path.exists(obs_path) else []
        for g, p in state.get("processed", {}).items():
            if p.get("status") != "ok" or not any(inside(p["footprint"], c[0], c[1]) for c in site["centres"]):
                continue
            t0 = datetime.strptime(p["start"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            inw = [w for w in wins if w[0] - timedelta(minutes=WIN_PAD_MIN) <= t0 <= w[1] + timedelta(minutes=WIN_PAD_MIN)]
            best = None
            for o in obs:
                if o["raw_item_id"] != g or o.get("confidence") not in ("MEDIUM", "HIGH"):
                    continue
                bb = (o.get("extra") or {}).get("broadband") or {}
                if o.get("h3_index"):
                    import h3
                    pos = h3.cell_to_latlng(o["h3_index"])
                elif bb.get("lat") is not None:
                    pos = (bb["lat"], bb["lon"])
                else:
                    continue
                d = min(km(pos, c) for c in site["centres"])
                if best is None or d < best[0]:
                    best = (d, o.get("confidence"), o.get("freq_low_mhz"), o.get("freq_high_mhz"))
            hit = best is not None and best[0] <= NEAR_KM
            rows.append({"site": sid, "granule": g, "start": p["start"], "track": p["track"], "direction": p["direction"],
                         "in_window": bool(inw), "tests": sorted({w[2] for w in inw}), "hit": hit,
                         "km": None if best is None else round(best[0], 1), "confidence": best and best[1]})
    inw = [r for r in rows if r["in_window"]]
    ctl = [r for r in rows if not r["in_window"]]
    hi, hc = sum(r["hit"] for r in inw), sum(r["hit"] for r in ctl)
    ri = hi / len(inw) if inw else 0.0
    rc = hc / len(ctl) if ctl else 0.0
    dists = sorted(r["km"] for r in inw if r["hit"])
    out = {"passes": len(rows), "in_window": len(inw), "control": len(ctl), "in_window_hits": hi, "control_hits": hc,
           "in_window_rate": round(ri, 3), "control_rate": round(rc, 3),
           "N1_pass": hi >= 3 and (rc == 0 or ri >= 2 * rc),
           "N2_median_km": dists[len(dists) // 2] if dists else None, "N2_distances_km": dists,
           "per_site": {s: {"in": sum(1 for r in inw if r["site"] == s), "in_hits": sum(r["hit"] for r in inw if r["site"] == s),
                            "ctl": sum(1 for r in ctl if r["site"] == s), "ctl_hits": sum(r["hit"] for r in ctl if r["site"] == s)}
                        for s in sorted({r["site"] for r in rows})}}
    json.dump({"summary": out, "rows": rows}, open(os.path.join(ROOT, "private", "nisar", "validation-faa", "score.json"), "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    {"configs": cmd_configs, "score": cmd_score}[sys.argv[1]]()
