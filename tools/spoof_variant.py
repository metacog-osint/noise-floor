#!/usr/bin/env python3
"""spoof_variant.py: score a spoofing detector variant in one command, from the day caches.

  python tools/spoof_variant.py --set SLOW_HI_A2_FT=0 --label V1 --out data/spoof_rerun_v1 \\
      --baseline data/spoofing_v06 --reference data/spoof_rerun_v1_earlier \\
      --outside DIR --at=LAT,LON [--cache data/spoof_cache] [--days ...] [--workers N] [--report FILE]

It takes the machine's heavy-job lock (tools/heavy_lock.py) and then runs, in order:
  1. rerun (tools/spoof_day.py rerun) of every day from its cache with the --set constants into --out;
  2. the held-out score (tools/spoof_heldout.py) on the held-out days among --days: H1-H6 against --baseline, and
     H7 (the A2 rule-A control-box episodes of v0.6's review that are still there: needs --baseline/new_controls.json,
     or --h7-list) and H8 (MLAT-confirmed episodes, at least 98% of the baseline's);
  3. the outside-list score (tools/spoof_compare.py score ... --cache-root --v06) for --outside/--at, on the days of
     --lima-days (default 2026-11-07:2026-11-12) among --days: P1 (placeable flights placed, >= 75%) and P2
     (flights counted, >= 60%);
  4. with --reference, tools/spoof_same.py of --out against that folder, day by day.
and writes one report JSON (--report, default <out>/variant_report.json): per day wall, CPU and read seconds, candidates,
aircraft and episodes; totals; H1-H8; P1 and P2; the reference check. Steps 2-4 are skipped when their arguments are
missing. The report holds counts only: no ICAO address, and not the outside folder's path.

--days defaults to the 18 test days: the 12 held-out days (spoof_heldout.DAYS) and 2026-11-07..2026-11-12. A token may
be a range, FIRST:LAST. --outside is always an argument: the folder lives in another project and is never named here.
The exit status is 1 if --reference differs for real, or a day fails; failed checks are in the report, not the status.

Wall time on this shared PC is unreliable (other jobs); cpu_seconds (this process plus its pool workers) is the number
to compare between runs.
"""
import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import heavy_lock  # noqa: E402
import spoof_compare as C  # noqa: E402
import spoof_day as S  # noqa: E402
import spoof_heldout as H  # noqa: E402
import spoof_same  # noqa: E402

NOV_DAYS = ["2026-11-07", "2026-11-08", "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"]
TEST_DAYS = H.DAYS + NOV_DAYS
H8_SHARE = 0.98
P1_MIN, P2_MIN = 0.75, 0.60


def expand(tokens):
    out = []
    for t in tokens:
        a, _, b = t.partition(":")
        d, e = date.fromisoformat(a), date.fromisoformat(b or a)
        while d <= e:
            if d.isoformat() not in out:
                out.append(d.isoformat())
            d += timedelta(days=1)
    return out


def parse_sets(sets):
    over = {}
    for kv in sets:
        k, _, v = kv.partition("=")
        if not _:
            sys.exit(f"--set {kv}: expected NAME=VALUE")
        over[k.strip()] = json.loads(v)
    return over


def run_days(days, cache, out, workers, over, label):
    """Rerun every day from its cache. Returns the per-day rows."""
    rows = []
    for day in days:
        cd = os.path.join(cache, day)
        if not os.path.exists(os.path.join(cd, "meta.json")):
            raise SystemExit(f"{day}: no day cache in {cache}")
        s = S.rerun(day, cd, out, workers, over, label)
        row = {"day": day, **{k: s.get(k) for k in ("seconds", "seconds_read", "cpu_seconds", "aircraft", "episodes",
                                                    "aircraft_with_episodes", "version")},
               "candidates": (s.get("rerun") or {}).get("candidates"), "parts": s.get("seconds_parts")}
        rows.append(row)
        print(f"RERUN {day}: {row['seconds']} s wall, {row['cpu_seconds']} s CPU, {row['seconds_read']} s read, "
              f"{row['episodes']} episodes", flush=True)
    return rows


def totals(rows, wall):
    def tot(k):
        v = [r[k] for r in rows if r.get(k) is not None]
        return round(sum(v), 1) if v else None
    return {"days": len(rows), "wall_seconds": round(wall, 1), "seconds": tot("seconds"), "cpu_seconds": tot("cpu_seconds"),
            "seconds_read": tot("seconds_read"), "candidates": sum(r["candidates"] or 0 for r in rows),
            "aircraft": sum(r["aircraft"] or 0 for r in rows), "episodes": sum(r["episodes"] or 0 for r in rows)}


def read_events(folder, day):
    return C.load_events(folder, day) or []


def h7_h8(out, baseline, days, h7_list, confirmed):
    """H7: of the A2 rule-A episodes (category A2, kind slow only) among v0.6's new control-box episodes, those still
    present in out. H8: MLAT-confirmed episodes against the baseline's (>= 98%)."""
    res = {}
    if baseline:
        base_conf = 0
        for d in days:
            with open(os.path.join(baseline, f"{d}.summary.json"), encoding="utf-8") as f:
                base_conf += json.load(f)["episodes_mlat_confirmed"]
        res["H8"] = {"confirmed": confirmed, "baseline": base_conf, "min": int(H8_SHARE * base_conf + 0.999999),
                     "pass": confirmed >= H8_SHARE * base_conf}
    path = h7_list or (os.path.join(baseline, "new_controls.json") if baseline else None)
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            rows = [r for r in json.load(f) if r.get("cat") == "A2" and r.get("kinds") == ["slow"]]
        rows = [r for r in rows if r["day"] in days]
        still = 0
        for r in rows:
            mine = H.control_episodes(read_events(out, r["day"]))
            still += any(e["icao"] == r["icao"] and e["start"] <= r["end"] and e["end"] >= r["start"] for e in mine)
        res["H7"] = {"still_present": still, "of": len(rows), "pass": still == 0}
    return res


def lima(days, outside, out, at, km, slack, cache, v06=True):
    per_day, flights = C.score(days, outside, out, at, km, slack, cache_root=cache, v06=v06)
    n = sum(r.get("outside_flights", 0) for r in per_day)
    counted = sum(r.get("counted", 0) for r in per_day)
    pl = sum(r.get("placeable", 0) for r in per_day)
    pm = sum(r.get("placeable_matched", 0) for r in per_day)
    return {"days": [r["day"] for r in per_day], "per_day": per_day,
            "outside_flights": n, "matched": sum(r.get("matched", 0) for r in per_day), "counted": counted,
            "P1": {"placed": pm, "placeable": pl, "share": round(pm / pl, 3) if pl else None,
                   "pass": bool(pl) and pm / pl >= P1_MIN},
            "P2": {"counted": counted, "flights": n, "share": round(counted / n, 3) if n else None,
                   "pass": bool(n) and counted / n >= P2_MIN}}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", action="append", default=[], metavar="NAME=VALUE", help="a detector constant (repeatable)")
    ap.add_argument("--label", required=True, help="variant name, added to each summary's version")
    ap.add_argument("--cache", default=os.path.join(ROOT, "data", "spoof_cache"), help="root of the day caches")
    ap.add_argument("--out", required=True, help="output folder of the reruns")
    ap.add_argument("--baseline", help="spoof_day output of the version compared against (H6, H7, H8)")
    ap.add_argument("--h7-list", help="H7's list of episodes (default <baseline>/new_controls.json; local)")
    ap.add_argument("--reference", help="an earlier output of the same variant: spoof_same.py checks --out against it")
    ap.add_argument("--outside", help="folder of the outside day files (read only), for P1 and P2")
    ap.add_argument("--at", help="LAT,LON of the place for --outside; write --at=LAT,LON when LAT is negative")
    ap.add_argument("--km", type=float, default=100.0)
    ap.add_argument("--slack-min", type=float, default=30.0)
    ap.add_argument("--lima-days", nargs="+", default=["2026-11-07:2026-11-12"], help="days the outside score uses")
    ap.add_argument("--days", nargs="+", default=None, help="days or FIRST:LAST ranges (default: the 18 test days)")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--report", help="report JSON (default <out>/variant_report.json)")
    ap.add_argument("--no-lock", action="store_true", help="don't take the heavy-job lock")
    ap.add_argument("--lock-timeout", type=float, default=None, help="give up waiting for the lock after this many s")
    a = ap.parse_args()
    over = parse_sets(a.set)
    S.check_overrides(over)
    days = expand(a.days) if a.days else TEST_DAYS
    if bool(a.outside) != bool(a.at):
        sys.exit("--outside and --at go together")
    os.makedirs(a.out, exist_ok=True)
    report_path = a.report or os.path.join(a.out, "variant_report.json")

    t_wait = time.time()
    lock = None if a.no_lock else heavy_lock.hold(f"score-variant {a.label}", timeout=a.lock_timeout)
    try:
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        t0 = time.time()
        rows = run_days(days, a.cache, a.out, a.workers, over, a.label)
        t_rerun = time.time() - t0
        rep = {"label": a.label, "overrides": over, "days": days, "workers": a.workers, "cpu_count": os.cpu_count(),
               "started_utc": started, "per_day": rows, "totals": totals(rows, t_rerun)}

        held = [d for d in days if d in H.DAYS]
        if held and os.path.exists(os.path.join(a.out, f"{held[0]}.hex4.parquet")):
            t1 = time.time()
            hs = H.score(a.out, held, a.baseline)
            hs.update(h7_h8(a.out, a.baseline, held, a.h7_list, hs["H3"]["confirmed"]))
            rep["heldout"] = hs
            rep["heldout_seconds"] = round(time.time() - t1, 1)
            print("HELDOUT " + json.dumps({k: v for k, v in hs.items() if k.startswith("H")}), flush=True)
        if a.outside:
            ld = [d for d in expand(a.lima_days) if d in days]
            t1 = time.time()
            at = tuple(float(x) for x in a.at.split(","))
            rep["lima"] = lima(ld, a.outside, a.out, at, a.km, a.slack_min, a.cache)
            rep["lima_seconds"] = round(time.time() - t1, 1)
            print(f"OUTSIDE P1 {rep['lima']['P1']} P2 {rep['lima']['P2']}", flush=True)
        status = 0
        if a.reference:
            t1 = time.time()
            same = spoof_same.compare(a.out, a.reference, days)
            rep["reference"] = {k: same[k] for k in ("n_days", "same", "real_differences", "tie_days")}
            rep["reference_seconds"] = round(time.time() - t1, 1)
            print(f"REFERENCE {rep['reference']}", flush=True)
            status = 0 if same["same"] else 1
        checks = {k: v["pass"] for k, v in {**rep.get("heldout", {}), **{k: rep["lima"][k] for k in ("P1", "P2")
                                                                      if "lima" in rep}}.items()
                  if isinstance(v, dict) and "pass" in v}
        rep["checks"] = checks
        rep["all_checks_pass"] = bool(checks) and all(checks.values())
        rep["total_seconds"] = round(time.time() - t0, 1)
        rep["lock_wait_seconds"] = round(t0 - t_wait, 1)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=1, default=str)
        print(f"TOTAL {rep['total_seconds']} s wall; reruns {rep['totals']['seconds']} s wall, "
              f"{rep['totals']['cpu_seconds']} s CPU; checks {checks}; report {report_path}", flush=True)
        sys.exit(status)
    finally:
        if lock:
            lock.release()


if __name__ == "__main__":
    main()
