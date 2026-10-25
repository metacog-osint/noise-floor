#!/usr/bin/env python3
"""vessels_build.py: the public Sea map's vessel data, from Finland's open AIS (Digitraffic) and official sanctions lists.

Inputs
  data/ais/digitraffic/<UTC day>/locations*.parquet, metadata*.parquet   collectors/digitraffic_ais.py (CC BY 4.0)
  data/vessels/sanctioned.json                                           tools/sanctions.py (OFAC SDN, UK Sanctions List)
  --rest   also one snapshot of Digitraffic's REST API (latest position and metadata per vessel; no history)
Outputs (published; the site serves them as they are)
  site/data/vessels/baltic.json       vessels in the categories below, with identifiers, listings, last position,
                                      a thinned 48 h track and the reporting pattern
  site/data/vessels/gnss_at_sea.json  GNSS interference at sea: affected vessels by sea area and the places their
                                      receivers were spoofed to, with no vessel identities
  site/data/vessels/land.json         Natural Earth 10m land minus lakes for the Baltic (public domain; --land rebuilds)

Which vessels (maritime plan Section 12: state and commercial vessels only, no private craft, no crew identities)
  sanctioned              the IMO number the ship broadcasts is on an official list. A listed MMSI is a flagged secondary
                          match when the ship broadcasts no valid IMO; a listed name only annotates a ship already shown
                          for another reason (match "name"), never adds it
  military, law_enforcement   AIS ship type 35 (military operations) or 55 (law enforcement)
  state_flag_of_interest  MMSI country code (MID) of Russia 273, China 412-414, Iran 422 or North Korea 445, for cargo,
                          tanker, tug, towing, passenger, service and other commercial or state types (an unknown type
                          only with a valid IMO number)
  Never output: fishing (30), sailing (36) and pleasure craft (37), and MMSIs that are not ships (ITU-R M.585).
Positions flagged by tools/ais_detect.py's spoofing tests (impossible implied speed, impossible reported speed, 20 km
or more inland), and positions left inside an impossible jump, are kept out of `track` and `last` and counted in
reporting.spoofed_positions.
Track points are [epoch seconds UTC, lat, lon], at most one per 5 minutes, over the 48 h before the newest position.

Usage
  python tools/sanctions.py                     # refresh the sanctions lists first (about 130 MB download)
  python tools/vessels_build.py                 # the latest collected days; a 48 h window ending at the newest position
  python tools/vessels_build.py --days 2026-10-24 2026-10-25 [--rest]
"""
import argparse
import gzip
import json
import os
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import ais_detect as A  # noqa: E402

OUT_DIR = os.path.join(ROOT, "site", "data", "vessels")
SANCTIONED = os.path.join(ROOT, "data", "vessels", "sanctioned.json")
REST = "https://meri.digitraffic.fi/api/ais/v1/"
DIGITRAFFIC = "Source: Fintraffic / digitraffic.fi, license CC 4.0 BY"
WINDOW_H = 48
THIN_S = 300
OUTAGE_S = 300            # no position from any vessel for this long: the collector was down, not the ships
COVERAGE = ("Finnish waters and the approaches: the Gulf of Finland to the approaches of St Petersburg, the Archipelago "
            "Sea and Åland, the Gulf of Bothnia and the northern Baltic Proper, as heard by Fintraffic's shore AIS stations. "
            "No coverage of Kaliningrad, and little or none of Narva Bay; positions far from the Finnish coast are sparse.")

# ITU Maritime Identification Digits (ITU-R M.585 and the ITU MID table) -> ISO 3166-1 alpha-2 of the flag the MMSI claims
MID = {
    201: "AL", 202: "AD", 203: "AT", 204: "PT", 205: "BE", 206: "BY", 207: "BG", 208: "VA", 209: "CY", 210: "CY",
    211: "DE", 212: "CY", 213: "GE", 214: "MD", 215: "MT", 216: "AM", 218: "DE", 219: "DK", 220: "DK", 224: "ES",
    225: "ES", 226: "FR", 227: "FR", 228: "FR", 229: "MT", 230: "FI", 231: "FO", 232: "GB", 233: "GB", 234: "GB",
    235: "GB", 236: "GI", 237: "GR", 238: "HR", 239: "GR", 240: "GR", 241: "GR", 242: "MA", 243: "HU", 244: "NL",
    245: "NL", 246: "NL", 247: "IT", 248: "MT", 249: "MT", 250: "IE", 251: "IS", 252: "LI", 253: "LU", 254: "MC",
    255: "PT", 256: "MT", 257: "NO", 258: "NO", 259: "NO", 261: "PL", 262: "ME", 263: "PT", 264: "RO", 265: "SE",
    266: "SE", 267: "SK", 268: "SM", 269: "CH", 270: "CZ", 271: "TR", 272: "UA", 273: "RU", 274: "MK", 275: "LV",
    276: "EE", 277: "LT", 278: "SI", 279: "RS",
    301: "AI", 303: "US", 304: "AG", 305: "AG", 306: "CW", 307: "AW", 308: "BS", 309: "BS", 310: "BM", 311: "BS",
    312: "BZ", 314: "BB", 316: "CA", 319: "KY", 321: "CR", 323: "CU", 325: "DM", 327: "DO", 329: "GP", 330: "GD",
    331: "GL", 332: "GT", 334: "HN", 336: "HT", 338: "US", 339: "JM", 341: "KN", 343: "LC", 345: "MX", 347: "MQ",
    348: "MS", 350: "NI", 351: "PA", 352: "PA", 353: "PA", 354: "PA", 355: "PA", 356: "PA", 357: "PA", 358: "PR",
    359: "SV", 361: "PM", 362: "TT", 364: "TC", 366: "US", 367: "US", 368: "US", 369: "US", 370: "PA", 371: "PA",
    372: "PA", 373: "PA", 374: "PA", 375: "VC", 376: "VC", 377: "VC", 378: "VG", 379: "VI",
    401: "AF", 403: "SA", 405: "BD", 408: "BH", 410: "BT", 412: "CN", 413: "CN", 414: "CN", 416: "TW", 417: "LK",
    419: "IN", 422: "IR", 423: "AZ", 425: "IQ", 428: "IL", 431: "JP", 432: "JP", 434: "TM", 436: "KZ", 437: "UZ",
    438: "JO", 440: "KR", 441: "KR", 443: "PS", 445: "KP", 447: "KW", 450: "LB", 451: "KG", 453: "MO", 455: "MV",
    457: "MN", 459: "NP", 461: "OM", 463: "PK", 466: "QA", 468: "SY", 470: "AE", 471: "AE", 472: "TJ", 473: "YE",
    475: "YE", 477: "HK", 478: "BA",
    501: "TF", 503: "AU", 506: "MM", 508: "BN", 510: "FM", 511: "PW", 512: "NZ", 514: "KH", 515: "KH", 516: "CX",
    518: "CK", 520: "FJ", 523: "CC", 525: "ID", 529: "KI", 531: "LA", 533: "MY", 536: "MP", 538: "MH", 540: "NC",
    542: "NU", 544: "NR", 546: "PF", 548: "PH", 550: "TL", 553: "PG", 555: "PN", 557: "SB", 559: "AS", 561: "WS",
    563: "SG", 564: "SG", 565: "SG", 566: "SG", 567: "TH", 570: "TO", 572: "TV", 574: "VN", 576: "VU", 577: "VU",
    578: "WF",
    601: "ZA", 603: "AO", 605: "DZ", 607: "TF", 608: "SH", 609: "BI", 610: "BJ", 611: "BW", 612: "CF", 613: "CM",
    615: "CG", 616: "KM", 617: "CV", 618: "TF", 619: "CI", 620: "KM", 621: "DJ", 622: "EG", 624: "ET", 625: "ER",
    626: "GA", 627: "GH", 629: "GM", 630: "GW", 631: "GQ", 632: "GN", 633: "BF", 634: "KE", 635: "TF", 636: "LR",
    637: "LR", 638: "SS", 642: "LY", 644: "LS", 645: "MU", 647: "MG", 649: "ML", 650: "MZ", 654: "MR", 655: "MW",
    656: "NE", 657: "NG", 659: "NA", 660: "RE", 661: "RW", 662: "SD", 663: "SN", 664: "SC", 665: "SH", 666: "SO",
    667: "SL", 668: "ST", 669: "SZ", 670: "TD", 671: "TG", 672: "TN", 674: "TZ", 675: "UG", 676: "CD", 677: "TZ",
    678: "ZM", 679: "ZW",
    701: "AR", 710: "BR", 720: "BO", 725: "CL", 730: "CO", 735: "EC", 740: "FK", 745: "GF", 750: "GY", 755: "PY",
    760: "PE", 765: "SR", 770: "UY", 775: "VE",
}
MID_OF_INTEREST = {273: "RU", 412: "CN", 413: "CN", 414: "CN", 422: "IR", 445: "KP"}
NEVER = {30, 36, 37}                                   # fishing, sailing, pleasure craft: never output
COMMERCIAL_OR_STATE = ({31, 32, 33, 34, 35, 50, 51, 52, 53, 54, 55, 58, 59} | set(range(40, 50)) | set(range(60, 100)))
# Type of electronic position fixing device (EPFD), ITU-R M.1371; Digitraffic's posType. 0 = undefined; 9-14 not used.
POS_FIX = {1: "GPS", 2: "GLONASS", 3: "combined GPS/GLONASS", 4: "Loran-C", 5: "Chayka", 6: "integrated navigation system",
           7: "surveyed", 8: "Galileo", 15: "internal GNSS"}
NAV_STATUS = {0: "under way using engine", 1: "at anchor", 2: "not under command", 3: "restricted manoeuvrability",
              4: "constrained by her draught", 5: "moored", 6: "aground", 7: "engaged in fishing", 8: "under way sailing",
              9: "reserved (HSC)", 10: "reserved (WIG)", 11: "towing astern", 12: "pushing ahead or towing alongside",
              13: "reserved", 14: "AIS-SART, MOB or EPIRB active", 15: "not defined"}


def flag_of(mmsi):
    """ISO2 of the country whose MID begins a ship MMSI (the flag the transponder claims), else None."""
    try:
        m = int(mmsi)
    except (TypeError, ValueError):
        return None
    if A.mmsi_kind(m) != "ship":
        return None
    return MID.get(m // 1_000_000)


def type_label(t):
    """AIS ship and cargo type (ITU-R M.1371 Table 53) in words."""
    if t is None or t <= 0:
        return "not given"
    fixed = {30: "Fishing", 31: "Towing", 32: "Towing (over 200 m long or 25 m wide)", 33: "Dredging or underwater operations",
             34: "Diving operations", 35: "Military operations", 36: "Sailing", 37: "Pleasure craft", 50: "Pilot vessel",
             51: "Search and rescue vessel", 52: "Tug", 53: "Port tender", 54: "Anti-pollution equipment",
             55: "Law enforcement", 56: "Local vessel (spare code)", 57: "Local vessel (spare code)", 58: "Medical transport",
             59: "Non-combatant ship (RR Resolution 18)"}
    if t in fixed:
        return fixed[t]
    base = {2: "Wing in ground", 4: "High-speed craft", 6: "Passenger", 7: "Cargo", 8: "Tanker", 9: "Other type"}.get(t // 10)
    if base is None:
        return f"Reserved code {t}"
    hz = {1: "hazardous category A", 2: "hazardous category B", 3: "hazardous category C", 4: "hazardous category D"}.get(t % 10)
    return f"{base} ({hz})" if hz else base


def categories_for(mmsi, t, imo_ok, sanction_match):
    """Categories a vessel qualifies for (empty: not published). sanction_match is 'imo', 'mmsi', 'name' or None."""
    if A.mmsi_kind(mmsi) != "ship" or t in NEVER:
        return []
    cats = []
    if sanction_match in ("imo", "mmsi"):
        cats.append("sanctioned")
    if t == 35:
        cats.append("military")
    if t == 55:
        cats.append("law_enforcement")
    known = t is not None and t > 0
    if int(mmsi) // 1_000_000 in MID_OF_INTEREST and ((known and t in COMMERCIAL_OR_STATE) or (not known and imo_ok)):
        cats.append("state_flag_of_interest")
    return cats


def pos_fix_label(v):
    """Declared position-fixing device from AIS posType, or None for 0 (undefined), unused codes or no value."""
    try:
        return POS_FIX.get(int(v))
    except (TypeError, ValueError):
        return None


def decode_eta(v):
    """AIS ETA bit field (month bits 19-16, day 15-11, hour 10-6, minute 5-0) -> 'MM-DD HH:MM UTC' or None."""
    if v is None or v <= 0:
        return None
    mo, d, h, mi = (v >> 16) & 0xF, (v >> 11) & 0x1F, (v >> 6) & 0x1F, v & 0x3F
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f"{mo:02d}-{d:02d} " + (f"{h:02d}:{mi:02d} UTC" if h < 24 and mi < 60 else "time not given")


def iso(t):
    return datetime.fromtimestamp(int(t), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------------------------------------- inputs
def latest_meta(days):
    """Latest non-empty value of each metadata field per MMSI (rows in receive order)."""
    t = A.read_kind(days, "metadata")
    out = {}
    if t is None:
        return out
    for r in t.sort_by([("mmsi", "ascending"), ("rx_ms", "ascending")]).to_pylist():
        v = out.setdefault(int(r["mmsi"]), {})
        for k in ("name", "callSign", "destination"):
            s = A.norm_text(r.get(k))
            if s:
                v[k] = s
        for k in ("imo", "type", "draught", "eta", "posType", "refA", "refB", "refC", "refD"):
            x = r.get(k)
            if x is not None and not (k in ("imo", "type", "draught", "eta") and x <= 0):
                v[k] = int(x)
    return out


def rest_snapshot():
    """Digitraffic REST: latest position and metadata per vessel (no history). Returns (location columns, meta dict)."""
    def get(path):
        req = urllib.request.Request(REST + path, headers={"Digitraffic-User": "noise-floor", "Accept-Encoding": "gzip"})
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
            return json.loads(gzip.decompress(raw) if r.headers.get("Content-Encoding") == "gzip" else raw)
    loc = get("locations")
    rx = int(datetime.now(timezone.utc).timestamp() * 1000)
    rows = []
    for f in loc.get("features", []):
        p, (lon, lat) = f.get("properties", {}), f["geometry"]["coordinates"][:2]
        ts = p.get("timestampExternal")
        rows.append((int(f["mmsi"]), int(ts // 1000) if ts else rx // 1000, float(lat), float(lon), float(p.get("sog", 102.3)),
                     float(p.get("cog", 360)), int(p.get("heading", 511)), int(p.get("navStat", 15)), bool(p.get("posAcc")),
                     bool(p.get("raim")), rx))
    keys = ("mmsi", "time", "lat", "lon", "sog", "cog", "heading", "navStat", "posAcc", "raim", "rx_ms")
    cols = {k: np.array([r[i] for r in rows]) for i, k in enumerate(keys)}
    meta = {}
    for v in get("vessels"):
        m = {"name": A.norm_text(v.get("name")), "callSign": A.norm_text(v.get("callSign")),
             "destination": A.norm_text(v.get("destination"))}
        for k, src in (("imo", "imo"), ("type", "shipType"), ("draught", "draught"), ("eta", "eta"), ("posType", "posType"),
                       ("refA", "referencePointA"), ("refB", "referencePointB"), ("refC", "referencePointC"), ("refD", "referencePointD")):
            if v.get(src) is not None and not (k in ("imo", "type", "draught", "eta") and v[src] <= 0):
                m[k] = int(v[src])
        meta[int(v["mmsi"])] = {k: x for k, x in m.items() if x not in ("", None)}
    return cols, meta


def add_rows(L, cols):
    """Append REST positions to the collected arrays, re-sort and drop exact repeats."""
    if not len(cols.get("mmsi", [])):
        return L
    L = {k: np.concatenate([L[k], cols[k].astype(L[k].dtype)]) for k in L}
    o = np.lexsort((L["lon"], L["lat"], L["time"], L["mmsi"]))
    L = {k: v[o] for k, v in L.items()}
    same = np.zeros(len(L["mmsi"]), bool)
    same[1:] = (L["mmsi"][1:] == L["mmsi"][:-1]) & (L["time"][1:] == L["time"][:-1]) & (L["lat"][1:] == L["lat"][:-1])
    return {k: v[~same] for k, v in L.items()}


# ----------------------------------------------------------------------------------------------- analysis
def outages(times, min_s=OUTAGE_S):
    """Intervals (a, b) with no position from any vessel for longer than min_s: collection gaps, not ship behaviour."""
    u = np.unique(times)
    if len(u) < 2:
        return []
    d = np.diff(u)
    return [(int(u[i]), int(u[i + 1])) for i in np.flatnonzero(d > min_s)]


def gap_hours(t, outs):
    """A vessel's reporting gaps in hours, each less any collection outage inside it."""
    out = []
    for a, b in zip(t[:-1], t[1:]):
        if b - a <= 3600:
            continue
        lost = sum(max(0, min(b, ob) - max(a, oa)) for oa, ob in outs)
        out.append((b - a - lost) / 3600)
    return out


def spoof_flags(L, meta_types, use_land=True):
    """ais_detect's tests on every position: impossible implied speed, impossible reported speed, 20 km or more
    inland. Returns (flagged mask, dirty vessel set). meta_types: {mmsi: {'type': t}} as ais_detect expects."""
    stats = {}
    _, suspect, per_vessel = A.d7_speed(L, meta_types, stats)
    _, rs_flag = A.d7_reported_speed(L, meta_types)
    flagged = suspect | rs_flag
    if use_land:
        try:
            depth = A.land_depth(L, A.LandMask())
            flagged = flagged | (depth >= 20)
        except Exception as e:                          # the tracks still work without the land test
            print(f"land mask unavailable: {e}", file=sys.stderr)
    dirty = {m for m, v in per_vessel.items() if v["excursions"]} | set(int(m) for m in np.unique(L["mmsi"][rs_flag]))
    return flagged, dirty


def thin_track(t, lat, lon, step=THIN_S):
    """One point per `step`-second UTC bin: the first in each bin, except the newest point in the last bin."""
    if len(t) == 0:
        return []
    b = t // step
    keep = np.ones(len(t), bool)
    keep[1:] = b[1:] != b[:-1]
    keep[b == b[-1]] = False
    keep[-1] = True
    return [[int(t[i]), round(float(lat[i]), 4), round(float(lon[i]), 4)] for i in np.flatnonzero(keep)]


def sanction_lookup(mmsi, imo, name, t, san):
    """(match kind, listing records) for one vessel against data/vessels/sanctioned.json."""
    by_imo, by_mmsi = san.get("by_imo", {}), san.get("by_mmsi", {})
    imo_ok = A.imo_valid(imo) if imo else False
    if imo and str(imo) in by_imo:
        return "imo", by_imo[str(imo)]["listings"]
    if not imo_ok and str(mmsi) in by_mmsi:
        ls = [l for i in by_mmsi[str(mmsi)] for l in by_imo.get(str(i), {}).get("listings", [])]
        if ls:
            return "mmsi", ls
    if not imo_ok and name and t is not None and 70 <= t <= 89:
        key = " ".join(name.upper().split())
        ls = [l for v in by_imo.values() if key in (" ".join(n.upper().split()) for n in v["names"]) for l in v["listings"]]
        if ls:
            return "name", ls
    return None, []


def jump_spans(t, lat, lon, ok, typ):
    """Positions left after the spoofing tests that still sit in an impossible jump (ais_detect.walk_track's 'jump'
    excursions, which it does not flag because the track continues from the new place). Returns a mask over t."""
    out = np.zeros(len(t), bool)
    idx = np.flatnonzero(ok)
    if len(idx) < 2:
        return out
    sus, exc = A.walk_track(t[idx], lat[idx], lon[idx], A.speed_limit_kn(typ))
    bad = sus.copy()
    for x in exc:
        if x["kind"] == "jump":
            bad[x["i0"]:x["i1"] + 1] = True
    out[idx[bad]] = True
    return out


def vessel_record(m, s, e, L, flagged, meta, cats, match, listings, outs):
    t, lat, lon = L["time"][s:e], L["lat"][s:e], L["lon"][s:e]
    v = meta.get(m, {})
    typ = v.get("type")
    f = flagged[s:e].copy()
    f |= jump_spans(t, lat, lon, ~f, typ)
    ok = ~f
    imo = v.get("imo")
    cls = "A" if (imo or v.get("destination") or v.get("eta") or v.get("draught")) else None
    last = {"t": None, "lat": None, "lon": None, "sog": None, "cog": None, "heading": None, "nav_status": None}
    if ok.any():
        i = s + int(np.flatnonzero(ok)[-1])
        sog, cog, hd, ns = float(L["sog"][i]), float(L["cog"][i]), int(L["heading"][i]), int(L["navStat"][i])
        last = {"t": iso(L["time"][i]), "lat": round(float(L["lat"][i]), 5), "lon": round(float(L["lon"][i]), 5),
                "sog": round(sog, 1) if sog < A.SOG_NA else None, "cog": round(cog, 1) if cog < 360 else None,
                "heading": hd if hd < 360 else None, "nav_status": NAV_STATUS.get(ns, "not defined")}
    gaps = gap_hours(t, outs)
    dims = None
    if any(v.get(k) for k in ("refA", "refB", "refC", "refD")):
        dims = {"length_m": (v.get("refA") or 0) + (v.get("refB") or 0) or None,
                "beam_m": (v.get("refC") or 0) + (v.get("refD") or 0) or None}
    return {
        "mmsi": int(m), "imo": imo, "name": v.get("name"), "callsign": v.get("callSign"), "flag": flag_of(m),
        "ais_type": typ, "ais_type_label": type_label(typ), "ais_class": cls, "categories": cats,
        "listings": [{"list": l["list"], "programme": l["programme"], "date": l["date"], "url": l["url"], "match": match}
                     for l in listings],
        "last": last,
        "track": thin_track(t[ok], lat[ok], lon[ok]),
        "reporting": {
            "positions": int(e - s), "first_seen": iso(t[0]), "last_seen": iso(t[-1]),
            "median_interval_s": round(float(np.median(np.diff(t))), 1) if e - s > 1 else None,
            "gaps_over_1h": int(sum(1 for g in gaps if g > 1)), "longest_gap_h": round(max([g for g in gaps if g > 1], default=0.0), 2),
            "spoofed_positions": int(f.sum()),
            "pos_accuracy_high_share": round(float(L["posAcc"][s:e].mean()), 2),
            "raim_share": round(float(L["raim"][s:e].mean()), 2)},
        "signals": {"ais_class": cls, "destination": v.get("destination"), "eta": decode_eta(v.get("eta")),
                    "draught": round(v["draught"] / 10, 1) if v.get("draught") else None, "dimensions": dims,
                    "imo_check_digit_ok": A.imo_valid(imo) if imo else None, "pos_fix_device": pos_fix_label(v.get("posType"))},
    }


def gnss_aggregate(L, meta_types, flagged, dirty, t0, t1, outs):
    """GNSS interference at sea with no identities: vessels by the sea area of their trusted positions, the centres
    their receivers were spoofed to, and vessels per hour."""
    vic = [v for v in A.spoof_victims(L, meta_types, flagged, dirty) if v["reading"] == "GNSS interference likely"]
    boxes = dict(A.REGIONS)
    area = Counter((v.get("before") or v.get("after") or {}).get("region", "No trusted position") for v in vic)
    to = Counter((round(v["flagged_center"][0], 1), round(v["flagged_center"][1], 1)) for v in vic
                 if (v["displacement_km"] or 0) > 50 or (v.get("before") is None and v.get("after") is None))
    vset = {v["mmsi"] for v in vic}
    sel = flagged & np.isin(L["mmsi"], np.array(sorted(vset), dtype=L["mmsi"].dtype))
    hrs = (L["time"][sel] // 3600) * 3600
    by_hour = [{"t": iso(h), "vessels": int(len(np.unique(L["mmsi"][sel][hrs == h])))} for h in np.unique(hrs)]
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window": {"start": iso(t0), "end": iso(t1)},
        "rules_version": A.RULES_VERSION,
        "sources": [DIGITRAFFIC],
        "coverage": COVERAGE,
        "collection_gaps": [{"start": iso(a), "end": iso(b)} for a, b in outs],
        "affected_vessels": len(vic),
        "by_area": [{"area": k, "box": list(boxes[k]) if k in boxes else None, "vessels": n} for k, n in area.most_common()],
        "spoofed_to": [{"lat": a, "lon": b, "vessels": n} for (a, b), n in to.most_common()],
        "by_hour": by_hour,
        "method": "Vessels with position reports that need an impossible speed, report an impossible speed over ground, or "
                  "sit 20 km or more inland, and whose reports show GNSS-derived speed or course detached from the ship "
                  "(tools/ais_detect.py, 'GNSS interference likely'). Areas are where their last trusted positions were; "
                  "spoofed-to centres are the median of their flagged positions, rounded to 0.1 degree.",
    }


# ----------------------------------------------------------------------------------------------- land layer
def write_land(path, clip=(9.0, 53.0, 35.0, 67.5), tol=0.004, min_area=0.0004):
    """Natural Earth 10m land minus 10m lakes, clipped to the Baltic, simplified (public domain)."""
    import shapely
    from shapely.geometry import box, mapping, shape
    c = box(*clip)
    land = [shapely.make_valid(shape(f["geometry"])).intersection(c) for f in A.natural_earth("ne_10m_land")["features"]
            if shape(f["geometry"]).intersects(c)]
    lakes = [shapely.make_valid(shape(f["geometry"])).intersection(c) for n in ("ne_10m_lakes", "ne_10m_lakes_europe")
             for f in A.natural_earth(n)["features"] if shape(f["geometry"]).intersects(c)]
    g = shapely.union_all(land)
    if lakes:
        g = g.difference(shapely.union_all(lakes))
    g = shapely.simplify(g, tol, preserve_topology=True)
    polys = [p for p in getattr(g, "geoms", [g]) if p.geom_type == "Polygon" and p.area >= min_area]
    rnd = lambda ring: [[round(x, 3), round(y, 3)] for x, y in ring.coords]
    feats = [{"type": "Feature", "properties": {},
              "geometry": {"type": "Polygon", "coordinates": [rnd(p.exterior)] + [rnd(r) for r in p.interiors if shapely.Polygon(r).area >= min_area]}}
             for p in polys]
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"type": "FeatureCollection", "source": "Natural Earth 10m land minus lakes (public domain), simplified",
                   "features": feats}, fh, separators=(",", ":"))
    return len(feats)


# ----------------------------------------------------------------------------------------------- main
def build(L, meta, san, use_land=True):
    """Everything from loaded positions (ais_detect arrays) and latest metadata. Returns (baltic, gnss)."""
    t1 = int(L["time"].max())
    t0 = t1 - WINDOW_H * 3600
    keep = L["time"] >= t0
    L = {k: v[keep] for k, v in L.items()}
    meta_types = {m: {"type": v.get("type"), "imo": v.get("imo"), "name": v.get("name")} for m, v in meta.items()}
    flagged, dirty = spoof_flags(L, meta_types, use_land)
    outs = outages(L["time"])
    vessels = []
    for m, s, e in A.vessel_slices(L["mmsi"]):
        v = meta.get(m, {})
        typ, imo = v.get("type"), v.get("imo")
        match, listings = sanction_lookup(m, imo, v.get("name"), typ, san)
        cats = categories_for(m, typ, A.imo_valid(imo) if imo else False, match)
        if not cats:
            continue
        vessels.append(vessel_record(m, s, e, L, flagged, meta, cats, match, listings, outs))
    order = {"sanctioned": 0, "military": 1, "law_enforcement": 1, "state_flag_of_interest": 2}
    vessels.sort(key=lambda x: (min(order[c] for c in x["categories"]), x["name"] or "~", x["mmsi"]))
    span = f"{iso(int(L['time'].min()))} to {iso(t1)}"
    gaps = "; ".join(f"{iso(a)[:16]}Z to {iso(b)[:16]}Z" for a, b in outs)
    src = [DIGITRAFFIC] + [f"{s['attribution']}, list dated {s['published']}" for s in san.get("sources", [])]
    baltic = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "coverage": f"{COVERAGE} Positions collected {span} (UTC)." + (f" Collection gaps: {gaps}." if gaps else ""),
              "sources": src, "vessels": vessels}
    gnss = gnss_aggregate(L, meta_types, flagged, dirty, int(L["time"].min()), t1, outs)
    return baltic, gnss


def main():
    ap = argparse.ArgumentParser(description="Sea map vessel data from Digitraffic AIS and official sanctions lists")
    ap.add_argument("--days", nargs="*", help="UTC day folders to read (default: the latest 3 collected)")
    ap.add_argument("--rest", action="store_true", help="also add one Digitraffic REST snapshot (latest positions and metadata)")
    ap.add_argument("--no-land", action="store_true", help="skip the inland-position test (no Natural Earth)")
    ap.add_argument("--land", action="store_true", help="rebuild site/data/vessels/land.json")
    ap.add_argument("--out", default=OUT_DIR)
    args = ap.parse_args()
    days = args.days or A.days_available()[-3:]
    if not days:
        raise SystemExit("no collected AIS days in data/ais/digitraffic/")
    if not os.path.exists(SANCTIONED):
        raise SystemExit("data/vessels/sanctioned.json missing: run tools/sanctions.py first")
    san = json.load(open(SANCTIONED, encoding="utf-8"))
    L, load_stats, _ = A.load_locations(days)
    meta = latest_meta(days)
    if args.rest:
        cols, rmeta = rest_snapshot()
        L = add_rows(L, cols)
        for m, v in rmeta.items():
            meta[m] = {**v, **meta.get(m, {})}         # collected metadata wins; REST fills what is missing
    baltic, gnss = build(L, meta, san, use_land=not args.no_land)
    os.makedirs(args.out, exist_ok=True)
    for name, obj in (("baltic.json", baltic), ("gnss_at_sea.json", gnss)):
        with open(os.path.join(args.out, name), "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    if args.land or not os.path.exists(os.path.join(args.out, "land.json")):
        print("land polygons:", write_land(os.path.join(args.out, "land.json")))
    cats = Counter(c for v in baltic["vessels"] for c in v["categories"])
    flags = Counter(v["flag"] or "?" for v in baltic["vessels"])
    print(f"days {days[0]}..{days[-1]}: {load_stats['rows']:,} positions; {len(baltic['vessels'])} vessels published")
    print("  by category:", dict(cats))
    print("  by flag:", dict(flags.most_common()))
    print(f"  GNSS interference at sea: {gnss['affected_vessels']} vessels; areas {[(a['area'], a['vessels']) for a in gnss['by_area']]}")
    print("  wrote", ", ".join(os.path.join(args.out, n) for n in ("baltic.json", "gnss_at_sea.json", "land.json")))


if __name__ == "__main__":
    main()
