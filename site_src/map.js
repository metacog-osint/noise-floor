/* Noise Floor public map: GNSS degradation per H3 hex from ADS-B (adsb.lol, ODbL).
   Data: /data/gnss/<day>.json (cells: h3, aircraft, bad_live, bad_raw, capable, capable_bad10).
   One canvas layer draws land and hexes; hover/click looks up the hex under the pointer. */
(function () {
  "use strict";
  var MEASURES = {
    jam: { label: "Jamming-scale loss (worse than 93 m)", unit: "of aircraft degraded",
           breaks: [2, 5, 10, 25], classes: ["Under 2%", "2–5%", "5–10%", "10–25%", "25% or more"] },
    acc: { label: "Accuracy loss (worse than 10 m, capable aircraft)", unit: "of 10 m-capable aircraft degraded",
           breaks: [10, 25, 50, 75], classes: ["Under 10%", "10–25%", "25–50%", "50–75%", "75% or more"] }
  };
  var state = { day: null, measure: "jam", raw: false };
  var days = [], cells = {}, cellList = [], land = [], colors = {};
  var mapEl = document.getElementById("map");
  if (!mapEl || !window.L || !window.h3) return;

  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function readColors() {
    colors = { ocean: css("--map-ocean"), land: css("--map-land"), coast: css("--map-coast"), quiet: css("--map-quiet"),
               low: css("--map-low"), ramp: [css("--ramp-1"), css("--ramp-2"), css("--ramp-3"), css("--ramp-4")],
               focus: css("--fg") };
    mapEl.style.background = colors.ocean;
  }

  // value and class for a cell under the current measure; null = not drawn
  function evaluate(c) {
    var n, bad;
    if (state.measure === "jam") { n = c[1]; bad = state.raw ? c[3] : c[2]; }
    else { n = c[4]; bad = c[5]; }
    if (n < 3) return null;
    if (n < 5) return { cls: "low", share: null, n: n, bad: bad };
    var share = 100 * Math.max(bad - 1, 0) / n;        // one bad aircraft never colours a hex (GPSJam's formula)
    var b = MEASURES[state.measure].breaks, k = 0;
    while (k < b.length && share >= b[k]) k++;
    return { cls: k === 0 ? "quiet" : k - 1, share: share, n: n, bad: bad };
  }

  var map = L.map(mapEl, { minZoom: 1, maxZoom: 7, zoomSnap: 0.5, worldCopyJump: false,
                           maxBounds: [[-85, -200], [85, 200]], attributionControl: true });
  map.attributionControl.setPrefix(false);
  map.attributionControl.addAttribution('ADS-B: <a href="https://www.adsb.lol/">adsb.lol</a> contributors (ODbL 1.0) · Land: Natural Earth');

  var Canvas = L.Layer.extend({
    onAdd: function (m) {
      this._c = L.DomUtil.create("canvas", "nf-canvas leaflet-zoom-hide");
      m.getPanes().overlayPane.appendChild(this._c);
      m.on("moveend zoomend resize viewreset", this.redraw, this);
      this.redraw();
    },
    onRemove: function (m) { L.DomUtil.remove(this._c); m.off("moveend zoomend resize viewreset", this.redraw, this); },
    redraw: function () {
      var m = this._map, size = m.getSize(), dpr = window.devicePixelRatio || 1, c = this._c;
      c.width = size.x * dpr; c.height = size.y * dpr; c.style.width = size.x + "px"; c.style.height = size.y + "px";
      L.DomUtil.setPosition(c, m.containerPointToLayerPoint([0, 0]));
      var g = c.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
      var b = m.getBounds().pad(0.2);
      g.fillStyle = colors.land; g.strokeStyle = colors.coast; g.lineWidth = 0.6;
      land.forEach(function (ring) {
        if (ring.box[0] > b.getNorth() || ring.box[1] < b.getSouth() || ring.box[2] > b.getEast() || ring.box[3] < b.getWest()) return;
        g.beginPath(); ring.pts.forEach(function (p, i) { var q = m.latLngToContainerPoint(p); i ? g.lineTo(q.x, q.y) : g.moveTo(q.x, q.y); });
        g.closePath(); g.fill(); g.stroke();
      });
      var byCls = { low: [], quiet: [], 0: [], 1: [], 2: [], 3: [] };
      cellList.forEach(function (c) {
        var e = evaluate(c.d); if (!e) return;
        var p = c.bnd[0]; if (p[0] > b.getNorth() + 2 || p[0] < b.getSouth() - 2) return;
        byCls[e.cls].push(c);
      });
      [["low", colors.low], ["quiet", colors.quiet], [0, colors.ramp[0]], [1, colors.ramp[1]], [2, colors.ramp[2]], [3, colors.ramp[3]]]
        .forEach(function (pair) {
          g.fillStyle = pair[1]; g.beginPath();
          byCls[pair[0]].forEach(function (c) {
            c.bnd.forEach(function (p, i) { var q = m.latLngToContainerPoint(p); i ? g.lineTo(q.x, q.y) : g.moveTo(q.x, q.y); });
            g.closePath();
          });
          g.fill();
        });
      if (state.focus && cells[state.focus]) {
        g.strokeStyle = colors.focus; g.lineWidth = 2; g.beginPath();
        cells[state.focus].bnd.forEach(function (p, i) { var q = m.latLngToContainerPoint(p); i ? g.lineTo(q.x, q.y) : g.moveTo(q.x, q.y); });
        g.closePath(); g.stroke();
      }
    }
  });
  var layer = new Canvas();

  // ---------- tooltip / readout
  var tip = document.getElementById("map-tip");
  function describe(h) {
    var c = cells[h]; if (!c) return null;
    var e = evaluate(c.d), d = c.d, ll = h3.cellToLatLng(h);
    var lines = [];
    lines.push(["", (Math.abs(ll[0]).toFixed(1) + "°" + (ll[0] >= 0 ? "N" : "S") + " " + Math.abs(ll[1]).toFixed(1) + "°" + (ll[1] >= 0 ? "E" : "W"))]);
    if (state.measure === "jam") {
      lines.push(["Aircraft", d[1]]);
      lines.push(["Worse than 93 m", (state.raw ? d[3] : d[2]) + (state.raw ? "" : " (live)")]);
      if (!state.raw && d[3] !== d[2]) lines.push(["Incl. post-exposure", d[3]]);
    } else {
      lines.push(["10 m-capable aircraft", d[4]]);
      lines.push(["Worse than 10 m", d[5]]);
    }
    lines.push(["Share", e && e.share !== null ? e.share.toFixed(1) + "%" : (e ? "low coverage (3–4 aircraft)" : "too few aircraft")]);
    return lines;
  }
  function showTip(h, pt) {
    var lines = describe(h);
    if (!lines) { tip.hidden = true; return; }
    tip.textContent = "";
    lines.forEach(function (l, i) {
      var row = document.createElement("div"); row.className = i ? "r" : "h";
      if (l[0]) { var k = document.createElement("span"); k.textContent = l[0]; row.appendChild(k); }
      var v = document.createElement("b"); v.textContent = String(l[1]); row.appendChild(v);
      tip.appendChild(row);
    });
    tip.hidden = false;
    var r = mapEl.getBoundingClientRect(), x = Math.min(pt.x + 14, r.width - tip.offsetWidth - 8), y = Math.min(pt.y + 14, r.height - tip.offsetHeight - 8);
    tip.style.left = Math.max(8, x) + "px"; tip.style.top = Math.max(8, y) + "px";
  }
  map.on("mousemove", function (ev) {
    if (state.pinned) return;
    var h = h3.latLngToCell(ev.latlng.lat, ev.latlng.lng, 4);
    if (cells[h]) showTip(h, ev.containerPoint); else tip.hidden = true;
  });
  map.on("mouseout", function () { if (!state.pinned) tip.hidden = true; });
  map.on("click", function (ev) {
    var h = h3.latLngToCell(ev.latlng.lat, ev.latlng.lng, 4);
    if (cells[h]) { state.pinned = true; state.focus = h; showTip(h, ev.containerPoint); layer.redraw(); }
    else { state.pinned = false; state.focus = null; tip.hidden = true; layer.redraw(); }
  });

  // ---------- table twin: worst hexes for the selected day and measure
  function renderTable() {
    var body = document.querySelector("#map-table tbody"); if (!body) return;
    var rows = cellList.map(function (c) { return { c: c, e: evaluate(c.d) }; })
      .filter(function (x) { return x.e && x.e.share !== null && x.e.share > 0; })
      .sort(function (a, b) { return b.e.share - a.e.share || b.e.n - a.e.n; }).slice(0, 25);
    body.textContent = "";
    rows.forEach(function (x) {
      var ll = h3.cellToLatLng(x.c.h), tr = document.createElement("tr");
      [ll[0].toFixed(1) + ", " + ll[1].toFixed(1), x.e.n, x.e.bad, x.e.share.toFixed(1) + "%"].forEach(function (v, i) {
        var td = document.createElement("td"); td.textContent = v; if (i) td.className = "num"; tr.appendChild(td);
      });
      var td = document.createElement("td"), btn = document.createElement("button");
      btn.type = "button"; btn.className = "linkish"; btn.textContent = "Show";
      btn.addEventListener("click", function () { state.focus = x.c.h; state.pinned = false; map.setView(ll, 5); layer.redraw(); mapEl.scrollIntoView({ behavior: "smooth", block: "center" }); });
      td.appendChild(btn); tr.appendChild(td); body.appendChild(tr);
    });
    document.getElementById("map-table-note").textContent = rows.length ? "" : "No hex reached the first class on this day for this measure.";
  }

  // ---------- legend, stats, controls
  function renderLegend() {
    var m = MEASURES[state.measure], el = document.getElementById("map-legend");
    el.textContent = "";
    var items = [["low", "Low coverage (3–4 aircraft)"], ["quiet", m.classes[0]]].concat(m.classes.slice(1).map(function (t, i) { return [i, t]; }));
    items.forEach(function (it) {
      var s = document.createElement("span"), sw = document.createElement("i");
      sw.style.background = it[0] === "low" ? colors.low : it[0] === "quiet" ? colors.quiet : colors.ramp[it[0]];
      s.appendChild(sw); s.appendChild(document.createTextNode(it[1])); el.appendChild(s);
    });
    var cap = document.getElementById("map-measure-note");
    cap.textContent = state.measure === "jam"
      ? (state.raw ? "Raw: includes aircraft still degraded after leaving interference (comparable with GPSJam)."
                   : "Live: aircraft still degraded after leaving interference elsewhere are left out.")
      : "Counted only for aircraft that showed 10 m accuracy at least once that day. Space weather and SBAS outages show here.";
  }
  function renderStats() {
    var d = days.filter(function (x) { return x.day === state.day; })[0];
    var el = document.getElementById("map-stats");
    var drawn = cellList.filter(function (c) { var e = evaluate(c.d); return e && e.share !== null; }).length;
    var hot = cellList.filter(function (c) { var e = evaluate(c.d); return e && typeof e.cls === "number" && e.cls >= 2; }).length;
    el.textContent = drawn.toLocaleString() + " hexes with 5 or more aircraft · " + hot.toLocaleString() + " in the top two classes";
    var a = document.getElementById("map-download"); a.href = "/data/gnss/" + state.day + ".json"; a.textContent = "Download " + state.day + " (JSON, ODbL)";
    var note = document.getElementById("map-day-note");
    note.textContent = d && d.daily ? "Daily run: automatic, not reviewed by a person" : d && d.note ? d.note : "";
  }
  function writeHash() { history.replaceState(null, "", "#day=" + state.day + "&m=" + state.measure + (state.raw ? "&raw=1" : "")); }

  function loadDay(day) {
    state.day = day; state.focus = null; state.pinned = false; tip.hidden = true;
    mapEl.classList.add("loading");
    return fetch("/data/gnss/" + day + ".json").then(function (r) { return r.json(); }).then(function (j) {
      cells = {}; cellList = [];
      j.cells.forEach(function (d) {
        var bnd = h3.cellToBoundary(d[0]);
        var lons = bnd.map(function (p) { return p[1]; });
        if (Math.max.apply(null, lons) - Math.min.apply(null, lons) > 180) return;   // skip cells across the antimeridian
        var c = { h: d[0], d: d, bnd: bnd }; cells[d[0]] = c; cellList.push(c);
      });
      mapEl.classList.remove("loading");
      layer.redraw(); renderStats(); renderTable(); writeHash();
    });
  }

  function refresh() { layer.redraw(); renderLegend(); renderStats(); renderTable(); writeHash(); }

  Promise.all([fetch("/data/gnss/days.json").then(function (r) { return r.json(); }),
               fetch("/data/land.json").then(function (r) { return r.json(); })]).then(function (res) {
    days = res[0];
    res[1].features.forEach(function (f) {
      var polys = f.geometry.type === "MultiPolygon" ? f.geometry.coordinates : [f.geometry.coordinates];
      polys.forEach(function (poly) {
        var ring = poly[0], pts = ring.map(function (p) { return [p[1], p[0]]; });
        var lats = pts.map(function (p) { return p[0]; }), lons = pts.map(function (p) { return p[1]; });
        land.push({ pts: pts, box: [Math.min.apply(null, lats), Math.max.apply(null, lats), Math.min.apply(null, lons), Math.max.apply(null, lons)] });
      });
    });
    readColors();
    var sel = document.getElementById("map-day");
    var daily = days.filter(function (d) { return d.daily; }).reverse();        // newest first
    var tested = days.filter(function (d) { return !d.daily; });
    [["Daily (automatic)", daily], ["Validated test days", tested]].forEach(function (g) {
      if (!g[1].length) return;
      var og = document.createElement("optgroup"); og.label = g[0];
      g[1].forEach(function (d) {
        var o = document.createElement("option"); o.value = d.day;
        o.textContent = d.day + (d.note ? " · " + d.note : ""); og.appendChild(o);
      });
      sel.appendChild(og);
    });
    var latest = days.length ? days[days.length - 1].day : null;          // days.json is sorted by day
    function fromHash() {
      var hp = {}; location.hash.replace(/^#/, "").split("&").forEach(function (kv) { var p = kv.split("="); if (p[0]) hp[p[0]] = decodeURIComponent(p[1] || ""); });
      state.measure = MEASURES[hp.m] ? hp.m : "jam"; state.raw = hp.raw === "1";
      var d = days.some(function (x) { return x.day === hp.day; }) ? hp.day : latest;
      sel.value = d;
      document.querySelectorAll('input[name="measure"]').forEach(function (r) { r.checked = r.value === state.measure; });
      document.getElementById("map-raw").checked = state.raw;
      document.getElementById("map-raw-wrap").hidden = state.measure !== "jam";
      return d;
    }
    var day = fromHash();
    window.addEventListener("hashchange", function () {
      var want = "#day=" + state.day + "&m=" + state.measure + (state.raw ? "&raw=1" : "");
      if (location.hash === want) return;              // our own replaceState
      var d = fromHash(); renderLegend();
      if (d !== state.day) loadDay(d); else refresh();
    });
    sel.addEventListener("change", function () { loadDay(sel.value); });
    document.querySelectorAll('input[name="measure"]').forEach(function (r) {
      r.addEventListener("change", function () {
        state.measure = r.value; document.getElementById("map-raw-wrap").hidden = state.measure !== "jam"; refresh();
      });
    });
    document.getElementById("map-raw").addEventListener("change", function (e) { state.raw = e.target.checked; refresh(); });
    map.setView([35, 15], window.innerWidth < 700 ? 1.5 : 2.5);
    layer.addTo(map); renderLegend();
    loadDay(day);
    if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () { readColors(); refresh(); });
  });
})();
