#!/usr/bin/env python3
"""position_loss.py: where aircraft are heard but send no GNSS position, per H3 hex and hour (prototype, not on the map).

The daily per-hex share counts only aircraft that broadcast an ADS-B position. Under strong jamming most aircraft stop
sending positions at all, drop out of the counts, and a hex where nearly everyone lost GNSS can show a modest share
from the few who kept a fix (docs/validation/phase1.md, verdict 45). Where ground receivers can multilaterate (MLAT),
readsb still places those aircraft, marked as MLAT positions. This tool counts them.

  python tools/position_loss.py run 2026-09-15 --raw data/raw/trace_box/2026-09-15
  python tools/position_loss.py boxes 2026-09-15 [...] [--box lat0,lat1,lon0,lon1 ...]   # box totals from the outputs

Per hex (res 4) and UTC hour, airborne at or above --min-alt (default 10,000 ft), ICAO addresses only:
  heard      aircraft with any ADS-B (adsb_icao) or MLAT position in the hex-hour
  adsb       of those, aircraft with at least one ADS-B position there
  mlat_only  aircraft with MLAT positions there and no ADS-B position: heard, but sending no GNSS position
  loss       100 * mlat_only / heard (a lower bound: aircraft with neither ADS-B nor MLAT positions can't be placed)
Hex-hours with no MLAT positions from any aircraft can't show loss this way; `mlat_any` (aircraft with any MLAT
position there) says where MLAT works at all. ADS-B version isn't filtered: any aircraft sending positions counts as
having them.

Outputs data/position_loss/<day>.hex4.parquet (h3, hour, heard, adsb, mlat_only, mlat_any) and <day>.daily4.parquet
(h3, lat, lon, heard, adsb, mlat_only, mlat_any; aircraft counted once per hex per day, mlat_only only if never on
ADS-B in that hex that day). Aggregates only: no aircraft identifiers. Derived from adsb.lol (ODbL 1.0).
"""
import argparse, gzip, io, json, os, sys, time
from collections import defaultdict
from datetime import datetime, timezone
from multiprocessing import Pool

import h3
import orjson
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import pnt_daily as P  # noqa: E402  (Chain, day_parts, batches: the pipeline's archive handling)

OUT = os.path.join(ROOT, "data", "position_loss")
RES = 4
MIN_ALT = 10000
BOXES = {   # the verdict 45 boxes
    "Suwalki-Elk": (53.5, 54.35, 21.6, 23.0), "Grodno area": (53.5, 54.35, 23.0, 24.4),
    "Kaunas": (54.6, 55.45, 23.5, 24.9), "Central Poland (control)": (52.0, 52.85, 19.5, 20.9),
}


def trace_cells(raw, day0, min_alt=MIN_ALT):
    """One trace file -> {(h3 int, hour): flags} with bit 1 = ADS-B position, bit 2 = MLAT position; None if non-ICAO."""
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    d = orjson.loads(raw)
    if d.get("icao", "~").startswith("~"):
        return None
    base = float(d.get("timestamp") or 0)
    out = {}
    for p in d.get("trace", []):
        src = p[9] if len(p) > 9 else None
        bit = 1 if src == "adsb_icao" else 2 if src == "mlat" else 0
        if not bit:
            continue
        alt = p[3]
        if alt == "ground" or alt is None or alt < min_alt:
            continue
        hour = int((base + p[0] - day0) // 3600)
        if not 0 <= hour < 24:
            continue
        k = (h3.str_to_int(h3.latlng_to_cell(p[1], p[2], RES)), hour)
        out[k] = out.get(k, 0) | bit
    return out


def work(args):
    batch, day0, min_alt = args
    hh = defaultdict(lambda: [0, 0, 0, 0])    # (hex, hour) -> [heard, adsb, mlat_only, mlat_any]
    dd = defaultdict(lambda: [0, 0, 0, 0])    # hex -> same, per aircraft per day
    n = 0
    for raw in batch:
        try:
            cells = trace_cells(raw, day0, min_alt)
        except Exception:
            continue
        if not cells:
            continue
        n += 1
        per_hex = defaultdict(int)
        for (hx, hour), f in cells.items():
            c = hh[(hx, hour)]
            c[0] += 1; c[1] += bool(f & 1); c[2] += f == 2; c[3] += bool(f & 2)
            per_hex[hx] |= f
        for hx, f in per_hex.items():
            c = dd[hx]
            c[0] += 1; c[1] += bool(f & 1); c[2] += f == 2; c[3] += bool(f & 2)
    return dict(hh), dict(dd), n


def run(day, raw_dir, out_dir=OUT, workers=None, min_alt=MIN_ALT):
    parts = P.day_parts(raw_dir, day)
    day0 = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())
    t0 = time.time()
    stream = io.BufferedReader(P.Chain(parts), buffer_size=8 << 20)
    hh = defaultdict(lambda: [0, 0, 0, 0]); dd = defaultdict(lambda: [0, 0, 0, 0]); n = 0
    jobs = ((b, d0, min_alt) for b, d0 in P.batches(stream, day0))
    with Pool(workers or max(1, (os.cpu_count() or 2) - 1)) as pool:
        for h, d, k in pool.imap_unordered(work, jobs, chunksize=1):
            n += k
            for key, v in h.items():
                c = hh[key]; c[0] += v[0]; c[1] += v[1]; c[2] += v[2]; c[3] += v[3]
            for key, v in d.items():
                c = dd[key]; c[0] += v[0]; c[1] += v[1]; c[2] += v[2]; c[3] += v[3]
    os.makedirs(out_dir, exist_ok=True)
    hk = sorted(hh)
    pq.write_table(pa.table({"h3": [h3.int_to_str(k[0]) for k in hk], "hour": pa.array([k[1] for k in hk], pa.int8()),
                             **{c: pa.array([hh[k][i] for k in hk], pa.int32()) for i, c in enumerate(("heard", "adsb", "mlat_only", "mlat_any"))}}),
                   os.path.join(out_dir, f"{day}.hex4.parquet"))
    dk = sorted(dd)
    ll = [h3.cell_to_latlng(h3.int_to_str(k)) for k in dk]
    pq.write_table(pa.table({"h3": [h3.int_to_str(k) for k in dk], "lat": [round(x[0], 4) for x in ll], "lon": [round(x[1], 4) for x in ll],
                             **{c: pa.array([dd[k][i] for k in dk], pa.int32()) for i, c in enumerate(("heard", "adsb", "mlat_only", "mlat_any"))}}),
                   os.path.join(out_dir, f"{day}.daily4.parquet"))
    summary = {"day": day, "aircraft": n, "hex_hours": len(hk), "hexes": len(dk), "min_alt_ft": min_alt,
               "input_sha256": stream.raw.sha.hexdigest(), "input_bytes": stream.raw.nbytes, "seconds": round(time.time() - t0, 1),
               "licence": "ODbL 1.0; derived from adsb.lol"}
    with open(os.path.join(out_dir, f"{day}.summary.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps({k: summary[k] for k in ("day", "aircraft", "hexes", "seconds")}))
    return summary


def box_totals(day, boxes, out_dir=OUT):
    """{box: {heard, adsb, mlat_only, mlat_any, loss}} summed over the day's hexes whose centres fall in each box."""
    t = pq.read_table(os.path.join(out_dir, f"{day}.daily4.parquet")).to_pylist()
    out = {}
    for name, b in boxes.items():
        rows = [r for r in t if b[0] <= r["lat"] <= b[1] and b[2] <= r["lon"] <= b[3]]
        s = {k: sum(r[k] for r in rows) for k in ("heard", "adsb", "mlat_only", "mlat_any")}
        s["loss"] = round(100 * s["mlat_only"] / s["heard"], 1) if s["heard"] else None
        out[name] = s
    return out


def parse_box(s):
    v = [float(x) for x in s.split(",")]
    if len(v) != 4:
        raise argparse.ArgumentTypeError("lat0,lat1,lon0,lon1")
    return tuple(v)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["run", "boxes"])
    ap.add_argument("days", nargs="+")
    ap.add_argument("--raw", help="folder with the day's archive parts (run)")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--min-alt", type=int, default=MIN_ALT)
    ap.add_argument("--workers", type=int)
    ap.add_argument("--box", type=parse_box, action="append", help="extra box for 'boxes' (repeatable)")
    a = ap.parse_args()
    if a.cmd == "run":
        for day in a.days:
            run(day, a.raw or os.path.join(ROOT, "data", "raw", "trace_box", day), a.out, a.workers, a.min_alt)
    else:
        boxes = dict(BOXES)
        for i, b in enumerate(a.box or []):
            boxes[f"box {i + 1} {b}"] = b
        for day in a.days:
            for name, s in box_totals(day, boxes, a.out).items():
                print(f"{day}  {name:<26} heard {s['heard']:5d}  adsb {s['adsb']:5d}  mlat_only {s['mlat_only']:5d}  loss {s['loss']}%")


if __name__ == "__main__":
    main()
