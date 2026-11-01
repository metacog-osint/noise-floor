#!/usr/bin/env python3
"""geo_callouts.py: GEO callouts C1-C8 over the held element history, by the frozen rules in
docs/validation/geo-callouts.md (v1). Behaviour only, never intent.

  python tools/geo_callouts.py run [--data DIR] [--start D] [--end D] [--out FILE]
      every callout over the span, from the monthly element files and the day region files in DIR
      (default data/geo/region); writes FILE (default data/geo/callouts/callouts-v1.json)
  python tools/geo_callouts.py case --elements FILE --ids A,B[,C] --start D --end D [--owners A=X,B=Y]
      the same rules on a few objects alone (a published case before the held history), from a stored
      gp_history JSON file

  python tools/geo_callouts.py pull     the gp_history each pre-history case needs (Space-Track, once, stored)
  python tools/geo_callouts.py score    every case in docs/validation/geo-callouts-cases.json against the held run
                                       and the case runs; data/geo/callouts/score-v1.json

SGP4 from the sgp4 library (MIT), WGS72 constants, TEME positions in km; numpy for the arrays.
Orbital data: USSPACECOM (space-track.org).
"""
import argparse
import bisect
import glob
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
from sgp4.api import WGS72, Satrec, jday

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "geo", "region")
OUT = os.path.join(ROOT, "data", "geo", "callouts", "callouts-v1.json")
ROLES = os.path.join(ROOT, "site_src", "geo_roles.json")
CITE = "Orbital data: USSPACECOM (space-track.org)"
SIDEREAL = 360.98564736629
VERSION = "v1"

# frozen thresholds (docs/validation/geo-callouts.md, v1)
MAX_AGE_DAYS = 10.0          # element sets older than this at an instant are not used
HOLD = 0.1                   # deg/day: holding longitude
KEPT_INC = 1.0               # deg: a station-kept neighbour (C3, C4) also holds inclination under this
BURN_DRIFT, BURN_GAP_D = 0.02, 3.0   # C3: a drift change this large between sets this close is a manoeuvre
C1_KM, C2_KM, C2_FALL, C2_DAYS, C2_QUIET = 100.0, 200.0, 30.0, 3, 14
C3_STOPPED, C3_LOOKBACK, C3_DEG, C3_QUIET = 0.05, 14, 0.5, 30
C4_LOOKBACK, C4_HORIZON, C4_DEG, C4_QUIET = 7, 14, 0.5, 30
C5_GAP_H, C5_DRIFT, C5_INC, C5_LON = 12.0, 0.02, 0.02, 0.15
CANDIDATE_DEG = 3.0          # pairs further apart than this in longitude at noon are far (over 2,000 km)
EVENT_RULES = {"arrived": "C6", "left up": "C7", "quiet": "C8"}


# ---------------------------------------------------------------- inputs
def parse_epoch(s):
    s = s.replace("Z", "")
    fmt = "%Y-%m-%dT%H:%M:%S.%f" if "." in s else "%Y-%m-%dT%H:%M:%S"
    return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)


def load_elements(data):
    """{norad: [rows sorted by epoch]} from every geo-elements-*.parquet in data."""
    import pyarrow.parquet as pq
    by = {}
    for p in sorted(glob.glob(os.path.join(data, "geo-elements-*.parquet"))):
        t = pq.read_table(p).to_pydict()
        cols = list(t)
        for vals in zip(*(t[c] for c in cols)):
            r = dict(zip(cols, vals))
            by.setdefault(int(r["norad"]), []).append(r)
    return finish(by)


def load_history_json(path, ids=None):
    """Rows from a stored Space-Track gp_history JSON file (OMM field names)."""
    raw = json.load(open(path, encoding="utf-8"))
    by = {}
    for g in raw:
        k = int(g["NORAD_CAT_ID"])
        if ids and k not in ids:
            continue
        num = lambda x: float(x) if x not in (None, "") else 0.0  # noqa: E731
        by.setdefault(k, []).append({"norad": k, "epoch": g["EPOCH"], "n": num(g["MEAN_MOTION"]), "e": num(g["ECCENTRICITY"]),
                                     "i": num(g["INCLINATION"]), "raan": num(g["RA_OF_ASC_NODE"]), "argp": num(g["ARG_OF_PERICENTER"]),
                                     "M": num(g["MEAN_ANOMALY"]), "bstar": num(g.get("BSTAR")), "ndot": num(g.get("MEAN_MOTION_DOT")),
                                     "nddot": num(g.get("MEAN_MOTION_DDOT"))})
    return finish(by)


def finish(by):
    for k, rows in by.items():
        rows.sort(key=lambda r: r["epoch"])
        uniq = []
        for r in rows:
            if uniq and uniq[-1]["epoch"] == r["epoch"]:
                uniq[-1] = r
            else:
                uniq.append(r)
        for r in uniq:
            r["t"] = parse_epoch(r["epoch"]).timestamp()
            r["drift"] = 360.0 * r["n"] - SIDEREAL
        by[k] = uniq
    return by


def load_static(data):
    """{norad: {name, owner, type}} from the newest day region file that carries objects."""
    for p in sorted(glob.glob(os.path.join(data, "*.geo-region.json")), reverse=True):
        d = json.load(open(p, encoding="utf-8"))
        if d.get("objects"):
            cols = d["object_cols"]
            return {int(r[cols.index("norad")]): {"name": r[cols.index("name")], "owner": r[cols.index("owner")],
                                                  "type": r[cols.index("type")]} for r in d["objects"]}
    return {}


def load_events(data, start, end):
    out = []
    for p in sorted(glob.glob(os.path.join(data, "*.geo-region.json"))):
        day = os.path.basename(p)[:10]
        if start <= day <= end:
            for e in json.load(open(p, encoding="utf-8")).get("events", []):
                if e["kind"] in EVENT_RULES:
                    out.append(e)
    return out


def load_roles(path=ROLES):
    try:
        d = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {int(o["id"]): o["role"] for o in d.get("objects", []) if o.get("role") in ("inspection", "servicing")}


# ---------------------------------------------------------------- SGP4
_SAT = {}


def satrec(r):
    key = (r["norad"], r["epoch"], r["n"], r["e"], r["i"], r["raan"], r["argp"], r["M"])
    s = _SAT.get(key)
    if s is None:
        ep = parse_epoch(r["epoch"])
        jd, fr = jday(ep.year, ep.month, ep.day, ep.hour, ep.minute, ep.second + ep.microsecond / 1e6)
        s = Satrec()
        s.sgp4init(WGS72, "i", int(r["norad"]) % 100000, jd + fr - 2433281.5, r.get("bstar") or 0.0,
                   (r.get("ndot") or 0.0) * 2 * math.pi / 1440 ** 2, (r.get("nddot") or 0.0) * 2 * math.pi / 1440 ** 3,
                   r["e"], math.radians(r["argp"]), math.radians(r["i"]), math.radians(r["M"]),
                   r["n"] * 2 * math.pi / 1440.0, math.radians(r["raan"]))
        _SAT[key] = s
    return s


def jd_of(ts):
    """Julian date (whole, fraction) arrays for unix seconds."""
    jd = np.asarray(ts, dtype=float) / 86400.0 + 2440587.5
    whole = np.floor(jd - 0.5) + 0.5
    return whole, jd - whole


def gmst_rad(ts):
    d = np.asarray(ts, dtype=float) / 86400.0 + 2440587.5 - 2451545.0
    T = d / 36525.0
    return np.radians((280.46061837 + 360.98564736629 * d + 0.000387933 * T * T - T ** 3 / 38710000.0) % 360.0)


def element_at(rows, t, ts=None):
    """The latest element set with epoch at or before t (unix seconds) and no older than MAX_AGE_DAYS, or None.
    ts: the rows' epochs, precomputed (a speed-up only)."""
    ts = ts if ts is not None else [r["t"] for r in rows]
    k = bisect.bisect_right(ts, t) - 1
    if k < 0 or t - rows[k]["t"] > MAX_AGE_DAYS * 86400:
        return None
    return rows[k]


def positions(rows, times, ts=None):
    """TEME km (len(times) x 3), NaN where no usable element set; and the element set used at each time."""
    out = np.full((len(times), 3), np.nan)
    ts = ts if ts is not None else [r["t"] for r in rows]
    used = [element_at(rows, t, ts) for t in times]
    k = 0
    while k < len(times):
        r = used[k]
        j = k
        while j + 1 < len(times) and used[j + 1] is r:
            j += 1
        if r is not None:
            whole, frac = jd_of(times[k:j + 1])
            e, p, _ = satrec(r).sgp4_array(whole, frac)
            p = np.asarray(p, dtype=float)
            p[np.asarray(e) != 0] = np.nan
            out[k:j + 1] = p
        k = j + 1
    return out, used


def lon_deg(p, ts):
    return (np.degrees(np.arctan2(p[..., 1], p[..., 0]) - gmst_rad(ts)) + 540.0) % 360.0 - 180.0


def wrap(d):
    return (d + 540.0) % 360.0 - 180.0


# ---------------------------------------------------------------- the rules
def days_between(start, end):
    d0 = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    d1 = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return [(d0 + timedelta(days=k)) for k in range((d1 - d0).days + 1)]


def run(elements, static, roles, start, end, events=None, ids=None, owners=None):
    """Every callout from start to end (UTC days, inclusive). ids: limit to these objects (a case run)."""
    owners = owners or {}
    own = lambda k: owners.get(k, (static.get(k) or {}).get("owner"))  # noqa: E731
    name = lambda k: (static.get(k) or {}).get("name") or str(k)  # noqa: E731
    if ids:
        pay = [k for k in ids if k in elements]
    else:
        pay = sorted(k for k in elements if (static.get(k) or {}).get("type") == "PAYLOAD")
    days = days_between(start, end)
    nd, npay = len(days), len(pay)
    noon = np.array([d.timestamp() + 43200 for d in days])
    lon = np.full((nd, npay), np.nan)
    drift = np.full((nd, npay), np.nan)
    incl = np.full((nd, npay), np.nan)
    pos = {}                                                    # (day index) -> (npay x 24 x 3)
    TS = {k: [r["t"] for r in elements[k]] for k in pay}       # epochs per object, built once (speed only)
    IDX = {k: j for j, k in enumerate(pay)}
    for di, d in enumerate(days):
        hours = [d.timestamp() + 3600 * h for h in range(24)]
        P = np.full((npay, 24, 3), np.nan)
        for j, k in enumerate(pay):
            P[j], used = positions(elements[k], hours, TS[k])
            r = used[12]
            if r is not None and not np.isnan(P[j, 12, 0]):
                lon[di, j] = lon_deg(P[j, 12], noon[di])
                drift[di, j] = r["drift"]
                incl[di, j] = r["i"]
        pos[di] = P
    callouts = []

    def other_owner(a, b):
        oa, ob = own(a), own(b)
        return not oa or not ob or oa != ob

    # day values for candidate pairs: {(a, b): array over days}, inf where far apart, nan where unknown
    dv = {}
    for di in range(nd):
        L = lon[di]
        ok = np.where(~np.isnan(L))[0]
        order = ok[np.argsort(L[ok])]
        m = len(order)
        for x in range(m):
            for y in range(x + 1, x + m):
                jj = order[y % m]
                if abs(wrap(L[jj] - L[order[x]])) > CANDIDATE_DEG:
                    break
                a, b = pay[order[x]], pay[jj]
                if a == b or not other_owner(a, b):
                    continue
                key = (min(a, b), max(a, b))
                if key in dv and not np.isnan(dv[key][di]) and dv[key][di] != np.inf:
                    continue
                ia, ib = IDX[key[0]], IDX[key[1]]
                sep = np.linalg.norm(pos[di][ia] - pos[di][ib], axis=1)
                val = np.nanmin(sep) if np.any(~np.isnan(sep)) else np.nan
                arr = dv.setdefault(key, np.full(nd, np.inf))
                arr[di] = val
    known = ~np.isnan(lon)
    for key, arr in dv.items():                                 # a day with no position for either is unknown, not far
        ia, ib = IDX[key[0]], IDX[key[1]]
        arr[~(known[:, ia] & known[:, ib])] = np.nan

    def pair_rec(rule, di, a, b, **kw):
        rec = {"rule": rule, "day": days[di].strftime("%Y-%m-%d"), "a": [a, name(a), own(a)], "b": [b, name(b), own(b)]}
        lvl = [roles[k] for k in (a, b) if k in roles]
        if lvl:
            rec["role"] = lvl[0]
        rec.update(kw)
        return rec

    # C1: episodes under 100 km; one non-qualifying or unknown day doesn't break an episode
    for (a, b), arr in dv.items():
        q = np.where(~np.isnan(arr), arr < C1_KM, False)
        di = 0
        while di < nd:
            if not q[di]:
                di += 1
                continue
            s = di
            last = di
            while di + 1 < nd and (q[di + 1] or (di + 2 < nd and q[di + 2])):
                di += 1
                if q[di]:
                    last = di
            span = arr[s:last + 1]
            callouts.append(pair_rec("C1", s, a, b, end=days[last].strftime("%Y-%m-%d"), min_km=round(float(np.nanmin(span)), 1),
                                     standing=bool(s == 0)))
            di = last + 1

    # C2: three consecutive daily falls, now under 200 km, total fall at least 30 km
    for (a, b), arr in dv.items():
        quiet_until = -1
        for di in range(C2_DAYS, nd):
            w = arr[di - C2_DAYS:di + 1]
            if np.any(np.isnan(w)) or di <= quiet_until:
                continue
            if all(w[k] > w[k + 1] for k in range(C2_DAYS)) and w[-1] < C2_KM and w[0] - w[-1] >= C2_FALL:
                callouts.append(pair_rec("C2", di, a, b, km=round(float(w[-1]), 1),
                                         from_km=None if np.isinf(w[0]) else round(float(w[0]), 1)))
                quiet_until = di + C2_QUIET - 1

    holding = (np.abs(drift) < HOLD) & (incl < KEPT_INC)       # station-kept neighbours only (inclined ones are far in 3D)

    def neighbour(di, j, within):
        """The nearest other-owner payload holding longitude within `within` degrees on day di, or None."""
        best = None
        for jj in range(npay):
            if jj == j or not holding[di, jj] or np.isnan(lon[di, jj]) or not other_owner(pay[j], pay[jj]):
                continue
            d = abs(wrap(lon[di, jj] - lon[di, j]))
            if d <= within and (best is None or d < best[1]):
                best = (jj, d)
        return best

    for j, k in enumerate(pay):
        rows = elements[k]
        q3 = q4 = -1
        for di in range(1, nd):
            if np.isnan(drift[di, j]) or np.isnan(lon[di, j]):
                continue
            # C3: was drifting in the last 14 days, stopped on D-1 and D, within 0.5 deg of another owner holding longitude
            if di > q3 and abs(drift[di, j]) < C3_STOPPED and not np.isnan(drift[di - 1, j]) and abs(drift[di - 1, j]) < C3_STOPPED:
                t0, t1 = noon[di] - C3_LOOKBACK * 86400, noon[di]
                recent = [r for r in rows if t0 <= r["t"] <= t1]
                burned = any(abs(b["drift"] - a["drift"]) > BURN_DRIFT and b["t"] - a["t"] <= BURN_GAP_D * 86400
                             for a, b in zip(recent, recent[1:]))   # a manoeuvre, not the slow end of a libration
                if burned and any(abs(r["drift"]) >= HOLD for r in recent):
                    nb = neighbour(di, j, C3_DEG)
                    if nb:
                        callouts.append({"rule": "C3", "day": days[di].strftime("%Y-%m-%d"), "a": [k, name(k), own(k)],
                                         "b": [pay[nb[0]], name(pay[nb[0]]), own(pay[nb[0]])], "deg": round(nb[1], 3),
                                         "lon": round(float(lon[di, j]), 2), **({"role": roles[k]} if k in roles else {})})
                        q3 = di + C3_QUIET - 1
            # C4: drifting, slowed to at most half its largest drift of the last 7 days, heading for an occupied slot
            dr = drift[di, j]
            if di > q4 and abs(dr) >= HOLD:
                back = drift[max(0, di - C4_LOOKBACK):di, j]
                back = back[~np.isnan(back)]
                if len(back) and abs(dr) <= 0.5 * np.max(np.abs(back)):
                    best = None
                    for jj in range(npay):
                        if jj == j or not holding[di, jj] or np.isnan(lon[di, jj]) or not other_owner(k, pay[jj]):
                            continue
                        gap = wrap(lon[di, jj] - lon[di, j])
                        if abs(gap) > C4_DEG and np.sign(gap) == np.sign(dr) and abs(gap) - C4_DEG <= abs(dr) * C4_HORIZON:
                            eta = (abs(gap) - C4_DEG) / abs(dr)
                            if best is None or eta < best[1]:
                                best = (jj, eta, gap)
                    if best:
                        callouts.append({"rule": "C4", "day": days[di].strftime("%Y-%m-%d"), "a": [k, name(k), own(k)],
                                         "b": [pay[best[0]], name(pay[best[0]]), own(pay[best[0]])], "days": round(best[1], 1),
                                         "deg": round(float(best[2]), 2), "drift": round(float(dr), 3),
                                         **({"role": roles[k]} if k in roles else {})})
                        q4 = di + C4_QUIET - 1

    # C5: orbit changes by listed-role objects
    t_lo, t_hi = days[0].timestamp(), days[-1].timestamp() + 86400
    for k, role in roles.items():
        if k not in elements or (ids and k not in ids):
            continue
        rows, ref, seen = elements[k], None, set()
        for r in rows:
            if ref is None:
                ref = r
                continue
            if r["t"] - ref["t"] < C5_GAP_H * 3600:
                continue
            if t_lo <= r["t"] < t_hi:
                p, _ = positions([ref], [r["t"]])       # the earlier set carried to the later epoch
                q, _ = positions([r], [r["t"]])
                dlon = abs(wrap(float(lon_deg(p[0], r["t"]) - lon_deg(q[0], r["t"])))) if not np.isnan(p[0, 0]) else 0.0
                ddrift, dinc = abs(r["drift"] - ref["drift"]), abs(r["i"] - ref["i"])
                day = datetime.fromtimestamp(r["t"], timezone.utc).strftime("%Y-%m-%d")
                if (ddrift > C5_DRIFT or dinc > C5_INC or dlon > C5_LON) and day not in seen:
                    seen.add(day)
                    callouts.append({"rule": "C5", "day": day, "a": [k, name(k), own(k)], "role": role,
                                     "between": [ref["epoch"][:16], r["epoch"][:16]], "drift_change": round(ddrift, 4),
                                     "inc_change": round(dinc, 4), "lon_off_deg": round(dlon, 3)})
            ref = r

    for e in events or []:
        callouts.append({"rule": EVENT_RULES[e["kind"]], "day": e["day"], "a": [e["norad"], e.get("name"), e.get("owner")],
                         "kind": e["kind"], "region": e.get("region"), "from": e.get("from")})
    callouts.sort(key=lambda c: (c["day"], c["rule"], c["a"][0]))
    return {"version": VERSION, "rules": "docs/validation/geo-callouts.md", "start": start, "end": end, "source": CITE,
            "objects": npay, "pairs_checked": len(dv), "callouts": callouts}


def weekly(doc):
    """New callouts per rule per ISO week (standing C1 episodes left out)."""
    out = {}
    for c in doc["callouts"]:
        if c.get("standing"):
            continue
        d = datetime.strptime(c["day"], "%Y-%m-%d")
        wk = f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
        out.setdefault(c["rule"], {}).setdefault(wk, 0)
        out[c["rule"]][wk] += 1
    return out


# ---------------------------------------------------------------- published cases: pull, then score
CASES = os.path.join(ROOT, "docs", "validation", "geo-callouts-cases.json")
CASE_DIR = os.path.join(ROOT, "data", "geo", "region", "history", "cases")
SCORE = os.path.join(ROOT, "data", "geo", "callouts", "score-v1.json")
DEFAULT_ON_HITS, DEFAULT_ON_WEEKLY = 0.5, 10.0       # frozen switch-on criteria


def case_file(case):
    p = case["pull"]
    return os.path.join(CASE_DIR, f"{case['id']}_{p['start']}_{p['end']}.json")


def pull(cases):
    """One gp_history request per case before the held history; stored and never fetched again."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import time
    import geo_region as R
    todo = [c for c in cases if c["scope"] == "history" and not os.path.exists(case_file(c))]
    if not todo:
        print("every case's history is held")
        return
    os.makedirs(CASE_DIR, exist_ok=True)
    with R.SpaceTrack() as st:
        for k, c in enumerate(todo):
            if k:
                time.sleep(R.PAUSE)
            p = c["pull"]
            data = st.query(R.history_path(p["ids"], p["start"], p["end"]))
            with open(case_file(c) + ".part", "w", encoding="utf-8") as f:
                json.dump(data, f, separators=(",", ":"))
            os.replace(case_file(c) + ".part", case_file(c))
            print(f"{c['id']}: {len(data)} element sets for {p['ids']}")


def matches(c, e):
    if c["rule"] != e["rule"]:
        return False
    lo, hi = e["window"]
    if c["rule"] == "C1":
        if c["day"] > hi or c.get("end", c["day"]) < lo:
            return False
    elif not lo <= c["day"] <= hi:
        return False
    ids = e["ids"]
    if c["rule"] in ("C1", "C2"):
        pair = {c["a"][0], c["b"][0]}
        return pair == set(ids) if len(ids) == 2 else ids[0] in pair
    if c["a"][0] != ids[0]:
        return False
    return not (c.get("b") and c["b"][0] in e.get("not_neighbour", []))


def score(held_path=OUT):
    spec = json.load(open(CASES, encoding="utf-8"))
    held = json.load(open(held_path, encoding="utf-8"))
    roles, static = load_roles(), load_static(DATA)
    rows, runs = [], {}
    for case in spec["cases"]:
        if case["scope"] == "held":
            callouts = held["callouts"]
        else:
            if not os.path.exists(case_file(case)):
                for e in case["expect"]:
                    rows.append({"case": case["id"], **e, "found": [], "hit": None, "note": "history not pulled"})
                continue
            p = case["pull"]
            doc = run(load_history_json(case_file(case), set(p["ids"])), static, roles, p["start"], p["end"], ids=p["ids"])
            runs[case["id"]] = doc
            callouts = doc["callouts"]
        for e in case["expect"]:
            found = [c for c in callouts if matches(c, e)]
            hit = bool(found) if e["outcome"] == "fire" else not found
            rows.append({"case": case["id"], **e, "found": found[:5], "hit": hit})
    by_rule = {}
    for r in rows:
        if r["hit"] is None:
            continue
        s = by_rule.setdefault(r["rule"], {"scored": 0, "hits": 0})
        s["scored"] += 1
        s["hits"] += int(r["hit"])
    wk = held.get("weekly") or weekly(held)
    weeks = max(1, len({w for ws in wk.values() for w in ws}))
    span_weeks = max(1.0, (datetime.strptime(held["end"], "%Y-%m-%d") - datetime.strptime(held["start"], "%Y-%m-%d")).days / 7 + 1 / 7)
    decide = {}
    for rule in ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"):
        s = by_rule.get(rule, {"scored": 0, "hits": 0})
        per_week = sum(wk.get(rule, {}).values()) / span_weeks
        busiest = max(wk.get(rule, {}).items(), key=lambda x: x[1], default=(None, 0))
        hits_ok = (s["hits"] / s["scored"] >= DEFAULT_ON_HITS) if s["scored"] else rule in ("C6", "C7", "C8")
        decide[rule] = {**s, "new_per_week": round(per_week, 2), "busiest_week": busiest[0], "busiest_count": busiest[1],
                        "default_on": bool(hits_ok and per_week <= DEFAULT_ON_WEEKLY)}
    out = {"version": VERSION, "scored_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "held_span": [held["start"], held["end"]],
           "weeks_with_callouts": weeks, "rules": decide, "expectations": rows,
           "case_runs": {k: {"start": v["start"], "end": v["end"], "callouts": v["callouts"]} for k, v in runs.items()}}
    os.makedirs(os.path.dirname(SCORE), exist_ok=True)
    with open(SCORE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for r in rows:
        mark = {True: "hit ", False: "MISS", None: "----"}[r["hit"]]
        got = "; ".join(f"{c['rule']} {c['day']} {c['a'][1]}" + (f" / {c['b'][1]}" if c.get("b") else "") +
                        (f" {c['min_km']} km" if "min_km" in c else f" {c['km']} km" if "km" in c else "") for c in r["found"][:2])
        print(f"{mark} {r['case']:4} {r['rule']} {r['outcome']:6} {r['ids']} {r['window'][0]}..{r['window'][1]}  {got}")
    for rule, d in decide.items():
        print(rule, d)
    return out


# ---------------------------------------------------------------- the globe's file
# Scores of v1 (docs/validation/geo-callouts.md, Results, 1 Nov 2026) and the default each earned by the frozen criteria.
RULES = {
    "C1": ("Close to another owner's satellite", False, "found 10 of 12 published cases, but about 160 new a week"),
    "C2": ("Approaching", False, "found 1 of 4 published cases; about 500 new a week"),
    "C3": ("Parked beside another owner", True, "found 4 of 5 published cases; about 2 a week"),
    "C4": ("Heading for an occupied slot", True, "found 2 of 4 published cases; about 1 a week"),
    "C5": ("Listed-role object changed orbit", True, "found 5 of 6 published cases; about 3 a week"),
    "C6": ("Arrived in the protected zone", True, "found 4 of 4 published cases; about 1 a week"),
    "C7": ("Retired to the graveyard", True, "found 3 of 4 published cases; under 1 a week"),
    "C8": ("Went quiet", False, "missed its one published case; about 1 a week"),
}


def publish(data, days, out, show_days=14):
    """The last `show_days` of callouts (computed over `days`, so the look-back rules have history) for the globe."""
    end = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    start = end - timedelta(days=days - 1)
    first_shown = (end - timedelta(days=show_days - 1)).isoformat()
    doc = run(load_elements(data), load_static(data), load_roles(), start.isoformat(), end.isoformat(),
              events=load_events(data, start.isoformat(), end.isoformat()))
    keep = []
    for c in doc["callouts"]:
        if c["day"] < first_shown and not (c["rule"] == "C1" and c.get("end", c["day"]) >= first_shown):
            continue
        k = {"r": c["rule"], "d": c["day"], "a": c["a"]}
        for f in ("b", "end", "min_km", "km", "from_km", "deg", "days", "drift", "lon", "role", "kind", "between",
                  "drift_change", "inc_change", "lon_off_deg", "standing"):
            if f in c and c[f] is not None and c[f] is not False:      # keep zeros (0 == False in Python)
                k[f] = c[f]
        keep.append(k)
    pub = {"version": VERSION, "built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "start": first_shown,
           "end": end.isoformat(), "source": CITE, "rules_doc": "docs/validation/geo-callouts.md",
           "rules": [{"id": r, "name": n, "default_on": on, "score": sc} for r, (n, on, sc) in RULES.items()], "callouts": keep}
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(pub, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{out}: {len(keep)} callouts, {first_shown} to {end}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pull", help="fetch the history each pre-history case needs (Space-Track, once)")
    pb = sub.add_parser("publish", help="the globe's file: the last two weeks of callouts")
    pb.add_argument("--data", default=DATA)
    pb.add_argument("--days", type=int, default=21)
    pb.add_argument("--out", default=os.path.join(ROOT, "site", "data", "geo", "callouts.json"))
    sc = sub.add_parser("score", help="score the held run and the case runs against docs/validation/geo-callouts-cases.json")
    sc.add_argument("--held", default=OUT)
    r = sub.add_parser("run")
    r.add_argument("--data", default=DATA)
    r.add_argument("--start", default="2026-07-08")
    r.add_argument("--end")
    r.add_argument("--out", default=OUT)
    c = sub.add_parser("case")
    c.add_argument("--elements", required=True)
    c.add_argument("--ids", required=True)
    c.add_argument("--start", required=True)
    c.add_argument("--end", required=True)
    c.add_argument("--owners", default="", help="norad=OWNER,... for objects missing from the held catalogue")
    c.add_argument("--out")
    a = ap.parse_args()
    if a.cmd == "pull":
        pull(json.load(open(CASES, encoding="utf-8"))["cases"])
        return 0
    if a.cmd == "score":
        score(a.held)
        return 0
    if a.cmd == "publish":
        publish(a.data, a.days, a.out)
        return 0
    roles = load_roles()
    if a.cmd == "run":
        el = load_elements(a.data)
        static = load_static(a.data)
        end = a.end or (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        doc = run(el, static, roles, a.start, end, events=load_events(a.data, a.start, end))
        out = a.out
    else:
        ids = [int(x) for x in a.ids.split(",")]
        el = load_history_json(a.elements, set(ids))
        owners = dict((int(p.split("=")[0]), p.split("=")[1]) for p in a.owners.split(",") if "=" in p)
        static = load_static(DATA)
        doc = run(el, static, roles, a.start, a.end, ids=ids, owners=owners)
        out = a.out or os.path.join(ROOT, "data", "geo", "callouts", f"case-{a.start}-{'-'.join(map(str, ids))}.json")
    doc["weekly"] = weekly(doc)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    counts = {}
    for x in doc["callouts"]:
        counts[x["rule"]] = counts.get(x["rule"], 0) + 1
    print(f"{out}: {len(doc['callouts'])} callouts over {doc['start']} to {doc['end']}, {doc['objects']} objects; by rule {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
