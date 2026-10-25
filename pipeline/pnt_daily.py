#!/usr/bin/env python3
"""pnt_daily.py — one adsb.lol day -> per-hex GNSS degradation, daily, hourly and per minute (PNT processor v1.4).

Method (docs/method-card.md):
  * Reports: ADS-B version 2, type adsb_icao only (no MLAT/TIS-B/ADS-R, no '~' non-ICAO addresses), airborne
    (baro altitude >= 1,000 ft), sampled at most once per SAMPLE_S seconds per aircraft, inside the UTC day.
  * Two thresholds per report:
      gross:     NACp < 8  (EPU >= 0.05 NM, ~93 m)  — jamming-scale loss; NIC < 7 tracked alongside
      accuracy:  NACp < 10 (EPU >= 10 m)            — fine degradation, sensitive to space weather
  * An aircraft is bad in a hex (and in a hex-hour) if >= 50% of its reports there are bad.
  * Post-exposure (v1.4; replaces v1.3 latching): an aircraft's exposure point is its first hex-hour with a gross-bad
    report where its peers were bad too (genuine interference: >= PEER_MIN peers, >= 25% of them bad). Any LATER
    hex-hour with gross-bad reports >= POST_MIN_KM from the exposure point, where peers are mostly good, is
    post-exposure: avionics still degraded (latched, or flipping on and off) after leaving interference, not new
    interference where it is seen. No continuity is required (v1.3 required an unbroken final run and missed the
    intermittent case, dominated by A350s on 21-25 Oct 2025). Post-exposure reports are counted in `latched` and left
    out of `bad_nacp_live`; `bad_nacp` stays raw, comparable with GPSJam.
  * Avionics suspects (peer test, on live reports): an aircraft is dropped for the day if >= 80% of its reports are
    live gross-bad AND, in the hex-hours where it is bad and has >= 2 peers, >= 75% have peers mostly good
    (< 25% of peers bad), judged over >= 3 such hex-hours.
  * Hex score, as GPSJam publishes it: 100 * max(bad - 1, 0) / (good + bad).
  * Option --heavy-apart (v1.5; off by default): A350 and A380 (A359, A35K, A388) report NACp 0 whenever one satellite
    is flagged degraded and stay degraded far longer than other types (verdict 43; ICAO CNS SG/29 IP/05). With the option,
    their gross-bad hex-hours count as interference only when other aircraft there are bad too (>= PEER_BAD_MAX of >=
    PEER_MIN peers). These types are left out of every peer count, so they neither vouch for each other nor dilute other
    aircraft's bad share. Where too few other aircraft are present to judge, the hex-hour is kept (`--heavy-unjudged
    keep`, default) or set apart (`apart`). Set-apart hex-hours go to `heavy_apart` and are left out of `bad_nacp_live`,
    the minute counts' live total, post-exposure and the peer tests. `bad_nacp` stays raw.

  * Option --position-loss (off by default; docs/validation/position-loss.md): from the same read, per hex and UTC
    hour, aircraft at or above PL_MIN_ALT_FT (10,000 ft) with any ADS-B (adsb_icao, any version) or MLAT position
    ("heard"), and those with MLAT positions but no ADS-B position there ("mlat_only"): heard, but sending no GNSS
    position. The degraded share can't see these aircraft, because they send nothing to grade. It changes none of the
    core tables, which come out the same with or without it.

Input is the day's tar, or its split parts (.tar.aa, .tar.ab ...), read as one stream without unpacking. The raw
bytes are SHA-256 hashed during the same pass, for provenance.

Output (in --out, default data/pnt/daily):
  YYYY-MM-DD.parquet         h3, lat, lon, aircraft, bad_nacp, bad_nic, bad_acc10, score, score_acc10, capable,
                             cap_bad_acc10, latched, bad_nacp_live, score_live, heavy_live
  YYYY-MM-DD.hourly.parquet  h3, hour, aircraft, bad_nacp, bad_nic, bad_acc10, capable, cap_bad_acc10, latched, bad_nacp_live,
                             heavy_live
  YYYY-MM-DD.minute.parquet  h3, minute (0-1439), bad_nacp, latched, heavy (aircraft with a gross-bad / latched report that
                             minute; nonzero rows only)
  heavy_live / heavy (from 25 Oct 2026): how many of the live gross-bad aircraft (in bad_nacp_live, or in bad_nacp minus
  latched for minutes) were A350s or A380s (HEAVY_TYPES), so events can say how much they rest on those types.
  With --heavy-apart, the daily, hourly and minute tables also carry heavy_apart (aircraft whose gross-bad reports there
  were set apart), and the summary's method_version is 1.5.
  YYYY-MM-DD.summary.json    inputs, hashes, counts, timings, method parameters, suspect and latch diagnostics
  With --position-loss only:
  YYYY-MM-DD.loss.parquet        h3, hour, heard, adsb, mlat_only, mlat_any (aircraft per hex-hour)
  YYYY-MM-DD.loss_daily.parquet  h3, lat, lon, heard, adsb, mlat_only, mlat_any (aircraft once per hex per day;
                                 mlat_only only if never on ADS-B in that hex that day)
  and a "position_loss" block in the summary. Position loss = mlat_only / heard, a lower bound (aircraft with neither
  ADS-B nor MLAT positions can't be placed) that depends on MLAT coverage (mlat_any says where MLAT works).

Usage
  python pipeline/pnt_daily.py 2025-10-16 --raw <folder with v2025.10.16-planes-readsb-prod-0.tar*>
  python pipeline/pnt_daily.py 2025-10-16 --raw <folder> --heavy-apart --out data/pnt/daily_v15 --compare-out data/pnt/daily
      (one read, both versions: v1.5 to --out and v1.4 to --compare-out)
  python pipeline/pnt_daily.py 2026-09-15 --raw <folder> --position-loss     (also the loss tables)
"""
import argparse, gzip, hashlib, io, json, math, os, sys, tarfile, time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from multiprocessing import Pool

import h3, orjson

METHOD_VERSION = "1.4"
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
POST_MIN_KM = 300.0   # post-exposure reports must be at least this far from the exposure point
HEAVY_TYPES = frozenset({"A359", "A35K", "A388"})   # --heavy-apart: NACp 0 on one degraded satellite (verdict 43)
BATCH = 400           # trace files per worker task
PL_MIN_ALT_FT = 10000  # --position-loss: aircraft at or above this (approach and departure MLAT gaps stay out)
PL_VERSION = "0.1"

# cell layout: [reports, gross bad, nic bad, acc bad]
R, G, N, A = range(4)


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


def position_flags(d, day0):
    """--position-loss: {(h3 int, hour): bits} for one parsed ICAO trace; bit 1 = an ADS-B (adsb_icao) position there,
    bit 2 = an MLAT position. Airborne at or above PL_MIN_ALT_FT, inside the UTC day."""
    base = float(d.get("timestamp") or 0)
    out = {}
    for p in d.get("trace", []):
        src = p[9] if len(p) > 9 else None
        bit = 1 if src == "adsb_icao" else 2 if src == "mlat" else 0
        alt = p[3]
        if not bit or alt == "ground" or alt is None or alt < PL_MIN_ALT_FT:
            continue
        hour = int((base + p[0] - day0) // 3600)
        if not 0 <= hour < 24:
            continue
        k = (h3.str_to_int(h3.latlng_to_cell(p[1], p[2], RES)), hour)
        out[k] = out.get(k, 0) | bit
    return out


def add_position_flags(flags, hh, dd):
    """Fold one aircraft's flags into hex-hour (hh) and hex-day (dd) counters [heard, adsb, mlat_only, mlat_any]."""
    per_hex = defaultdict(int)
    for (hx, hour), f in flags.items():
        c = hh[(hx, hour)]
        c[0] += 1; c[1] += bool(f & 1); c[2] += f == 2; c[3] += bool(f & 2)
        per_hex[hx] |= f
    for hx, f in per_hex.items():
        c = dd[hx]
        c[0] += 1; c[1] += bool(f & 1); c[2] += f == 2; c[3] += bool(f & 2)


def score_trace(raw, day0, pl=None):
    """One trace file -> aircraft record, or None if not usable. pl: a dict to receive position_flags (--position-loss).

    Record: (cells, meta, bad_minutes).
      cells: {(h3_int, hour): [reports, gross_bad, nic_bad, acc_bad]}
      meta: (used, gross_bad, sum_lat, sum_lon, first_t, last_t, type, acc_capable)
        acc_capable: the aircraft reported NACp >= 10 at least once that day, so NACp < 10 is a change for it, not its
        normal equipage (many aircraft without SBAS report NACp 9 all the time).
      bad_minutes: sorted [(h3_int, minute_of_day)] with at least one gross-bad report.
    """
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    d = orjson.loads(raw)
    if d.get("icao", "~").startswith("~"):
        return None
    if pl is not None:
        pl.update(position_flags(d, day0))
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
        return {}, (0, 0, 0.0, 0.0, 0, 0, "", False), []
    cells = defaultdict(lambda: [0, 0, 0, 0])
    bad_min = set()
    for t, la, lo, g, hx, hour, minute, nb, ab in rep:
        c = cells[(hx, hour)]
        c[R] += 1; c[G] += g; c[N] += nb; c[A] += ab
        if g:
            bad_min.add((hx, minute))
    gross = sum(r[3] for r in rep)
    meta = (len(rep), gross, sum(r[1] for r in rep), sum(r[2] for r in rep), rep[0][0], rep[-1][0], d.get("t") or "", cap)
    return dict(cells), meta, sorted(bad_min)


def work(args):
    batch, day0, pl_on = (args + (False,))[:3]
    recs, st = [], defaultdict(int)
    hh, dd, n_pl = defaultdict(lambda: [0, 0, 0, 0]), defaultdict(lambda: [0, 0, 0, 0]), 0
    for raw in batch:
        st["files"] += 1
        flags = {} if pl_on else None
        try:
            r = score_trace(raw, day0, flags)
        except Exception:
            st["parse_errors"] += 1
            continue
        if r is None:
            st["non_icao"] += 1
            continue
        if flags:
            add_position_flags(flags, hh, dd)
            n_pl += 1
        if r[1][0]:
            recs.append(r)
    if pl_on:
        return recs, dict(st), (dict(hh), dict(dd), n_pl)
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


def hex_hour_totals(recs, ignore=frozenset()):
    """(hex, hour) -> [aircraft, gross-bad aircraft]. Aircraft of types in `ignore` are left out entirely."""
    tot = defaultdict(lambda: [0, 0])
    for cells, meta, _ in recs:
        if meta[6] in ignore:
            continue
        for key, c in cells.items():
            t = tot[key]; t[0] += 1; t[1] += is_bad(c, G)
    return tot


def peers_mostly_good(tot, key, self_bad, self_counted=True):
    """True / False when judgeable (>= PEER_MIN peers), None otherwise. self_counted: the aircraft itself is in tot."""
    n, nb = tot[key]
    peers, peers_bad = n - (1 if self_counted else 0), nb - (1 if self_bad and self_counted else 0)
    if peers < PEER_MIN:
        return None
    return peers_bad / peers < PEER_BAD_MAX


_CENTRE = {}


def centre(hx):
    if hx not in _CENTRE:
        _CENTRE[hx] = h3.cell_to_latlng(h3.int_to_str(hx))
    return _CENTRE[hx]


def resolve_post_exposure(recs, tot, skip=frozenset()):
    """Per record: the set of (hex, hour) cells that are post-exposure. Returns (cells per record, diagnostics).
    Types in `skip` get none (with --heavy-apart their uncorroborated cells are set apart instead)."""
    out, regions, types, unjudged, n_aircraft = [], Counter(), Counter(), 0, 0
    for cells, meta, bad_minutes in recs:
        if meta[6] in skip:
            out.append(set())
            continue
        first = {}
        for hx, m in bad_minutes:
            key = (hx, m // 60)
            if key not in first or m < first[key]:
                first[key] = m
        order = sorted(first, key=first.get)
        exposure = None
        for key in order:   # first hex-hour where the aircraft was bad and its peers were bad too
            ok = peers_mostly_good(tot, key, is_bad(cells[key], G))
            if ok is False and is_bad(cells[key], G):
                exposure = key; break
        pe = set()
        if exposure is not None:
            la0, lo0 = centre(exposure[0]); t0 = first[exposure]
            for key in order:
                if first[key] <= t0:
                    continue
                la, lo = centre(key[0])
                if km(la0, lo0, la, lo) < POST_MIN_KM:
                    continue
                ok = peers_mostly_good(tot, key, is_bad(cells[key], G))
                if ok:
                    pe.add(key)
                elif ok is None:
                    unjudged += 1
        if pe:
            n_aircraft += 1
            regions[h3.cell_to_parent(h3.int_to_str(exposure[0]), 2)] += 1
            types[meta[6] or "?"] += 1
        out.append(pe)
    diag = {"latched_aircraft": n_aircraft, "latch_candidate_cells_unjudged": unjudged,
            "latch_onset_regions_res2": [[c, *[round(x, 2) for x in h3.cell_to_latlng(c)], n] for c, n in regions.most_common(30)],
            "post_exposure_types": dict(types.most_common()),     # all types: a cap hid rare ones from the ratios
            "note": "v1.4: latched = post-exposure; onset = exposure point (first bad hex-hour with bad peers)"}
    return out, diag


_RING = {}


def ring_totals(tot, key):
    """[aircraft, gross-bad aircraft] summed over the hex and its ring-1 neighbours in the same hour."""
    hx, hour = key
    if hx not in _RING:
        _RING[hx] = [h3.str_to_int(c) for c in h3.grid_disk(h3.int_to_str(hx), 1)]
    n = nb = 0
    for c in _RING[hx]:
        t = tot.get((c, hour))
        if t:
            n += t[0]; nb += t[1]
    return n, nb


def heavy_apart_cells(recs, tot, unjudged="keep", corroborate="share"):
    """--heavy-apart: per record, the (hex, hour) cells where an A350/A380 is gross-bad without corroboration from
    other aircraft (`tot` must leave these types out entirely). Corroborated: >= PEER_BAD_MAX of the other aircraft bad
    ("share"), or at least one of them bad ("any"). With fewer than PEER_MIN other aircraft in the hex-hour, unjudged:
    "keep" it, set it "apart", or judge it on the hex plus its ring-1 neighbours ("ring"; kept if still too few).
    Returns (cells, diag)."""
    out, types, healthy, n_unjudged, kept_unjudged, kept, n_aircraft, ringed = [], Counter(), 0, 0, 0, 0, 0, 0
    for cells, meta, _ in recs:
        apart = set()
        if meta[6] in HEAVY_TYPES:
            for key, c in cells.items():
                if not is_bad(c, G):
                    continue
                n, nb = tot[key] if key in tot else (0, 0)          # tot leaves these types out
                if n < PEER_MIN and unjudged == "ring":
                    n, nb = ring_totals(tot, key); ringed += n >= PEER_MIN
                if n < PEER_MIN:
                    n_unjudged += 1
                    if unjudged in ("keep", "ring"):
                        kept_unjudged += 1
                        continue
                elif (nb >= 1) if corroborate == "any" else (nb / n >= PEER_BAD_MAX):
                    kept += 1
                    continue
                else:
                    healthy += 1
                apart.add(key)
            if apart:
                n_aircraft += 1; types[meta[6]] += 1
        out.append(apart)
    diag = {"types": sorted(HEAVY_TYPES), "unjudged_rule": unjudged, "corroborate": corroborate,
            "judged_on_ring": ringed, "aircraft_with_apart_cells": n_aircraft,
            "apart_hex_hours": healthy + n_unjudged - kept_unjudged, "apart_peers_healthy": healthy,
            "apart_peers_unjudged": n_unjudged - kept_unjudged, "kept_unjudged_hex_hours": kept_unjudged,
            "kept_corroborated_hex_hours": kept,
            "aircraft_by_type": dict(types.most_common()),
            "note": "v1.5: A350/A380 gross-bad hex-hours count as interference only when peers are bad too"}
    return out, diag


def live(c, pe_cell):
    """Gross-bad reports in a cell that count as live (none, in a post-exposure cell)."""
    return 0 if pe_cell else c[G]


def find_suspects(recs, tot, latched, ignore=frozenset()):
    """Peer test on live reports. Returns a set of record indexes to drop and a diagnostic list. `latched`: per record,
    the cells whose gross-bad reports aren't live (post-exposure, and with --heavy-apart the set-apart cells)."""
    drop, where = set(), []
    for i, (cells, meta, _) in enumerate(recs):
        used, _, slat, slon, t0, t1, typ, _ = meta
        live_gross = sum(live(c, key in latched[i]) for key, c in cells.items())
        if live_gross < SUSPECT_BAD_FRAC * used:
            continue
        judged = anomalous = 0
        for key, c in cells.items():
            if not is_bad(c, G) or key in latched[i]:
                continue
            ok = peers_mostly_good(tot, key, typ not in ignore)
            if ok is None:
                continue
            judged += 1; anomalous += ok
        if judged >= SUSPECT_MIN_JUDGED and anomalous >= SUSPECT_ANOMALOUS_FRAC * judged:
            drop.add(i)
            where.append((round(slat / used, 1), round(slon / used, 1), round((t1 - t0) / 3600, 1), typ))
    return drop, where


def aggregate(recs, drop, latched, apart=None):
    # hex (or (hex, hour)) -> [aircraft, gross, nic, acc, capable, capable acc-bad, latched, live gross, heavy apart,
    #                         live gross that is an A350/A380]
    daily = defaultdict(lambda: [0] * 10)
    hourly = defaultdict(lambda: [0] * 10)
    minute = defaultdict(lambda: [0, 0, 0, 0])    # (hex, minute) -> [aircraft gross-bad, latched, heavy apart, heavy live]
    no_apart = set()

    def add(t, c, cap, lat_reports, apart_reports, heavy=False):
        acc = is_bad(c, A)
        t[0] += 1; t[1] += is_bad(c, G); t[2] += is_bad(c, N); t[3] += acc
        if cap:
            t[4] += 1; t[5] += acc
        t[6] += lat_reports * 2 >= c[R] and lat_reports > 0
        t[8] += apart_reports * 2 >= c[R] and apart_reports > 0
        live_reports = c[G] - lat_reports - apart_reports
        is_live = live_reports * 2 >= c[R] and live_reports > 0
        t[7] += is_live
        t[9] += is_live and heavy

    for i, (cells, meta, bad_minutes) in enumerate(recs):
        if i in drop:
            continue
        cap, lc = meta[7], latched[i]
        heavy = meta[6] in HEAVY_TYPES
        ac = apart[i] if apart is not None else no_apart
        per_hex = defaultdict(lambda: [0, 0, 0, 0])
        per_hex_lat = defaultdict(int)
        per_hex_apart = defaultdict(int)
        for (hx, hour), c in cells.items():
            lr = c[G] if (hx, hour) in lc else 0
            ar = c[G] if (hx, hour) in ac else 0
            add(hourly[(hx, hour)], c, cap, lr, ar, heavy)
            ph = per_hex[hx]
            for k in range(4):
                ph[k] += c[k]
            per_hex_lat[hx] += lr; per_hex_apart[hx] += ar
        for hx, c in per_hex.items():   # daily: the aircraft's reports in the hex over the whole day
            add(daily[hx], c, cap, per_hex_lat[hx], per_hex_apart[hx], heavy)
        for hx, m in bad_minutes:
            x = minute[(hx, m)]; x[0] += 1; x[1] += (hx, m // 60) in lc; x[2] += (hx, m // 60) in ac
            x[3] += heavy and (hx, m // 60) not in lc and (hx, m // 60) not in ac
    return daily, hourly, minute


def score(bad, n):
    return round(100 * max(bad - 1, 0) / n, 2)


def run(day, raw_dir, out_dir, workers, heavy_apart=False, also=None, position_loss=False):
    """Process one day into out_dir. also: optional (out_dir, heavy_apart) for a second output set from the same read,
    for like-for-like comparisons. position_loss: also write the loss tables to out_dir. Returns the first set's summary."""
    parts = day_parts(raw_dir, day)
    day0 = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())
    t0 = time.time()
    stream = io.BufferedReader(Chain(parts), buffer_size=8 << 20)
    recs, st = [], defaultdict(int)
    hh, dd, n_pl = defaultdict(lambda: [0, 0, 0, 0]), defaultdict(lambda: [0, 0, 0, 0]), 0
    jobs = ((b, d0, True) for b, d0 in batches(stream, day0)) if position_loss else batches(stream, day0)
    with Pool(workers) as pool:
        for res in pool.imap_unordered(work, jobs, chunksize=1):
            r, s = res[0], res[1]
            recs.extend(r)
            for k, v in s.items():
                st[k] += v
            if position_loss:
                h, d, k = res[2]
                n_pl += k
                for key, v in h.items():
                    c = hh[key]; c[0] += v[0]; c[1] += v[1]; c[2] += v[2]; c[3] += v[3]
                for key, v in d.items():
                    c = dd[key]; c[0] += v[0]; c[1] += v[1]; c[2] += v[2]; c[3] += v[3]
    chain = stream.raw
    t_read = time.time() - t0
    pl = write_position_loss(day, out_dir, hh, dd, n_pl) if position_loss else None
    s = finish(day, out_dir, heavy_apart, recs, st, chain, parts, t0, t_read, workers, pl)
    for extra_out, extra_mode in ([also] if also and not isinstance(also, list) else (also or [])):
        finish(day, extra_out, extra_mode, recs, st, chain, parts, t0, t_read, workers)
    return s


def write_position_loss(day, out_dir, hh, dd, n_aircraft):
    """--position-loss: write <day>.loss.parquet and <day>.loss_daily.parquet; returns the summary block."""
    import pyarrow as pa, pyarrow.parquet as pq
    os.makedirs(out_dir, exist_ok=True)
    cols = ("heard", "adsb", "mlat_only", "mlat_any")
    hk = sorted(hh)
    pq.write_table(pa.table({"h3": [h3.int_to_str(k[0]) for k in hk], "hour": pa.array([k[1] for k in hk], pa.int8()),
                             **{c: pa.array([hh[k][i] for k in hk], pa.int32()) for i, c in enumerate(cols)}}),
                   os.path.join(out_dir, f"{day}.loss.parquet"), compression="zstd")
    dk = sorted(dd)
    cells = [h3.int_to_str(k) for k in dk]
    ll = [h3.cell_to_latlng(c) for c in cells]
    pq.write_table(pa.table({"h3": cells, "lat": [round(a, 4) for a, _ in ll], "lon": [round(b, 4) for _, b in ll],
                             **{c: pa.array([dd[k][i] for k in dk], pa.int32()) for i, c in enumerate(cols)}}),
                   os.path.join(out_dir, f"{day}.loss_daily.parquet"), compression="zstd")
    heard = sum(v[0] for v in dd.values()); mo = sum(v[2] for v in dd.values())
    return {"version": PL_VERSION, "min_alt_ft": PL_MIN_ALT_FT, "aircraft": n_aircraft, "hexes": len(dk), "hex_hours": len(hk),
            "aircraft_hexes_heard": heard, "aircraft_hexes_mlat_only": mo,
            "definition": "mlat_only / heard per hex: aircraft with MLAT but no ADS-B position there, of those with either; "
                          "a lower bound that depends on MLAT coverage"}


def finish(day, out_dir, heavy_apart, recs, st, chain, parts, t0, t_read, workers, pl=None):
    """heavy_apart: False (v1.4), or True / a mode string (v1.5): keep, apart, ring, keep-any, ring-any (see heavy_apart_cells)."""
    mode = "keep" if heavy_apart is True else (heavy_apart or "")
    if mode == "drop":            # comparison only: A350/A380 left out of every count, as if absent
        recs = [r for r in recs if r[1][6] not in HEAVY_TYPES]
        heavy_apart = False
    unjudged = mode.split("-")[0] or "keep"
    corroborate = "any" if mode.endswith("-any") else "share"
    ignore = HEAVY_TYPES if heavy_apart else frozenset()
    tot = hex_hour_totals(recs, ignore)
    latched, latch_diag = resolve_post_exposure(recs, tot, ignore)
    if heavy_apart:
        apart, apart_diag = heavy_apart_cells(recs, tot, unjudged, corroborate)
        excluded = [lc | ac for lc, ac in zip(latched, apart)]
    else:
        apart, apart_diag, excluded = None, None, latched
    drop, where = find_suspects(recs, tot, excluded, ignore)
    daily, hourly, minute = aggregate(recs, drop, latched, apart)
    secs = time.time() - t0
    extra = (lambda rows, i: {"heavy_apart": [v[i] for _, v in rows]}) if heavy_apart else (lambda rows, i: {})

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
        "heavy_live": [v[9] for _, v in rows],
        **extra(rows, 8),
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
        "heavy_live": [v[9] for _, v in hrows],
        **extra(hrows, 8),
    }), os.path.join(out_dir, f"{day}.hourly.parquet"), compression="zstd")
    mrows = sorted(minute.items())
    pq.write_table(pa.table({
        "h3": [h3.int_to_str(hx) for (hx, _), _ in mrows],
        "minute": pa.array([m for (_, m), _ in mrows], pa.int16()),
        "bad_nacp": pa.array([v[0] for _, v in mrows], pa.int32()),
        "latched": pa.array([v[1] for _, v in mrows], pa.int32()),
        "heavy": pa.array([v[3] for _, v in mrows], pa.int32()),
        **({"heavy_apart": pa.array([v[2] for _, v in mrows], pa.int32())} if heavy_apart else {}),
    }), os.path.join(out_dir, f"{day}.minute.parquet"), compression="zstd")
    summary = {
        "day": day, "method_version": "1.5" if heavy_apart else (METHOD_VERSION + "-noheavy" if mode == "drop" else METHOD_VERSION), "inputs": [os.path.basename(p) for p in parts],
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
                   "post_exposure": {"exposure": "first bad hex-hour with >= peer_min peers, >= peer_bad_max of them bad",
                                     "min_km_from_exposure": POST_MIN_KM, "tagged_if_peers_mostly_good": True},
                   "heavy_apart": {"types": sorted(HEAVY_TYPES), "unjudged": unjudged, "corroborate": corroborate} if heavy_apart else None,
                   "score": "100*max(bad-1,0)/(good+bad)"},
        "source": "adsb.lol globe_history (ODbL 1.0)",
        "latching": latch_diag,
        **({"heavy_apart": apart_diag} if heavy_apart else {}),
        **({"position_loss": pl} if pl else {}),
        "type_counts_all": dict(Counter(m[6] or "?" for _, m, _ in recs).most_common()),   # all types (was top 80)
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
    ap.add_argument("--heavy-apart", action="store_true", help="v1.5: A350/A380 degradation counts only when peers agree")
    ap.add_argument("--heavy-unjudged", choices=["keep", "apart", "ring"], default="keep",
                    help="--heavy-apart: hex-hours with too few other aircraft: kept (default), set apart, or judged on ring 1")
    ap.add_argument("--heavy-any", action="store_true",
                    help="--heavy-apart: corroborated when any other aircraft there is bad (default: >= PEER_BAD_MAX of them)")
    ap.add_argument("--compare-out", help="also write the other setting (with or without --heavy-apart) here, same read")
    ap.add_argument("--position-loss", action="store_true",
                    help="also write <day>.loss.parquet and .loss_daily.parquet (aircraft heard but sending no GNSS position)")
    a = ap.parse_args()
    mode = (a.heavy_unjudged + ("-any" if a.heavy_any else "")) if a.heavy_apart else False
    s = run(a.day, a.raw, a.out, a.workers, mode, (a.compare_out, False if a.heavy_apart else "keep") if a.compare_out else None,
            position_loss=a.position_loss)
    print(json.dumps({k: s[k] for k in ("day", "seconds", "files", "aircraft", "avionics_suspects", "hexes", "hex_hours", "reports_used")}
                     | {"latched_aircraft": s["latching"]["latched_aircraft"]}))


if __name__ == "__main__":
    main()
