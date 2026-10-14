"""Sun-transit (sun-outage) windows for GEO satellites seen from fixed receivers.

A receiver loses a GEO downlink when the sun sits close behind the satellite in the dish's beam.
Model: low-precision solar ephemeris (Meeus, ~0.01 deg), ideal geostationary satellite at its nominal
longitude, WGS84 receiver at sea level. "Outage" = sun centre within THRESH deg of the satellite.
THRESH 1.2 deg ~ half the 3 dB beamwidth of a 0.9 m Ku dish at 12 GHz (~1.9 deg) plus the sun's radius.

Usage:
  python tools/sun_transit.py                          # autumn 2026 watch list, summary table
  python tools/sun_transit.py --daily                  # one row per day
  python tools/sun_transit.py --start 2026-02-20 --end 2026-03-20
Times are computed in UTC; output adds receiver local time and US Central.
"""
import argparse
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

A_WGS, F_WGS = 6378.137, 1 / 298.257223563
E2 = F_WGS * (2 - F_WGS)
R_GEO = 42164.17  # km
CENTRAL = ZoneInfo("America/Chicago")

SATS = {  # nominal longitude, deg E
    "Yahsat 1A": 52.5,
    "Hot Bird": 13.0,
    "Astra 4A": 4.8,
    "Express-AMU1": 36.0,
    "Yamal 402": 55.0,
}
CITIES = {  # lat, lon, IANA zone
    "Tabriz": (38.08, 46.29, "Asia/Tehran"),
    "Mashhad": (36.30, 59.60, "Asia/Tehran"),
    "Tehran": (35.69, 51.39, "Asia/Tehran"),
    "Isfahan": (32.65, 51.67, "Asia/Tehran"),
    "Shiraz": (29.59, 52.58, "Asia/Tehran"),
    "Bandar Abbas": (27.18, 56.27, "Asia/Tehran"),
    "Lviv": (49.84, 24.03, "Europe/Kyiv"),
    "Kyiv": (50.45, 30.52, "Europe/Kyiv"),
    "Kharkiv": (49.99, 36.23, "Europe/Kyiv"),
    "Odesa": (46.48, 30.72, "Europe/Kyiv"),
    "St Petersburg": (59.94, 30.31, "Europe/Moscow"),
    "Moscow": (55.75, 37.62, "Europe/Moscow"),
    "Rostov-on-Don": (47.23, 39.72, "Europe/Moscow"),
}
WATCH = [
    ("Yahsat 1A", ["Tabriz", "Mashhad", "Tehran", "Isfahan", "Shiraz", "Bandar Abbas"]),
    ("Hot Bird", ["Tabriz", "Mashhad", "Tehran", "Isfahan", "Shiraz", "Bandar Abbas"]),
    ("Astra 4A", ["Lviv", "Kyiv", "Kharkiv", "Odesa"]),
    ("Express-AMU1", ["St Petersburg", "Moscow", "Rostov-on-Don"]),
    ("Yamal 402", ["St Petersburg", "Moscow", "Rostov-on-Don"]),
]


def _unit(v):
    m = math.sqrt(sum(x * x for x in v))
    return tuple(x / m for x in v)


def _ecef_to_enu(lat, lon, v):
    sl, cl, so, co = math.sin(lat), math.cos(lat), math.sin(lon), math.cos(lon)
    x, y, z = v
    return (-so * x + co * y, -sl * co * x - sl * so * y + cl * z, cl * co * x + cl * so * y + sl * z)


def sat_direction(lat_d, lon_d, sat_lon_d):
    """Unit ENU vector from receiver to satellite, and elevation in degrees."""
    lat, lon, sl = math.radians(lat_d), math.radians(lon_d), math.radians(sat_lon_d)
    n = A_WGS / math.sqrt(1 - E2 * math.sin(lat) ** 2)
    st = (n * math.cos(lat) * math.cos(lon), n * math.cos(lat) * math.sin(lon), n * (1 - E2) * math.sin(lat))
    sat = (R_GEO * math.cos(sl), R_GEO * math.sin(sl), 0.0)
    enu = _unit(_ecef_to_enu(lat, lon, tuple(a - b for a, b in zip(sat, st))))
    return enu, math.degrees(math.asin(enu[2]))


def sun_ecef(t):
    """Unit vector to the sun in Earth-fixed axes (Meeus low-precision; parallax ignored)."""
    n = t.timestamp() / 86400.0 + 2440587.5 - 2451545.0
    T = n / 36525.0
    L0 = (280.46646 + 36000.76983 * T + 0.0003032 * T * T) % 360
    M = math.radians((357.52911 + 35999.05029 * T - 0.0001537 * T * T) % 360)
    C = ((1.914602 - 0.004817 * T - 0.000014 * T * T) * math.sin(M)
         + (0.019993 - 0.000101 * T) * math.sin(2 * M) + 0.000289 * math.sin(3 * M))
    om = math.radians(125.04 - 1934.136 * T)
    lam = math.radians(L0 + C - 0.00569 - 0.00478 * math.sin(om))
    eps0 = 23 + (26 + (21.448 - T * (46.815 + T * (0.00059 - T * 0.001813))) / 60) / 60
    eps = math.radians(eps0 + 0.00256 * math.cos(om))
    ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    dec = math.asin(math.sin(eps) * math.sin(lam))
    gmst = math.radians((280.46061837 + 360.98564736629 * n + 0.000387933 * T * T) % 360)
    ha = gmst - ra
    return (math.cos(dec) * math.cos(-ha), math.cos(dec) * math.sin(-ha), math.sin(dec))


def separation(lat_d, lon_d, sat_enu, t):
    sun = _ecef_to_enu(math.radians(lat_d), math.radians(lon_d), sun_ecef(t))
    dot = max(-1.0, min(1.0, sum(a * b for a, b in zip(sat_enu, sun))))
    return math.degrees(math.acos(dot))


def day_outage(lat, lon, sat_enu, day, thresh):
    """Closest approach and outage interval (UTC) on one UTC day, or None if the sun stays outside thresh."""
    best = min(((separation(lat, lon, sat_enu, day + timedelta(minutes=m)), m) for m in range(1440)))
    if best[0] > thresh + 0.3:
        return None
    centre = day + timedelta(minutes=best[1])
    fine = [(centre + timedelta(seconds=s), separation(lat, lon, sat_enu, centre + timedelta(seconds=s)))
            for s in range(-1200, 1201, 5)]
    inside = [t for t, sep in fine if sep < thresh]
    if not inside:
        return None
    peak_t, peak_sep = min(fine, key=lambda x: x[1])
    return {"start": inside[0], "end": inside[-1], "peak": peak_t, "sep": peak_sep,
            "minutes": (inside[-1] - inside[0]).total_seconds() / 60 + 5 / 60}


def fmt(t, tz):
    return t.astimezone(tz).strftime("%H:%M")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-09-25")
    ap.add_argument("--end", default="2026-10-25")
    ap.add_argument("--threshold", type=float, default=1.2)
    ap.add_argument("--daily", action="store_true")
    a = ap.parse_args()
    d0 = datetime.fromisoformat(a.start).replace(tzinfo=timezone.utc)
    d1 = datetime.fromisoformat(a.end).replace(tzinfo=timezone.utc)

    print(f"Threshold {a.threshold} deg. Times: receiver local / UTC / US Central.\n")
    for sat, cities in WATCH:
        print(f"### {sat} ({SATS[sat]:.1f} E)\n")
        if a.daily:
            print("| Receiver | Date | Peak local | Peak UTC | Peak Central | Loss (min) | Min sep (deg) |")
            print("|---|---|---|---|---|---|---|")
        else:
            print("| Receiver | Elev. | Window | Worst day | Daily peak, local | UTC | Central | Max loss (min) |")
            print("|---|---|---|---|---|---|---|---|")
        for city in cities:
            lat, lon, zname = CITIES[city]
            tz = ZoneInfo(zname)
            enu, elev = sat_direction(lat, lon, SATS[sat])
            days = []
            d = d0
            while d <= d1:
                o = day_outage(lat, lon, enu, d, a.threshold)
                if o:
                    days.append(o)
                    if a.daily:
                        print(f"| {city} | {o['peak']:%d %b} | {fmt(o['peak'], tz)} {o['peak'].astimezone(tz):%Z} "
                              f"| {o['peak']:%H:%M} | {fmt(o['peak'], CENTRAL)} {o['peak'].astimezone(CENTRAL):%Z} "
                              f"| {o['minutes']:.0f} | {o['sep']:.2f} |")
                d += timedelta(days=1)
            if a.daily or not days:
                if not days:
                    print(f"| {city} | {elev:.0f} deg | none in range | | | | | |")
                continue
            worst = min(days, key=lambda o: o["sep"])
            p = worst["peak"]
            print(f"| {city} | {elev:.0f} deg | {days[0]['peak']:%d %b}–{days[-1]['peak']:%d %b} | {p:%d %b} "
                  f"| {fmt(p, tz)} {p.astimezone(tz):%Z} | {p:%H:%M} | {fmt(p, CENTRAL)} {p.astimezone(CENTRAL):%Z} "
                  f"| {max(o['minutes'] for o in days):.0f} |")
        print()


if __name__ == "__main__":
    main()
