#!/usr/bin/env python3
"""sanctions.py: vessels on official sanctions lists, by IMO number, for the Sea map (tools/vessels_build.py).

Sources (official government lists only; no aggregators, nothing paid):
  ofac  US Treasury OFAC Specially Designated Nationals and Blocked Persons List (SDN), "enhanced" XML from the
        Sanctions List Service. Vessel entries carry IMO numbers ("Vessel Registration Identification"), often MMSI
        and call sign, programme codes and the date the entry was published on the list (datePublished).
        US government work: not subject to copyright (17 U.S.C. 105). The OFAC pages state no terms of use (checked
        24 Oct 2026).
  uk    UK Sanctions List (FCDO), XML. "Specified ships" (IndividualEntityShip = Ship) carry IMO numbers, the regime,
        the date designated and the believed flag. Open Government Licence v3.0 (gov.uk publication page, checked
        24 Oct 2026); attribution "Contains public sector information licensed under the Open Government Licence v3.0."
OpenSanctions is not used (non-commercial licence). The EU port-access annex (Regulation 833/2014 Annex XLII) is not
parsed yet.

Output (root data/ is gitignored): data/vessels/sanctioned.json
  generated, sources [{id, list, name, url, page, published, licence, licence_evidence, attribution, vessels}],
  by_imo {"<imo>": {imo, names, flags, mmsi, callsigns, listings [{list, programme, date, url, id, name, flag}]}},
  no_imo [listings without an IMO number], by_mmsi {"<mmsi>": [imo, ...]} (OFAC only; a secondary match)
Downloads are cached in data/cache/sanctions/ (about 130 MB for both lists).

Usage
  python tools/sanctions.py                 # download both lists and write data/vessels/sanctioned.json
  python tools/sanctions.py --offline       # reuse the cached downloads
  python tools/sanctions.py --ofac FILE --uk FILE
"""
import argparse
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "cache", "sanctions")
OUT = os.path.join(ROOT, "data", "vessels", "sanctioned.json")
UA = {"User-Agent": "noise-floor sanctions list reader (research; github.com/metacog-osint/noise-floor)"}

SOURCES = {
    "ofac": {
        "list": "OFAC SDN",
        "name": "US Treasury OFAC Specially Designated Nationals and Blocked Persons List (SDN)",
        "url": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN_ENHANCED.XML",
        "page": "https://ofac.treasury.gov/sanctions-list-service",
        "file": "SDN_ENHANCED.XML",
        "licence": "US government work, not subject to copyright (17 U.S.C. 105)",
        "licence_evidence": "https://www.law.cornell.edu/uscode/text/17/105: \"not available for any work of the United States "
                            "Government\"; OFAC's list pages state no terms of use (checked 2026-10-24)",
        "attribution": "US Treasury, Office of Foreign Assets Control (OFAC), SDN List",
    },
    "uk": {
        "list": "UK Sanctions List",
        "name": "UK Sanctions List (Foreign, Commonwealth and Development Office)",
        "url": "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.xml",
        "page": "https://www.gov.uk/government/publications/the-uk-sanctions-list",
        "file": "UK-Sanctions-List.xml",
        "licence": "Open Government Licence v3.0",
        "licence_evidence": "https://www.gov.uk/government/publications/the-uk-sanctions-list: \"All content is available "
                            "under the Open Government Licence v3.0\" (checked 2026-10-24)",
        "attribution": "Contains public sector information licensed under the Open Government Licence v3.0 (UK Sanctions List, FCDO)",
    },
}
OFAC_DETAIL = "https://sanctionssearch.ofac.treas.gov/Details.aspx?id={}"


def imo_check_ok(imo):
    """IMO ship number check digit: digits 1-6 weighted 7..2, the sum's last digit equals digit 7."""
    try:
        imo = int(imo)
    except (TypeError, ValueError):
        return False
    if not 1_000_000 <= imo <= 9_999_999:
        return False
    s = str(imo)
    return sum(int(s[i]) * (7 - i) for i in range(6)) % 10 == int(s[6])


def imo_of(text):
    """The 7-digit IMO number in a list field ("IMO 9187629", "IMO9187629", "9187629"), else None."""
    m = re.search(r"(?<!\d)(\d{7})(?!\d)", str(text or ""))
    return int(m.group(1)) if m else None


def mmsi_of(text):
    m = re.search(r"(?<!\d)(\d{9})(?!\d)", str(text or ""))
    return int(m.group(1)) if m else None


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _kids(el, name):
    return [c for c in el if _local(c.tag) == name]


def _kid(el, name):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _all(el, *path):
    """Children named path[-1] under the chain of first children path[:-1] (empty when a step is missing)."""
    for p in path[:-1]:
        el = _kid(el, p) if el is not None else None
    return _kids(el, path[-1]) if el is not None else []


def _text(el, *path):
    for p in path:
        if el is None:
            return None
        el = _kid(el, p)
    return el.text.strip() if el is not None and el.text and el.text.strip() else None


def parse_ofac_enhanced(source):
    """OFAC SDN enhanced XML (file path or file object) -> one record per vessel entry."""
    out = []
    for _, el in ET.iterparse(source, events=("end",)):
        if _local(el.tag) != "entity":
            continue
        if _text(el, "generalInfo", "entityType") != "Vessel":
            el.clear()
            continue
        names, aliases = [], []
        for n in _all(el, "names", "name"):
            primary = _text(n, "isPrimary") == "true"
            for tr in _all(n, "translations", "translation"):
                full = _text(tr, "formattedFullName")
                if full:
                    (names if primary else aliases).append(full)
        feats = {}
        for f in _all(el, "features", "feature"):
            feats.setdefault(_text(f, "type") or "", []).append(_text(f, "value"))
        imos, mmsis = [], []
        for d in _all(el, "identityDocuments", "identityDocument"):
            kind, num = _text(d, "type"), _text(d, "documentNumber")
            if kind == "Vessel Registration Identification" and imo_of(num):
                imos.append(imo_of(num))
            elif kind == "MMSI" and mmsi_of(num):
                mmsis.append(mmsi_of(num))
        dates = [s.get("datePublished") for s in _all(el, "sanctionsLists", "sanctionsList")
                 if s.get("datePublished")]
        progs = [p.text.strip() for p in _all(el, "sanctionsPrograms", "sanctionsProgram")
                 if p.text and p.text.strip()]
        eid = el.get("id")
        rec = {"source": "ofac", "list": SOURCES["ofac"]["list"], "id": eid, "name": names[0] if names else None,
               "aliases": sorted(set(aliases)), "imo": imos[0] if imos else None, "imos": sorted(set(imos)),
               "mmsi": sorted(set(mmsis)), "flag": (feats.get("Vessel Flag") or [None])[0],
               "callsign": (feats.get("Vessel Call Sign") or [None])[0], "type": (feats.get("VESSEL TYPE") or [None])[0],
               "programme": "; ".join(progs) or None, "date": min(dates) if dates else None,
               "url": OFAC_DETAIL.format(eid) if eid else SOURCES["ofac"]["page"]}
        out.append(rec)
        el.clear()
    return out


def _uk_date(s):
    try:
        return datetime.strptime(s, "%d/%m/%Y").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def uk_regime(name):
    """'The Russia (Sanctions) (EU Exit) Regulations 2019' -> 'Russia (Sanctions) (EU Exit) Regulations 2019'."""
    return re.sub(r"^The\s+", "", (name or "").strip()) or None


def parse_uk_xml(source):
    """UK Sanctions List XML (file path or file object) -> one record per specified ship."""
    out = []
    for _, el in ET.iterparse(source, events=("end",)):
        if _local(el.tag) != "Designation":
            continue
        if (_text(el, "IndividualEntityShip") or "").lower() != "ship":
            el.clear()
            continue
        names, aliases = [], []
        for n in _all(el, "Names", "Name"):
            v = _text(n, "Name6")
            if not v:
                continue
            (names if (_text(n, "NameType") or "").lower().startswith("primary") else aliases).append(v)
        imos, flags, types = [], [], []
        for ship in _all(el, "ShipDetails", "Ship"):
            for i in _all(ship, "IMONumbers", "IMONumber"):
                if imo_of(i.text):
                    imos.append(imo_of(i.text))
            for f in _all(ship, "CurrentBelievedFlagOfShips", "CurrentBelievedFlagOfShip"):
                if f.text and f.text.strip():
                    flags.append(f.text.strip())
            t = _text(ship, "TypeOfShipDetails", "TypeOfShip")
            if t:
                types.append(t)
        uid = _text(el, "UniqueID")
        regime = uk_regime(_text(el, "RegimeName"))
        imos = list(dict.fromkeys(imos))
        rec = {"source": "uk", "list": SOURCES["uk"]["list"], "id": uid, "name": names[0] if names else None,
               "aliases": sorted(set(aliases)), "imo": imos[0] if imos else None, "imos": imos, "mmsi": [],
               "flag": flags[0] if flags else None, "callsign": None, "type": types[0] if types else None,
               "programme": f"{regime}, ref {uid}" if regime and uid else regime or uid,
               "date": _uk_date(_text(el, "DateDesignated")), "url": SOURCES["uk"]["page"]}
        out.append(rec)
        el.clear()
    return out


def merge(records):
    """Group listing records by IMO number. Returns (by_imo, no_imo, by_mmsi)."""
    by_imo, no_imo, by_mmsi = {}, [], {}
    for r in records:
        listing = {k: r[k] for k in ("list", "programme", "date", "url", "id", "name", "flag")}
        if not r["imos"]:
            no_imo.append(dict(listing, mmsi=r["mmsi"], aliases=r["aliases"]))
            continue
        for imo in r["imos"]:
            v = by_imo.setdefault(str(imo), {"imo": imo, "imo_check_digit_ok": imo_check_ok(imo), "names": [], "flags": [],
                                             "mmsi": [], "callsigns": [], "listings": []})
            for n in [r["name"]] + r["aliases"]:
                if n and n not in v["names"]:
                    v["names"].append(n)
            if r["flag"] and r["flag"] not in v["flags"]:
                v["flags"].append(r["flag"])
            for m in r["mmsi"]:
                if m not in v["mmsi"]:
                    v["mmsi"].append(m)
                by_mmsi.setdefault(str(m), [])
                if imo not in by_mmsi[str(m)]:
                    by_mmsi[str(m)].append(imo)
            if r["callsign"] and r["callsign"] not in v["callsigns"]:
                v["callsigns"].append(r["callsign"])
            if listing not in v["listings"]:
                v["listings"].append(listing)
    for v in by_imo.values():
        v["listings"].sort(key=lambda l: (l["list"], l["date"] or ""))
    return by_imo, no_imo, by_mmsi


def download(key, offline=False):
    src = SOURCES[key]
    path = os.path.join(CACHE, src["file"])
    if offline:
        if not os.path.exists(path):
            raise SystemExit(f"{key}: no cached file at {path}; run without --offline first")
        return path
    os.makedirs(CACHE, exist_ok=True)
    tmp = path + ".part"
    req = urllib.request.Request(src["url"], headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    os.replace(tmp, path)
    return path


def published(key, path):
    """The list's own publication date, read from the file header."""
    head = open(path, "rb").read(4096).decode("utf-8", "replace")
    if key == "ofac":
        m = re.search(r"<dataAsOf>(\d{4}-\d{2}-\d{2})", head)
        return m.group(1) if m else None
    m = re.search(r"<DateGenerated>(\d{2}/\d{2}/\d{4})", head)
    return _uk_date(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser(description="Sanctioned vessels from official lists (OFAC SDN, UK Sanctions List)")
    ap.add_argument("--offline", action="store_true", help="reuse cached downloads in data/cache/sanctions/")
    ap.add_argument("--ofac", help="a local OFAC SDN enhanced XML file instead of downloading")
    ap.add_argument("--uk", help="a local UK Sanctions List XML file instead of downloading")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    records, sources = [], []
    for key, parser in (("ofac", parse_ofac_enhanced), ("uk", parse_uk_xml)):
        path = getattr(args, key) or download(key, args.offline)
        recs = parser(path)
        records += recs
        s = {k: v for k, v in SOURCES[key].items() if k != "file"}
        s.update({"id": key, "published": published(key, path), "vessels": len(recs),
                  "with_imo": sum(1 for r in recs if r["imos"])})
        sources.append(s)
        print(f"{key}: {len(recs)} vessel entries, {s['with_imo']} with an IMO number, list dated {s['published']}")
    by_imo, no_imo, by_mmsi = merge(records)
    both = sum(1 for v in by_imo.values() if len({l["list"] for l in v["listings"]}) > 1)
    out = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "sources": sources,
           "by_imo": by_imo, "no_imo": no_imo, "by_mmsi": by_mmsi}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"{len(by_imo)} distinct IMO numbers ({both} on more than one list); {len(no_imo)} entries without IMO -> {args.out}")


if __name__ == "__main__":
    sys.exit(main())
