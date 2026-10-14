#!/usr/bin/env python3
"""pnt_daily.py — one adsb.lol day -> per-hex GNSS degradation, daily and hourly (PNT processor v1.1).

Method (docs/method-card.md):
  * Reports: ADS-B version 2, type adsb_icao only (no MLAT/TIS-B/ADS-R, no '~' non-ICAO addresses), airborne
    (baro altitude >= 1,000 ft), sampled at most once per SAMPLE_S seconds per aircraft, inside the UTC day.
  * Two thresholds per report:
      gross:     NACp < 8  (EPU >= 0.05 NM, ~93 m)  — jamming-scale loss; NIC < 7 tracked alongside
      accuracy:  NACp < 10 (EPU >= 10 m)            — fine degradation, sensitive to space weather
  * An aircraft is bad in a hex (and in a hex-hour) if >= 50% of its reports there are bad.
  * Avionics suspects (v1.1, peer test): an aircraft is dropped for the day if >= 80% of its reports are gross-bad AND,
    in the hex-hours where it is bad and has >= 2 peers, >= 75% have peers mostly good (< 25% of peers bad),
    judged over >= 3 such hex-hours. Faulty avionics are bad where others are fine; a jammed flight is bad where
    others are bad too, so it stays in.
  * Hex score, as GPSJam publishes it: 100 * max(bad - 1, 0) / (good + bad).

Input is the day's tar, or its split parts (.tar.aa, .tar.ab ...), read as one stream without unpacking. The raw
bytes are SHA-256 hashed during the same pass, for provenance.

Output (in --out, default data/pnt/daily):
  YYYY-MM-DD.parquet         h3, lat, lon, aircraft, bad_nacp, bad_nic, bad_acc10, score, score_acc10, capable, cap_bad_acc10
  YYYY-MM-DD.hourly.parquet  h3, hour, aircraft, bad_nacp, bad_nic, bad_acc10, capable, cap_bad_acc10
  YYYY-MM-DD.minute.parquet  h3, minute (0-1439), bad_nacp (aircraft with a gross-bad report that minute; nonzero rows only)
  YYYY-MM-DD.summary.json    inputs, hashes, counts, timings, method parameters, suspect diagnostics

Usage
  python pipeline/pnt_daily.py 2025-10-16 --raw <folder with v2025.10.16-planes-readsb-prod-0.tar*>
"""
import argparse, gzip, hashlib, io, json, os, sys, tarfile, time
from collections import defaultdict
from datetime import datetime, timezone
from multiprocessing import Pool

import h3, orjson

METHOD_VERSION = "1.2"
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
BATCH = 400           # trace files per worker task


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


def score_trace(raw, day0):
    """One trace file -> aircraft record, or None if not usable.

    Record: (cells, meta, bad_minutes). cells: {(h3_int, hour): [reports, gross_bad, nic_bad, acc_bad]};
    bad_minutes: sorted {(h3_int, minute_of_day)} with at least one gross-bad report (for burst timing);
    meta: (used, gross_bad, sum_lat, sum_lon, first_t, last_t, type, acc_capable).
    acc_capable: the aircraft reported NACp >= 10 at least once that day, so NACp < 10 is a change for it, not its
    normal equipage (many aircraft without SBAS report NACp 9 all the time).
    """
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    d = orjson.loads(raw)
    if d.get("icao", "~").startswith("~"):
        return None
    base = float(d.get("timestamp") or 0)
    nacp = nic = ver = None
    last_t = -1e9
    first_t = last_used_t = None
    cells = defaultdict(lambda: [0, 0, 0, 0])
    used = gross = 0
    cap = False
    bad_min = set()
    sum_lat = sum_lon = 0.0
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
        hour = int((base + p[0] - day0) // 3600)
        if not 0 <= hour < 24:
            continue  # outside the processed UTC day
        last_t = p[0]
        first_t = p[0] if first_t is None else first_t
        last_used_t = p[0]
        used += 1
        hx = h3.str_to_int(h3.latlng_to_cell(p[1], p[2], RES))
        c = cells[(hx, hour)]
        g = nacp < NACP_BAD
        if g:
            bad_min.add((hx, int((base + p[0] - day0) // 60)))
        c[0] += 1; c[1] += g; c[2] += nic < NIC_BAD; c[3] += nacp < NACP_ACC
        gross += g
        cap = cap or nacp >= NACP_ACC
        sum_lat += p[1]; sum_lon += p[2]
    if not used:
        return {}, (0, 0, 0.0, 0.0, 0, 0, "", False), []
    return dict(cells), (used, gross, sum_lat, sum_lon, first_t, last_used_t, d.get("t") or "", cap), sorted(bad_min)


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
    """Aircraft bad in a cell on measure k (1 gross, 2 NIC, 3 accuracy): >= 50% of its reports there."""
    return c[k] * 2 >= c[0]


def find_suspects(recs):
    """Peer test. Returns a set of record indexes to drop and a diagnostic list."""
    tot = defaultdict(lambda: [0, 0])   # (hex, hour) -> [aircraft, gross-bad aircraft]
    for cells, *_ in recs:
        for key, c in cells.items():
            t = tot[key]; t[0] += 1; t[1] += is_bad(c, 1)
    drop, where = set(), []
    for i, (cells, meta, _) in enumerate(recs):
        used, gross, slat, slon, t0, t1, typ, _ = meta
        if gross < SUSPECT_BAD_FRAC * used:
            continue
        judged = anomalous = 0
        for key, c in cells.items():
            if not is_bad(c, 1):
                continue
            n, nb = tot[key]
            peers, peers_bad = n - 1, nb - 1
            if peers < PEER_MIN:
                continue
            judged += 1
            anomalous += peers_bad / peers < PEER_BAD_MAX
        if judged >= SUSPECT_MIN_JUDGED and anomalous >= SUSPECT_ANOMALOUS_FRAC * judged:
            drop.add(i)
            where.append((round(slat / used, 1), round(slon / used, 1), round((t1 - t0) / 3600, 1), typ))
    return drop, where


def aggregate(recs, drop):
    # hex (or (hex, hour)) -> [aircraft, gross, nic, acc, capable aircraft, capable aircraft acc-bad]
    daily = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    hourly = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    minute = defaultdict(int)                    # (hex, minute) -> aircraft with a gross-bad report

    def add(t, c, cap):
        acc = is_bad(c, 3)
        t[0] += 1; t[1] += is_bad(c, 1); t[2] += is_bad(c, 2); t[3] += acc
        if cap:
            t[4] += 1; t[5] += acc

    for i, (cells, meta, bad_minutes) in enumerate(recs):
        if i in drop:
            continue
        cap = meta[7]
        for key in bad_minutes:
            minute[key] += 1
        per_hex = defaultdict(lambda: [0, 0, 0, 0])
        for (hx, hour), c in cells.items():
            add(hourly[(hx, hour)], c, cap)
            ph = per_hex[hx]
            for k in range(4):
                ph[k] += c[k]
        for hx, c in per_hex.items():   # daily: the aircraft's reports in the hex over the whole day
            add(daily[hx], c, cap)
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
    drop, where = find_suspects(recs)
    daily, hourly, minute = aggregate(recs, drop)
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
    }), os.path.join(out_dir, f"{day}.hourly.parquet"), compression="zstd")
    mrows = sorted(minute.items())
    pq.write_table(pa.table({
        "h3": [h3.int_to_str(hx) for (hx, _), _ in mrows],
        "minute": pa.array([m for (_, m), _ in mrows], pa.int16()),
        "bad_nacp": pa.array([v for _, v in mrows], pa.int32()),
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
                   "suspect": {"min_gross_bad_frac": SUSPECT_BAD_FRAC, "peer_min": PEER_MIN,
                               "peer_bad_max": PEER_BAD_MAX, "anomalous_frac": SUSPECT_ANOMALOUS_FRAC,
                               "min_judged_hex_hours": SUSPECT_MIN_JUDGED},
                   "score": "100*max(bad-1,0)/(good+bad)"},
        "source": "adsb.lol globe_history (ODbL 1.0)",
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
    print(json.dumps({k: s[k] for k in ("day", "seconds", "files", "aircraft", "avionics_suspects", "hexes", "hex_hours", "reports_used")}))


if __name__ == "__main__":
    main()
