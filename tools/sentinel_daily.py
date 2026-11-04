#!/usr/bin/env python3
"""sentinel_daily.py: the daily Sentinel navigation-receiver job (step E of docs/space-sensors-plan.md), run from the
06:30 collectors task (collectors/run_daily.cmd). Private: nothing is uploaded or published (plan step E4 waits on Tom).

  python tools/sentinel_daily.py [--max-days 4] [--weeks 8] [--map-days 28] [--no-fetch]

1. Asks the catalogue for the newest day every default unit has posted (tools/sentinel_gnss.py latest).
2. Builds the E1 table, the E2 epoch indices and the X3 band indices (tools/sentinel_bands.py: GPS L2C and Galileo
   E5a on the PODRIX units) for each day after the newest held epoch file, up to that day (at most --max-days per
   run, oldest first; nothing older than --weeks is fetched). Then fills band files for up to --max-days held days in
   the --weeks window that lack one.
3. For each focus area in the private config (private/watch/satgnss.json): the daily and weekly trend over the last
   --weeks weeks of held days, the cell map over the last --map-days days and the trend chart, written to
   private/sentinel/<area>/ (tools/sentinel_trend.py), on GPS L1 and again on GPS L2C (files named <area>_l2c*).

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


def held_band_days():
    import sentinel_bands as SB
    if not os.path.isdir(SB.BANDS_DIR):
        return []
    return sorted(dt.date.fromisoformat(f[:10]) for f in os.listdir(SB.BANDS_DIR) if f.endswith(".parquet"))


def bands_missing(epoch_days, band_days, weeks, max_days):
    """Held epoch days in the last `weeks` weeks (of the newest) without a band file, newest first, at most max_days."""
    if not epoch_days:
        return []
    floor = max(epoch_days) - dt.timedelta(weeks=weeks)
    have = set(band_days)
    return sorted((d for d in epoch_days if d > floor and d not in have), reverse=True)[:max_days]


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
    bands = set(held_band_days())
    band_series = [d for d in series_days if d in bands]
    band_map = [d for d in map_list if d in bands]
    for a in cfg.get("focus_areas", []):
        out = os.path.join(OUT, a["id"])
        for signal, s_days, m_days in (("l1", series_days, map_list), ("l2c", band_series, band_map)):
            if not s_days:
                log(f"{a['id']} {signal}: no days held")
                continue
            try:
                res = ST.series(cfg, a["id"], s_days, signal)
                ST.write_series(res, ST.stem(a["id"], signal), out)
                ST.main(["chart", "--config", cfg_path, "--area", a["id"], "--out", out, "--signal", signal])
                if m_days:
                    ST.main(["map", "--config", cfg_path, "--area", a["id"], "--out", out, "--signal", signal]
                            + [str(d) for d in m_days])
                wk = res["weekly"][-1] if res["weekly"] else {}
                s = wk.get(a["id"], {})
                log(f"{a['id']} {signal}: {len(s_days)} days to {s_days[-1]}; latest week {wk.get('week')} median "
                    f"{s.get('median')} dB, anomaly {wk.get('anomaly')} dB")
            except Exception as e:
                log(f"{a['id']} {signal}: product failed: {e.__class__.__name__}: {e}")
                traceback.print_exc()


def build_bands(day):
    """X3 band indices for one day; a failure is logged and never stops the run."""
    import sentinel_bands as SB
    try:
        path, counts = SB.build_bands(day)
        log(f"{day}: bands built ({', '.join(f'{u} {n}' for u, n in counts.items()) or 'no PODRIX unit'})")
    except BaseException as e:      # build_bands raises SystemExit when a table is missing
        if isinstance(e, KeyboardInterrupt):
            raise
        log(f"{day}: bands failed: {e.__class__.__name__}: {e}")


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
                build_bands(day)
            except SystemExit as e:
                log(f"{day}: stopped: {e}")
                break
            except Exception as e:
                log(f"{day}: failed: {e.__class__.__name__}: {e}")
                traceback.print_exc()
                break
        for day in bands_missing(held_epoch_days(), held_band_days(), a.weeks, a.max_days):
            build_bands(day)
    products(a.config, a.weeks, a.map_days)
    return 0 if (did or a.no_fetch or held_epoch_days()) else 1


if __name__ == "__main__":
    sys.exit(main())
