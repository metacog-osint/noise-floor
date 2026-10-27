#!/usr/bin/env python3
"""geo_region.py: every object in and near the geostationary region from Space-Track, where each one is, and which
arrived or left. Behaviour only, never intent.

  python tools/geo_region.py pull [--day D] [--out DIR] [--upload]        # one gp query: inventory, element sets, events
  python tools/geo_region.py backfill --since 2026-07-01 --events-from 2026-07-29 [--out DIR] [--upload]
                                                                          # gp_history once per object, then replay days
  python tools/geo_region.py replay --events-from 2026-07-29 [--out DIR] [--upload]  # the replay alone, from held files

Data: Space-Track, USSPACECOM basic SSA data (blanket approval to redistribute and to publish analysis, with citation:
"Orbital data: USSPACECOM (space-track.org)"). Account: SPACETRACK_USER and SPACETRACK_PASSWORD from the environment
or, on Windows, the user variables; never printed. API rules (space-track.org/documentation, read 27 Oct 2026): under
30 requests a minute and 300 an hour; the gp class at most once an hour, not at the top or bottom of the hour;
gp_history once per object over its lifetime, stored and never downloaded again (the backfill caches every chunk
before it moves on, and skips chunks it already holds).

Region (stated on the GEO page):
  near GEO    mean motion 0.9-1.1 rev/day and eccentricity under 0.3: what the daily query takes (not decayed)
  zone        perigee and apogee within GEO +-200 km (35,586-35,986 km altitude) and inclination 15 deg or less:
              the IADC geosynchronous protected region
  graveyard   perigee above the zone
  below       apogee below the zone
  crossing    inclination 15 deg or less, reaching into the zone's altitudes without staying inside them
  inclined    reaching the zone's altitudes with inclination over 15 deg (inclined geosynchronous orbits)
  edges       an object enters the zone only when 25 km (0.25 deg) inside its edges and leaves only when that far
              outside, so an orbit riding an edge doesn't flicker in and out
Events between consecutive days (each day's inventory is every object's latest element set by the end of that day):
  new         first seen near GEO, launched within the last year
  returned    first seen near GEO in our data, launched earlier (back after a gap in public elements)
  arrived     in the zone, and wasn't the day before
  left up     zone -> graveyard
  left down   zone -> below
  left        zone -> crossing or inclined
  quiet       a payload CelesTrak lists as active (the GEO board's snapshot), in the zone, whose latest elements
              passed 7 days old that day
  gone        near GEO the day before, not any more (decayed, moved away, or dropped from the public catalogue)
Files (on the pnt-data-YYYY-MM releases): geo-elements-YYYY-MM.parquet (every element set held from HISTORY_START,
by epoch month; an older latest set, such as a lost object's, stays only in the day file) and
<day>.geo-region.json (the day's regions, counts and events; a daily pull also carries the objects with their latest
elements).
"""
import argparse
import glob
import http.cookiejar
import json
import math
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "metacog-osint/noise-floor"
BASE = "https://www.space-track.org"
CITE = "Orbital data: USSPACECOM (space-track.org)"
UA = "noise-floor (github.com/metacog-osint/noise-floor)"
MU, RE = 398600.4418, 6378.137               # km^3/s^2, km
GEO_ALT, BAND, ZONE_INC = 35786.0, 200.0, 15.0
N_MIN, N_MAX, E_MAX = 0.9, 1.1, 0.3
QUIET_DAYS, NEW_LAUNCH_DAYS = 7, 365
EDGE_KM, EDGE_DEG = 25.0, 0.25               # hysteresis at the zone's edges
HISTORY_START = "2026-07-01"                 # the first epoch the monthly element files hold
CHUNK, PAUSE = 100, 13.0                     # gp_history: objects per request, seconds between requests (under 5 a minute)
ELSET = ["NORAD_CAT_ID", "EPOCH", "MEAN_MOTION", "ECCENTRICITY", "INCLINATION", "RA_OF_ASC_NODE", "ARG_OF_PERICENTER",
         "MEAN_ANOMALY", "BSTAR", "MEAN_MOTION_DOT", "MEAN_MOTION_DDOT", "ELEMENT_SET_NO", "REV_AT_EPOCH"]
COLS = ["norad", "epoch", "n", "e", "i", "raan", "argp", "M", "bstar", "ndot", "nddot", "elset", "rev"]
OBJ_COLS = ["norad", "name", "cospar", "type", "owner", "launch", "rcs", "region", "epoch", "n", "e", "i", "raan", "argp", "M",
            "bstar", "ndot", "nddot"]
REGIONS = ["zone", "graveyard", "crossing", "inclined", "below"]


# ---------------------------------------------------------------- geometry and regions
def altitudes(n, e):
    """Perigee and apogee altitude (km) from mean motion (rev/day) and eccentricity."""
    a = (MU / (n * 2 * math.pi / 86400.0) ** 2) ** (1 / 3)
    return a * (1 - e) - RE, a * (1 + e) - RE


def near_geo(n, e):
    return n is not None and e is not None and N_MIN <= n <= N_MAX and e < E_MAX


def region_of(n, e, i, prev=None):
    """The region of an orbit. `prev`, the object's region the day before, moves the zone's edges: inward by
    EDGE_KM/EDGE_DEG for an object outside, outward for one inside, so edge-riders don't flicker."""
    perigee, apogee = altitudes(n, e)
    m, md = (0.0, 0.0) if prev is None else (-EDGE_KM, -EDGE_DEG) if prev == "zone" else (EDGE_KM, EDGE_DEG)
    if perigee >= GEO_ALT - BAND + m and apogee <= GEO_ALT + BAND - m and i <= ZONE_INC - md:
        return "zone"
    if perigee > GEO_ALT + BAND:
        return "graveyard"
    if apogee < GEO_ALT - BAND:
        return "below"
    if i > ZONE_INC:
        return "inclined"
    return "crossing"


# ---------------------------------------------------------------- records
def num(x, kind=float):
    if x is None or x == "":
        return None
    try:
        return kind(x)
    except (TypeError, ValueError):
        return None


def elset_row(g):
    """A Space-Track GP/GP_history record (all strings) -> the stored element set."""
    return {"norad": num(g.get("NORAD_CAT_ID"), int), "epoch": g.get("EPOCH"), "n": num(g.get("MEAN_MOTION")),
            "e": num(g.get("ECCENTRICITY")), "i": num(g.get("INCLINATION")), "raan": num(g.get("RA_OF_ASC_NODE")),
            "argp": num(g.get("ARG_OF_PERICENTER")), "M": num(g.get("MEAN_ANOMALY")), "bstar": num(g.get("BSTAR")),
            "ndot": num(g.get("MEAN_MOTION_DOT")), "nddot": num(g.get("MEAN_MOTION_DDOT")),
            "elset": num(g.get("ELEMENT_SET_NO"), int), "rev": num(g.get("REV_AT_EPOCH"), int)}


def static_row(g):
    return {"norad": num(g.get("NORAD_CAT_ID"), int), "name": g.get("OBJECT_NAME"), "cospar": g.get("OBJECT_ID"),
            "type": g.get("OBJECT_TYPE"), "owner": g.get("COUNTRY_CODE"), "launch": g.get("LAUNCH_DATE"), "rcs": g.get("RCS_SIZE")}


def end_of(day):
    return (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")


def age_days(epoch, at):
    """Days from an element epoch to a time (ISO strings, UTC)."""
    e = datetime.fromisoformat(epoch[:19])
    t = datetime.fromisoformat(at[:19]) if "T" in at else datetime.strptime(at[:10], "%Y-%m-%d")
    return (t - e).total_seconds() / 86400.0


# ---------------------------------------------------------------- inventories and events
def from_latest(latest, prev=None):
    """{norad: {region, epoch}} from each object's latest element set, near-GEO sets only; `prev` sets the edges."""
    prev = prev or {}
    return {k: {"region": region_of(r["n"], r["e"], r["i"], (prev.get(k) or {}).get("region")), "epoch": r["epoch"][:19]}
            for k, r in latest.items() if near_geo(r["n"], r["e"])}


def inventory(elsets, day):
    """The inventory at the end of `day`: each object's latest element set before then."""
    cut, latest = end_of(day), {}
    for r in elsets:
        if r["epoch"] and r["epoch"] < cut:
            q = latest.get(r["norad"])
            if q is None or r["epoch"] > q["epoch"]:
                latest[r["norad"]] = r
    return from_latest(latest)


def events(prev, cur, day, static, seen=None, active=None):
    """Membership events between two inventories. `seen`: norads ever near GEO before (defaults to prev's).
    `active`: catalogue numbers listed as active (None: every payload counts for "quiet")."""
    seen = set(prev) if seen is None else seen
    end, out = end_of(day), []

    def ev(k, kind, rec, frm=None):
        s = static.get(k) or {}
        out.append({"day": day, "norad": k, "kind": kind, "name": s.get("name"), "owner": s.get("owner"), "type": s.get("type"),
                    "region": rec["region"], "from": frm, "epoch": rec["epoch"][:16]})
    for k, c in cur.items():
        p = prev.get(k)
        if p is None:
            if k not in seen:
                launch = (static.get(k) or {}).get("launch")
                recent = bool(launch) and age_days(launch + "T00:00:00", day) <= NEW_LAUNCH_DAYS
                ev(k, "new" if recent else "returned", c)
            if c["region"] == "zone":
                ev(k, "arrived", c, p and p["region"])
            continue
        if p["region"] != "zone" and c["region"] == "zone":
            ev(k, "arrived", c, p["region"])
        elif p["region"] == "zone" and c["region"] != "zone":
            ev(k, {"graveyard": "left up", "below": "left down"}.get(c["region"], "left"), c, p["region"])
        if (c["region"] == "zone" and (static.get(k) or {}).get("type") == "PAYLOAD" and (active is None or k in active)
                and age_days(c["epoch"], end) > QUIET_DAYS
                and age_days(p["epoch"], day) <= QUIET_DAYS):
            ev(k, "quiet", c, p["region"])
    for k, p in prev.items():
        if k not in cur:
            ev(k, "gone", p, p["region"])
    return out


def active_ids(day, geo_dir=os.path.join(ROOT, "data", "geo")):
    """Catalogue numbers in the GEO board's CelesTrak snapshot (its active list): the day's, else the newest held."""
    exact = os.path.join(geo_dir, f"{day}.geo.json")
    files = sorted(glob.glob(os.path.join(geo_dir, "*.geo.json")))
    path = exact if os.path.exists(exact) else (files[-1] if files else None)
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return {int(o["id"]) for o in json.load(f)["objects"]}
    except (ValueError, KeyError, OSError):
        return None


def counts(inv, static):
    c = {r: {} for r in REGIONS}
    for k, v in inv.items():
        t = (static.get(k) or {}).get("type") or "UNKNOWN"
        c[v["region"]][t] = c[v["region"]].get(t, 0) + 1
    return c


# ---------------------------------------------------------------- Space-Track
def credentials():
    user, pw = os.environ.get("SPACETRACK_USER"), os.environ.get("SPACETRACK_PASSWORD")
    if (not user or not pw) and sys.platform == "win32":
        import winreg                               # user variables set after this process started

        def get(k, name):
            try:
                return winreg.QueryValueEx(k, name)[0]
            except FileNotFoundError:
                return None
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            user, pw = user or get(k, "SPACETRACK_USER"), pw or get(k, "SPACETRACK_PASSWORD")
    if not user or not pw:
        raise SystemExit("SPACETRACK_USER / SPACETRACK_PASSWORD not set")
    return user, pw


class SpaceTrack:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.op.addheaders = [("User-Agent", UA)]
        self.requests = 0

    def __enter__(self):
        user, pw = credentials()
        body = urllib.parse.urlencode({"identity": user, "password": pw}).encode()
        with self.op.open(BASE + "/ajaxauth/login", body, timeout=60) as r:
            text = r.read().decode("utf-8", "replace")
        if r.status != 200 or "Failed" in text:
            raise SystemExit("Space-Track login failed (check the account; the password is not shown)")
        return self

    def __exit__(self, *exc):
        try:
            self.op.open(BASE + "/ajaxauth/logout", timeout=30).read()
        except OSError:
            pass

    def query(self, path):
        """GET /basicspacedata/query/<path>; stop on anything but a JSON list (the rules say to stop, not retry)."""
        self.requests += 1
        with self.op.open(BASE + "/basicspacedata/query/" + path, timeout=600) as r:
            if r.status != 200:
                raise SystemExit(f"Space-Track returned {r.status}; stopping")
            data = json.loads(r.read().decode("utf-8"))
        if not isinstance(data, list):
            raise SystemExit(f"Space-Track error: {str(data)[:300]}")
        return data


def gp_near_geo(out, st=None):
    """The gp query, at most once an hour: a response fetched in the last hour is reused from `out`/gp_latest.json."""
    p = os.path.join(out, "gp_latest.json")
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < 3600:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    if st is None:
        with SpaceTrack() as s:
            data = s.query(GP_NEAR_GEO)
    else:
        data = st.query(GP_NEAR_GEO)
    os.makedirs(out, exist_ok=True)
    with open(p + ".part", "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    os.replace(p + ".part", p)
    return data


GP_NEAR_GEO = ("class/gp/decay_date/null-val/MEAN_MOTION/{}--{}/ECCENTRICITY/%3C{}/orderby/NORAD_CAT_ID%20asc/format/json"
               .format(N_MIN, N_MAX, E_MAX))


def history_path(ids, since, until):
    return (f"class/gp_history/NORAD_CAT_ID/{','.join(str(i) for i in ids)}/EPOCH/{since}--{until}"
            f"/orderby/NORAD_CAT_ID%20asc,EPOCH%20asc/predicates/{','.join(ELSET)}/format/json")


# ---------------------------------------------------------------- files
def month_of(epoch):
    return epoch[:7]


def read_elements(path):
    import pyarrow.parquet as pq
    if not os.path.exists(path):
        return []
    t = pq.read_table(path).to_pydict()
    return [dict(zip(COLS, vals)) for vals in zip(*(t[c] for c in COLS))]


def write_elements(path, rows):
    import pyarrow as pa
    import pyarrow.parquet as pq
    rows = sorted({(r["norad"], r["epoch"]): r for r in rows}.values(), key=lambda r: (r["norad"], r["epoch"]))
    types = {"norad": pa.int64(), "epoch": pa.string(), "elset": pa.int64(), "rev": pa.int64()}
    tb = pa.table({c: pa.array([r.get(c) for r in rows], type=types.get(c, pa.float64())) for c in COLS})
    pq.write_table(tb, path + ".part", compression="zstd")
    os.replace(path + ".part", path)
    return len(rows)


def merge_elements(out, rows):
    """Add element sets to the monthly files in `out`; returns {month: rows in the file}."""
    by = {}
    for r in rows:
        if r["epoch"] >= HISTORY_START:
            by.setdefault(month_of(r["epoch"]), []).append(r)
    done = {}
    for m, new in sorted(by.items()):
        p = os.path.join(out, f"geo-elements-{m}.parquet")
        done[m] = write_elements(p, read_elements(p) + new)
    return done


def gh(*args):
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def tags_for(name):
    """The release for a file: its month's, else the month before (a new month's release exists from its second day)."""
    m = name[13:20] if name.startswith("geo-elements-") else name[:7]
    first = datetime.strptime(m + "-01", "%Y-%m-%d")
    return [f"pnt-data-{m}", f"pnt-data-{(first - timedelta(days=1)).strftime('%Y-%m')}"]


def release_get(names, out):
    """Download release files that exist (missing ones are skipped)."""
    repo = os.environ.get("GITHUB_REPOSITORY", REPO)
    for name in names:
        for tag in tags_for(name):
            if not gh("release", "download", tag, "-R", repo, "-p", name, "-D", out, "--clobber").returncode:
                break


def release_put(paths):
    repo = os.environ.get("GITHUB_REPOSITORY", REPO)
    for p in paths:
        name = os.path.basename(p)
        for tag in tags_for(name):
            r = gh("release", "upload", tag, "-R", repo, "--clobber", p)
            if not r.returncode:
                break
        if r.returncode:
            raise SystemExit(f"upload of {name} failed: {r.stderr.strip()[:300]}")


def region_file(out, day, inv, evs, static, objects=None, fetched=None):
    doc = {"day": day, "source": CITE, "fetched_utc": fetched,
           "definitions": {"geo_alt_km": GEO_ALT, "band_km": BAND, "zone_inclination_deg": ZONE_INC,
                           "near_geo": {"mean_motion": [N_MIN, N_MAX], "eccentricity_below": E_MAX}, "quiet_days": QUIET_DAYS},
           "counts": counts(inv, static), "events": evs, "regions": {str(k): [v["region"], v["epoch"][:19]] for k, v in sorted(inv.items())}}
    if objects is not None:
        doc["object_cols"] = OBJ_COLS
        doc["objects"] = objects
    p = os.path.join(out, f"{day}.geo-region.json")
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, separators=(",", ":"), ensure_ascii=False)
    return p


def load_region(out, day):
    p = os.path.join(out, f"{day}.geo-region.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return None


# ---------------------------------------------------------------- commands
def pull(day, out, upload, records=None, geo_dir=os.path.join(ROOT, "data", "geo")):
    """One gp query (or `records`, for tests and the backfill's own first query): today's file and new element sets."""
    os.makedirs(out, exist_ok=True)
    fetched = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    if records is None and upload:
        release_get([f"{day}.geo-region.json"], out)
        held = load_region(out, day)
        if held and held.get("fetched_utc"):
            since = datetime.now(timezone.utc) - datetime.strptime(held["fetched_utc"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
            if since.total_seconds() < 3600:
                print(f"{day}: pulled {int(since.total_seconds() // 60)} minutes ago; Space-Track allows one gp query an hour: skipped")
                return None, None
    if records is None:
        records = gp_near_geo(out)
    static = {s["norad"]: s for s in map(static_row, records) if s["norad"] is not None}
    rows = [r for r in map(elset_row, records) if r["norad"] is not None and r["epoch"]]
    yday = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    months = sorted({month_of(r["epoch"]) for r in rows if r["epoch"] >= HISTORY_START})
    if upload:
        release_get([f"geo-elements-{m}.parquet" for m in months] + [f"{yday}.geo-region.json"], out)
    merged = merge_elements(out, rows)
    latest = {r["norad"]: r for r in rows}
    prev_doc = load_region(out, yday)
    prev = {int(k): {"region": v[0], "epoch": v[1]} for k, v in prev_doc["regions"].items()} if prev_doc else None
    inv = from_latest(latest, prev)
    evs = events(prev, inv, day, static, active=active_ids(day, geo_dir)) if prev is not None else []   # a first day lists none
    objects = []
    for k in sorted(inv):
        s, r = static.get(k, {}), latest[k]
        objects.append([k, s.get("name"), s.get("cospar"), s.get("type"), s.get("owner"), s.get("launch"), s.get("rcs"), inv[k]["region"],
                        r["epoch"], r["n"], r["e"], r["i"], r["raan"], r["argp"], r["M"], r["bstar"], r["ndot"], r["nddot"]])
    path = region_file(out, day, inv, evs, static, objects, fetched)
    c = counts(inv, static)
    print(f"{day}: {len(inv)} objects near GEO; zone {sum(c['zone'].values())}, graveyard {sum(c['graveyard'].values())}; "
          f"{len(evs)} events; element sets held by month: {merged}")
    if upload:
        release_put([path] + [os.path.join(out, f"geo-elements-{m}.parquet") for m in merged])
        print("uploaded")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write("geo_changed=true\n")
    return records, static


def backfill(since, events_from, out, upload):
    """gp_history for every object near GEO now, once: cached per chunk, never fetched twice; then replay the days."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cache = os.path.join(out, "history")
    os.makedirs(cache, exist_ok=True)
    until = end_of(today)
    mpath = os.path.join(cache, "fetched.json")          # {norad: [since, until]}: histories already held
    held = json.load(open(mpath, encoding="utf-8")) if os.path.exists(mpath) else {}
    with SpaceTrack() as st:
        records = gp_near_geo(out, st)
        ids = sorted({int(g["NORAD_CAT_ID"]) for g in records} - {int(k) for k in held})
        chunks = [ids[k:k + CHUNK] for k in range(0, len(ids), CHUNK)]
        print(f"{len(records)} objects near GEO now; {len(held)} histories already held; {len(chunks)} history requests of up to {CHUNK}")
        for n, ch in enumerate(chunks):
            p = os.path.join(cache, f"history_{ch[0]}-{ch[-1]}_{since}_{until}.json")
            time.sleep(PAUSE)
            data = st.query(history_path(ch, since, until))
            with open(p + ".part", "w", encoding="utf-8") as f:
                json.dump(data, f, separators=(",", ":"))
            os.replace(p + ".part", p)
            held.update({str(k): [since, until] for k in ch})
            with open(mpath + ".part", "w", encoding="utf-8") as f:
                json.dump(held, f)
            os.replace(mpath + ".part", mpath)
            print(f"  chunk {n + 1}/{len(chunks)}: {len(data)} element sets")
    replay(events_from, out, upload, records)


def replay(events_from, out, upload, records=None):
    """Rebuild the monthly element files and one region file per day from the held history (no Space-Track request)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cache = os.path.join(out, "history")
    if records is None:
        with open(os.path.join(out, "gp_latest.json"), encoding="utf-8") as f:
            records = json.load(f)
    rows = []
    for p in sorted(glob.glob(os.path.join(cache, "history_*.json"))):
        with open(p, encoding="utf-8") as f:
            rows += [r for r in map(elset_row, json.load(f)) if r["norad"] is not None and r["epoch"]]
    rows += [r for r in map(elset_row, records) if r["norad"] is not None and r["epoch"]]
    static = {s["norad"]: s for s in map(static_row, records) if s["norad"] is not None}
    merged = merge_elements(out, rows)
    print(f"{len(rows)} element sets; by month: {merged}")
    # replay: one region file per day, events from `events_from`
    d, seen, prev, paths = datetime.strptime(events_from, "%Y-%m-%d") - timedelta(days=1), set(), None, []
    stop = datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)          # today's file comes from the pull below
    tally, latest, order, at = {}, {}, sorted(rows, key=lambda r: r["epoch"]), 0
    active = active_ids(today)
    while d <= stop:
        day = d.strftime("%Y-%m-%d")
        cut = end_of(day)
        while at < len(order) and order[at]["epoch"] < cut:
            latest[order[at]["norad"]] = order[at]
            at += 1
        inv = from_latest(latest, prev)
        if prev is None:
            seen |= set(inv)                       # the day before the first: its objects aren't "new"
        else:
            evs = events(prev, inv, day, static, seen, active)
            seen |= set(inv)
            for e in evs:
                tally[e["kind"]] = tally.get(e["kind"], 0) + 1
            paths.append(region_file(out, day, inv, evs, static))
        prev, d = inv, d + timedelta(days=1)
    print(f"replayed {len(paths)} days from {events_from}: events {tally}")
    pull(today, out, False, records)               # today's file from the same gp query (no second gp request)
    paths.append(os.path.join(out, f"{today}.geo-region.json"))
    if upload:
        release_put(paths + [os.path.join(out, f"geo-elements-{m}.parquet") for m in merged])
        print(f"uploaded {len(paths)} region files and {len(merged)} element files")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pull")
    p.add_argument("--day", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    p.add_argument("--out", default=os.path.join(ROOT, "data", "geo", "region"))
    p.add_argument("--upload", action="store_true")
    b = sub.add_parser("backfill")
    b.add_argument("--since", required=True, help="first epoch to fetch (YYYY-MM-DD); fetched once per object, ever")
    b.add_argument("--events-from", required=True, help="first day with events (a week or more after --since)")
    b.add_argument("--out", default=os.path.join(ROOT, "data", "geo", "region"))
    b.add_argument("--upload", action="store_true")
    r = sub.add_parser("replay")
    r.add_argument("--events-from", required=True)
    r.add_argument("--out", default=os.path.join(ROOT, "data", "geo", "region"))
    r.add_argument("--upload", action="store_true")
    a = ap.parse_args()
    if a.cmd == "pull":
        pull(a.day, a.out, a.upload)
    elif a.cmd == "replay":
        replay(a.events_from, a.out, a.upload)
    else:
        backfill(a.since, a.events_from, a.out, a.upload)


if __name__ == "__main__":
    main()
