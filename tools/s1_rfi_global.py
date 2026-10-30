#!/usr/bin/env python3
"""s1_rfi_global.py: worldwide C-band RFI share from Sentinel-1's own RFI annotation, by region, never as sites.

`tools/s1_rfi.py` reads the RFI annotation of IW GRD products over private boxes and looks for sites; its location
check failed on 24 Oct 2026 (docs/validation/s1-rfi.md), but region-scale activity was reliable. This tool runs the
same parser, fetch and flag rule (s1_rfi.DETECT) over every IW GRD product of a day, worldwide, and keeps one row per
pass and H3 cell: did the pass cover the cell, and did any burst over it carry RFI.

Commands
  day DAY... [--workers 8]     products of the day from Planetary Computer (anonymous), annotation read into a
                               temporary folder and deleted -> data/s1rfi/global/<day>.parquet (pass, cell, flagged)
  week END [--days 7] [--res 3]  -> data/s1rfi/global/week/<END>.r<res>.parquet: per cell, passes covering, passes
                               with RFI, share

About 1,000 IW GRD products a day (S1C and S1D, 15 Oct 2026), about 0.27 MB of files each.
Data: Copernicus Sentinel-1 (free, including commercial use, with "Contains modified Copernicus Sentinel data [year]").
"""
import argparse
import datetime as dt
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import s1_rfi as S  # noqa: E402

OUT = os.path.join(ROOT, "data", "s1rfi", "global")
CELL_RES = 4                       # a burst (about 85 x 20 km) is about one res-4 cell (1,770 km2)


def burst_cells(row, res=CELL_RES):
    """H3 cells a burst covers: the cells of its footprint polygon, or the centre's cell if the polygon is smaller."""
    import h3
    poly = row.get("poly")
    cells = set()
    if poly and len(poly) >= 3:
        try:
            cells = set(h3.polygon_to_cells(h3.LatLngPoly([(a, o) for a, o in poly]), res))
        except Exception:
            cells = set()
    if not cells:
        cells = {h3.latlng_to_cell(row["lat"], row["lon"], res)}
    return cells


def one_product(pc, prod):
    tmp = tempfile.mkdtemp(prefix="s1g_")
    try:
        S.pc_fetch(pc, prod, tmp)
        rows, _ = S.product_rows(prod, tmp)
        return rows
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def day(dayname, workers=8):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from concurrent.futures import ThreadPoolExecutor, as_completed
    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, f"{dayname}.parquet")
    if os.path.exists(out):
        print(f"{dayname}: have it")
        return out
    pc = S.PC()
    t0 = time.time()
    prods = [p for p in pc.search([-180, -90, 180, 90], dayname, dayname) if p["mode"] == "IW"]
    rows, bad = [], 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(one_product, pc, p): p for p in prods}
        for f in as_completed(futs):
            try:
                rows += f.result()
            except Exception as e:
                bad += 1
                if bad <= 5:
                    print(f"  skip {futs[f]['id']}: {S.scrub(e)}")
    rows = S.dedupe(rows)
    seen = {}
    for r in rows:
        fl = S.flag(r)
        for c in burst_cells(r):
            k = (r["pass"], c)
            seen[k] = seen.get(k, False) or fl
    tab = {"pass": [k[0] for k in seen], "cell": [k[1] for k in seen], "flagged": list(seen.values())}
    pq.write_table(pa.table(tab), out, compression="zstd")
    nf = sum(seen.values())
    print(f"{dayname}: {len(prods)} products ({bad} failed), {len(rows)} bursts, {len(seen)} pass-cells, "
          f"{nf / max(len(seen), 1):.3f} flagged, {time.time() - t0:.0f} s")
    return out


def week(end, ndays=7, res=3):
    import h3
    import pyarrow as pa
    import pyarrow.parquet as pq
    e = dt.date.fromisoformat(end)
    days = [(e - dt.timedelta(days=k)).isoformat() for k in range(ndays - 1, -1, -1)]
    cover, hit = {}, {}
    used = []
    for d in days:
        p = os.path.join(OUT, f"{d}.parquet")
        if not os.path.exists(p):
            continue
        used.append(d)
        t = pq.read_table(p).to_pydict()
        per = {}
        for ps, c, fl in zip(t["pass"], t["cell"], t["flagged"]):
            k = (ps, h3.cell_to_parent(c, res) if res < CELL_RES else c)
            per[k] = per.get(k, False) or fl
        for (ps, c), fl in per.items():
            cover[c] = cover.get(c, 0) + 1
            hit[c] = hit.get(c, 0) + int(fl)
    if not used:
        raise SystemExit(f"no day files for the {ndays} days ending {end}")
    cells = sorted(cover)
    ll = [h3.cell_to_latlng(c) for c in cells]
    os.makedirs(os.path.join(OUT, "week"), exist_ok=True)
    out = os.path.join(OUT, "week", f"{end}.r{res}.parquet")
    pq.write_table(pa.table({"cell": cells, "lat": [a for a, _ in ll], "lon": [o for _, o in ll],
                             "passes": [cover[c] for c in cells], "rfi_passes": [hit[c] for c in cells],
                             "share": [hit[c] / cover[c] for c in cells]}), out, compression="zstd")
    print(f"{end}: {len(used)} days, {len(cells)} cells")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("day")
    a1.add_argument("days", nargs="+")
    a1.add_argument("--workers", type=int, default=8)
    a2 = sub.add_parser("week")
    a2.add_argument("end")
    a2.add_argument("--days", type=int, default=7)
    a2.add_argument("--res", type=int, default=3)
    a = ap.parse_args(argv)
    if a.cmd == "day":
        for d in a.days:
            day(d, a.workers)
    else:
        week(a.end, a.days, a.res)


if __name__ == "__main__":
    main()
