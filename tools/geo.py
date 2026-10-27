#!/usr/bin/env python3
"""geo.py: the GEO threat board: where every active geosynchronous object is, which are drifting, which manoeuvred, and
which come close to an object of another owner. Proximity and behaviour only, never intent.

  python tools/geo.py snapshot [--day D] [--out DIR] [--upload]   # CelesTrak GEO elements + catalogue -> DIR/<day>.geo.json
  python tools/geo.py build RELEASE_DIR [SITE]                    # snapshots -> SITE/data/geo.json (the /geo page, board card)

Data: CelesTrak GP (GROUP=geo, OMM JSON) and SATCAT (owner, type). The elements are USSPACECOM basic SSA data, which
Space-Track allows to be redistributed and used in published analysis with citation; cite "Orbital data: USSPACECOM
(space-track.org) via CelesTrak". CelesTrak's usage policy: download once per 2-hour update and stop on any non-200
response, so the daily workflow takes at most one snapshot per run (two runs a day).

Method (coarse, stated on the page):
  longitude   sub-satellite longitude at the element epoch from the mean elements (two-body, near-circular), and at a
              common time by two-body propagation; public elements at GEO are good to tens of km
  drift       (mean motion x 360 - 360.9856) deg/day; station-kept objects drift under DRIFT_KEPT deg/day
  close       pairs of different owners within CLOSE_KM of each other at the common time; pairs of one owner are
              listed apart (operators co-locate their own satellites on purpose)
  manoeuvre   between consecutive snapshots: drift rate changed by more than MAN_DRIFT deg/day, inclination by more
              than MAN_INC deg, or the longitude is more than MAN_LON deg from where the earlier elements put it at the later
              epoch (two-body propagation, so inclined and eccentric orbits' daily swing isn't mistaken for a manoeuvre)
  kind        routine station-keeping when the object isn't drifting (drift under DRIFT_KEPT) before or after, except
              an inclination change on an inclined orbit (INC_KEPT or more): inclined satellites still trim drift to hold
              longitude, but aren't held north-south, so that is "inclined orbit changed". Drifting before or after:
              started drifting, stopped drifting, or drift rate changed
  owners      SATCAT owner codes are often a country (US, PRC), so "same owner" pairs are counted, not listed, unless one
              of the two has a listed role (site_src/geo_roles.json)
"""
import argparse
import glob
import json
import math
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "noise-floor (github.com/metacog-osint/noise-floor)"}
GP_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=geo&FORMAT=json"
SATCAT_URL = "https://celestrak.org/satcat/records.php?GROUP=geo&FORMAT=json"
MU = 398600.4418                  # km^3/s^2
SIDEREAL = 360.98564736629        # deg/day, Earth's rotation
DRIFT_KEPT, INC_KEPT = 0.1, 1.0   # deg/day, deg: station-kept
CLOSE_KM = 100.0
MAN_DRIFT, MAN_INC, MAN_LON = 0.02, 0.02, 0.15
CITE = "Orbital data: USSPACECOM (space-track.org) via CelesTrak; basic SSA data, redistributed with citation."
REPO = "metacog-osint/noise-floor"
ROLES = os.path.join(ROOT, "site_src", "geo_roles.json")   # cited roles (inspection-capable, servicing), curated by hand


def load_roles(path=ROLES):
    try:
        d = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {o["id"]: o for o in d.get("objects", [])}


def pair_kind(ra, rb):
    """What a close pair is, as far as the listed roles say."""
    roles = {ra, rb} - {None}
    if "servicing" in roles:
        return "servicing involved"
    if "inspection" in roles:
        return "inspection-capable involved"
    return "no listed role (often slot-sharing)"


def gmst_deg(t):
    """Greenwich mean sidereal time (deg) at datetime t (UTC), IAU 1982."""
    jd = t.timestamp() / 86400.0 + 2440587.5
    d = jd - 2451545.0
    T = d / 36525.0
    return (280.46061837 + 360.98564736629 * d + 0.000387933 * T * T - T ** 3 / 38710000.0) % 360.0


def kepler(M, e):
    E = M
    for _ in range(8):
        E -= (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
    return E


def epoch_of(s):
    s = s.replace("Z", "")
    fmt = "%Y-%m-%dT%H:%M:%S.%f" if "." in s else "%Y-%m-%dT%H:%M:%S"
    return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)


def state(o, t):
    """ECI position (km) and sub-satellite longitude (deg, -180..180) of object o at time t, two-body from its epoch."""
    n = o["n"] * 2 * math.pi / 86400.0                       # rad/s
    a = (MU / n ** 2) ** (1 / 3)
    dt = (t - epoch_of(o["epoch"])).total_seconds()
    M = math.radians(o["M"]) + n * dt
    E = kepler(M % (2 * math.pi), o["e"])
    nu = 2 * math.atan2(math.sqrt(1 + o["e"]) * math.sin(E / 2), math.sqrt(1 - o["e"]) * math.cos(E / 2))
    r = a * (1 - o["e"] * math.cos(E))
    i, W, w = math.radians(o["i"]), math.radians(o["raan"]), math.radians(o["argp"])
    u = w + nu
    x = r * (math.cos(W) * math.cos(u) - math.sin(W) * math.sin(u) * math.cos(i))
    y = r * (math.sin(W) * math.cos(u) + math.cos(W) * math.sin(u) * math.cos(i))
    z = r * math.sin(u) * math.sin(i)
    lon = (math.degrees(math.atan2(y, x)) - gmst_deg(t) + 540) % 360 - 180
    return (x, y, z), lon


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        if r.status != 200:
            raise RuntimeError(f"CelesTrak returned {r.status}: stopping, as its usage policy asks")
        return json.load(r)


def snapshot(day, gp=None, satcat=None):
    gp = gp if gp is not None else fetch(GP_URL)
    satcat = satcat if satcat is not None else fetch(SATCAT_URL)
    cat = {s["NORAD_CAT_ID"]: s for s in satcat}
    objs = []
    for g in gp:
        o = {"id": g["NORAD_CAT_ID"], "name": g["OBJECT_NAME"], "cospar": g.get("OBJECT_ID"), "epoch": g["EPOCH"],
             "n": g["MEAN_MOTION"], "e": g["ECCENTRICITY"], "i": g["INCLINATION"], "raan": g["RA_OF_ASC_NODE"],
             "argp": g["ARG_OF_PERICENTER"], "M": g["MEAN_ANOMALY"]}
        c = cat.get(g["NORAD_CAT_ID"], {})
        o.update(owner=c.get("OWNER"), type=c.get("OBJECT_TYPE"), status=c.get("OPS_STATUS_CODE"), launch=c.get("LAUNCH_DATE"))
        _, o["lon"] = state(o, epoch_of(o["epoch"]))
        o["lon"] = round(o["lon"], 3)
        o["drift"] = round(o["n"] * 360 - SIDEREAL, 4)
        objs.append(o)
    return {"day": day, "fetched_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "source": CITE,
            "count": len(objs), "objects": objs}


def classify(o):
    if abs(o["drift"]) >= DRIFT_KEPT:
        return "drifting"
    return "station-kept" if o["i"] < INC_KEPT else "inclined"


ROUTINE = "station-keeping"


def man_kind(q, o, changed=()):
    """Routine station-keeping, or the rarer kind: a relocation, a drift change, or a change to an inclined orbit."""
    kept_q, kept_o = abs(q["drift"]) < DRIFT_KEPT, abs(o["drift"]) < DRIFT_KEPT
    if kept_q and kept_o:
        inclined = q["i"] >= INC_KEPT or o["i"] >= INC_KEPT
        return "inclined orbit changed" if inclined and "inclination" in changed else ROUTINE
    if kept_q:
        return "started drifting"
    if kept_o:
        return "stopped drifting"
    return "drift rate changed"


def manoeuvres(prev, cur):
    """Objects whose elements changed between two snapshots more than drift alone explains."""
    p = {o["id"]: o for o in prev["objects"]}
    out = []
    for o in cur["objects"]:
        q = p.get(o["id"])
        if not q or q["epoch"] == o["epoch"]:
            continue
        # where the earlier elements put the object at the later epoch, by the same two-body motion: a straight drift line
        # would miss the daily figure-of-eight of inclined orbits and the swing of eccentric ones (up to 1-2 degrees)
        _, pred = state(q, epoch_of(o["epoch"]))
        dlon = (o["lon"] - pred + 540) % 360 - 180
        why, changed = [], []
        if abs(o["drift"] - q["drift"]) > MAN_DRIFT:
            why.append(f"drift {q['drift']:+.3f} -> {o['drift']:+.3f} deg/day")
            changed.append("drift")
        if abs(o["i"] - q["i"]) > MAN_INC:
            why.append(f"inclination {q['i']:.3f} -> {o['i']:.3f} deg")
            changed.append("inclination")
        if abs(dlon) > MAN_LON:
            why.append(f"longitude {dlon:+.2f} deg off the earlier drift")
            changed.append("longitude")
        if why:
            out.append({"id": o["id"], "name": o["name"], "owner": o["owner"], "lon": o["lon"], "between": [q["epoch"][:16], o["epoch"][:16]],
                        "kind": man_kind(q, o, changed), "changed": changed, "drift": [q["drift"], o["drift"]],
                        "inc": [round(q["i"], 3), round(o["i"], 3)], "dlon": round(dlon, 2), "what": "; ".join(why)})
    return out


def region_summary(release, days=30):
    """The Space-Track region files (tools/geo_region.py): the latest day's counts and the last `days` days' events."""
    docs = []
    for f in sorted(glob.glob(os.path.join(release, "*.geo-region.json")))[-days:]:
        try:
            docs.append(json.load(open(f, encoding="utf-8")))
        except ValueError:
            pass
    if not docs:
        return None
    last = docs[-1]
    evs = sorted((e for d in docs for e in d.get("events", [])), key=lambda e: (e["day"], e["norad"]), reverse=True)
    return {"day": last["day"], "fetched_utc": last.get("fetched_utc"), "first_day": docs[0]["day"], "counts": last["counts"],
            "definitions": last.get("definitions"), "source": last.get("source"), "events": evs}


def build(release, site, now=None):
    now = now or datetime.now(timezone.utc)
    snaps = []
    for f in sorted(glob.glob(os.path.join(release, "*.geo.json"))):
        try:
            snaps.append(json.load(open(f, encoding="utf-8")))
        except ValueError:
            pass
    if not snaps:
        raise SystemExit("no GEO snapshots")
    cur = snaps[-1]
    objs = cur["objects"]
    roles = load_roles()
    t = now.replace(second=0, microsecond=0)
    for o in objs:
        o["role"] = (roles.get(o["id"]) or {}).get("role")
        o["age_days"] = round((t - epoch_of(o["epoch"])).total_seconds() / 86400, 1)
    pos = {}
    for o in objs:
        try:
            pos[o["id"]], o["lon_now"] = state(o, t)
        except (ValueError, ZeroDivisionError):
            continue
        o["class"] = classify(o)
    close, same = [], []
    ids = [o for o in objs if o["id"] in pos]
    for k, a in enumerate(ids):
        for b in ids[k + 1:]:
            if abs(((a["lon_now"] - b["lon_now"] + 540) % 360) - 180) > 1.0:
                continue
            d = math.dist(pos[a["id"]], pos[b["id"]])
            if d <= CLOSE_KM:
                row = {"a": [a["id"], a["name"], a["owner"], a.get("role")], "b": [b["id"], b["name"], b["owner"], b.get("role")],
                       "km": round(d), "lon": round(a["lon_now"], 2), "kind": pair_kind(a.get("role"), b.get("role")),
                       "age_days": max(a["age_days"], b["age_days"])}
                hidden = a["owner"] and a["owner"] == b["owner"] and not (a.get("role") or b.get("role"))
                (same if hidden else close).append(row)
    close.sort(key=lambda r: (r["kind"].startswith("no listed"), r["km"]))
    mans = []
    for prev, nxt in list(zip(snaps, snaps[1:]))[-7:]:          # the last seven consecutive pairs
        for m in manoeuvres(prev, nxt):
            m["day"] = nxt["day"]
            mans.append(m)
    rare = [m for m in mans if m["kind"] != ROUTINE]
    routine = [m for m in mans if m["kind"] == ROUTINE][-300:]
    mans = sorted(rare + routine, key=lambda m: (m["day"], m["id"]))
    drifting = sorted((o for o in objs if o.get("class") == "drifting"), key=lambda o: -abs(o["drift"]))
    out = {"built_utc": now.strftime("%Y-%m-%dT%H:%MZ"), "at_utc": t.strftime("%Y-%m-%dT%H:%MZ"), "snapshot_day": cur["day"],
           "snapshots": len(snaps), "source": CITE, "method": {"close_km": CLOSE_KM, "drift_kept": DRIFT_KEPT,
           "inc_kept": INC_KEPT, "manoeuvre": [MAN_DRIFT, MAN_INC, MAN_LON]},
           "counts": {"objects": len(objs), "station-kept": sum(1 for o in objs if o.get("class") == "station-kept"),
                      "inclined": sum(1 for o in objs if o.get("class") == "inclined"), "drifting": len(drifting)},
           "close_other_owner": close[:40], "close_same_owner_count": len(same), "manoeuvres": mans,
           "manoeuvre_counts": {"other": len(rare), "station-keeping": sum(1 for m in mans if m["kind"] == ROUTINE)},
           "region": region_summary(release),
           "drifting": [{"id": o["id"], "name": o["name"], "owner": o["owner"], "lon": round(o["lon_now"], 2),
                         "drift": o["drift"], "role": o.get("role")} for o in drifting[:40]],
           "roles": {str(k): {"role": v["role"], "basis": v["basis"], "sources": v["sources"]} for k, v in roles.items()},
           "objects": [{"id": o["id"], "name": o["name"], "owner": o["owner"], "type": o.get("type"),
                        "lon": round(o.get("lon_now", o["lon"]), 2), "drift": o["drift"], "i": round(o["i"], 2),
                        "class": o.get("class"), "role": o.get("role"), "epoch": o["epoch"][:16]} for o in sorted(objs, key=lambda o: o.get("lon_now", o["lon"]))]}
    path = os.path.join(site, "data", "geo.json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("--day", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    s.add_argument("--out", default=os.path.join(ROOT, "data", "geo"))
    s.add_argument("--upload", action="store_true", help="upload to this repo's release pnt-data-<YYYY-MM> (gh CLI)")
    b = sub.add_parser("build")
    b.add_argument("release")
    b.add_argument("site", nargs="?", default=os.path.join(ROOT, "site"))
    a = ap.parse_args()
    if a.cmd == "snapshot":
        os.makedirs(a.out, exist_ok=True)
        snap = snapshot(a.day)
        path = os.path.join(a.out, f"{a.day}.geo.json")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(snap, f, separators=(",", ":"), ensure_ascii=False)
        print(f"{path}: {snap['count']} objects")
        if a.upload:
            repo = os.environ.get("GITHUB_REPOSITORY", REPO)
            first = datetime.strptime(a.day[:7] + "-01", "%Y-%m-%d")
            for month in (a.day[:7], (first - timedelta(days=1)).strftime("%Y-%m")):   # a new month's release exists from D+1
                r = subprocess.run(["gh", "release", "upload", f"pnt-data-{month}", "-R", repo, "--clobber", path],
                                   capture_output=True, text=True)
                if not r.returncode:
                    break
            if r.returncode:
                sys.exit(f"upload failed: {r.stderr.strip()[:300]}")
            print("uploaded")
            if os.environ.get("GITHUB_OUTPUT"):
                with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                    f.write("geo_changed=true\n")
    else:
        out = build(a.release, a.site)
        c = out["counts"]
        print(f"geo: {c['objects']} objects ({c['station-kept']} station-kept, {c['inclined']} inclined, {c['drifting']} drifting); "
              f"{len(out['close_other_owner'])} close pairs of different owners; {len(out['manoeuvres'])} manoeuvres "
              f"from {out['snapshots']} snapshots")


if __name__ == "__main__":
    main()
