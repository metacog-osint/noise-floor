#!/usr/bin/env python3
"""pnt_daily.py — one adsb.lol day -> per-hex GNSS degradation (PNT processor v1).

Method (docs/method-card.md):
  * Reports: ADS-B version 2, type adsb_icao only (no MLAT/TIS-B/ADS-R, no '~' non-ICAO addresses), airborne
    (baro altitude >= 1,000 ft), sampled at most once per SAMPLE_S seconds per aircraft.
  * A report is bad if NACp < 8 (also tracked: NIC < 7). An aircraft is bad in an H3 res-4 hex if >= 50% of its
    reports there are bad.
  * Avionics suspects: an aircraft bad in >= 95% of its reports across >= MIN_SUSPECT_H hours airborne is dropped from
    every hex for the day (counted in the summary). Persistently bad avionics would otherwise paint whole routes.
  * Hex score, as GPSJam publishes it: 100 * max(bad - 1, 0) / (good + bad).

Input is the day's tar, or its split parts (.tar.aa, .tar.ab ...), read as one stream without unpacking. The raw
bytes are SHA-256 hashed during the same pass, for provenance.

Output (in --out, default data/pnt/daily):
  YYYY-MM-DD.parquet       h3, lat, lon, aircraft, bad_nacp, bad_nic, score
  YYYY-MM-DD.summary.json  inputs, hashes, counts, timings, method parameters

Usage
  python pipeline/pnt_daily.py 2025-10-16 --raw <folder with v2025.10.16-planes-readsb-prod-0.tar*>
"""
import argparse, gzip, hashlib, io, json, os, sys, tarfile, time
from collections import defaultdict
from multiprocessing import Pool

import h3, orjson

RES = 4
GOOD_TYPES = {"adsb_icao"}
NACP_BAD = 8          # NACp < 8: EPU >= 0.05 NM (93 m)
NIC_BAD = 7           # NIC < 7: Rc >= 0.2 NM
MIN_ALT_FT = 1000
SAMPLE_S = 30.0
SUSPECT_BAD_FRAC = 0.95
MIN_SUSPECT_H = 3.0
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


def score_trace(raw):
    """One trace file -> (per-hex [reports, bad_nacp, bad_nic], stats) or None if not usable."""
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    d = orjson.loads(raw)
    if d.get("icao", "~").startswith("~"):
        return None
    nacp = nic = ver = None
    last_t = -1e9
    first_t = last_used_t = None
    per_hex = defaultdict(lambda: [0, 0, 0])
    seen = used = bad = 0
    for p in d.get("trace", []):
        seen += 1
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
        last_t = p[0]
        first_t = p[0] if first_t is None else first_t
        last_used_t = p[0]
        used += 1
        c = per_hex[h3.latlng_to_cell(p[1], p[2], RES)]
        c[0] += 1; c[1] += nacp < NACP_BAD; c[2] += nic < NIC_BAD
        bad += nacp < NACP_BAD
    hours = ((last_used_t - first_t) / 3600) if used else 0
    suspect = used > 0 and hours >= MIN_SUSPECT_H and bad / used >= SUSPECT_BAD_FRAC
    return dict(per_hex), (seen, used, suspect)


def work(batch):
    hexes = defaultdict(lambda: [0, 0, 0])  # hex -> [aircraft, bad_nacp aircraft, bad_nic aircraft]
    st = defaultdict(int)
    for raw in batch:
        st["files"] += 1
        try:
            r = score_trace(raw)
        except Exception:
            st["parse_errors"] += 1
            continue
        if r is None:
            st["non_icao"] += 1
            continue
        per_hex, (seen, used, suspect) = r
        st["reports_seen"] += seen; st["reports_used"] += used
        if not used:
            continue
        st["aircraft"] += 1
        if suspect:
            st["avionics_suspects"] += 1
            continue
        for hx, (n, bn, bi) in per_hex.items():
            a = hexes[hx]
            a[0] += 1; a[1] += bn * 2 >= n; a[2] += bi * 2 >= n
    return dict(hexes), dict(st)


def batches(stream):
    with tarfile.open(fileobj=stream, mode="r|") as tf:
        cur = []
        for m in tf:
            if m.isfile() and "/traces/" in "/" + m.name.lstrip("./") and "trace_full_" in m.name:
                cur.append(tf.extractfile(m).read())
                if len(cur) >= BATCH:
                    yield cur; cur = []
        if cur:
            yield cur


def run(day, raw_dir, out_dir, workers):
    parts = day_parts(raw_dir, day)
    t0 = time.time()
    stream = io.BufferedReader(Chain(parts), buffer_size=8 << 20)
    total = defaultdict(lambda: [0, 0, 0])
    st = defaultdict(int)
    with Pool(workers) as pool:
        for hexes, s in pool.imap_unordered(work, batches(stream), chunksize=1):
            for hx, (n, bn, bi) in hexes.items():
                a = total[hx]; a[0] += n; a[1] += bn; a[2] += bi
            for k, v in s.items():
                st[k] += v
    chain = stream.raw
    secs = time.time() - t0

    import pyarrow as pa, pyarrow.parquet as pq
    rows = sorted(total.items())
    lat_lon = [h3.cell_to_latlng(hx) for hx, _ in rows]
    table = pa.table({
        "h3": [hx for hx, _ in rows],
        "lat": [round(a, 4) for a, _ in lat_lon],
        "lon": [round(b, 4) for _, b in lat_lon],
        "aircraft": [v[0] for _, v in rows],
        "bad_nacp": [v[1] for _, v in rows],
        "bad_nic": [v[2] for _, v in rows],
        "score": [round(100 * max(v[1] - 1, 0) / v[0], 2) for _, v in rows],
    })
    os.makedirs(out_dir, exist_ok=True)
    pq.write_table(table, os.path.join(out_dir, f"{day}.parquet"), compression="zstd")
    summary = {
        "day": day, "inputs": [os.path.basename(p) for p in parts], "input_bytes": chain.nbytes,
        "input_sha256": chain.sha.hexdigest(), "seconds": round(secs, 1), "workers": workers, "hexes": len(rows),
        **{k: st.get(k, 0) for k in ("files", "aircraft", "avionics_suspects", "non_icao", "parse_errors",
                                      "reports_seen", "reports_used")},
        "method": {"h3_res": RES, "types": sorted(GOOD_TYPES), "adsb_version": 2, "nacp_bad_below": NACP_BAD,
                   "nic_bad_below": NIC_BAD, "min_alt_ft": MIN_ALT_FT, "sample_s": SAMPLE_S,
                   "aircraft_bad_if_frac_reports_bad_ge": 0.5, "suspect_bad_frac": SUSPECT_BAD_FRAC,
                   "suspect_min_hours": MIN_SUSPECT_H, "score": "100*max(bad-1,0)/(good+bad)"},
        "source": "adsb.lol globe_history (ODbL 1.0)",
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
    print(json.dumps({k: s[k] for k in ("day", "seconds", "files", "aircraft", "avionics_suspects", "hexes", "reports_used")}))


if __name__ == "__main__":
    main()
