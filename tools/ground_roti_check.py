#!/usr/bin/env python3
"""ground_roti_check.py: the pre-registered check of ground ROTI against INGV eSWua ground scintillation receivers.

ROTI, a measured TEC fluctuation index at fixed stations, is a proxy for irregularities, not an S4 value: this check
asks only whether a station's ROTI is higher in the hours when a nearby scintillation receiver saw scintillation.
Rules: docs/validation/ground-roti.md sections 2-5 (frozen 15 Nov 2026). Registry rows `cors-igs` and
`ingv-eswua-scint` (CC BY 4.0; credit the eSWua citation and each receiver's owner).

  python tools/ground_roti_check.py check DAY... [--ground DIR] [--out F]

DAY may be START:END. eSWua records are read from DIR/<code>/<day>.json (default data/eswua; made by
tools/cosmic2_s4_check.py ground); ROTI files from data/swx/<day>.ground-roti.json, downloaded from the release if
missing.
"""
import argparse
import json
import os
import sys
import urllib.request

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cosmic2_s4_check as G  # noqa: E402  (eSWua stations, hour labels, AUC, chance test, bootstrap)
import ground_roti as R  # noqa: E402

SWX = os.path.join(ROOT, "data", "swx")
# Frozen partner table (section 3): eSWua receiver -> the IGS station paired with it
PARTNERS = {p: s for s, (_, _, _, p) in R.STATIONS.items() if p}
NEAR_KM = 250.0                    # reported without marks: only pairs this close
FAR_KM = (500.0, 2000.0)           # reported without marks: stations with no receiver within 500 km
FAR_DLON = 15.0
MARKS = {"R1": (0.80, 0.70), "R2": (0.70, 0.60), "R3": (0.01, 0.05)}


def verdict(name, value):
    if value is None:
        return "not judged"
    good, bad = MARKS[name]
    if name == "R3":
        return "holds" if value <= good else "fails" if value > bad else "weakened"
    return "holds" if value >= good else "fails" if value < bad else "weakened"


def roti_file(day):
    import cosmic2_job as J
    name = f"{day}.{R.FEED}.json"
    p = os.path.join(SWX, name)
    if not os.path.exists(p):
        try:
            req = urllib.request.Request(J.asset_url(J.s4_tag(day), name), headers=R.UA)
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
        except OSError:
            return None
        os.makedirs(SWX, exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
    return json.load(open(p, encoding="utf-8"))


def ground_reader(ground_dir):
    def read(code, day):
        p = os.path.join(ground_dir, code, f"{day}.json")
        return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None
    return read


def index(doc):
    """{(station, hour): row} of a day file."""
    out = {}
    for h, hh in enumerate(doc["hours"]):
        for r in hh["stations"]:
            out[(r[0], h)] = r
    return out


def far_pairs():
    """[(station, eSWua code)] for stations with no receiver within 500 km: receivers 500-2,000 km away whose
    longitude is within 15 deg (local time within an hour)."""
    out = []
    for s, (_, la, lo, partner) in R.STATIONS.items():
        if partner:
            continue
        for c, (_, gla, glo, _) in G.STATIONS.items():
            d = R.km(la, lo, gla, glo)
            if FAR_KM[0] < d <= FAR_KM[1] and abs(lo - glo) <= FAR_DLON:
                out.append((s, c))
    return out


def pairs(days, ground, roti=roti_file, links=None):
    """[{day, code, station, hour, label, R, Rmax, breaks, lst, km}] for judged (disturbed or quiet) receiver-hours
    whose partner station has a p95 in the same UTC hour, and the counts of what was skipped or unpaired."""
    links = links if links is not None else list(PARTNERS.items())
    cols = R.COLUMNS
    ip, im, ib = cols.index("p95"), cols.index("max"), cols.index("breaks")
    out, skipped, unpaired, judged = [], [], 0, 0
    for day in days:
        doc = roti(day)
        if doc is None:
            skipped.append(f"{day}: no ROTI file")
            continue
        idx = index(doc)
        have = {s["id"] for s in doc["stations"]}
        for code, sta in links:
            recs = ground(code, day)
            if not recs:
                skipped.append(f"{day} {code}: no eSWua records")
                continue
            if sta not in have:
                skipped.append(f"{day} {sta}: station not in the ROTI file")
                continue
            name, lat, lon, _ = G.STATIONS[code]
            d = R.km(lat, lon, R.STATIONS[sta][1], R.STATIONS[sta][2])
            for h, (lab, _, _) in G.hour_labels(recs).items():
                if lab not in ("disturbed", "quiet"):
                    continue
                judged += 1
                row = idx.get((sta, h))
                if row is None or row[ip] is None:
                    unpaired += 1
                    continue
                out.append({"day": day, "code": code, "station": sta, "hour": h, "label": lab, "R": row[ip],
                            "Rmax": row[im], "breaks": row[ib], "lst": round((h + 0.5 + lon / 15.0) % 24.0, 2),
                            "km": round(d)})
    return out, {"skipped": skipped, "judged_receiver_hours": judged, "unpaired": unpaired}


def _auc(P, key="R"):
    lab = np.array([p["label"] == "disturbed" for p in P], bool)
    v = np.array([p[key] for p in P], float)
    if not lab.any() or lab.all():
        return None
    return round(G.auc(v[lab], v[~lab]), 3)


def score(P):
    lab = np.array([p["label"] == "disturbed" for p in P], bool)
    v = np.array([p["R"] for p in P], float)
    out = {"pairs": len(P), "disturbed": int(lab.sum()), "quiet": int((~lab).sum())}
    if not lab.any() or lab.all():
        return out
    strata = np.array([f"{p['code']}:{int(p['lst'])}" for p in P])
    a1, p3 = G.perm_p(v, lab, strata)
    night = np.array([G.in_night(p["lst"]) for p in P], bool)
    n_d, n_q = int((lab & night).sum()), int((~lab & night).sum())
    a2 = G.auc(v[lab & night], v[~lab & night]) if n_d >= 20 and n_q >= 20 else None
    blocks = np.array([f"{p['code']}:{p['day']}" for p in P])
    per = {}
    for code, sta in PARTNERS.items():
        m = np.array([p["code"] == code for p in P], bool)
        if (m & lab).sum() >= 5 and (m & ~lab).any():
            per[f"{G.STATIONS[code][0]} / {sta}"] = {"auc": round(G.auc(v[m & lab], v[m & ~lab]), 3),
                                                    "disturbed": int((m & lab).sum()), "quiet": int((~lab & m).sum())}
    near = [p for p in P if p["km"] <= NEAR_KM]
    out.update({
        "R1_auc": round(a1, 3), "R1": verdict("R1", a1),
        "R2_auc": None if a2 is None else round(a2, 3), "R2": verdict("R2", a2),
        "R2_pairs": {"disturbed": n_d, "quiet": n_q},
        "R3_p": round(p3, 4), "R3": verdict("R3", p3),
        "median_R_disturbed": G.boot_median(v[lab], blocks[lab]),
        "median_R_quiet": G.boot_median(v[~lab], blocks[~lab]),
        "auc_with_max": _auc(P, "Rmax"),
        "auc_with_breaks": _auc(P, "breaks"),
        "near_250_km": {"pairs": len(near), "auc": _auc(near)},
        "stations": per,
    })
    return out


def check(days, ground, roti=roti_file):
    P, meta = pairs(days, ground, roti)
    res = {"days": days, **meta, **score(P)}
    F, fmeta = pairs(days, ground, roti, links=[(c, s) for s, c in far_pairs()])
    res["far_pairs"] = {"links": [f"{s}-{c}" for s, c in far_pairs()], "pairs": len(F),
                        "disturbed": sum(p["label"] == "disturbed" for p in F), "auc": _auc(F) if F else None,
                        "unpaired": fmeta["unpaired"]}
    res["validated"] = all(res.get(k) == "holds" for k in ("R1", "R2", "R3"))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("days", nargs="+")
    c.add_argument("--ground", default=G.GROUND, help="folder of cached eSWua records (<code>/<day>.json)")
    c.add_argument("--out")
    a = ap.parse_args(argv)
    res = check(G.days_from(a.days), ground_reader(a.ground))
    text = json.dumps(res, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
