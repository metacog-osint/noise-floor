#!/usr/bin/env python3
"""fir_approx.py: country outlines that stand in for flight information regions (FIRs), for EASA's FIR tables.

  python tools/fir_approx.py [--ne data/natural_earth/ne_50m_admin_0_countries.geojson] [--out data/declared/fir_approx.json]

ICAO's FIR boundaries aren't free to reuse, so tools/events.py (rule D1, EASA) places an EASA FIR listing with the land
outline of the country (or countries) that FIR covers, from Natural Earth (public domain). An area applies only when
EASA lists every FIR in AREAS[...]["firs"], so a country split between FIRs (Turkey: Ankara and Istanbul) counts only
when all its FIRs are listed, and countries with many FIRs (Russia, India, Pakistan, Ukraine) are left out unless
listed here. Kaliningrad's FIR is the Kaliningrad exclave's outline.

What the stand-in gets wrong, stated in docs/assessment/events.md: FIRs reach over the sea (the Baltic FIRs, Nicosia,
Cairo, Jeddah, Ankara's Black Sea part), and the outlines don't, so events over open sea are mostly missed (the check
also uses each event's H3 res-2 cell centres, which reach some way offshore); and a FIR boundary isn't always the
border. Needs shapely (local only; the output is plain JSON that events.py reads without it).
"""
import argparse
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# key: (name, Natural Earth ADM0_A3 codes, FIRs that must all be listed, optional point picking one part of a country)
AREAS = {
    "BGR": ("Bulgaria", ["BGR"], ["LBSR"], None),
    "MMR": ("Myanmar", ["MMR"], ["VYYF"], None),
    "TUR": ("Turkey", ["TUR"], ["LTAA", "LTBB"], None),
    "POL": ("Poland", ["POL"], ["EPWW"], None),
    "LVA": ("Latvia", ["LVA"], ["EVRR"], None),
    "LTU": ("Lithuania", ["LTU"], ["EYVL"], None),
    "ROU": ("Romania", ["ROU"], ["LRBB"], None),
    "THA": ("Thailand", ["THA"], ["VTBB"], None),
    "SWE": ("Sweden", ["SWE"], ["ESAA"], None),
    "EST": ("Estonia", ["EST"], ["EETT"], None),
    "IRN": ("Iran", ["IRN"], ["OIIX"], None),
    "SAU": ("Saudi Arabia", ["SAU"], ["OEJD"], None),
    "CYP": ("Cyprus (whole island)", ["CYP", "CYN"], ["LCCC"], None),
    "IRQ": ("Iraq", ["IRQ"], ["ORBB"], None),
    "BLR": ("Belarus", ["BLR"], ["UMMV"], None),
    "ARE": ("United Arab Emirates", ["ARE"], ["OMAE"], None),
    "EGY": ("Egypt", ["EGY"], ["HECC"], None),
    "JOR": ("Jordan", ["JOR"], ["OJAC"], None),
    "FIN": ("Finland", ["FIN"], ["EFIN"], None),
    "OMN": ("Oman", ["OMN"], ["OOMM"], None),
    "ISR": ("Israel and the Palestinian territories", ["ISR", "PSX"], ["LLLL"], None),
    "SDN": ("Sudan", ["SDN"], ["HSSS"], None),
    "SYR": ("Syria", ["SYR"], ["OSTT"], None),
    "GEO": ("Georgia", ["GEO"], ["UGGG"], None),
    "LBN": ("Lebanon", ["LBN"], ["OLBB"], None),
    "KGD": ("Kaliningrad", ["RUS"], ["UMKK"], (54.71, 20.51)),
    "PAK": ("Pakistan", ["PAK"], ["OPLR", "OPKR"], None),
}
TOLERANCE_DEG = 0.03          # simplification: about 3 km, far below the coarseness of a FIR-week listing
MIN_AREA_DEG2 = 0.02          # drop islets smaller than this (about 15 x 15 km)


def build(ne_path):
    from shapely.geometry import Point, shape
    from shapely.ops import unary_union
    feats = json.load(open(ne_path, encoding="utf-8"))["features"]
    by = {f["properties"]["ADM0_A3"]: shape(f["geometry"]) for f in feats}
    out = {}
    for key, (name, codes, firs, pick) in AREAS.items():
        g = unary_union([by[c] for c in codes])
        parts = list(getattr(g, "geoms", [g]))
        if pick:
            parts = [p for p in parts if p.contains(Point(pick[1], pick[0]))]
            assert parts, key
        rings = []
        for p in parts:
            p = p.simplify(TOLERANCE_DEG, preserve_topology=True)
            if p.area < MIN_AREA_DEG2:
                continue
            rings.append([[round(la, 3), round(lo, 3)] for lo, la in list(p.exterior.coords)[:-1]])
        out[key] = {"name": name, "countries": codes, "firs": firs, "rings": rings}
    return {"source": "Natural Earth 1:50m admin-0 countries (public domain), simplified; stand-ins for FIRs, "
                      "see tools/fir_approx.py", "areas": out}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ne", default=os.path.join(ROOT, "data", "natural_earth", "ne_50m_admin_0_countries.geojson"))
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "declared", "fir_approx.json"))
    a = ap.parse_args()
    d = build(a.ne)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(d, f, separators=(",", ":"))
    for k, v in d["areas"].items():
        print(f"{k}: {v['name']}, FIRs {'+'.join(v['firs'])}, {len(v['rings'])} ring(s), {sum(len(r) for r in v['rings'])} points")
    print(f"-> {a.out} ({os.path.getsize(a.out) // 1024} KB)")


if __name__ == "__main__":
    main()
