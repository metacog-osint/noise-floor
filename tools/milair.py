#!/usr/bin/env python3
"""milair.py: military aircraft seen on ADS-B and MLAT, by role and region, against each region's own usual level.

A measurement, never an alert. Every count is a LOWER BOUND: military aircraft often fly with ADS-B off, many send
Mode S with no position, and adsb.lol's receivers cover some regions thinly or not at all. A count that rises can
mean more aircraft, or the same aircraft transmitting more; a count that falls can mean fewer, or more of them dark.

  python tools/milair.py day 2026-09-22 --raw DIR [--out data/milair]   one archive day -> <day>.milair.json
  python tools/milair.py read DAY --days DIR [--json]                    the day's reading against its baseline
  python tools/milair.py site RELEASE_DIR SITE                           site/data/milair/reading.json (deploy)
  python tools/milair.py live FILE.json                                  counts from a saved /v2/mil snapshot (probe)

Method v1.0 (docs/validation/milair.md):
  * Input: the adsb.lol daily archive (globe_history, ODbL), one trace file per aircraft, streamed without unpacking.
  * Military: adsb.lol's own database flag (dbFlags bit 1) OR the ICAO address in the committed plane-alert-db
    snapshot (registry/plane_alert_mil.csv, ODbL). Which one said so is counted (`via`).
  * Role: from the ICAO type code (registry/mil_roles.csv), deterministic; for airframes shared by several roles
    (A330 MRTT and A330, KC-130J and C-130J, E-8C and 707) a type-name rule in the same file decides, read from the
    plane-alert-db type name, else the archive's own description. No model or LLM assigns roles. Headline roles:
    tanker, isr (ISR, airborne early warning, maritime patrol, SIGINT, large drones), transport, bomber, fighter
    (fighter and attack). Also counted: trainer, rotary, other (a military type not in the table), unknown (no type).
  * Positions: airborne (not "ground"), not stale, from ADS-B, MLAT, TIS-B, ADS-R or ADS-C. An aircraft is counted
    in a region-hour if it has any such position inside the region's boxes (tools/milair_regions.json, Watchfloor's
    zone boxes) in that UTC hour. MLAT-only: all its positions there that hour came from multilateration, which
    places aircraft that send no position of their own; they are counted and flagged (`mlat_only`).
  * Measures per region and role: aircraft-hours (sum over the 24 hours of distinct aircraft per hour) and distinct
    aircraft over the day. No aircraft identifiers leave the day scan.
  * Baseline: the same UTC hours on the same kind of day (workday or weekend) over the 28 days before: the median of
    those days' aircraft-hours summed over the hours the day covers (all 24 for a complete day; not per-hour medians
    summed, which read near zero where aircraft are sparse), from at least 12 of the workdays or 5 of the weekend
    days; the distinct-aircraft median over the
    same days; and the 7-day mean of distinct aircraft (Bellingcat Turnstone's weekly per-day average). Military
    flying drops by about two thirds worldwide at weekends, so a plain 28-day median would read every weekend as
    "below". Each region names its weekend (tools/milair_regions.json): Friday-Saturday for the Gulf, Red Sea and
    Levant regions, Saturday-Sunday elsewhere (measured on 20 Oct - 17 Nov 2026, docs/validation/milair.md).
  * Level (descriptive, pre-set, not tuned): ratio = aircraft-hours / max(baseline aircraft-hours, 1).
      above: ratio >= 2 and distinct aircraft >= the role's floor; banded 2x, 3x, 4x (World Monitor's surge rule)
      below: ratio <= 0.5 and the usual distinct aircraft >= the floor (World Monitor's stand-down)
      near: anything else; building: fewer baseline days than the minimum.
    Floors (distinct aircraft): transport 5, fighter 4, tanker 3, isr 3, bomber 2, all military 5.
  Feed items stay at tier routine whatever the level (Tom's rule: no tier above routine without his yes).
"""
import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import re
import statistics
import sys
import tarfile
import time
import urllib.request
import zlib
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

try:
    import orjson
    _loads = orjson.loads
except ImportError:                       # the deploy job runs without orjson; only `day` reads traces
    _loads = json.loads

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROLES_CSV = os.path.join(ROOT, "registry", "mil_roles.csv")
PLANE_ALERT_CSV = os.path.join(ROOT, "registry", "plane_alert_mil.csv")
REGIONS_JSON = os.path.join(ROOT, "tools", "milair_regions.json")

FORMAT = "noisefloor-milair/1"
METHOD = "milair-1.0"
HEADLINE = ("tanker", "isr", "transport", "bomber", "fighter")
ROLES = HEADLINE + ("trainer", "rotary", "other", "unknown")
ALL = "all"
WORLD = "world"
BASE_WINDOW = 28
HOURS = range(24)
MIN_BASE_DAYS = {"workday": 12, "weekend": 5}      # of the 20 workdays and 8 weekend days in 28
WEEKEND = (5, 6)                                  # Saturday, Sunday (date.weekday()); regions may name their own
FLOORS = {"transport": 5, "fighter": 4, "tanker": 3, "isr": 3, "bomber": 2, ALL: 5}
ABOVE, BELOW = 2.0, 0.5
BANDS = (4, 3, 2)
ADSB, MLAT, OTHER = 1, 2, 4               # position source bits per aircraft and region-hour
ROLE_WORDS = {"tanker": "tankers", "isr": "ISR", "transport": "transports", "bomber": "bombers", "fighter": "fighters"}
LOWER_BOUND = ("A lower bound: military aircraft often fly with ADS-B off or send no position, and receiver "
               "coverage is uneven, so aircraft that were there but not heard are not counted.")
ATTRIBUTION = ("Aircraft data: adsb.lol contributors (ODbL 1.0). Military addresses: plane-alert-db, SDR-Enthusiasts "
               "and contributors (ODbL 1.0).")


# ---------------------------------------------------------------- tables

def load_roles(path=ROLES_CSV):
    """{TYPE: (default role, [(role, compiled name pattern), ...])} from registry/mil_roles.csv."""
    out = {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            rules = []
            for part in filter(None, (r.get("split") or "").split(";")):
                role, pat = part.split("=", 1)
                if role not in ROLES:
                    raise ValueError(f"mil_roles.csv {r['type']}: unknown role {role!r}")
                rules.append((role, re.compile(pat, re.I)))
            if r["role"] not in ROLES:
                raise ValueError(f"mil_roles.csv {r['type']}: unknown role {r['role']!r}")
            t = r["type"].strip().upper()
            if t in out:
                raise ValueError(f"mil_roles.csv: {t} is listed twice")
            out[t] = (r["role"], rules)
    return out


def load_plane_alert(path=PLANE_ALERT_CSV):
    """{hex: (icao_type, type name)} from the committed plane-alert-db snapshot."""
    with open(path, encoding="utf-8", newline="") as f:
        return {r["icao"]: (r["icao_type"].strip().upper(), r["type"].strip()) for r in csv.DictReader(f)}


def load_regions(path=REGIONS_JSON):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["regions"]


def role_of(type_code, name, roles):
    """Role from the ICAO type code; a type-name rule decides for shared airframes. No type -> unknown; a type not in
    the table -> other."""
    t = (type_code or "").strip().upper()
    if not t:
        return "unknown"
    if t not in roles:
        return "other"
    default, rules = roles[t]
    for role, pat in rules:
        if name and pat.search(name):
            return role
    return default


def region_of(lat, lon, regions):
    """Index of the region whose boxes hold the point (west <= lon < east, south <= lat < north), or None."""
    for i, r in enumerate(regions):
        for w, s, e, n in r["boxes"]:
            if w <= lon < e and s <= lat < n:
                return i
    return None


def source_bit(src):
    if not src:
        return 0
    if src == "mlat":
        return MLAT
    if src.startswith("adsb"):
        return ADSB
    if src.startswith(("tisb", "adsr", "adsc")):
        return OTHER
    return 0                               # mode_s, other, unknown: no usable position


# ---------------------------------------------------------------- one trace

def scan(d, day0, regions, roles, pa):
    """One decoded trace file -> aircraft record, or None if not military or not usable.

    Record: {"role", "type", "via": "both"|"adsblol"|"plane-alert", "cells": {(region index or WORLD, hour): bits}}"""
    hx = (d.get("icao") or "").lower()
    if not hx or hx.startswith("~"):
        return None
    flagged, listed = bool((d.get("dbFlags") or 0) & 1), hx in pa
    if not (flagged or listed):
        return None
    t = (d.get("t") or "").strip().upper() or (pa[hx][0] if listed else "")
    name = (pa[hx][1] if listed else "") or d.get("desc") or ""
    role = role_of(t, name, roles)
    base = float(d.get("timestamp") or 0)
    cells = defaultdict(int)
    for p in d.get("trace") or []:
        if len(p) < 4 or p[3] == "ground" or p[3] is None:
            continue
        if len(p) > 6 and isinstance(p[6], int) and p[6] & 1:     # stale position
            continue
        bit = source_bit(p[9] if len(p) > 9 else None)
        if not bit:
            continue
        hour = int((base + p[0] - day0) // 3600)
        if not 0 <= hour < 24:
            continue
        cells[(WORLD, hour)] |= bit
        ri = region_of(p[1], p[2], regions)
        if ri is not None:
            cells[(ri, hour)] |= bit
    return {"role": role, "type": t, "via": "both" if flagged and listed else ("adsblol" if flagged else "plane-alert"),
            "cells": dict(cells)}


DBFLAGS = re.compile(rb'"dbFlags"\s*:\s*(\d+)')


def maybe_military(raw, hx, pa):
    """Cheap pre-filter before a full parse: the address is listed, or the file's header says dbFlags bit 1."""
    if hx in pa:
        return True
    head = zlib.decompressobj(31).decompress(raw, 2048) if raw[:2] == b"\x1f\x8b" else raw[:2048]
    m = DBFLAGS.search(head)
    return bool(m and int(m.group(1)) & 1)


# ---------------------------------------------------------------- one day

class Chain(io.RawIOBase):
    """Several byte streams (split archive parts) read as one, hashed on the way."""

    def __init__(self, openers):
        self.openers, self.cur, self.sha, self.bytes = list(openers), None, hashlib.sha256(), 0

    def readable(self):
        return True

    def readinto(self, b):
        while True:
            if self.cur is None:
                if not self.openers:
                    return 0
                self.cur = self.openers.pop(0)()
            n = self.cur.readinto(b)
            if n:
                self.sha.update(memoryview(b)[:n]); self.bytes += n
                return n
            self.cur.close(); self.cur = None


def local_parts(folder, day):
    tag = f"v{day.replace('-', '.')}-planes-readsb-prod-0"
    names = sorted(n for n in os.listdir(folder) if n.startswith(tag + ".tar"))
    return [os.path.join(folder, n) for n in names]


def url_opener(url):
    def op():
        return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "noise-floor"}), timeout=300)
    return op


def scan_stream(stream, day, regions=None, roles=None, pa=None):
    """Read one day's tar stream -> (records, stats)."""
    regions = regions if regions is not None else load_regions()
    roles = roles if roles is not None else load_roles()
    pa = pa if pa is not None else load_plane_alert()
    day0 = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    recs, st = [], Counter()
    with tarfile.open(fileobj=stream, mode="r|") as tf:
        for m in tf:
            if not (m.isfile() and "trace_full_" in m.name):
                continue
            st["traces"] += 1
            raw = tf.extractfile(m).read()
            hx = os.path.basename(m.name).split("trace_full_", 1)[1].split(".", 1)[0].lower()
            if not maybe_military(raw, hx, pa):
                continue
            try:
                d = _loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
            except Exception:
                st["parse_errors"] += 1
                continue
            r = scan(d, day0, regions, roles, pa)
            if r is None:
                continue
            st["military"] += 1
            recs.append(r)
    return recs, st


def aggregate(recs, regions):
    """Records -> per region (and world): hours, mlat-only hours, distinct and mlat-only distinct, per role and all."""
    ids = [r["id"] for r in regions] + [WORLD]
    keys = ROLES + (ALL,)
    out = {rid: {"hours": {k: [0] * 24 for k in keys}, "mlat_only_hours": {k: [0] * 24 for k in keys},
                 "distinct": {k: 0 for k in keys}, "mlat_only_distinct": {k: 0 for k in keys}} for rid in ids}
    for rec in recs:
        per = defaultdict(int)
        for (ri, hour), bits in rec["cells"].items():
            rid = WORLD if ri == WORLD else regions[ri]["id"]
            o = out[rid]
            for k in (rec["role"], ALL):
                o["hours"][k][hour] += 1
                o["mlat_only_hours"][k][hour] += bits == MLAT
            per[rid] |= bits
        for rid, bits in per.items():
            for k in (rec["role"], ALL):
                out[rid]["distinct"][k] += 1
                out[rid]["mlat_only_distinct"][k] += bits == MLAT
    return out


def day_doc(day, recs, st, source, regions):
    with_pos = sum(1 for r in recs if any(k[0] == WORLD for k in r["cells"]))
    unmapped = Counter(r["type"] for r in recs if r["role"] == "other")
    return {
        "format": FORMAT, "method_version": METHOD, "day": day,
        "made_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source, "regions_version": json.load(open(REGIONS_JSON, encoding="utf-8"))["version"],
        "counts": {"traces": st["traces"], "military": st["military"], "airborne_with_position": with_pos,
                   "parse_errors": st["parse_errors"], "via": dict(Counter(r["via"] for r in recs)),
                   "roles": dict(Counter(r["role"] for r in recs)),
                   "unmapped_types": dict(unmapped.most_common(25))},
        "regions": aggregate(recs, regions),
        "licence": "ODbL 1.0", "attribution": ATTRIBUTION, "lower_bound": LOWER_BOUND,
    }


def run_day(day, openers, source):
    regions = load_regions()
    t0 = time.time()
    stream = Chain(openers)
    recs, st = scan_stream(io.BufferedReader(stream, 8 << 20), day, regions)
    source = {**source, "bytes": stream.bytes, "sha256": stream.sha.hexdigest(), "seconds": round(time.time() - t0)}
    return day_doc(day, recs, st, source, regions)


# ---------------------------------------------------------------- reading

def _median(xs):
    return statistics.median(xs) if xs else 0


def day_type(day, weekend=WEEKEND):
    return "weekend" if date.fromisoformat(day).weekday() in tuple(weekend) else "workday"


def level(ratio, distinct, usual_distinct, base_days, role, min_days=MIN_BASE_DAYS["workday"]):
    floor = FLOORS.get(role, 3)
    if base_days < min_days:
        return "building", None
    if ratio >= ABOVE and distinct >= floor:
        return "above", next(b for b in BANDS if ratio >= b)
    if ratio <= BELOW and usual_distinct >= floor:
        return "below", None
    return "near", None


def reading(docs, day, window=BASE_WINDOW, regions=None):
    """docs: {day: day doc}. -> the day's reading per region and role against the same UTC hours on the same kind of
    day (workday or weekend, by the region's own weekend) over the `window` days before."""
    if day not in docs:
        raise KeyError(day)
    weekends = {r["id"]: tuple(r.get("weekend") or WEEKEND) for r in (regions if regions is not None else load_regions())}
    d0 = date.fromisoformat(day)
    before = [(d0 - timedelta(days=k)).isoformat() for k in range(1, window + 1)]
    week = [docs[x] for x in ((d0 - timedelta(days=k)).isoformat() for k in range(0, 7)) if x in docs]
    today = docs[day]
    out = {"day": day, "method_version": METHOD, "baseline_days": sum(x in docs for x in before), "window": window,
           "min_baseline_days": dict(MIN_BASE_DAYS), "regions": {}}
    for rid, reg in today["regions"].items():
        wk = weekends.get(rid, WEEKEND)
        kind = day_type(day, wk)
        hist = [docs[x]["regions"][rid] for x in before
                if x in docs and rid in docs[x]["regions"] and day_type(x, wk) == kind]
        roles = {}
        span = HOURS                       # the hours the day covers: all 24 for a complete archive day
        for k in HEADLINE + (ALL,):
            hrs = reg["hours"][k]
            ah = sum(hrs[i] for i in span)
            base = _median([sum(h["hours"][k][i] for i in span) for h in hist])
            dist = reg["distinct"][k]
            usual = _median([h["distinct"][k] for h in hist])
            ratio = ah / max(base, 1)
            lv, band = level(ratio, dist, usual, len(hist), k, MIN_BASE_DAYS[kind])
            busiest = max(range(24), key=lambda i: hrs[i]) if ah else None
            roles[k] = {"aircraft_hours": ah, "usual_aircraft_hours": round(base, 1), "ratio": round(ratio, 2),
                        "distinct": dist, "usual_distinct": usual,
                        "week_mean_distinct": round(statistics.mean(w["regions"][rid]["distinct"][k] for w in week
                                                                    if rid in w["regions"]), 1),
                        "mlat_only_share": round(sum(reg["mlat_only_hours"][k]) / ah, 3) if ah else None,
                        "busiest_hour": busiest, "level": lv, "band": band, "floor": FLOORS.get(k, 3)}
        roles["baseline"] = {"day_type": kind, "weekend": list(wk), "days": len(hist), "min_days": MIN_BASE_DAYS[kind]}
        out["regions"][rid] = roles
    return out


def load_days(folder):
    docs = {}
    for n in sorted(os.listdir(folder)):
        if n.endswith(".milair.json"):
            with open(os.path.join(folder, n), encoding="utf-8") as f:
                d = json.load(f)
            if d.get("format") == FORMAT:
                docs[d["day"]] = d
    return docs


def site(release_dir, site_dir):
    """Deploy step: the newest day's reading, the region boxes and a daily history -> SITE/data/milair/."""
    docs = load_days(release_dir)
    out = os.path.join(site_dir, "data", "milair")
    os.makedirs(out, exist_ok=True)
    if not docs:
        print("milair: no day files")
        return None
    newest = max(docs)
    regions = load_regions()
    r = reading(docs, newest, regions=regions)
    r["regions_meta"] = {x["id"]: {"name": x["name"], "boxes": x["boxes"], "watchfloor": x["watchfloor"]}
                         for x in regions}
    r["made_at"] = docs[newest].get("made_at")
    r["counts"] = docs[newest].get("counts")
    hist = {"days": sorted(docs), "regions": {}}
    for rid in r["regions"]:
        hist["regions"][rid] = {k: [docs[d]["regions"].get(rid, {}).get("distinct", {}).get(k) for d in hist["days"]]
                                for k in HEADLINE + (ALL,)}
    for name, doc in (("reading.json", r), ("history.json", hist)):
        with open(os.path.join(out, name), "w", encoding="utf-8", newline="\n") as f:
            json.dump(doc, f, separators=(",", ":"))
    print(f"milair: reading for {newest} from {r['baseline_days']} baseline days, {len(docs)} day files")
    return r


# ---------------------------------------------------------------- words (feed and site)

def plain_day(day):
    return datetime.strptime(day, "%Y-%m-%d").strftime("%d %b %Y").lstrip("0")


def level_words(x):
    if x["level"] == "building":
        return "no usual level yet"
    if x["level"] == "above":
        return f"at least {x['band']}x its usual level"
    if x["level"] == "below":
        return "under half its usual level"
    return "near its usual level"


def baseline_ok(rd):
    b = rd["baseline"]
    return b["days"] >= b["min_days"]


def region_sentence(name, rd, day):
    """One region's reading in plain words (feed summary)."""
    a, b = rd[ALL], rd["baseline"]
    ok = baseline_ok(rd)
    kind = "weekend days" if b["day_type"] == "weekend" else "workdays"
    wk = "Friday-Saturday" if tuple(b["weekend"]) == (4, 5) else "Saturday-Sunday"
    s = (f"Military aircraft seen over {name} on {plain_day(day)}: {a['distinct']:,} aircraft, "
         f"{a['aircraft_hours']:,} aircraft-hours")
    if ok:
        s += (f", against a usual {a['usual_aircraft_hours']:g} aircraft-hours for the same UTC hours on {kind} "
              f"(median of the {b['days']} {kind} in the 28 days before; the weekend here is {wk}): {level_words(a)}.")
    else:
        s += f". The usual level needs {b['min_days']} earlier {kind}; {b['days']} so far."
    parts = []
    for k in HEADLINE:
        x = rd[k]
        if x["distinct"] or x["usual_distinct"]:
            bit = f"{ROLE_WORDS[k]} {x['distinct']}"
            if ok and x["level"] in ("above", "below"):
                bit += f" ({level_words(x)})"
            parts.append(bit)
    if parts:
        s += " By role (aircraft): " + ", ".join(parts) + "."
    if a["mlat_only_share"]:
        s += f" {a['mlat_only_share'] * 100:.0f}% of aircraft-hours were placed by multilateration only."
    return s + " " + LOWER_BOUND


# ---------------------------------------------------------------- live probe

def live(path, regions=None, roles=None, pa=None):
    """Counts from a saved api.adsb.lol/v2/mil snapshot (a probe; the live API is not cleared for use yet)."""
    regions = regions if regions is not None else load_regions()
    roles = roles if roles is not None else load_roles()
    pa = pa if pa is not None else load_plane_alert()
    with open(path, encoding="utf-8") as f:
        ac = json.load(f).get("ac") or []
    out = {"aircraft": len(ac), "with_position": 0, "no_position": 0, "mlat": 0, "regions": Counter(), "roles": Counter()}
    for a in ac:
        hx = (a.get("hex") or "").lower()
        t = (a.get("t") or "").upper() or (pa.get(hx, ("", ""))[0])
        out["roles"][role_of(t, pa.get(hx, ("", ""))[1] or a.get("desc") or "", roles)] += 1
        if a.get("lat") is None or a.get("alt_baro") == "ground":
            out["no_position"] += a.get("lat") is None
            continue
        out["with_position"] += 1
        out["mlat"] += "lat" in (a.get("mlat") or [])
        ri = region_of(a["lat"], a["lon"], regions)
        if ri is not None:
            out["regions"][regions[ri]["id"]] += 1
    return {**out, "regions": dict(out["regions"]), "roles": dict(out["roles"])}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("day"); p.add_argument("day"); p.add_argument("--raw", required=True)
    p.add_argument("--out", default=os.path.join(ROOT, "data", "milair"))
    p = sub.add_parser("read"); p.add_argument("day"); p.add_argument("--days", required=True)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("site"); p.add_argument("release_dir"); p.add_argument("site_dir")
    p = sub.add_parser("live"); p.add_argument("file")
    a = ap.parse_args(argv)
    if a.cmd == "day":
        parts = local_parts(a.raw, a.day)
        if not parts:
            sys.exit(f"no archive parts for {a.day} in {a.raw}")
        doc = run_day(a.day, [lambda p=p: open(p, "rb", buffering=0) for p in parts],
                      {"archive": os.path.basename(parts[0]).split(".tar")[0], "parts": len(parts)})
        os.makedirs(a.out, exist_ok=True)
        path = os.path.join(a.out, f"{a.day}.milair.json")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(doc, f, separators=(",", ":"))
        print(json.dumps({"day": a.day, **doc["counts"], "seconds": doc["source"]["seconds"], "out": path}))
    elif a.cmd == "read":
        r = reading(load_days(a.days), a.day)
        if a.json:
            print(json.dumps(r, indent=1))
        else:
            names = {x["id"]: x["name"] for x in load_regions()}
            for rid, rd in r["regions"].items():
                if rid != WORLD:
                    print(region_sentence(names[rid], rd, a.day))
    elif a.cmd == "site":
        site(a.release_dir, a.site_dir)
    elif a.cmd == "live":
        print(json.dumps(live(a.file), indent=1))


if __name__ == "__main__":
    main()
