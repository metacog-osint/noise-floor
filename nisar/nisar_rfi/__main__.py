"""nisar-rfi command line.

  python -m nisar_rfi run      [--config config.json] [--days 10] [--max N] [--local DIR] [--seed]
  python -m nisar_rfi inspect  GRANULE_UR | URL | FILE.h5
  python -m nisar_rfi tables   GCOV_OR_RSLC_GRANULE_UR [--height M]
  python -m nisar_rfi map      [--config config.json]
  python -m nisar_rfi publish  [--config config.json] [--build-only]   (private web view)
  python -m nisar_rfi vessels  [--config config.json] [--out DIR] [--days N]   (private vessel page, built only)
  python -m nisar_rfi export   [--config C ...] [--out DIR] [--upload]   (public repeat-site file for the site map)
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


def _write_community(links):
    """Private: every post linked to a site, for the private view (private/nisar/out/community.json)."""
    import json
    out = os.path.join(pipeline.REPO, "private", "nisar", "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "community.json"), "w", encoding="utf-8") as f:
        json.dump(links, f, ensure_ascii=False, indent=1)


def cmd_community(a):
    """Link community posts to sites and print them (private; nothing published)."""
    from . import community, public
    cfgs = public.default_configs(pipeline.load_config, pipeline.REPO)
    links = community.build_links(cfgs, pipeline.REPO)
    _write_community(links)
    for x in links:
        where = x["site"] or ("area: " + x["area"])
        print(f'{x["date"]}  {where:24s} {x["place"]:16s} {x["author"] or "":32s} {"NISAR " if x["same_sensor"] else ""}{x["url"]}')
    print(f"community: {len(links)} link(s) to {len({x['site'] for x in links})} site(s)")


def cmd_export(a):
    """Public repeat-site file (nisar_rfi/public.py) from every public area; optionally upload it."""
    from . import public
    cfgs = ([pipeline.load_config(p) for p in a.config] if a.config
            else public.default_configs(pipeline.load_config, pipeline.REPO))
    adsb = None if a.no_adsb else public.Adsb(os.path.join(pipeline.REPO, "data", "adsb"))
    from . import community
    links = community.build_links(cfgs, pipeline.REPO)
    _write_community(links)
    ok = community.approved(os.path.join(pipeline.REPO, "private", "watch", "community_public.txt"))
    doc = public.build(cfgs, adsb=adsb, community=community.public_view(links, ok))
    path = public.write(doc, a.out or os.path.join(pipeline.REPO, "private", "nisar", "public"))
    print(f"export: {len(doc['sites'])} site(s) in {len(doc['areas'])} area(s) -> {path}")
    if a.upload:
        public.upload(path)


def cmd_tables(a):
    """Table method on one pass: read the RSLC RFI tables and print the candidates (nothing saved)."""
    import tempfile

    from . import tabdetect, tables
    name = a.granule.replace("_L1_PR_RSLC_", "_L2_PR_GCOV_")
    g = cmr.find_granule(name) or {"granule": name, "track": 0, "direction": "", "frame": 0, "start": ""}
    fs = pipeline.earthdata_fs()
    with tempfile.TemporaryDirectory() as d:
        tab, orb, meta = pipeline.fetch_tables(g, {"state_dir": d}, fs)
    print(f'{tables.rslc_name(name)}\n{meta.get("rslc_mb")} MB in {meta.get("read_s")} s; channels {meta.get("channels")}'
          + (f'; {meta["status"]}' if meta.get("status") else ""))
    if not tab:
        return
    for band, cands in tabdetect.detect(tab, orb, meta.get("look", "Left"), {"height_m": a.height}).items():
        print(f"band {band}: {len(cands)} candidate(s)")
        for c in cands:
            print(f'  {c["lat"]:.3f},{c["lon"]:.3f}  {c["blocks"]} blocks, {int(c["peak_hit"] * 100)}% of pulses, '
                  f'ISR {c["peak_isr_db"]} dB, {"+".join(c["pols"])}, {c["along_km"]} x {c["across_km"]} km, '
                  f'{c["confidence"]}{" WIDESPREAD" if c["widespread"] else ""}: {tabdetect.describe_runs(c["freq_runs_mhz"])}')


def cmd_publish(a):
    from . import view
    cfg = pipeline.load_config(a.config)
    folder = view.build(cfg)
    print(f"view built: {folder}")
    if not a.build_only:
        ok = view.deploy(cfg, folder)
        raise SystemExit(0 if ok else 1)


def cmd_vessels(a):
    """Build the private vessel page locally (never deploys; publish adds it when the view config says "vessels")."""
    from . import vessels
    try:
        cfg = pipeline.load_config(a.config)
    except SystemExit:
        cfg = {}                                  # no NISAR config: the page builds without emitter context
    info = vessels.build(cfg, a.out, days=a.day or None, n_days=a.days, near_km=a.near_km, use_land=not a.no_land)
    print(f"vessel page built: {os.path.join(info['dest'], 'vessels.html')}")
    print(", ".join(f"{k} {v}" for k, v in info.items() if k not in ("dest", "days")) + f"; days {', '.join(info['days'])}")


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
    t = sub.add_parser("tables")
    t.add_argument("granule")
    t.add_argument("--height", type=float, default=0.0, help="terrain height for geolocation, m")
    t.set_defaults(fn=cmd_tables)
    pb = sub.add_parser("publish")
    pb.add_argument("--config", default=default_cfg)
    pb.add_argument("--build-only", action="store_true")
    pb.set_defaults(fn=cmd_publish)
    v = sub.add_parser("vessels")
    v.add_argument("--config", default=default_cfg)
    v.add_argument("--out", help="output folder (default private/maritime/vessels)")
    v.add_argument("--days", type=int, default=2, help="the last N UTC days with AIS data (default 2)")
    v.add_argument("--day", action="append", help="explicit UTC day(s), YYYY-MM-DD (repeatable)")
    v.add_argument("--no-land", action="store_true", help="skip the Baltic inland-position test")
    v.add_argument("--near-km", type=float, default=50, help="NISAR detections this close count as near (default 50)")
    v.set_defaults(fn=cmd_vessels)
    m = sub.add_parser("map")
    m.add_argument("--config", default=default_cfg)
    m.set_defaults(fn=cmd_map)
    e = sub.add_parser("export")
    e.add_argument("--config", action="append",
                   help="area config (repeatable); default: the main config plus private/watch/nisar.d/*.json")
    e.add_argument("--out", help="output folder (default private/nisar/public)")
    e.add_argument("--upload", action="store_true", help="upload the file to the nisar-data release (gh)")
    e.add_argument("--no-adsb", action="store_true",
                   help="skip the aircraft cross-check (otherwise reads the public map's day files into data/adsb/)")
    e.set_defaults(fn=cmd_export)
    cm = sub.add_parser("community")
    cm.set_defaults(fn=cmd_community)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
