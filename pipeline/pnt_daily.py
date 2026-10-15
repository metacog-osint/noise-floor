#!/usr/bin/env python3
"""pnt_daily.py — one adsb.lol day -> per-hex GNSS degradation, daily, hourly and per minute (PNT processor v1.3).

Method (docs/method-card.md):
  * Reports: ADS-B version 2, type adsb_icao only (no MLAT/TIS-B/ADS-R, no '~' non-ICAO addresses), airborne
    (baro altitude >= 1,000 ft), sampled at most once per SAMPLE_S seconds per aircraft, inside the UTC day.
  * Two thresholds per report:
      gross:     NACp < 8  (EPU >= 0.05 NM, ~93 m)  — jamming-scale loss; NIC < 7 tracked alongside
      accuracy:  NACp < 10 (EPU >= 10 m)            — fine degradation, sensitive to space weather
  * An aircraft is bad in a hex (and in a hex-hour) if >= 50% of its reports there are bad.
  * Latching (v1.3): some avionics hold NACp/NIC degraded until reset after landing. A report is a latch candidate
    if it belongs to the aircraft's final gross-bad run of the day (no recovery in flight; gaps up to EPISODE_GAP_S),
    that run lasts >= LATCH_MIN_S, and the report is >= LATCH_MIN_KM from where the run began. A candidate is
    latched where its hex-hour peers are mostly good (same peer rule as suspects); where peers are bad too, the
    aircraft is still inside interference and the report stays live. Latched reports are counted in `latched` and
    left out of `bad_nacp_live`; `bad_nacp` stays raw, comparable with GPSJam.
  * Avionics suspects (peer test, on live reports): an aircraft is dropped for the day if >= 80% of its reports are
    live gross-bad AND, in the hex-hours where it is bad and has >= 2 peers, >= 75% have peers mostly good
    (< 25% of peers bad), judged over >= 3 such hex-hours.
  * Hex score, as GPSJam publishes it: 100 * max(bad - 1, 0) / (good + bad).

Input is the day's tar, or its split parts (.tar.aa, .tar.ab ...), read as one stream without unpacking. The raw
bytes are SHA-256 hashed during the same pass, for provenance.

Output (in --out, default data/pnt/daily):
  YYYY-MM-DD.parquet         h3, lat, lon, aircraft, bad_nacp, bad_nic, bad_acc10, score, score_acc10, capable,
                             cap_bad_acc10, latched, bad_nacp_live, score_live
  YYYY-MM-DD.hourly.parquet  h3, hour, aircraft, bad_nacp, bad_nic, bad_acc10, capable, cap_bad_acc10, latched, bad_nacp_live
  YYYY-MM-DD.minute.parquet  h3, minute (0-1439), bad_nacp, latched (aircraft with a gross-bad / latched report that
                             minute; nonzero rows only)
  YYYY-MM-DD.summary.json    inputs, hashes, counts, timings, method parameters, suspect and latch diagnostics

Usage
  python pipeline/pnt_daily.py 2025-10-16 --raw <folder with v2025.10.16-planes-readsb-prod-0.tar*>
"""
import argparse, gzip, hashlib, io, json, math, os, sys, tarfile, time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from multiprocessing import Pool

import h3, orjson

METHOD_VERSION = "1.3"
RES = 4
GOOD_TYPES = {"adsb_icao"}
NACP_BAD = 8          # gross: NACp < 8, EPU >= 0.05 NM (93 m)
NIC_BAD = 7           # NIC < 7: Rc >= 0.2 NM
NACP_ACC = 10         # accuracy: NACp < 10, EPU >= 10 m
MIN_ALT_FT = 1000
SAMPLE_S = 30.0
SUSPECT_BAD_FRAC = 0.80
PEER_MIN = 2          # peers needed in a hex-hour to judge it
PEER_BAD_MAX = 0.25   # peers "mostly good" below this bad share
SUSPECT_ANOMALOUS_FRAC = 0.75
SUSPECT_MIN_JUDGED = 3
EPISODE_GAP_S = 1800  # a gap longer than this between reports breaks a bad run
LATCH_MIN_S = 1800    # the final bad run must last at least this long
LATCH_MIN_KM = 300.0  # and a report must be at least this far from the run's onset to be a latch candidate
BATCH = 400           # trace files per worker task

# cell layout: [reports, gross bad, nic bad, acc bad, latch-candidate gross-bad reports]
R, G, N, A, L = range(5)


class Chain(io.RawIOBase):
    """Read several files as one stream and hash every byte that passes through."""

    def __init__(self, paths):
        self.paths, self.i, self.f = list(paths), 0, None
        self.sha = hashlib.sha256()
        self.nbytes = 0

    def readable(self):
        return True

    def readinto(self, b):
        while True:
            if self.f is None:
                if self.i >= len(self.paths):
                    return 0
                self.f = open(self.paths[self.i], "rb"); self.i += 1
            n = self.f.readinto(b)
            if n:
                self.sha.update(memoryview(b)[:n]); self.nbytes += n
                return n
            self.f.close(); self.f = None


def day_parts(raw_dir, day):
    """Prefer split parts (.tar.aa, .tar.ab ...) when present: some whole .tar files on disk are truncated copies."""
    stem = f"v{day.replace('-', '.')}-planes-readsb-prod-0.tar"
    parts = sorted(p for p in os.listdir(raw_dir) if p.startswith(stem + "."))
    if parts:
        return [os.path.join(raw_dir, p) for p in parts]
    whole = os.path.join(raw_dir, stem)
    if os.path.exists(whole):
        return [whole]
    raise FileNotFoundError(f"no {stem}[.aa ...] in {raw_dir}")


def km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 12742.0 * math.asin(min(1.0, math.sqrt(a)))


def latch_candidates(rep):
    """Indexes of latch-candidate reports and the onset (lat, lon) of the final bad run, or (set(), None).

    rep: [(t, lat, lon, gross_bad)] in time order (used reports only)."""
    if not rep or not rep[-1][3]:
        return set(), None
    s = len(rep) - 1
    while s > 0 and rep[s - 1][3] and rep[s][0] - rep[s - 1][0] <= EPISODE_GAP_S:
        s -= 1
    if rep[-1][0] - rep[s][0] < LATCH_MIN_S:
        return set(), None
    lat0, lon0 = rep[s][1], rep[s][2]
    idx = {i for i in range(s, len(rep)) if km(lat0, lon0, rep[i][1], rep[i][2]) >= LATCH_MIN_KM}
    return idx, ((round(lat0, 2), round(lon0, 2)) if idx else None)


def score_trace(raw, day0):
    """One trace file -> aircraft record, or None if not usable.

    Record: (cells, meta, bad_minutes).
      cells: {(h3_int, hour): [reports, gross_bad, nic_bad, acc_bad, latch_candidate_bad]}
      meta: (used, gross_bad, sum_lat, sum_lon, first_t, last_t, type, acc_capable, latch_onset)
        acc_capable: the aircraft reported NACp >= 10 at least once that day, so NACp < 10 is a change for it, not its
        normal equipage (many aircraft without SBAS report NACp 9 all the time).
      bad_minutes: sorted [(h3_int, minute_of_day, latch_candidate)] with at least one gross-bad report.
    """
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    d = orjson.loads(raw)
    if d.get("icao", "~").startswith("~"):
        return None
    base = float(d.get("timestamp") or 0)
    nacp = nic = ver = None
    last_t = -1e9
    rep = []                     # (t, lat, lon, gross_bad, hx, hour, minute, nic_bad, acc_bad)
    cap = False
    for p in d.get("trace", []):
        det = p[8] if len(p) > 8 else None
        if det:
            nacp = det.get("nac_p", nacp); nic = det.get("nic", nic); ver = det.get("version", ver)
        if p[0] - last_t < SAMPLE_S:
            continue
        if (p[9] if len(p) > 9 else None) not in GOOD_TYPES or ver != 2 or nacp is None or nic is None:
            continue
        alt = p[3]
        if alt == "ground" or alt is None or alt < MIN_ALT_FT:
            continue
        sec = base + p[0] - day0
        hour = int(sec // 3600)
        if not 0 <= hour < 24:
            continue  # outside the processed UTC day
        last_t = p[0]
        cap = cap or nacp >= NACP_ACC
        rep.append((p[0], p[1], p[2], nacp < NACP_BAD, h3.str_to_int(h3.latlng_to_cell(p[1], p[2], RES)), hour,
                    int(sec // 60), nic < NIC_BAD, nacp < NACP_ACC))
    if not rep:
        return {}, (0, 0, 0.0, 0.0, 0, 0, "", False, None), []
    cand, onset = latch_candidates([(r[0], r[1], r[2], r[3]) for r in rep])
    cells = defaultdict(lambda: [0, 0, 0, 0, 0])
    bad_min = {}
    for i, (t, la, lo, g, hx, hour, minute, nb, ab) in enumerate(rep):
        c = cells[(hx, hour)]
        c[R] += 1; c[G] += g; c[N] += nb; c[A] += ab; c[L] += g and i in cand
        if g:
            bad_min[(hx, minute)] = bad_min.get((hx, minute), False) or i in cand
    gross = sum(r[3] for r in rep)
    meta = (len(rep), gross, sum(r[1] for r in rep), sum(r[2] for r in rep), rep[0][0], rep[-1][0], d.get("t") or "", cap, onset)
    return dict(cells), meta, sorted((hx, m, c) for (hx, m), c in bad_min.items())


def work(args):
    batch, day0 = args
    recs, st = [], defaultdict(int)
    for raw in batch:
        st["files"] += 1
        try:
            r = score_trace(raw, day0)
        except Exception:
            st["parse_errors"] += 1
            continue
        if r is None:
            st["non_icao"] += 1
            continue
        if r[1][0]:
            recs.append(r)
    return recs, dict(st)


def batches(stream, day0):
    with tarfile.open(fileobj=stream, mode="r|") as tf:
        cur = []
        for m in tf:
            if m.isfile() and "/traces/" in "/" + m.name.lstrip("./") and "trace_full_" in m.name:
                cur.append(tf.extractfile(m).read())
                if len(cur) >= BATCH:
                    yield cur, day0; cur = []
        if cur:
            yield cur, day0


def is_bad(c, k):
    """Aircraft bad in a cell on measure k: >= 50% of its reports there."""
    return c[k] * 2 >= c[R]


def hex_hour_totals(recs):
    tot = defaultdict(lambda: [0, 0])   # (hex, hour) -> [aircraft, gross-bad aircraft]
    for cells, *_ in recs:
        for key, c in cells.items():
            t = tot[key]; t[0] += 1; t[1] += is_bad(c, G)
    return tot


def peers_mostly_good(tot, key, self_bad):
    """True / False when judgeable (>= PEER_MIN peers), None otherwise."""
    n, nb = tot[key]
    peers, peers_bad = n - 1, nb - (1 if self_bad else 0)
    if peers < PEER_MIN:
        return None
    return peers_bad / peers < PEER_BAD_MAX


def resolve_latching(recs, tot):
    """Per record: the set of (hex, hour) cells where its latch candidates are confirmed latched (peers mostly good).
    Returns (latched_cells per record, diagnostics)."""
    out, onsets, unjudged, confirmed_aircraft = [], Counter(), 0, 0
    for cells, meta, _ in recs:
        lc = set()
        for key, c in cells.items():
            if c[L] and is_bad(c, G):
                ok = peers_mostly_good(tot, key, True)
                if ok:
                    lc.add(key)
                elif ok is None:
                    unjudged += 1
        if lc:
            confirmed_aircraft += 1
            if meta[8]:
                onsets[h3.cell_to_parent(h3.latlng_to_cell(meta[8][0], meta[8][1], 4), 2)] += 1
        out.append(lc)
    diag = {"latched_aircraft": confirmed_aircraft, "latch_candidate_cells_unjudged": unjudged,
            "latch_onset_regions_res2": [[c, *[round(x, 2) for x in h3.cell_to_latlng(c)], n] for c, n in onsets.most_common(30)]}
    return out, diag


def live(c, latched_cell):
    """Cell counts with confirmed latched reports removed from gross-bad."""
    return c[G] - (c[L] if latched_cell else 0)


def find_suspects(recs, tot, latched):
    """Peer test on live reports. Returns a set of record indexes to drop and a diagnostic list."""
    drop, where = set(), []
    for i, (cells, meta, _) in enumerate(recs):
        used, _, slat, slon, t0, t1, typ, _, _ = meta
        live_gross = sum(live(c, key in latched[i]) for key, c in cells.items())
        if live_gross < SUSPECT_BAD_FRAC * used:
            continue
        judged = anomalous = 0
        for key, c in cells.items():
            if not is_bad(c, G) or key in latched[i]:
                continue
            ok = peers_mostly_good(tot, key, True)
            if ok is None:
                continue
            judged += 1; anomalous += ok
        if judged >= SUSPECT_MIN_JUDGED and anomalous >= SUSPECT_ANOMALOUS_FRAC * judged:
            drop.add(i)
            where.append((round(slat / used, 1), round(slon / used, 1), round((t1 - t0) / 3600, 1), typ))
    return drop, where


def aggregate(recs, drop, latched):
    # hex (or (hex, hour)) -> [aircraft, gross, nic, acc, capable, capable acc-bad, latched, live gross]
    daily = defaultdict(lambda: [0] * 8)
    hourly = defaultdict(lambda: [0] * 8)
    minute = defaultdict(lambda: [0, 0])          # (hex, minute) -> [aircraft gross-bad, aircraft latched]

    def add(t, c, cap, lat_reports):
        acc = is_bad(c, A)
        t[0] += 1; t[1] += is_bad(c, G); t[2] += is_bad(c, N); t[3] += acc
        if cap:
            t[4] += 1; t[5] += acc
        lat = lat_reports * 2 >= c[R] and lat_reports > 0
        t[6] += lat
        t[7] += (c[G] - lat_reports) * 2 >= c[R] and c[G] - lat_reports > 0

    for i, (cells, meta, bad_minutes) in enumerate(recs):
        if i in drop:
            continue
        cap, lc = meta[7], latched[i]
        per_hex = defaultdict(lambda: [0, 0, 0, 0, 0])
        per_hex_lat = defaultdict(int)
        for (hx, hour), c in cells.items():
            lr = c[L] if (hx, hour) in lc else 0
            add(hourly[(hx, hour)], c, cap, lr)
            ph = per_hex[hx]
            for k in range(5):
                ph[k] += c[k]
            per_hex_lat[hx] += lr
        for hx, c in per_hex.items():   # daily: the aircraft's reports in the hex over the whole day
            add(daily[hx], c, cap, per_hex_lat[hx])
        for hx, m, cand in bad_minutes:
            x = minute[(hx, m)]; x[0] += 1; x[1] += cand and (hx, m // 60) in lc
    return daily, hourly, minute


def score(bad, n):
    return round(100 * max(bad - 1, 0) / n, 2)


def run(day, raw_dir, out_dir, workers):
    parts = day_parts(raw_dir, day)
    day0 = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())
    t0 = time.time()
    stream = io.BufferedReader(Chain(parts), buffer_size=8 << 20)
    recs, st = [], defaultdict(int)
    with Pool(workers) as pool:
        for r, s in pool.imap_unordered(work, batches(stream, day0), chunksize=1):
            recs.extend(r)
            for k, v in s.items():
                st[k] += v
    chain = stream.raw
    t_read = time.time() - t0
    tot = hex_hour_totals(recs)
    latched, latch_diag = resolve_latching(recs, tot)
    drop, where = find_suspects(recs, tot, latched)
    daily, hourly, minute = aggregate(recs, drop, latched)
    secs = time.time() - t0

    import pyarrow as pa, pyarrow.parquet as pq
    rows = sorted(daily.items())
    hexes = [h3.int_to_str(hx) for hx, _ in rows]
    lat_lon = [h3.cell_to_latlng(h) for h in hexes]
    os.makedirs(out_dir, exist_ok=True)
    pq.write_table(pa.table({
        "h3": hexes,
        "lat": [round(a, 4) for a, _ in lat_lon],
        "lon": [round(b, 4) for _, b in lat_lon],
        "aircraft": [v[0] for _, v in rows],
        "bad_nacp": [v[1] for _, v in rows],
        "bad_nic": [v[2] for _, v in rows],
        "bad_acc10": [v[3] for _, v in rows],
        "score": [score(v[1], v[0]) for _, v in rows],
        "score_acc10": [score(v[3], v[0]) for _, v in rows],
        "capable": [v[4] for _, v in rows],
        "cap_bad_acc10": [v[5] for _, v in rows],
        "latched": [v[6] for _, v in rows],
        "bad_nacp_live": [v[7] for _, v in rows],
        "score_live": [score(v[7], v[0]) for _, v in rows],
    }), os.path.join(out_dir, f"{day}.parquet"), compression="zstd")
    hrows = sorted(hourly.items())
    pq.write_table(pa.table({
        "h3": [h3.int_to_str(hx) for (hx, _), _ in hrows],
        "hour": pa.array([hr for (_, hr), _ in hrows], pa.int8()),
        "aircraft": [v[0] for _, v in hrows],
        "bad_nacp": [v[1] for _, v in hrows],
        "bad_nic": [v[2] for _, v in hrows],
        "bad_acc10": [v[3] for _, v in hrows],
        "capable": [v[4] for _, v in hrows],
        "cap_bad_acc10": [v[5] for _, v in hrows],
        "latched": [v[6] for _, v in hrows],
        "bad_nacp_live": [v[7] for _, v in hrows],
    }), os.path.join(out_dir, f"{day}.hourly.parquet"), compression="zstd")
    mrows = sorted(minute.items())
    pq.write_table(pa.table({
        "h3": [h3.int_to_str(hx) for (hx, _), _ in mrows],
        "minute": pa.array([m for (_, m), _ in mrows], pa.int16()),
        "bad_nacp": pa.array([v[0] for _, v in mrows], pa.int32()),
        "latched": pa.array([v[1] for _, v in mrows], pa.int32()),
    }), os.path.join(out_dir, f"{day}.minute.parquet"), compression="zstd")
    summary = {
        "day": day, "method_version": METHOD_VERSION, "inputs": [os.path.basename(p) for p in parts],
        "input_bytes": chain.nbytes, "input_sha256": chain.sha.hexdigest(),
        "seconds": round(secs, 1), "seconds_read": round(t_read, 1), "workers": workers,
        "hexes": len(rows), "hex_hours": len(hrows), "aircraft": len(recs), "avionics_suspects": len(drop),
        "reports_used": sum(m[0] for _, m, _ in recs), "bad_hex_minutes": len(minute),
        **{k: st.get(k, 0) for k in ("files", "non_icao", "parse_errors")},
        "method": {"h3_res": RES, "types": sorted(GOOD_TYPES), "adsb_version": 2, "nacp_bad_below": NACP_BAD,
                   "nic_bad_below": NIC_BAD, "nacp_acc_bad_below": NACP_ACC,
                   "acc_capable_if_any_report_nacp_ge": NACP_ACC, "min_alt_ft": MIN_ALT_FT,
                   "sample_s": SAMPLE_S, "aircraft_bad_if_frac_reports_bad_ge": 0.5,
                   "suspect": {"min_live_gross_bad_frac": SUSPECT_BAD_FRAC, "peer_min": PEER_MIN,
                               "peer_bad_max": PEER_BAD_MAX, "anomalous_frac": SUSPECT_ANOMALOUS_FRAC,
                               "min_judged_hex_hours": SUSPECT_MIN_JUDGED},
                   "latch": {"final_bad_run_min_s": LATCH_MIN_S, "episode_gap_s": EPISODE_GAP_S,
                             "min_km_from_onset": LATCH_MIN_KM, "confirmed_if_peers_mostly_good": True},
                   "score": "100*max(bad-1,0)/(good+bad)"},
        "source": "adsb.lol globe_history (ODbL 1.0)",
        "latching": latch_diag,
        "avionics_suspect_centroids": sorted(where),   # [mean lat, mean lon, hours, type]; no identifiers
    }
    json.dump(summary, open(os.path.join(out_dir, f"{day}.summary.json"), "w"), indent=1)
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("day", help="YYYY-MM-DD")
    ap.add_argument("--raw", required=True, help="folder holding the day's adsb.lol tar or split parts")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "pnt", "daily"))
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()
    s = run(a.day, a.raw, a.out, a.workers)
    print(json.dumps({k: s[k] for k in ("day", "seconds", "files", "aircraft", "avionics_suspects", "hexes", "hex_hours", "reports_used")}
                     | {"latched_aircraft": s["latching"]["latched_aircraft"]}))


if __name__ == "__main__":
    main()
