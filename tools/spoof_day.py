#!/usr/bin/env python3
"""spoof_day.py: one adsb.lol day -> GNSS spoofing indicators per aircraft, per H3 hex (res 4 and 2) and UTC hour.

Spoofing differs from jamming: a spoofed receiver can report good accuracy (NACp) at a false position, so the jamming
processor (pipeline/pnt_daily.py) can't see it. This tool looks for positions an aircraft can't physically have flown.
Validation and results: docs/validation/spoofing.md.

Per aircraft (ADS-B airborne positions, type adsb_icao, any ADS-B version, every position):
  fast       emitter category A2-A5 with >= 10 reports at >= 250 kt above 10,000 ft that day, or no category and
             >= 10 reports at >= 350 kt above 20,000 ft. Only fast aircraft get the three tests below (light aircraft,
             rotorcraft, gliders and balloons can fly slowly or circle at altitude, and share addresses more often).
  slow       ground speed < 100 kt at or above 10,000 ft baro (18,000 ft for category A2). A transport aircraft can't
             fly that slowly at altitude; a receiver held at a fixed point reports about 0 kt.
  loiter     within 3 km of one point for >= 3 minutes (no coverage gap over 2 min), at the same altitude floor:
             circle and fixed-point spoofing. A6 (high-performance) aircraft are exempt.
  excursion  the track is split at jumps (>= 20 km at an implied >= 1,200 kt) and where slow/loiter status changes.
             Plausible segments are chained into tracks an aircraft could fly (700 kt + 5 km), choosing the track
             whose dead-reckoned position is nearest; the track with the most observed time is taken as true. A segment
             of another track with true-track segments on both sides, at most 2 h apart, is an excursion. A jump with
             no return is counted (unresolved_jumps) but not used. Aircraft with >= 2 jumps over 2,000 km between
             plausible positions are duplicate-address suspects and get no excursion test.
  An episode is a run of slow, loiter or excursion positions (gaps under 15 min), at least 2 positions over 20 s. Its
  victim location is where the aircraft really was during the episode: the last trusted position before it and the
  first after (each within 60 min) joined by a great circle, sampled each minute over the episode's own span; else one
  of them if within 15 min; else MLAT positions. Each episode is classed active, post (post-exposure), isolated or
  unlocated (see classify()). Maps should use spoofed_active.
Supporting indicators (tested, reported, not used to build episodes):
  geo        geometric minus baro altitude jumps by >= 1,000 ft within 60 s (geo_step), or sits at the ADS-B
             encoding limit, |diff| >= 3,100 ft (geo_sat); and per hex-hour, an aircraft whose median diff is >= 1,500 ft
             from its peers' median (geo_out, >= 4 aircraft with altitude data in the hex-hour)
  mlat       an MLAT position within 30 s of an ADS-B position (moved on by the ADS-B ground speed and track) disagrees
             by >= 20 km. MLAT doesn't use GNSS, so where it exists it is independent truth; kept out of the detector so
             that it can validate it.
  kin        reported ground speed / track disagree with the speed / bearing between consecutive sampled trusted
             positions (25-90 s apart) by > 100 kt or > 45 degrees, in >= 3 pairs and >= half the pairs in a hex-hour
  jam        jamming proxy from the same pass: aircraft with >= 50% of their trusted version-2 reports at NACp < 8
             (30 s sampling, no latch or suspect logic: close to, not the same as, pnt_daily.py)

Output (in --out, default data/spoofing/):
  YYYY-MM-DD.hex4.parquet   h3, hour, aircraft, spoofed (all located episodes), spoofed_active / _post / _isolated
                            (episode classes, see classify()), spoofed_slow, spoofed_loiter, spoofed_excursion,
                            spoofed_clean (false positions mostly NACp >= 8), spoofed_geo, spoofed_mlat, false_pos
                            (aircraft shown here at a false position), jam, kin, geo_out, geo_flag (aircraft with
                            >= 2 trusted positions flagged geo_step or geo_sat), mlat_pairs, mlat_dis, mlat_dis_trusted
                            (MLAT pairs, at the MLAT position; disagreeing; disagreeing where ADS-B was trusted),
                            unresolved_jumps
  YYYY-MM-DD.hex2.parquet   the same at H3 res 2
  YYYY-MM-DD.daily4.parquet h3, lat, lon, aircraft, spoofed, false_pos, jam, spoofed_active (distinct aircraft, day)
  YYYY-MM-DD.events.json.gz one row per episode (ICAO address included: local file, adsb.lol data is ODbL)
  YYYY-MM-DD.summary.json   inputs, hashes, counts, timings, parameters, top spoofed-to points, overlap statistics

Usage
  python tools/spoof_day.py run 2024-10-14 [--raw data/raw/trace_box/2024-10-14]
  python tools/spoof_day.py report 2024-10-14 2024-10-15 ...      # region tables (known areas and quiet controls)
"""
import argparse, bisect, gzip, io, json, itertools, math, os, statistics, sys, time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from multiprocessing import Pool

import h3, orjson

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import pnt_daily as P                       # noqa: E402  (Chain, day_parts, batches: same archive handling)

VERSION = "0.3"
RES, RES2, RES_PT = 4, 2, 6                 # maps, regional maps, spoofed-to points
MIN_ALT_FT = 1000
SAMPLE_S = 30.0                             # hex-hour tables: at most one trusted report per aircraft per 30 s
HIGH_ALT_FT = 10000                         # slow / loiter tests only at or above this baro altitude
HIGH_ALT_A2_FT = 18000                      # ... and this for category A2 (skydiving, training and survey flights fly
                                            #     slowly or circle at 10,000-18,000 ft; v0.3, see the validation)
FAST_KT, FAST_KT_NOCAT, FAST_MIN_PTS = 250, 350, 10
FAST_CATS = {"A2", "A3", "A4", "A5"}         # emitter categories tested for slow / loiter: small to heavy transports
SLOW_KT = 100
LOITER_KM, LOITER_S, LOITER_MIN_PTS, LOITER_GAP_S = 3.0, 180, 4, 120   # gap: longest break in coverage inside a run
JUMP_KM, JUMP_KT, FAR_KM = 20.0, 1200.0, 2000.0
VMAX_KT, SLACK_KM = 700.0, 5.0
OBS_GAP_S, EXC_MAX_S = 120.0, 7200.0          # observed-time gap cap; longest excursion (true track resumes within)
EPISODE_GAP_S, EPISODE_MIN_PTS, EPISODE_MIN_S = 900, 2, 20.0
VICTIM_MAX_S = 3600                         # trusted anchors before and after an episode, joined: each within this time
VICTIM_SINGLE_S = 900                       # a single anchor (the other missing or inconsistent): within this time
POST_MIN_KM, POST_GAP_S, PEER_HOURS = 300.0, 900.0, 1   # post-exposure and peer rules (see aggregate())
MLAT_DT_S, MLAT_KM = 30.0, 20.0
KIN_DT_S, KIN_MIN_KM, KIN_KT, KIN_DEG, KIN_MIN_BAD = (25.0, 90.0), 0.5, 100.0, 45.0, 3
GEO_STEP_FT, GEO_STEP_S, GEO_SAT_FT, GEO_PEER_FT, GEO_PEER_MIN = 1000, 60.0, 3100, 1500, 4
GEO_FLAG_MIN = 2                            # geo_flag column: trusted points with geo_step or geo_sat in the hex-hour
NACP_BAD, NACP_CLEAN = 8, 8
KT_PER_KMS = 1943.844                       # 1 km/s in knots
# trusted-cell layout: [reports, v2 reports, v2 NACp < 8, kin pairs, kin bad, geo diff sum, geo n]  (+ geo list kept apart)
TR, V2, V2B, KP, KB = range(5)

T, LAT, LON, ALT, GS, TRK, GEO, NACP, NIC, VER = range(10)


def km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 12742.0 * math.asin(min(1.0, math.sqrt(a)))


def fkm(lat1, lon1, lat2, lon2):
    """Flat-earth distance in km: within 1% of km() up to a few hundred km away from the poles; used for the
    per-point tests, where it is called millions of times a day."""
    dlon = (lon2 - lon1 + 180.0) % 360.0 - 180.0
    x = dlon * math.cos(math.radians((lat1 + lat2) * 0.5))
    return 111.195 * math.sqrt(x * x + (lat2 - lat1) ** 2)


def bearing(lat1, lon1, lat2, lon2):
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    return math.degrees(math.atan2(math.sin(dl) * math.cos(p2),
                                   math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl))) % 360


def destination(lat, lon, brg, dist_km):
    la, lo, b, d = math.radians(lat), math.radians(lon), math.radians(brg), dist_km / 6371.0
    la2 = math.asin(math.sin(la) * math.cos(d) + math.cos(la) * math.sin(d) * math.cos(b))
    lo2 = lo + math.atan2(math.sin(b) * math.sin(d) * math.cos(la), math.cos(d) - math.sin(la) * math.sin(la2))
    return math.degrees(la2), (math.degrees(lo2) + 540) % 360 - 180


def interpolate(a, b, f):
    """Great-circle point a fraction f of the way from (lat, lon) a to b."""
    d = km(a[0], a[1], b[0], b[1])
    if d < 1e-6:
        return a
    return destination(a[0], a[1], bearing(a[0], a[1], b[0], b[1]), d * f)


def reachable(p, q):
    """Could an aircraft get from point p to point q (ADS-B tuples, q later) at VMAX_KT, with SLACK_KM of slack?"""
    dt = q[T] - p[T]
    return km(p[LAT], p[LON], q[LAT], q[LON]) <= VMAX_KT / KT_PER_KMS * max(dt, 0.0) + SLACK_KM


def angle_diff(a, b):
    return abs((a - b + 180) % 360 - 180)


# ---------- per aircraft ----------

def parse_trace(d):
    """Raw trace dict -> (ADS-B airborne points, MLAT airborne points, emitter category)."""
    base = float(d.get("timestamp") or 0)
    nacp = nic = ver = cat = None
    A, M = [], []
    for p in d.get("trace", []):
        det = p[8] if len(p) > 8 else None
        if det:
            nacp = det.get("nac_p", nacp); nic = det.get("nic", nic); ver = det.get("version", ver)
            cat = det.get("category", cat)
        alt = p[3]
        if alt == "ground" or alt is None:
            continue
        src = p[9] if len(p) > 9 else None
        if src == "adsb_icao":
            geo = p[10] if len(p) > 10 else None
            if p[6] & 8:                    # the altitude field is geometric: no baro altitude for this point
                geo, alt = alt, None
            if alt is not None and alt < MIN_ALT_FT:
                continue
            A.append((base + p[0], p[1], p[2], alt, p[4], p[5], geo, nacp, nic, ver))
        elif src == "mlat" and alt >= MIN_ALT_FT:
            M.append((base + p[0], p[1], p[2], alt))
    return A, M, cat


def point_flags(A, cat):
    """slow and loiter flags per ADS-B point, and whether the aircraft counts as fast."""
    n = len(A)
    slow, loiter = [False] * n, [False] * n
    hi = [p[ALT] is not None and p[ALT] >= HIGH_ALT_FT for p in A]
    floor = HIGH_ALT_A2_FT if cat == "A2" else HIGH_ALT_FT
    if cat in FAST_CATS:
        fast = sum(1 for p, h in zip(A, hi) if h and p[GS] is not None and p[GS] >= FAST_KT) >= FAST_MIN_PTS
    elif cat in (None, "", "A0"):          # no category: only clearly jet-like speeds at jet altitudes
        fast = sum(1 for p in A if p[ALT] is not None and p[ALT] >= 20000 and p[GS] is not None
                   and p[GS] >= FAST_KT_NOCAT) >= FAST_MIN_PTS
    else:
        fast = False
    if not fast:
        return slow, loiter, False
    hi = [p[ALT] is not None and p[ALT] >= floor for p in A]   # slow / loiter floor (higher for A2, see HIGH_ALT_A2_FT)
    for i, p in enumerate(A):
        if hi[i] and p[GS] is not None and p[GS] < SLOW_KT:
            slow[i] = True
    if cat != "A6":
        i = 0
        while i < n:
            if not hi[i]:
                i += 1; continue
            j = i
            while (j + 1 < n and hi[j + 1] and A[j + 1][T] - A[j][T] <= LOITER_GAP_S
                   and fkm(A[i][LAT], A[i][LON], A[j + 1][LAT], A[j + 1][LON]) <= LOITER_KM):
                j += 1
            if A[j][T] - A[i][T] >= LOITER_S and j - i + 1 >= LOITER_MIN_PTS:
                for k in range(i, j + 1):
                    loiter[k] = True
                i = j + 1                   # the run is flagged; continue after it
            else:
                i += 1
    return slow, loiter, True


def residual(p, q):
    """Distance (km) from q to where p would be at q's time, flying on at its reported ground speed and track
    (dead reckoning capped at 30 minutes)."""
    dt = min(max(q[T] - p[T], 0.0), 1800.0)
    la, lo = p[LAT], p[LON]
    if p[GS] is not None and p[TRK] is not None:
        la, lo = destination(la, lo, p[TRK], p[GS] / KT_PER_KMS * dt)
    return km(la, lo, q[LAT], q[LON])


def segments_and_tracks(A, bad):
    """Split the track at jumps and where the slow/loiter flag (bad) changes; chain the plausible (not bad) segments
    into tracks an aircraft could have flown, choosing the track whose dead-reckoned position is nearest.

    Returns (segments [(start, end_excl)], track id per segment (-1 for bad segments), primary track id (longest
    observed time, counting gaps between positions up to OBS_GAP_S; -1 if none), number of jumps, number of far
    jumps)."""
    n = len(A)
    starts, jumps, far = [0], 0, 0
    for i in range(1, n):
        split = bad[i] != bad[i - 1]
        dt = A[i][T] - A[i - 1][T]
        if dt > 0:
            d = fkm(A[i - 1][LAT], A[i - 1][LON], A[i][LAT], A[i][LON])
            if JUMP_KM <= d <= 300:
                d = km(A[i - 1][LAT], A[i - 1][LON], A[i][LAT], A[i][LON])
            if d >= JUMP_KM and d / dt * KT_PER_KMS >= JUMP_KT:
                jumps += 1; split = True
                far += d > FAR_KM and not bad[i] and not bad[i - 1]   # far jumps between plausible positions
        if split:
            starts.append(i)
    segs = list(zip(starts, starts[1:] + [n]))
    last, dur, track_of = [], [], []        # per track: index of its last point; observed time (s)
    for s, e in segs:
        if bad[s]:
            track_of.append(-1); continue
        seen = 1.0 + sum(min(A[i][T] - A[i - 1][T], OBS_GAP_S) for i in range(s + 1, e))
        best, best_r = None, None
        for k, li in enumerate(last):
            if reachable(A[li], A[s]):
                r = residual(A[li], A[s])
                if best is None or r < best_r:
                    best, best_r = k, r
        if best is None:
            last.append(e - 1); dur.append(seen); track_of.append(len(last) - 1)
        else:
            last[best] = e - 1; dur[best] += seen; track_of.append(best)
    primary = max(range(len(dur)), key=dur.__getitem__) if dur else -1
    return segs, track_of, primary, jumps, far


def analyse(A, M, cat):
    """Per-aircraft analysis on time-ordered ADS-B points A and MLAT points M.

    Returns dict: false (bool per point), trusted (bool per point), flags {name: [bool]}, episodes [...],
    mlat pairs, dup, jumps, far, unresolved [indexes of the first point after an unresolved jump]."""
    n = len(A)
    slow, loiter, fast = point_flags(A, cat)
    bad = [a or b for a, b in zip(slow, loiter)]
    segs, track_of, primary, jumps, far = segments_and_tracks(A, bad)
    dup = far >= 2
    excursion, other_track = [False] * n, [False] * n
    unresolved = []
    if fast and not dup and primary >= 0 and len(segs) > 1:
        prim_idx = [k for k, tr in enumerate(track_of) if tr == primary]
        for k, (s, e) in enumerate(segs):
            if track_of[k] in (primary, -1):
                continue
            for i in range(s, e):
                other_track[i] = True
            pb = max((j for j in prim_idx if j < k), default=None)      # nearest true-track segments either side
            pa = min((j for j in prim_idx if j > k), default=None)
            if pb is not None and pa is not None and A[segs[pa][0]][T] - A[segs[pb][1] - 1][T] <= EXC_MAX_S:
                for i in range(s, e):
                    excursion[i] = True
            else:
                unresolved.append(s if pb is not None else e)       # the jump into, or out of, the segment
    false = [slow[i] or loiter[i] or excursion[i] for i in range(n)]
    trusted = [not false[i] and not other_track[i] for i in range(n)]

    # geometric - baro altitude
    geo_step, geo_sat = [False] * n, [False] * n
    prev = None
    for i, p in enumerate(A):
        if p[ALT] is None or p[GEO] is None or p[ALT] < HIGH_ALT_FT:
            continue
        diff = p[GEO] - p[ALT]
        geo_sat[i] = abs(diff) >= GEO_SAT_FT
        if prev is not None and p[T] - prev[0] <= GEO_STEP_S and abs(diff - prev[1]) >= GEO_STEP_FT:
            geo_step[i] = True
        prev = (p[T], diff)

    # MLAT against ADS-B
    mlat = []                               # (index of the ADS-B point, distance km, MLAT point)
    if M and A:
        times = [p[T] for p in A]
        for m in M:
            j = bisect.bisect_left(times, m[0])
            best = None
            for k in (j - 1, j):
                if 0 <= k < n and abs(m[0] - times[k]) <= MLAT_DT_S and (best is None or abs(m[0] - times[k]) < abs(m[0] - times[best])):
                    best = k
            if best is None:
                continue
            a = A[best]
            la, lo = a[LAT], a[LON]
            if a[GS] is not None and a[TRK] is not None:
                la, lo = destination(la, lo, a[TRK], a[GS] / KT_PER_KMS * (m[0] - a[T]))
            mlat.append((best, km(la, lo, m[1], m[2]), m))

    # episodes
    episodes, cur = [], []
    for i in range(n):
        if not false[i]:
            continue
        if cur and A[i][T] - A[cur[-1]][T] > EPISODE_GAP_S:
            episodes.append(cur); cur = []
        cur.append(i)
    if cur:
        episodes.append(cur)
    episodes = [e for e in episodes if len(e) >= EPISODE_MIN_PTS and A[e[-1]][T] - A[e[0]][T] >= EPISODE_MIN_S]
    return {"false": false, "trusted": trusted, "fast": fast, "dup": dup, "jumps": jumps, "far": far,
            "flags": {"slow": slow, "loiter": loiter, "excursion": excursion, "geo_step": geo_step, "geo_sat": geo_sat},
            "episodes": episodes, "mlat": mlat, "unresolved": unresolved}


def victim_track(A, trusted, ep, M):
    """Where the aircraft really was during an episode: [(t, lat, lon)], and how it was found."""
    t0, t1 = A[ep[0]][T], A[ep[-1]][T]
    before = next((A[i] for i in range(ep[0] - 1, -1, -1) if trusted[i]), None)
    after = next((A[i] for i in range(ep[-1] + 1, len(A)) if trusted[i]), None)
    if before is not None and t0 - before[T] > VICTIM_MAX_S:
        before = None
    if after is not None and after[T] - t1 > VICTIM_MAX_S:
        after = None
    out = []
    if before is not None and after is not None and reachable(before, after):
        dt = after[T] - before[T]
        a, b = max(before[T], t0 - 60), min(after[T], t1 + 60)       # only the episode's own time span
        steps = max(1, int((b - a) // 60))
        for s in range(steps + 1):
            t = a + (b - a) * s / steps
            la, lo = interpolate((before[LAT], before[LON]), (after[LAT], after[LON]), (t - before[T]) / dt if dt > 0 else 0.0)
            out.append((t, la, lo))
        how = "between"
    elif (before is not None and t0 - before[T] <= VICTIM_SINGLE_S) or (after is not None and after[T] - t1 <= VICTIM_SINGLE_S):
        near = [p for p, gap in ((before, t0 - before[T] if before else 1e9), (after, after[T] - t1 if after else 1e9))
                if p is not None and gap <= VICTIM_SINGLE_S]
        out = [(p[T], p[LAT], p[LON]) for p in near]
        how = "before" if near[0] is before else "after"
    else:
        out = [(m[0], m[1], m[2]) for m in M if t0 - 60 <= m[0] <= t1 + 60]
        how = "mlat" if out else "none"
    return out, before, after, how


def cell(lat, lon, res):
    return h3.str_to_int(h3.latlng_to_cell(lat, lon, res))


def score_trace(raw, day0):
    """One trace file -> aircraft record, or None."""
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    d = orjson.loads(raw)
    icao = d.get("icao", "~")
    if icao.startswith("~"):
        return None
    A, M, cat = parse_trace(d)
    if not A:
        return None
    r = analyse(A, M, cat)
    trusted, false = r["trusted"], r["false"]

    def hour(t):
        h = int((t - day0) // 3600)
        return h if 0 <= h < 24 else None

    cells = defaultdict(lambda: [0, 0, 0, 0, 0])            # (hex4, hour) -> TR, V2, V2B, KP, KB
    geo = defaultdict(list)                                 # (hex4, hour) -> geo - baro diffs (trusted, high)
    prev, last_t = None, -1e18
    for i, p in enumerate(A):
        if not trusted[i]:
            prev = None; continue
        if p[T] - last_t < SAMPLE_S:       # at most one report per SAMPLE_S, as in pnt_daily.py
            continue
        last_t = p[T]
        h = hour(p[T])
        if h is None:
            prev = p; continue
        c = cells[(cell(p[LAT], p[LON], RES), h)]
        c[TR] += 1
        if p[VER] == 2 and p[NACP] is not None:
            c[V2] += 1; c[V2B] += p[NACP] < NACP_BAD
        if p[ALT] is not None and p[GEO] is not None and p[ALT] >= HIGH_ALT_FT:
            geo[(cell(p[LAT], p[LON], RES), h)].append(p[GEO] - p[ALT])
        if prev is not None and p[GS] is not None and p[GS] > 0:
            dt = p[T] - prev[T]
            if KIN_DT_S[0] <= dt <= KIN_DT_S[1]:
                dk = fkm(prev[LAT], prev[LON], p[LAT], p[LON])
                if dk >= KIN_MIN_KM:
                    v = dk / dt * KT_PER_KMS
                    bad = abs(v - p[GS]) > KIN_KT or (p[GS] > 150 and p[TRK] is not None
                                                      and angle_diff(bearing(prev[LAT], prev[LON], p[LAT], p[LON]), p[TRK]) > KIN_DEG)
                    c[KP] += 1; c[KB] += bad
        prev = p
    geo_med = {k: statistics.median(v) for k, v in geo.items() if v}

    episodes = []
    for ep in r["episodes"]:
        vt, before, after, how = victim_track(A, trusted, ep, M)
        vcells = sorted({(cell(la, lo, RES), h) for t, la, lo in vt if (h := hour(t)) is not None})
        fcells = sorted({(cell(A[i][LAT], A[i][LON], RES), h) for i in ep if (h := hour(A[i][T])) is not None})
        pts6 = sorted({cell(A[i][LAT], A[i][LON], RES_PT) for i in ep})
        nacps = [A[i][NACP] for i in ep if A[i][NACP] is not None]
        nics = [A[i][NIC] for i in ep if A[i][NIC] is not None]
        kinds = sorted(k for k in ("slow", "loiter", "excursion") if any(r["flags"][k][i] for i in ep))
        lo_t, hi_t = A[ep[0]][T] - 60, A[ep[-1]][T] + 60
        geo_hits = sum(1 for i in range(len(A)) if lo_t <= A[i][T] <= hi_t and (r["flags"]["geo_step"][i] or r["flags"]["geo_sat"][i]))
        ml = [x for x in r["mlat"] if lo_t <= x[2][0] <= hi_t]
        clat = statistics.median(A[i][LAT] for i in ep); clon = statistics.median(A[i][LON] for i in ep)
        episodes.append({
            "t0": A[ep[0]][T], "t1": A[ep[-1]][T], "n": len(ep), "kinds": kinds,
            "false_lat": round(clat, 4), "false_lon": round(clon, 4), "false_cell6": [h3.int_to_str(c) for c in pts6[:5]],
            "alt": A[ep[0]][ALT],
            "before": [round(before[T]), round(before[LAT], 4), round(before[LON], 4), before[NACP]] if before else None,
            "after": [round(after[T]), round(after[LAT], 4), round(after[LON], 4), after[NACP]] if after else None,
            "victim_how": how, "nacp_median": statistics.median(nacps) if nacps else None,
            "clean_share": round(sum(1 for x in nacps if x >= NACP_CLEAN) / len(nacps), 2) if nacps else None,
            "nic_median": statistics.median(nics) if nics else None,
            "geo_hits": geo_hits, "mlat_pairs": len(ml), "mlat_dis": sum(1 for x in ml if x[1] >= MLAT_KM),
            "vcells": vcells, "fcells": fcells,
            # reference location for the post-exposure rule: where the aircraft was, else where it was shown
            "ref": ([round(statistics.median(x[1] for x in vt), 4), round(statistics.median(x[2] for x in vt), 4)]
                    if vt else [round(clat, 4), round(clon, 4)]),
        })

    ml_tr = [x for x in r["mlat"] if trusted[x[0]]]
    ml_fa = [x for x in r["mlat"] if false[x[0]]]
    mlat_cells = defaultdict(lambda: [0, 0, 0])             # (hex4, hour) at the MLAT position -> [pairs, disagree,
    for x in r["mlat"]:                                     #   disagree where the ADS-B position was trusted]
        h = hour(x[2][0])
        if h is None:
            continue
        c = mlat_cells[(cell(x[2][1], x[2][2], RES), h)]
        dis = x[1] >= MLAT_KM
        c[0] += 1; c[1] += dis; c[2] += dis and trusted[x[0]]
    fl = r["flags"]
    geo_flag = Counter()                                    # (hex4, hour) -> trusted points with geo_step or geo_sat
    for i, p in enumerate(A):
        if trusted[i] and (fl["geo_step"][i] or fl["geo_sat"][i]):
            h = hour(p[T])
            if h is not None:
                geo_flag[(cell(p[LAT], p[LON], RES), h)] += 1
    unres = []
    for i in r["unresolved"]:
        j = min(max(i, 0), len(A) - 1)
        h = hour(A[j][T])
        if h is not None:
            unres.append((cell(A[j][LAT], A[j][LON], RES), h))
    return {
        "icao": icao, "type": d.get("t") or "", "cat": cat or "", "fast": r["fast"], "dup": r["dup"],
        "jumps": r["jumps"], "far": r["far"], "cells": dict(cells), "geo": geo_med, "episodes": episodes,
        "mlat": [len(ml_tr), sum(1 for x in ml_tr if x[1] >= MLAT_KM), len(ml_fa), sum(1 for x in ml_fa if x[1] >= MLAT_KM)],
        "mlat_cells": dict(mlat_cells), "unresolved": unres, "geo_flag": dict(geo_flag),
        "points": len(A), "false_points": sum(false),
        "flag_points": {k: sum(v) for k, v in fl.items()},
        "geo_false": sum(1 for i in range(len(A)) if false[i] and (fl["geo_step"][i] or fl["geo_sat"][i])),
        "geo_trusted": sum(1 for i in range(len(A)) if trusted[i] and (fl["geo_step"][i] or fl["geo_sat"][i])),
        "geo_sat_trusted_cells": sorted({(cell(A[i][LAT], A[i][LON], RES2)) for i in range(len(A)) if trusted[i] and fl["geo_sat"][i]}),
    }


def work(args):
    batch, day0 = args
    recs, st = [], Counter()
    for raw in batch:
        st["files"] += 1
        try:
            r = score_trace(raw, day0)
        except Exception:
            st["parse_errors"] += 1
            continue
        if r is None:
            st["skipped"] += 1
            continue
        recs.append(r)
    return recs, dict(st)


# ---------- day aggregation ----------

COLS = ["aircraft", "spoofed", "spoofed_active", "spoofed_post", "spoofed_isolated", "spoofed_slow", "spoofed_loiter",
        "spoofed_excursion", "spoofed_clean", "spoofed_geo", "spoofed_mlat", "false_pos", "jam", "kin", "geo_out", "geo_flag", "mlat_pairs", "mlat_dis", "mlat_dis_trusted",
        "unresolved_jumps"]
CI = {c: i for i, c in enumerate(COLS)}


_PARENT = {}


def parent(hx, res):
    k = (hx, res)
    if k not in _PARENT:
        _PARENT[k] = h3.str_to_int(h3.cell_to_parent(h3.int_to_str(hx), res))
    return _PARENT[k]


def classify(recs):
    """Episode classes, in place: e["class"] is
      active     another aircraft (not post-exposure) was spoofed in the same res-2 cell within PEER_HOURS hours:
                 spoofing in the area where the aircraft really was;
      post       no such peer, and the same aircraft had an earlier episode (ended >= POST_GAP_S before) >= POST_MIN_KM
                 away: false positions carried on after leaving a spoofed area (receiver still contaminated);
      isolated   no peer and no earlier episode: unexplained (exposure not seen, a local source, or a false alarm);
      unlocated  no victim location.
    The peer rule mirrors the jamming processor's: real interference affects many aircraft in an area at once."""
    for r in recs:
        eps = r["episodes"]
        for i, e in enumerate(eps):
            e["cand_post"] = any(p["t1"] <= e["t0"] - POST_GAP_S and km(*p["ref"], *e["ref"]) >= POST_MIN_KM
                                 for p in eps[:i])
    near = defaultdict(set)                 # (res-2 cell, hour) -> aircraft with a non-post episode located there
    for r in recs:
        for e in r["episodes"]:
            if not e["cand_post"]:
                for hx, h in e["vcells"]:
                    near[(parent(hx, RES2), h)].add(r["icao"])
    for r in recs:
        for e in r["episodes"]:
            ps = set()
            for hx, h in e["vcells"]:
                p2 = parent(hx, RES2)
                for dh in range(-PEER_HOURS, PEER_HOURS + 1):
                    ps |= near.get((p2, h + dh), set())
            ps.discard(r["icao"])
            e["peers"] = len(ps)
            e["class"] = ("unlocated" if not e["vcells"] else "active" if ps else "post" if e["cand_post"] else "isolated")


def aggregate(recs):
    """Per hex-hour tables at res 4 and res 2, daily res-4 table, events, and diagnostics."""
    # peer geo medians per res-4 hex-hour
    peers = defaultdict(list)
    for r in recs:
        for k, v in r["geo"].items():
            peers[k].append(v)
    peer_med = {k: (statistics.median(v), len(v)) for k, v in peers.items() if len(v) >= GEO_PEER_MIN}

    classify(recs)
    t4 = defaultdict(lambda: [0] * len(COLS))
    t2 = defaultdict(lambda: [0] * len(COLS))
    d4 = defaultdict(lambda: [0, 0, 0, 0, 0])               # hex4 -> aircraft, spoofed, false_pos, jam, spoofed_active
    events, geo_out_aircraft, ep_geo_out = [], 0, 0
    for r in recs:
        mine4, mine2 = defaultdict(set), defaultdict(set)    # cell-hour -> set of column names this aircraft adds 1 to
        day_flags = defaultdict(set)
        jam_cells2 = defaultdict(lambda: [0, 0])
        for (hx, h), c in r["cells"].items():
            mine4[(hx, h)].add("aircraft"); day_flags[hx].add(0)
            if c[V2] and c[V2B] * 2 >= c[V2]:
                mine4[(hx, h)].add("jam")
            if c[KB] >= KIN_MIN_BAD and c[KB] * 2 >= c[KP]:
                mine4[(hx, h)].add("kin")
            p2 = parent(hx, RES2)
            mine2[(p2, h)].add("aircraft")
            j = jam_cells2[(p2, h)]; j[0] += c[V2]; j[1] += c[V2B]
            if "kin" in mine4[(hx, h)]:
                mine2[(p2, h)].add("kin")
        for k, (v2, v2b) in jam_cells2.items():
            if v2 and v2b * 2 >= v2:
                mine2[k].add("jam")
        # daily jam per hex4: over the day's trusted reports there
        per_hex = defaultdict(lambda: [0, 0])
        for (hx, h), c in r["cells"].items():
            per_hex[hx][0] += c[V2]; per_hex[hx][1] += c[V2B]
        for hx, (v2, v2b) in per_hex.items():
            if v2 and v2b * 2 >= v2:
                day_flags[hx].add(3)
        out_here = False
        for k, own in r["geo"].items():
            pm = peer_med.get(k)
            if pm and abs(own - pm[0]) >= GEO_PEER_FT:
                mine4[k].add("geo_out"); mine2[(parent(k[0], RES2), k[1])].add("geo_out"); out_here = True
        geo_out_aircraft += out_here
        for (hx, h), (n, dis, dis_tr) in r["mlat_cells"].items():
            p2 = (parent(hx, RES2), h)
            for t, k in ((t4, (hx, h)), (t2, p2)):
                t[k][CI["mlat_pairs"]] += n; t[k][CI["mlat_dis"]] += dis; t[k][CI["mlat_dis_trusted"]] += dis_tr
        for (hx, h), n in r["geo_flag"].items():
            if n >= GEO_FLAG_MIN:
                mine4[(hx, h)].add("geo_flag"); mine2[(parent(hx, RES2), h)].add("geo_flag")
        for hx, h in r["unresolved"]:
            t4[(hx, h)][CI["unresolved_jumps"]] += 1; t2[(parent(hx, RES2), h)][CI["unresolved_jumps"]] += 1
        any_geo_out_in_ep = False
        for e in r["episodes"]:
            cols = {"spoofed"} | {f"spoofed_{k}" for k in e["kinds"]}
            if e["clean_share"] is not None and e["clean_share"] >= 0.5:
                cols.add("spoofed_clean")
            if e["geo_hits"]:
                cols.add("spoofed_geo")
            if e["mlat_dis"]:
                cols.add("spoofed_mlat")
            if e["class"] in ("active", "post", "isolated"):
                cols.add(f"spoofed_{e['class']}")
            for hx, h in e["vcells"]:
                mine4[(hx, h)] |= cols | {"aircraft"}
                mine2[(parent(hx, RES2), h)] |= cols | {"aircraft"}
                day_flags[hx] |= {0, 1, 4} if e["class"] == "active" else {0, 1}
            for hx, h in e["fcells"]:
                mine4[(hx, h)].add("false_pos"); mine2[(parent(hx, RES2), h)].add("false_pos")
                day_flags[hx].add(2)
            if any(k in peer_med and abs(r["geo"].get(k, 1e9) - peer_med[k][0]) >= GEO_PEER_FT for k in e["vcells"]):
                any_geo_out_in_ep = True
            events.append({"icao": r["icao"], "type": r["type"], "cat": r["cat"],
                           "start": datetime.fromtimestamp(e["t0"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                           "end": datetime.fromtimestamp(e["t1"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                           **{k: v for k, v in e.items() if k not in ("t0", "t1", "vcells", "fcells")},
                           "victim_cells": sorted({h3.int_to_str(hx) for hx, _ in e["vcells"]}),
                           "victim_hours": sorted({h for _, h in e["vcells"]})})
        ep_geo_out += any_geo_out_in_ep
        for k, cols in mine4.items():
            row = t4[k]
            for c in cols:
                row[CI[c]] += 1
        for k, cols in mine2.items():
            row = t2[k]
            for c in cols:
                row[CI[c]] += 1
        for hx, fs in day_flags.items():
            for f in fs:
                d4[hx][f] += 1
    return t4, t2, d4, events, {"geo_out_aircraft": geo_out_aircraft, "episodes_with_geo_out_aircraft": ep_geo_out}


def run(day, raw_dir, out_dir, workers, limit=0):
    parts = P.day_parts(raw_dir, day)
    day0 = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())
    t0 = time.time()
    stream = io.BufferedReader(P.Chain(parts), buffer_size=8 << 20)
    recs, st = [], Counter()
    with Pool(workers) as pool:
        src = P.batches(stream, day0)
        if limit:
            src = itertools.islice(src, limit)
        for r, s in pool.imap_unordered(work, src, chunksize=1):
            recs.extend(r); st.update(s)
    chain = stream.raw
    t_read = time.time() - t0
    t4, t2, d4, events, diag = aggregate(recs)

    import pyarrow as pa, pyarrow.parquet as pq
    os.makedirs(out_dir, exist_ok=True)
    for name, tab in (("hex4", t4), ("hex2", t2)):
        rows = sorted(tab.items())
        cols = {"h3": [h3.int_to_str(hx) for (hx, _), _ in rows],
                "hour": pa.array([h for (_, h), _ in rows], pa.int8())}
        for c in COLS:
            cols[c] = pa.array([v[CI[c]] for _, v in rows], pa.int32())
        pq.write_table(pa.table(cols), os.path.join(out_dir, f"{day}.{name}.parquet"), compression="zstd")
    rows = sorted(d4.items())
    hexes = [h3.int_to_str(hx) for hx, _ in rows]
    ll = [h3.cell_to_latlng(h) for h in hexes]
    pq.write_table(pa.table({
        "h3": hexes, "lat": [round(a, 4) for a, _ in ll], "lon": [round(b, 4) for _, b in ll],
        "aircraft": pa.array([v[0] for _, v in rows], pa.int32()), "spoofed": pa.array([v[1] for _, v in rows], pa.int32()),
        "false_pos": pa.array([v[2] for _, v in rows], pa.int32()), "jam": pa.array([v[3] for _, v in rows], pa.int32()),
        "spoofed_active": pa.array([v[4] for _, v in rows], pa.int32()),
    }), os.path.join(out_dir, f"{day}.daily4.parquet"), compression="zstd")
    events.sort(key=lambda e: e["start"])
    with gzip.open(os.path.join(out_dir, f"{day}.events.json.gz"), "wt", encoding="utf-8") as f:
        json.dump(events, f, separators=(",", ":"))

    # spoofed-to points: res-6 cells by distinct aircraft with false positions there
    to_pts = Counter()
    for e in events:
        for c6 in set(e["false_cell6"][:1]):
            to_pts[c6] += 1
    nd = recs                               # duplicate suspects are kept (no excursion test for them)
    ml = [sum(r["mlat"][i] for r in nd) for i in range(4)]
    with_ep = [r for r in nd if r["episodes"]]
    ml_unflagged_dis = sum(1 for r in nd if not r["episodes"] and r["mlat"][1] >= 2)
    secs = time.time() - t0
    summary = {
        "day": day, "version": VERSION, "inputs": [os.path.basename(p) for p in parts],
        "input_bytes": chain.nbytes, "input_sha256": chain.sha.hexdigest(),
        "seconds": round(secs, 1), "seconds_read": round(t_read, 1), "workers": workers,
        **{k: st.get(k, 0) for k in ("files", "skipped", "parse_errors")},
        "aircraft": len(recs), "fast_aircraft": sum(r["fast"] for r in recs), "duplicate_suspects": len(recs) - len(nd),
        "aircraft_with_episodes": len(with_ep), "episodes": len(events),
        "episodes_by_kind": dict(Counter(k for e in events for k in e["kinds"])),
        "episodes_by_victim_how": dict(Counter(e["victim_how"] for e in events)),
        "episodes_by_class": dict(Counter(e["class"] for e in events)),
        "episodes_clean": sum(1 for e in events if e["clean_share"] is not None and e["clean_share"] >= 0.5),
        "episodes_with_geo": sum(1 for e in events if e["geo_hits"]),
        "episodes_with_mlat_pairs": sum(1 for e in events if e["mlat_pairs"]),
        "episodes_mlat_confirmed": sum(1 for e in events if e["mlat_dis"]),
        "mlat_pairs_trusted": ml[0], "mlat_disagree_trusted": ml[1], "mlat_pairs_false": ml[2], "mlat_disagree_false": ml[3],
        "aircraft_mlat_disagree_without_episode": ml_unflagged_dis,
        "points": sum(r["points"] for r in nd), "false_points": sum(r["false_points"] for r in nd),
        "flag_points": {k: sum(r["flag_points"][k] for r in nd) for k in ("slow", "loiter", "excursion", "geo_step", "geo_sat")},
        "geo_flag_points_on_false": sum(r["geo_false"] for r in nd), "geo_flag_points_on_trusted": sum(r["geo_trusted"] for r in nd),
        "unresolved_jumps": sum(len(r["unresolved"]) for r in nd), "jumps": sum(r["jumps"] for r in nd),
        **diag,
        "spoofed_to_res6_top": [[c, *[round(x, 3) for x in h3.cell_to_latlng(c)], n] for c, n in to_pts.most_common(40)],
        "victim_res2_top": Counter(h3.cell_to_parent(c, RES2) for e in events for c in set(e["victim_cells"])).most_common(40),
        "geo_sat_trusted_res2_top": Counter(h3.int_to_str(c) for r in nd for c in r["geo_sat_trusted_cells"]).most_common(20),
        "method": {k: v for k, v in globals().items() if k.isupper() and isinstance(v, (int, float, tuple, str))
                   and k not in ("T", "LAT", "LON", "ALT", "GS", "TRK", "GEO", "NACP", "NIC", "VER", "TR", "V2", "V2B", "KP", "KB", "ROOT", "VERSION")},
        "source": "adsb.lol globe_history (ODbL 1.0)",
    }
    summary["method"]["FAST_CATS"] = sorted(FAST_CATS)
    json.dump(summary, open(os.path.join(out_dir, f"{day}.summary.json"), "w"), indent=1, default=list)
    return summary


# ---------- report: known areas against quiet controls ----------

REGIONS = {   # (lat0, lat1, lon0, lon1); expectations are from public reporting, see docs/validation/spoofing.md
    "east_med": ((32.0, 36.5, 29.0, 36.0), "known"),          # Cyprus, Lebanon coast, Nicosia FIR
    "egypt_jordan": ((27.0, 32.0, 29.0, 37.5), "known"),      # northern Cairo FIR, Sinai, Jordan
    "iraq": ((29.0, 37.5, 38.8, 48.5), "known"),
    "gulf": ((23.5, 29.5, 48.0, 57.0), "known"),            # Persian Gulf incl. the Iranian coast (listed before iran:
    "iran": ((25.0, 39.8, 48.5, 63.0), "known"),            #   a cell counts in the first box that holds it)
    "black_sea_s": ((40.5, 43.5, 28.0, 41.5), "known"),       # Turkish coast and offshore
    "black_sea_w": ((42.0, 46.5, 26.5, 31.0), "known"),       # Bulgarian and Romanian coast
    "baltic_e": ((53.5, 60.5, 19.0, 28.5), "known"),          # Kaliningrad, Baltic states, Gulf of Finland
    "baltic_sw": ((52.0, 58.0, 12.0, 19.0), "known"),         # southern Baltic Sea, Poland west of 19E (from Nov 2024)
    "russia_w": ((52.0, 60.0, 28.5, 40.0), "known"),          # Smolensk, Moscow (thin adsb.lol coverage)
    "myanmar": ((14.0, 23.0, 92.0, 99.0), "known"),
    "india_pak": ((24.0, 33.0, 68.0, 77.0), "known"),
    "c_europe": ((46.0, 52.0, 2.0, 15.0), "control"),         # France east, Benelux, Germany, Switzerland, Austria
    "uk_ie": ((50.0, 58.0, -10.0, 2.0), "control"),
    "us_east": ((30.0, 45.0, -90.0, -70.0), "control"),
    "us_west": ((32.0, 45.0, -123.0, -105.0), "control"),
    "canada": ((48.0, 65.0, -125.0, -60.0), "control"),
    "australia": ((-40.0, -12.0, 113.0, 154.0), "control"),
}
GROUPS = {
    "Middle East": ["east_med", "egypt_jordan", "iraq", "iran", "gulf"],
    "Black Sea": ["black_sea_s", "black_sea_w"],
    "Baltic and W Russia": ["baltic_e", "baltic_sw", "russia_w"],
    "South Asia": ["myanmar", "india_pak"],
    "Controls": ["c_europe", "uk_ie", "us_east", "us_west", "canada", "australia"],
}
# Spoofed-to points named in public sources (coordinates of the named airport, or the city centre: approximate), and
# places used only to say where an unnamed point is (marked *)
REF_POINTS = {
    "Amman OJAI": (31.7226, 35.9932), "Beirut OLBA": (33.8209, 35.4884), "Cairo HECA": (30.1219, 31.4056),
    "Tel Aviv LLBG": (32.0114, 34.8867), "Simferopol UKFF": (45.0522, 33.9751), "Belbek UKFB": (44.6919, 33.5710),
    "Smolensk": (54.78, 32.05), "Krasnodar URKK": (45.0347, 39.1705), "Moscow": (55.7558, 37.6173),
    "Yaroslavl": (57.6261, 39.8845), "Yangon VYYY": (16.9073, 96.1332), "Kaliningrad": (54.71, 20.51),
    "Bandar Abbas (ships)": (27.18, 56.27), "Asaluyeh (ships)": (27.48, 52.61),
    "*Moscow UUEE": (55.9726, 37.4146), "*Perm": (57.91, 56.02), "*Amritsar": (31.71, 74.80), "*Dawei": (14.10, 98.20),
    "*Ufa": (54.56, 55.87), "*Veliky Novgorod": (58.52, 31.27), "*Sochi": (43.60, 39.73),
}
_LL = {}


def inbox(lat, lon, b):
    return b[0] <= lat <= b[1] and b[2] <= lon <= b[3]


def region_of(h):
    """First region box holding the centre of H3 cell h (string), or None."""
    if h not in _LL:
        _LL[h] = h3.cell_to_latlng(h)
    lat, lon = _LL[h]
    for name, (box, _) in REGIONS.items():
        if inbox(lat, lon, box):
            return name
    return None


def pct(a, b, nd=2):
    return f"{100 * a / b:.{nd}f}" if b else "-"


def spearman(x, y):
    def rank(v):
        o = sorted(range(len(v)), key=v.__getitem__)
        r, i = [0.0] * len(v), 0
        while i < len(o):
            j = i
            while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
                j += 1
            for k in range(i, j + 1):
                r[o[k]] = (i + j) / 2
            i = j + 1
        return r
    if len(x) < 3:
        return float("nan")
    rx, ry = rank(x), rank(y)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else float("nan")


def report(days, out_dir, metric="spoofed_active"):
    """Markdown tables for docs/validation/spoofing.md: shares by region and day, pooled indicators by region group,
    control-region episodes, spoofed-to points against published ones, per-day diagnostics, comparison with the
    jamming tables (data/pnt/validation2024 or data/pnt/year, where present)."""
    import pyarrow.parquet as pq
    t4, ev, sm = {}, {}, {}
    for d in days:
        t4[d] = pq.read_table(os.path.join(out_dir, f"{d}.hex4.parquet")).to_pylist()
        ev[d] = json.load(gzip.open(os.path.join(out_dir, f"{d}.events.json.gz"), "rt"))
        sm[d] = json.load(open(os.path.join(out_dir, f"{d}.summary.json")))
    rs = {}
    for d in days:
        rs[d] = defaultdict(Counter)
        for r in t4[d]:
            reg = region_of(r["h3"])
            if reg:
                for c in COLS:
                    rs[d][reg][c] += r[c]
    ep_regions = lambda e: {region_of(c) for c in e["victim_cells"]} - {None}

    for m in (metric, "spoofed"):
        print(f"\n### {m}: share of aircraft-hours by region and day (%; '.' = under 200 aircraft-hours)\n")
        print("| Region | " + " | ".join(d[2:] for d in days) + " |")
        print("|---" * (len(days) + 1) + "|")
        for name in REGIONS:
            print(f"| {name} | " + " | ".join(pct(rs[d][name][m], rs[d][name]["aircraft"]) if rs[d][name]["aircraft"] >= 200
                                             else "." for d in days) + " |")

    cols = ["spoofed", "spoofed_active", "spoofed_post", "spoofed_isolated", "spoofed_slow", "spoofed_loiter",
            "spoofed_excursion", "spoofed_clean", "spoofed_geo", "geo_flag", "geo_out", "kin", "jam"]
    print("\n### Pooled over the days: indicators by region (% of aircraft-hours)\n")
    print("| Region | kind | aircraft-hours | " + " | ".join(cols) + " | MLAT pairs | disagree | disagree, trusted |")
    print("|---" * (len(cols) + 6) + "|")
    rows = [(g, "group", regs) for g, regs in GROUPS.items()] + [(n, k, [n]) for n, (b, k) in REGIONS.items()]
    for name, kind, regs in rows:
        tot = Counter()
        for d in days:
            for reg in regs:
                tot.update(rs[d][reg])
        print(f"| {name} | {kind} | {tot['aircraft']} | " + " | ".join(pct(tot[c], tot["aircraft"], 3) for c in cols)
              + f" | {tot['mlat_pairs']} | {tot['mlat_dis']} | {tot['mlat_dis_trusted']} |")

    ctl = {n for n, (b, k) in REGIONS.items() if k == "control"}
    print("\n### Episodes located in a control box\n")
    by = Counter()
    for d in days:
        for e in ev[d]:
            hit = ep_regions(e) & ctl
            if hit:
                by[e["class"]] += 1
                print(f"- {d} {e['start'][11:16]}-{e['end'][11:16]} {e['type'] or '?'} {e['cat']} {','.join(sorted(hit))} "
                      f"{e['class']} peers={e['peers']} kinds={'+'.join(e['kinds'])} n={e['n']} alt={e['alt']} "
                      f"shown=({e['false_lat']},{e['false_lon']}) nacp={e['nacp_median']} mlat={e['mlat_pairs']}/{e['mlat_dis']}")
    print("by class:", dict(by))

    print("\n### Spoofed-to points: top res-6 cells per day (distinct aircraft), nearest published point\n")
    for d in days:
        items = []
        for c, la, lo, n in sm[d]["spoofed_to_res6_top"][:6]:
            name, dist = min(((k, km(la, lo, *v)) for k, v in REF_POINTS.items()), key=lambda x: x[1])
            items.append(f"{la:.2f}N {lo:.2f}E x{n} ({name} {dist:.0f} km)")
        print(f"- {d}: " + "; ".join(items))

    keys = ["aircraft", "episodes", "aircraft_with_episodes", "episodes_clean", "episodes_with_geo",
            "episodes_with_mlat_pairs", "episodes_mlat_confirmed", "mlat_pairs_trusted", "mlat_disagree_trusted",
            "mlat_pairs_false", "mlat_disagree_false", "unresolved_jumps", "duplicate_suspects", "seconds"]
    print("\n### Per day\n")
    print("| day | " + " | ".join(keys) + " | classes |")
    print("|---" * (len(keys) + 2) + "|")
    tot, cls = Counter(), Counter()
    for d in days:
        print(f"| {d} | " + " | ".join(str(sm[d][k]) for k in keys) + f" | {sm[d]['episodes_by_class']} |")
        for k in keys:
            tot[k] += sm[d][k]
        cls.update(sm[d]["episodes_by_class"])
    print("\ntotals:", dict(tot), dict(cls))

    print(f"\n### {metric} against jamming (official PNT tables where present), res-4 hexes with >= 30 aircraft\n")
    for d in days:
        off = None
        for sub in ("validation2024", "year"):
            p = os.path.join(ROOT, "data", "pnt", sub, f"{d}.parquet")
            if os.path.exists(p):
                off = {r["h3"]: r for r in pq.read_table(p, columns=["h3", "aircraft", "bad_nacp_live"]).to_pylist()}
                break
        if not off:
            print(f"- {d}: no jamming table"); continue
        dd = pq.read_table(os.path.join(out_dir, f"{d}.daily4.parquet")).to_pylist()
        xs, ys, pj, c = [], [], [], Counter()
        for r in dd:
            o = off.get(r["h3"])
            if r["aircraft"] < 30 or not o or o["aircraft"] < 30:
                continue
            sp, jo = r[metric] / r["aircraft"], o["bad_nacp_live"] / o["aircraft"]
            xs.append(sp); ys.append(jo); pj.append(r["jam"] / r["aircraft"])
            c["n"] += 1; c["both"] += sp >= 0.02 and jo >= 0.10; c["spoof_only"] += sp >= 0.02 and jo < 0.10
            c["jam_only"] += sp < 0.005 and jo >= 0.25
        print(f"- {d}: {c['n']} hexes; spoofed >= 2% and jammed >= 10%: {c['both']}; spoofed >= 2%, jammed < 10%: "
              f"{c['spoof_only']}; jammed >= 25%, spoofed < 0.5%: {c['jam_only']}; Spearman {spearman(xs, ys):.2f}; "
              f"jam proxy against the jamming table, Spearman {spearman(pj, ys):.2f}")

    print(f"\n### Active episodes by region (pooled)\n")
    reg_eps = defaultdict(Counter)
    for d in days:
        for e in ev[d]:
            if e["class"] != "active":
                continue
            for reg in ep_regions(e) or {"other"}:
                c = reg_eps[reg]
                c["n"] += 1; c["clean"] += (e["clean_share"] or 0) >= 0.5
                c["low"] += e["nacp_median"] is not None and e["nacp_median"] < 7
                c["geo"] += e["geo_hits"] > 0; c["mlat"] += e["mlat_pairs"] > 0; c["conf"] += e["mlat_dis"] > 0
                for k in e["kinds"]:
                    c[k] += 1
    print("| Region | active episodes | slow | loiter | excursion | false positions NACp >= 8 | NACp < 7 | geo corroborated "
          "| with MLAT | MLAT confirms |")
    print("|---" * 10 + "|")
    for reg, c in sorted(reg_eps.items(), key=lambda x: -x[1]["n"]):
        print(f"| {reg} | {c['n']} | {c['slow']} | {c['loiter']} | {c['excursion']} | {c['clean']} | {c['low']} | {c['geo']} "
              f"| {c['mlat']} | {c['conf']} |")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "report"])
    ap.add_argument("days", nargs="+")
    ap.add_argument("--raw", help="folder with the day's tar or split parts (default data/raw/trace_box/<day>)")
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "spoofing"))
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--limit", type=int, default=0, help="process only the first N batches of 400 traces (testing)")
    a = ap.parse_args()
    if a.cmd == "run":
        for day in a.days:
            raw = a.raw or os.path.join(ROOT, "data", "raw", "trace_box", day)
            s = run(day, raw, a.out, a.workers, a.limit)
            print(json.dumps({k: s[k] for k in ("day", "seconds", "files", "aircraft", "episodes", "aircraft_with_episodes",
                                                 "episodes_by_kind", "episodes_mlat_confirmed", "duplicate_suspects")}), flush=True)
    else:
        report(a.days, a.out)


if __name__ == "__main__":
    main()
