/* Noise Floor Sea map: vessels of interest in Finland's open AIS (Digitraffic, CC BY 4.0) joined with official
   sanctions lists (OFAC SDN, UK Sanctions List), plus anonymous GNSS-interference counts at sea.
   Data: /data/vessels/baltic.json, /data/vessels/gnss_at_sea.json, /data/vessels/land.json (tools/vessels_build.py). */
(function () {
  "use strict";
  var mapEl = document.getElementById("sea-map");
  if (!mapEl || !window.L) return;

  var GROUP = {                                         // marker group: first match wins (sanctioned, then state, then flag)
    sanctioned: { label: "Sanctioned", shape: "diamond", lyr: "lyr-sanctioned" },
    state: { label: "Military or law enforcement", shape: "square", lyr: "lyr-state" },
    flag: { label: "State flag of interest", shape: "circle", lyr: "lyr-flag" }
  };
  var CAT = { sanctioned: "Sanctioned", military: "Military", law_enforcement: "Law enforcement",
              state_flag_of_interest: "State flag of interest" };
  var LIST_BY = { "OFAC SDN": "OFAC", "UK Sanctions List": "the UK" };
  var vessels = [], gnss = null, colors = {}, markers = {}, selected = null, trackLayer = null;
  var on = { sanctioned: true, state: true, flag: true, gnss: true, borders: true };
  try { var saved = JSON.parse(localStorage.getItem("nf-sea-layers") || "null"); if (saved) on = Object.assign(on, saved); } catch (e) { /* defaults */ }

  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function readColors() {
    colors = { ocean: css("--map-ocean"), land: css("--map-land"), coast: css("--map-coast"), border: css("--map-border"),
               sanctioned: css("--sea-sanctioned"), state: css("--sea-state"), flag: css("--sea-flag"), gnss: css("--sea-gnss"),
               fg: css("--fg"), card: css("--card"), label: css("--map-label") };
    mapEl.style.background = colors.ocean;
  }
  function esc(s) {
    return String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function isState(v) { return v.categories.indexOf("military") >= 0 || v.categories.indexOf("law_enforcement") >= 0; }
  function group(v) {
    if (v.categories.indexOf("sanctioned") >= 0) return "sanctioned";
    return isState(v) ? "state" : "flag";
  }
  var regionName = null;
  try { regionName = new Intl.DisplayNames(["en"], { type: "region" }); } catch (e) { /* ISO codes only */ }
  function country(iso) {
    if (!iso) return "unknown";
    var n = null;
    try { n = regionName ? regionName.of(iso) : null; } catch (e) { n = null; }
    return n && n !== iso ? n + " (" + iso + ")" : iso;
  }
  var CT = new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", month: "short", day: "numeric",
                                              hour: "numeric", minute: "2-digit", timeZoneName: "short" });
  function utc(iso) { return iso ? iso.slice(0, 10) + " " + iso.slice(11, 16) + " UTC" : "–"; }
  function both(iso) { return iso ? utc(iso) + " (" + CT.format(new Date(iso)) + ")" : "–"; }
  function longDate(d) {
    if (!d) return "an unstated date";
    var p = d.split("-"), M = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
                               "October", "November", "December"];
    return +p[2] + " " + M[+p[1] - 1] + " " + p[0];
  }
  function ll(lat, lon) {
    return Math.abs(lat).toFixed(3) + "°" + (lat >= 0 ? "N" : "S") + " " + Math.abs(lon).toFixed(3) + "°" + (lon >= 0 ? "E" : "W");
  }
  function num(x, unit) { return x === null || x === undefined ? "–" : x + (unit || ""); }
  function pct(x) { return x === null || x === undefined ? "–" : Math.round(100 * x) + "%"; }

  // ---------- map
  var map = L.map(mapEl, { minZoom: 4, maxZoom: 12, zoomSnap: 0.5, preferCanvas: true, attributionControl: true,
                           maxBounds: [[50, 0], [70, 45]] });
  map.attributionControl.setPrefix(false);
  map.attributionControl.addAttribution('Source: Fintraffic / <a href="https://www.digitraffic.fi/en/marine-traffic/">digitraffic.fi</a>, license CC 4.0 BY · ' +
    'Sanctions: OFAC SDN, UK Sanctions List (OGL v3.0) · Land: Natural Earth');
  var canvas = L.canvas({ padding: 0.3 });
  var landLayer = null, borderLayer = null, gnssLayer = L.layerGroup(), vesselLayers = { sanctioned: L.layerGroup(), state: L.layerGroup(), flag: L.layerGroup() };

  function shapeSvg(shape, fill, stroke, size, ring) {
    var s = size, h = s / 2, p;
    if (shape === "diamond") p = '<path d="M' + h + ' 1 L' + (s - 1) + ' ' + h + ' L' + h + ' ' + (s - 1) + ' L1 ' + h + ' Z"';
    else if (shape === "square") p = '<rect x="2.5" y="2.5" width="' + (s - 5) + '" height="' + (s - 5) + '" rx="1"';
    else p = '<circle cx="' + h + '" cy="' + h + '" r="' + (h - 2.5) + '"';
    return '<svg xmlns="http://www.w3.org/2000/svg" width="' + s + '" height="' + s + '" viewBox="0 0 ' + s + ' ' + s + '">' +
      (ring ? '<circle cx="' + h + '" cy="' + h + '" r="' + (h - 0.8) + '" fill="none" stroke="' + colors.fg + '" stroke-width="1.6"/>' : "") +
      p + ' fill="' + fill + '" stroke="' + stroke + '" stroke-width="1.4"/></svg>';
  }
  function icon(v, isSel) {
    var g = group(v), size = isSel ? 22 : 15;
    return L.divIcon({ className: "sea-marker", html: shapeSvg(GROUP[g].shape, colors[g], colors.card, size, isSel),
                       iconSize: [size, size], iconAnchor: [size / 2, size / 2] });
  }
  function zFor(v) { return selected === v.mmsi ? 1000 : group(v) === "sanctioned" ? 200 : 0; }
  function drawVessels() {
    Object.keys(vesselLayers).forEach(function (g) { vesselLayers[g].clearLayers(); });
    markers = {};
    vessels.forEach(function (v) {
      if (v.last.lat === null || v.last.lat === undefined) return;
      var m = L.marker([v.last.lat, v.last.lon], { icon: icon(v, selected === v.mmsi), keyboard: true,
                                                   title: (v.name || "MMSI " + v.mmsi) + " · " + GROUP[group(v)].label,
                                                   alt: v.name || "MMSI " + v.mmsi, riseOnHover: true,
                                                   zIndexOffset: zFor(v) });
      m.on("click", function () { select(v.mmsi, false); });
      m.addTo(vesselLayers[group(v)]);
      markers[v.mmsi] = m;
    });
  }
  function drawGnss() {
    gnssLayer.clearLayers();
    if (!gnss) return;
    var top = Math.max.apply(null, gnss.by_area.map(function (a) { return a.box ? a.vessels : 0; }).concat([1]));
    gnss.by_area.forEach(function (a) {
      if (!a.box) return;
      var tip = esc(a.area) + ": " + a.vessels + (a.vessels === 1 ? " ship" : " ships") + " with GNSS interference (where they last had a trusted position)";
      L.rectangle([[a.box[0], a.box[2]], [a.box[1], a.box[3]]], { renderer: canvas, color: colors.gnss, weight: 1, dashArray: "5 4",
        opacity: 0.5 + 0.5 * a.vessels / top, fillColor: colors.gnss, fillOpacity: 0.03 + 0.17 * a.vessels / top, interactive: true })
        .bindTooltip(tip, { sticky: true }).addTo(gnssLayer);
      L.marker([a.box[1], a.box[2]], { interactive: false, keyboard: false,
        icon: L.divIcon({ className: "sea-glabel", html: a.vessels + (a.vessels === 1 ? " ship" : " ships"), iconSize: null, iconAnchor: [-4, -4] }) })
        .addTo(gnssLayer);
    });
    gnss.spoofed_to.forEach(function (s) {
      L.circleMarker([s.lat, s.lon], { renderer: canvas, radius: 5 + 2.2 * Math.sqrt(s.vessels), color: colors.gnss, weight: 2,
        fillColor: colors.gnss, fillOpacity: 0.25 })
        .bindTooltip(s.vessels + (s.vessels === 1 ? " ship was" : " ships were") + " shown here by spoofed GNSS (" + ll(s.lat, s.lon) + ")", { sticky: true })
        .addTo(gnssLayer);
    });
  }
  function applyLayers() {
    Object.keys(vesselLayers).forEach(function (g) {
      if (on[g]) vesselLayers[g].addTo(map); else map.removeLayer(vesselLayers[g]);
    });
    if (on.gnss) gnssLayer.addTo(map); else map.removeLayer(gnssLayer);
    if (borderLayer) { if (on.borders) borderLayer.addTo(map); else map.removeLayer(borderLayer); }
  }
  function styleBase() {
    if (landLayer) landLayer.setStyle({ fillColor: colors.land, color: colors.coast, weight: 0.6, fillOpacity: 1 });
    if (borderLayer) borderLayer.setStyle({ color: colors.border, weight: 0.9, dashArray: "3 3" });
  }

  // ---------- selection and the detail panel
  function drawTrack(v) {
    if (trackLayer) { map.removeLayer(trackLayer); trackLayer = null; }
    if (!v || !v.track || v.track.length < 2) return;
    var pts = v.track.map(function (p) { return [p[1], p[2]]; });
    trackLayer = L.layerGroup([
      L.polyline(pts, { renderer: canvas, color: colors.card, weight: 5, opacity: 0.8, interactive: false }),
      L.polyline(pts, { renderer: canvas, color: colors[group(v)], weight: 2.5, opacity: 1, interactive: false }),
      L.circleMarker(pts[0], { renderer: canvas, radius: 3.5, color: colors[group(v)], weight: 2, fillColor: colors.card, fillOpacity: 1 })
        .bindTooltip("First trusted position in the window: " + utc(new Date(v.track[0][0] * 1000).toISOString()))
    ]).addTo(map);
  }
  function row(k, val) { return "<dt>" + esc(k) + "</dt><dd>" + val + "</dd>"; }
  function listingHtml(l) {
    var who = LIST_BY[l.list] || l.list;
    var txt = "Listed by " + esc(who) + " on " + esc(longDate(l.date)) + " under " + esc(l.programme || "an unstated programme") + ".";
    var link = ' <a href="' + esc(l.url) + '" rel="noopener">' + (l.list === "OFAC SDN" ? "OFAC entry" : "UK Sanctions List") + "</a>";
    var note = l.match === "mmsi" ? ' <span class="sd-warn">Matched by MMSI only: the ship broadcasts no valid IMO number, so this match is unconfirmed.</span>'
             : l.match === "name" ? ' <span class="sd-warn">Name match only, not confirmed by IMO or MMSI.</span>' : "";
    return "<li>" + txt + link + note + "</li>";
  }
  function renderDetail(v) {
    var box = document.getElementById("sea-detail");
    if (!v) {
      box.innerHTML = '<h2 id="sd-h">Select a vessel</h2><p class="small">Click a marker, or choose "Show" in the table below.</p>';
      return;
    }
    var g = group(v), r = v.reporting, s = v.signals, last = v.last;
    var chips = v.categories.map(function (c) { return '<span class="chip sea-chip c-' + esc(c) + '">' + esc(CAT[c] || c) + "</span>"; }).join(" ");
    var h = '<div class="sd-head"><span class="sd-shape">' + shapeSvg(GROUP[g].shape, colors[g], colors.card, 18, false) + "</span>" +
            '<h2 id="sd-h">' + esc(v.name || "Name not broadcast") + '</h2><button type="button" class="linkish" id="sd-close">Close</button></div>' +
            '<p class="sd-chips">' + chips + "</p>";
    h += '<h3>Identifiers</h3><dl class="sd-dl">' +
         row("MMSI", esc(v.mmsi)) +
         row("IMO", v.imo ? esc(v.imo) + (s.imo_check_digit_ok === false ? ' <span class="sd-warn">check digit invalid</span>' : "") : "not broadcast") +
         row("Call sign", esc(v.callsign || "not broadcast")) +
         row("Flag by MMSI", esc(country(v.flag))) +
         row("AIS type", v.ais_type ? esc(v.ais_type) + " · " + esc(v.ais_type_label) : esc(v.ais_type_label)) +
         row("AIS class", esc(v.ais_class ? v.ais_class + " (inferred)" : "not known")) + "</dl>";
    if (v.listings.length) {
      h += "<h3>Official listings</h3><ul class=\"sd-list\">" + v.listings.map(listingHtml).join("") + "</ul>";
    }
    h += "<h3>Last trusted position</h3>";
    if (last.lat === null || last.lat === undefined) {
      h += '<p class="small">None in this data: every report from this ship failed the spoofing tests, so where it was is unknown.</p>';
    } else {
      h += '<dl class="sd-dl">' + row("Time", esc(both(last.t))) + row("Position", esc(ll(last.lat, last.lon))) +
           row("Speed", esc(num(last.sog, " kn"))) + row("Course", esc(num(last.cog, "°"))) + row("Heading", esc(num(last.heading, "°"))) +
           row("Status", esc(last.nav_status || "–")) + "</dl>" +
           '<p class="small">As the ship reported it. Positions can be spoofed or falsified.' +
           (r.spoofed_positions > r.positions / 2 ? " Most of this ship's reports failed the spoofing tests, so the remaining position and track may still be affected." : "") + "</p>";
    }
    h += '<h3>Reporting pattern</h3><dl class="sd-dl">' +
         row("Reports", esc(r.positions.toLocaleString("en-US"))) +
         row("First heard", esc(both(r.first_seen))) + row("Last heard", esc(both(r.last_seen))) +
         row("Median interval", esc(num(r.median_interval_s, " s"))) +
         row("Gaps over 1 h", esc(r.gaps_over_1h) + (r.gaps_over_1h ? " (longest " + esc(r.longest_gap_h) + " h)" : "")) +
         row("Failed spoofing tests", r.spoofed_positions ? '<span class="sd-warn">' + esc(r.spoofed_positions.toLocaleString("en-US")) + " of " +
             esc(r.positions.toLocaleString("en-US")) + " reports</span>" : "none") +
         row("High position accuracy flag", esc(pct(r.pos_accuracy_high_share))) +
         row("RAIM flag", esc(pct(r.raim_share))) + "</dl>";
    var dim = s.dimensions ? [s.dimensions.length_m ? s.dimensions.length_m + " m long" : null, s.dimensions.beam_m ? s.dimensions.beam_m + " m wide" : null]
      .filter(Boolean).join(", ") : null;
    h += '<h3>Signals</h3><dl class="sd-dl">' +
         row("Class", esc(s.ais_class ? "Class " + s.ais_class + " (inferred)" : "not known")) +
         row("Destination", esc(s.destination || "not given")) + row("ETA", esc(s.eta || "not given")) +
         row("Draught", esc(num(s.draught, " m"))) + row("Size", esc(dim || "not given")) +
         row("Position source (declared)", esc(s.pos_fix_device || "not given")) +
         row("IMO check digit", esc(s.imo_check_digit_ok === null || s.imo_check_digit_ok === undefined ? "no IMO" : s.imo_check_digit_ok ? "valid" : "invalid")) + "</dl>";
    box.innerHTML = h;
    document.getElementById("sd-close").addEventListener("click", function () { select(null, false); });
  }
  function select(mmsi, fromTable) {
    var prev = selected;
    selected = mmsi;
    var v = vessels.filter(function (x) { return x.mmsi === mmsi; })[0] || null;
    [prev, mmsi].forEach(function (m) {
      var vv = vessels.filter(function (x) { return x.mmsi === m; })[0];
      if (vv && markers[m]) { markers[m].setIcon(icon(vv, m === selected)); markers[m].setZIndexOffset(zFor(vv)); }
    });
    drawTrack(v);
    renderDetail(v);
    renderTable();
    try { history.replaceState(null, "", v ? "#v=" + v.mmsi : location.pathname + location.search); } catch (e) { /* no history API */ }
    if (v && fromTable) {
      if (v.track && v.track.length > 1) map.fitBounds(L.latLngBounds(v.track.map(function (p) { return [p[1], p[2]]; })), { maxZoom: 9, padding: [30, 30], animate: false });
      else if (v.last.lat !== null) map.setView([v.last.lat, v.last.lon], Math.max(map.getZoom(), 8), { animate: false });
      document.getElementById("sea-map").scrollIntoView({ block: "nearest" });
      document.getElementById("sea-detail").focus({ preventScroll: true });
    }
  }

  // ---------- table
  function renderTable() {
    var q = document.getElementById("sea-q").value.trim().toLowerCase();
    var cat = document.getElementById("sea-cat").value, fl = document.getElementById("sea-flag").value;
    var tb = document.querySelector("#sea-table tbody"), n = 0, out = [];
    vessels.forEach(function (v) {
      if (cat === "state" ? !isState(v) : cat && v.categories.indexOf(cat) < 0) return;
      if (fl && (v.flag || "") !== fl) return;
      if (q && [v.name, v.mmsi, v.imo, v.callsign].join(" ").toLowerCase().indexOf(q) < 0) return;
      n++;
      var g = group(v), sp = v.reporting.spoofed_positions;
      out.push('<tr' + (selected === v.mmsi ? ' class="sel"' : "") + '><td><span class="sd-shape">' + shapeSvg(GROUP[g].shape, colors[g], colors.card, 13, false) +
        "</span> " + esc(v.name || "–") + "</td><td>" + esc(country(v.flag)) + "</td><td>" + esc(v.ais_type_label) + "</td><td>" +
        esc(v.categories.map(function (c) { return CAT[c] || c; }).join(", ")) + (v.listings.length ? " (" + esc(v.listings.map(function (l) { return LIST_BY[l.list] === "the UK" ? "UK" : LIST_BY[l.list] || l.list; })
          .filter(function (x, i, a) { return a.indexOf(x) === i; }).join(", ")) + ")" : "") + '</td><td class="num">' + esc(v.mmsi) +
        '</td><td class="num">' + esc(v.imo || "–") + "</td><td>" + (v.last.t ? esc(utc(v.last.t)) : '<span class="mut">none trusted</span>') +
        '</td><td class="num">' + (sp ? esc(sp.toLocaleString("en-US")) : "0") + '</td><td><button type="button" class="linkish" data-m="' + v.mmsi + '">Show</button></td></tr>');
    });
    tb.innerHTML = out.join("");
    document.getElementById("sea-shown").textContent = n + " of " + vessels.length + " vessels shown";
  }

  // ---------- GNSS tables
  function renderGnss() {
    if (!gnss) return;
    var hrs = gnss.by_hour.length;
    document.getElementById("gnss-summary").textContent = gnss.affected_vessels + " ships showed GNSS interference between " +
      utc(gnss.window.start) + " and " + utc(gnss.window.end) + (hrs ? ", in " + hrs + " of the hours collected." : ".");
    document.querySelector("#gnss-areas tbody").innerHTML = gnss.by_area.map(function (a) {
      return "<tr><td>" + esc(a.area) + '</td><td class="num">' + a.vessels + "</td></tr>";
    }).join("");
    document.querySelector("#gnss-to tbody").innerHTML = gnss.spoofed_to.map(function (s) {
      return "<tr><td>" + esc(ll(s.lat, s.lon)) + '</td><td class="num">' + s.vessels + "</td></tr>";
    }).join("") || '<tr><td colspan="2">None</td></tr>';
    var CH = new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", month: "short", day: "numeric", hour: "numeric", timeZoneName: "short" });
    document.querySelector("#gnss-hours tbody").innerHTML = gnss.by_hour.map(function (h) {
      return "<tr><td>" + esc(utc(h.t)) + "</td><td>" + esc(CH.format(new Date(h.t))) + '</td><td class="num">' + h.vessels + "</td></tr>";
    }).join("");
  }

  // ---------- load
  function getJson(u) { return fetch(u).then(function (r) { if (!r.ok) throw new Error(u + " " + r.status); return r.json(); }); }
  readColors();
  if (window.innerWidth < 700) map.setView([59.9, 27.0], 6, { animate: false });
  else map.fitBounds([[57.4, 19.5], [61.4, 33.0]], { animate: false });     // the Gulf of Finland and the spoofed-to points
  getJson("/data/vessels/land.json").then(function (j) {
    landLayer = L.geoJSON(j, { renderer: canvas, interactive: false }).addTo(map);
    landLayer.bringToBack();
    styleBase();
  }).catch(function () { /* markers still work without land */ });
  getJson("/data/borders.json").then(function (j) {
    var lines = j.lines.filter(function (l) {
      return l[1].some(function (p) { return p[1] > 52 && p[1] < 70 && p[0] > 5 && p[0] < 40; });
    }).map(function (l) { return l[1].map(function (p) { return [p[1], p[0]]; }); });
    borderLayer = L.polyline(lines, { renderer: canvas, interactive: false });
    styleBase(); applyLayers();
  }).catch(function () { /* the map works without borders */ });
  Promise.all([getJson("/data/vessels/baltic.json"), getJson("/data/vessels/gnss_at_sea.json").catch(function () { return null; })]).then(function (res) {
    var d = res[0];
    vessels = d.vessels; gnss = res[1];
    var counts = { sanctioned: 0, state: 0, flag: 0 };
    vessels.forEach(function (v) { counts[group(v)]++; });
    document.getElementById("sea-data").textContent = "Data built " + utc(d.generated);
    document.getElementById("sea-stats").textContent = vessels.length + " vessels: " + counts.sanctioned + " sanctioned, " + counts.state +
      " military or law enforcement, " + counts.flag + " other state-flag ships. " + d.coverage;
    document.getElementById("sea-dates").textContent = "This data was built " + both(d.generated) + ". Lists used: " + d.sources.slice(1).join("; ") + ".";
    var flags = {};
    vessels.forEach(function (v) { flags[v.flag || ""] = (flags[v.flag || ""] || 0) + 1; });
    var sel = document.getElementById("sea-flag");
    Object.keys(flags).sort(function (a, b) { return flags[b] - flags[a] || a.localeCompare(b); }).forEach(function (f) {
      var o = document.createElement("option"); o.value = f; o.textContent = (f ? country(f) : "unknown") + " (" + flags[f] + ")"; sel.appendChild(o);
    });
    drawVessels(); drawGnss(); applyLayers(); renderTable(); renderGnss();
    function fromHash() {                               // #v=<mmsi> opens that vessel (links and the back button)
      var m = /v=(\d+)/.exec(location.hash), id = m ? +m[1] : null;
      if (id !== selected && (id === null || vessels.some(function (v) { return v.mmsi === id; }))) select(id, id !== null);
    }
    fromHash();
    window.addEventListener("hashchange", fromHash);
  }).catch(function (e) {
    document.getElementById("sea-stats").textContent = "The vessel data could not be loaded (" + e.message + ").";
  });

  // ---------- controls
  var panel = document.getElementById("sea-panel"), toggle = document.getElementById("sea-toggle");
  var pctl = L.control({ position: "topleft" });          // the busy eastern Gulf stays clear
  pctl.onAdd = function () { L.DomEvent.disableClickPropagation(panel); L.DomEvent.disableScrollPropagation(panel); return panel; };
  pctl.addTo(map);
  function setPanel(open) { panel.classList.toggle("closed", !open); toggle.setAttribute("aria-expanded", open); }
  setPanel(window.innerWidth >= 900);
  toggle.addEventListener("click", function () { setPanel(panel.classList.contains("closed")); });
  [["sanctioned", "lyr-sanctioned"], ["state", "lyr-state"], ["flag", "lyr-flag"], ["gnss", "lyr-gnss"], ["borders", "lyr-borders"]].forEach(function (p) {
    var box = document.getElementById(p[1]);
    box.checked = on[p[0]];
    box.addEventListener("change", function () {
      on[p[0]] = box.checked;
      try { localStorage.setItem("nf-sea-layers", JSON.stringify(on)); } catch (e) { /* this visit only */ }
      applyLayers();
    });
  });
  ["sea-q", "sea-cat", "sea-flag"].forEach(function (id) { document.getElementById(id).addEventListener("input", renderTable); });
  document.querySelector("#sea-table tbody").addEventListener("click", function (ev) {
    var b = ev.target.closest("button[data-m]");
    if (b) select(+b.getAttribute("data-m"), true);
  });
  map.on("click", function () { if (selected !== null) select(null, false); });
  if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () {
    readColors(); styleBase(); drawVessels(); drawGnss(); applyLayers(); renderTable();
    var v = vessels.filter(function (x) { return x.mmsi === selected; })[0];
    drawTrack(v); renderDetail(v);
  });
})();
