#!/usr/bin/env python3
"""spoof_shadow.py: shadow variants of the spoofing detector, scored on the days the daily run processes anyway.

  python tools/spoof_shadow.py diff DAY BASE_DIR VARIANT_DIR [--name NAME]    # one day, one variant -> JSON
  python tools/spoof_shadow.py score PATH [PATH ...] [--name NAME]            # pool <day>.spoof-shadow.json files

A shadow variant is a set of detector constants (tools/spoof_shadow.json) that the daily job runs beside the default
every day: pipeline/daily_job.py --spoofing runs tools/spoof_day.py with --cache, reruns each listed variant from that
day cache (spoof_day.py rerun, minutes, no second archive read) and uploads <day>.spoof-shadow.json beside the day's
spoofing files. A proposed change is then scored on days that are processed anyway, with no reprocessing
(docs/spoofing-light-plan.md).

<day>.spoof-shadow.json holds aggregates only, no aircraft identifiers (ODbL 1.0, derived from adsb.lol): for the
default and each variant, active aircraft-hours and aircraft-hours by region group, episodes by class, kind and region
group, control-box episodes and MLAT-tested and MLAT-confirmed episodes; and what changed against the default (episodes
gone and new, by class, region group and emitter category, and MLAT-confirmed episodes lost).

score pools the files and applies the standing held-out checks (docs/validation/spoofing-v06.md, -v061.md) to the
variant against the default on the same days:
  H1  controls: pooled active share of aircraft-hours                  <= 0.01%
  H2  Middle East, Baltic and W Russia: pooled active share             each >= 0.2% and >= 20x H1
  H3  episodes confirmed by MLAT, of those MLAT can test                >= 75%
  H6  control-box episodes against the default                         <= 1.5x
  H8  MLAT-confirmed episodes against the default                      >= 98%
These are the default marks. A pre-registration may set others; it is scored by its own document.
"""
import argparse
import glob
import gzip
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import spoof_day as S  # noqa: E402

LICENCE = "ODbL 1.0; derived from adsb.lol"
SHARE_GROUPS = ("Controls", "Middle East", "Baltic and W Russia")
CONFIG = os.path.join(ROOT, "tools", "spoof_shadow.json")
_GROUP_OF = {r: g for g, rs in S.GROUPS.items() for r in rs}


def variants(day=None, path=CONFIG):
    """Variants listed in tools/spoof_shadow.json that are due on day (from <= day <= until, either may be absent)."""
    try:
        cfg = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for v in cfg.get("variants") or []:
        if day and ((v.get("from") and day < v["from"]) or (v.get("until") and day > v["until"])):
            continue
        out.append(v)
    return out


def _groups(e):
    return sorted({_GROUP_OF.get(S.region_of(c)) for c in e.get("victim_cells") or []} - {None}) or ["Elsewhere"]


def _side(out_dir, day):
    import pyarrow.parquet as pq
    sm = json.load(open(os.path.join(out_dir, f"{day}.summary.json"), encoding="utf-8"))
    ev = json.load(gzip.open(os.path.join(out_dir, f"{day}.events.json.gz"), "rt", encoding="utf-8"))
    sh = Counter()
    for r in pq.read_table(os.path.join(out_dir, f"{day}.hex4.parquet"), columns=["h3", "aircraft", "spoofed_active"]).to_pylist():
        g = _GROUP_OF.get(S.region_of(r["h3"]))
        if g in SHARE_GROUPS:
            sh[(g, 0)] += r["spoofed_active"]; sh[(g, 1)] += r["aircraft"]
    ctl = {n for n, (b, k) in S.REGIONS.items() if k == "control"}
    side = {
        "version": sm.get("version"),
        "shares": {g: [sh[(g, 0)], sh[(g, 1)]] for g in SHARE_GROUPS},
        "episodes": len(ev),
        "by_class": dict(Counter(e["class"] for e in ev)),
        "by_kind": dict(Counter(k for e in ev for k in e["kinds"])),
        "by_group": dict(Counter(g for e in ev for g in _groups(e))),
        "control_episodes": sum(1 for e in ev if {S.region_of(c) for c in e.get("victim_cells") or []} & ctl),
        "mlat_testable": sm.get("episodes_with_mlat_pairs", 0),
        "mlat_confirmed": sm.get("episodes_mlat_confirmed", 0),
    }
    return side, ev


def _changes(rows):
    return {"episodes": len(rows), "by_class": dict(Counter(e["class"] for e in rows)),
            "by_group": dict(Counter(g for e in rows for g in _groups(e))),
            "by_category": dict(Counter(e.get("cat") or "none" for e in rows)),
            "by_kind": dict(Counter("+".join(e["kinds"]) for e in rows)),
            "mlat_confirmed": sum(1 for e in rows if e.get("mlat_dis"))}


def diff(day, base_dir, var_dir, name=None, settings=None):
    """The default (base_dir) and one variant (var_dir) on one day -> aggregate comparison (no identifiers)."""
    b, bev = _side(base_dir, day)
    v, vev = _side(var_dir, day)

    def overlaps(e, others):
        return any(o["icao"] == e["icao"] and o["start"] <= e["end"] and o["end"] >= e["start"] for o in others)
    by_b, by_v = {}, {}
    for e in bev:
        by_b.setdefault(e["icao"], []).append(e)
    for e in vev:
        by_v.setdefault(e["icao"], []).append(e)
    gone = [e for e in bev if not overlaps(e, by_v.get(e["icao"], []))]
    new = [e for e in vev if not overlaps(e, by_b.get(e["icao"], []))]
    return {"name": name, "settings": settings or {}, "variant": v, "gone": _changes(gone), "new": _changes(new),
            "default": b}


def write(day, base_dir, results, site_dir):
    """results: [diff(...), ...] -> site_dir/<day>.spoof-shadow.json."""
    os.makedirs(site_dir, exist_ok=True)
    p = os.path.join(site_dir, f"{day}.spoof-shadow.json")
    out = {"day": day, "licence": LICENCE, "default_version": results[0]["default"]["version"] if results else None,
           "default": results[0]["default"] if results else None,
           "variants": [{k: r[k] for k in ("name", "settings", "variant", "gone", "new")} for r in results],
           "method": "tools/spoof_shadow.py: each variant rerun from the day cache (tools/spoof_day.py rerun) and "
                     "compared with the default; aggregates only. docs/spoofing-light-plan.md"}
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, separators=(",", ":"))
    return p


def score(paths, name=None):
    """Pool <day>.spoof-shadow.json files (files or folders) per variant and apply the standing checks."""
    files = []
    for p in paths:
        files += sorted(glob.glob(os.path.join(p, "*.spoof-shadow.json"))) if os.path.isdir(p) else [p]
    pooled = {}
    for f in files:
        d = json.load(open(f, encoding="utf-8"))
        for v in d.get("variants") or []:
            if name and v["name"] != name:
                continue
            P = pooled.setdefault(v["name"], {"days": [], "settings": v["settings"], "b": Counter(), "v": Counter(),
                                               "gone": Counter(), "new": Counter()})
            P["days"].append(d["day"])
            for side, src in (("b", d["default"]), ("v", v["variant"])):
                for g, (act, ac) in src["shares"].items():
                    P[side][(g, "act")] += act; P[side][(g, "ac")] += ac
                for k in ("episodes", "control_episodes", "mlat_testable", "mlat_confirmed"):
                    P[side][k] += src[k]
            for k in ("gone", "new"):
                P[k]["episodes"] += v[k]["episodes"]; P[k]["mlat_confirmed"] += v[k]["mlat_confirmed"]
                for c, n in v[k]["by_class"].items():
                    P[k][f"class:{c}"] += n
                for c, n in v[k]["by_group"].items():
                    P[k][f"group:{c}"] += n
    out = {}
    for nm, P in pooled.items():
        def share(side, g):
            ac = P[side][(g, "ac")]
            return 100.0 * P[side][(g, "act")] / ac if ac else 0.0
        h1 = share("v", "Controls"); me = share("v", "Middle East"); ba = share("v", "Baltic and W Russia")
        vb, vv = P["b"], P["v"]
        out[nm] = {
            "days": len(P["days"]), "from": min(P["days"]), "to": max(P["days"]), "settings": P["settings"],
            "H1": {"control_active_pct": round(h1, 4), "default": round(share("b", "Controls"), 4), "pass": h1 <= 0.01},
            "H2": {"middle_east_pct": round(me, 3), "baltic_w_russia_pct": round(ba, 3),
                   "pass": me >= 0.2 and ba >= 0.2 and (h1 == 0 or (me >= 20 * h1 and ba >= 20 * h1))},
            "H3": {"confirmed": vv["mlat_confirmed"], "testable": vv["mlat_testable"],
                   "pass": bool(vv["mlat_testable"]) and vv["mlat_confirmed"] / vv["mlat_testable"] >= 0.75},
            "H6": {"control_episodes": vv["control_episodes"], "default": vb["control_episodes"],
                   "pass": vv["control_episodes"] <= 1.5 * vb["control_episodes"]},
            "H8": {"mlat_confirmed": vv["mlat_confirmed"], "default": vb["mlat_confirmed"],
                   "pass": vv["mlat_confirmed"] * 100 >= 98 * vb["mlat_confirmed"]},
            "episodes": {"default": vb["episodes"], "variant": vv["episodes"]},
            "gone": dict(P["gone"]), "new": dict(P["new"]),
        }
        out[nm]["all_pass"] = all(out[nm][h]["pass"] for h in ("H1", "H2", "H3", "H6", "H8"))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["diff", "score"])
    ap.add_argument("args", nargs="+")
    ap.add_argument("--name")
    a = ap.parse_args()
    if a.cmd == "diff":
        day, base, var = a.args
        print(json.dumps(diff(day, base, var, a.name), indent=1))
    else:
        print(json.dumps(score(a.args, a.name), indent=1))


if __name__ == "__main__":
    main()
