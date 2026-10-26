/* sunoutage.js: sun-outage (sun-transit) windows for geostationary satellites, in the browser.
   A port of tools/sun_transit.py, kept numerically the same (tests/test_sunoutage.mjs compares the two):
   low-precision solar ephemeris (Meeus, about 0.01 deg), an ideal geostationary satellite at its nominal longitude, a
   WGS84 receiver at sea level. "Outage" = the sun's centre within the threshold angle of the satellite as seen from the
   receiver. The angle is taken between Earth-fixed unit vectors, so one sun position per minute serves every pair.
   NFSun.threshold(dishM, freqGHz): half the 3 dB beamwidth (70 lambda / D) plus the sun's radius, in degrees.
   NFSun.windows(lat, lon, satLon, fromDay, days, thresh): daily outages [{start, end, peak, sep, minutes}] (Date objects).
   NFSun.scan(pairs, fromMs, minutes, thresh): fast minute-by-minute scan of many pairs (for the dashboard). */
(function (root) {
  "use strict";
  var A_WGS = 6378.137, F_WGS = 1 / 298.257223563, E2 = F_WGS * (2 - F_WGS), R_GEO = 42164.17;
  var D2R = Math.PI / 180, R2D = 180 / Math.PI, SUN_RADIUS = 0.267, DAY = 86400000;

  function mod(a, n) { return ((a % n) + n) % n; }
  function unit(v) { var m = Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]); return [v[0] / m, v[1] / m, v[2] / m]; }

  // receiver -> satellite unit vector (Earth-fixed) and the elevation angle, degrees
  function satDirection(latD, lonD, satLonD) {
    var lat = latD * D2R, lon = lonD * D2R, sl = satLonD * D2R;
    var n = A_WGS / Math.sqrt(1 - E2 * Math.sin(lat) * Math.sin(lat));
    var st = [n * Math.cos(lat) * Math.cos(lon), n * Math.cos(lat) * Math.sin(lon), n * (1 - E2) * Math.sin(lat)];
    var v = unit([R_GEO * Math.cos(sl) - st[0], R_GEO * Math.sin(sl) - st[1], -st[2]]);
    var up = Math.cos(lat) * Math.cos(lon) * v[0] + Math.cos(lat) * Math.sin(lon) * v[1] + Math.sin(lat) * v[2];
    return { v: v, elev: Math.asin(up) * R2D };
  }

  // unit vector to the sun in Earth-fixed axes at time t (ms since 1970, UTC); parallax ignored
  function sunEcef(tMs) {
    var n = tMs / DAY + 2440587.5 - 2451545.0, T = n / 36525.0;
    var L0 = mod(280.46646 + 36000.76983 * T + 0.0003032 * T * T, 360);
    var M = mod(357.52911 + 35999.05029 * T - 0.0001537 * T * T, 360) * D2R;
    var C = (1.914602 - 0.004817 * T - 0.000014 * T * T) * Math.sin(M) + (0.019993 - 0.000101 * T) * Math.sin(2 * M) +
            0.000289 * Math.sin(3 * M);
    var om = (125.04 - 1934.136 * T) * D2R;
    var lam = (L0 + C - 0.00569 - 0.00478 * Math.sin(om)) * D2R;
    var eps0 = 23 + (26 + (21.448 - T * (46.815 + T * (0.00059 - T * 0.001813))) / 60) / 60;
    var eps = (eps0 + 0.00256 * Math.cos(om)) * D2R;
    var ra = Math.atan2(Math.cos(eps) * Math.sin(lam), Math.cos(lam)), dec = Math.asin(Math.sin(eps) * Math.sin(lam));
    var gmst = mod(280.46061837 + 360.98564736629 * n + 0.000387933 * T * T, 360) * D2R, ha = gmst - ra;
    return [Math.cos(dec) * Math.cos(-ha), Math.cos(dec) * Math.sin(-ha), Math.sin(dec)];
  }
  function sepDeg(v, s) { return Math.acos(Math.max(-1, Math.min(1, v[0] * s[0] + v[1] * s[1] + v[2] * s[2]))) * R2D; }

  function threshold(dishM, freqGHz) { return 0.5 * 70 * (0.299792458 / freqGHz) / dishM + SUN_RADIUS; }

  // closest approach and outage interval on one UTC day (day0 = ms at 00:00 UTC), or null; as day_outage in Python
  function dayOutage(v, day0, thresh, sunCache) {
    var best = Infinity, bm = 0;
    for (var m = 0; m < 1440; m++) {
      var s = sunCache ? sunCache[m] : sunEcef(day0 + m * 60000), d = sepDeg(v, s);
      if (d < best) { best = d; bm = m; }
    }
    if (best > thresh + 0.3) return null;
    var centre = day0 + bm * 60000, first = null, last = null, peakT = centre, peakSep = Infinity;
    for (var sec = -1200; sec <= 1200; sec += 5) {
      var t = centre + sec * 1000, d2 = sepDeg(v, sunEcef(t));
      if (d2 < thresh) { if (first === null) first = t; last = t; }
      if (d2 < peakSep) { peakSep = d2; peakT = t; }
    }
    if (first === null) return null;
    return { start: new Date(first), end: new Date(last), peak: new Date(peakT), sep: peakSep, minutes: (last - first) / 60000 + 5 / 60 };
  }
  function sunDay(day0) { var a = new Array(1440); for (var m = 0; m < 1440; m++) a[m] = sunEcef(day0 + m * 60000); return a; }
  function dayStart(ms) { return Math.floor(ms / DAY) * DAY; }

  // daily outages for one receiver and satellite over `days` UTC days from fromDay ("YYYY-MM-DD" or ms)
  function windows(lat, lon, satLon, fromDay, days, thresh) {
    var d0 = typeof fromDay === "string" ? Date.parse(fromDay + "T00:00:00Z") : dayStart(fromDay);
    var dir = satDirection(lat, lon, satLon), out = [];
    for (var k = 0; k < days; k++) {
      var o = dayOutage(dir.v, d0 + k * DAY, thresh, null);
      if (o) out.push(o);
    }
    return { elev: dir.elev, windows: out };
  }

  // many pairs, minute by minute from fromMs for `minutes`: [{pair, start, end, peak, sep}] intervals (Date objects).
  // pairs: [{lat, lon, satLon, ...}]; pairs below 5 deg elevation are skipped. One sun position per minute for all.
  function scan(pairs, fromMs, minutes, thresh) {
    var t0 = Math.floor(fromMs / 60000) * 60000, sun = new Array(minutes), out = [];
    for (var m = 0; m < minutes; m++) sun[m] = sunEcef(t0 + m * 60000);
    pairs.forEach(function (p) {
      var dir = satDirection(p.lat, p.lon, p.satLon);
      if (dir.elev < 5) return;
      var open = null;
      for (var m = 0; m < minutes; m++) {
        var d = sepDeg(dir.v, sun[m]);
        if (d < thresh) {
          if (!open) open = { pair: p, start: t0 + m * 60000, peak: t0 + m * 60000, sep: d, elev: dir.elev };
          else if (d < open.sep) { open.sep = d; open.peak = t0 + m * 60000; }
          open.end = t0 + m * 60000 + 60000;
        } else if (open) { out.push(open); open = null; }
      }
      if (open) out.push(open);
    });
    out.forEach(function (o) { o.start = new Date(o.start); o.end = new Date(o.end); o.peak = new Date(o.peak); });
    return out.sort(function (a, b) { return a.start - b.start; });
  }

  // receivers on a satellite's own meridian: the latitude band in outage on a UTC day (for the season chart)
  function latitudeBand(day0, thresh, step) {
    step = step || 0.25;
    var sun = sunDay(day0), lats = [];
    for (var lat = -75; lat <= 75; lat += step) {
      var dir = satDirection(lat, 0, 0), best = Infinity;
      for (var m = 0; m < 1440; m++) { var d = sepDeg(dir.v, sun[m]); if (d < best) best = d; }
      if (best < thresh) lats.push(lat);
    }
    if (!lats.length) return null;
    var north = lats.filter(function (x) { return x >= 0; }), south = lats.filter(function (x) { return x < 0; });
    function band(a) { return a.length ? [a[0], a[a.length - 1]] : null; }
    return { north: band(north), south: band(south) };
  }

  // quick season geometry: when the sun lines up with the satellite, the angle between them is about the difference
  // between the sun's declination and the satellite's apparent declination from the receiver (both in degrees)
  function apparentDec(lat) { return Math.asin(satDirection(lat, 0, 0).v[2]) * R2D; }
  function sunDec(tMs) { return Math.asin(sunEcef(tMs)[2]) * R2D; }

  var api = { threshold: threshold, satDirection: satDirection, sunEcef: sunEcef, dayOutage: dayOutage,
              windows: windows, scan: scan, latitudeBand: latitudeBand, apparentDec: apparentDec, sunDec: sunDec,
              SUN_RADIUS: SUN_RADIUS };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.NFSun = api;
})(typeof window !== "undefined" ? window : globalThis);
