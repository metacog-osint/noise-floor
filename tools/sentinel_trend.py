#!/usr/bin/env python3
"""sentinel_trend.py: a box-level trend and map from the Sentinel navigation-receiver index (step E5 of
docs/space-sensors-plan.md). Areas, references, comparison boxes, places and events come from a private config
(watch configuration never lives in this repo); outputs go where --out says.

Commands
  series --config CFG --area ID DAYS... --out DIR   per day and per week (Monday-Sunday): scored epochs, units, median
                                                    index, share of epochs at <= -1 dB and <= -3 dB, for the area, each
                                                    reference and each comparison box; the area minus the pooled
                                                    references is the anomaly -> DIR/<ID>_daily.csv, _weekly.csv, .json
  map --config CFG --area ID DAYS... --out DIR      median index per res-2 cell over the area padded by map_pad_deg
                                                    -> DIR/<ID>_map_<first>_<last>.csv and .png
  chart --config CFG --area ID --out DIR            the weekly and daily series with the config's events and Kp >= 5
                                                    days -> DIR/<ID>_trend.png (reads the series files)
DAYS are YYYY-MM-DD or FIRST..LAST (GPS days with epoch files from tools/sentinel_rfi.py epochs).

The index is E2's (tools/sentinel_rfi.py): the median drop in GPS L1 signal strength below the unit-day baseline over
an epoch's links, in dB, by where the spacecraft was. Validation (docs/validation/sentinel-gnss.md): a regional sensor
about 2,000 km across, not a cell map; inland Australia reads about -1 dB for an unknown reason.

Config (JSON): focus_areas [{id, name, box}], references [{id, name, box}], comparisons [{id, name, box}],
map_pad_deg, places [{name, lat, lon}], events [{date, label, source}]. Boxes are [lat_min, lat_max, lon_min, lon_max];
a box whose lon_min > lon_max crosses 180 degrees.
"""
import argparse
import csv
import datetime as dt
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import sentinel_gnss as SG  # noqa: E402

EPOCH_DIR = os.path.join(SG.DATA, "epochs")
LAND = os.path.join(ROOT, "data", "cache", "ne_50m_land.geojson")
DEGRADED_DB, STRONG_DB = -1.0, -3.0
CAPTION = ("Where Sentinel-1/2/3 navigation receivers (693-815 km) measured weaker GPS L1 signals: the median drop "
           "below each unit-day's baseline, by the spacecraft's position, not the emitter's. Regional, about 2,000 km "
           "across (validation: Baltic AUC 0.917). Between about 60 and 160 deg E it reads 0.5-1 dB low even over empty "
           "ocean, probably from BeiDou and QZSS signals overhead (unverified), so a drop there is not jamming by "
           "itself. "
           "Jamming, not spoofing. About six days behind. Contains modified Copernicus Sentinel data {year}; orbital "
           "data USSPACECOM (space-track.org).")


def in_box(lat, lon, b):
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    lon_ok = ((lon >= b[2]) & (lon <= b[3])) if b[2] <= b[3] else ((lon >= b[2]) | (lon <= b[3]))
    return (lat >= b[0]) & (lat <= b[1]) & lon_ok


def pad(b, deg):
    lo, hi = b[2] - deg, b[3] + deg
    wrap = lambda x: ((x + 180.0) % 360.0) - 180.0
    return [max(b[0] - deg, -90.0), min(b[1] + deg, 90.0), wrap(lo), wrap(hi)]


def load_day(day, cols=("unit", "lat", "lon", "cell", "present", "d_l1")):
    import pyarrow.parquet as pq
    p = os.path.join(EPOCH_DIR, f"{day}.parquet")
    if not os.path.exists(p):
        return None
    T = pq.read_table(p, columns=list(cols))
    out = {k: np.asarray(T.column(k).to_numpy(zero_copy_only=False)) for k in cols}
    for k in ("unit", "cell"):
        if k in out:
            out[k] = out[k].astype(str)
    return out


def stats(d, units):
    """Summary of scored epoch values d (dB)."""
    d = np.asarray(d, float)
    if not len(d):
        return {"epochs": 0, "units": 0, "median": None, "deg1": None, "deg3": None}
    return {"epochs": int(len(d)), "units": int(len(set(units))), "median": round(float(np.median(d)), 3),
            "deg1": round(float(np.mean(d <= DEGRADED_DB)), 4), "deg3": round(float(np.mean(d <= STRONG_DB)), 4)}


def week_start(day):
    return day - dt.timedelta(days=day.weekday())


def boxes_of(cfg, area):
    a = next((x for x in cfg.get("focus_areas", []) if x["id"] == area), None)
    if a is None:
        raise SystemExit(f"no focus area '{area}' in the config")
    return a, cfg.get("references", []), cfg.get("comparisons", [])


def series(cfg, area, days):
    a, refs, comps = boxes_of(cfg, area)
    named = [("area", a)] + [("ref", r) for r in refs] + [("cmp", c) for c in comps]
    daily, weekly_acc = [], {}
    for day in days:
        e = load_day(day)
        if e is None:
            continue
        ok = e["present"] & np.isfinite(e["d_l1"]) & np.isfinite(e["lat"])
        row = {"day": str(day), "week": str(week_start(day))}
        ref_vals = []
        for kind, b in named:
            m = ok & in_box(e["lat"], e["lon"], b["box"])
            row[b["id"]] = stats(e["d_l1"][m], e["unit"][m])
            acc = weekly_acc.setdefault(str(week_start(day)), {}).setdefault(b["id"], [[], [], set()])
            acc[0].append(e["d_l1"][m])
            acc[1].append(e["unit"][m])
            acc[2].add(str(day))
            if kind == "ref":
                ref_vals.append(e["d_l1"][m])
        rv = np.concatenate(ref_vals) if ref_vals else np.zeros(0)
        row["reference"] = stats(rv, [])
        row["anomaly"] = (round(row[a["id"]]["median"] - row["reference"]["median"], 3)
                          if row[a["id"]]["median"] is not None and row["reference"]["median"] is not None else None)
        daily.append(row)
    weekly = []
    for wk in sorted(weekly_acc):
        row = {"week": wk}
        ref_vals = []
        for kind, b in named:
            v = np.concatenate(weekly_acc[wk][b["id"]][0])
            row[b["id"]] = stats(v, np.concatenate(weekly_acc[wk][b["id"]][1]))
            row[b["id"]]["days"] = len(weekly_acc[wk][b["id"]][2])
            if kind == "ref":
                ref_vals.append(v)
        rv = np.concatenate(ref_vals) if ref_vals else np.zeros(0)
        row["reference"] = stats(rv, [])
        row["anomaly"] = (round(row[a["id"]]["median"] - row["reference"]["median"], 3)
                          if row[a["id"]]["median"] is not None and row["reference"]["median"] is not None else None)
        weekly.append(row)
    return {"area": a, "references": refs, "comparisons": comps, "daily": daily, "weekly": weekly}


def write_series(res, area, out):
    os.makedirs(out, exist_ok=True)
    ids = [res["area"]["id"]] + [r["id"] for r in res["references"]] + [c["id"] for c in res["comparisons"]]
    for kind in ("daily", "weekly"):
        key = "day" if kind == "daily" else "week"
        with open(os.path.join(out, f"{area}_{kind}.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            head = [key] + (["days"] if kind == "weekly" else [])
            for i in ids + ["reference"]:
                head += [f"{i}_median_db", f"{i}_deg1", f"{i}_deg3", f"{i}_epochs", f"{i}_units"]
            w.writerow(head + ["anomaly_db"])
            for r in res[kind]:
                line = [r[key]] + ([r[res["area"]["id"]].get("days")] if kind == "weekly" else [])
                for i in ids + ["reference"]:
                    s = r[i]
                    line += [s["median"], s["deg1"], s["deg3"], s["epochs"], s["units"]]
                w.writerow(line + [r["anomaly"]])
    with open(os.path.join(out, f"{area}.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)


def cell_map(cfg, area, days):
    import h3
    a, _, _ = boxes_of(cfg, area)
    box = pad(a["box"], float(cfg.get("map_pad_deg", 10.0)))
    vals = {}
    for day in days:
        e = load_day(day)
        if e is None:
            continue
        ok = e["present"] & np.isfinite(e["d_l1"]) & in_box(e["lat"], e["lon"], box) & (e["cell"] != "")
        for c, v in zip(e["cell"][ok], e["d_l1"][ok]):
            vals.setdefault(c, []).append(float(v))
    rows = []
    for c, v in vals.items():
        lat, lon = h3.cell_to_latlng(c)
        rows.append({"h3": c, "lat": round(lat, 3), "lon": round(lon, 3), "epochs": len(v),
                     "median_db": round(float(np.median(v)), 3), "deg1": round(float(np.mean(np.array(v) <= -1.0)), 3)})
    return box, sorted(rows, key=lambda r: r["h3"])


def _lon_plot(lon, box):
    """Longitude for plotting: continuous across 180 when the box crosses it."""
    lon = np.asarray(lon, float)
    return np.where(lon < 0, lon + 360.0, lon) if box[2] > box[3] or box[3] > 170 else lon


def land_in(box):
    """Natural Earth land clipped to the box, as plot rings (lon continuous across 180 when the box crosses it)."""
    from shapely.geometry import box as sbox, shape
    from shapely.ops import unary_union
    if not os.path.exists(LAND):
        return []
    land = unary_union([shape(f["geometry"]) for f in json.load(open(LAND, encoding="utf-8"))["features"]])
    parts = ([(box[2], box[3], 0.0)] if box[2] <= box[3] else [(box[2], 180.0, 0.0), (-180.0, box[3], 360.0)])
    rings = []
    for lo, hi, shift in parts:
        g = land.intersection(sbox(lo, box[0], hi, box[1]))
        for p in getattr(g, "geoms", [g]):
            if p.is_empty or p.geom_type != "Polygon":
                continue
            xy = np.asarray(p.exterior.coords)
            rings.append(np.c_[xy[:, 0] + shift, xy[:, 1]])
    return rings


def draw_map(cfg, area, box, rows, days, path):
    import h3
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    from matplotlib.colors import TwoSlopeNorm
    xl = _lon_plot([box[2], box[3]], box)
    aspect = 1.0 / np.cos(np.radians((box[0] + box[1]) / 2))
    w_deg, h_deg = abs(xl[1] - xl[0]), box[1] - box[0]
    fig_w = 9.0
    fig, ax = plt.subplots(figsize=(fig_w, min(11.0, fig_w * 0.82 * h_deg * aspect / w_deg + 1.6)), dpi=150)
    ax.add_collection(PolyCollection(land_in(box), facecolor="#e9e9e4", edgecolor="#8a8a82", linewidth=0.5,
                                     zorder=1))
    hexes, cols = [], []
    for r in rows:
        bnd = np.asarray(h3.cell_to_boundary(r["h3"]))
        lon = _lon_plot(bnd[:, 1], box)
        if lon.max() - lon.min() > 180:
            continue
        hexes.append(np.c_[lon, bnd[:, 0]])
        cols.append(r["median_db"])
    pc = PolyCollection(hexes, array=np.clip(cols, -2, 1), cmap=plt.get_cmap("RdBu"),
                        norm=TwoSlopeNorm(vmin=-2.0, vcenter=0.0, vmax=1.0), edgecolor="none", alpha=0.6, zorder=2)
    ax.add_collection(pc)
    a = next(x for x in cfg["focus_areas"] if x["id"] == area)
    b = a["box"]
    bl = _lon_plot([b[2], b[3]], box)
    ax.plot([bl[0], bl[1], bl[1], bl[0], bl[0]], [b[0], b[0], b[1], b[1], b[0]], color="#222", lw=1.2, zorder=3)
    for p in cfg.get("places", []):
        x = float(_lon_plot([p["lon"]], box)[0])
        ax.plot(x, p["lat"], "o", ms=3, color="#111", zorder=4)
        ax.annotate(p["name"], (x, p["lat"]), xytext=(4, 3), textcoords="offset points", fontsize=7, zorder=4)
    ax.set_xlim(min(xl), max(xl))
    ax.set_ylim(box[0], box[1])
    ax.set_aspect(aspect)
    ax.set_xticks(ax.get_xticks())
    ax.set_xticklabels([f"{t if t <= 180 else t - 360:.0f}" for t in ax.get_xticks()])
    ax.set_xlim(min(xl), max(xl))
    cb = fig.colorbar(pc, ax=ax, fraction=0.04, pad=0.02, extend="both")
    cb.set_label("GPS L1 signal-strength change, dB (median per ~300 km cell)", fontsize=8)
    n_days = len(days)
    ax.set_title(f"{a['name']}\nSentinel navigation receivers, {days[0]:%d %b %Y} to {days[-1]:%d %b %Y} "
                 f"({n_days} days)", fontsize=9)
    ax.set_xlabel("longitude (deg; east positive)", fontsize=8)
    ax.set_ylabel("latitude (deg N)", fontsize=8)
    fig.text(0.01, 0.005, CAPTION.format(year=days[-1].year), fontsize=6, wrap=True, va="bottom")
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(path)
    plt.close(fig)


def draw_chart(cfg, area, res, kp_days, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    a = res["area"]
    fig, ax = plt.subplots(figsize=(11, 5.6), dpi=150)
    d_days = [dt.date.fromisoformat(r["day"]) for r in res["daily"]]
    ax.plot(d_days, [r[a["id"]]["median"] for r in res["daily"]], ".", color="#2b6cb0", ms=4, alpha=0.6,
            label=f"{a['name']}, daily median")
    wk = [dt.date.fromisoformat(r["week"]) + dt.timedelta(days=3) for r in res["weekly"]]
    ax.plot(wk, [r[a["id"]]["median"] for r in res["weekly"]], "-o", color="#1a365d", lw=2, ms=5,
            label=f"{a['name']}, weekly median")
    ax.plot(wk, [r["reference"]["median"] for r in res["weekly"]], "-s", color="#718096", lw=1.2, ms=4,
            label="quiet references (pooled), weekly")
    styles = ["-^", "-v", "-d", "-p"]
    colors = ["#c05621", "#2f855a", "#6b46c1", "#b7791f"]
    for i, c in enumerate(res["comparisons"]):
        ax.plot(wk, [r[c["id"]]["median"] for r in res["weekly"]], styles[i % 4], color=colors[i % 4], lw=1, ms=4,
                alpha=0.85, label=f"{c['name']} (comparison), weekly")
    ax.axhline(0, color="#999", lw=0.8)
    ax.axhline(DEGRADED_DB, color="#999", lw=0.8, ls="--")
    lo, hi = min(d_days + wk), max(d_days + wk)
    for d in kp_days:
        x = dt.date.fromisoformat(d)
        if lo <= x <= hi:
            ax.axvspan(x, x + dt.timedelta(days=1), color="#f6e05e", alpha=0.35, lw=0)
    for ev in cfg.get("events", []):
        x = dt.date.fromisoformat(ev["date"])
        if lo - dt.timedelta(days=3) <= x <= hi + dt.timedelta(days=3):
            ax.axvline(x, color="#805ad5", lw=1, ls=":")
            ax.annotate(ev["label"], (x, ax.get_ylim()[1]), rotation=90, fontsize=6.5, va="top", ha="right",
                        color="#553c9a")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.set_ylabel("GPS L1 signal-strength change, dB (median of epochs in the box)")
    ax.set_title(f"{a['name']}: interference seen by Sentinel navigation receivers", fontsize=10)
    ax.legend(fontsize=7, loc="lower left")
    fig.text(0.01, 0.005, CAPTION.format(year=hi.year) + " Shaded: Kp >= 5 (GFZ). Dotted: events from the config.",
             fontsize=6, wrap=True, va="bottom")
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(path)
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("series", "map", "chart"):
        p = sub.add_parser(name)
        p.add_argument("--config", required=True)
        p.add_argument("--area", required=True)
        p.add_argument("--out", required=True)
        if name != "chart":
            p.add_argument("days", nargs="+")
    a = ap.parse_args(argv)
    with open(a.config, encoding="utf-8") as f:
        cfg = json.load(f)
    if a.cmd == "series":
        res = series(cfg, a.area, SG.days_arg(a.days))
        write_series(res, a.area, a.out)
        print(json.dumps({"days": len(res["daily"]), "weeks": len(res["weekly"]), "out": a.out}))
    elif a.cmd == "map":
        days = [d for d in SG.days_arg(a.days) if os.path.exists(os.path.join(EPOCH_DIR, f"{d}.parquet"))]
        box, rows = cell_map(cfg, a.area, days)
        os.makedirs(a.out, exist_ok=True)
        stem = os.path.join(a.out, f"{a.area}_map_{days[0]}_{days[-1]}")
        with open(stem + ".csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        draw_map(cfg, a.area, box, rows, days, stem + ".png")
        print(json.dumps({"cells": len(rows), "days": len(days), "png": stem + ".png"}))
    else:
        import sentinel_rfi as R
        with open(os.path.join(a.out, f"{a.area}.json"), encoding="utf-8") as f:
            res = json.load(f)
        first = dt.date.fromisoformat(res["daily"][0]["day"])
        last = dt.date.fromisoformat(res["daily"][-1]["day"])
        try:
            kp = R.kp_storm_days(first, last)
        except Exception as ex:
            print(f"Kp not fetched: {ex}", file=sys.stderr)
            kp = []
        path = os.path.join(a.out, f"{a.area}_trend.png")
        draw_chart(cfg, a.area, res, kp, path)
        print(json.dumps({"png": path, "kp5_days": kp}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
