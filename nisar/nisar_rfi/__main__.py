"""nisar-rfi command line.

  python -m nisar_rfi run      [--config config.json] [--days 10] [--max N] [--local DIR] [--seed]
  python -m nisar_rfi inspect  GRANULE_UR | URL | FILE.h5
  python -m nisar_rfi map      [--config config.json]
"""
import argparse
import os
from datetime import datetime, timedelta, timezone

import numpy as np

from . import cmr, detect, pipeline, product, report, sites

HERE = os.path.dirname(os.path.abspath(__file__))


def cmd_run(a):
    cfg = pipeline.load_config(a.config)
    day = lambda v: datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=timezone.utc) if v else None
    end = day(a.end) + timedelta(days=1) if a.end else None
    log = (lambda m: None) if a.quiet else print
    _, alerts = pipeline.run(cfg, local_dir=a.local, seed=a.seed, max_granules=a.max, days=a.days,
                             start=day(a.start), end=end, log=log)
    if a.quiet:
        print(f"nisar: run complete, {len(alerts)} alert(s)")


def cmd_map(a):
    cfg = pipeline.load_config(a.config)
    st = sites.load(os.path.join(cfg["state_dir"], "state.json"))
    report.write_map(st, cfg, datetime.now(timezone.utc), os.path.join(cfg["out_dir"], "map.html"))
    print(os.path.join(cfg["out_dir"], "map.html"))


def _find(granule):
    import requests
    for short in ("NISAR_L2_GCOV_PROVISIONAL_V1", "NISAR_L1_RSLC_PROVISIONAL_V1",
                  "NISAR_L2_GCOV_BETA_V1", "NISAR_L1_RSLC_BETA_V1"):
        r = requests.get(cmr.CMR, params={"short_name": short, "readable_granule_name": granule}, headers=cmr.UA, timeout=60)
        items = r.json().get("items", [])
        if items:
            return cmr.parse(items[0])
    raise SystemExit(f"{granule}: not found in CMR")


def cmd_inspect(a):
    """What RFI information does this product carry, and what does the scorer see?"""
    src, g, fs = a.target, None, None
    if not os.path.exists(src):
        if not src.startswith("http"):
            g = _find(src)
            src = g["links"]["data"]
            print(f'granule  {g["granule"]}\nmode     {g["mode"]} MHz, track {g["track"]}{g["direction"]} frame {g["frame"]}')
        fs = pipeline.earthdata_fs()
    with product.open_product(src, fs=fs) as h:
        ident = product.identification(h)
        ptype = ident.get("product") or "GCOV"
        meta = product.rfi_metadata(h, ptype)
        print(f'product  {ptype}  CRID {ident.get("crid")}  {ident["start"]}  pass {ident["direction"]}')
        print(f'rfiLikelihood        {meta["likelihood"] or "absent"}')
        print(f'mitigation applied   {meta["mitigation_applied"]}')
        print(f'algorithms           detection={meta["detection_algorithm"]} mitigation={meta["mitigation_algorithm"]}')
        print(f'per-block RFI group  {meta["block_group"] or "absent"}')
        print("RFI-related paths:")
        for p in product.list_rfi_paths(h):
            print("   ", p)
        if meta["block_group"]:
            blk = product.rfi_block_grid(h, meta["block_group"])
            isr = blk.get("interferenceSignalRatio")
            if isr is not None:
                print(f'  ISR grid {isr.shape}, max {np.nanmax(isr):.3g}, blocks > 0.1: {(isr > 0.1).sum()}')
        if ptype == "GCOV":
            grids = {}
            for f in ident.get("frequencies") or ["A"]:
                grid = product.coarse_grid(h, f, 500)
                if grid and detect.score_grid(grid, ident["direction"] or "D") is not None:
                    grids[f] = grid
            for f, grid in grids.items():
                cands = detect.find_blobs(grid)
                kept = [b for b in cands if detect.evaluate(b, grids)]
                print(f'freq {f}: grid {grid["co_db"].shape} at {abs(grid["dx"]):.0f} m, range azimuth '
                      f'{grid["range_az_true"]:.1f}°, {len(cands)} candidate(s), {len(kept)} kept (no change check here)')
                for b in kept[:8]:
                    print(f'   {b["lat"]:.3f},{b["lon"]:.3f}  z {b["peak_z"]}  excess {b["peak_excess_db"]} dB  '
                          f'{b["area_km2"]} km²  {b["confidence"]}: {"; ".join(b["evidence"])}')
    if g and g["links"].get("runconfig"):
        try:
            import earthaccess
            txt = earthaccess.get_requests_https_session().get(g["links"]["runconfig"], timeout=60).text
            lines = txt.splitlines()
            i = next((k for k, l in enumerate(lines) if "radio_frequency_interference" in l), None)
            if i is not None:
                print("runconfig RFI section:")
                print("\n".join("   " + l for l in lines[i:i + 14]))
        except Exception as e:
            print(f"runconfig not read: {e}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="nisar_rfi")
    sub = ap.add_subparsers(dest="cmd", required=True)
    default_cfg = None          # private/watch/nisar.json
    r = sub.add_parser("run")
    r.add_argument("--config", default=default_cfg)
    r.add_argument("--days", type=int)
    r.add_argument("--max", type=int)
    r.add_argument("--start", help="search window start, YYYY-MM-DD (backfill / validation)")
    r.add_argument("--end", help="search window end, YYYY-MM-DD (inclusive)")
    r.add_argument("--local", help="process local .h5 files in this folder instead of searching")
    r.add_argument("--seed", action="store_true", help="record sites without alerting (baseline run)")
    r.add_argument("--quiet", action="store_true", help="one summary line only (for logs others can read)")
    r.set_defaults(fn=cmd_run)
    i = sub.add_parser("inspect")
    i.add_argument("target")
    i.set_defaults(fn=cmd_inspect)
    m = sub.add_parser("map")
    m.add_argument("--config", default=default_cfg)
    m.set_defaults(fn=cmd_map)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
