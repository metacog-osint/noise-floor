#!/usr/bin/env python3
"""navwarnings.py: NGA navigational warnings (HYDROARC, HYDROLANT, NAVAREA IV/XII, HYDROPAC), archived and parsed.

  python tools/navwarnings.py fetch [--areas C,A,P] [--year 2026]   # merge into data/declared/navwarn/<area>-<year>.json
  python tools/navwarnings.py near LAT LON [--km 400] [--since YYYY-MM-DD]   # warnings with an area vertex in range

Source: NGA Maritime Safety Information, the "smaps" endpoint behind msi.nga.mil's warnings pages
  https://msi.nga.mil/api/publications/smaps?navArea=C&status=all&createdOn=2026&category=14&output=json
(category=14 is required; navArea 4, 12, A=HYDROLANT, P=HYDROPAC, C=HYDROARC). The older broadcast-warn endpoint
froze on 10 May 2024. smaps is undocumented and only reliable from about 26 Jul 2026, with gaps in the numbering, so
this tool keeps its own archive going forward: every fetch merges into the local files, newest version of each
warning wins. Russian warnings for the Barents and Kara seas appear only as NGA's HYDROARC relays (a subset).
Licence: US government work; NGA claims no copyright on its nautical publications (msi.nga.mil FAQ). Credit NGA.

Each warning is parsed into: id ("HYDROARC 280/26"), issued (UTC), cancel (UTC, from "CANCEL THIS MSG" or the
record's cancelledOn), activity (the first numbered line, without times), regions (header lines such as BARENTS SEA)
and points ([lat, lon] of every coordinate in the text). Standard library only.
"""
import argparse
import json
import math
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "declared", "navwarn")
URL = "https://msi.nga.mil/api/publications/smaps?navArea={area}&status={status}&createdOn={year}&category=14&output=json"
NAMES = {"4": "NAVAREA IV", "12": "NAVAREA XII", "A": "HYDROLANT", "P": "HYDROPAC", "C": "HYDROARC"}
MON = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}
COORD = re.compile(r"(\d{1,2})-(\d{2}(?:\.\d+)?)([NS])\s+(\d{1,3})-(\d{2}(?:\.\d+)?)([EW])")
CANCEL = re.compile(r"CANCEL THIS MSG (\d{2})(\d{2})(\d{2})Z ([A-Z]{3}) (\d{2})")
DTG = re.compile(r"(\d{2})(\d{2})(\d{2})Z ([A-Z]{3}) (\d{2,4})")


def dtg(s):
    """'271205Z OCT 2026' or '271205Z OCT 26' -> '2026-10-27T12:05Z' (None if it doesn't parse)."""
    m = DTG.search(s or "")
    if not m or m.group(4) not in MON:
        return None
    d, h, mi, mon, y = m.groups()
    y = int(y) + (2000 if len(y) == 2 else 0)
    return f"{y:04d}-{MON[mon]:02d}-{int(d):02d}T{int(h):02d}:{int(mi):02d}Z"


def parse(rec):
    text = rec.get("msgText") or ""
    area = str(rec.get("navArea", ""))
    num, issued = rec.get("msgSqncNumber"), dtg(rec.get("createdOn"))
    yy = (issued or "0000")[2:4]
    pts = [[round((int(a) + float(b) / 60) * (1 if c == "N" else -1), 4),
            round((int(d) + float(e) / 60) * (1 if f == "E" else -1), 4)] for a, b, c, d, e, f in COORD.findall(text)]
    cm = CANCEL.search(text)
    cancel = dtg(" ".join(cm.groups()[:3]).replace(" ", "") + "Z " + cm.group(4) + " " + cm.group(5)) if cm else None
    cancel = cancel or dtg(rec.get("cancelledOn"))
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    regions = [l.rstrip(".") for l in lines[2:6] if re.fullmatch(r"[A-Z .,'-]+\.", l) and not l.startswith(NAMES.get(area, "~"))]
    act = next((l for l in lines if re.match(r"1\.\s", l)), "")[3:]
    if not act:      # unnumbered messages (common in HYDROPAC): the first body line after the DTG, ID and region lines
        body = [l for l in lines[2:] if not re.fullmatch(r"[A-Z0-9 .,'()/-]+\.", l) or COORD.search(l) or len(l) > 40]
        act = body[0] if body else ""
    act = re.split(r"\s\d{4,6}Z|\sIN AREA|\sDAILY|\sBOUND BY", act)[0].strip(" .,")
    hm = re.search(r"\b(HYDROARC|HYDROLANT|HYDROPAC|NAVAREA [IVX]+) (\d+)/(\d{2})", text)
    ident = f"{hm.group(1)} {int(hm.group(2))}/{hm.group(3)}" if hm else f"{NAMES.get(area, area)} {num}/{yy}"
    return {"id": ident, "area": area, "number": num, "issued": issued,
            "cancel": cancel, "status": rec.get("status"), "activity": act, "regions": regions, "points": pts,
            "text": text}


def fetch(areas, year, log=print):
    os.makedirs(OUT, exist_ok=True)
    for area in areas:
        path = os.path.join(OUT, f"{NAMES.get(area, area).replace(' ', '_')}-{year}.json")
        have = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
        req = urllib.request.Request(URL.format(area=area, status="all", year=year), headers={"User-Agent": "noise-floor"})
        recs = None
        for attempt in range(3):                          # large responses sometimes arrive cut short
            try:
                recs = json.load(urllib.request.urlopen(req, timeout=90)).get("smaps", [])
                break
            except Exception as e:
                log(f"{NAMES.get(area, area)} {year}: attempt {attempt + 1} failed ({type(e).__name__})")
                time.sleep(5 * (attempt + 1))
        if recs is None:
            log(f"{NAMES.get(area, area)} {year}: skipped this run; the archive keeps what it had")
            continue
        new = 0
        for r in recs:
            w = parse(r)
            key = str(w["number"])
            if key not in have:
                new += 1
            have[key] = w
        tmp = path + ".tmp"
        json.dump(have, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
        os.replace(tmp, path)
        log(f"{NAMES.get(area, area)} {year}: {len(recs)} fetched, {new} new, {len(have)} archived -> {os.path.relpath(path, ROOT)}")
        time.sleep(1.0)                                   # one request per query; the site sits behind a firewall


def load(areas=("C", "A", "P"), years=None):
    years = years or [datetime.now(timezone.utc).year]
    out = []
    for area in areas:
        for y in years:
            path = os.path.join(OUT, f"{NAMES.get(area, area).replace(' ', '_')}-{y}.json")
            if os.path.exists(path):
                out += json.load(open(path, encoding="utf-8")).values()
    return out


def km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(a)))


MILITARY = re.compile(r"MISSILE|ROCKET|HAZARDOUS OPERATIONS|GUNNERY|FIRING|EXERCISE|GPS|GNSS|JAMMING|"
                      r"SPACE DEBRIS|DANGEROUS|NAVAL OPERATIONS|MILITARY", re.I)


def near(warnings, lat, lon, max_km=400, start=None, end=None, military=True):
    """Warnings with an area vertex within max_km whose issued..cancel window overlaps start..end (ISO strings).
    military=True keeps only firing, missile, rocket, exercise and GNSS warnings (not buoys, cables, surveys)."""
    out = []
    for w in warnings:
        # the military/GNSS test reads the whole message: unnumbered warnings name their activity anywhere in the body
        if not w["points"] or military and not MILITARY.search((w["activity"] or "") + " " + (w.get("text") or "")):
            continue
        d = min(km(lat, lon, p[0], p[1]) for p in w["points"])
        if d > max_km:
            continue
        lo, hi = w["issued"] or "", w["cancel"] or "9999"
        if start and hi < start or end and lo > end:
            continue
        out.append({"id": w["id"], "activity": w["activity"], "issued": w["issued"], "cancel": w["cancel"],
                    "regions": w["regions"], "km": round(d)})
    return sorted(out, key=lambda x: x["issued"] or "")


def main():
    ap = argparse.ArgumentParser(prog="navwarnings")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--areas", default="C,A,P")
    f.add_argument("--year", type=int, default=datetime.now(timezone.utc).year)
    n = sub.add_parser("near")
    n.add_argument("lat", type=float)
    n.add_argument("lon", type=float)
    n.add_argument("--km", type=float, default=400)
    n.add_argument("--since")
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch(a.areas.split(","), a.year)
    else:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        for w in near(load(), a.lat, a.lon, a.km, start=a.since):
            print(f'{w["id"]:18s} {w["issued"] or "?":17s} to {w["cancel"] or "?":17s} {w["km"]:4d} km  {w["activity"][:60]}  ({", ".join(w["regions"])})')


if __name__ == "__main__":
    main()
