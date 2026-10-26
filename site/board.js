/* Noise Floor home: the status board's cards from /data/board.json (built at deploy by tools/board.py), plus live Kp
   from NOAA SWPC (US public domain, CORS open). Sun outages, solar radio and the Sea card are drawn by dash.js. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  if (!$("dash")) return;
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function get(u) { return fetch(u, { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }); }
  function n(x) { return x == null ? "–" : Number(x).toLocaleString("en-US"); }
  function pct(x) { return x == null ? "–" : Number(x).toFixed(Math.abs(x) < 10 ? 1 : 0) + "%"; }
  function signed(x) { return x == null ? "–" : (x > 0 ? "+" : x < 0 ? "−" : "±") + Math.abs(x).toFixed(1); }
  function ll(lat, lon) { return Math.abs(lat).toFixed(1) + "°" + (lat >= 0 ? "N" : "S") + " " + Math.abs(lon).toFixed(1) + "°" + (lon >= 0 ? "E" : "W"); }
  function place(r) { return r.near ? "near " + esc(r.near) : esc(ll(r.lat, r.lon)); }
  function mapLink(day, lat, lon, text) {
    return '<a href="/map#day=' + esc(day) + "&m=jam&v=" + Number(lat).toFixed(2) + "," + Number(lon).toFixed(2) + ',6">' + text + "</a>";
  }
  function spark(series) {                 // 30 values, nulls left as gaps
    var v = series.filter(function (x) { return x != null; });
    if (v.length < 2) return "";
    var max = Math.max.apply(null, v), min = Math.min.apply(null, v), W = 90, H = 18, span = (max - min) || 1, seg = [], segs = [];
    series.forEach(function (x, i) {
      if (x == null) { if (seg.length) segs.push(seg); seg = []; return; }
      seg.push((i * W / (series.length - 1)).toFixed(1) + "," + (H - 2 - (x - min) / span * (H - 4)).toFixed(1));
    });
    if (seg.length) segs.push(seg);
    return '<svg class="spark" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="last 30 days, ' +
      min.toFixed(0) + " to " + max.toFixed(0) + '%">' + segs.map(function (s) {
        return s.length > 1 ? '<polyline points="' + s.join(" ") + '"/>' : '<circle r="1.2" cx="' + s[0].split(",")[0] + '" cy="' + s[0].split(",")[1] + '"/>';
      }).join("") + "</svg>";
  }
  function card(id, html) { var el = $(id); if (el) el.innerHTML = html; }

  function render(b) {
    var f = b.freshness || {};
    card("bsum", b.summary ? "<p>" + esc(b.summary) + "</p>" : "<p>The day's summary isn't available.</p>");

    var h = b.hotspots;
    if (h) {
      card("bhot-body", '<table class="dash-table bhot"><thead><tr><th>Area</th><th class="num">Today</th><th class="num">30-day median</th>' +
        '<th class="num">Change</th><th>Last 30 days</th></tr></thead><tbody>' + h.areas.map(function (a) {
          var c = a.change, cls = c != null && c >= 5 ? "up" : "";   // a fall is left uncoloured: it can be aircraft dropping out
          var lat = a.box ? (a.box[0] + a.box[1]) / 2 : 0, lon = a.box ? (a.box[2] + a.box[3]) / 2 : 0;
          return "<tr><td>" + mapLink(h.day, lat, lon, esc(a.name)) + '</td><td class="num">' + pct(a.today) + '</td><td class="num">' + pct(a.median30) +
            '</td><td class="num ' + cls + '">' + signed(c) + "</td><td>" + spark(a.series) + "</td></tr>";
        }).join("") + "</tbody></table>" +
        '<p class="small">Share of aircraft-hexes worse than 93 m on ' + esc(h.day) + " (UTC), live counts. Change is in percentage points against the median of the 30 days before. " +
        "A falling share can mean aircraft dropped out of the count rather than less interference: see position loss.</p>");
    }

    var c = b.changes;
    if (c) {
      var li = function (r, k) { return "<li>" + mapLink(c.day, r.lat, r.lon, place(r)) + " (" + r[k] + (k === "days_in_last7" ? " of the last 7 days" : " of the 30 days before") + ")</li>"; };
      card("bchange-body", "<p><strong>" + n(c.regions_today) + "</strong> regions at jamming scale on " + esc(c.day) + "; <strong>" + n(c.long_running) +
        "</strong> on 90% or more of the last " + n(c.long_running_days) + " days.</p>" +
        "<p>New this week: <strong>" + n(c.new_count) + "</strong></p>" + (c.new.length ? '<ul class="dash-list">' + c.new.slice(0, 4).map(function (r) { return li(r, "days_in_last7"); }).join("") + "</ul>" : "") +
        "<p>Ended this week: <strong>" + n(c.ended_count) + "</strong></p>" + (c.ended.length ? '<ul class="dash-list">' + c.ended.slice(0, 4).map(function (r) { return li(r, "days_in_prior30"); }).join("") + "</ul>" : "") +
        '<p class="small">A region is an H3 cell about 300 km across with 3 or more map hexes at jamming scale that day.</p>');
    }

    var l = b.loss;
    if (l) {
      card("bloss-body", '<table class="dash-table"><thead><tr><th>Area</th><th class="num">No position</th><th class="num">Aircraft</th></tr></thead><tbody>' +
        l.areas.slice(0, 6).map(function (a) {
          var thin = a.hexes && a.hexes_with_mlat / a.hexes < 0.5;
          return "<tr><td>" + esc(a.name) + '</td><td class="num">' + (thin ? '<span class="mut">no MLAT</span>' : pct(a.share)) + '</td><td class="num">' + n(a.heard) + "</td></tr>";
        }).join("") + "</tbody></table>" +
        '<p class="small">Aircraft heard by multilateration (MLAT) but sending no GNSS position, ' + esc(l.day) + " (UTC). A lower bound, and only where MLAT reaches. " +
        '<a href="https://github.com/metacog-osint/noise-floor/blob/main/docs/validation/position-loss.md">How it works</a></p>');
    }

    var s = b.spoofing;
    card("bspoof-body", s ? "<p><strong>" + n(s.active) + "</strong> active spoofing episodes on " + esc(s.day) + " (UTC), " + n(s.aircraft) + " aircraft.</p>" +
      (s.victims && s.victims.length ? '<ul class="dash-list">' + s.victims.slice(0, 4).map(function (v) {
        return "<li>" + (v.lat != null ? mapLink(s.day, v.lat, v.lon, place(v)) : esc(v.region || "")) + ": " + n(v.episodes || v.n) + "</li>";
      }).join("") + "</ul>" : "") +
      '<p class="small">Aircraft positions that can\'t be flown (jumps, loiters, too slow at altitude), placed where the aircraft really was. ' + esc(s.note) +
      ' <a href="/validation#spoofing">Validation</a></p>'
      : '<p class="small">Daily spoofing summaries start with the next daily run. The method passed its held-out test: <a href="/validation#spoofing">Validation</a>.</p>');

    var d = b.declared || {};
    var dh = "";
    if (d.faa_tests) {
      dh += "<p>Announced US GPS tests: <strong>" + n(d.faa_tests.today) + "</strong> today, <strong>" + n(d.faa_tests.next7) + "</strong> in the next 7 days.</p>";
      if (d.faa_tests.list.length) dh += '<ul class="dash-list">' + d.faa_tests.list.slice(0, 3).map(function (t) {
        return "<li>" + (t.url ? '<a href="' + esc(t.url) + '">' + esc(t.id) + "</a>" : esc(t.id)) + ", " + esc(t.place) + ", from " + esc(t.next.replace("T", " ")) + "</li>";
      }).join("") + "</ul>";
    }
    if (d.notices && d.notices.length) {
      dh += "<p>Official notices in force:</p><ul class=\"dash-list\">" + d.notices.map(function (x) {
        return '<li><a href="' + esc(x.url) + '">' + esc(x.id) + "</a>: " + esc(x.area) + ". “" + esc(x.wording) + "”</li>";
      }).join("") + "</ul>";
    }
    var e = b.easa;
    if (e && e.tables && e.tables.length) {
      var t7 = e.tables[0], sp = t7.firs.filter(function (r) { return r.spoofing; }).map(function (r) { return r.name; });
      dh += "<p>EASA, last " + t7.days + " days to " + esc(t7.date) + ": " + n(t7.firs.length) + " FIRs with GNSS interference reports; spoofing in " +
        esc(sp.slice(0, 8).join(", ")) + (sp.length > 8 ? " and " + (sp.length - 8) + " more" : "") + '. <a href="' + esc(e.url) + '">EASA list</a></p>';
    }
    card("bdecl-body", (dh || '<p class="small">Not available.</p>') + '<p class="small">Notices are what officials announce; they are not our measurements. FAA SPANS (US public domain); EASA: source acknowledged.</p>');

    var sc = b.scintillation;
    card("bscint", sc ? "Ionospheric scintillation (ESA, " + esc(sc.valid_utc) + "): <strong>" + esc(sc.level) + "</strong>; highest S4 " + sc.s4.max + ", sigma-phi " + sc.sigma_phi.max +
      " rad. <span class=\"small\">" + esc(sc.credit) + "</span>" : "Ionospheric scintillation: not available at the last build.");

    var cy = b.cygnss;
    card("bcyg-body", cy ? "<p>Newest complete day: <strong>" + esc(cy.day) + "</strong>. " + n(cy.raised_cells) + " of " + n(cy.cells) + " cells raised 1 dB or more.</p>" +
      (cy.top && cy.top.length ? '<ul class="dash-list">' + cy.top.slice(0, 4).map(function (r) {
        return "<li>" + place(r) + ": +" + Number(r.med_db).toFixed(1) + " dB</li>";
      }).join("") + "</ul>" : "") + '<p class="small">' + esc(cy.note) + ' NASA CYGNSS (open data). <a href="/validation#cygnss">Validation</a></p>'
      : '<p class="small">CYGNSS summaries start with the next daily collection on our side; the data arrive over several days. <a href="/validation#cygnss">Validation</a></p>');

    var g = b.geo;
    card("bgeo-body", g ? "<p><strong>" + n(g.counts.objects) + "</strong> active GEO objects; <strong>" + n(g.counts.drifting) + "</strong> drifting; <strong>" +
      n(g.close_count) + "</strong> within 100 km of a satellite of another owner" + (g.snapshots > 1 ? "; " + n(g.manoeuvre_count) + " manoeuvres in the last week" : "") + ".</p>" +
      (g.close.length ? '<ul class="dash-list">' + g.close.slice(0, 4).map(function (p) {
        return "<li>" + esc(p.a[1]) + " (" + esc(p.a[2]) + ") and " + esc(p.b[1]) + " (" + esc(p.b[2]) + "): " + p.km + " km, " + Math.abs(p.lon).toFixed(1) + "°" + (p.lon < 0 ? "W" : "E") + "</li>";
      }).join("") + "</ul>" : "") +
      '<p class="small">Proximity and behaviour, never intent; public elements are good to tens of km. ' + esc(g.source) + ' <a href="/geo">GEO board</a></p>'
      : '<p class="small">The GEO board is not available at the last build.</p>');

    var ev = b.events;
    if (ev) {
      var v = ev.effect_verdict, su = ev.effect_support;
      card("bevents-body", "<p>" + esc(ev.month) + " (" + ev.days + " days, " + esc(ev.version) + "):</p><table class=\"dash-table\"><tbody>" +
        "<tr><td>Multiple sources</td><td class=\"num\">" + n(su["Multiple sources"]) + "</td></tr>" +
        "<tr><td>Partially corroborated</td><td class=\"num\">" + n(su["Partially corroborated"]) + "</td></tr>" +
        "<tr><td>Planned (announced test)</td><td class=\"num\">" + n(v.planned) + "</td></tr>" +
        "<tr><td>Benign natural</td><td class=\"num\">" + n(v.benign_natural) + "</td></tr>" +
        "<tr><td>Deliberate suspected</td><td class=\"num\">" + n(v.deliberate_suspected) + "</td></tr></tbody></table>" +
        '<p class="small">Effect events by grade. Rules frozen, not yet validated. <a href="/validation#events">All months</a></p>');
    }

    var rows = [["Aircraft (daily run)", f.aircraft_day], ["Spoofing", f.spoofing_day], ["Ships (Finnish AIS)", f.ships_built && f.ships_built.slice(0, 16).replace("T", " ") + "Z"],
      ["CYGNSS", f.cygnss_day], ["GEO elements (CelesTrak)", f.geo_snapshot], ["Scintillation (ESA)", f.scintillation_valid], ["EASA FIR table", f.easa_table], ["This board", f.board_built && f.board_built.replace("T", " ")]];
    card("bfresh-body", '<table class="dash-table"><tbody>' + rows.map(function (r) {
      return "<tr><td>" + esc(r[0]) + '</td><td class="num">' + (r[1] ? esc(r[1]) : '<span class="mut">not yet</span>') + "</td></tr>";
    }).join("") + '</tbody></table><p class="small">Times UTC. Sun outages and solar radio update live in your browser.</p>');
  }

  function renderKp(rows) {
    var el = $("bkp");
    if (!el) return;
    if (!rows || !rows.length) { el.textContent = "Kp: not available."; return; }
    var last = rows[rows.length - 1], since = Date.now() - 24 * 3600000, max = 0;
    rows.forEach(function (r) { var t = Date.parse(r.time_tag + "Z"); if (t >= since && r.Kp > max) max = r.Kp; });
    var lvl = function (k) { return k >= 9 ? "G5" : k >= 8 ? "G4" : k >= 7 ? "G3" : k >= 6 ? "G2" : k >= 5 ? "G1" : ""; };
    el.innerHTML = "Geomagnetic Kp (NOAA, live): <strong>" + Number(last.Kp).toFixed(1) + "</strong> at " + esc(last.time_tag.slice(5, 16).replace("T", " ")) +
      " UTC; 24-hour max " + max.toFixed(1) + (lvl(max) ? " (" + lvl(max) + " storm)" : "") + ".";
  }

  get("/data/board.json").then(function (b) { if (b) render(b); else card("bsum", "<p class=\"small\">The board's data could not be loaded.</p>"); });
  get("https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json").then(renderKp);
})();
