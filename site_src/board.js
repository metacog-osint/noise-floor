/* Noisefloor home: the daily briefing from /data/board.json (built at deploy by tools/board.py), plus live Kp from
   NOAA SWPC (US public domain, CORS open). Sun outages, solar radio, alerts and the at-sea row are filled by dash.js. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  if (!$("dash")) return;
  var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function get(u) { return fetch(u, { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }); }
  function n(x) { return x == null ? "–" : Number(x).toLocaleString("en-US"); }
  function pct(x) { return x == null ? "–" : Number(x).toFixed(Math.abs(x) < 10 ? 1 : 0) + "%"; }
  function signed(x) { return x == null ? "–" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(1); }
  function pad(x) { return (x < 10 ? "0" : "") + x; }
  function utc(s) { return new Date(/Z$/.test(s) ? s.replace(" ", "T") : s.replace(" ", "T") + "Z"); }
  function dayShort(d) { return +d.slice(8, 10) + " " + MON[+d.slice(5, 7) - 1]; }       // "2026-10-26" -> "26 Oct"
  function dtShort(s) {                    // "2026-10-26T20:03..." or "2026-10-27 09:00Z" -> "26 Oct 20:03"
    return s ? dayShort(s.slice(0, 10)) + (s.length > 10 ? " " + s.slice(11, 16) : "") : null;
  }
  function dateline(d) {                   // "Monday 26 October 2026"
    try { return new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", weekday: "long", day: "numeric", month: "long", year: "numeric" }).format(utc(d + "T12:00")).replace(",", ""); }
    catch (e) { return d; }
  }
  function both(s) {                       // "Tue 27 Oct, 11:07 UTC (6:07 AM CDT)"
    var d = utc(s), z = pad(d.getUTCHours()) + ":" + pad(d.getUTCMinutes()) + " UTC";
    var w = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][d.getUTCDay()] + " " + d.getUTCDate() + " " + MON[d.getUTCMonth()];
    var local = window.TicTime && window.TicTime.zone() !== "UTC" ? " (" + window.TicTime.format(d, { date: false }) + ")" : "";
    return w + ", " + z + local;
  }
  function short(name) { return String(name).split(" / ")[0].replace(" and approaches", "").replace("Southern Black Sea offshore Turkey", "Southern Black Sea"); }
  function mapHref(day, lat, lon, z) { return "/map#day=" + esc(day) + "&m=jam&v=" + Number(lat).toFixed(2) + "," + Number(lon).toFixed(2) + "," + (z || 6); }
  function ramp(v) { return v >= 25 ? 4 : v >= 10 ? 3 : v >= 5 ? 2 : v >= 2 ? 1 : 0; }
  function spark(series) {                 // 30 values, nulls left as gaps
    var v = series.filter(function (x) { return x != null; });
    if (v.length < 2) return "";
    var max = Math.max.apply(null, v), min = Math.min.apply(null, v), W = 120, H = 28, span = (max - min) || 1, d = "", pen = false, last = null;
    series.forEach(function (x, i) {
      if (x == null) { pen = false; return; }
      var px = (i * W / (series.length - 1)).toFixed(1), py = (H - 3 - (x - min) / span * (H - 6)).toFixed(1);
      d += (pen ? "L" : "M") + px + "," + py; pen = true; last = [px, py];
    });
    return '<svg class="spark" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Last 30 days, from ' +
      pct(min) + " to " + pct(max) + '"><path d="' + d + '"/>' + (last ? '<circle cx="' + last[0] + '" cy="' + last[1] + '" r="2.5"/>' : "") + "</svg>";
  }
  function bar(v) {
    var w = Math.max(2, Math.min(v / 50, 1) * 100).toFixed(0), k = ramp(v);
    return '<svg width="56" height="8" viewBox="0 0 100 8" preserveAspectRatio="none" aria-hidden="true"><rect class="bar-bg" width="100" height="8" rx="2"/>' +
      (k ? '<rect width="' + w + '" height="8" rx="2" style="fill: var(--ramp-' + k + ')"/>' : "") + "</svg>";
  }
  function set(id, html) { var el = $(id); if (el) el.innerHTML = html; }

  function render(b) {
    var h = b.hotspots, c = b.changes, day = (h && h.day) || (c && c.day) || "";
    // the bottom line
    if (day) set("brief-day", esc(dateline(day)) + " <span>(UTC data day)</span>");
    set("brief-h", esc(b.brief || b.summary || "Today's numbers are below."));
    set("brief-meta", "Updated " + esc(both(b.built_utc)) + " from aircraft, satellite and official sources.");

    // four numbers
    var st = [];
    if (c) st.push([n(c.regions_today), "areas with GPS interference", c.new_count + " started this week, " + c.ended_count + " stopped"]);
    var s = b.spoofing;
    if (s && s.active != null) st.push([n(s.active), "active spoofing episodes", n(s.aircraft) + " aircraft" + (s.victims && s.victims[0] && s.victims[0].near ? "; most near " + s.victims[0].near : "")]);
    var lo = ((b.loss && b.loss.areas) || []).filter(function (a) { return !a.hexes || a.hexes_with_mlat / a.hexes >= 0.5; });
    if (lo.length) st.push([pct(lo[0].share), "of aircraft over " + short(lo[0].name) + " sent no GPS position", "Heard only by multilateration"]);
    var ft = b.declared && b.declared.faa_tests;
    if (ft) {
      var places = []; (ft.list || []).filter(function (t) { return t.today; }).forEach(function (t) { var p = t.place.replace(/, [A-Z]{2}$| [A-Z]{2}$/, ""); if (places.indexOf(p) < 0) places.push(p); });
      st.push([n(ft.today), "announced US GPS tests today", places.length ? places.join(", ") : "None scheduled today"]);
    }
    set("stats", st.map(function (x) { return '<div class="stat"><b>' + esc(x[0]) + "</b><span>" + esc(x[1]) + "</span><small>" + esc(x[2]) + "</small></div>"; }).join(""));

    // map, table and events
    if (day) {
      set("map-day", ", " + esc(dayShort(day)));
      $("map-link").href = $("map-thumb").href = "/map#day=" + day + "&m=jam";
      set("wa-day", esc(dayShort(day)));
    }
    if (h) {
      set("wa-body", h.areas.map(function (a) {
        var lat = a.box ? (a.box[0] + a.box[1]) / 2 : 0, lon = a.box ? (a.box[2] + a.box[3]) / 2 : 0;
        return '<tr><td><a href="' + mapHref(h.day, lat, lon, 5) + '">' + esc(a.name.replace(" / ", " and ").replace(" excl. ", " outside ")) + "</a></td>" +
          '<td class="num"><span class="val">' + (a.today != null ? bar(a.today) : "") + "<span>" + pct(a.today) + "</span></span></td>" +
          '<td class="num sec">' + pct(a.median30) + '</td><td class="num sec">' + signed(a.change) + "</td><td>" + spark(a.series || []) + "</td></tr>";
      }).join(""));
    }
    var te = b.top_events;
    if (te) {
      set("ev-day", ", " + esc(dayShort(te.day)));
      $("ev-link").href = "/map#day=" + te.day + "&m=jam";
      var evs = (te.events || []).slice().sort(function (x, y) { return y.peak - x.peak; }).slice(0, 6);
      set("ev-list", evs.length ? evs.map(function (e) {
        var tier = e.tier === "major" ? "Major" : e.tier === "notable" ? "Notable" : "Minor", k = e.tier === "major" ? 3 : 1;
        var where = e.near ? "Near " + e.near : Math.abs(e.lat).toFixed(1) + "°" + (e.lat >= 0 ? "N" : "S") + " " + Math.abs(e.lon).toFixed(1) + "°" + (e.lon >= 0 ? "E" : "W");
        return '<li><span class="tier"><i style="background: var(--ramp-' + k + ')"></i>' + tier + '</span><span class="where"><a href="' + mapHref(te.day, e.lat, e.lon) + '">' +
          esc(where) + '</a></span><span class="what">' + Math.round(e.peak) + "% of aircraft degraded</span>" +
          '<span class="when">' + pad(e.h0) + ":00–" + pad(e.h1) + ":59 UTC</span>" + (e.test ? '<span class="note">Fits announced test ' + esc(e.test) + "</span>" : "") + "</li>";
      }).join("") : '<li class="loading">No major or notable event that day.</li>');
      var more = [];
      if (te.bursts) more.push(n(te.bursts) + " minute-level burst" + (te.bursts === 1 ? "" : "s"));
      if (te.tests) more.push(n(te.tests) + " announced US test" + (te.tests === 1 ? "" : "s") + " in force");
      set("ev-more", more.length ? "Also that day: " + esc(more.join("; ")) + "." : "");
    }

    // this week
    if (c) {
      var names = function (xs) { return xs.map(function (r) { return r.near; }).filter(Boolean).join(", "); };
      set("wk", "<dt>Started (" + n(c.new_count) + ")</dt><dd>" + (esc(names(c.new || [])) || "None") + "</dd>" +
        "<dt>Stopped (" + n(c.ended_count) + ")</dt><dd>" + (esc(names(c.ended || [])) || "None") + "</dd>" +
        "<dt>Running " + n(c.long_running_days) + " days or more</dt><dd>" + n(c.long_running) + " areas</dd>");
    }

    // across the spectrum (the rows are in the page; dash.js fills sun outages, solar radio and at sea)
    set("r-spoof", s && s.active != null ? n(s.active) + " active episodes" + ((s.victims || []).length ? "; aircraft mostly near " +
      esc(s.victims.slice(0, 3).map(function (v) { return v.near; }).filter(Boolean).join(", ")) : "") : "Not available in the last build.");
    set("r-loss", lo.length ? esc(lo.slice(0, 3).map(function (a) { return short(a.name) + " " + pct(a.share); }).join(", ")) : "Not available in the last build.");
    var sc = b.scintillation;
    set("scint-text", sc ? "Scintillation " + esc(sc.level) + "." : "");
    var g = b.geo;
    set("r-geo", g ? n(g.counts.objects) + " objects; " + n(g.close_count) + " close pairs; " +
      (g.snapshots > 1 ? (g.manoeuvre_count ? n(g.manoeuvre_count) + " manoeuvres flagged this week" : "no manoeuvres flagged") : "manoeuvre flags start with the second snapshot")
      : "Not available in the last build.");
    var d = b.declared || {}, bits = [];
    if (d.faa_tests) bits.push(n(d.faa_tests.today) + " US GPS tests today, " + n(d.faa_tests.next7) + " in the next 7 days");
    if (d.notices && d.notices.length) bits.push(n(d.notices.length) + " official GNSS warning" + (d.notices.length === 1 ? "" : "s") + " in force");
    var ea = b.easa && b.easa.tables && b.easa.tables[0];
    if (ea) bits.push("EASA lists spoofing in " + ea.firs.filter(function (r) { return r.spoofing; }).length + " regions (" + dayShort(ea.date) + ")");
    set("r-notices", bits.length ? esc(bits.join(". ")) + "." : "Not available in the last build.");
    var ev = b.events;
    if (ev) {
      set("r-events-h", "Graded events, " + MON[+ev.month.slice(5, 7) - 1] + " " + ev.month.slice(0, 4));
      set("r-events", n(ev.effect_support["Multiple sources"]) + " seen by two sensor families; " + n(ev.effect_verdict.deliberate_suspected) + " deliberate suspected (EASA weeks)");
    } else set("r-events", "Not available in the last build.");

    // latest data
    var f = b.freshness || {};
    var fr = [["Aircraft", f.aircraft_day && dayShort(f.aircraft_day)], ["Spoofing", f.spoofing_day && dayShort(f.spoofing_day)],
      ["Ships (Finnish AIS)", dtShort(f.ships_built)], ["Satellite orbits", f.geo_snapshot && dayShort(f.geo_snapshot)],
      ["Scintillation (ESA)", dtShort(f.scintillation_valid)], ["CYGNSS", f.cygnss_day && dayShort(f.cygnss_day)],
      ["EASA table", f.easa_table && dayShort(f.easa_table)], ["This page", dtShort(f.board_built)]];
    set("fresh", fr.map(function (r) { return "<div><span>" + esc(r[0]) + "</span><span>" + (r[1] ? esc(r[1]) : "not yet") + "</span></div>"; }).join(""));
  }

  function renderKp(rows) {
    var el = $("kp-text");
    if (!el) return;
    if (!rows || !rows.length) { el.textContent = "Geomagnetic Kp not available."; return; }
    var last = rows[rows.length - 1], since = Date.now() - 24 * 3600000, max = 0;
    rows.forEach(function (r) { var t = Date.parse(r.time_tag + "Z"); if (t >= since && r.Kp > max) max = r.Kp; });
    var lvl = function (k) { return k >= 9 ? "G5 storm" : k >= 8 ? "G4 storm" : k >= 7 ? "G3 storm" : k >= 6 ? "G2 storm" : k >= 5 ? "G1 storm" : k >= 4 ? "active" : "quiet"; };
    el.textContent = "Geomagnetic Kp " + Number(last.Kp).toFixed(1) + ", " + lvl(Number(last.Kp)) + (max >= 5 ? " (24-hour max " + max.toFixed(1) + ")" : "") + ".";
  }

  var img = document.querySelector("#map-thumb img");          // the thumbnail is built at deploy; hide the frame if it isn't there
  if (img) {
    var hide = function () { var t = $("map-thumb"); if (t) t.hidden = true; };
    img.addEventListener("error", hide);
    if (img.complete && !img.naturalWidth) hide();
  }
  Promise.all([get("/data/board.json"), get("https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json")]).then(function (r) {
    if (r[0]) render(r[0]);
    else set("brief-h", "Today's briefing could not be loaded.");
    renderKp(r[1]);
  });
})();
