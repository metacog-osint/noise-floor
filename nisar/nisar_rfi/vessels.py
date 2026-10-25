"""Private vessel page for the private watch site: AIS vessels of interest with their identifiers, reporting
patterns and tracks, plus NISAR emitter detections near them. PRIVATE OUTPUT ONLY.

Why it lives here: the private site is assembled by view.build() and deployed by view.deploy() (Cloudflare Pages
behind Access, noindex/no-store headers). Adding the vessel page as a module of the same package reuses that one
build-and-deploy path instead of a second site, and the NISAR outputs it joins are already loaded here.

Inputs (all private or gitignored; nothing here is published):
  data/ais/aisstream/<day>/locations*.parquet, metadata*.parquet    collectors/aisstream_ais.py (no published terms)
  data/ais/digitraffic/<day>/locations*.parquet, metadata*.parquet  collectors/digitraffic_ais.py (CC BY 4.0)
  private/watch/maritime.json   vessel_watch.vessels (watch list, with reasons) and optional flags_of_interest
  data/vessels/sanctioned.json  official sanctions listings (tools/sanctions.py: OFAC SDN and the UK Sanctions List)
  <nisar state_dir>/state.json  NISAR detections (lat, lon, start) for "near" context

Per-vessel records come from tools/vessels_build.py's own vessel_record() (the public vessel tab's builder), so the
shared keys mean exactly the same on both pages: mmsi, imo, name, callsign, flag, ais_type, ais_type_label, ais_class,
categories, listings (with match: imo, mmsi or name), last, track ([epoch s UTC, lat, lon], one per 5 min), reporting,
signals (with pos_fix_device). Spoofing flags are vessels_build.spoof_flags() (ais_detect D7 implied and reported speed,
plus impossible jumps); its 20 km inland test is applied only inside ais_detect's land-mask area (the Baltic).
Private extras: emitters_near, private_notes, identities, category_basis, sources, suspect_positions, seen,
pos_unavailable. ais_class uses the AIS message numbers aisstream gives (1-3/5 = A, 18/19/24 = B) when known.

Private categories (the public tab's rules are narrower):
  sanctioned              as public: the broadcast IMO is listed; a listed MMSI only when no valid IMO is broadcast
                          (unconfirmed); a listed name never adds a ship, it only annotates one shown for another reason
  military, law_enforcement   AIS type 35 / 55, or a navy / coast-guard name pattern (marked "check")
  state_flag_of_interest  MMSI flag in FLAGS_OF_INTEREST (or the private override), any type except sailing and
                          pleasure craft: fishing types and unknown types without an IMO count here (maritime militia
                          often look like that). Being listed is not an allegation of anything
  watch_list              the private watch list (by MMSI or IMO); watched IMOs not seen are listed as not seen
  gnss_victim             at least GNSS_MIN suspect positions
  emitters_near           NISAR detections on the same UTC day within NEAR_KM of the vessel's accepted positions that
                          day: proximity only, never attribution ("near", not "from")
No private craft: AIS type 37 is left out, and type 36 unless it has a valid IMO, except vessels on a sanctions listing
or the watch list; non-ship MMSIs are left out; unidentified class B stations stay out of the traffic layer. Nothing
about crews is used. The page embeds Natural Earth land and uses no map tiles, so viewing it tells no tile server
where we look.
"""
import glob
import gzip
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
AIS_DIRS = {"aisstream": os.path.join(REPO, "data", "ais", "aisstream"),
            "digitraffic": os.path.join(REPO, "data", "ais", "digitraffic")}
WATCH_CONFIG = os.path.join(REPO, "private", "watch", "maritime.json")
SANCTIONED = os.path.join(REPO, "data", "vessels", "sanctioned.json")
DEFAULT_OUT = os.path.join(REPO, "private", "maritime", "vessels")
SOURCE_NOTES = {"aisstream": "aisstream.io (no published terms: private use only, never publish)",
                "digitraffic": "Source: Fintraffic / digitraffic.fi, license CC 4.0 BY"}
FLAGS_OF_INTEREST = ("RU", "CN", "IR", "KP")     # override with "flags_of_interest" in the private maritime config
NEAR_KM = 50.0
GNSS_MIN = 3
CAT_ORDER = ["sanctioned", "military", "law_enforcement", "watch_list", "gnss_victim", "state_flag_of_interest"]
MILITARY_NAME = re.compile(r"\bWARSHIP\b|\bNAVY\b|\bNAVAL\b|^(HMS|USNS|USS|HMAS|HMCS|HMNZS|RFS|INS|KRI|BRP|ROKS|JS)\s")
LAW_NAME = re.compile(r"COAST\s?GUARD|\bHAI\s?JING\b|^CCG\b|BORDER\s?GUARD|\bHAI\s?XUN\b|\bPOLICE\b")
LISTING_KEYS = ("list", "programme", "date", "url")


def _tools():
    """(tools/ais_detect.py, tools/vessels_build.py), imported lazily."""
    tools = os.path.join(REPO, "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import ais_detect
    import vessels_build
    return ais_detect, vessels_build


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(a, dtype=float)) for a in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(np.minimum(a, 1.0)))


def iso(t):
    return datetime.fromtimestamp(float(t), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm(s):
    return " ".join(str(s).replace("@", " ").split()).upper() if s is not None else ""


def _num_id(v, lo, hi):
    try:
        x = int(str(v).upper().replace("IMO", "").strip()) if v is not None else None
    except ValueError:
        return None
    return x if x is not None and lo <= x <= hi else None


# ----------------------------------------------------------------------------------------------- private inputs
def load_watch(path=WATCH_CONFIG):
    """(entries by MMSI, entries by IMO, flags of interest) from the private maritime config."""
    try:
        cfg = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    by_m, by_i = {}, {}
    for v in (cfg.get("vessel_watch") or {}).get("vessels", []):
        if not isinstance(v, dict):
            continue
        m, i = _num_id(v.get("mmsi"), 1, 999_999_999), _num_id(v.get("imo"), 1_000_000, 9_999_999)
        if m:
            by_m[m] = v
        if i:
            by_i[i] = v
    flags = tuple(str(f).upper() for f in cfg.get("flags_of_interest", FLAGS_OF_INTEREST))
    return by_m, by_i, flags


def load_sanctions(path=SANCTIONED):
    """data/vessels/sanctioned.json as written by tools/sanctions.py ({} if missing), and whether it loaded."""
    try:
        d = json.load(open(path, encoding="utf-8"))
        return (d if isinstance(d, dict) else {}), isinstance(d, dict)
    except (OSError, ValueError):
        return {}, False


def load_detections(cfg, days):
    """NISAR detections (not ignored) on the window days: [{id, site, t, lat, lon, ...}]."""
    if not cfg or not cfg.get("state_dir"):
        return []
    try:
        st = json.load(open(os.path.join(cfg["state_dir"], "state.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return []
    days = set(days)
    out = []
    for d in st.get("detections", []):
        if d.get("ignored") or d.get("lat") is None or not d.get("start") or d["start"][:10] not in days:
            continue
        out.append({"id": d.get("id"), "site": d.get("site"), "t": d["start"], "lat": round(float(d["lat"]), 4),
                    "lon": round(float(d["lon"]), 4), "confidence": d.get("confidence"), "method": d.get("method"),
                    "band_text": d.get("band_text"), "where": d.get("where")})
    return out


# ----------------------------------------------------------------------------------------------- AIS reading
def days_available(dirs=None):
    out = set()
    for d in (dirs or AIS_DIRS).values():
        out |= {os.path.basename(p) for p in glob.glob(os.path.join(d, "????-??-??")) if os.path.isdir(p)}
    return sorted(out)


def _files(d, day, kind):
    return sorted(glob.glob(os.path.join(d, day, f"{kind}*.parquet")))


def read_metadata(dirs, days):
    """Per MMSI: latest static fields (vessels_build's key names), distinct identity values with counts, AIS message
    numbers seen, and sources."""
    import pyarrow.parquet as pq
    rows = []
    for src, d in dirs.items():
        for day in days:
            for p in _files(d, day, "metadata"):
                try:
                    t = pq.read_table(p)
                except Exception:
                    continue
                for r in t.to_pylist():
                    r["_src"] = src
                    rows.append(r)
    rows.sort(key=lambda r: (r.get("mmsi") or 0, r.get("rx_ms") or 0))
    meta = {}
    for r in rows:
        m = r.get("mmsi")
        if not m:
            continue
        v = meta.setdefault(m, {"hist": defaultdict(Counter), "msg_ids": set(), "sources": set()})
        v["sources"].add(r["_src"])
        if r.get("msg_id"):
            v["msg_ids"].add(int(r["msg_id"]))
        for k in ("name", "callSign", "destination"):
            s = _norm(r.get(k))
            if s:
                v[k] = s
                if k != "destination":
                    v["hist"][k][s] += 1
        for k in ("imo", "type"):
            if r.get(k):
                v[k] = int(r[k])
                v["hist"][k][int(r[k])] += 1
        for k in ("draught", "eta", "posType", "refA", "refB", "refC", "refD"):    # vessels_build.latest_meta's rule
            x = r.get(k)
            if x is not None and not (k in ("draught", "eta") and x <= 0):
                v[k] = int(x)
    return meta


_LCOLS = ("mmsi", "time", "lat", "lon", "sog", "cog", "heading", "navStat", "posAcc", "raim", "rx_ms")


def read_day_locations(dirs, day):
    """One UTC day's positions from every source as numpy arrays (src = index in dirs), or None."""
    import pyarrow.parquet as pq
    parts = []
    for si, (src, d) in enumerate(dirs.items()):
        for p in _files(d, day, "locations"):
            try:
                names = set(pq.read_schema(p).names)
                t = pq.read_table(p, columns=[c for c in _LCOLS + ("msg_id",) if c in names])
            except Exception:
                continue
            n = t.num_rows
            if not n:
                continue
            a = {c: (t.column(c).to_numpy(zero_copy_only=False) if c in names else np.full(n, None, dtype=object))
                 for c in _LCOLS}
            a["msg_id"] = (np.nan_to_num(np.asarray(t.column("msg_id").to_numpy(zero_copy_only=False), dtype=float),
                                         nan=-1).astype(np.int16) if "msg_id" in names else np.full(n, -1, np.int16))
            a["src"] = np.full(n, si, np.int8)
            parts.append(a)
    if not parts:
        return None
    L = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
    L["mmsi"] = L["mmsi"].astype(np.int64)
    tm = np.asarray(L["time"], dtype=float)
    L["time"] = np.where(np.isfinite(tm) & (tm > 0), tm, np.asarray(L["rx_ms"], float) // 1000).astype(np.int64)
    for k in ("lat", "lon", "sog", "cog"):
        L[k] = np.asarray(L[k], dtype=float)
    L["heading"] = np.nan_to_num(np.asarray(L["heading"], dtype=float), nan=511).astype(np.int16)
    L["navStat"] = np.nan_to_num(np.asarray(L["navStat"], dtype=float), nan=15).astype(np.int8)   # 15: not defined
    for k in ("posAcc", "raim"):
        x = L[k]
        L[k] = np.array([bool(v) if v is not None else False for v in x]) if x.dtype == object else x.astype(bool)
    del L["rx_ms"]
    return L


def _split_invalid(L):
    bad = (~np.isfinite(L["lat"]) | ~np.isfinite(L["lon"]) | (np.abs(L["lat"]) > 90) | (np.abs(L["lon"]) > 180)
           | ((L["lat"] == 0) & (L["lon"] == 0)))
    return {k: v[~bad] for k, v in L.items()}, Counter(L["mmsi"][bad].tolist())


def _sort_dedupe(L):
    o = np.lexsort((L["lon"], L["lat"], L["time"], L["mmsi"]))
    L = {k: v[o] for k, v in L.items()}
    same = np.zeros(len(L["mmsi"]), bool)
    same[1:] = ((L["mmsi"][1:] == L["mmsi"][:-1]) & (L["time"][1:] == L["time"][:-1])
                & (L["lat"][1:] == L["lat"][:-1]) & (L["lon"][1:] == L["lon"][:-1]))
    return {k: v[~same] for k, v in L.items()}


def _bounds(mmsi):
    if not len(mmsi):
        return np.array([], int), np.array([], int)
    s = np.flatnonzero(np.r_[True, mmsi[1:] != mmsi[:-1]])
    return s, np.r_[s[1:], len(mmsi)]


def screen_mmsis(L, limit_of):
    """MMSIs that might carry spoofed positions: a consecutive pair needing more than the class speed limit over more
    than 1 km, or a reported speed above it (a cheap vectorised screen; spoof_flags decides later)."""
    m = L["mmsi"]
    if not len(m):
        return set()
    u, inv = np.unique(m, return_inverse=True)
    lim = np.array([limit_of(x) for x in u])[inv]
    sog = np.nan_to_num(L["sog"], nan=0.0)
    hit = (sog > lim) & (sog < 102.25)
    if len(m) > 1:
        same = m[1:] == m[:-1]
        d = haversine_km(L["lat"][:-1], L["lon"][:-1], L["lat"][1:], L["lon"][1:])
        kn = d / np.maximum((L["time"][1:] - L["time"][:-1]).astype(float), 1.0) * 3600 / 1.852
        hit[1:] |= same & (d > 1.0) & (kn > lim[1:])
    return set(np.unique(m[hit]).tolist())


def flags_with_land(K, meta_types, use_land):
    """vessels_build.spoof_flags without its land test, then the 20 km inland test only inside ais_detect's land-mask
    area (CLIP, the Baltic): the mask is projected for Finland and has no land elsewhere."""
    A, P = _tools()
    flagged, dirty = P.spoof_flags(K, meta_types, use_land=False)
    if use_land and len(K["mmsi"]):
        lo0, la0, lo1, la1 = A.CLIP
        inside = (K["lon"] >= lo0) & (K["lon"] <= lo1) & (K["lat"] >= la0) & (K["lat"] <= la1)
        if inside.any():
            try:
                sub = {k: v[inside] for k, v in K.items()}
                flagged[np.flatnonzero(inside)[A.land_depth(sub, A.LandMask()) >= 20]] = True
            except Exception as e:
                print(f"vessels: land mask unavailable ({type(e).__name__}: {e})", file=sys.stderr)
    return flagged


# ----------------------------------------------------------------------------------------------- records
def classify(mmsi, mv, flag, watch_m, watch_i, match, flags_interest):
    """(categories, basis) from identity alone (gnss_victim is added from the track). match: sanction_lookup's kind."""
    cats, basis = [], {}
    imo, typ, name = mv.get("imo"), mv.get("type"), mv.get("name", "")
    if match == "imo":
        cats.append("sanctioned"); basis["sanctioned"] = "broadcast IMO on a listing"
    elif match == "mmsi":
        cats.append("sanctioned"); basis["sanctioned"] = "MMSI on a listing, no valid IMO broadcast (unconfirmed)"
    if typ == 35:
        cats.append("military"); basis["military"] = "AIS type 35"
    elif name and MILITARY_NAME.search(name):
        cats.append("military"); basis["military"] = "name pattern (check)"
    if typ == 55:
        cats.append("law_enforcement"); basis["law_enforcement"] = "AIS type 55"
    elif name and LAW_NAME.search(name):
        cats.append("law_enforcement"); basis["law_enforcement"] = "name pattern (check)"
    if flag and flag in flags_interest:
        cats.append("state_flag_of_interest"); basis["state_flag_of_interest"] = f"MMSI flag {flag}"
    if mmsi in watch_m or (imo and imo in watch_i):
        cats.append("watch_list"); basis["watch_list"] = "private watch list"
    return cats, basis


def excluded(mmsi, mv, keep_anyway):
    """Private craft and non-ship stations are left out (unless sanctioned or watch-listed)."""
    if keep_anyway:
        return False
    A, _ = _tools()
    if A.mmsi_kind(mmsi) != "ship":
        return True
    t = mv.get("type")
    return t == 37 or (t == 36 and not A.imo_valid(mv.get("imo")))


def ais_class_of(msg_ids):
    if msg_ids & {1, 2, 3, 5}:
        return "A"
    if msg_ids & {18, 19, 24}:
        return "B"
    return None


def emitters_near(t, lat, lon, dets, near_km=NEAR_KM):
    """NISAR detections on the same UTC day within near_km of any of these positions (closest position reported)."""
    out = []
    if not len(t) or not dets:
        return out
    vday = np.asarray(t, np.int64) // 86400
    for d in dets:
        dts = datetime.fromisoformat(d["t"].replace("Z", "+00:00")).timestamp()
        sel = vday == int(dts // 86400)
        if not sel.any():
            continue
        km = haversine_km(lat[sel], lon[sel], d["lat"], d["lon"])
        i = int(np.argmin(km))
        if km[i] <= near_km:
            ts = t[sel][i]
            out.append({**d, "km": round(float(km[i]), 1), "vessel_t": iso(ts), "dt_h": round(float(ts - dts) / 3600, 2)})
    out.sort(key=lambda e: (e["km"], e["t"]))
    return out


def unseen_record(imo, entry, listings, match):
    """A watch-listed IMO with no AIS position in the window (public keys, empty)."""
    _, P = _tools()
    return {"mmsi": None, "imo": imo, "name": _norm(entry.get("name")) or None, "callsign": None, "flag": None,
            "ais_type": None, "ais_type_label": P.type_label(None), "ais_class": None, "categories": ["watch_list"],
            "listings": [{**{k: l.get(k) for k in LISTING_KEYS}, "match": match} for l in listings],
            "last": {k: None for k in ("t", "lat", "lon", "sog", "cog", "heading", "nav_status")}, "track": [],
            "reporting": {"positions": 0, "first_seen": None, "last_seen": None, "median_interval_s": None,
                          "gaps_over_1h": 0, "longest_gap_h": 0.0, "spoofed_positions": 0,
                          "pos_accuracy_high_share": None, "raim_share": None},
            "signals": {"ais_class": None, "destination": None, "eta": None, "draught": None, "dimensions": None,
                        "imo_check_digit_ok": None, "pos_fix_device": None},
            "seen": False, "sources": [], "category_basis": {"watch_list": "private watch list"}, "emitters_near": [],
            "private_notes": [_note(entry)], "identities": {}, "suspect_positions": []}


def _note(entry):
    n = {k: entry.get(k) for k in ("reason", "source", "added", "notes", "name") if entry.get(k)}
    return n or {"reason": "on the private watch list"}


def build_data(days=None, n_days=2, cfg=None, dirs=None, watch_path=WATCH_CONFIG, sanctions_path=SANCTIONED,
               near_km=NEAR_KM, use_land=True, now=None, log=print):
    """Everything the page shows, as one JSON-ready dict."""
    A, P = _tools()
    dirs = dirs or AIS_DIRS
    now = now or datetime.now(timezone.utc)
    days = sorted(days) if days else days_available(dirs)[-n_days:]
    src_names = list(dirs)
    watch_m, watch_i, flags_interest = load_watch(watch_path)
    san, have_sanctions = load_sanctions(sanctions_path)
    san_imo = {int(k) for k in (san.get("by_imo") or {}) if str(k).isdigit()}
    san_mmsi = {int(k) for k in (san.get("by_mmsi") or {}) if str(k).isdigit()}
    meta = read_metadata(dirs, days)
    dets = load_detections(cfg, days)

    def keep_anyway(m, mv):
        imo = mv.get("imo")
        return bool(m in watch_m or m in san_mmsi or (imo and (imo in watch_i or imo in san_imo)))

    def limit_of(m):
        return A.speed_limit_kn((meta.get(int(m)) or {}).get("type"))

    def lookup(m, mv):
        return P.sanction_lookup(m, mv.get("imo"), mv.get("name"), mv.get("type"), san)

    cand = set()
    for m, mv in meta.items():
        if keep_anyway(m, mv) or not excluded(m, mv, False):
            if classify(m, mv, P.flag_of(m), watch_m, watch_i, lookup(m, mv)[0], flags_interest)[0]:
                cand.add(m)
    kept, last_pos, unavailable, rows_by_src, suspicious = [], {}, Counter(), Counter(), set()
    outs = defaultdict(list)
    for day in days:
        L = read_day_locations(dirs, day)
        if L is None:
            continue
        for si, n in Counter(L["src"].tolist()).items():
            rows_by_src[src_names[si]] += n
        L, un = _split_invalid(L)
        unavailable.update(un)
        L = _sort_dedupe(L)
        for si in np.unique(L["src"]).tolist():
            outs[src_names[si]] += P.outages(L["time"][L["src"] == si])
        s, e = _bounds(L["mmsi"])
        for i0, i1 in zip(s, e):
            m, j = int(L["mmsi"][i0]), i1 - 1
            if m not in last_pos or L["time"][j] >= last_pos[m][0]:
                last_pos[m] = (int(L["time"][j]), float(L["lat"][j]), float(L["lon"][j]), float(L["sog"][j]),
                               float(L["cog"][j]), int(L["src"][j]), set(int(x) for x in np.unique(L["msg_id"][i0:i1])))
        suspicious |= screen_mmsis(L, limit_of)
        for m in np.unique(L["mmsi"]).tolist():          # identity from the MMSI alone (no static data in the window)
            if m not in cand and m not in meta and not excluded(m, {}, keep_anyway(m, {})):
                if classify(m, {}, P.flag_of(m), watch_m, watch_i, lookup(m, {})[0], flags_interest)[0]:
                    cand.add(m)
        sel = np.isin(L["mmsi"], np.array(sorted(cand | suspicious | set(watch_m)), dtype=np.int64))
        kept.append({k: v[sel] for k, v in L.items()})
        log(f"vessels: {day}: {len(L['mmsi'])} positions, {len(s)} MMSIs, kept {int(sel.sum())}")

    vessels = []
    if kept:
        K = _sort_dedupe({k: np.concatenate([p[k] for p in kept]) for k in kept[0]})
        pmeta = {m: {k: v.get(k) for k in ("type", "imo", "name", "callSign", "destination", "eta", "draught", "posType",
                                            "refA", "refB", "refC", "refD")} for m, v in meta.items()}
        flagged = flags_with_land(K, pmeta, use_land)
        s, e = _bounds(K["mmsi"])
        for a, b in zip(s, e):
            m = int(K["mmsi"][a])
            mv = meta.get(m, {"hist": {}, "msg_ids": set(), "sources": set()})
            if m not in cand and excluded(m, mv, keep_anyway(m, mv)):
                continue
            match, listings = lookup(m, mv)
            cats, basis = classify(m, mv, P.flag_of(m), watch_m, watch_i, match, flags_interest)
            main_src = src_names[int(np.bincount(K["src"][a:b].astype(int)).argmax())]
            rec = P.vessel_record(m, a, b, K, flagged, pmeta, cats, match, listings, outs.get(main_src, []))
            t, lat, lon = K["time"][a:b], K["lat"][a:b], K["lon"][a:b]
            ok = np.ones(b - a, bool)
            if rec["reporting"]["spoofed_positions"]:
                f = flagged[a:b] | P.jump_spans(t, lat, lon, ~flagged[a:b], mv.get("type"))
                ok = ~f
                rec["suspect_positions"] = [[int(t[i]), round(float(lat[i]), 4), round(float(lon[i]), 4)]
                                            for i in np.flatnonzero(f)[:100]]
                if rec["reporting"]["spoofed_positions"] >= GNSS_MIN:
                    cats = cats + ["gnss_victim"]
                    basis["gnss_victim"] = f'{rec["reporting"]["spoofed_positions"]} suspect positions'
            rec["categories"] = [c for c in CAT_ORDER if c in set(cats)]
            if not rec["categories"]:
                continue
            cls = ais_class_of(set(mv["msg_ids"]) | {int(x) for x in np.unique(K["msg_id"][a:b]) if x >= 0})
            if cls:
                rec["ais_class"] = rec["signals"]["ais_class"] = cls
            hist = mv.get("hist") or {}
            we = watch_m.get(m) or (watch_i.get(mv.get("imo")) if mv.get("imo") else None)
            rec.update({
                "seen": bool(ok.any()), "category_basis": basis,
                "sources": sorted(set(mv["sources"]) | {src_names[int(x)] for x in np.unique(K["src"][a:b])}),
                "emitters_near": emitters_near(t[ok], lat[ok], lon[ok], dets, near_km),
                "private_notes": [_note(we)] if we else [],
                "identities": {out: [[v, n] for v, n in hist[k].most_common(10)]
                               for k, out in (("name", "names"), ("callSign", "callsigns"), ("imo", "imos"), ("type", "types"))
                               if hist.get(k) and len(hist[k]) > 1}})
            rec.setdefault("suspect_positions", [])
            if unavailable.get(m):
                rec["pos_unavailable"] = unavailable[m]
            vessels.append(rec)
    # watched MMSIs and IMOs with no position in the window
    seen_m = {v["mmsi"] for v in vessels}
    seen_i = {v["imo"] for v in vessels if v.get("imo")}
    for m, we in watch_m.items():
        if m not in seen_m:
            mv = meta.get(m, {})
            match, listings = lookup(m, mv)
            r = unseen_record(mv.get("imo"), we, listings, match)
            r.update(mmsi=m, flag=P.flag_of(m), name=mv.get("name") or r["name"])
            vessels.append(r)
            seen_i.add(mv.get("imo"))
    for imo, we in watch_i.items():
        if imo not in seen_i:
            match, listings = P.sanction_lookup(None, imo, None, None, san)
            vessels.append(unseen_record(imo, we, listings, match))
    rank = {c: i for i, c in enumerate(CAT_ORDER)}
    vessels.sort(key=lambda v: (min(rank[c] for c in v["categories"]), -(v["reporting"]["positions"] or 0)))

    # traffic layer: every other ship's last position (no tracks); private craft, non-ships, unidentified class B left out
    rec_m = {v["mmsi"] for v in vessels}
    traffic = []
    for m, (t, la, lo, sog, cog, si, mids) in last_pos.items():
        mv = meta.get(m, {})
        if m in rec_m or excluded(m, mv, keep_anyway(m, mv)):
            continue
        if ais_class_of(set(mv.get("msg_ids", set())) | mids) == "B" and not mv.get("type") and not mv.get("imo"):
            continue
        traffic.append([m, mv.get("name"), mv.get("type"), P.flag_of(m), t, round(la, 4), round(lo, 4),
                        round(sog, 1) if np.isfinite(sog) and sog < 102.25 else None,
                        round(cog, 1) if np.isfinite(cog) and cog < 360 else None, src_names[si]])
    counts = Counter(c for v in vessels for c in v["categories"])
    lists = [f"{x.get('attribution', x.get('list'))}, list dated {x.get('published')}" for x in san.get("sources", [])]
    return {
        "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "days": days,
        "sources": {s: {"rows": rows_by_src.get(s, 0), "note": SOURCE_NOTES.get(s, s)} for s in src_names},
        "sanctions_loaded": have_sanctions, "sanctions_sources": lists, "flags_of_interest": list(flags_interest),
        "near_km": near_km, "gnss_min": GNSS_MIN,
        "collection_gaps": {k: [[iso(a), iso(b)] for a, b in v] for k, v in outs.items()},
        "counts": {"vessels": len(vessels), "traffic": len(traffic), **{c: counts.get(c, 0) for c in CAT_ORDER},
                   "detections": len(dets), "with_emitters_near": sum(1 for v in vessels if v["emitters_near"])},
        "vessels": vessels,
        "traffic": {"cols": ["mmsi", "name", "ais_type", "flag", "t", "lat", "lon", "sog", "cog", "src"], "rows": traffic},
        "detections": dets,
    }


# ----------------------------------------------------------------------------------------------- page
def _land():
    fc = json.load(gzip.open(os.path.join(HERE, "assets", "land.geojson.gz"), "rt", encoding="utf-8"))

    def rnd(c):
        return [rnd(x) for x in c] if isinstance(c[0], list) else [round(c[0], 3), round(c[1], 3)]
    return {"type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {},
                          "geometry": {"type": f["geometry"]["type"], "coordinates": rnd(f["geometry"]["coordinates"])}}
                         for f in fc["features"]]}


def write_page(data, path):
    tpl = open(os.path.join(HERE, "vessels_template.html"), encoding="utf-8").read()
    assert "/*__DATA__*/null" in tpl and "/*__LAND__*/null" in tpl
    blob = json.dumps(data, separators=(",", ":"), default=str).replace("</", "<\\/")     # AIS text is untrusted
    out = tpl.replace("/*__LAND__*/null", json.dumps(_land(), separators=(",", ":"))).replace("/*__DATA__*/null", blob)
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)


def build(cfg=None, dest=None, days=None, n_days=2, near_km=NEAR_KM, log=print, **kw):
    """Build vessels.json and vessels.html into dest (default private/maritime/vessels/). Returns a summary dict."""
    dest = dest or DEFAULT_OUT
    os.makedirs(dest, exist_ok=True)
    data = build_data(days=days, n_days=n_days, cfg=cfg, near_km=near_km, log=log, **kw)
    with open(os.path.join(dest, "vessels.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), default=str)
    write_page(data, os.path.join(dest, "vessels.html"))
    return {"dest": dest, "days": data["days"], **data["counts"]}


def build_for_view(cfg, dest, opt):
    """view.build() hook: opt is the view config's "vessels" value (true, or a dict with days / near_km)."""
    o = opt if isinstance(opt, dict) else {}
    return build(cfg, dest, n_days=int(o.get("days", 2)), near_km=float(o.get("near_km", NEAR_KM)))
