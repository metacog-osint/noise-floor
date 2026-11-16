#!/usr/bin/env python3
"""spoof_site.py: the site's spoofing files, at deploy, from the published <day>.spoof.json and <day>.spoof-targets.json.

  python3 tools/spoof_site.py RELEASE_DIR [SITE]        # after tools/site_layers.py

- SITE/data/spoof/<day>.json (written by site_layers.py) gains `targets`, every spoofed-to cluster of the day in a
  compact form, and `unplaced`, for the map layer. Row: [lat, lon, aircraft, episodes, active episodes, first, last,
  near, r90_km, victims], victims = [[H3 res-2 region, episodes, near], ...] up to 3, where the aircraft really were.
- SITE/data/spoof/history.json: the Trends page's spoofing section. `days`: per published day, active episodes,
  aircraft and the res-4 cells where spoofed aircraft really were, by region group (the validation's region boxes,
  tools/spoof_day.py REGIONS and GROUPS; everything else is "Elsewhere"). `targets`: spoofed-to places followed from
  day to day. `new`: places with a new cluster on the newest day (new_targets()).

Everything is aggregates of the published files: no aircraft identifiers (ODbL 1.0, derived from adsb.lol). Spoofed-to
points are where receivers were shown, not where a transmitter is. Needs h3.
"""
import ast
import glob
import json
import math
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LICENCE = "ODbL 1.0; derived from adsb.lol"
TRACK_KM = 10.0          # a day's cluster belongs to a followed place if its centre is within this of the place's
NEW_MIN_AIRCRAFT = 3     # a new place needs this many aircraft on the day
NEW_LOOKBACK = 30        # ... and no cluster within TRACK_KM on any earlier day with a targets file, up to this many back
NEW_MIN_HISTORY = 7      # ... of which there must be at least this many
TABLE_MIN_AIRCRAFT_DAYS, TABLE_MIN_DAYS, TABLE_ROWS = 5, 2, 30
SERIES_DAYS = 30
USUAL_DAYS, USUAL_MIN_DAYS = 30, 7    # a place's usual level: median of its daily aircraft on up to 30 earlier days with
                                      # a targets file (0 on days it wasn't shown), from at least 7 of them
LEVEL_RATIO, LEVEL_MIN_DIFF = 2.0, 3  # above: at least 2x usual and 3 or more aircraft over it; below: at most half
                                      # and 3 or more under it; otherwise near
ABOVE_ROWS = 10
NEAR_KM = 200            # a spoofed-to place is named after the nearest listed place within this


def km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 12742.0 * math.asin(min(1.0, math.sqrt(a)))


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def regions():
    """REGIONS and GROUPS from tools/spoof_day.py, read as literals (spoof_day itself needs the detector's
    dependencies, which the deploy doesn't install)."""
    src = open(os.path.join(ROOT, "tools", "spoof_day.py"), encoding="utf-8").read()
    out = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and getattr(node.targets[0], "id", None) in ("REGIONS", "GROUPS"):
            out[node.targets[0].id] = ast.literal_eval(node.value)
    return out["REGIONS"], out["GROUPS"]


GROUP_NAMES = {"Baltic and W Russia": "Baltic and western Russia"}     # display names; "Controls" folds into Elsewhere


def group_of(lat, lon, reg, groups):
    for name, ((la0, la1, lo0, lo1), _) in reg.items():
        if la0 <= lat <= la1 and lo0 <= lon <= lo1:
            for g, members in groups.items():
                if name in members:
                    return None if g == "Controls" else GROUP_NAMES.get(g, g)
            return None
    return None


def _near(places, lat, lon, limit):
    try:
        return places.near(lat, lon, limit=limit) if places else None
    except Exception:
        return None


def victims(cells, places, top=3):
    """Res-4 victim cells [[cell, episodes, aircraft], ...] -> the res-2 regions holding most of them."""
    import h3
    by = Counter()
    for c, n, _ in cells or []:
        by[h3.cell_to_parent(c, 2)] += n
    out = []
    for r, n in by.most_common(top):
        la, lo = h3.cell_to_latlng(r)
        out.append([r, n, _near(places, la, lo, 350)])
    return out


def compact(targets, places):
    """<day>.spoof-targets.json -> (targets rows, unplaced rows) for the map (see the module docstring)."""
    rows = []
    for c in targets.get("clusters") or []:
        rows.append([c["lat"], c["lon"], c["aircraft"], c["episodes"], (c.get("classes") or {}).get("active", 0),
                     c.get("first"), c.get("last"), _near(places, c["lat"], c["lon"], NEAR_KM), c.get("r90_km"),
                     victims(c.get("victim_cells"), places)])
    un = [[u.get("reported_gs_kt"), u["aircraft"], u["episodes"], victims(u.get("victim_cells"), places)]
          for u in targets.get("unplaced") or []]
    return rows, un


def target_days(release):
    out = {}
    for f in sorted(glob.glob(os.path.join(release, "*.spoof-targets.json"))):
        t = load(f)
        if t and isinstance(t.get("clusters"), list):
            out[os.path.basename(f)[:10]] = t
    return out


def new_targets(release, places=None, tdays=None):
    """Places shown as a spoofed-to cluster on the newest day with a targets file, with NEW_MIN_AIRCRAFT or more
    aircraft, and no cluster of any size within TRACK_KM on the earlier days (up to NEW_LOOKBACK of them; at least
    NEW_MIN_HISTORY needed, else no list). An observation, not a warning."""
    tdays = tdays if tdays is not None else target_days(release)
    days = sorted(tdays)
    if not days:
        return None
    last, hist = days[-1], days[-1 - NEW_LOOKBACK:-1]
    out = {"day": last, "history_days": len(hist), "history_from": hist[0] if hist else None, "new": [],
           "km_from_aircraft": "distance from the spoofed-to place to the centre of the region where most of its aircraft "
                               "really were",
           "rule": f"a cluster of {NEW_MIN_AIRCRAFT} or more aircraft on the day, with no cluster within {TRACK_KM:g} km "
                   f"on any of the up to {NEW_LOOKBACK} earlier days with a targets file (at least {NEW_MIN_HISTORY})"}
    if len(hist) < NEW_MIN_HISTORY:
        out["note"] = f"only {len(hist)} earlier days with a targets file; {NEW_MIN_HISTORY} needed"
        return out
    seen = [(c["lat"], c["lon"]) for d in hist for c in tdays[d]["clusters"]]
    for c in tdays[last]["clusters"]:
        if c["aircraft"] < NEW_MIN_AIRCRAFT:
            continue
        if any(km(c["lat"], c["lon"], la, lo) <= TRACK_KM for la, lo in seen):
            continue
        vic = victims(c.get("victim_cells"), places)
        dist = None
        if vic:
            import h3
            dist = round(km(c["lat"], c["lon"], *h3.cell_to_latlng(vic[0][0])))
        out["new"].append({"lat": c["lat"], "lon": c["lon"], "near": _near(places, c["lat"], c["lon"], NEAR_KM),
                           "aircraft": c["aircraft"], "episodes": c["episodes"], "first": c.get("first"),
                           "last": c.get("last"), "km_from_aircraft": dist,
                           "victims": [{"region": r, "episodes": n, "near": nm} for r, n, nm in vic]})
    out["new"].sort(key=lambda x: (-x["aircraft"], x["first"] or ""))
    return out


def level(latest, earlier):
    """Newest day's count against the median of earlier days -> (usual, "above" | "near" | "below"), or (None, None)
    with fewer than USUAL_MIN_DAYS earlier days. An observation against the place's own normal, not a warning."""
    if len(earlier) < USUAL_MIN_DAYS:
        return None, None
    e = sorted(earlier)
    n = len(e)
    usual = e[n // 2] if n % 2 else (e[n // 2 - 1] + e[n // 2]) / 2
    if latest >= LEVEL_RATIO * usual and latest - usual >= LEVEL_MIN_DIFF:
        return usual, "above"
    if latest <= usual / LEVEL_RATIO and usual - latest >= LEVEL_MIN_DIFF:
        return usual, "below"
    return usual, "near"


def level_rule():
    return (f"usual level: median aircraft a day on up to {USUAL_DAYS} earlier days with a targets file (0 when not "
            f"shown; at least {USUAL_MIN_DAYS} needed); above: {LEVEL_RATIO:g}x usual or more and {LEVEL_MIN_DIFF} or "
            f"more aircraft over it; below: half or less and {LEVEL_MIN_DIFF} or more under it")


def track(tdays, places=None):
    """Follow spoofed-to places across days: each day's clusters, largest first, join the followed place whose centre
    is within TRACK_KM (the place keeps its first centre), else start a new one."""
    import h3
    days = sorted(tdays)
    tracked = []
    for d in days:
        for c in sorted(tdays[d]["clusters"], key=lambda c: -c["aircraft"]):
            best = min(tracked, key=lambda t: km(c["lat"], c["lon"], t["lat"], t["lon"]), default=None)
            if best is None or km(c["lat"], c["lon"], best["lat"], best["lon"]) > TRACK_KM:
                best = {"lat": c["lat"], "lon": c["lon"], "by_day": defaultdict(int), "victims": Counter()}
                tracked.append(best)
            best["by_day"][d] += c["aircraft"]
            for cell, n, _ in c.get("victim_cells") or []:
                best["victims"][h3.cell_to_parent(cell, 2)] += n
    recent = days[-SERIES_DAYS:]
    earlier = days[-1 - USUAL_DAYS:-1]
    rows, above = [], []
    for t in tracked:
        t["usual"], t["level"] = level(t["by_day"].get(days[-1], 0), [t["by_day"].get(d, 0) for d in earlier])
        if t["level"] == "above" and not any(t["by_day"].get(d) for d in earlier):
            t["level"] = "new"              # not used on any earlier day: new_targets() reports it, not this list
        seen = sorted(t["by_day"])
        total = sum(t["by_day"].values())
        if total < TABLE_MIN_AIRCRAFT_DAYS and len(seen) < TABLE_MIN_DAYS:
            continue
        vic = []
        for r, n in t["victims"].most_common(3):
            la, lo = h3.cell_to_latlng(r)
            vic.append(_near(places, la, lo, 350) or f"{la:.1f}, {lo:.1f}")
        row = {"lat": t["lat"], "lon": t["lon"], "near": _near(places, t["lat"], t["lon"], NEAR_KM),
               "first": seen[0], "last": seen[-1], "days": len(seen), "aircraft_days": total,
               "latest": t["by_day"].get(days[-1], 0), "series": [t["by_day"].get(d, 0) for d in recent],
               "victims": list(dict.fromkeys(vic)), "usual": t["usual"], "level": t["level"]}
        rows.append(row)
        if t["level"] == "above":
            today = Counter()               # where the newest day's aircraft at this place really were (res-2 regions)
            for c in tdays[days[-1]]["clusters"]:
                if km(c["lat"], c["lon"], t["lat"], t["lon"]) <= TRACK_KM:
                    for cell, n, _ in c.get("victim_cells") or []:
                        today[h3.cell_to_parent(cell, 2)] += n
            above.append(dict(row, regions=[[r, n] for r, n in today.most_common(3)]))
    rows.sort(key=lambda r: (-r["aircraft_days"], r["first"]))
    above.sort(key=lambda r: (-(r["latest"] - r["usual"]), r["first"]))
    totals = [sum(c["aircraft"] for c in tdays[d]["clusters"]) for d in days]
    t_usual, t_level = level(totals[-1], totals[-1 - USUAL_DAYS:-1]) if totals else (None, None)
    return {"from": days[0] if days else None, "to": days[-1] if days else None, "series_days": recent,
            "rows": rows[:TABLE_ROWS], "places": len(rows),
            "above": above[:ABOVE_ROWS], "above_count": len(above), "earlier_days": len(earlier),
            "total": {"series": totals[-SERIES_DAYS:], "latest": totals[-1] if totals else None, "usual": t_usual,
                      "level": t_level},
            "level_rule": level_rule(),
            "rule": f"clusters within {TRACK_KM:g} km of a place's first centre on any day count as the same place; "
                    f"listed with {TABLE_MIN_AIRCRAFT_DAYS} or more aircraft-days or seen on {TABLE_MIN_DAYS} or more days"}


def day_series(release):
    """Per published day: active episodes, aircraft, and res-4 victim cells by region group."""
    import h3
    reg, groups = regions()
    names = [GROUP_NAMES.get(g, g) for g in groups if g != "Controls"] + ["Elsewhere"]
    out = []
    for f in sorted(glob.glob(os.path.join(release, "*.spoof.json"))):
        s = load(f)
        if not s or "cells" not in s:
            continue
        by = Counter()
        for c, _n in s["cells"]:
            la, lo = h3.cell_to_latlng(c)
            by[group_of(la, lo, reg, groups) or "Elsewhere"] += 1
        out.append({"day": s["day"], "version": s.get("version"), "active": s.get("active"),
                    "aircraft": s.get("aircraft_with_episodes"), "cells": {n: by.get(n, 0) for n in names}})
    return out, names


def history(release, places=None, tdays=None):
    tdays = tdays if tdays is not None else target_days(release)
    days, names = day_series(release)
    return {"licence": LICENCE, "groups": names, "days": days, "targets": track(tdays, places),
            "new": new_targets(release, places, tdays),
            "method": "tools/spoof_site.py from the published <day>.spoof.json and <day>.spoof-targets.json "
                      "(tools/spoof_summary.py; docs/validation/spoofing.md). cells: H3 res-4 cells where aircraft "
                      "really were during active episodes, by the validation's region boxes. Spoofed-to places are "
                      "where receivers were shown, not where a transmitter is."}


def main():
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    release = sys.argv[1]
    site = sys.argv[2] if len(sys.argv) == 3 else os.path.join(ROOT, "site")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from board import Places
        places = Places(site)
    except Exception:
        places = None
    tdays = target_days(release)
    out = os.path.join(site, "data", "spoof")
    os.makedirs(out, exist_ok=True)
    n = 0
    for day, t in tdays.items():
        p = os.path.join(out, f"{day}.json")
        d = load(p)
        if not d:
            continue
        d["targets"], d["unplaced"] = compact(t, places)
        with open(p, "w", encoding="utf-8", newline="\n") as g:
            json.dump(d, g, ensure_ascii=False, separators=(",", ":"))
        n += 1
    h = history(release, places, tdays)
    with open(os.path.join(out, "history.json"), "w", encoding="utf-8", newline="\n") as g:
        json.dump(h, g, ensure_ascii=False, separators=(",", ":"))
    print(f"spoof_site: targets added to {n} day files; history {len(h['days'])} days, "
          f"{h['targets']['places']} followed places, {len((h['new'] or {}).get('new') or [])} new on "
          f"{(h['new'] or {}).get('day')}")


if __name__ == "__main__":
    main()
