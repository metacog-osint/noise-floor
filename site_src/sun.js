/* sun.js: the sun-outage calculator page (/sun). Uses NFSun (sunoutage.js) and the public watch list in
   /data/sun/targets.json. Everything is computed in the browser; the URL hash keeps the settings so a result can be
   shared: #lat=..&lon=..&sat=..&dish=..&band=..&from=YYYY-MM-DD&days=N */
(function () {
  "use strict";
  var form = document.getElementById("sun-form");
  if (!form || !window.NFSun) return;
  var $ = function (id) { return document.getElementById(id); };
  var CENTRAL = window.TicTime ? window.TicTime.zone() : "America/Chicago", targets = { slots: [], cities: [] }, last = null;

  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function isoDay(d) { return d.getUTCFullYear() + "-" + pad(d.getUTCMonth() + 1) + "-" + pad(d.getUTCDate()); }
  function hm(d) { return pad(d.getUTCHours()) + ":" + pad(d.getUTCMinutes()); }
  function inZone(d, tz) {
    try { return new Intl.DateTimeFormat("en-US", { timeZone: tz, hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZoneName: "short" }).format(d); }
    catch (e) { return ""; }
  }
  function lonText(x) { return Math.abs(x).toFixed(1) + "°" + (x < 0 ? "W" : "E"); }
  function latText(x) { return Math.abs(x).toFixed(1) + "°" + (x < 0 ? "S" : "N"); }
  function thresh() { return NFSun.threshold(+$("sun-dish").value || 0.9, +$("sun-band").value || 12); }
  function showThresh() { $("sun-thresh").textContent = "Outage when the sun is within " + thresh().toFixed(2) + "° of the satellite."; drawSeason(); }

  // ---------- settings <-> URL hash
  function readHash() {
    var hp = {};
    location.hash.replace(/^#/, "").split("&").forEach(function (kv) { var i = kv.indexOf("="); if (i > 0) hp[kv.slice(0, i)] = decodeURIComponent(kv.slice(i + 1)); });
    return hp;
  }
  function writeHash() {
    var h = "#lat=" + (+$("sun-lat").value).toFixed(2) + "&lon=" + (+$("sun-lon").value).toFixed(2) + "&sat=" + (+$("sun-satlon").value).toFixed(1) +
            "&dish=" + $("sun-dish").value + "&band=" + $("sun-band").value + "&from=" + $("sun-from").value + "&days=" + $("sun-days").value;
    try { history.replaceState(null, "", h); } catch (e) { /* no history API */ }
  }
  function cityAt(lat, lon) {
    for (var i = 0; i < targets.cities.length; i++) {
      var c = targets.cities[i];
      if (Math.abs(c.lat - lat) < 0.005 && Math.abs(c.lon - lon) < 0.005) return c;
    }
    return null;
  }
  function selectMatching() {
    var c = cityAt(+$("sun-lat").value, +$("sun-lon").value);
    $("sun-city").value = c ? c.name : "";
    var s = +$("sun-satlon").value, slot = targets.slots.filter(function (x) { return Math.abs(x.lon - s) < 0.05; })[0];
    $("sun-slot").value = slot ? String(slot.lon) : "";
  }

  // ---------- calculate
  function calculate() {
    var lat = +$("sun-lat").value, lon = +$("sun-lon").value, sat = +$("sun-satlon").value, th = thresh();
    if (![lat, lon, sat].every(isFinite)) return;
    var from = $("sun-from").value || isoDay(new Date()), days = +$("sun-days").value || 90;
    $("sun-busy").textContent = "Calculating…";
    setTimeout(function () {                                     // let the message paint first
      var r = NFSun.windows(lat, lon, sat, from, days, th), city = cityAt(lat, lon);
      var tz = city ? city.tz : Intl.DateTimeFormat().resolvedOptions().timeZone;
      last = { r: r, lat: lat, lon: lon, sat: sat, th: th, from: from, days: days, tz: tz, city: city };
      render(); writeHash();
      $("sun-busy").textContent = "";
    }, 20);
  }
  function render() {
    var L = last, r = L.r, where = (L.city ? L.city.name + " (" : "") + latText(L.lat) + " " + lonText(L.lon) + (L.city ? ")" : "");
    var body = document.querySelector("#sun-table tbody");
    body.textContent = "";
    if (r.elev < 0) {
      $("sun-summary").textContent = "From " + where + ", a satellite at " + lonText(L.sat) + " is below the horizon (" + r.elev.toFixed(1) + "°).";
      $("sun-table-wrap").hidden = $("sun-dl-wrap").hidden = true;
      return;
    }
    var low = r.elev < 5 ? " That is too low for most dishes." : "";
    if (!r.windows.length) {
      $("sun-summary").textContent = "From " + where + ", the satellite at " + lonText(L.sat) + " is " + r.elev.toFixed(1) + "° above the horizon." + low +
        " No sun outages between " + L.from + " and the following " + L.days + " days. Seasons fall around the equinoxes: try a longer period.";
      $("sun-table-wrap").hidden = $("sun-dl-wrap").hidden = true;
      return;
    }
    var worst = r.windows.reduce(function (a, b) { return b.sep < a.sep ? b : a; }), now = Date.now();
    var next = r.windows.filter(function (w) { return w.end.getTime() > now; })[0];
    $("sun-summary").innerHTML = "From " + esc(where) + ", the satellite at " + esc(lonText(L.sat)) + " is " + r.elev.toFixed(1) + "° above the horizon." + esc(low) +
      " <strong>" + r.windows.length + " outage day" + (r.windows.length === 1 ? "" : "s") + "</strong> in this period, worst on " + isoDay(worst.peak) +
      " (up to " + Math.round(worst.minutes) + " minutes, peak " + hm(worst.peak) + " UTC)." +
      (next ? " Next: " + isoDay(next.start) + ", " + hm(next.start) + "–" + hm(next.end) + " UTC." : "");
    r.windows.forEach(function (w) {
      var tr = document.createElement("tr");
      [isoDay(w.peak), hm(w.start), hm(w.peak), hm(w.end), Math.round(w.minutes), w.sep.toFixed(2), inZone(w.peak, L.tz), inZone(w.peak, CENTRAL)].forEach(function (v, i) {
        var td = document.createElement("td"); td.textContent = v; if (i === 4 || i === 5) td.className = "num"; tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    $("sun-table-wrap").hidden = $("sun-dl-wrap").hidden = false;
  }
  function download() {
    if (!last) return;
    var L = last, rows = [["date", "start_utc", "peak_utc", "end_utc", "minutes", "closest_deg", "receiver_lat", "receiver_lon", "satellite_lon", "threshold_deg"]];
    L.r.windows.forEach(function (w) {
      rows.push([isoDay(w.peak), w.start.toISOString(), w.peak.toISOString(), w.end.toISOString(), w.minutes.toFixed(1), w.sep.toFixed(3), L.lat, L.lon, L.sat, L.th.toFixed(3)]);
    });
    var text = "# Noisefloor sun-outage calculator (https://noisefloor.theintelligence.company/sun), computed " + new Date().toISOString() +
               ". Geometry only: ideal geostationary satellite at its nominal longitude.\n" + rows.map(function (r) { return r.join(","); }).join("\n") + "\n";
    var a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
    a.download = "sun-outages-" + L.from + ".csv";
    document.body.appendChild(a); a.click(); a.remove();
  }

  // ---------- season chart: latitude band in outage through the year (analytic: declinations at alignment)
  var appDec = null;
  function drawSeason() {
    var box = $("season-chart");
    if (!box) return;
    var th = thresh(), y0 = new Date().getUTCFullYear(), start = Date.UTC(y0, 0, 1), ndays = (Date.UTC(y0 + 1, 0, 1) - start) / 86400000;
    if (!appDec) { appDec = []; for (var lat = -75; lat <= 75; lat += 0.5) appDec.push([lat, NFSun.apparentDec(lat)]); }
    var W = Math.max(320, box.clientWidth || 640), H = 230, m = { l: 40, r: 10, t: 10, b: 26 }, iw = W - m.l - m.r, ih = H - m.t - m.b;
    var X = function (d) { return m.l + iw * d / ndays; }, Y = function (lat) { return m.t + ih * (75 - lat) / 150; };
    var NS = "http://www.w3.org/2000/svg";
    function el(name, attrs, parent) { var e = document.createElementNS(NS, name); for (var k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; }
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H });
    [-60, -30, 0, 30, 60].forEach(function (lat) {
      el("line", { x1: m.l, x2: W - m.r, y1: Y(lat), y2: Y(lat), class: "hgrid" }, svg);
      var t = el("text", { x: m.l - 6, y: Y(lat) + 4, "text-anchor": "end", class: "axis" }, svg); t.textContent = lat === 0 ? "0°" : Math.abs(lat) + "°" + (lat < 0 ? "S" : "N");
    });
    for (var mo = 0; mo < 12; mo++) {
      var d = (Date.UTC(y0, mo, 1) - start) / 86400000, t2 = el("text", { x: X(d) + 2, y: H - 8, class: "axis" }, svg);
      t2.textContent = new Date(Date.UTC(y0, mo, 1)).toLocaleString("en-US", { month: "short", timeZone: "UTC" });
    }
    var path = "";
    for (var day = 0; day < ndays; day++) {
      var sd = NFSun.sunDec(start + day * 86400000 + 43200000);
      appDec.forEach(function (p) {
        if (Math.abs(p[1] - sd) < th) path += "M" + X(day).toFixed(1) + " " + Y(p[0] + 0.25).toFixed(1) + "h" + Math.max(1, iw / ndays).toFixed(2) + "v" + (ih / 300).toFixed(2) + "h-" + Math.max(1, iw / ndays).toFixed(2) + "z";
      });
    }
    el("path", { d: path, class: "season-band" }, svg);
    var today = (Date.now() - start) / 86400000;
    el("line", { x1: X(today), x2: X(today), y1: m.t, y2: m.t + ih, class: "season-today" }, svg);
    box.textContent = ""; box.appendChild(svg);
    // today, in words
    var sdNow = NFSun.sunDec(Date.now()), inBand = appDec.filter(function (p) { return Math.abs(p[1] - sdNow) < th; }).map(function (p) { return p[0]; });
    var north = inBand.filter(function (x) { return x >= 0; }), south = inBand.filter(function (x) { return x < 0; });
    var parts = [];
    if (north.length) parts.push(north[0].toFixed(1) + "°N to " + north[north.length - 1].toFixed(1) + "°N");
    if (south.length) parts.push(Math.abs(south[south.length - 1]).toFixed(1) + "°S to " + Math.abs(south[0]).toFixed(1) + "°S");
    $("season-today").innerHTML = parts.length ? "<strong>Today</strong>, receivers at " + esc(parts.join(" and ")) +
      " see sun outages near local noon on satellites close to their own longitude (threshold " + th.toFixed(2) + "°)."
      : "<strong>Today</strong> no latitude band is in outage for satellites on the receiver's meridian (threshold " + th.toFixed(2) +
        "°): the sun is too far from the celestial equator. Seasons fall around late February to mid-March and late September to mid-October.";
  }

  // ---------- set up
  function fill(sel, items, label, value) {
    sel.innerHTML = '<option value="">Custom</option>' + items.map(function (x) { return '<option value="' + esc(value(x)) + '">' + esc(label(x)) + "</option>"; }).join("");
  }
  fetch("/data/sun/targets.json").then(function (r) { return r.ok ? r.json() : targets; }).catch(function () { return targets; }).then(function (t) {
    targets = t || targets;
    fill($("sun-city"), targets.cities, function (c) { return c.name; }, function (c) { return c.name; });
    fill($("sun-slot"), targets.slots, function (s) { return lonText(s.lon) + " · " + s.name; }, function (s) { return String(s.lon); });
    var hp = readHash(), dflt = targets.cities.filter(function (c) { return c.name === "London"; })[0] || { lat: 51.51, lon: -0.13 };
    $("sun-lat").value = isFinite(+hp.lat) && hp.lat !== undefined ? hp.lat : dflt.lat;
    $("sun-lon").value = isFinite(+hp.lon) && hp.lon !== undefined ? hp.lon : dflt.lon;
    $("sun-satlon").value = isFinite(+hp.sat) && hp.sat !== undefined ? hp.sat : 19.2;
    if (hp.dish && +hp.dish > 0) $("sun-dish").value = hp.dish;
    if (hp.band && $("sun-band").querySelector('option[value="' + hp.band + '"]')) $("sun-band").value = hp.band;
    $("sun-from").value = /^\d{4}-\d{2}-\d{2}$/.test(hp.from || "") ? hp.from : isoDay(new Date());
    if (hp.days && $("sun-days").querySelector('option[value="' + hp.days + '"]')) $("sun-days").value = hp.days;
    selectMatching(); showThresh(); calculate();
  });
  $("sun-city").addEventListener("change", function () {
    var c = targets.cities.filter(function (x) { return x.name === $("sun-city").value; })[0];
    if (c) { $("sun-lat").value = c.lat; $("sun-lon").value = c.lon; }
  });
  $("sun-slot").addEventListener("change", function () { if ($("sun-slot").value !== "") $("sun-satlon").value = $("sun-slot").value; });
  ["sun-lat", "sun-lon"].forEach(function (id) { $(id).addEventListener("input", function () { $("sun-city").value = ""; }); });
  $("sun-satlon").addEventListener("input", function () { $("sun-slot").value = ""; });
  ["sun-dish", "sun-band"].forEach(function (id) { $(id).addEventListener("input", showThresh); });
  $("sun-here").addEventListener("click", function () {
    if (!navigator.geolocation) { $("sun-busy").textContent = "This browser can't share its location."; return; }
    $("sun-busy").textContent = "Asking the browser for your location…";
    navigator.geolocation.getCurrentPosition(function (p) {
      $("sun-lat").value = p.coords.latitude.toFixed(2); $("sun-lon").value = p.coords.longitude.toFixed(2); $("sun-city").value = "";
      $("sun-busy").textContent = ""; calculate();
    }, function () { $("sun-busy").textContent = "Location not shared; enter it by hand."; }, { maximumAge: 600000, timeout: 15000 });
  });
  form.addEventListener("submit", function (ev) { ev.preventDefault(); calculate(); });
  $("sun-dl").addEventListener("click", download);
  var rt; window.addEventListener("resize", function () { clearTimeout(rt); rt = setTimeout(drawSeason, 200); });
})();
