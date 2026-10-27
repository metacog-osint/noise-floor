/* Noisefloor Sea map: vessels of interest in Finland's open AIS (Digitraffic, CC BY 4.0) joined with official
   sanctions lists (OFAC SDN, UK Sanctions List), sea zones (Marine Regions, CC BY 4.0) and ports (NGA World Port
   Index), plus anonymous GNSS-interference counts at sea.
   Data: /data/vessels/baltic.json, /data/vessels/gnss_at_sea.json, /data/vessels/land.json (tools/vessels_build.py).
   Filters: AND across facets, OR within one; counts beside each option assume the other facets as they are.
   The URL hash holds the selected vessel (v=<mmsi>) and the filters, so a filtered view can be shared. */
(function () {
  "use strict";
  var mapEl = document.getElementById("sea-map");
  if (!mapEl || !window.L) return;
  var DATA_V = mapEl.getAttribute("data-v") || "";        // hash of the data files, set by tools/build_site.py
  function vdata(u) { return DATA_V ? u + "?v=" + DATA_V : u; }

  var GROUP = {                                         // marker group: first match wins (sanctioned, then state, then flag)
    sanctioned: { label: "Sanctioned", shape: "diamond", lyr: "lyr-sanctioned" },
    state: { label: "Military or law enforcement", shape: "square", lyr: "lyr-state" },
    flag: { label: "State flag of interest", shape: "circle", lyr: "lyr-flag" }
  };
  var CAT = { sanctioned: "Sanctioned", military: "Military", law_enforcement: "Law enforcement",
              state_flag_of_interest: "State flag of interest" };
  var LIST_BY = { "OFAC SDN": "OFAC", "UK Sanctions List": "the UK" };
  var LIST_SHORT = { "OFAC SDN": "OFAC", "UK Sanctions List": "UK" };
  var HOME_PORT = "not in open data (the port of registry is held by commercial registries)";
  var vessels = [], shown = [], gnss = null, colors = {}, markers = {}, selected = null, trackLayer = null, dataEnd = 0;
  var on = { sanctioned: true, state: true, flag: true, gnss: true, borders: true };
  var img = { kind: "", i: null }, imgWant = null;        // satellite imagery: kind "" (none), "s2", "s1" or "esri"; i = month window
  var MOS = null;                                          // the Sentinel mosaic layers by kind (imagery.js), set below
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
  function uniq(a) { return a.filter(function (x, i) { return a.indexOf(x) === i; }); }
  function normName(s) { return String(s || "").toUpperCase().replace(/[^A-Z0-9]+/g, " ").trim(); }
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
  function owners(v) { return v.owners || []; }
  function calls(v) { return v.port_calls || []; }

  // ---------- facets: k (hash key), label, values per vessel; "" means none or not given
  var NONE = "";
  function programmes(v) {
    var out = [];
    v.listings.forEach(function (l) {
      var who = LIST_SHORT[l.list] || l.list;
      String(l.programme || "").split(l.list === "OFAC SDN" ? "; " : ", ref ").slice(0, l.list === "OFAC SDN" ? 99 : 1)
        .forEach(function (p) { if (p) out.push(who + " · " + p); });
    });
    return uniq(out);
  }
  function lists(v) {
    var ls = uniq(v.listings.filter(function (l) { return l.match !== "name"; }).map(function (l) { return LIST_SHORT[l.list] || l.list; }));
    if (!ls.length) return [NONE];
    return ls.length > 1 ? ls.concat(["Both lists"]) : ls;
  }
  function fixLost(f) {                               // AIS UTC-second 62 / 63 in the collector's REST polls
    if (!f) return '<span class="mut">not collected for this ship</span>';
    var n = f.dead_reckoning + f.inoperative;
    if (!n) return "none in " + f.polls + " polls";
    return n + " of " + f.polls + " polls (" + (f.inoperative ? f.inoperative + " positioning system inoperative" : "") +
      (f.inoperative && f.dead_reckoning ? ", " : "") + (f.dead_reckoning ? f.dead_reckoning + " dead reckoning" : "") + "); last " + esc(utc(f.last_lost));
  }
  function flagSource(v) { return v.flag_believed_list === "OFAC SDN" ? "flag on the OFAC entry" : "UK list, believed flag"; }
  var FACETS = [
    { k: "cat", label: "Group", vals: function (v) { return v.categories; }, name: function (x) { return CAT[x] || x; } },
    { k: "flag", label: "Flag (by MMSI)", vals: function (v) { return [v.flag || NONE]; }, name: country, none: "unknown" },
    { k: "bflag", label: "Listed flag (UK, else OFAC)", vals: function (v) { return [v.flag_believed || NONE]; }, name: country, none: "not listed or not given" },
    { k: "bsrc", label: "Listed flag from", vals: function (v) { return [v.flag_believed ? flagSource(v) : NONE]; }, name: function (x) { return x; }, none: "no listed flag" },
    { k: "ocountry", label: "Owner country", vals: function (v) {
        var o = owners(v);
        return o.length ? uniq(o.map(function (x) { return x.country || "?"; })) : [NONE];
      }, name: function (x) { return x === "?" ? "owner listed, country not given" : country(x); }, none: "no owner listed" },
    { k: "list", label: "Sanctions list", vals: lists, name: function (x) { return x; }, none: "not listed" },
    { k: "prog", label: "Programme or regime", vals: function (v) { var p = programmes(v); return p.length ? p : [NONE]; },
      name: function (x) { return x; }, none: "not listed" },
    { k: "type", label: "AIS type", vals: function (v) { return [v.ais_type_label]; }, name: function (x) { return x; } },
    { k: "eez", label: "Sea zone of last position", vals: function (v) { return [v.eez ? v.eez.name : NONE]; },
      name: function (x) { return x; }, none: "no trusted position" },
    { k: "dcountry", label: "Destination country", vals: function (v) { return [v.destination_country || NONE]; }, name: country, none: "not given or not read" },
    { k: "dport", label: "Destination port", vals: function (v) {
        return [v.destination_port ? v.destination_port + (v.destination_locode ? " (" + v.destination_locode + ")" : "") :
                v.destination_locode ? v.destination_locode : NONE];
      }, name: function (x) { return x; }, none: "not given or not read" },
    { k: "pcountry", label: "Port call country", vals: function (v) {
        var c = calls(v); return c.length ? uniq(c.map(function (p) { return p.country || "?"; })) : [NONE];
      }, name: function (x) { return x === "?" ? "unknown" : country(x); }, none: "no port call seen" },
    { k: "pport", label: "Port call port", vals: function (v) {
        var c = calls(v); return c.length ? uniq(c.map(function (p) { return p.name + (p.locode ? " (" + p.locode + ")" : ""); })) : [NONE];
      }, name: function (x) { return x; }, none: "no port call seen" },
    { k: "nav", label: "Navigation status", vals: function (v) { return [v.last.nav_status || NONE]; },
      name: function (x) { return x; }, none: "no trusted position" }
  ];
  var F = { sel: {}, owner: [], name: "", imo: "", mmsi: "", cs: "", spoof: false, gaps: false, mism: false, seen: 0 };
  function mism(v) { return !!(v.flag && v.flag_believed && v.flag !== v.flag_believed); }
  FACETS.forEach(function (f) { F.sel[f.k] = []; });
  function ownerKeys(v) { return uniq(owners(v).map(function (o) { return normName(o.name); })); }
  function ago(v) { return v.reporting.last_seen ? (dataEnd - Date.parse(v.reporting.last_seen)) / 3600000 : Infinity; }
  // every filter except `skip` (a facet key, or "owner", "spoof", "gaps", "seen")
  function passes(v, skip) {
    for (var i = 0; i < FACETS.length; i++) {
      var f = FACETS[i], s = F.sel[f.k];
      if (f.k === skip || !s.length) continue;
      var vals = f.vals(v);
      if (!s.some(function (x) { return vals.indexOf(x) >= 0; })) return false;
    }
    if (skip !== "owner" && F.owner.length) {
      var ok = ownerKeys(v);
      if (!F.owner.some(function (x) { return ok.indexOf(normName(x)) >= 0; })) return false;
    }
    if (F.name && String(v.name || "").toLowerCase().indexOf(F.name.toLowerCase()) < 0) return false;
    if (F.cs && String(v.callsign || "").toLowerCase().indexOf(F.cs.toLowerCase()) < 0) return false;
    if (F.imo && String(v.imo || "") !== F.imo.trim()) return false;
    if (F.mmsi && String(v.mmsi) !== F.mmsi.trim()) return false;
    if (skip !== "spoof" && F.spoof && !v.reporting.spoofed_positions) return false;
    if (skip !== "gaps" && F.gaps && !v.reporting.gaps_over_1h) return false;
    if (skip !== "mism" && F.mism && !mism(v)) return false;
    if (skip !== "seen" && F.seen && !(ago(v) <= F.seen)) return false;
    return true;
  }
  function activeCount() {
    var n = F.owner.length + (F.name ? 1 : 0) + (F.imo ? 1 : 0) + (F.mmsi ? 1 : 0) + (F.cs ? 1 : 0) + (F.spoof ? 1 : 0) + (F.gaps ? 1 : 0) + (F.mism ? 1 : 0) + (F.seen ? 1 : 0);
    FACETS.forEach(function (f) { n += F.sel[f.k].length; });
    return n;
  }

  // ---------- map
  var map = L.map(mapEl, { minZoom: 4, maxZoom: 12, zoomSnap: 0.5, preferCanvas: true, attributionControl: true,
                           maxBounds: [[50, 0], [70, 45]] });
  map.attributionControl.setPrefix(false);
  map.attributionControl.addAttribution('Source: Fintraffic / <a href="https://www.digitraffic.fi/en/marine-traffic/">digitraffic.fi</a>, license CC 4.0 BY · ' +
    'Sanctions: OFAC SDN, UK Sanctions List (OGL v3.0) · Zones: <a href="https://www.marineregions.org/">Marine Regions</a> (CC BY 4.0) · ' +
    'Ports: NGA World Port Index · Land: Natural Earth');
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
    shown.forEach(function (v) {
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
    var M = MOS && MOS[img.kind], under = !!(img.kind === "esri" || (M && map.getZoom() >= M.minZoom));   // land fill off under imagery
    if (landLayer) landLayer.setStyle({ fillColor: colors.land, color: colors.coast, weight: 0.6, fillOpacity: under ? 0 : 1 });
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
  function ownerHtml(o) {
    var src = o.list === "OFAC SDN" && o.ref ? '<a href="https://sanctionssearch.ofac.treas.gov/Details.aspx?id=' + encodeURIComponent(o.ref) +
              '" rel="noopener">OFAC entry</a>' : esc(LIST_SHORT[o.list] || o.list) + (o.ref ? " ref " + esc(o.ref) : "");
    return "<li>" + esc(o.name) + ": " + esc(o.role) + ", " + esc(o.country ? country(o.country) : "country not given") +
           '. <span class="small">' + src + "</span></li>";
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
         (v.flag_believed ? row("Listed flag", esc(country(v.flag_believed)) + ' <span class="sd-src">(' + esc(flagSource(v)) + ")" +
            (mism(v) ? "; differs from the MMSI flag" : "") + "</span>") : "") +
         row("AIS type", v.ais_type ? esc(v.ais_type) + " · " + esc(v.ais_type_label) : esc(v.ais_type_label)) +
         row("AIS class", esc(v.ais_class ? v.ais_class + " (inferred)" : "not known")) +
         row("Home port", esc(HOME_PORT)) +
         row("Position fix lost (ship's own report)", fixLost(s.fix_lost)) + "</dl>";
    if (v.listings.length) {
      h += "<h3>Official listings</h3><ul class=\"sd-list\">" + v.listings.map(listingHtml).join("") + "</ul>";
    }
    if (owners(v).length) {
      h += '<h3>Owners named by the lists</h3><ul class="sd-list">' + owners(v).map(ownerHtml).join("") + "</ul>" +
           '<p class="small">As each list publishes them; a company\'s country is its address on the SDN or UK list.</p>';
    }
    h += "<h3>Last trusted position</h3>";
    if (last.lat === null || last.lat === undefined) {
      h += '<p class="small">None in this data: every report from this ship failed the spoofing tests, so where it was is unknown.</p>';
    } else {
      h += '<dl class="sd-dl">' + row("Time", esc(both(last.t))) + row("Position", esc(ll(last.lat, last.lon))) +
           row("Sea zone", esc(v.eez ? v.eez.name + (v.eez.sovereign ? " (" + v.eez.sovereign + ")" : "") : "not found")) +
           row("Speed", esc(num(last.sog, " kn"))) + row("Course", esc(num(last.cog, "°"))) + row("Heading", esc(num(last.heading, "°"))) +
           row("Status", esc(last.nav_status || "–")) + "</dl>" +
           '<p class="small">As the ship reported it. Positions can be spoofed or falsified.' +
           (r.spoofed_positions > r.positions / 2 ? " Most of this ship's reports failed the spoofing tests, so the remaining position and track may still be affected." : "") + "</p>";
      if (window.NFImagery) {
        h += "<h3>Satellite imagery of this position</h3>" + NFImagery.linksHtml(last.lat, last.lon, last.t ? last.t.slice(0, 10) : null, 15) +
             (MOS ? '<p>On this map, for the 30 days or month of this position: <button type="button" class="linkish" data-img="s2">Sentinel-2 imagery</button> · ' +
                   '<button type="button" class="linkish" data-img="s1">Sentinel-1 radar</button></p>' : "") +
             '<p class="small">Imagery shows the place, not the ship at that moment.</p>';
      }
    }
    h += '<h3>Destination and port calls</h3><dl class="sd-dl">' +
         row("Destination (as typed)", esc(s.destination || "not given")) +
         row("Read as", esc(v.destination_port || v.destination_locode || v.destination_country ?
             [v.destination_port, v.destination_locode, v.destination_country ? country(v.destination_country) : null].filter(Boolean).join(", ") : "not read")) +
         row("Port calls", calls(v).length ? "<ul class=\"sd-list\">" + calls(v).map(function (p) {
             return "<li>" + esc(p.name) + (p.locode ? " (" + esc(p.locode) + ")" : "") + ", " + esc(country(p.country)) + ": " +
                    esc(utc(p.from)) + " to " + esc(utc(p.to)) + "</li>"; }).join("") + "</ul>" : "none seen") + "</dl>" +
         '<p class="small">Port calls are stops of an hour or more under 1 knot within 10 km of a World Port Index port, in this data only.</p>';
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
         row("ETA", esc(s.eta || "not given")) +
         row("Draught", esc(num(s.draught, " m"))) + row("Size", esc(dim || "not given")) +
         row("Position source (declared)", esc(s.pos_fix_device || "not given")) +
         row("IMO check digit", esc(s.imo_check_digit_ok === null || s.imo_check_digit_ok === undefined ? "no IMO" : s.imo_check_digit_ok ? "valid" : "invalid")) + "</dl>";
    box.innerHTML = h;
    document.getElementById("sd-close").addEventListener("click", function () { select(null, false); });
    [].forEach.call(box.querySelectorAll("button[data-img]"), function (b2) {
      b2.addEventListener("click", function () {
        var kind = b2.getAttribute("data-img"), M = MOS[kind], i = last.t ? M.windowFor(last.t.slice(0, 10)) : null;
        setImagery(kind, i === null ? M.windows.length - 1 : i);
        map.setView([last.lat, last.lon], Math.max(map.getZoom(), 12));
      });
    });
  }
  function byMmsi(m) { return vessels.filter(function (x) { return x.mmsi === m; })[0] || null; }
  function select(mmsi, fromTable) {
    var prev = selected;
    selected = mmsi;
    var v = byMmsi(mmsi);
    [prev, mmsi].forEach(function (m) {
      var vv = byMmsi(m);
      if (vv && markers[m]) { markers[m].setIcon(icon(vv, m === selected)); markers[m].setZIndexOffset(zFor(vv)); }
    });
    drawTrack(v);
    renderDetail(v);
    renderTable();
    writeHash();
    if (v && fromTable) {
      if (v.track && v.track.length > 1) map.fitBounds(L.latLngBounds(v.track.map(function (p) { return [p[1], p[2]]; })), { maxZoom: 9, padding: [30, 30], animate: false });
      else if (v.last.lat !== null) map.setView([v.last.lat, v.last.lon], Math.max(map.getZoom(), 8), { animate: false });
      document.getElementById("sea-map").scrollIntoView({ block: "nearest" });
      document.getElementById("sea-detail").focus({ preventScroll: true });
    }
  }

  // ---------- table
  function renderTable() {
    var tb = document.querySelector("#sea-table tbody");
    tb.innerHTML = shown.map(function (v) {
      var g = group(v), sp = v.reporting.spoofed_positions;
      return '<tr' + (selected === v.mmsi ? ' class="sel"' : "") + '><td><span class="sd-shape">' + shapeSvg(GROUP[g].shape, colors[g], colors.card, 13, false) +
        "</span> " + esc(v.name || "–") + "</td><td>" + esc(country(v.flag)) + "</td><td>" + esc(v.ais_type_label) + "</td><td>" +
        esc(v.categories.map(function (c) { return CAT[c] || c; }).join(", ")) +
        (v.listings.length ? " (" + esc(uniq(v.listings.map(function (l) { return LIST_SHORT[l.list] || l.list; })).join(", ")) + ")" : "") +
        '</td><td class="num">' + esc(v.mmsi) + '</td><td class="num">' + esc(v.imo || "–") + "</td><td>" +
        esc(v.eez ? v.eez.name : "–") + "</td><td>" + esc(v.destination_port || v.destination_locode || (v.destination_country ? country(v.destination_country) : "–")) +
        "</td><td>" + (v.last.t ? esc(utc(v.last.t)) : '<span class="mut">none trusted</span>') +
        '</td><td class="num">' + (sp ? esc(sp.toLocaleString("en-US")) : "0") + '</td><td><button type="button" class="linkish" data-m="' + v.mmsi + '">Show</button></td></tr>';
    }).join("");
    document.getElementById("sea-shown").textContent = shown.length + " of " + vessels.length + " vessels shown" +
      (activeCount() ? " (filtered)" : "");
  }

  // ---------- filters panel
  function optionsFor(f) {
    var counts = {};
    vessels.forEach(function (v) {
      if (!passes(v, f.k)) return;
      f.vals(v).forEach(function (x) { counts[x] = (counts[x] || 0) + 1; });
    });
    F.sel[f.k].forEach(function (x) { if (!(x in counts)) counts[x] = 0; });
    return Object.keys(counts).sort(function (a, b) {
      if ((a === NONE) !== (b === NONE)) return a === NONE ? 1 : -1;
      return counts[b] - counts[a] || f.name(a).localeCompare(f.name(b));
    }).map(function (x) { return { v: x, n: counts[x], label: x === NONE ? (f.none || "not given") : f.name(x) }; });
  }
  function renderFacets() {
    var box = document.getElementById("sf-facets");
    box.innerHTML = FACETS.map(function (f) {
      var opts = optionsFor(f).filter(function (o) { return o.n > 0 || F.sel[f.k].indexOf(o.v) >= 0; });
      return '<fieldset class="sf-facet"><legend>' + esc(f.label) + (F.sel[f.k].length ? ' <span class="sf-on">' + F.sel[f.k].length + "</span>" : "") +
        '</legend><div class="sf-opts">' + (opts.length ? opts.map(function (o) {
          return '<label><input type="checkbox" data-f="' + f.k + '" value="' + esc(o.v) + '"' + (F.sel[f.k].indexOf(o.v) >= 0 ? " checked" : "") +
                 '> <span>' + esc(o.label) + '</span> <span class="sf-n">' + o.n + "</span></label>";
        }).join("") : '<span class="small">none</span>') + "</div></fieldset>";
    }).join("");
    // owner names: typeahead from the ships that pass the other filters
    var names = {}, display = {};
    vessels.forEach(function (v) {
      if (!passes(v, "owner")) return;
      owners(v).forEach(function (o) { var k = normName(o.name); if (!display[k]) display[k] = o.name; });
      ownerKeys(v).forEach(function (k) { names[k] = (names[k] || 0) + 1; });
    });
    document.getElementById("sf-owner-list").innerHTML = Object.keys(names).sort(function (a, b) { return names[b] - names[a] || a.localeCompare(b); })
      .filter(function (k) { return !F.owner.some(function (x) { return normName(x) === k; }); })
      .map(function (k) { return '<option value="' + esc(display[k]) + '">' + esc(display[k]) + " (" + names[k] + ")</option>"; }).join("");
    [["spoof", function (v) { return v.reporting.spoofed_positions > 0; }], ["gaps", function (v) { return v.reporting.gaps_over_1h > 0; }], ["mism", mism]].forEach(function (p) {
      var n = vessels.filter(function (v) { return passes(v, p[0]) && p[1](v); }).length;
      document.getElementById("sf-" + p[0] + "-n").textContent = n;
      document.getElementById("sf-" + p[0]).checked = F[p[0]];
    });
    var seenSel = document.getElementById("sf-seen");
    [].forEach.call(seenSel.options, function (o) {
      var h = +o.value, n = vessels.filter(function (v) { return passes(v, "seen") && (!h || ago(v) <= h); }).length;
      o.textContent = o.getAttribute("data-label") + " (" + n + ")";
    });
    seenSel.value = String(F.seen);
  }
  function chip(label, remove) { return { label: label, remove: remove }; }
  function renderChips() {
    var cs = [];
    FACETS.forEach(function (f) {
      F.sel[f.k].forEach(function (x) {
        cs.push(chip(f.label + ": " + (x === NONE ? (f.none || "not given") : f.name(x)), function () { F.sel[f.k] = F.sel[f.k].filter(function (y) { return y !== x; }); }));
      });
    });
    F.owner.forEach(function (x) { cs.push(chip("Owner: " + x, function () { F.owner = F.owner.filter(function (y) { return y !== x; }); })); });
    [["name", "Name contains"], ["imo", "IMO"], ["mmsi", "MMSI"], ["cs", "Call sign contains"]].forEach(function (p) {
      if (F[p[0]]) cs.push(chip(p[1] + ": " + F[p[0]], function () { F[p[0]] = ""; document.getElementById("sf-" + p[0]).value = ""; }));
    });
    if (F.spoof) cs.push(chip("Has failed spoofing tests", function () { F.spoof = false; }));
    if (F.gaps) cs.push(chip("Has gaps over 1 h", function () { F.gaps = false; }));
    if (F.mism) cs.push(chip("Flag by MMSI differs from listed flag", function () { F.mism = false; }));
    if (F.seen) cs.push(chip("Last heard within " + F.seen + " h", function () { F.seen = 0; }));
    var box = document.getElementById("sf-chips");
    box.innerHTML = cs.map(function (c, i) {
      return '<span class="sf-chip">' + esc(c.label) + ' <button type="button" data-i="' + i + '" aria-label="Remove filter: ' + esc(c.label) + '">×</button></span>';
    }).join("");
    [].forEach.call(box.querySelectorAll("button[data-i]"), function (b) {
      b.addEventListener("click", function () { cs[+b.getAttribute("data-i")].remove(); applyFilters(); });
    });
    document.getElementById("sf-reset").hidden = !cs.length;
    document.getElementById("sf-count").textContent = cs.length ? cs.length + " active · " + shown.length + " of " + vessels.length + " vessels" :
      "none active · " + vessels.length + " vessels";
  }
  function applyFilters() {
    shown = vessels.filter(function (v) { return passes(v, null); });
    if (selected !== null && !shown.some(function (v) { return v.mmsi === selected; })) {
      selected = null; drawTrack(null); renderDetail(null);
    }
    drawVessels(); applyLayers(); renderTable(); renderFacets(); renderChips(); writeHash();
  }

  // ---------- downloads of the ships shown
  var sources = [];
  function flatRow(v) {
    var o = owners(v);
    return {
      name: v.name, mmsi: v.mmsi, imo: v.imo, callsign: v.callsign, flag_by_mmsi: v.flag, listed_flag: v.flag_believed,
      listed_flag_from: v.flag_believed ? v.flag_believed_list : null, ais_type: v.ais_type, ais_type_label: v.ais_type_label,
      groups: v.categories.join("; "), lists: uniq(v.listings.map(function (l) { return l.list; })).join("; "),
      programmes: uniq(v.listings.map(function (l) { return l.programme; }).filter(Boolean)).join("; "),
      listing_dates: uniq(v.listings.map(function (l) { return l.date; }).filter(Boolean)).join("; "),
      listing_match: uniq(v.listings.map(function (l) { return l.match; }).filter(Boolean)).join("; "),
      owners: o.map(function (x) { return x.name + (x.country ? " [" + x.country + "]" : ""); }).join("; "),
      sea_zone: v.eez ? v.eez.name : null, destination_as_typed: v.signals.destination, destination_locode: v.destination_locode,
      destination_country: v.destination_country, destination_port: v.destination_port,
      port_calls: (v.port_calls || []).map(function (p) { return (p.locode || p.name) + " " + p.from + "/" + p.to; }).join("; "),
      last_trusted_utc: v.last.t, lat: v.last.lat, lon: v.last.lon, sog_kn: v.last.sog, cog_deg: v.last.cog,
      nav_status: v.last.nav_status, first_heard_utc: v.reporting.first_seen, last_heard_utc: v.reporting.last_seen,
      positions: v.reporting.positions, gaps_over_1h: v.reporting.gaps_over_1h,
      failed_spoofing_tests: v.reporting.spoofed_positions, pos_fix_device: v.signals.pos_fix_device
    };
  }
  function csvCell(x) {
    if (x === null || x === undefined) return "";
    var s = String(x);
    if (typeof x === "string" && /^[=+\-@\t\r]/.test(s)) s = "'" + s;      // keep spreadsheets from reading broadcast text as a formula
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }
  function download(kind) {
    var rows = shown.map(flatRow), stamp = dataEnd ? new Date(dataEnd).toISOString().slice(0, 10) : "data", text, type;
    var note = "Noisefloor Sea page (https://noisefloor.theintelligence.company/sea" + location.hash + "), downloaded " +
               new Date().toISOString().slice(0, 16) + "Z. " + sources.join(" | ");
    if (kind === "csv") {
      var keys = rows.length ? Object.keys(rows[0]) : Object.keys(flatRow(vessels[0]));
      text = "# " + note.replace(/[\r\n]+/g, " ") + "\r\n" + keys.join(",") + "\r\n" +
             rows.map(function (r) { return keys.map(function (k) { return csvCell(r[k]); }).join(","); }).join("\r\n") + "\r\n";
      type = "text/csv";
    } else {
      text = JSON.stringify({ type: "FeatureCollection", attribution: note, features: rows.map(function (r) {
        return { type: "Feature", geometry: r.lat === null || r.lat === undefined ? null : { type: "Point", coordinates: [r.lon, r.lat] }, properties: r };
      }) });
      type = "application/geo+json";
    }
    var a = document.createElement("a"), url = URL.createObjectURL(new Blob([text], { type: type + ";charset=utf-8" }));
    a.href = url; a.download = "noise-floor-sea-" + stamp + "." + kind;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
  }

  // ---------- URL hash: v=<mmsi>, facet keys, owner, name, imo, mmsi, cs, spoof, gaps, seen
  function writeHash() {
    var parts = [];
    if (selected !== null) parts.push("v=" + selected);
    FACETS.forEach(function (f) {
      if (F.sel[f.k].length) parts.push(f.k + "=" + F.sel[f.k].map(function (x) { return encodeURIComponent(x === NONE ? "-" : x); }).join("|"));
    });
    if (F.owner.length) parts.push("owner=" + F.owner.map(encodeURIComponent).join("|"));
    ["name", "imo", "mmsi", "cs"].forEach(function (k) { if (F[k]) parts.push(k + "=" + encodeURIComponent(F[k])); });
    if (F.spoof) parts.push("spoof=1");
    if (F.gaps) parts.push("gaps=1");
    if (F.mism) parts.push("mism=1");
    if (F.seen) parts.push("seen=" + F.seen);
    if (MOS && MOS[img.kind]) parts.push("img=" + img.kind + "&when=" + MOS[img.kind].windows[img.i].key);
    if (img.kind === "esri") parts.push("img=esri");
    var h = parts.length ? "#" + parts.join("&") : "";
    if (h !== location.hash && !(h === "" && location.hash === "")) {
      try { history.replaceState(null, "", h || location.pathname + location.search); } catch (e) { /* no history API */ }
    }
  }
  function readHash() {
    var hp = {};
    location.hash.replace(/^#/, "").split("&").forEach(function (kv) {
      var i = kv.indexOf("=");
      if (i > 0) hp[kv.slice(0, i)] = kv.slice(i + 1);
    });
    function list(k) { return hp[k] ? hp[k].split("|").map(function (x) { try { x = decodeURIComponent(x); } catch (e) { /* as is */ } return x === "-" ? NONE : x; }) : []; }
    function one(k) { try { return hp[k] ? decodeURIComponent(hp[k]) : ""; } catch (e) { return hp[k] || ""; } }
    FACETS.forEach(function (f) { F.sel[f.k] = list(f.k); });
    F.owner = list("owner");
    ["name", "imo", "mmsi", "cs"].forEach(function (k) { F[k] = one(k); var el = document.getElementById("sf-" + k); if (el) el.value = F[k]; });
    F.spoof = hp.spoof === "1"; F.gaps = hp.gaps === "1"; F.mism = hp.mism === "1";
    F.seen = [6, 24, 48].indexOf(+hp.seen) >= 0 ? +hp.seen : 0;
    imgWant = { kind: ["s2", "s1", "esri"].indexOf(hp.img) >= 0 ? hp.img : "", key: one("when") };
    var m = /^\d+$/.test(hp.v || "") ? +hp.v : null;
    return m;
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
  getJson(vdata("/data/vessels/land.json")).then(function (j) {
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
  Promise.all([getJson(vdata("/data/vessels/baltic.json")), getJson(vdata("/data/vessels/gnss_at_sea.json")).catch(function () { return null; })]).then(function (res) {
    var d = res[0];
    vessels = d.vessels; gnss = res[1]; sources = d.sources || [];
    vessels.forEach(function (v) { var t = Date.parse(v.reporting.last_seen || ""); if (t > dataEnd) dataEnd = t; });
    var counts = { sanctioned: 0, state: 0, flag: 0 };
    vessels.forEach(function (v) { counts[group(v)]++; });
    document.getElementById("sea-data").textContent = "Data built " + utc(d.generated);
    document.getElementById("sea-stats").textContent = vessels.length + " vessels: " + counts.sanctioned + " sanctioned, " + counts.state +
      " military or law enforcement, " + counts.flag + " other state-flag ships. " + d.coverage;
    document.getElementById("sea-dates").textContent = "This data was built " + both(d.generated) + ". Sources: " + d.sources.slice(1).join("; ") + ".";
    var v0 = readHash();
    applyImgWant();
    shown = vessels.filter(function (v) { return passes(v, null); });
    drawGnss(); renderGnss(); applyFilters();
    if (v0 !== null && shown.some(function (v) { return v.mmsi === v0; })) select(v0, true);
    if (activeCount() && window.innerWidth >= 700) setFilters(true);   // on a phone the chips show them; the panel stays shut
    window.addEventListener("hashchange", function () {
      var m = readHash();
      applyImgWant();
      applyFilters();
      if (m !== selected && (m === null || shown.some(function (v) { return v.mmsi === m; }))) select(m, m !== null);
    });
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
  // ---------- satellite imagery (imagery.js): Sentinel-2 mosaics by month
  var BASE_MAX_ZOOM = 12, IMG_MAX_ZOOM = 16, ESRI_MAX_ZOOM = 18;
  // Esri World Imagery (imagery.js): offered only where /api/imagery returns a key; otherwise the option stays hidden
  var esriKey = null, esriLayer = null, esriPending = false;
  var imgNote = document.getElementById("img-note"), imgS2 = document.getElementById("img-s2");
  var imgWhen = document.getElementById("img-when"), imgLabel = document.getElementById("img-when-label");
  var imgScene = document.getElementById("img-scene"), imgHelp = document.getElementById("img-help");
  var imgMsg = "", imgErr = false, whenT = null;
  var HELP = { s2: "The clearest scenes of each month are drawn first; a cloudy month shows cloud.",
               s1: "Radar, latest pass first: ships show as bright points at that moment; wind and waves change the texture of the sea." };
  function imgStatus(text, isErr) { imgMsg = text; imgErr = isErr; showImgNote(); }
  function sceneText(t) { imgScene.textContent = t; }
  var s2 = window.NFImagery ? NFImagery.sentinel2(map, { status: imgStatus, scene: sceneText }) : null;
  if (s2) MOS = { s2: s2, s1: NFImagery.sentinel1(map, { status: imgStatus, scene: sceneText }) };
  function showImgNote() {
    var M = MOS && MOS[img.kind], low = !!(M && map.getZoom() < M.minZoom), t = imgMsg || (low ? "Imagery shows from zoom " + M.minZoom + ". " : "");
    imgNote.textContent = t;
    imgNote.hidden = !t;
    imgNote.classList.toggle("img-err", !!(imgMsg && imgErr));
    if (low && !imgMsg) {
      var b = document.createElement("button");
      b.type = "button"; b.className = "linkish"; b.textContent = "Zoom in";
      b.addEventListener("click", function () { map.setZoom(M.minZoom); });
      imgNote.appendChild(b);
    }
  }
  function setImagery(kind, i) {
    if (kind === "esri" && !esriKey) { esriPending = true; return; }       // applied once /api/imagery answers
    var M = MOS && MOS[kind], prev = MOS && MOS[img.kind];
    if (kind && !M && kind !== "esri") kind = "";
    if (kind !== "esri" && esriLayer) { map.removeLayer(esriLayer); esriLayer = null; }
    img.kind = kind;
    img.i = M ? (i === null || i === undefined ? M.windows.length - 1 : i) : null;
    [].forEach.call(document.querySelectorAll('input[name="lyr-img"]'), function (r) { r.checked = r.value === kind; });
    imgS2.hidden = !M;                                     // the month slider, shared by both Sentinel layers
    clearTimeout(whenT);
    if (prev && prev !== M) prev.hide();
    if (M) {
      imgWhen.max = M.windows.length - 1; imgWhen.value = img.i;
      imgLabel.textContent = M.windows[img.i].label;
      imgHelp.textContent = HELP[kind];
      map.setMaxZoom(IMG_MAX_ZOOM);
      M.show(img.i);
    } else if (kind === "esri") {
      imgHelp.textContent = "";
      map.setMaxZoom(ESRI_MAX_ZOOM);
      if (!esriLayer) {
        esriLayer = NFImagery.esriLayer(esriKey, function () {
          imgStatus("Esri imagery isn't loading (the free monthly allowance may be used up). Try Sentinel-2.", true);
        }).addTo(map);
      }
    } else {
      map.setMaxZoom(BASE_MAX_ZOOM);
    }
    styleBase(); showImgNote(); writeHash();
  }
  function applyImgWant() {
    if (!imgWant) return;
    var w = imgWant, i = null;
    imgWant = null;
    if (MOS && MOS[w.kind]) MOS[w.kind].windows.forEach(function (x, k) { if (x.key === w.key) i = k; });
    if (w.kind !== img.kind || (w.kind && i !== null && i !== img.i)) setImagery(w.kind, i);
  }
  [].forEach.call(document.querySelectorAll('input[name="lyr-img"]'), function (r) {
    r.addEventListener("change", function () { if (r.checked) setImagery(r.value, img.i); });
  });
  imgWhen.addEventListener("input", function () {
    var M = MOS && MOS[img.kind];
    if (!M) return;
    img.i = +imgWhen.value;
    imgLabel.textContent = M.windows[img.i].label;
    clearTimeout(whenT);
    whenT = setTimeout(function () { M.show(img.i); writeHash(); }, 350);
  });
  map.on("zoomend", function () { showImgNote(); if (img.kind) styleBase(); });
  if (window.NFImagery) NFImagery.esriKey().then(function (k) {
    if (!k) { esriPending = false; return; }       // local preview, not configured, or not offered here: Sentinel layers only
    esriKey = k;
    document.getElementById("img-esri-opt").hidden = false;
    document.getElementById("img-esri-opt").closest("fieldset").hidden = false;
    if (esriPending) { esriPending = false; setImagery("esri", null); }
  });
  if (!s2) document.getElementById("img-note").closest("fieldset").hidden = true;

  var sfToggle = document.getElementById("sf-toggle"), sfBody = document.getElementById("sf-body");
  function setFilters(open) { sfBody.hidden = !open; sfToggle.setAttribute("aria-expanded", open); }
  sfToggle.addEventListener("click", function () { setFilters(sfBody.hidden); });
  document.getElementById("sf-facets").addEventListener("change", function (ev) {
    var b = ev.target;
    if (!b.matches || !b.matches("input[data-f]")) return;
    var k = b.getAttribute("data-f");
    F.sel[k] = b.checked ? uniq(F.sel[k].concat([b.value])) : F.sel[k].filter(function (x) { return x !== b.value; });
    applyFilters();
  });
  var typing;
  ["name", "imo", "mmsi", "cs"].forEach(function (k) {
    document.getElementById("sf-" + k).addEventListener("input", function (ev) {
      F[k] = ev.target.value.trim();
      clearTimeout(typing); typing = setTimeout(applyFilters, 200);
    });
  });
  var ownerIn = document.getElementById("sf-owner");
  function addOwner() {
    var x = ownerIn.value.trim();
    if (!x) return;
    var known = vessels.some(function (v) { return ownerKeys(v).indexOf(normName(x)) >= 0; });
    if (known && !F.owner.some(function (y) { return normName(y) === normName(x); })) { F.owner.push(x); ownerIn.value = ""; applyFilters(); }
  }
  ownerIn.addEventListener("change", addOwner);
  ownerIn.addEventListener("input", function () {          // a pick from the list fills the exact name
    var x = normName(ownerIn.value);
    if (x && [].some.call(document.getElementById("sf-owner-list").options, function (o) { return normName(o.value) === x; })) addOwner();
  });
  ownerIn.addEventListener("keydown", function (ev) { if (ev.key === "Enter") { ev.preventDefault(); addOwner(); } });
  document.getElementById("sf-spoof").addEventListener("change", function (ev) { F.spoof = ev.target.checked; applyFilters(); });
  document.getElementById("sf-gaps").addEventListener("change", function (ev) { F.gaps = ev.target.checked; applyFilters(); });
  document.getElementById("sf-mism").addEventListener("change", function (ev) { F.mism = ev.target.checked; applyFilters(); });
  document.getElementById("dl-csv").addEventListener("click", function () { download("csv"); });
  document.getElementById("dl-geojson").addEventListener("click", function () { download("geojson"); });
  document.getElementById("sf-seen").addEventListener("change", function (ev) { F.seen = +ev.target.value; applyFilters(); });
  document.getElementById("sf-reset").addEventListener("click", function () {
    FACETS.forEach(function (f) { F.sel[f.k] = []; });
    F.owner = []; F.spoof = F.gaps = F.mism = false; F.seen = 0;
    ["name", "imo", "mmsi", "cs"].forEach(function (k) { F[k] = ""; document.getElementById("sf-" + k).value = ""; });
    applyFilters();
  });
  document.querySelector("#sea-table tbody").addEventListener("click", function (ev) {
    var b = ev.target.closest("button[data-m]");
    if (b) select(+b.getAttribute("data-m"), true);
  });
  map.on("click", function () { if (selected !== null) select(null, false); });
  if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () {
    readColors(); styleBase(); drawVessels(); drawGnss(); applyLayers(); renderTable();
    var v = byMmsi(selected);
    drawTrack(v); renderDetail(v);
  });
})();
