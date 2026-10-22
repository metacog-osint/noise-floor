/* Noise Floor public map: GNSS degradation per H3 hex from ADS-B (adsb.lol, ODbL).
   Data: /data/gnss/<day>.json (cells: h3, aircraft, bad_live, bad_raw, capable, capable_bad10) and
   /data/events/<day>.json (anomaly events, bursts and SBAS flags from pipeline/pnt_analysis.py).
   One canvas layer draws land and hexes; hover/click looks up the hex under the pointer. */
(function () {
  "use strict";
  var MEASURES = {
    jam: { label: "Jamming-scale loss (worse than 93 m)", unit: "of aircraft degraded",
           breaks: [2, 5, 10, 25], classes: ["Under 2%", "2–5%", "5–10%", "10–25%", "25% or more"] },
    acc: { label: "Accuracy loss (worse than 10 m, capable aircraft)", unit: "of 10 m-capable aircraft degraded",
           breaks: [10, 25, 50, 75], classes: ["Under 10%", "10–25%", "25–50%", "50–75%", "75% or more"] }
  };
  var state = { day: null, measure: "jam", raw: false, ev: null, evShow: true, evAll: { anom: false, burst: false }, evFocus: null };
  var EV_ROWS = { anom: 15, burst: 10 };
  var TIER = { major: "Major", notable: "Notable", minor: "Minor" };
  var days = [], cells = {}, cellList = [], land = [], colors = {};
  var mapEl = document.getElementById("map");
  if (!mapEl || !window.L || !window.h3) return;

  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function readColors() {
    colors = { ocean: css("--map-ocean"), land: css("--map-land"), coast: css("--map-coast"), quiet: css("--map-quiet"),
               low: css("--map-low"), ramp: [css("--ramp-1"), css("--ramp-2"), css("--ramp-3"), css("--ramp-4")],
               focus: css("--fg"), event: css("--map-event"), ring: css("--map-ocean") };
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
      if (state.evShow && state.ev) {
        var rows = evRows();
        var outline = function (e) {
          g.beginPath();
          poly(e).forEach(function (loops) { loops.forEach(function (loop) {
            loop.forEach(function (p, i) { var q = m.latLngToContainerPoint(p); i ? g.lineTo(q.x, q.y) : g.moveTo(q.x, q.y); });
            g.closePath();
          }); });
          g.stroke();
        };
        g.strokeStyle = colors.event; g.lineWidth = 2;
        rows.anom.forEach(function (e) { if (e !== state.evFocus) outline(e); });
        rows.burst.forEach(function (e) {
          if (e === state.evFocus) return;
          var q = m.latLngToContainerPoint([e.lat, e.lon]);
          g.beginPath(); g.arc(q.x, q.y, 5, 0, 2 * Math.PI); g.fillStyle = colors.event; g.fill();
          g.lineWidth = 2; g.strokeStyle = colors.ring; g.stroke(); g.strokeStyle = colors.event;
        });
        if (state.evFocus) {
          g.strokeStyle = colors.focus; g.lineWidth = 3;
          if (state.evFocus.t0) {
            var q = m.latLngToContainerPoint([state.evFocus.lat, state.evFocus.lon]);
            g.beginPath(); g.arc(q.x, q.y, 7, 0, 2 * Math.PI); g.fillStyle = colors.event; g.fill(); g.stroke();
          } else outline(state.evFocus);
        }
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
    if (state.evShow && state.ev) {
      var r2 = h3.cellToParent(h, 2);
      evRows().anom.forEach(function (a) {
        if (a.cells.indexOf(r2) >= 0) lines.push(["Anomaly", TIER[a.tier] + ", " + pad(a.h0) + ":00–" + pad(a.h1) + ":59Z"]);
      });
    }
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

  // ---------- events panel: anomaly events, bursts, SBAS flags (pipeline/pnt_analysis.py)
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function ll2(lat, lon) {
    return Math.abs(lat).toFixed(1) + "°" + (lat >= 0 ? "N" : "S") + " " + Math.abs(lon).toFixed(1) + "°" + (lon >= 0 ? "E" : "W");
  }
  var CT = new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", month: "short", day: "numeric",
                                              hour: "numeric", minute: "2-digit", timeZoneName: "short" });
  var UT = new Intl.DateTimeFormat("en-US", { timeZone: "UTC", month: "short", day: "numeric" });
  function central(day, mins) {
    var p = day.split("-"), d = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2], 0, mins)), x = {};
    CT.formatToParts(d).forEach(function (q) { x[q.type] = q.value; });
    return { time: x.hour + ":" + x.minute + " " + String(x.dayPeriod || "").toLowerCase(), zone: x.timeZoneName,
             date: x.month + " " + x.day, utcDate: UT.format(new Date(Date.UTC(+p[0], +p[1] - 1, +p[2]))) };
  }
  // "03:00–05:59Z" and "10:00 pm (Oct 20)–12:59 am CDT"
  function when(day, m0, m1) {
    var a = central(day, m0), b = central(day, m1);
    return [pad(Math.floor(m0 / 60)) + ":" + pad(m0 % 60) + "–" + pad(Math.floor(m1 / 60)) + ":" + pad(m1 % 60) + "Z",
            a.time + (a.date !== a.utcDate ? " (" + a.date + ")" : "") + "–" + b.time + " " + b.zone];
  }
  function mins(hhmm) { return +hhmm.slice(0, 2) * 60 + +hhmm.slice(3, 5); }
  function poly(e) {
    if (!e.poly) {
      // skip events whose regions cross the antimeridian (Leaflet would draw them across the world)
      var bad = e.cells.some(function (c) {
        var lons = h3.cellToBoundary(c).map(function (p) { return p[1]; });
        return Math.max.apply(null, lons) - Math.min.apply(null, lons) > 180;
      });
      e.poly = bad || !e.cells.length ? [] : h3.cellsToMultiPolygon(e.cells);
    }
    return e.poly;
  }
  function evRows() {
    var ev = state.ev; if (!ev) return { anom: [], burst: [], anomAll: [], burstAll: [] };
    var anomAll = ev.anomalies.filter(function (e) { return e.m === state.measure; });
    var anom = state.evAll.anom ? anomAll : anomAll.filter(function (e) { return e.tier !== "minor"; }).slice(0, EV_ROWS.anom);
    var burstAll = state.measure === "jam" ? ev.bursts : [];
    var burst = state.evAll.burst ? burstAll : burstAll.slice(0, EV_ROWS.burst);
    return { anom: anom, burst: burst, anomAll: anomAll, burstAll: burstAll };
  }
  function showEvent(e) {
    state.evFocus = e; state.focus = null; state.pinned = false; tip.hidden = true;
    var pts = [];
    poly(e).forEach(function (loops) { loops.forEach(function (loop) { pts = pts.concat(loop); }); });
    if (pts.length) map.fitBounds(L.latLngBounds(pts), { maxZoom: 5, padding: [40, 40] });
    else map.setView([e.lat, e.lon], 5);
    layer.redraw(); mapEl.scrollIntoView({ behavior: "smooth", block: "center" });
  }
  function cell(tr, text, cls) { var td = document.createElement("td"); td.textContent = text; if (cls) td.className = cls; tr.appendChild(td); return td; }
  function showButton(tr, e, label) {
    var td = document.createElement("td"), btn = document.createElement("button");
    btn.type = "button"; btn.className = "linkish"; btn.textContent = "Show"; btn.setAttribute("aria-label", "Show " + label + " on the map");
    btn.addEventListener("click", function () { showEvent(e); });
    td.appendChild(btn); tr.appendChild(td);
  }
  function moreButton(id, kind, shown, total, label) {
    var b = document.getElementById(id);
    b.hidden = total <= shown && !state.evAll[kind];
    b.textContent = state.evAll[kind] ? "Show fewer" : "Show all " + total + " " + label;
  }
  function renderEvents() {
    var ev = state.ev, rows = evRows(), jam = state.measure === "jam";
    var sum = document.getElementById("ev-summary"), anomBody = document.querySelector("#ev-anom tbody"),
        burstBody = document.querySelector("#ev-burst tbody"), sbasEl = document.getElementById("ev-sbas");
    document.getElementById("ev-day").textContent = state.day;
    document.getElementById("ev-anom-h").textContent = jam ? "Anomalies, jamming-scale (93 m)" : "Anomalies, accuracy (10 m)";
    document.getElementById("ev-burst-wrap").hidden = !jam;
    document.getElementById("ev-sbas-wrap").hidden = jam;
    anomBody.textContent = ""; burstBody.textContent = ""; sbasEl.textContent = "";
    document.getElementById("ev-body").hidden = !ev;
    if (!ev) { sum.textContent = state.evLoading ? "Loading events…" : "No event data for this day."; return; }

    var n = { major: 0, notable: 0, minor: 0 };
    rows.anomAll.forEach(function (e) { n[e.tier]++; });
    var parts = [];
    if (ev.anomaly_note) parts.push("Anomalies need at least 5 earlier days for a baseline; this day has " + ev.baseline_days + ".");
    else parts.push("Compared with the same hour on " + ev.baseline_days + " earlier days: " + n.major + " major, " + n.notable +
                    " notable and " + n.minor + " minor anomaly events on this measure.");
    if (jam) parts.push(ev.bursts.length + " bursts" + (ev.burst_basis === "within day" ? " (judged against the day's own level: fewer than 5 earlier days)." : "."));
    else parts.push(ev.sbas.length ? "SBAS flags: " + ev.sbas.length + "." : "No SBAS flags.");
    sum.textContent = parts.join(" ");

    rows.anom.forEach(function (e) {
      var tr = document.createElement("tr"), w = when(state.day, e.h0 * 60, e.h1 * 60 + 59);
      cell(tr, TIER[e.tier]); cell(tr, w[0]); cell(tr, w[1], "mut"); cell(tr, ll2(e.lat, e.lon));
      cell(tr, e.regions, "num"); cell(tr, e.peak.toFixed(0) + "%", "num"); cell(tr, "+" + e.excess.toFixed(0) + " pts", "num");
      showButton(tr, e, TIER[e.tier] + " anomaly at " + w[0]); anomBody.appendChild(tr);
    });
    var shown = state.evAll.anom ? rows.anomAll.length : rows.anom.length;
    document.getElementById("ev-anom-note").textContent = ev.anomaly_note ? "No baseline yet for this day."
      : rows.anomAll.length ? (state.evAll.anom ? "All events, ranked by size × excess." : "Major and notable events, ranked by size × excess (top " + EV_ROWS.anom + ").")
      : "No anomaly events on this measure.";
    moreButton("ev-anom-more", "anom", shown, rows.anomAll.length, n.minor ? "events, including minor" : "events");

    rows.burst.forEach(function (e) {
      var tr = document.createElement("tr"), w = when(state.day, mins(e.t0), mins(e.t1));
      cell(tr, w[0]); cell(tr, w[1], "mut"); cell(tr, ll2(e.lat, e.lon)); cell(tr, e.peak, "num"); cell(tr, e.regions, "num");
      showButton(tr, e, "burst at " + w[0]); burstBody.appendChild(tr);
    });
    document.getElementById("ev-burst-note").textContent = rows.burstAll.length ? "Ranked by peak aircraft." : "No bursts on this day.";
    moreButton("ev-burst-more", "burst", rows.burst.length, rows.burstAll.length, "bursts");

    if (!jam) {
      if (!ev.sbas.length) { var p0 = document.createElement("p"); p0.className = "small"; p0.textContent = "No SBAS service area was flagged on this day."; sbasEl.appendChild(p0); }
      else {
        var ul = document.createElement("ul");
        ev.sbas.forEach(function (s) {
          var li = document.createElement("li"), w = when(state.day, s.start * 60, s.end * 60 + 59);
          li.textContent = s.area + ": " + s.state + ", " + w[0] + " (" + w[1] + ")"; ul.appendChild(li);
        });
        sbasEl.appendChild(ul);
      }
    }
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
    state.ev = null; state.evFocus = null; state.evAll = { anom: false, burst: false }; state.evLoading = true;
    fetch("/data/events/" + day + ".json").then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; })
      .then(function (ev) { if (state.day !== day) return; state.ev = ev; state.evLoading = false; renderEvents(); layer.redraw(); });
    renderEvents();
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

  function refresh() { state.evFocus = null; layer.redraw(); renderLegend(); renderStats(); renderTable(); renderEvents(); writeHash(); }

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
    document.getElementById("ev-show").addEventListener("change", function (e) { state.evShow = e.target.checked; layer.redraw(); });
    [["ev-anom-more", "anom"], ["ev-burst-more", "burst"]].forEach(function (p) {
      document.getElementById(p[0]).addEventListener("click", function () {
        state.evAll[p[1]] = !state.evAll[p[1]]; state.evFocus = null; renderEvents(); layer.redraw();
      });
    });
    map.setView([35, 15], window.innerWidth < 700 ? 1.5 : 2.5);
    layer.addTo(map); renderLegend();
    loadDay(day);
    if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () { readColors(); refresh(); });
  });
})();
