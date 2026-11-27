#!/usr/bin/env python3
"""swx_site.py: the space weather files on the site, the home page and the feed.

Two day files from the swx-data-YYYY-MM releases:
- <day>.cosmic2-limb-s4.json (tools/cosmic2_s4.py, docs/validation/cosmic2-limb-s4.md): limb S4 measured along
  radio-occultation paths, which reads higher than a ground receiver's S4. Per H3 res-1 cell and UTC hour.
- <day>.ground-roti.json (tools/ground_roti.py, docs/validation/ground-roti.md): ROTI, a measured TEC fluctuation
  index at fixed stations. Per IGS station and UTC hour, in TECU/min. A proxy for irregularities, never an S4 value.

Label rule: limb S4 is never compared with the ground S4 alert levels, and ROTI is
never read against S4 alert levels; neither has an alert level here. Every number below is a measurement with no
baseline, so the board card and the feed items built from it are routine observations: the day's highest values,
not departures from a usual level.

  limb_map(d), roti_map(d)      slim map files for site/data/limbs4/ and site/data/roti/ (site_layers.py)
  card(release, places)         the board's "swx" section: the newest day of each, with the highest cells and stations

Standard library only (the deploy job's site_layers.py runs before anything is installed); h3 is imported only for
cell distances in card(), which board.py runs after the install.
"""
import glob
import json
import math
import os

REPO = "metacog-osint/noise-floor"
LIMB_LABEL = "Limb S4 measured along radio-occultation paths, which reads higher than a ground receiver's S4"
ROTI_LABEL = "ROTI, a measured TEC fluctuation index at fixed stations"
ROTI_NOT_S4 = ("A proxy for ionospheric irregularities from TEC fluctuations. It is not an S4 value and is never read "
               "against S4 alert levels.")
LIMB_NOT_GROUND = ("The ray crosses the ionosphere edge-on over thousands of kilometres, so this is not a ground "
                   "receiver's S4 and is never compared with the alert levels used for ground S4.")
RFI_MAX = 0.5          # a cell-hour with more than half its values taken while UCAR's RFI index was raised is not a top
                       # cell: interference can raise on-board S4 (validation section 2.6; exploratory AUC 0.808 at 0.5)
TOP_LIMB = 5           # the day's highest limb S4 cells in the card and the feed
LIMB_SPACING_KM = 1500.0   # top cells at least this far apart (a res-1 cell is about 840 km across)


def release_url(day, kind):
    return f"https://github.com/{REPO}/releases/download/swx-data-{day[:7]}/{day}.{kind}.json"


def _best_by(rows, key):
    """rows: (id, hour index, row) -> {id: (hour index, row)} keeping the row with the highest row[key]."""
    best = {}
    for k, hi, r in rows:
        v = r[key]
        if v is None:
            continue
        if k not in best or v > best[k][1][key]:
            best[k] = (hi, r)
    return best


def limb_map(d):
    """The map file for one limb S4 day: each cell's highest hourly p95 (cell-hours with 10 or more values only).

    cells: [cell, p95, hour, lst, rfi, n, links, max, hours] where hour is the UTC hour of that p95, lst the cell's mean
    local solar time then, rfi the RFI-flagged share of that cell-hour's values, and hours the number of the cell's
    hours with a p95."""
    cols = d["columns"]
    ix = {c: i for i, c in enumerate(cols)}
    rows, hours_with = [], {}
    for hi, h in enumerate(d.get("hours") or []):
        for c in h.get("cells") or []:
            rows.append((c[ix["cell"]], int(h["hour"][11:13]), c))
            if c[ix["p95"]] is not None:
                hours_with[c[ix["cell"]]] = hours_with.get(c[ix["cell"]], 0) + 1
    best = _best_by(rows, ix["p95"])
    cells = sorted(([k, r[ix["p95"]], hi, r[ix["lst"]], r[ix["rfi"]], r[ix["n"]], r[ix["links"]], r[ix["max"]],
                     hours_with.get(k, 0)] for k, (hi, r) in best.items()), key=lambda c: -c[1])
    cnt = d.get("counts") or {}
    return {"feed": d.get("feed"), "day": d["day"], "as_of": d.get("as_of"), "measure": LIMB_LABEL,
            "note": LIMB_NOT_GROUND, "licence": d.get("licence"), "credit": d.get("credit"),
            "satellites": d.get("satellites"), "problems": d.get("problems") or [],
            "cell_hours": cnt.get("cell_hours"), "with_p95": cnt.get("with_p95"),
            "file": release_url(d["day"], "cosmic2-limb-s4"),
            "columns": ["cell", "p95", "hour", "lst", "rfi", "n", "links", "max", "hours"], "cells": cells}


def roti_map(d):
    """The map file for one ground ROTI day: per station, its 24 hourly p95 values (TECU/min) and the highest."""
    cols = d["columns"]
    ix = {c: i for i, c in enumerate(cols)}
    meta = {s["id"]: s for s in d.get("stations") or []}
    by = {}
    for h in d.get("hours") or []:
        hi = int(h["hour"][11:13])
        for r in h.get("stations") or []:
            st = by.setdefault(r[ix["station"]], {"p95": [None] * 24, "lst": [None] * 24, "n": [0] * 24,
                                                  "lat": r[ix["lat"]], "lon": r[ix["lon"]]})
            st["p95"][hi] = r[ix["p95"]]
            st["lst"][hi] = r[ix["lst"]]
            st["n"][hi] = r[ix["n"]]
    stations = []
    for sid in sorted(by):
        st = by[sid]
        vals = [(v, hi) for hi, v in enumerate(st["p95"]) if v is not None]
        top = max(vals) if vals else (None, None)
        stations.append({"id": sid, "place": (meta.get(sid) or {}).get("place"), "lat": st["lat"], "lon": st["lon"],
                         "p95": st["p95"], "max_p95": top[0], "hour": top[1],
                         "lst": st["lst"][top[1]] if top[1] is not None else None, "hours": len(vals)})
    return {"feed": d.get("feed"), "day": d["day"], "as_of": d.get("as_of"), "measure": ROTI_LABEL,
            "note": ROTI_NOT_S4, "units": d.get("units", "TECU/min"), "licence": d.get("licence"),
            "credit": d.get("credit"), "missing": d.get("missing") or [], "problems": d.get("problems") or [],
            "file": release_url(d["day"], "ground-roti"), "stations": stations}


def _km(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    x = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 12742 * math.asin(min(1.0, math.sqrt(x)))


def _newest(release, kind):
    files = sorted(glob.glob(os.path.join(release, f"*.{kind}.json")))
    for f in reversed(files):
        try:
            with open(f, encoding="utf-8") as g:
                return json.load(g)
        except (OSError, ValueError):
            continue
    return None


def limb_card(d, places=None):
    m = limb_map(d)
    import h3
    top = []
    for c in m["cells"]:
        if c[4] is not None and c[4] > RFI_MAX:
            continue
        ll = h3.cell_to_latlng(c[0])
        if any(_km(ll, (t["lat"], t["lon"])) < LIMB_SPACING_KM for t in top):
            continue
        # Named on the jamming areas' rule (tools/area_names.py, Tom's yes 18 Nov 2026 evening CST): "near Recife",
        # "in Brazil, 350 km S of Marabá", "in the South Atlantic Ocean"; a place's point only for a place name.
        name, at, kind, rf = places.area_kind(ll[0], ll[1], []) if places else (None, None, None, None)
        top.append({"cell": c[0], "lat": round(ll[0], 2), "lon": round(ll[1], 2), "p95": c[1], "hour": c[2],
                    "lst": c[3], "rfi": c[4], "n": c[5], "links": c[6], "max": c[7], "near": name,
                    "near_at": at if kind == "place" else None, "near_kind": kind, "near_ref": rf,
                    "where": places.where(ll[0], ll[1], []) if places else None})
        if len(top) == TOP_LIMB:
            break
    return {"day": m["day"], "as_of": m["as_of"], "measure": LIMB_LABEL, "note": LIMB_NOT_GROUND,
            "satellites": m["satellites"], "cells": len(m["cells"]), "file": m["file"], "top": top,
            "rule": f"each cell's highest hourly 95th percentile (10 or more values); cells with more than "
                    f"{RFI_MAX:g} of that hour's values RFI-flagged left out; top {TOP_LIMB}, at least "
                    f"{LIMB_SPACING_KM:,.0f} km apart"}


def roti_card(d):
    m = roti_map(d)
    st = sorted((s for s in m["stations"] if s["max_p95"] is not None), key=lambda s: -s["max_p95"])
    return {"day": m["day"], "as_of": m["as_of"], "measure": ROTI_LABEL, "note": ROTI_NOT_S4, "units": m["units"],
            "missing": m["missing"], "file": m["file"],
            "stations": [{k: s[k] for k in ("id", "place", "lat", "lon", "max_p95", "hour", "lst", "hours")} for s in st]}


def card(release, places=None):
    """The board's swx section. Raises if neither file exists yet (board.py lists that under problems)."""
    out = {}
    d = _newest(release, "cosmic2-limb-s4")
    if d:
        out["limb"] = limb_card(d, places)
    d = _newest(release, "ground-roti")
    if d:
        out["roti"] = roti_card(d)
    if not out:
        raise ValueError("no space weather files yet")
    return out
