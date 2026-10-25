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
  by_imo {"<imo>": {imo, names, flags, mmsi, callsigns, listings [{list, programme, date, url, id, name, flag}],
                    owners [{name, role, country, list, ref}]}},
  no_imo [listings without an IMO number], by_mmsi {"<mmsi>": [imo, ...]} (OFAC only; a secondary match)
Owners: OFAC links each vessel to entities by "Owned or Controlled By" and "Property in the interest of"; the owner's
country is the country of its own SDN address (most common if several). The UK list gives "current owner/operator"
names only; their country comes from an exact name match to an entity designated on the UK list, then on the SDN list,
when that entity has an address. Individuals linked to vessels are never output (counted only).
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


# Country names as the lists write them -> ISO 3166-1 alpha-2. Base table: tzdata's iso3166.tab (a requirement already);
# these aliases cover the names it spells differently.
COUNTRY_ALIASES = {
    "bahamas, the": "BS", "burma": "MM", "myanmar": "MM", "congo": "CG", "congo (democratic republic)": "CD",
    "congo, democratic republic of the": "CD", "congo, republic of the": "CG", "democratic republic of the congo": "CD",
    "cote d ivoire": "CI", "cote d'ivoire": "CI", "curacao": "CW", "dprk": "KP", "korea, north": "KP", "north korea": "KP",
    "korea, south": "KR", "south korea": "KR", "kosovo": "XK", "man, isle of": "IM", "north macedonia, the republic of": "MK",
    "occupied palestinian territories": "PS", "palestinian": "PS", "west bank": "PS", "region: northern mali": "ML",
    "saint kitts and nevis": "KN", "saint vincent and the grenadines": "VC", "st vincent and the grenadines": "VC",
    "samoa": "WS", "the gambia": "GM", "gambia, the": "GM", "united kingdom": "GB", "uk": "GB", "virgin islands, british": "VG",
    "british virgin islands": "VG", "central african republic": "CF", "russian federation": "RU", "united states of america": "US",
    "usa": "US", "turkiye": "TR", "t\u00fcrkiye": "TR", "viet nam": "VN", "macao": "MO", "hong kong sar": "HK",
    "iran (islamic republic of)": "IR", "syrian arab republic": "SY", "lao pdr": "LA", "tanzania, united republic of": "TZ",
    "micronesia, federated states of": "FM", "brunei darussalam": "BN", "cabo verde": "CV", "eswatini": "SZ",
    "democratic people's republic of korea": "KP", "democratic people\u2019s republic of korea": "KP",
    "st. kitts and nevis": "KN", "st kitts and nevis": "KN", "republic of palau": "PW", "sint maarten": "SX",
    "st. vincent and grenadines": "VC", "st vincent and grenadines": "VC", "saint vincent and grenadines": "VC",
}
_COUNTRIES = None


def country_iso2(name):
    """ISO2 for a country name as written in the lists, else None."""
    global _COUNTRIES
    if not name:
        return None
    if _COUNTRIES is None:
        _COUNTRIES = {}
        try:
            import importlib.resources
            tab = importlib.resources.files("tzdata").joinpath("zoneinfo/iso3166.tab").read_text(encoding="utf-8")
            for line in tab.splitlines():
                if line and not line.startswith("#") and "\t" in line:
                    code, nm = line.split("\t", 1)
                    _COUNTRIES[nm.strip().lower().replace("&", "and")] = code.strip()
        except Exception:                               # no tzdata: aliases only
            pass
        _COUNTRIES.update(COUNTRY_ALIASES)
    key = " ".join(str(name).strip().lower().replace("&", "and").split())
    return _COUNTRIES.get(key)


def listed_flag(name):
    """ISO2 for a vessel flag as a list gives it, or None when the list marks it false ('Mozambique (False)'),
    unknown or none identified, or the name isn't recognised."""
    if not name or "false" in str(name).lower():
        return None
    return country_iso2(name)


def is_iso2(code):
    """True for an ISO 3166-1 alpha-2 code in the country table."""
    country_iso2("x")                                   # loads the table
    return bool(code) and code.upper() in set(_COUNTRIES.values())


def norm_name(s):
    """Company names compared across lists: upper case, punctuation dropped."""
    return re.sub(r"[^A-Z0-9]+", " ", str(s or "").upper()).strip()


def _main_country(names):
    """The most common ISO2 among address country names (first seen wins a tie), else None."""
    codes = [c for c in (country_iso2(n) for n in names) if c]
    if not codes:
        return None
    return max(dict.fromkeys(codes), key=codes.count)


OFAC_OWNER_ROLES = {"Owned or Controlled By": "owner or controller", "Property in the interest of": "property in the interest of"}


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


def _ofac_primary_name(el):
    for n in _all(el, "names", "name"):
        if _text(n, "isPrimary") == "true":
            for tr in _all(n, "translations", "translation"):
                if _text(tr, "formattedFullName"):
                    return _text(tr, "formattedFullName")
    return None


def parse_ofac_enhanced(source, names_index=None):
    """OFAC SDN enhanced XML (file path or file object) -> one record per vessel entry, owners resolved through the
    entry's relationships. names_index, if given, is filled with normalised entity name -> ISO2 of its address."""
    out, ents = [], {}
    for _, el in ET.iterparse(source, events=("end",)):
        if _local(el.tag) != "entity":
            continue
        etype = _text(el, "generalInfo", "entityType")
        if etype != "Vessel":
            nm = _ofac_primary_name(el)
            country = _main_country([_text(a, "country") for a in _all(el, "addresses", "address") if _text(a, "country")])
            ents[el.get("id")] = (etype, nm, country)
            if names_index is not None and etype == "Entity" and nm and country:
                names_index.setdefault(norm_name(nm), country)
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
        rels = []
        for r in _all(el, "relationships", "relationship"):
            rel = _kid(r, "relatedEntity")
            if rel is not None and _text(r, "type") in OFAC_OWNER_ROLES:
                rels.append((OFAC_OWNER_ROLES[_text(r, "type")], rel.get("entityId"), (rel.text or "").strip()))
        rec = {"source": "ofac", "list": SOURCES["ofac"]["list"], "id": eid, "name": names[0] if names else None,
               "aliases": sorted(set(aliases)), "imo": imos[0] if imos else None, "imos": sorted(set(imos)),
               "mmsi": sorted(set(mmsis)), "flag": (feats.get("Vessel Flag") or [None])[0],
               "callsign": (feats.get("Vessel Call Sign") or [None])[0], "type": (feats.get("VESSEL TYPE") or [None])[0],
               "programme": "; ".join(progs) or None, "date": min(dates) if dates else None,
               "url": OFAC_DETAIL.format(eid) if eid else SOURCES["ofac"]["page"], "_rels": rels, "owners": [],
               "individual_owners": 0}
        out.append(rec)
        el.clear()
    for rec in out:                                     # related entities can come later in the file than the vessel
        for role, rid, rname in rec.pop("_rels"):
            etype, nm, country = ents.get(rid, (None, rname, None))
            if etype == "Individual":                   # people are never output (maritime plan Section 12)
                rec["individual_owners"] += 1
                continue
            o = {"name": nm or rname, "role": role, "country": country, "list": SOURCES["ofac"]["list"], "ref": rid}
            if o["name"] and o not in rec["owners"]:
                rec["owners"].append(o)
    return out


def _uk_date(s):
    try:
        return datetime.strptime(s, "%d/%m/%Y").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def uk_regime(name):
    """'The Russia (Sanctions) (EU Exit) Regulations 2019' -> 'Russia (Sanctions) (EU Exit) Regulations 2019'."""
    return re.sub(r"^The\s+", "", (name or "").strip()) or None


def parse_uk_xml(source, names_index=None):
    """UK Sanctions List XML (file path or file object) -> one record per specified ship, with its current
    owner/operator names. names_index, if given, is filled with normalised entity name -> ISO2 of its address."""
    out = []
    for _, el in ET.iterparse(source, events=("end",)):
        if _local(el.tag) != "Designation":
            continue
        kind = (_text(el, "IndividualEntityShip") or "").lower()
        if kind == "entity" and names_index is not None:
            c = _main_country([_text(a, "AddressCountry") for a in _all(el, "Addresses", "Address") if _text(a, "AddressCountry")])
            if c:
                for n in _all(el, "Names", "Name"):
                    if _text(n, "Name6"):
                        names_index.setdefault(norm_name(_text(n, "Name6")), c)
        if kind != "ship":
            el.clear()
            continue
        names, aliases = [], []
        for n in _all(el, "Names", "Name"):
            v = _text(n, "Name6")
            if not v:
                continue
            (names if (_text(n, "NameType") or "").lower().startswith("primary") else aliases).append(v)
        imos, flags, types, owners = [], [], [], []
        for ship in _all(el, "ShipDetails", "Ship"):
            for o in _all(ship, "CurrentOwnerOperators", "CurrentOwnerOperator"):
                if o.text and o.text.strip() and o.text.strip() not in owners:
                    owners.append(o.text.strip())
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
               "date": _uk_date(_text(el, "DateDesignated")), "url": SOURCES["uk"]["page"],
               "owners": [{"name": o, "role": "owner/operator", "country": None, "list": SOURCES["uk"]["list"], "ref": uid}
                          for o in owners], "individual_owners": 0}
        out.append(rec)
        el.clear()
    if names_index is not None:
        fill_owner_countries(out, names_index)
    return out


def fill_owner_countries(records, *indexes):
    """Owners without a country take it from the first index (normalised name -> ISO2) that has their exact name."""
    for r in records:
        for o in r.get("owners", []):
            if o["country"]:
                continue
            for idx in indexes:
                c = idx.get(norm_name(o["name"]))
                if c:
                    o["country"] = c
                    break


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
                                             "mmsi": [], "callsigns": [], "listings": [], "owners": []})
            for o in r.get("owners", []):
                if o not in v["owners"]:
                    v["owners"].append(dict(o))
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
    index = {"ofac": {}, "uk": {}}
    for key, parser in (("ofac", parse_ofac_enhanced), ("uk", parse_uk_xml)):
        path = getattr(args, key) or download(key, args.offline)
        recs = parser(path, index[key])
        records += recs
        s = {k: v for k, v in SOURCES[key].items() if k != "file"}
        s.update({"id": key, "published": published(key, path), "vessels": len(recs),
                  "with_imo": sum(1 for r in recs if r["imos"])})
        sources.append(s)
        print(f"{key}: {len(recs)} vessel entries, {s['with_imo']} with an IMO number, list dated {s['published']}")
    fill_owner_countries(records, index["uk"], index["ofac"])
    by_imo, no_imo, by_mmsi = merge(records)
    ow = [v for v in by_imo.values() if v["owners"]]
    print(f"owners: {len(ow)} of {len(by_imo)} IMO numbers have an owner; {sum(1 for v in ow if any(o['country'] for o in v['owners']))} "
          f"with an owner country; {sum(r['individual_owners'] for r in records)} links to individuals left out")
    both = sum(1 for v in by_imo.values() if len({l["list"] for l in v["listings"]}) > 1)
    out = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "sources": sources,
           "by_imo": by_imo, "no_imo": no_imo, "by_mmsi": by_mmsi}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"{len(by_imo)} distinct IMO numbers ({both} on more than one list); {len(no_imo)} entries without IMO -> {args.out}")


if __name__ == "__main__":
    sys.exit(main())
