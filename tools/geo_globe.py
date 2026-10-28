#!/usr/bin/env python3
"""geo_globe.py: the data files behind the GEO globe on /geo: every object near GEO with its latest elements, and the
observed tracks of the last 1, 7, 30 and 90 days.

  python tools/geo_globe.py build RELEASE_DIR [SITE]    # -> SITE/data/geo/globe.json and SITE/data/geo/tracks-<N>d.json

Inputs (the pnt-data releases, fetched at deploy): the newest <day>.geo-region.json that carries objects
(tools/geo_region.py), the newest <day>.geo.json (CelesTrak's active list, tools/geo.py) and the monthly
geo-elements-YYYY-MM.parquet files (every element set held).

Tracks: each element set is propagated with SGP4 (the sgp4 library, MIT; WGS72, as satellite.js in the browser) only
until the next one is published, so a track is what the published elements said at each time, manoeuvres included.
Positions are Earth-fixed (TEME rotated by Greenwich mean sidereal time; polar motion ignored) and good to tens of
kilometres at GEO. Each track is [first sample, lon, lat, dalt, then the change from the sample before for each of
the three]; lon and lat in hundredths of a degree, dalt in km from the GEO altitude (35,786 km).
"""
import glob
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOWS = {1: 15, 7: 60, 30: 240, 90: 720}       # days shown: minutes between samples
GEO_ALT, RE = 35786.0, 6378.137
OBJ_COLS = ["norad", "name", "cospar", "type", "owner", "launch", "rcs", "region", "active", "epoch", "n", "e", "i", "raan",
            "argp", "M", "bstar"]
CITE = "Orbital data: USSPACECOM (space-track.org)"


def newest(paths, test=lambda d: True):
    for p in sorted(paths, reverse=True):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        if test(d):
            return d
    return None


def satrec(r):
    from sgp4.api import WGS72, Satrec
    s = Satrec()
    ep = datetime.fromisoformat(r["epoch"][:26])
    days = (ep - datetime(1949, 12, 31)).total_seconds() / 86400.0
    s.sgp4init(WGS72, "i", 0, days, r.get("bstar") or 0.0, 0.0, 0.0, r["e"], math.radians(r["argp"]), math.radians(r["i"]),
               math.radians(r["M"]), r["n"] * 2 * math.pi / 1440.0, math.radians(r["raan"]))
    return s


def earth_fixed(s, t):
    """(lon deg, lat deg, km from GEO altitude) of a Satrec at a UTC datetime, or None if SGP4 fails."""
    from sgp4.api import jday
    from sgp4.propagation import gstime
    jd, fr = jday(t.year, t.month, t.day, t.hour, t.minute, t.second + t.microsecond / 1e6)
    err, r, _ = s.sgp4(jd, fr)
    if err:
        return None
    g = gstime(jd + fr)
    x, y = r[0] * math.cos(g) + r[1] * math.sin(g), -r[0] * math.sin(g) + r[1] * math.cos(g)
    return (math.degrees(math.atan2(y, x)), math.degrees(math.atan2(r[2], math.hypot(x, y))),
            math.sqrt(x * x + y * y + r[2] * r[2]) - RE - GEO_ALT)


def encode(start, samples):
    """[start, lon, lat, dalt, then deltas]: integers (0.01 deg, km); longitude steps wrapped to the short way round."""
    out, prev = [start], None
    for lon, lat, dalt in samples:
        q = (round(lon * 100), round(lat * 100), round(dalt))
        if prev is None:
            out += list(q)
        else:
            dl = (q[0] - prev[0] + 18000) % 36000 - 18000
            out += [dl, q[1] - prev[1], q[2] - prev[2]]
        prev = q
    return out


def decode(track):
    """The inverse of encode (for tests): (start, [(lon, lat, dalt), ...])."""
    start, vals, out = track[0], track[1:], []
    lon = lat = dalt = None
    for k in range(0, len(vals), 3):
        if lon is None:
            lon, lat, dalt = vals[k:k + 3]
        else:
            lon, lat, dalt = (lon + vals[k] + 18000) % 36000 - 18000, lat + vals[k + 1], dalt + vals[k + 2]
        out.append((lon / 100, lat / 100, dalt))
    return start, out


def read_elsets(release, since):
    """{norad: [element sets sorted by epoch]} from the monthly files that can hold sets newer than `since` - 45 days."""
    import pyarrow.parquet as pq
    first = (since - timedelta(days=45)).strftime("%Y-%m")
    by = {}
    for p in sorted(glob.glob(os.path.join(release, "geo-elements-*.parquet"))):
        if os.path.basename(p)[13:20] < first:
            continue
        t = pq.read_table(p, columns=["norad", "epoch", "n", "e", "i", "raan", "argp", "M", "bstar"]).to_pydict()
        for k in range(len(t["norad"])):
            by.setdefault(t["norad"][k], []).append({c: t[c][k] for c in t})
    for v in by.values():
        v.sort(key=lambda r: r["epoch"])
    return by


def tracks(elsets, norads, end, days, step):
    """Observed tracks over `days` ending at `end`, one sample every `step` minutes."""
    n = days * 1440 // step
    times = [end - timedelta(minutes=step * (n - k)) for k in range(n + 1)]
    iso = [t.strftime("%Y-%m-%dT%H:%M:%S") for t in times]
    out = {}
    for norad in norads:
        sets = elsets.get(norad)
        if not sets:
            continue
        at, cache, start, samples = -1, {}, None, []
        for k, t in enumerate(times):
            while at + 1 < len(sets) and sets[at + 1]["epoch"][:19] <= iso[k]:
                at += 1
            if at < 0:
                continue                           # no element set yet at this time
            if at not in cache:
                cache = {at: satrec(sets[at])}     # one at a time: the sets only move forward
            p = earth_fixed(cache[at], t)
            if p is None:
                if start is not None:
                    break                          # stop the track at a failure rather than leave a gap
                continue
            if start is None:
                start = k
            samples.append(p)
        if samples:
            out[str(norad)] = encode(start, samples)
    return {"start_utc": times[0].strftime("%Y-%m-%dT%H:%MZ"), "step_min": step, "samples": n + 1, "tracks": out}


def build(release, site, now=None):
    now = (now or datetime.now(timezone.utc)).replace(tzinfo=None, second=0, microsecond=0)
    region = newest(glob.glob(os.path.join(release, "*.geo-region.json")), lambda d: "objects" in d)
    if not region:
        raise SystemExit("no geo-region file with objects (tools/geo_region.py pull runs first)")
    snap = newest(glob.glob(os.path.join(release, "*.geo.json")))
    active = {int(o["id"]) for o in (snap or {}).get("objects", [])}
    cols = region["object_cols"]
    objs = []
    for row in region["objects"]:
        o = dict(zip(cols, row))
        objs.append([o["norad"], o["name"], o["cospar"], o["type"], o["owner"], o["launch"], o["rcs"], o["region"],
                     1 if o["norad"] in active else 0, o["epoch"][:19], round(o["n"], 8), round(o["e"], 7), round(o["i"], 4),
                     round(o["raan"], 4), round(o["argp"], 4), round(o["M"], 4), o.get("bstar") or 0.0])
    out_dir = os.path.join(site, "data", "geo")
    os.makedirs(out_dir, exist_ok=True)
    meta = {}
    end = now.replace(minute=now.minute - now.minute % 15)
    elsets = read_elsets(release, end - timedelta(days=max(WINDOWS)))
    norads = [o[0] for o in objs]
    for days, step in WINDOWS.items():
        e = end.replace(minute=0) - timedelta(hours=end.hour % (step // 60)) if step >= 60 else end
        tr = tracks(elsets, norads, e, days, step)
        name = f"tracks-{days}d.json"
        with open(os.path.join(out_dir, name), "w", encoding="utf-8", newline="\n") as f:
            json.dump(tr, f, separators=(",", ":"))
        meta[str(days)] = {"file": name, "start_utc": tr["start_utc"], "step_min": step, "samples": tr["samples"],
                           "objects": len(tr["tracks"])}
    owners = {}
    try:
        with open(os.path.join(ROOT, "site_src", "satcat_owners.json"), encoding="utf-8") as f:
            names = json.load(f)["codes"]
        owners = {o[4]: names[o[4]] for o in objs if o[4] in names}
    except (OSError, ValueError, KeyError):
        pass
    doc = {"built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "region_day": region["day"], "owners": owners,
           "elements_fetched_utc": region.get("fetched_utc"), "active_from": (snap or {}).get("day"), "source": CITE,
           "definitions": region.get("definitions"), "cols": OBJ_COLS, "objects": objs, "tracks": meta}
    with open(os.path.join(out_dir, "globe.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, separators=(",", ":"), ensure_ascii=False)
    return doc


def main():
    if len(sys.argv) < 3 or sys.argv[1] != "build":
        raise SystemExit(__doc__)
    site = sys.argv[3] if len(sys.argv) > 3 else os.path.join(ROOT, "site")
    d = build(sys.argv[2], site)
    sizes = {k: os.path.getsize(os.path.join(site, "data", "geo", v["file"])) // 1024 for k, v in d["tracks"].items()}
    print(f"geo globe: {len(d['objects'])} objects; tracks KB by window (days): {sizes}")


if __name__ == "__main__":
    main()
