#!/usr/bin/env python3
"""sun_alerts.py: sun-outage alerts at deploy time, for the site's Atom feed and the home-page board.

The board (site_src/dash.js) predicts outages and reads NOAA live; this script makes the same judgements for the last
seven days so they last: written to site/data/sun/alerts.json, which tools/site_days.py turns into feed entries.

  predicted   sun-outage windows for the public watch list (site/data/sun/targets.json: orbital slots x cities), for a
              0.9 m Ku-band dish (threshold = half the 3 dB beamwidth + the sun's radius), from tools/sun_transit.py's
              ephemeris and geometry, minute by minute.
  observed    NOAA SWPC (US public domain): fixed-frequency radio bursts (edited events, type RBR: frequency MHz, peak
              sfu) and the daily RSTN solar radio flux.
  alerts      kind "burst-in-window"   a radio burst at 4 GHz or above inside a predicted window (level: both)
              kind "bright-sun"        a day with predicted windows when the Ku-band flux (15.4 GHz, else 8.8 GHz) was
                                       at least 1.25x its 30-day median (level: both)
              kind "l-burst"           a radio burst near 1.4 GHz (1-2 GHz) of 1,000 sfu or more (level: observed)
              kind "report"            a curated outage report (site/data/sun/reports.json) inside or outside its
                                       predicted window
Thresholds are provisional (docs/design/sun-outage.md).

  python tools/sun_alerts.py                    # fetch NOAA, write site/data/sun/alerts.json
  python tools/sun_alerts.py --noaa-dir DIR     # use saved NOAA files (solar-radio-flux.json, edited_events.json)
"""
import argparse, json, math, os, sys, time, urllib.request
from datetime import datetime, timedelta, timezone

try:
    import numpy as np                     # faster; the deploy runner may not have it, so plain Python works too
except ImportError:
    np = None

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import sun_transit as S  # noqa: E402

SUN_DIR = os.path.join(ROOT, "site", "data", "sun")
SWPC = "https://services.swpc.noaa.gov/"
DISH_M, BAND_GHZ, SUN_RADIUS = 0.9, 12.0, 0.267
TH = 0.5 * 70 * (0.299792458 / BAND_GHZ) / DISH_M + SUN_RADIUS
ELEVATED, L_BURST, DAYS = 1.25, 1000.0, 7
SITE_URL = "https://noisefloor.theintelligence.company"


def fetch(path, noaa_dir=None, tries=3):
    if noaa_dir:
        p = os.path.join(noaa_dir, os.path.basename(path))
        return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(SWPC + path, headers={"User-Agent": "noise-floor"}), timeout=60) as r:
                return json.load(r)
        except Exception as e:  # NOAA hiccups: try again, then go without
            print(f"sun_alerts: {path}: {e}", file=sys.stderr)
            time.sleep(3 * (k + 1))
    return None


def utc(s):
    s = s.replace(" ", "T")
    return datetime.fromisoformat(s if s.endswith(("Z", "+00:00")) else s + "+00:00").astimezone(timezone.utc)


def sat_vec(lat_d, lon_d, sat_lon_d):
    """Earth-fixed unit vector from receiver to satellite, and elevation (deg); as satDirection in sunoutage.js."""
    lat, lon, sl = math.radians(lat_d), math.radians(lon_d), math.radians(sat_lon_d)
    n = S.A_WGS / math.sqrt(1 - S.E2 * math.sin(lat) ** 2)
    st = (n * math.cos(lat) * math.cos(lon), n * math.cos(lat) * math.sin(lon), n * (1 - S.E2) * math.sin(lat))
    v = (S.R_GEO * math.cos(sl) - st[0], S.R_GEO * math.sin(sl) - st[1], -st[2])
    m = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    v = (v[0] / m, v[1] / m, v[2] / m)
    up = math.cos(lat) * math.cos(lon) * v[0] + math.cos(lat) * math.sin(lon) * v[1] + math.sin(lat) * v[2]
    return v, math.degrees(math.asin(up))


def pairs_from(targets):
    out = []
    for c in targets["cities"]:
        for s in targets["slots"]:
            v, elev = sat_vec(c["lat"], c["lon"], s["lon"])
            if elev >= 5:
                out.append({"city": c["name"], "slot": s["name"], "lat": c["lat"], "lon": c["lon"], "sat_lon": s["lon"], "v": v})
    return out


def windows(pairs, t0, days, th=TH):
    """Minute-resolution outage intervals [(start, end, pair)] over `days` UTC days from t0 (datetime at 00:00 UTC)."""
    if not pairs:
        return []
    cos_th, out = math.cos(math.radians(th)), []
    for d in range(days):
        day0 = t0 + timedelta(days=d)
        sun = [S.sun_ecef(day0 + timedelta(minutes=m)) for m in range(1440)]
        if np is not None:
            inside = (np.array([p["v"] for p in pairs]) @ np.array(sun).T) > cos_th      # (pairs, minutes)
            rows = [(i, inside[i].tolist()) for i in np.nonzero(inside.any(axis=1))[0]]
        else:
            rows = []
            for i, p in enumerate(pairs):
                vx, vy, vz = p["v"]
                row = [vx * s[0] + vy * s[1] + vz * s[2] > cos_th for s in sun]
                if any(row):
                    rows.append((i, row))
        for i, row in rows:
            start = None
            for m, on in enumerate(row + [False]):
                if on and start is None:
                    start = m
                elif not on and start is not None:
                    out.append((day0 + timedelta(minutes=start), day0 + timedelta(minutes=m), pairs[int(i)]))
                    start = None
    return sorted(out, key=lambda w: w[0])


def bursts_from(events, since):
    out = []
    for e in events or []:
        if e.get("type") != "RBR":
            continue
        try:
            f, peak = float(e["frequency"]), float(e["particulars1"])
            tmax = utc(e.get("max_datetime") or e["begin_datetime"])
        except (KeyError, TypeError, ValueError):
            continue
        if tmax >= since:
            out.append({"f": f, "peak": peak, "t": tmax, "obs": e.get("observatory")})
    return sorted(out, key=lambda b: b["t"])


def ku_ratios(flux):
    """{UTC day: (ratio, freq)} for the Ku proxy (15.4 GHz, else 8.8 GHz): each day's mean against the file's median."""
    out = {}
    for f in (15400, 8800):
        vals = [(utc(r["time_tag"]), d["flux"]) for r in flux or [] for d in r.get("details", [])
                if d.get("frequency") == f and d.get("flux") is not None]
        if len(vals) < 10:
            continue
        srt = sorted(v for _, v in vals)
        med = float(srt[len(srt) // 2])
        byday = {}
        for t, v in vals:
            byday.setdefault(t.date().isoformat(), []).append(v)
        for day, vs in byday.items():
            out.setdefault(day, (sum(vs) / len(vs) / med, f))
    return out


def hm(t):
    return t.strftime("%Y-%m-%d %H:%M")


def make_alerts(targets, flux, events, reports, now=None):
    now = now or datetime.now(timezone.utc)
    t0 = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) - timedelta(days=DAYS - 1)
    pairs = pairs_from(targets)
    wins = windows(pairs, t0, DAYS)
    alerts = []
    # radio bursts at satcom frequencies inside predicted windows
    for b in bursts_from(events, t0):
        if b["f"] >= 4000:
            hit = [w for w in wins if w[0] <= b["t"] < w[1]]
            if hit:
                ex = hit[0][2]
                alerts.append({"kind": "burst-in-window", "level": "both", "t": b["t"].isoformat().replace("+00:00", "Z"),
                               "text": f"Radio burst at {b['f']:.0f} MHz ({b['peak']:,.0f} sfu) at {hm(b['t'])} UTC, during {len(hit)} predicted "
                                       f"sun outage{'s' if len(hit) != 1 else ''} on the watch list (e.g. {ex['slot']} from {ex['city']}): deeper fades than geometry alone predicts."})
        elif 1000 <= b["f"] <= 2000 and b["peak"] >= L_BURST:
            alerts.append({"kind": "l-burst", "level": "obs", "t": b["t"].isoformat().replace("+00:00", "Z"),
                           "text": f"Strong L-band radio burst: {b['peak']:,.0f} sfu at {b['f']:.0f} MHz, {hm(b['t'])} UTC. GNSS receivers on the "
                                   f"sunlit side can lose signal-to-noise."})
    # days with predicted windows when the sun was bright at Ku band
    ratios = ku_ratios(flux)
    for d in range(DAYS):
        day = (t0 + timedelta(days=d)).date().isoformat()
        r = ratios.get(day)
        n = sum(1 for w in wins if w[0].date().isoformat() == day)
        if r and n and r[0] >= ELEVATED:
            alerts.append({"kind": "bright-sun", "level": "both", "t": f"{day}T12:00:00Z",
                           "text": f"{day}: {n} predicted sun outages on the watch list while the sun was {r[0]:.2f}x its 30-day median at "
                                   f"{r[1] / 1000:.1f} GHz: fades deeper than usual."})
    # curated outage reports against their own predicted window
    for rep in (reports or {}).get("reports", []):
        try:
            t = utc(rep["time_utc"])
        except (KeyError, ValueError):
            continue
        if t < now - timedelta(days=30):
            continue
        v, elev = sat_vec(rep["lat"], rep["lon"], rep["satellite_lon"])
        day0 = datetime(t.year, t.month, t.day, tzinfo=timezone.utc)
        o = S.day_outage(rep["lat"], rep["lon"], S.sat_direction(rep["lat"], rep["lon"], rep["satellite_lon"])[0], day0, TH)
        inside = bool(o and o["start"] - timedelta(minutes=5) <= t <= o["end"] + timedelta(minutes=5))
        what = ("inside a predicted sun-outage window, so the loss itself is not evidence of interference" if inside else
                "outside any predicted sun-outage window, so sun transit does not explain it")
        alerts.append({"kind": "report", "level": "both" if inside else "obs", "t": t.isoformat().replace("+00:00", "Z"),
                       "link": rep.get("source_url"),
                       "text": f"Reported outage ({rep.get('source_name', 'source')}): {rep.get('summary', '')} At {hm(t)} UTC this was {what}."})
    alerts.sort(key=lambda a: a["t"], reverse=True)
    for a in alerts:
        a["id"] = f"sun-{a['kind']}-{a['t']}"
    return {"generated": now.isoformat().replace("+00:00", "Z"), "window_days": DAYS, "threshold_deg": round(TH, 3),
            "pairs": len(pairs), "predicted_windows": len(wins),
            "rules": "docs/design/sun-outage.md (provisional thresholds: flux >= 1.25x its 30-day median; L-band burst >= 1000 sfu)",
            "source": "Predictions: Noisefloor (tools/sun_transit.py geometry). Observations: NOAA SWPC (US public domain).",
            "alerts": alerts}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--noaa-dir", help="read solar-radio-flux.json and edited_events.json from here instead of NOAA")
    ap.add_argument("--out", default=os.path.join(SUN_DIR, "alerts.json"))
    a = ap.parse_args()
    targets = json.load(open(os.path.join(SUN_DIR, "targets.json"), encoding="utf-8"))
    rp = os.path.join(SUN_DIR, "reports.json")
    reports = json.load(open(rp, encoding="utf-8")) if os.path.exists(rp) else None
    flux = fetch("json/solar-radio-flux.json", a.noaa_dir)
    events = fetch("json/edited_events.json", a.noaa_dir)
    res = make_alerts(targets, flux, events, reports)
    res["noaa"] = {"flux": flux is not None, "events": events is not None}
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1, ensure_ascii=False)
    print(json.dumps({k: res[k] for k in ("generated", "pairs", "predicted_windows")} | {"alerts": len(res["alerts"]), "noaa": res["noaa"]}))


if __name__ == "__main__":
    main()
