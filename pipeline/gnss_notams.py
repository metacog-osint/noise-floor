#!/usr/bin/env python3
"""gnss_notams.py: GPS/GNSS NOTAMs from Launch's published files, archived to a release and shown on the map.

Launch (the suite's launch program) reads the FAA NOTAM Management Service API (NMS-API) and publishes the GNSS
subset at https://launch.theintelligence.company/data/gnss-notams/: index.json, active.json and one <day>.json per
ended UTC day (schema and selection rule in Launch's launch/gnss.py, rule gnss-1.0). Launch keeps 14 days and may
rewrite a day file for 48 hours after the day ends (`revised_at`, set when a late cancel changes it). Noisefloor
keeps every day:

  python pipeline/gnss_notams.py archive [--upload]   # new or rewritten day files to DIR (and the declared-data release)
  python pipeline/gnss_notams.py site RELEASE_DIR SITE # SITE/data/notams/<day>.json and index.json, for the map

archive compares each day in Launch's index with the archive's own index (gnss-notams-index.json): a day is fetched
again when Launch's written_at or revised_at differs from the copy kept. Day files are kept exactly as Launch
published them (<day>.gnss-notams.json); a day Launch has dropped stays in the archive.

Wording (the FAA NMS-API terms and Launch's source_note): never "FAA data"; NMS is not the authoritative source for
NOTAMs issued outside the United States. Every file Noisefloor writes carries Launch's source_note word for word.

Geometry comes from each NOTAM's Q line (notam.coordinates, ddmmN dddmmE, and notam.radius in NM), never from the
NMS GeoJSON geometry, which is sometimes empty or a point at 0,0. A notice without a Q line (US domestic notices,
numbered like 10/113) takes the first "NNNNM RADIUS CENTERED AT ddmmssN dddmmssW" in its text, marked
geo "text"; else it has no place on the map. A radius of 999 NM means the whole FIR or more: no circle.

The site groups notices for reading (a display choice, Noisefloor's own, not the FAA's or ICAO's; see KINDS):
copies of one notice issued to several US centres (the same text, or the same announced test id) show once, with
their numbers. Standard library only (the deploy job runs it without installing anything).
"""
import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://launch.theintelligence.company/data/gnss-notams/"
DIR = os.path.join(ROOT, "data", "declared", "gnss-notams")
RELEASE = "declared-data"
INDEX = "gnss-notams-index.json"
DAY_FILE = "{day}.gnss-notams.json"
DAY_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.gnss-notams\.json$")
UA = {"User-Agent": "noise-floor (research; github.com/metacog-osint/noise-floor)"}
SOURCE_FALLBACK = ("NOTAMs read through the FAA NOTAM Management Service API (NMS-API). Not FAA data as published "
                   "by Launch, and not the authoritative source for NOTAMs issued outside the United States.")
WHOLE_FIR_NM = 999

# Q line: 4054N02919E (degrees and minutes); text: 333921N1063127W (degrees, minutes, seconds)
Q_POS = re.compile(r"^(\d{2})(\d{2})([NS])(\d{3})(\d{2})([EW])$")
TEXT_RADIUS = re.compile(r"(\d{1,4})\s*NM\s+RADIUS\s+(?:CENTERED\s+AT|CENTRED\s+(?:AT|ON)|OF)\s+"
                         r"(\d{2})(\d{2})(\d{2}(?:\.\d+)?)([NS])\s*(\d{3})(\d{2})(\d{2}(?:\.\d+)?)([EW])")
TEST_ID = re.compile(r"\(([A-Z][A-Z0-9]+ GPS \d{2}-\d+)(?: REV \d+)?\)")
LEAD = re.compile(r"^(?:(?:Z[A-Z]{2}|GPS|NAV|AIRSPACE)\s+)+")   # "ZFW NAV GPS ...", "GPS NAV PRN 25 U/S"

# Reading groups, first that applies. Noisefloor's display choice from the notice's own words.
KINDS = [
    ("test", "Announced GPS tests", re.compile(r"\b[A-Z][A-Z0-9]+ GPS \d{2}-\d+\b")),
    ("satellite", "Satellite outages", re.compile(r"\bNANU\b|PSEUDO RANDOM NOISE|\bPRN\s*\d")),
    ("interference", "Interference reported or expected",
     re.compile(r"INTERFER|JAMM|SPOOF|BROUILLAGE|PERTURBATION|UNREL|INTERRUPT|INTRP|LOSS|\bLOST\b|DISRUPT|"
                r"NOT BE RECEIVED|CAN NOT BE RECEIVED|FAILURES?\b|MISSING OF GNSS|OUTAGE|ANOMAL|\bECM\b|"
                r"RECEPTION ISSUES|MAP SHIFT")),
    ("equipment", "Ground equipment and procedures",
     re.compile(r"GBAS|\bGLS\b|SBAS|WAAS|EGNOS|RNAV|\bRNP\b|\bPROC|\bIAC\b|\bAIP\b|APCH|APPROACH|\bSID\b|\bSTAR\b")),
    ("other", "Other GNSS notices", re.compile(r"")),
]
KIND_LABEL = {k: label for k, label, _ in KINDS}


# ---------------------------------------------------------------- fetching and the archive
def get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return json.load(r)


def gh(*args, check=True):
    return subprocess.run(["gh", *args], check=check, capture_output=True, text=True)


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write(path, obj, compact=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":") if compact else None,
                  indent=None if compact else 1)
        f.write("\n")
    os.replace(tmp, path)


def valid_day(d, day):
    """A Launch day file as the schema promises, else the reason it isn't."""
    if not isinstance(d, dict):
        return "not an object"
    if d.get("program") != "launch" or d.get("dataset") != "gnss-notams":
        return f"program/dataset {d.get('program')}/{d.get('dataset')}"
    if d.get("day") != day:
        return f"day {d.get('day')} in the file for {day}"
    if not isinstance(d.get("notices"), list):
        return "no notices list"
    if d.get("n") is not None and d["n"] != len(d["notices"]):
        return f"n {d['n']} but {len(d['notices'])} notices"
    return None


def changed(entry, kept):
    """Launch's index entry differs from the archived copy (a new day, a rewrite or a revision)."""
    return not kept or (entry.get("written_at"), entry.get("revised_at")) != (kept.get("written_at"), kept.get("revised_at"))


def archive(out_dir=DIR, upload=False, fetch=get_json, now=None):
    """Fetch new or rewritten day files into out_dir and update its index. Returns the list of days written."""
    now = now or datetime.now(timezone.utc)
    os.makedirs(out_dir, exist_ok=True)
    idx_path = os.path.join(out_dir, INDEX)
    if upload:
        gh("release", "download", RELEASE, "-p", INDEX, "-D", out_dir, "--clobber", check=False)
    idx = load(idx_path, {}) or {}
    days = idx.setdefault("days", {})
    launch = fetch(BASE + "index.json")
    wrote = []
    for e in launch.get("days") or []:
        day = e.get("day")
        if not day or not changed(e, days.get(day)):
            continue
        d = fetch(e.get("url") or BASE + f"{day}.json")
        bad = valid_day(d, day)
        if bad:
            print(f"gnss_notams: {day} skipped: {bad}", file=sys.stderr)
            continue
        path = os.path.join(out_dir, DAY_FILE.format(day=day))
        write(path, d)
        with open(path, "rb") as f:
            sha = hashlib.sha256(f.read()).hexdigest()
        was = days.get(day)
        days[day] = {"n": len(d["notices"]), "written_at": d.get("written_at"), "revised_at": d.get("revised_at"),
                     "env": d.get("env"), "lane_status": d.get("lane_status"), "runs_that_day": d.get("runs_that_day"),
                     "sha256": sha, "archived_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "copies": (was or {}).get("copies", 0) + 1}
        wrote.append(day)
    idx.update({"program": "noisefloor", "dataset": "gnss-notams-archive", "from": BASE,
                "source_note": launch.get("source_note") or SOURCE_FALLBACK, "rule": launch.get("rule"),
                "checked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "note": ("Day files as Launch published them (launch/gnss.py), kept beyond Launch's 14 days. A day is "
                         "copied again when Launch's written_at or revised_at changes; copies counts the copies.")})
    idx["days"] = dict(sorted(days.items()))
    write(idx_path, idx)
    if upload and wrote:
        files = [os.path.join(out_dir, DAY_FILE.format(day=d)) for d in wrote]
        gh("release", "upload", RELEASE, *files, idx_path, "--clobber")
    elif upload:
        gh("release", "upload", RELEASE, idx_path, "--clobber")
    print(f"gnss_notams: {len(wrote)} day file(s) archived ({', '.join(wrote) or 'none new'}); "
          f"{len(idx['days'])} days kept")
    return wrote


# ---------------------------------------------------------------- reading one notice
def q_position(coords):
    """(lat, lon) from a Q line position such as '4054N02919E', else None (also for 0,0)."""
    m = Q_POS.match((coords or "").strip())
    if not m:
        return None
    lat = int(m.group(1)) + int(m.group(2)) / 60
    lon = int(m.group(4)) + int(m.group(5)) / 60
    lat, lon = (-lat if m.group(3) == "S" else lat), (-lon if m.group(6) == "W" else lon)
    if lat == 0 and lon == 0:
        return None
    return round(lat, 4), round(lon, 4)


def text_circle(text):
    """(lat, lon, radius_nm) from the first 'NNNNM RADIUS CENTERED AT ddmmssN dddmmssW' in the text, else None."""
    m = TEXT_RADIUS.search(text or "")
    if not m:
        return None
    g = m.groups()
    lat = int(g[1]) + int(g[2]) / 60 + float(g[3]) / 3600
    lon = int(g[5]) + int(g[6]) / 60 + float(g[7]) / 3600
    return round(-lat if g[4] == "S" else lat, 4), round(-lon if g[8] == "W" else lon, 4), int(g[0])


def where(n, text):
    """{'lat','lon','radius_nm','geo'} from the Q line, else the text, else {}."""
    pos = q_position(n.get("coordinates"))
    if pos:
        try:
            r = int(str(n.get("radius") or "").strip())
        except ValueError:
            r = None
        return {"lat": pos[0], "lon": pos[1], "radius_nm": r, "geo": "q"}
    c = text_circle(text)
    if c:
        return {"lat": c[0], "lon": c[1], "radius_nm": c[2], "geo": "text"}
    return {}


def kind(text):
    t = (text or "").upper()
    for k, _, rx in KINDS:
        if rx.search(t):
            return k
    return "other"


def group_key(text):
    """Copies of one US notice to several centres share this: the announced test id, else the text without its
    leading centre id and subject words ('ZFW NAV GPS ...', 'GPS NAV PRN 25 U/S') and its daily schedule."""
    t = re.sub(r"\s+", " ", (text or "").upper()).strip()
    m = TEST_ID.search(t)
    if m:
        return "test:" + m.group(1)
    t = LEAD.sub("", t)
    t = re.sub(r"\s*DLY\s+\d{4}\s*-\s*\d{4}\.?$", "", t)
    return "text:" + hashlib.sha1(t.encode("utf-8")).hexdigest()[:16]


def slim(x):
    """One notice as the map shows it."""
    n = x.get("notam") or {}
    text = (n.get("text") or "").strip()
    test = TEST_ID.search(re.sub(r"\s+", " ", text.upper()))
    return {"number": n.get("number"), "type": n.get("type"), "fir": n.get("affectedFir"),
            "location": n.get("icaoLocation") or n.get("location"), "q_code": x.get("q_code"),
            "matched_by": x.get("matched_by"), "classification": n.get("classification"),
            "issued": n.get("issued"), "start": n.get("effectiveStart"), "end": n.get("effectiveEnd"),
            "schedule": n.get("schedule"), "lower": n.get("lowerLimit") or n.get("minimumFl"),
            "upper": n.get("upperLimit") or n.get("maximumFl"),
            "refers_to": x.get("refers_to"), "cancelled_by": x.get("cancelled_by"),
            "replaced_by": x.get("replaced_by"), "ended_at": x.get("ended_at"),
            "kind": kind(text), "test": test.group(1) if test else None, "text": text, **where(n, text)}


def site_day(d):
    """The map's file for one Launch day file: groups of copies, newest issue first within each reading group."""
    groups = {}
    for x in d.get("notices") or []:
        s = slim(x)
        # The same words at two aerodromes ("GNSS FAILURE POSS WI AD AREA.") are two notices: their Q lines differ.
        at = (s.get("lat"), s.get("lon")) if s.get("geo") == "q" else None
        groups.setdefault((group_key(s["text"]), at), []).append(s)
    rows = []
    for members in groups.values():
        members.sort(key=lambda s: (s["classification"] != "INTL", s["number"] or ""))
        lead = dict(members[0])
        geo = next((m for m in members if m.get("geo") == "q"), None) or next((m for m in members if m.get("geo")), None)
        for k in ("lat", "lon", "radius_nm", "geo"):
            lead.pop(k, None)
            if geo and k in geo:
                lead[k] = geo[k]
        lead["copies"] = [{"number": m["number"], "location": m["location"]} for m in members[1:]]
        lead["issued"] = max((m["issued"] or "") for m in members) or None
        rows.append(lead)
    order = {k: i for i, (k, _, _) in enumerate(KINDS)}
    rows.sort(key=lambda r: (order[r["kind"]], "".join(chr(255 - ord(c)) for c in (r["issued"] or ""))))
    counts = {k: sum(1 for r in rows if r["kind"] == k) for k, _, _ in KINDS}
    return {"program": "noisefloor", "dataset": "gnss-notams", "day": d.get("day"), "from": BASE + f"{d.get('day')}.json",
            "source_note": d.get("source_note") or SOURCE_FALLBACK, "rule": d.get("rule"),
            "written_at": d.get("written_at"), "revised_at": d.get("revised_at"), "env": d.get("env"),
            "lane_status": d.get("lane_status"), "runs_that_day": d.get("runs_that_day"),
            "n": len(d.get("notices") or []), "groups": len(rows), "kinds": {k: KIND_LABEL[k] for k, _, _ in KINDS},
            "counts": counts, "notices": rows}


def site(release_dir, site_dir):
    """SITE/data/notams/<day>.json for every archived day, and index.json listing them."""
    out = os.path.join(site_dir, "data", "notams")
    days = []
    for path in sorted(glob.glob(os.path.join(release_dir, "*.gnss-notams.json"))):
        m = DAY_RE.match(os.path.basename(path))
        d = load(path)
        if not m or valid_day(d, m.group(1)):
            continue
        s = site_day(d)
        write(os.path.join(out, f"{s['day']}.json"), s, compact=True)
        days.append({"day": s["day"], "n": s["n"], "groups": s["groups"], "counts": s["counts"],
                     "revised_at": s["revised_at"], "written_at": s["written_at"]})
    src = (load(os.path.join(release_dir, INDEX), {}) or {}).get("source_note") or SOURCE_FALLBACK
    write(os.path.join(out, "index.json"), {"program": "noisefloor", "dataset": "gnss-notams", "source_note": src,
                                            "from": BASE, "days": days}, compact=True)
    print(f"gnss_notams: {len(days)} day(s) for the map")
    return days


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("archive")
    a.add_argument("--dir", default=DIR)
    a.add_argument("--upload", action="store_true", help=f"read and write the {RELEASE} release (needs gh)")
    s = sub.add_parser("site")
    s.add_argument("release_dir")
    s.add_argument("site_dir")
    args = ap.parse_args(argv)
    if args.cmd == "archive":
        archive(args.dir, args.upload)
    else:
        site(args.release_dir, args.site_dir)


if __name__ == "__main__":
    main()
