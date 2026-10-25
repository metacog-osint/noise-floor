#!/usr/bin/env python3
"""roll_turn.py: roll angle against GNSS turn rate, an inertial check on ADS-B tracks (pre-registered method in
docs/validation/roll-turn.md; thresholds there are fixed and must not be tuned here).

  python tools/roll_turn.py run 2026-06-20 [--raw data/raw/trace_box/2026-06-20]   # one day -> data/roll_turn/
  python tools/roll_turn.py report 2026-01-02 2026-01-15 ...                         # the pre-registered checks

Pairs: consecutive ADS-B (adsb_icao) points of one ICAO aircraft with track and ground speed, 8-40 s apart, the later
one with roll and indicated airspeed, at 10,000 ft or more, IAS >= 150 kt, |roll| <= 45 deg.
  omega_exp = g * tan(roll) / TAS (TAS from IAS and ISA density at the barometric altitude), omega_obs = wrapped track
  change / dt, both in deg/s. Mismatch pair: |omega_obs - omega_exp| >= 1.0 deg/s. Mismatch run: >= 3 consecutive
  mismatch pairs spanning >= 60 s.
Each pair is tagged with the day's v0.4 spoofing episodes (data/spoofing_v04/<day>.events.json.gz): "active" if it falls
inside an active episode of the same aircraft, "other" inside any other episode class, else "none".

Output data/roll_turn/<day>.hours.parquet (local: holds ICAO addresses, like the spoofing events): one row per aircraft,
UTC hour and episode tag: n_pairs, n_mismatch, runs (mismatch runs starting there), lat, lon (median of the pairs),
nacp_bad (pairs whose current NACp < 8). Plus <day>.summary.json. Derived from adsb.lol (ODbL 1.0).
"""
import argparse, gzip, io, json, math, os, sys, time
from collections import defaultdict
from datetime import datetime, timezone
from multiprocessing import Pool

import orjson
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import pnt_daily as P  # noqa: E402  (Chain, day_parts, batches)

OUT = os.path.join(ROOT, "data", "roll_turn")
SPOOF = os.path.join(ROOT, "data", "spoofing_v04")
G, KT = 9.80665, 0.514444
DT_MIN, DT_MAX = 8.0, 40.0
MIN_ALT_FT, MIN_IAS_KT, MAX_ROLL = 10000, 150, 45.0
MISMATCH_DEG_S, RUN_PAIRS, RUN_SPAN_S = 1.0, 3, 60.0
CONTROL = (48.0, 52.0, 5.0, 15.0)
BALTIC = (53.0, 61.0, 14.0, 32.0)


def density_ratio(alt_ft):
    """ISA density / sea-level density at a pressure altitude (troposphere, then the isothermal layer)."""
    h = alt_ft * 0.3048
    if h <= 11000.0:
        t = 288.15 - 0.0065 * h
        p = 101325.0 * (t / 288.15) ** 5.25588
    else:
        t = 216.65
        p = 22632.06 * math.exp(-G * (h - 11000.0) / (287.05287 * t))
    return (p / (287.05287 * t)) / 1.225


def expected_rate(roll_deg, ias_kt, alt_ft):
    """Coordinated-turn rate in deg/s from bank and airspeed (TAS from IAS by the density ratio)."""
    tas = ias_kt * KT / math.sqrt(density_ratio(alt_ft))
    return math.degrees(G * math.tan(math.radians(roll_deg)) / tas)


def wrap(a):
    return (a + 180.0) % 360.0 - 180.0


def trace_pairs(d, day0):
    """[(t_epoch, lat, lon, residual, nacp_bad)] for one parsed trace, in time order."""
    base = float(d.get("timestamp") or 0)
    out, anchor, nacp = [], None, None
    for p in d.get("trace", []):
        det = p[8] if len(p) > 8 else None
        if det:
            nacp = det.get("nac_p", nacp)
        if (p[9] if len(p) > 9 else None) != "adsb_icao" or p[5] is None or p[4] is None:
            continue
        alt = p[3]
        if alt == "ground" or alt is None or alt < MIN_ALT_FT:
            anchor = None
            continue
        t = base + p[0]
        if anchor is None or t - anchor[0] > DT_MAX:
            anchor = (t, p[5])
            continue
        dt = t - anchor[0]
        if dt < DT_MIN:
            continue
        roll = p[13] if len(p) > 13 else None
        ias = p[12] if len(p) > 12 else None
        if roll is not None and ias is not None and ias >= MIN_IAS_KT and abs(roll) <= MAX_ROLL and 0 <= t - day0 < 86400:
            res = wrap(p[5] - anchor[1]) / dt - expected_rate(roll, ias, alt)
            out.append((t, p[1], p[2], res, nacp is not None and nacp < 8))
        anchor = (t, p[5])
    return out


def runs_of(pairs):
    """Indexes of the first pair of each mismatch run (>= RUN_PAIRS consecutive mismatches spanning >= RUN_SPAN_S, with
    no gap over DT_MAX between pairs)."""
    starts, i, n = [], 0, len(pairs)
    while i < n:
        if abs(pairs[i][3]) < MISMATCH_DEG_S:
            i += 1
            continue
        j = i
        while j + 1 < n and abs(pairs[j + 1][3]) >= MISMATCH_DEG_S and pairs[j + 1][0] - pairs[j][0] <= DT_MAX:
            j += 1
        if j - i + 1 >= RUN_PAIRS and pairs[j][0] - pairs[i][0] >= RUN_SPAN_S:
            starts.append(i)
        i = j + 1
    return starts


def tag_of(t, windows):
    """'active', 'other' or 'none' for a time against [(start, end, class)] of one aircraft."""
    tag = "none"
    for a, b, cls in windows:
        if a <= t <= b:
            if cls == "active":
                return "active"
            tag = "other"
    return tag


def work(args):
    batch, day0, episodes = args
    rows = defaultdict(lambda: [0, 0, 0, [], [], 0])    # (icao, hour, tag) -> [pairs, mismatch, runs, lats, lons, nacp_bad]
    n_ac = n_pairs = 0
    for raw in batch:
        try:
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            d = orjson.loads(raw)
        except Exception:
            continue
        icao = d.get("icao", "~")
        if icao.startswith("~"):
            continue
        pairs = trace_pairs(d, day0)
        if not pairs:
            continue
        n_ac += 1; n_pairs += len(pairs)
        win = episodes.get(icao, [])
        keys = [(icao, int((t - day0) // 3600), tag_of(t, win)) for t, *_ in pairs]
        for k, (t, la, lo, res, nb) in zip(keys, pairs):
            r = rows[k]
            r[0] += 1; r[1] += abs(res) >= MISMATCH_DEG_S; r[3].append(la); r[4].append(lo); r[5] += nb
        for i in runs_of(pairs):
            rows[keys[i]][2] += 1
    out = []
    for (icao, hour, tag), (n, m, runs, la, lo, nb) in rows.items():
        la.sort(); lo.sort()
        out.append((icao, hour, tag, n, m, runs, round(la[len(la) // 2], 3), round(lo[len(lo) // 2], 3), nb))
    return out, n_ac, n_pairs


def load_episodes(day):
    p = os.path.join(SPOOF, f"{day}.events.json.gz")
    eps = defaultdict(list)
    if not os.path.exists(p):
        return None
    for e in json.load(gzip.open(p, "rt", encoding="utf-8")):
        a = datetime.fromisoformat(e["start"].replace("Z", "+00:00")).timestamp()
        b = datetime.fromisoformat(e["end"].replace("Z", "+00:00")).timestamp()
        eps[e["icao"]].append((a, b, e.get("class")))
    return dict(eps)


def run(day, raw_dir, out_dir=OUT, workers=None):
    episodes = load_episodes(day)
    if episodes is None:
        raise SystemExit(f"no v0.4 spoofing events for {day}")
    day0 = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())
    t0 = time.time()
    stream = io.BufferedReader(P.Chain(P.day_parts(raw_dir, day)), buffer_size=8 << 20)
    rows, n_ac, n_pairs = [], 0, 0
    with Pool(workers or max(1, (os.cpu_count() or 2) - 1)) as pool:
        jobs = ((b, d0, episodes) for b, d0 in P.batches(stream, day0))
        for r, a, n in pool.imap_unordered(work, jobs, chunksize=1):
            rows.extend(r); n_ac += a; n_pairs += n
    os.makedirs(out_dir, exist_ok=True)
    cols = ("icao", "hour", "tag", "n_pairs", "n_mismatch", "runs", "lat", "lon", "nacp_bad")
    rows.sort()
    pq.write_table(pa.table({c: [r[i] for r in rows] for i, c in enumerate(cols)}), os.path.join(out_dir, f"{day}.hours.parquet"))
    s = {"day": day, "aircraft_with_pairs": n_ac, "pairs": n_pairs, "rows": len(rows), "seconds": round(time.time() - t0, 1),
         "episodes_aircraft": len(episodes), "input_sha256": stream.raw.sha.hexdigest(),
         "method": {"dt_s": [DT_MIN, DT_MAX], "min_alt_ft": MIN_ALT_FT, "min_ias_kt": MIN_IAS_KT, "max_roll_deg": MAX_ROLL,
                    "mismatch_deg_s": MISMATCH_DEG_S, "run_pairs": RUN_PAIRS, "run_span_s": RUN_SPAN_S},
         "licence": "ODbL 1.0; derived from adsb.lol (local file holds ICAO addresses)"}
    json.dump(s, open(os.path.join(out_dir, f"{day}.summary.json"), "w"), indent=1)
    print(json.dumps({k: s[k] for k in ("day", "aircraft_with_pairs", "pairs", "seconds")}))
    return s


def inside(r, b):
    return b[0] <= r["lat"] <= b[1] and b[2] <= r["lon"] <= b[3]


def report(days, out_dir=OUT):
    """The pre-registered checks over the given days. Unit: aircraft-hour (per tag) with >= 5 valid pairs."""
    rows = []
    for day in days:
        for r in pq.read_table(os.path.join(out_dir, f"{day}.hours.parquet")).to_pylist():
            r["day"] = day
            rows.append(r)
    ok = [r for r in rows if r["n_pairs"] >= 5]

    def rate(sel):
        n = len(sel); k = sum(1 for r in sel if r["runs"] > 0)
        return k, n, (100.0 * k / n if n else None)

    c1 = rate([r for r in ok if inside(r, CONTROL)])                      # as pre-registered: every aircraft-hour in the box
    c1u = rate([r for r in ok if r["tag"] == "none" and inside(r, CONTROL)])
    c2 = rate([r for r in ok if r["tag"] == "active"])
    c3 = rate([r for r in ok if r["tag"] == "none" and inside(r, BALTIC) and r["nacp_bad"] * 2 >= r["n_pairs"]])
    base = rate([r for r in ok if r["tag"] == "none"])
    pair_rate = lambda sel: 100.0 * sum(r["n_mismatch"] for r in sel) / max(1, sum(r["n_pairs"] for r in sel))
    out = {"days": days, "aircraft_hours_with_5_pairs": len(ok),
           "check1_control": {"runs": c1[0], "aircraft_hours": c1[1], "rate_pct": c1[2],
                              "pass": c1[2] is not None and c1[2] <= 1.0},
           "check1_control_untagged_only": {"runs": c1u[0], "aircraft_hours": c1u[1], "rate_pct": c1u[2]},
           "check2_active_spoofing": {"runs": c2[0], "aircraft_hours": c2[1], "rate_pct": c2[2],
                                      "pass": None if c2[1] < 30 else (c2[2] >= 5.0 and c1[2] is not None and c2[2] >= 5 * c1[2]),
                                      "untestable": c2[1] < 30},
           "check3_jammed_not_spoofed_baltic": {"runs": c3[0], "aircraft_hours": c3[1], "rate_pct": c3[2],
                                                "pass": None if not c3[1] else (c1[2] is not None and c3[2] <= 3 * max(c1[2], 1e-9))},
           "all_untagged": {"runs": base[0], "aircraft_hours": base[1], "rate_pct": base[2]},
           "mismatch_pair_pct": {"control": pair_rate([r for r in ok if r["tag"] == "none" and inside(r, CONTROL)]),
                                 "active": pair_rate([r for r in ok if r["tag"] == "active"])}}
    # exploratory: where untagged runs happen (res-2 cells by 5-degree box)
    where = defaultdict(lambda: [0, 0])
    for r in ok:
        if r["tag"] == "none":
            k = (5 * math.floor(r["lat"] / 5), 5 * math.floor(r["lon"] / 5))
            where[k][0] += 1; where[k][1] += r["runs"] > 0
    out["check4_untagged_by_5deg_box"] = sorted(([k[0], k[1], v[1], v[0], round(100 * v[1] / v[0], 2)] for k, v in where.items()
                                                 if v[0] >= 200), key=lambda x: -x[4])[:25]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["run", "report"])
    ap.add_argument("days", nargs="+")
    ap.add_argument("--raw")
    ap.add_argument("--workers", type=int)
    a = ap.parse_args()
    if a.cmd == "run":
        for day in a.days:
            run(day, a.raw or os.path.join(ROOT, "data", "raw", "trace_box", day), OUT, a.workers)
    else:
        print(json.dumps(report(a.days), indent=1))


if __name__ == "__main__":
    main()
