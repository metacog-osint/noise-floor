#!/usr/bin/env python3
"""run_days.py — process a date range (or list) of adsb.lol days with pnt_daily, skipping days already done.

A day is done when its summary.json exists with the current METHOD_VERSION. Raw folders are searched in order.

Usage
  python pipeline/run_days.py 2025-10-09:2025-10-25 2025-11-11 --raw D:/a/raw --raw data/raw/adsblol
"""
import argparse, json, os, sys, time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pnt_daily as P  # noqa: E402


def expand(specs):
    for s in specs:
        if ":" in s:
            a, b = (date.fromisoformat(x) for x in s.split(":"))
            while a <= b:
                yield a.isoformat(); a += timedelta(days=1)
        else:
            yield s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("days", nargs="+", help="YYYY-MM-DD or START:END")
    ap.add_argument("--raw", action="append", required=True)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "pnt", "daily"))
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    for day in expand(a.days):
        sp = os.path.join(a.out, f"{day}.summary.json")
        if not a.force and os.path.exists(sp) and json.load(open(sp)).get("method_version") == P.METHOD_VERSION:
            print(json.dumps({"day": day, "status": "skip (current)"})); continue
        raw = next((r for r in a.raw if _has(r, day)), None)
        if raw is None:
            print(json.dumps({"day": day, "status": "no raw data"})); continue
        t = time.time()
        try:
            s = P.run(day, raw, a.out, a.workers)
            print(json.dumps({"day": day, "status": "ok", "seconds": s["seconds"], "aircraft": s["aircraft"],
                              "suspects": s["avionics_suspects"], "bad_hex_minutes": s["bad_hex_minutes"]}), flush=True)
        except Exception as e:
            print(json.dumps({"day": day, "status": f"ERROR {e.__class__.__name__}: {e}", "seconds": round(time.time() - t)}), flush=True)


def _has(raw, day):
    try:
        P.day_parts(raw, day); return True
    except FileNotFoundError:
        return False


if __name__ == "__main__":
    main()
