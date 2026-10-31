#!/usr/bin/env python3
"""sentinel_daily.py: the daily Sentinel navigation-receiver job (step E of docs/space-sensors-plan.md), run from the
06:30 collectors task (collectors/run_daily.cmd). Private: nothing is uploaded or published (plan step E4 waits on Tom).

  python tools/sentinel_daily.py [--max-days 4] [--weeks 8] [--map-days 28] [--no-fetch]

1. Asks the catalogue for the newest day every default unit has posted (tools/sentinel_gnss.py latest).
2. Builds the E1 table and the E2 epoch indices for each day after the newest held epoch file, up to that day
   (at most --max-days per run, oldest first; nothing older than --weeks is fetched).
3. For each focus area in the private config (private/watch/satgnss.json): the daily and weekly trend over the last
   --weeks weeks of held days, the cell map over the last --map-days days and the trend chart, written to
   private/sentinel/<area>/ (tools/sentinel_trend.py).

Raw product files are kept (about 27 GB a year); raw/index.jsonl holds each one's source and SHA-256. A failure in one
step is logged and the rest still run. Exit status 1 only if nothing could be done.
"""
import argparse
import datetime as dt
import json
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import sentinel_gnss as SG  # noqa: E402

CONFIG = os.path.join(ROOT, "private", "watch", "satgnss.json")
OUT = os.path.join(ROOT, "private", "sentinel")


def log(msg):
    print(f"{dt.datetime.now(dt.timezone.utc):%Y-%m-%dT%H:%MZ} {msg}", flush=True)


def held_epoch_days():
    import sentinel_rfi as SR
    if not os.path.isdir(SR.EPOCH_DIR):
        return []
    return sorted(dt.date.fromisoformat(f[:10]) for f in os.listdir(SR.EPOCH_DIR) if f.endswith(".parquet"))


def days_to_build(newest, held, max_days, weeks):
    """Days after the newest held epoch file (or from `weeks` back) up to `newest`, oldest first, at most max_days."""
    floor = newest - dt.timedelta(weeks=weeks)
    start = max([d for d in held if d <= newest], default=floor - dt.timedelta(days=1)) + dt.timedelta(days=1)
    start = max(start, floor)
    todo = [start + dt.timedelta(days=k) for k in range((newest - start).days + 1)]
    return todo[:max_days]


def products(cfg_path, weeks, map_days):
    import sentinel_trend as ST
    if not os.path.exists(cfg_path):
        log(f"no private config at {os.path.relpath(cfg_path, ROOT)}: area products skipped")
        return
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    held = held_epoch_days()
    if not held:
        log("no epoch files held: area products skipped")
        return
    last = held[-1]
    series_days = [d for d in held if d > last - dt.timedelta(weeks=weeks)]
    map_list = [d for d in held if d > last - dt.timedelta(days=map_days)]
    for a in cfg.get("focus_areas", []):
        out = os.path.join(OUT, a["id"])
        try:
            res = ST.series(cfg, a["id"], series_days)
            ST.write_series(res, a["id"], out)
            ST.main(["chart", "--config", cfg_path, "--area", a["id"], "--out", out])
            ST.main(["map", "--config", cfg_path, "--area", a["id"], "--out", out] + [str(d) for d in map_list])
            wk = res["weekly"][-1] if res["weekly"] else {}
            s = wk.get(a["id"], {})
            log(f"{a['id']}: {len(series_days)} days to {last}; latest week {wk.get('week')} median {s.get('median')} dB, "
                f"anomaly {wk.get('anomaly')} dB")
        except Exception as e:
            log(f"{a['id']}: product failed: {e.__class__.__name__}: {e}")
            traceback.print_exc()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--max-days", type=int, default=4)
    ap.add_argument("--weeks", type=int, default=8)
    ap.add_argument("--map-days", type=int, default=28)
    ap.add_argument("--no-fetch", action="store_true", help="only rebuild the area products from held days")
    ap.add_argument("--config", default=CONFIG)
    a = ap.parse_args(argv)
    did = 0
    if not a.no_fetch:
        import sentinel_rfi as SR
        try:
            newest, per = SG.latest()
        except Exception as e:
            newest, per = None, {}
            log(f"catalogue unreachable: {e.__class__.__name__}: {e}")
        if newest is None and per:
            log(f"not every unit has posted: {per}")
        for day in (days_to_build(newest, held_epoch_days(), a.max_days, a.weeks) if newest else []):
            try:
                if not os.path.exists(os.path.join(SG.DAYS_DIR, f"{day}.parquet")):
                    SG.build_day(day, SG.DEFAULT_UNITS)
                SR.build_epochs(day)
                log(f"{day}: E1 and E2 built")
                did += 1
            except SystemExit as e:
                log(f"{day}: stopped: {e}")
                break
            except Exception as e:
                log(f"{day}: failed: {e.__class__.__name__}: {e}")
                traceback.print_exc()
                break
    products(a.config, a.weeks, a.map_days)
    return 0 if (did or a.no_fetch or held_epoch_days()) else 1


if __name__ == "__main__":
    sys.exit(main())
