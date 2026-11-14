#!/usr/bin/env python3
"""spoof_compare.py: compare tools/spoof_day.py episodes with an outside list of spoofed flights, for one spoofed-to place.

Validation only (docs/validation/spoofing-lima.md). The outside list is read from local day files and never copied:
GeoJSON FeatureCollections, one per UTC day, named spoof_<YYYY-MM-DD>.json, whose features carry icao24, segment
(e.g. "before-during-after"), timestamp_during_min / _max, and one coordinate per segment (a Point when the segment is
"during" alone). The "during" coordinate is where the receiver was shown.

  python tools/spoof_compare.py score 2026-11-07:2026-11-12 --outside DIR --events data/spoofing_nov \
      --at -12.043,-77.050 [--km 100] [--raw-root data/raw/trace_box] [--json out.json]

For each outside flight shown within --km of --at: matched if spoof_day has an episode for the same ICAO address whose
spoofed-to point (false_lat, false_lon) is within --km of --at and whose time overlaps the outside "during" window
widened by --slack-min minutes on each side (default 30). Events of the day before and after are searched too, where
present. With --raw-root, each unmatched flight is explained from the raw adsb.lol trace: whether the archive holds
ADS-B positions near the place in the window, only MLAT positions, or nothing, and if positions are there, which test
let them through. Prints per-day counts; the per-flight table holds ICAO addresses and stays local (--json).
"""
import argparse
import gzip
import io
import json
import math
import os
import sys
import tarfile
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))


def km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 12742.0 * math.asin(min(1.0, math.sqrt(a)))


def iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def days_of(spec):
    out = []
    for part in spec:
        a, _, b = part.partition(":")
        d, e = date.fromisoformat(a), date.fromisoformat(b or a)
        while d <= e:
            out.append(d.isoformat()); d += timedelta(days=1)
    return out


def outside_flights(path, at, radius):
    """Features of one outside day file shown within radius km of at: [{icao, t0, t1, segment, km, during}]."""
    with open(path, encoding="utf-8") as f:
        fc = json.load(f)
    out = []
    for ft in fc.get("features", []):
        p, g = ft.get("properties") or {}, ft.get("geometry") or {}
        seg = (p.get("segment") or "").split("-")
        if "during" not in seg or not p.get("icao24") or not p.get("timestamp_during_min"):
            continue
        co = g.get("coordinates") or []
        co = [co] if g.get("type") == "Point" else co
        if len(co) != len(seg):
            continue
        lon, lat = co[seg.index("during")][:2]
        d = km(lat, lon, *at)
        if d <= radius:
            out.append({"icao": p["icao24"].lower(), "t0": iso(p["timestamp_during_min"]),
                        "t1": iso(p.get("timestamp_during_max") or p["timestamp_during_min"]), "segment": p.get("segment"),
                        "km": round(d, 2)})
    return out


def load_events(events_dir, day):
    p = os.path.join(events_dir, f"{day}.events.json.gz")
    if not os.path.exists(p):
        return None
    with gzip.open(p, "rt", encoding="utf-8") as f:
        ev = json.load(f)
    return ev.get("events", ev) if isinstance(ev, dict) else ev


def explain(trace, fl, at, radius, airspeed=True):
    """Why spoof_day didn't place an outside flight at the place, from the aircraft's raw trace."""
    import spoof_day as S
    base = float(trace.get("timestamp") or 0)
    lo_t, hi_t = fl["t0"] - 300, fl["t1"] + 300
    win = [p for p in trace.get("trace", []) if lo_t <= base + p[0] <= hi_t]
    if not win:
        return "no positions in the window", ""
    near = [p for p in win if p[1] is not None and km(p[1], p[2], *at) <= radius]
    if not near:
        srcs = sorted({str(p[9]) if len(p) > 9 else "?" for p in win})
        return "no position near the place in the window", "sources in the window: " + ", ".join(srcs)
    if not any(len(p) > 9 and p[9] == "adsb_icao" for p in near):
        return "positions near the place, none ADS-B", ""
    A, M, cat = S.parse_trace(trace)
    r = S.analyse(A, M, cat, airspeed)
    idx = [i for i, p in enumerate(A) if lo_t <= p[S.T] <= hi_t and km(p[S.LAT], p[S.LON], *at) <= radius]
    if not idx:
        return "ADS-B positions near the place, below 1,000 ft or on the ground", ""
    if not r["fast"]:
        return "ADS-B positions near the place, aircraft not tested", "not fast"
    if any(r["false"][i] for i in idx):
        return "ADS-B positions near the place, flagged but placed elsewhere or too short", ""
    span = A[idx[-1]][S.T] - A[idx[0]][S.T]
    gs = sorted(A[i][S.GS] for i in idx if A[i][S.GS] is not None)
    why = [f"{len(idx)} ADS-B positions over {round(span)} s, ground speed {gs[0]:.0f}-{gs[-1]:.0f} kt" if gs else
           f"{len(idx)} ADS-B positions over {round(span)} s"]
    if gs and gs[0] >= S.SLOW_KT:
        why.append(f"not slow (>= {S.SLOW_KT} kt)")
    if span < S.LOITER_S:
        why.append(f"too short for loiter (< {S.LOITER_S} s)")
    if r["dup"]:
        why.append(f"duplicate-address rule: {r['far']} jumps over {S.FAR_KM:.0f} km, so no excursion test")
    elif r["far"]:
        why.append("one-way far jump (unresolved), so no excursion")
    return "ADS-B positions near the place, not flagged", "; ".join(why)


def traces_for(raw_root, day, icaos):
    """{icao: trace dict} for the given addresses, streamed from one day's archive."""
    import pnt_daily as P
    raw = os.path.join(raw_root, day)
    if not icaos or not os.path.isdir(raw):
        return {}
    out = {}
    stream = io.BufferedReader(P.Chain(P.day_parts(raw, day)), buffer_size=8 << 20)
    with tarfile.open(fileobj=stream, mode="r|") as tf:
        for m in tf:
            if m.isfile() and "trace_full_" in m.name:
                ic = m.name.rsplit("trace_full_", 1)[1].split(".")[0].lower()
                if ic in icaos:
                    b = tf.extractfile(m).read()
                    out[ic] = json.loads(gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b)
    return out


def score(days, outside_dir, events_dir, at, radius, slack_min=30, raw_root=None):
    per_day, flights = [], []
    cache = {}

    def ev(d):
        if d not in cache:
            cache[d] = load_events(events_dir, d)
        return cache[d]

    for day in days:
        p = os.path.join(outside_dir, f"spoof_{day}.json")
        if not os.path.exists(p):
            per_day.append({"day": day, "status": "no outside file"}); continue
        if ev(day) is None:
            per_day.append({"day": day, "status": "no spoof_day events"}); continue
        d0 = date.fromisoformat(day)
        pool = [e for k in (-1, 0, 1) for e in (ev((d0 + timedelta(days=k)).isoformat()) or [])]
        nf_here = {}
        for e in pool:
            if e.get("false_lat") is not None and km(e["false_lat"], e["false_lon"], *at) <= radius:
                nf_here.setdefault(e["icao"].lower(), []).append(e)
        fl = outside_flights(p, at, radius)
        for f in fl:
            lo_t, hi_t = f["t0"] - slack_min * 60, f["t1"] + slack_min * 60
            f["day"] = day
            f["matched"] = any(iso(e["start"]) <= hi_t and iso(e["end"]) >= lo_t for e in nf_here.get(f["icao"], []))
            f["nf_any_episode"] = any(e["icao"].lower() == f["icao"] and iso(e["start"]) <= hi_t and iso(e["end"]) >= lo_t
                                      for e in pool)
        if raw_root:
            need = {f["icao"] for f in fl if not f["matched"]}
            tr = traces_for(raw_root, day, need)
            for f in fl:
                if not f["matched"]:
                    f["why"], f["detail"] = (explain(tr[f["icao"]], f, at, radius) if f["icao"] in tr
                                             else ("aircraft not in the archive", ""))
        own_day = {i for i, es in nf_here.items() if any(e["start"][:10] == day for e in es)}
        per_day.append({"day": day, "outside_flights": len(fl), "outside_aircraft": len({f["icao"] for f in fl}),
                        "matched": sum(f["matched"] for f in fl),
                        "noisefloor_aircraft_here": len(own_day),
                        "noisefloor_only": len(own_day - {f["icao"] for f in fl})})
        flights += fl
    return per_day, flights


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["score"])
    ap.add_argument("days", nargs="+")
    ap.add_argument("--outside", required=True, help="folder of the outside day files (read only)")
    ap.add_argument("--events", required=True, help="spoof_day output folder (<day>.events.json.gz)")
    ap.add_argument("--at", required=True, help="lat,lon of the spoofed-to place")
    ap.add_argument("--km", type=float, default=100.0)
    ap.add_argument("--slack-min", type=float, default=30.0)
    ap.add_argument("--raw-root", help="folder holding <day>/ adsb.lol archive parts, to explain misses")
    ap.add_argument("--json", help="write the per-flight table here (holds ICAO addresses: keep it local)")
    a = ap.parse_args()
    at = tuple(float(x) for x in a.at.split(","))
    per_day, flights = score(days_of(a.days), a.outside, a.events, at, a.km, a.slack_min, a.raw_root)
    for r in per_day:
        print(json.dumps(r))
    n, m = sum(r.get("outside_flights", 0) for r in per_day), sum(r.get("matched", 0) for r in per_day)
    print(json.dumps({"outside_flights": n, "matched": m, "share": round(m / n, 3) if n else None,
                      "days_with_a_match": sum(1 for r in per_day if r.get("matched"))}))
    if a.raw_root:
        from collections import Counter
        for why, k in Counter(f.get("why", "matched") for f in flights).most_common():
            print(f"{k:4d}  {why}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"per_day": per_day, "flights": flights}, f, indent=1)


if __name__ == "__main__":
    main()
