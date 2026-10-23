#!/usr/bin/env python3
"""trace_box.py: follow aircraft through a box on one day, from the raw adsb.lol traces.

When a box's ADS-B aircraft count collapses, this tells the two readings apart:
  * position loss: aircraft still fly through, but their ADS-B positions stop across the box (a gap, or MLAT only);
  * routing: fewer aircraft fly through the box at all.

  python tools/trace_box.py extract <raw_dir> <day>      # raw archive parts -> data/trace_box/<day>.jsonl.gz
  python tools/trace_box.py report <day> [<day> ...]     # crossings, gaps and MLAT per day
  python tools/trace_box.py night <day> [<day> ...]      # night vs day degraded share by altitude, type, arrival state

Defaults: the southern Baltic lead box (54.8-57N, 15-19E) inside a region of 52-60N, 8-26E. Override with
--box / --region lat0,lat1,lon0,lon1. Only airborne points at or above --min-alt feet (default 10,000) count, and
only aircraft that sent at least one ADS-B position in the region that day (--all-aircraft to include the rest).

A crossing is a stretch of an aircraft's track (any position source, consecutive points joined by straight lines
when under --max-join minutes apart) that lies inside the box for at least 5 minutes. Inside the box it is:
  seen       positions for most of it (gaps of more than --gap minutes cover under half the crossing), mostly ADS-B
  mlat-only  the same, but most positions inside the box come from MLAT or other sources, not ADS-B
  dark       gaps of more than --gap minutes cover half the crossing or more
  dark-long  a single gap longer than --max-join (up to 4 hours) whose straight line crosses the box: the aircraft
             was out of sight for the whole region, so its path is a guess
"""
import argparse, gzip, json, os, sys, tarfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from multiprocessing import Pool

import orjson

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import pnt_daily as P                       # noqa: E402  (Chain, day_parts: same archive handling as the pipeline)

OUT = os.path.join(ROOT, "data", "trace_box")
BOX = (54.8, 57.0, 15.0, 19.0)
REGION = (52.0, 60.0, 8.0, 26.0)
SRC = {"adsb_icao": "a", "mlat": "m"}       # anything else: "o"


def parse_box(s):
    v = tuple(float(x) for x in s.split(","))
    assert len(v) == 4 and v[0] < v[1] and v[2] < v[3], s
    return v


def inside(lat, lon, b):
    return b[0] <= lat <= b[1] and b[2] <= lon <= b[3]


# ---------- extract ----------

def scan(args):
    """Batch of raw trace files -> aircraft with points in the region: {icao, type, pts:[[t, lat, lon, alt, src, nacp, nic]]}."""
    raws, region = args
    out = []
    for raw in raws:
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        d = orjson.loads(raw)
        icao = d.get("icao", "~")
        if icao.startswith("~"):
            continue
        base = float(d.get("timestamp") or 0)
        nacp = nic = None
        pts = []
        for p in d.get("trace", []):
            det = p[8] if len(p) > 8 else None
            if det:
                nacp = det.get("nac_p", nacp); nic = det.get("nic", nic)
            alt = p[3]
            if alt == "ground" or alt is None or not inside(p[1], p[2], region):
                continue
            pts.append([round(base + p[0], 1), round(p[1], 4), round(p[2], 4), alt,
                        SRC.get(p[9] if len(p) > 9 else None, "o"), nacp, nic])
        if pts:
            out.append({"icao": icao, "type": d.get("t") or "", "pts": pts})
    return out


def batches(stream, region, size=400):
    with tarfile.open(fileobj=stream, mode="r|") as tf:
        cur = []
        for m in tf:
            if m.isfile() and "/traces/" in "/" + m.name.lstrip("./") and "trace_full_" in m.name:
                cur.append(tf.extractfile(m).read())
                if len(cur) >= size:
                    yield cur, region; cur = []
        if cur:
            yield cur, region


def extract(raw_dir, day, region, workers):
    os.makedirs(OUT, exist_ok=True)
    dest = os.path.join(OUT, f"{day}.jsonl.gz")
    n = 0
    with gzip.open(dest + ".part", "wt", encoding="utf-8") as f, Pool(workers) as pool:
        for res in pool.imap_unordered(scan, batches(P.Chain(P.day_parts(raw_dir, day)), region), chunksize=1):
            for a in res:
                f.write(json.dumps(a, separators=(",", ":")) + "\n"); n += 1
    os.replace(dest + ".part", dest)
    print(json.dumps({"day": day, "aircraft_in_region": n, "file": dest}))


# ---------- report ----------

def clip(p, q, b):
    """Liang-Barsky: the part of segment p->q (lat, lon) inside box b, as (t0, t1) in [0, 1], or None."""
    lat0, lat1, lon0, lon1 = b
    dx, dy = q[2] - p[2], q[1] - p[1]
    t0, t1 = 0.0, 1.0
    for pp, qq in ((-dx, p[2] - lon0), (dx, lon1 - p[2]), (-dy, p[1] - lat0), (dy, lat1 - p[1])):
        if pp == 0:
            if qq < 0:
                return None
            continue
        r = qq / pp
        if pp < 0:
            t0 = max(t0, r)
        else:
            t1 = min(t1, r)
        if t0 > t1:
            return None
    return t0, t1


def crossings(pts, b, gap_s, join_s):
    """Crossings of box b by one aircraft's time-ordered points."""
    out, cur = [], None
    for p, q in zip(pts, pts[1:]):
        dt = q[0] - p[0]
        if dt <= 0:                             # repeated timestamp: neither joins nor breaks the track
            continue
        c = clip(p, q, b)
        if c is None or dt > join_s:
            if cur:
                out.append(cur); cur = None
            if c is not None and dt <= 4 * 3600:   # a gap longer than max-join whose straight line crosses the box
                out.append({"t0": p[0] + c[0] * dt, "t1": p[0] + c[1] * dt, "gap": (c[1] - c[0]) * dt, "src": Counter(),
                            "nacp_bad": 0, "adsb": 0, "before": p, "after": q, "long": True})
            continue
        t_in, t_out = p[0] + c[0] * dt, p[0] + c[1] * dt
        if cur is None:
            cur = {"t0": t_in, "t1": t_out, "gap": 0.0, "src": Counter(), "nacp_bad": 0, "adsb": 0,
                   "before": p, "after": q}
        cur["t1"] = t_out; cur["after"] = q
        if dt > gap_s:
            cur["gap"] += t_out - t_in
        if c[1] < 1.0:                          # the segment leaves the box: the crossing ends here
            out.append(cur); cur = None
            continue
        cur["src"][q[4]] += 1                   # q is inside the box
        if q[4] == "a":
            cur["adsb"] += 1; cur["nacp_bad"] += q[5] is not None and q[5] < 8
    if cur:
        out.append(cur)
    return [c for c in out if c["t1"] - c["t0"] >= 300]


def classify(c):
    dur = c["t1"] - c["t0"]
    if c.get("long"):
        return "dark-long"
    if c["gap"] >= 0.5 * dur:
        return "dark"
    return "seen" if c["adsb"] >= 0.5 * sum(c["src"].values()) and c["adsb"] else "mlat-only"


def last_good(pts, t, before=True):
    """The nearest ADS-B point before (or after) time t."""
    cand = [p for p in pts if p[4] == "a" and ((p[0] <= t) if before else (p[0] >= t))]
    if not cand:
        return None
    return cand[-1] if before else cand[0]


def report(day, b, min_alt, gap_s, join_s, adsb_only=True):
    path = os.path.join(OUT, f"{day}.jsonl.gz")
    day0 = datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()
    kinds, hours, aircraft, edges_in, edges_out = Counter(), defaultdict(Counter), set(), Counter(), Counter()
    seen_pts = seen_bad = 0
    pre_bad = pre_n = 0
    types = defaultdict(Counter)
    type_pts = defaultdict(lambda: [0, 0])
    n_region = 0
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            a = json.loads(line)
            if adsb_only and not any(p[4] == "a" for p in a["pts"]):
                continue                        # never sent ADS-B here: its "gaps" would only track MLAT coverage
            pts = sorted((p for p in a["pts"] if p[3] >= min_alt), key=lambda p: p[0])
            if not pts:
                continue
            n_region += 1
            for c in crossings(pts, b, gap_s, join_s):
                if not day0 <= c["t0"] < day0 + 86400:      # the archive also holds some of the day before
                    continue
                k = classify(c)
                kinds[k] += 1; aircraft.add(a["icao"]); types[k][a["type"] or "?"] += 1
                hours[int((c["t0"] % 86400) // 3600)][k] += 1
                if k == "seen":
                    seen_pts += c["adsb"]; seen_bad += c["nacp_bad"]
                    type_pts[a["type"] or "?"][0] += c["adsb"]; type_pts[a["type"] or "?"][1] += c["nacp_bad"]
                if k.startswith("dark"):
                    lb, fa = last_good(pts, c["t0"] + 1), last_good(pts, c["t1"] - 1, before=False)
                    if lb:
                        edges_in[(int(lb[1]), int(lb[2]))] += 1
                        pre_n += 1; pre_bad += lb[5] is not None and lb[5] < 8
                    if fa:
                        edges_out[(int(fa[1]), int(fa[2]))] += 1
    tot = sum(kinds.values())
    print(f"{day}: {n_region} {'ADS-B ' if adsb_only else ''}aircraft at or above {min_alt} ft in the region; {len(aircraft)} crossed the box "
          f"({tot} crossings of 5+ min)")
    for k in ("seen", "mlat-only", "dark", "dark-long"):
        print(f"  {k:10} {kinds[k]:5d}  {100 * kinds[k] / tot if tot else 0:5.1f}%")
    if seen_pts:
        print(f"  ADS-B points inside the box on 'seen' crossings: {seen_pts}, {100 * seen_bad / seen_pts:.1f}% with NACp < 8")
    if pre_n:
        print(f"  dark crossings: last ADS-B point before the gap had NACp < 8 on {pre_bad} of {pre_n} ({100 * pre_bad / pre_n:.0f}%)")
        print("  where the dark gaps start (1-degree cells, last ADS-B point):",
              ", ".join(f"{la}N {lo}E: {n}" for (la, lo), n in edges_in.most_common(6)))
        print("  where they end (first ADS-B point after):",
              ", ".join(f"{la}N {lo}E: {n}" for (la, lo), n in edges_out.most_common(6)))
    print("  by UTC hour (seen/mlat-only/dark incl. long):", " ".join(
        f"{h:02d}:{hours[h]['seen']}/{hours[h]['mlat-only']}/{hours[h]['dark'] + hours[h]['dark-long']}" for h in sorted(hours)))
    by_type = Counter()
    for k in types:
        by_type.update(types[k])
    rows = []
    for t, n in by_type.most_common():
        if n < 8:
            break
        dark = types["dark"][t] + types["dark-long"][t]
        tp = type_pts.get(t, [0, 0])
        rows.append(f"{t} {n} ({100 * types['seen'][t] / n:.0f}% seen, {100 * dark / n:.0f}% dark"
                    + (f", {100 * tp[1] / tp[0]:.0f}% of seen points NACp<8)" if tp[0] else ")"))
    print("  by type, 8+ crossings:", "; ".join(rows))


NARROW = {"A20N", "A21N", "A319", "A320", "A321", "B737", "B738", "B739", "B38M", "B39M", "BCS1", "BCS3", "E190", "E195",
          "E290", "E295", "CRJ7", "CRJ9", "AT75", "AT76", "DH8D", "E170", "E175", "E75L"}
BANDS = ((10000, 20000, "FL100-195"), (20000, 30000, "FL200-295"), (30000, 10 ** 6, "FL300+"))
NIGHT, DAY = {22, 23, 0, 1, 2, 3, 4}, set(range(8, 18))


def night(day, area):
    """Night (22-04Z) against day (08-17Z) inside an area: degraded share (NACp < 8) of ADS-B aircraft-minutes by
    altitude band; and at FL300+, by narrowbody or not, and by whether the aircraft was already degraded at its first
    ADS-B point in the extract (carried in from elsewhere, or first heard inside the area already degraded)."""
    tot = defaultdict(lambda: [0, 0])
    with gzip.open(os.path.join(OUT, f"{day}.jsonl.gz"), "rt", encoding="utf-8") as f:
        for line in f:
            a = json.loads(line)
            pts = sorted((p for p in a["pts"] if p[4] == "a" and p[5] is not None and isinstance(p[3], (int, float))),
                         key=lambda p: p[0])
            if not pts:
                continue
            arrived = "arrived degraded" if pts[0][5] < 8 else "arrived healthy"
            grp = "narrowbody" if a["type"] in NARROW else "other types"
            minutes = set()
            for p in pts:
                if not inside(p[1], p[2], area):
                    continue
                m = int(p[0] // 60)
                if m in minutes:
                    continue
                minutes.add(m)
                h = (m // 60) % 24
                per = "night" if h in NIGHT else "day" if h in DAY else None
                b = next((name for lo, hi, name in BANDS if lo <= p[3] < hi), None)
                if not per or not b:
                    continue
                keys = [(per, b)] + ([(per, grp), (per, arrived)] if b == "FL300+" else [])
                for k in keys:
                    tot[k][0] += 1; tot[k][1] += p[5] < 8
    print(f"{day}: night (22-04Z) vs day (08-17Z), degraded share of ADS-B aircraft-minutes in {area}")
    for k in [b[2] for b in BANDS] + ["narrowbody", "other types", "arrived healthy", "arrived degraded"]:
        n, d = tot[("night", k)], tot[("day", k)]
        label = k if k.startswith("FL") else "FL300+, " + k
        print(f"  {label:28} night {100 * n[1] / n[0] if n[0] else 0:5.1f}% of {n[0]:6d}   day {100 * d[1] / d[0] if d[0] else 0:5.1f}% of {d[0]:6d}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["extract", "report", "night"])
    ap.add_argument("args", nargs="+")
    ap.add_argument("--box", type=parse_box, default=BOX)
    ap.add_argument("--region", type=parse_box, default=REGION)
    ap.add_argument("--area", type=parse_box, default=(53.0, 60.0, 14.0, 26.0),
                    help="night: the area compared (default the Baltic side of the 02Z test, 53-60N 14-26E)")
    ap.add_argument("--min-alt", type=int, default=10000)
    ap.add_argument("--gap", type=float, default=4.0, help="minutes without a position that count as a gap")
    ap.add_argument("--max-join", type=float, default=45.0, help="longest gap (minutes) still joined into one track")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--all-aircraft", action="store_true",
                    help="also count aircraft that never sent an ADS-B position in the region (MLAT-only equipage)")
    a = ap.parse_args()
    if a.cmd == "extract":
        raw_dir, day = a.args
        extract(raw_dir, day, a.region, a.workers)
    elif a.cmd == "night":
        for day in a.args:
            night(day, a.area)
    else:
        for day in a.args:
            report(day, a.box, a.min_alt, a.gap * 60, a.max_join * 60, adsb_only=not a.all_aircraft)


if __name__ == "__main__":
    main()
