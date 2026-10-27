/* dash.js: the home-page briefing's live rows (sun outages, solar radio, alerts, at sea). Sun outages are predicted live in the browser (NFSun, sunoutage.js) for the
   public watch list (/data/sun/targets.json); NOAA SWPC's live solar radio data (US public domain, read directly from
   services.swpc.noaa.gov) is the observed side. Alerts fire when a predicted outage meets observed evidence, or when a
   strong radio burst is observed. Thresholds are provisional and stated on the page (docs/design/sun-outage.md).
   Our own aircraft GNSS check and curated outage reports join the alerts through /data/sun/alerts.json (built at deploy). */
(function () {
  "use strict";
  var board = document.getElementById("dash");
  if (!board || !window.fetch || !window.NFSun) return;
  var $ = function (id) { return document.getElementById(id); };
  var SWPC = "https://services.swpc.noaa.gov/";
  var DISH_M = 0.9, BAND_GHZ = 12, TH = NFSun.threshold(DISH_M, BAND_GHZ);     // the board's reference dish: 0.9 m Ku
  var ELEVATED = 1.25, HIGH = 2;          // flux against its 30-day median (provisional)
  var L_BURST = 1000;                     // sfu near 1.4 GHz: GNSS receivers on the sunlit side can lose C/N0 (provisional)
  var BANDS = [[1415, "1.4 GHz (L)"], [2695, "2.7 GHz (S)"], [4995, "5.0 GHz (C)"], [8800, "8.8 GHz (X)"], [15400, "15.4 GHz (Ku)"]];

  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function hm(d) { return pad(d.getUTCHours()) + ":" + pad(d.getUTCMinutes()); }
  function dayHm(d) { return d.toISOString().slice(5, 10) + " " + hm(d); }
  var TZ = window.TicTime ? window.TicTime.zone() : "America/Chicago", HC = window.TicTime && !window.TicTime.hour12() ? "h23" : "h12";
  var CT = new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric", minute: "2-digit", hourCycle: HC, timeZoneName: "short" });
  function both(d) { return TZ === "UTC" ? hm(d) + " UTC" : hm(d) + " UTC (" + CT.format(d) + ")"; }
  function lonText(x) { return Math.abs(x).toFixed(1) + "°" + (x < 0 ? "W" : "E"); }
  function get(u) { return fetch(u, { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }); }
  function utcMs(s) { return Date.parse(/Z$|[+-]\d\d:?\d\d$/.test(s) ? s : s.replace(" ", "T") + "Z"); }

  var state = { windows: null, flux: null, bursts: null, alerts: null, deploy: null, targets: null };

  // ---------- predicted: the public list, 6 h back to 48 h ahead, one scan
  function predict(targets) {
    var pairs = [];
    targets.cities.forEach(function (c) {
      targets.slots.forEach(function (s) { pairs.push({ lat: c.lat, lon: c.lon, satLon: s.lon, city: c.name, slot: s.name, tz: c.tz }); });
    });
    var from = Date.now() - 6 * 3600000;
    return NFSun.scan(pairs, from, 54 * 60, TH);
  }
  function nextSeason(targets) {          // the next day any listed city has an outage band (meridian approximation)
    var start = Math.floor(Date.now() / 86400000) * 86400000, decs = targets.cities.map(function (c) { return [c.name, NFSun.apparentDec(c.lat)]; });
    for (var k = 0; k < 220; k++) {
      var sd = NFSun.sunDec(start + k * 86400000 + 43200000);
      for (var i = 0; i < decs.length; i++) if (Math.abs(decs[i][1] - sd) < TH) return { day: new Date(start + k * 86400000), city: decs[i][0] };
    }
    return null;
  }
  var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function dayText(d) { return d.getUTCDate() + " " + MON[d.getUTCMonth()] + " " + d.getUTCFullYear(); }
  function renderSun() {                  // one line: in outage now, the next 48 hours, or the next season
    var w = state.windows, now = Date.now(), box = $("sun-text");
    if (!w || !box) return;
    var active = w.filter(function (x) { return x.start.getTime() <= now && x.end.getTime() > now; });
    var next = w.filter(function (x) { return x.start.getTime() > now; });
    var t = active.length ? active.length + " on the watch list in outage now (e.g. " + active[0].slot + " from " + active[0].city + ")" : "None in outage now";
    if (next.length) t += "; " + next.length + " more in the next 48 hours.";
    else {
      var ns = nextSeason(state.targets);
      t += ". " + (ns ? "Next season from " + dayText(ns.day) + " (" + ns.city + ")." : "None in the next 48 hours.");
    }
    box.textContent = t;
  }

  // ---------- observed: NOAA SWPC solar radio flux, radio bursts and radio alerts
  function fluxStatus(rows) {             // latest value per frequency against the 30-day median of all observatories
    var byF = {};
    (rows || []).forEach(function (r) {
      (r.details || []).forEach(function (d) {
        if (d.flux === null || d.flux === undefined) return;
        (byF[d.frequency] = byF[d.frequency] || []).push({ t: utcMs(r.time_tag), v: +d.flux, obs: r.common_name });
      });
    });
    var out = {};
    BANDS.forEach(function (b) {
      var a = byF[b[0]]; if (!a || !a.length) return;
      var vals = a.map(function (x) { return x.v; }).sort(function (x, y) { return x - y; }), med = vals[Math.floor(vals.length / 2)];
      var latest = a.reduce(function (p, q) { return q.t > p.t ? q : p; });
      out[b[0]] = { label: b[1], latest: latest, median: med, ratio: med ? latest.v / med : null };
    });
    return out;
  }
  function burstsFrom(events) {           // RBR (fixed-frequency radio burst) events in the last 24 h: frequency (MHz), peak (sfu)
    var since = Date.now() - 86400000;
    return (events || []).filter(function (e) { return e.type === "RBR"; }).map(function (e) {
      return { t0: utcMs(e.begin_datetime), tmax: utcMs(e.max_datetime || e.begin_datetime), t1: utcMs(e.end_datetime || e.max_datetime || e.begin_datetime),
               f: +e.frequency, peak: +e.particulars1, obs: e.observatory };
    }).filter(function (b) { return b.t1 >= since && isFinite(b.f) && isFinite(b.peak); }).sort(function (a, b) { return b.tmax - a.tmax; });
  }
  function radioAlerts(alerts) {          // SWPC radio messages in the last 24 h: 10 cm burst summaries, Type II and IV sweeps
    var since = Date.now() - 86400000, codes = { SUM10R: "10 cm radio burst", ALTTP2: "Type II radio emission", ALTTP4: "Type IV radio emission" };
    return (alerts || []).map(function (a) {
      var m = /Message Code: (\w+)/.exec(a.message || ""), code = m ? m[1] : "";
      var peak = /Peak Flux: ([\d,]+) sfu/.exec(a.message || ""), vel = /Estimated Velocity: ([\d,]+) km\/s/.exec(a.message || "");
      return { code: code, what: codes[code], t: utcMs(a.issue_datetime), peak: peak ? peak[1] : null, vel: vel ? vel[1] : null };
    }).filter(function (a) { return a.what && a.t >= since; }).sort(function (a, b) { return b.t - a.t; });
  }
  function renderSolar() {
    var f = state.flux, box = $("dsolar-body"), line = $("radio-text");
    if (!box) return;
    if (!f) { box.innerHTML = '<p class="small">NOAA data not loaded yet, or NOAA is not answering.</p>'; return; }
    var h = '<table><thead><tr><th>Frequency</th><th class="num">Latest, sfu</th><th class="num">Against 30-day median</th></tr></thead><tbody>';
    var worst = null;
    BANDS.forEach(function (b) {
      var x = f[b[0]]; if (!x) return;
      var cls = x.ratio >= HIGH ? "lvl lvl-high" : x.ratio >= ELEVATED ? "lvl lvl-elev" : "lvl";
      var word = x.ratio >= HIGH ? "high" : x.ratio >= ELEVATED ? "elevated" : "normal";
      if (x.ratio && (!worst || x.ratio > worst.ratio)) worst = { ratio: x.ratio, word: word, label: x.label };
      h += "<tr><td>" + esc(x.label) + '</td><td class="num">' + Math.round(x.latest.v) + '</td><td class="num"><span class="' + cls + '">' +
           (x.ratio ? x.ratio.toFixed(2) + "×, " + word : "–") + "</span></td></tr>";
    });
    h += "</tbody></table>";
    if (line) line.textContent = worst && worst.word !== "normal" ? "Solar radio " + worst.word + " at " + worst.label + "." : "Solar radio normal.";
    var b = state.bursts;
    if (b === null) h += '<p class="small">Radio bursts: loading…</p>';
    else if (!b.length) h += '<p class="small">No fixed-frequency radio bursts reported in the last 24 hours.</p>';
    else {
      var strongest = b.slice().sort(function (x, y) { return y.peak - x.peak; }).slice(0, 4);
      h += '<p class="small">' + b.length + " radio burst" + (b.length === 1 ? "" : "s") + " in the last 24 hours. Strongest:</p><ul>" +
        strongest.map(function (x) { return "<li>" + esc(dayHm(new Date(x.tmax))) + " UTC: " + x.f + " MHz, " + x.peak.toLocaleString("en-US") + " sfu</li>"; }).join("") + "</ul>";
    }
    var ra = state.alerts || [];
    if (ra.length) h += '<p class="small">NOAA radio alerts (24 h): ' + ra.slice(0, 3).map(function (a) {
      return esc(a.what) + " " + esc(dayHm(new Date(a.t))) + " UTC" + (a.peak ? " (" + esc(a.peak) + " sfu)" : "") + (a.vel ? " (" + esc(a.vel) + " km/s)" : "");
    }).join("; ") + ".</p>";
    box.innerHTML = h;
  }

  // ---------- alerts: predicted and observed together
  function bandFlux(fMHz) {               // the flux record that best matches a downlink band
    var f = state.flux; if (!f) return null;
    return fMHz >= 10000 ? (f[15400] || f[8800]) : fMHz >= 3000 ? f[4995] : f[1415];
  }
  function computeAlerts() {
    var out = [], now = Date.now(), w = state.windows || [], b = state.bursts || [];
    var ku = bandFlux(12000);
    var recent = w.filter(function (x) { return x.end.getTime() > now - 6 * 3600000 && x.start.getTime() <= now + 60000; });
    // 1. a predicted outage now, with the sun observed brighter than usual at Ku band
    var activeNow = recent.filter(function (x) { return x.end.getTime() > now; });
    if (activeNow.length && ku && ku.ratio >= ELEVATED) {
      out.push({ level: "both", text: activeNow.length + " predicted outage" + (activeNow.length === 1 ? "" : "s") + " on the list now, and the sun is " +
        ku.ratio.toFixed(2) + "× its 30-day median at " + ku.label + ": fades deeper than usual. Example: " + activeNow[0].slot + " from " + activeNow[0].city + "." });
    }
    // 2. a radio burst at satcom frequencies during a predicted outage window
    b.filter(function (x) { return x.f >= 4000; }).forEach(function (x) {
      var hit = recent.filter(function (wn) { return x.tmax >= wn.start.getTime() && x.tmax <= wn.end.getTime(); });
      if (hit.length) out.push({ level: "both", text: "Radio burst at " + x.f + " MHz (" + x.peak.toLocaleString("en-US") + " sfu) at " + dayHm(new Date(x.tmax)) +
        " UTC, during " + hit.length + " predicted outage" + (hit.length === 1 ? "" : "s") + " (e.g. " + hit[0].slot + " from " + hit[0].city + ")." });
    });
    // 3. a strong L-band burst: GNSS on the sunlit side
    b.filter(function (x) { return x.f >= 1000 && x.f <= 2000 && x.peak >= L_BURST; }).slice(0, 3).forEach(function (x) {
      out.push({ level: "obs", text: "Strong L-band radio burst: " + x.peak.toLocaleString("en-US") + " sfu at " + x.f + " MHz, " + dayHm(new Date(x.tmax)) +
        " UTC. GNSS receivers on the sunlit side can lose signal-to-noise; the next daily aircraft run checks for it." });
    });
    // 4. from the deploy-time file: aircraft GNSS checks and curated outage reports matched to predicted windows
    ((state.deploy && state.deploy.alerts) || []).filter(function (a) { return a.kind === "aircraft" || a.kind === "report"; })   // the rest is computed live above
      .forEach(function (a) { out.push({ level: a.level || "obs", text: a.text, link: a.link }); });
    return out;
  }
  function renderAlerts() {
    var a = computeAlerts(), box = $("dalerts-body"), top = $("alerts");
    if (!box) return;
    if (top) {
      top.hidden = !a.length;
      top.textContent = a.length ? "Sun-outage alert: " + a[0].text + (a.length > 1 ? " (" + (a.length - 1) + " more below)" : "") : "";
    }
    if (!a.length) {
      var w = state.windows || [], soon = w.filter(function (x) { return x.start.getTime() > Date.now(); }).length;
      box.innerHTML = "<p><strong>No alerts.</strong> " + (soon ? soon + " predicted sun outages on the list in the next 48 hours, but none meets observed evidence"
        : "No predicted outage meets observed evidence") + ", and there was no strong L-band radio burst in the last 24 hours.</p>";
      return;
    }
    box.innerHTML = "<ul>" + a.map(function (x) {
      var tag = x.level === "both" ? '<span class="lvl lvl-high">predicted and observed</span>' : '<span class="lvl lvl-elev">observed</span>';
      return "<li>" + tag + " " + esc(x.text) + (x.link ? ' <a href="' + esc(x.link) + '">Source</a>' : "") + "</li>";
    }).join("") + "</ul>";
  }
  function renderAll() { renderSun(); renderSolar(); renderAlerts(); var u = $("dash-updated"); if (u) u.textContent = "Updated " + both(new Date()) + "."; }

  // ---------- Sea card
  get("/data/vessels/gnss_at_sea.json").then(function (g) {
    if (!g) return;
    var top = (g.by_area || []).slice().sort(function (a, b) { return b.vessels - a.vessels; })[0];
    var box = $("sea-text");
    if (box) box.textContent = g.affected_vessels + " ships in Finnish waters showed GNSS interference in the last collection" +
      (top ? ", most in " + top.area + " (" + top.vessels + ")" : "") + ".";
  });

  // ---------- load
  get("/data/sun/targets.json").then(function (t) {
    if (!t) { var sb = $("sun-text"); if (sb) sb.textContent = "The watch list could not be loaded."; return; }
    state.targets = t;
    setTimeout(function () { state.windows = predict(t); renderAll(); }, 0);
  });
  Promise.all([get(SWPC + "json/solar-radio-flux.json"), get(SWPC + "products/alerts.json"), get("/data/sun/alerts.json")]).then(function (r) {
    state.flux = r[0] ? fluxStatus(r[0]) : null;
    state.alerts = r[1] ? radioAlerts(r[1]) : [];
    state.deploy = r[2];
    renderAll();
    var later = function (fn) {           // the event list is large: fetch it after the page has settled, within 3 s at most
      if (window.requestIdleCallback) window.requestIdleCallback(fn, { timeout: 3000 }); else setTimeout(fn, 1200);
    };
    later(function () {
      get(SWPC + "json/edited_events.json").then(function (ev) { state.bursts = ev ? burstsFrom(ev) : []; renderAll(); });
    });
  });
  setInterval(function () { if (state.windows) renderAll(); }, 60000);   // "now" moves on
})();
