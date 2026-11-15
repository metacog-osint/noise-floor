#!/usr/bin/env python3
"""cosmic2_s4_check.py: the pre-registered check of COSMIC-2 limb S4 against INGV eSWua ground scintillation receivers.

Rules: docs/validation/cosmic2-limb-s4.md sections 3-5 (frozen 15 Nov 2026). Registry rows `cosmic2-ro` and
`ingv-eswua-scint` (CC BY 4.0; credit the eSWua citation and each receiver's owner).

  python tools/cosmic2_s4_check.py ground DAY...            fetch each station's 1-minute records at 30 deg or more
                                                            -> data/eswua/<code>/<day>.json (cached)
  python tools/cosmic2_s4_check.py check DAY... [--out F]   pair receiver-hours with limb cells and score L1-L3

DAY may be START:END. Limb files are read from data/swx/<day>.cosmic2-limb-s4.json, downloaded from the release if
missing.
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
GROUND = os.path.join(ROOT, "data", "eswua")
SWX = os.path.join(ROOT, "data", "swx")
BASE = "http://ws-eswua.rm.ingv.it/swit/scintillation/records/"
UA = "noisefloor/1.0 (+https://github.com/metacog-osint/noise-floor)"
# eSWua's station table (read 15 Nov 2026): code -> (name, lat, lon, receiver owner)
STATIONS = {
    "lag0p": ("Lagos", 6.729469, 3.414128, "INGV"),
    "nai0p": ("Nairobi", -1.288398, 36.800694, "KSA"),
    "mal0p": ("Malindi", -2.995556, 40.194444, "INGV, ASI"),
    "tuc0p": ("Tucuman", -23.727, -65.23, "INGV"),
    "sao0p": ("Sao Paulo", -23.5, -46.7, "INGV"),
    "sab0p": ("Saba", 17.621, -63.243, "KNMI"),
    "klu0p": ("KL University", 16.440342, 80.623689, "KLU"),
    "dha0p": ("Dhaka", 23.837448, 90.357175, "INGV"),
    "han0p": ("Hanoi", 21.0046, 105.8439, "NAVIS"),
    "ken0p": ("Kenting", 21.91325, 120.848194, "IAP, INGV"),
}
MIN_ELEV = 30.0
MIN_SAT_MINUTES = 300
GROUND_LEVEL = 0.5                 # ground receivers' own S4 only; never applied to limb S4
DISTURBED_MINUTES = 2
RADIUS_KM = 1000.0
SENSITIVITY_KM = (600.0, 1500.0)
NIGHT = (19.0, 2.0)                # station local solar time window for L2
N_PERM = N_BOOT = 2000
SEED = 1
MARKS = {"L1": (0.70, 0.60), "L2": (0.60, 0.55), "L3": (0.01, 0.05)}


def keep_svid(s):
    """eSWua satellite ids kept: GPS, GLONASS, Galileo, BeiDou from C06, QZSS J01-J06 (section 3)."""
    if s is None:
        return False
    s = int(s)
    return 1 <= s <= 37 or 38 <= s <= 68 or 71 <= s <= 106 or 146 <= s <= 177 or 181 <= s <= 186


def s4_corrected(total, corr):
    if total is None:
        return None
    if corr is None:
        return float(total)
    return math.sqrt(max(float(total) ** 2 - float(corr) ** 2, 0.0))


def days_from(args):
    out = []
    for a in args:
        if ":" in a:
            s, e = (date.fromisoformat(x) for x in a.split(":"))
            out += [(s + timedelta(days=k)).isoformat() for k in range((e - s).days + 1)]
        else:
            out.append(date.fromisoformat(a).isoformat())
    return out


# ---------------------------------------------------------------------------------------------- ground

def ground_url(code, day):
    q = [("filter", f"dt,bt,{day} 00:00:00,{day} 23:59:59"), ("filter", f"elevation,ge,{MIN_ELEV:g}"),
         ("include", "dt,svid,elevation,totals4l1,corrections4l1")]
    return BASE + "ws" + code + "?" + urllib.parse.urlencode(q)


def fetch_ground(code, day, force=False):
    d = os.path.join(GROUND, code)
    p = os.path.join(d, f"{day}.json")
    if os.path.exists(p) and not force:
        return p
    os.makedirs(d, exist_ok=True)
    for attempt in range(3):
        try:
            req = urllib.request.Request(ground_url(code, day), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                recs = json.load(r).get("records", [])
            break
        except (OSError, ValueError) as e:
            if attempt == 2:
                raise
            print(f"{code} {day}: retry after {e}", file=sys.stderr)
            time.sleep(10 * (attempt + 1))
    with open(p, "w", encoding="utf-8") as f:
        json.dump(recs, f, separators=(",", ":"))
    return p


def hour_labels(records):
    """1-minute records -> {hour: (label, kept satellite-minutes, minutes at the ground level or above)}."""
    acc = {}
    for r in records:
        if not keep_svid(r.get("svid")) or r.get("elevation") is None or float(r["elevation"]) < MIN_ELEV:
            continue
        s4 = s4_corrected(r.get("totals4l1"), r.get("corrections4l1"))
        if s4 is None or not math.isfinite(s4):
            continue
        h = int(str(r["dt"])[11:13])
        a = acc.setdefault(h, [0, 0])
        a[0] += 1
        a[1] += s4 >= GROUND_LEVEL
    out = {}
    for h, (n, hi) in acc.items():
        if n < MIN_SAT_MINUTES:
            lab = "unjudged"
        elif hi >= DISTURBED_MINUTES:
            lab = "disturbed"
        elif hi == 0:
            lab = "quiet"
        else:
            lab = "unclear"
        out[h] = (lab, n, hi)
    return out


# ---------------------------------------------------------------------------------------------- limb

def limb_file(day):
    import cosmic2_job as J
    import cosmic2_s4 as S
    name = f"{day}.{S.FEED}.json"
    p = os.path.join(SWX, name)
    if not os.path.exists(p):
        try:
            req = urllib.request.Request(J.asset_url(J.s4_tag(day), name), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
        except OSError:
            return None
        os.makedirs(SWX, exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
    return json.load(open(p, encoding="utf-8"))


def km(lat1, lon1, lat2, lon2):
    a, b, c, d = map(math.radians, (lat1, lon1, lat2, lon2))
    x = math.sin(a) * math.sin(c) + math.cos(a) * math.cos(c) * math.cos(b - d)
    return 6371.0 * math.acos(max(-1.0, min(1.0, x)))


def nearby(doc, hour, lat, lon, radius_km):
    """(largest p95, largest max, share of those cells with rfi > 0.5) over the hour's cells within radius, or None."""
    cols = doc["columns"]
    ic, ila, ilo, ip, im, ir = (cols.index(k) for k in ("cell", "lat", "lon", "p95", "max", "rfi"))
    rows = [r for r in doc["hours"][hour]["cells"]
            if r[ip] is not None and km(lat, lon, r[ila], r[ilo]) <= radius_km]
    if not rows:
        return None
    return max(r[ip] for r in rows), max(r[im] for r in rows), float(np.mean([r[ir] > 0.5 for r in rows]))


# ---------------------------------------------------------------------------------------------- stats

def auc(pos, neg):
    """Mann-Whitney AUC (ties count half)."""
    from scipy.stats import rankdata
    pos, neg = np.asarray(pos, float), np.asarray(neg, float)
    if not len(pos) or not len(neg):
        return None
    r = rankdata(np.r_[pos, neg])
    return float((r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def perm_p(values, labels, strata, n=N_PERM, seed=SEED):
    """One-sided p of the AUC with labels shuffled within strata."""
    values, labels, strata = np.asarray(values, float), np.asarray(labels, bool), np.asarray(strata)
    obs = auc(values[labels], values[~labels])
    rng = np.random.default_rng(seed)
    groups = [np.flatnonzero(strata == s) for s in np.unique(strata)]
    hits = 0
    lab = labels.copy()
    for _ in range(n):
        for g in groups:
            lab[g] = rng.permutation(labels[g])
        a = auc(values[lab], values[~lab])
        hits += a is not None and a >= obs
    return obs, (1 + hits) / (1 + n)


def boot_median(values, blocks, n=N_BOOT, seed=SEED):
    values, blocks = np.asarray(values, float), np.asarray(blocks)
    if not len(values):
        return None
    ub = np.unique(blocks)
    idx = {b: np.flatnonzero(blocks == b) for b in ub}
    rng = np.random.default_rng(seed)
    meds = [np.median(np.concatenate([values[idx[b]] for b in rng.choice(ub, len(ub))])) for _ in range(n)]
    return [round(float(np.median(values)), 3), round(float(np.percentile(meds, 2.5)), 3),
            round(float(np.percentile(meds, 97.5)), 3)]


def verdict(name, value):
    if value is None:
        return "not judged"
    good, bad = MARKS[name]
    if name == "L3":
        return "holds" if value <= good else "fails" if value > bad else "weakened"
    return "holds" if value >= good else "fails" if value < bad else "weakened"


def in_night(lst):
    return lst >= NIGHT[0] or lst < NIGHT[1]


def pairs(days, radius_km=RADIUS_KM, ground=None, limb=None):
    """[{day, code, hour, label, L, Lmax, rfi, lst}] for judged (disturbed or quiet) receiver-hours with a nearby cell.
    Also returns the counts of skipped days and unpaired receiver-hours."""
    out, skipped, unpaired, judged = [], [], 0, 0
    for day in days:
        doc = (limb or limb_file)(day)
        if doc is None:
            skipped.append(f"{day}: no limb file")
            continue
        for code, (name, lat, lon, _) in STATIONS.items():
            recs = (ground or (lambda c, d: json.load(open(fetch_ground(c, d), encoding="utf-8"))))(code, day)
            if not recs:
                skipped.append(f"{day} {code}: no eSWua records")
                continue
            for h, (lab, _, _) in hour_labels(recs).items():
                if lab not in ("disturbed", "quiet"):
                    continue
                judged += 1
                nb = nearby(doc, h, lat, lon, radius_km)
                if nb is None:
                    unpaired += 1
                    continue
                lst = (h + 0.5 + lon / 15.0) % 24.0
                out.append({"day": day, "code": code, "hour": h, "label": lab, "L": nb[0], "Lmax": nb[1],
                            "rfi": nb[2], "lst": round(lst, 2)})
    return out, {"skipped": skipped, "judged_receiver_hours": judged, "unpaired": unpaired}


def score(P):
    lab = np.array([p["label"] == "disturbed" for p in P], bool)
    L = np.array([p["L"] for p in P], float)
    out = {"pairs": len(P), "disturbed": int(lab.sum()), "quiet": int((~lab).sum())}
    if not lab.any() or lab.all():
        return out
    strata = np.array([f"{p['code']}:{int(p['lst'])}" for p in P])
    a1, p3 = perm_p(L, lab, strata)
    night = np.array([in_night(p["lst"]) for p in P], bool)
    n_d, n_q = int((lab & night).sum()), int((~lab & night).sum())
    a2 = auc(L[lab & night], L[~lab & night]) if n_d >= 20 and n_q >= 20 else None
    blocks = np.array([f"{p['code']}:{p['day']}" for p in P])
    per = {}
    for code in STATIONS:
        m = np.array([p["code"] == code for p in P], bool)
        if (m & lab).sum() >= 5 and (m & ~lab).any():
            per[STATIONS[code][0]] = {"auc": round(auc(L[m & lab], L[m & ~lab]), 3), "disturbed": int((m & lab).sum()),
                                      "quiet": int((m & ~lab).sum())}
    Lmax = np.array([p["Lmax"] for p in P], float)
    out.update({
        "L1_auc": round(a1, 3), "L1": verdict("L1", a1),
        "L2_auc": None if a2 is None else round(a2, 3), "L2": verdict("L2", a2),
        "L2_pairs": {"disturbed": n_d, "quiet": n_q},
        "L3_p": round(p3, 4), "L3": verdict("L3", p3),
        "median_L_disturbed": boot_median(L[lab], blocks[lab]),
        "median_L_quiet": boot_median(L[~lab], blocks[~lab]),
        "auc_with_max": round(auc(Lmax[lab], Lmax[~lab]), 3),
        "stations": per,
        "share_rfi_cells": round(float(np.mean([p["rfi"] for p in P])), 3),
    })
    return out


def check(days, ground=None, limb=None):
    P, meta = pairs(days, RADIUS_KM, ground, limb)
    res = {"days": days, **meta, **score(P)}
    res["sensitivity"] = {}
    for r in SENSITIVITY_KM:
        Q, _ = pairs(days, r, ground, limb)
        lab = [q["label"] == "disturbed" for q in Q]
        a = auc([q["L"] for q, d in zip(Q, lab) if d], [q["L"] for q, d in zip(Q, lab) if not d])
        res["sensitivity"][f"{int(r)}_km"] = {"pairs": len(Q), "auc": None if a is None else round(a, 3)}
    res["validated"] = all(res.get(k) == "holds" for k in ("L1", "L2", "L3"))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("ground")
    g.add_argument("days", nargs="+")
    g.add_argument("--force", action="store_true")
    c = sub.add_parser("check")
    c.add_argument("days", nargs="+")
    c.add_argument("--out")
    a = ap.parse_args(argv)
    days = days_from(a.days)
    if a.cmd == "ground":
        for day in days:
            for code in STATIONS:
                try:
                    p = fetch_ground(code, day, a.force)
                    print(f"{day} {code}: {len(json.load(open(p, encoding='utf-8')))} records")
                except Exception as e:              # one station must not stop the others
                    print(f"{day} {code}: FAILED {e}", file=sys.stderr)
        return 0
    res = check(days)
    text = json.dumps(res, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
