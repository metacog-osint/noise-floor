#!/usr/bin/env python3
"""event_no_heavy.py: rule N, the pre-registered event grade with A350/A380 left out (docs/validation/event-grade-no-heavy.md,
frozen 21 Nov 2026 in 50161a1).

  python tools/event_no_heavy.py plan A B 2026-11-20       # days=[...] and tests=[...] for the workflow
  python tools/event_no_heavy.py table 2026-11-13          # one day's region-hour counts without A359, A35K, A388
  python tools/event_no_heavy.py v0 2026-11-13             # one day's V0 gross events, after daily_job has run
  python tools/event_no_heavy.py score [--report report.json]

Counts only: no aircraft address leaves a run. Nothing here uploads to the data releases or changes the live grade.
The rule and marks are copied from the write-up and must not change after scoring starts.
"""
import argparse
import json
import os
import shutil
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import event_floor as E  # noqa: E402

BASE = os.path.join(ROOT, "data", "event_nh")
MIN_AIRCRAFT, MIN_BASE_DAYS, BASE_DAYS, BASE_WINDOW = 50, 5, 14, 30     # pnt_analysis's existing minimums
SET_D = [(date(2026, 11, 22) + timedelta(k)).isoformat() for k in range(14)]       # held out, 22 Nov - 5 Dec 2026
EXTRA_CASES = [("2026-11-01", 64.6, -21.16, "Near Iceland major, 08 UTC"),
               ("2026-11-06", 47.43, -72.03, "Quebec major, 12 UTC"),
               ("2026-11-20", 47.0, 19.0, "20 Nov central Europe major (noisefloor-event-2026-11-20-1)")]


# ---------------------------------------------------------------------------------------------------------- rule N

def tier_of(excess):
    return "major" if excess >= 25 else "notable" if excess >= 10 else "minor"


def excess_n(key, v0_excess, today, history):
    """(excess, gradable) for one region-hour. Too few other aircraft to judge: it keeps its V0 excess (rule step 3)."""
    n, bad = today.get(key, (0, 0))
    xs = [100 * x[1] / x[0] for x in (d.get(key) for d in history) if x and x[0] >= MIN_AIRCRAFT]
    if n < MIN_AIRCRAFT or len(xs) < MIN_BASE_DAYS:
        return v0_excess, False
    return round(100 * bad / n, 1) - round(statistics.median(xs), 1), True


def grade(event, found, today, history):
    """Rule N for one V0 event. The tier can fall or stay; it never rises and the event is never removed."""
    results = []
    for region, hour in event["rh"]:
        f = found[(region, hour)]
        results.append(excess_n((region, hour), f["share"] - f["baseline_median"], today, history))
    peak = max(x for x, _ in results)
    t = tier_of(peak)
    final = t if E.RANK[t] < E.RANK[event["tier"]] else event["tier"]
    return {"tier_n": final, "excess_n": round(peak, 1), "gradable": sum(1 for _, ok in results if ok),
            "region_hours": len(results)}


# ----------------------------------------------------------------------------------------------------------- plan

def expand(tokens):
    out = []
    for t in tokens:
        if t == "A":
            out += E.SET_A
        elif t == "B":
            out += E.SET_B
        elif ":" in t:
            d0, d1 = (date.fromisoformat(x) for x in t.split(":"))
            out += [(d0 + timedelta(k)).isoformat() for k in range((d1 - d0).days + 1)]
        else:
            out.append(date.fromisoformat(t).isoformat())
    out = sorted(set(out))
    if set(out) & set(SET_D):
        raise SystemExit("Set D needs the write-up's case-count check before N is computed on it")
    return out


def baseline_for(day, has_hourly):
    d0, days = date.fromisoformat(day), []
    for k in range(1, BASE_WINDOW + 1):
        d = (d0 - timedelta(days=k)).isoformat()
        if has_hourly(d):
            days.append(d)
        if len(days) == BASE_DAYS:
            break
    return days


def plan_days(tests, has_hourly):
    need = set(tests)
    for day in tests:
        need.update(baseline_for(day, has_hourly))
    return sorted(need)


def plan_cmd(a):
    import daily_job as J
    tests = expand(a.tokens)

    def has_hourly(d):
        return f"{d}.hourly.parquet" in (J.assets(J.REPO, J.data_tag(d)) or {})
    print("days=" + json.dumps(plan_days(tests, has_hourly)))
    print("tests=" + json.dumps(tests))


# ------------------------------------------------------------------------------------------------------ day files

def table_cmd(a):
    import daily_job as J
    import pnt_analysis as PA
    import pnt_daily as P
    raw = a.raw or J.download_raw(a.day)
    if raw is None:
        raise SystemExit(f"{a.day}: no adsb.lol archive")
    work = os.path.join(BASE, "work", a.day)
    try:
        P.run(a.day, raw, work, a.workers, heavy_apart="drop")
    finally:
        if not a.raw:
            shutil.rmtree(raw, ignore_errors=True)
    version = json.load(open(os.path.join(work, f"{a.day}.summary.json"), encoding="utf-8"))["method_version"]
    if not version.endswith("-noheavy"):
        raise SystemExit(f"{a.day}: expected a no-heavy table, got method {version}")
    PA.DAILY = work
    rows = sorted([r, h, v[0], v[1]] for (r, h), v in PA.region_hours(a.day, set()).items())
    out = os.path.join(BASE, "tables")
    os.makedirs(out, exist_ok=True)
    json.dump({"day": a.day, "method_version": version, "rows": rows}, open(os.path.join(out, f"{a.day}.noheavy.json"), "w"))
    shutil.rmtree(work, ignore_errors=True)
    print(json.dumps({"day": a.day, "method_version": version, "region_hours": len(rows)}))


def v0_cmd(a):
    import pnt_analysis as PA
    PA.DAILY = a.daily
    an = json.load(open(os.path.join(a.analysis, f"{a.day}.anomalies.json"), encoding="utf-8"))
    if an.get("error"):
        out = {"day": a.day, "error": an["error"]}
    else:
        gross = [f for f in an["anomalies"] if f["measure"] == "gross"]
        out = {"day": a.day, "baseline_days": an["baseline_days"],
               "found": [[f["region"], f["hour"], f["share"], f["baseline_median"]] for f in gross],
               "events": [E.slim(e) for e in E.events(gross, PA.heavy_hours(a.day))]}
    d = os.path.join(BASE, "v0")
    os.makedirs(d, exist_ok=True)
    json.dump(out, open(os.path.join(d, f"{a.day}.v0.json"), "w"))
    print(json.dumps({"day": a.day, "error": out.get("error"), "events": len(out.get("events", []))}))


# ---------------------------------------------------------------------------------------------------------- score

def load_tables(folder):
    out = {}
    for name in os.listdir(folder):
        if name.endswith(".noheavy.json"):
            t = json.load(open(os.path.join(folder, name), encoding="utf-8"))
            out[t["day"]] = {(r, int(h)): (int(n), int(b)) for r, h, n, b in t["rows"]}
    return out


def event_rows(v0s, tables, site):
    rows, per_day, missing = [], {}, set()
    for day, d in sorted(v0s.items()):
        if day in SET_D:
            raise SystemExit("Set D needs the write-up's case-count check before N is computed on it")
        if d.get("error"):
            per_day[day] = {"error": d["error"]}
            continue
        gaps = [x for x in [day] + d["baseline_days"] if x not in tables]
        if gaps:
            missing.update(gaps)
            continue
        found = {(r, int(h)): {"share": s, "baseline_median": m} for r, h, s, m in d["found"]}
        history = [tables[x] for x in d["baseline_days"]]
        st = "A" if day in E.SET_A else "B" if day in E.SET_B else "-"
        count = {"V0": defaultdict(int), "N": defaultdict(int)}
        for e in d["events"]:
            if e["tier"] not in ("major", "notable"):
                continue
            g = grade(e, found, tables[day], history)
            count["V0"][e["tier"]] += 1
            count["N"][g["tier_n"]] += 1
            row = {"day": day, "set": st, "tier": e["tier"], "N": g["tier_n"], "peak_excess": e["peak_excess"],
                   "excess_n": g["excess_n"], "gradable": g["gradable"], "region_hours": g["region_hours"],
                   "heavy_share": e.get("heavy_share"), "lat": e["lat"], "lon": e["lon"],
                   "hours": [e["start_hour"], e["end_hour"]], "box": E.in_box(e)}
            if st == "A":
                row["mugu"] = (day == E.MUGU["day"] and E.km(e["lat"], e["lon"], E.MUGU["lat"], E.MUGU["lon"]) <= E.MUGU["km"]
                               and e["start_hour"] <= E.MUGU["h1"] and e["end_hour"] >= E.MUGU["h0"])
            elif st == "B":
                row["corroboration"] = E.corroborated(e, day, site)
            rows.append(row)
        per_day[day] = {k: {t: v[t] for t in ("major", "notable")} for k, v in count.items()}
    if missing:
        raise SystemExit("no-heavy tables missing, nothing scored: " + " ".join(sorted(missing)))
    return rows, per_day


def marks(rows):
    A = [r for r in rows if r["set"] == "A"]
    B = [r for r in rows if r["set"] == "B"]
    boxed = [r for r in A if r["box"] and r["tier"] == "major"]
    mugu = [r for r in A if r.get("mugu")]
    cor = [r for r in B if r["corroboration"]]
    unc = [r for r in B if not r["corroboration"]]
    values = {"P1": E.frac([r["N"] == "major" for r in boxed]),
              "P2": E.frac([E.RANK[r["N"]] >= 2 for r in boxed]),
              "P3": (all(E.RANK[r["N"]] >= 2 for r in mugu) if mugu else None, len(mugu)),
              "P4B": E.frac([E.RANK[r["N"]] >= 2 for r in cor]),
              "P5B": E.frac([r["N"] == "major" for r in cor if r["tier"] == "major"]),
              "P6B": E.frac([E.RANK[r["N"]] < E.RANK[r["tier"]] for r in unc])}
    verdict = {}
    for k, (val, _) in values.items():
        if k == "P3":
            verdict[k] = "not scored" if val is None else "pass" if val else "fail"
        elif val is None:
            verdict[k] = "no cases"
        else:
            verdict[k] = "pass" if val >= E.MARKS[k[:2]] else "fail"
    return {"values": values, "verdict": verdict,
            "passes_A_and_B": all(v == "pass" or (k == "P3" and v == "not scored") for k, v in verdict.items())}


def not_gradable(rows):
    out = defaultdict(lambda: [0, 0])
    for r in rows:
        for key in (f"set {r['set']}", f"box {r['box']}" if r["box"] else None):
            if key:
                out[key][0] += r["region_hours"] - r["gradable"]
                out[key][1] += r["region_hours"]
    return {k: {"not_gradable": a, "region_hours": b, "share": round(a / b, 3) if b else None} for k, (a, b) in sorted(out.items())}


def score_cmd(a):
    v0s = {}
    for name in sorted(os.listdir(a.v0)):
        if name.endswith(".v0.json"):
            d = json.load(open(os.path.join(a.v0, name), encoding="utf-8"))
            v0s[d["day"]] = d
    rows, per_day = event_rows(v0s, load_tables(a.tables), E.Site(a.cache))
    cases = []
    for day, la, lo, what in E.CASES + EXTRA_CASES:
        hits = [r for r in rows if r["day"] == day and E.km(r["lat"], r["lon"], la, lo) <= (400 if day == "2026-11-20" else 150)]
        cases.append({"case": what, "day": day, "events": hits or "not in the scored days or not a V0 major/notable"})
    report = {"rules": "docs/validation/event-grade-no-heavy.md (50161a1)", "days": sorted(v0s), "marks": marks(rows),
              "not_gradable": not_gradable(rows), "per_day": per_day, "cases": cases, "events": rows}
    if a.report:
        json.dump(report, open(a.report, "w"), indent=1)
    print(json.dumps({"verdict": report["marks"]["verdict"], "values": report["marks"]["values"],
                      "passes_A_and_B": report["marks"]["passes_A_and_B"]}, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("tokens", nargs="+")
    t = sub.add_parser("table")
    t.add_argument("day")
    t.add_argument("--raw")
    t.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    v = sub.add_parser("v0")
    v.add_argument("day")
    v.add_argument("--daily", default=os.path.join(ROOT, "data", "pnt", "daily"))
    v.add_argument("--analysis", default=os.path.join(ROOT, "data", "pnt", "analysis"))
    s = sub.add_parser("score")
    s.add_argument("--v0", default=os.path.join(BASE, "v0"))
    s.add_argument("--tables", default=os.path.join(BASE, "tables"))
    s.add_argument("--cache", default=os.path.join(BASE, "cache"))
    s.add_argument("--report")
    a = ap.parse_args()
    {"plan": plan_cmd, "table": table_cmd, "v0": v0_cmd, "score": score_cmd}[a.cmd](a)


if __name__ == "__main__":
    main()
