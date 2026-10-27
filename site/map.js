/* Noisefloor public map: GNSS degradation per H3 hex from ADS-B (adsb.lol, ODbL).
   Data: /data/gnss/<day>.json (cells: h3, aircraft, bad_live, bad_raw, capable, capable_bad10) and
   /data/events/<day>.json (anomaly events, bursts and SBAS flags from pipeline/pnt_analysis.py).
   One canvas layer draws land and hexes; hover/click looks up the hex under the pointer. */
(function () {
  "use strict";
  var MEASURES = {
    jam: { label: "Jamming-scale loss (worse than 93 m)", unit: "of aircraft degraded",
           breaks: [2, 5, 10, 25], classes: ["Under 2%", "2–5%", "5–10%", "10–25%", "25% or more"] },
    acc: { label: "Accuracy loss (worse than 10 m, capable aircraft)", unit: "of 10 m-capable aircraft degraded",
           breaks: [10, 25, 50, 75], classes: ["Under 10%", "10–25%", "25–50%", "50–75%", "75% or more"] },
    chg: { label: "Change from usual (93 m)", unit: "points above the hex's usual share",
           breaks: [5, 10, 25, 50], classes: ["Under 5 points above usual", "5–10 points", "10–25 points", "25–50 points", "50 points or more"] },
    miss: { label: "Fewer aircraft than usual", unit: "fewer aircraft than the hex's usual count",
            breaks: [30, 50, 70, 90], classes: ["Under 30% fewer, or more", "30–50% fewer", "50–70% fewer", "70–90% fewer", "90% or more fewer"] }
  };
  var MISS_MIN = 10;                                  // the "fewer aircraft" view needs a usual count of 10 or more
  // SBAS areas flagged on most days in the first year (GAGAN 162 of 344 days, SouthPAN 229): most aircraft there don't
  // use the service, so their flags mark the 10 m measure as unreliable, not an outage. Listed apart from the rest.
  var ROUTINE_SBAS = { "GAGAN (India)": true, "SouthPAN (Australia/NZ)": true };
  function sbasSplit(runs) {
    var main = [], routine = {};
    (runs || []).forEach(function (s) {
      if (ROUTINE_SBAS[s.area]) routine[s.area] = (routine[s.area] || 0) + (s.end - s.start + 1); else main.push(s);
    });
    return { main: main, routine: routine };
  }
  function emeasure() { return state.measure === "acc" ? "acc" : "jam"; }    // events and the strip follow 93 m for chg
  var state = { day: null, measure: "jam", raw: false, ev: null, evShow: true, evAll: { anom: false, burst: false }, evFocus: null,
                iu: -1, iun: -1, playing: false, hist: null };
  var EV_ROWS = { anom: 15, burst: 10 };
  var TIER = { major: "Major", notable: "Notable", minor: "Minor" };
  var days = [], cells = {}, cellList = [], land = [], colors = {}, borders = [], places = [], areas = [];
  var layersOn = { borders: true, places: true, areas: false };
  var imagery = { on: false, want: false, key: null, layer: null };   // Esri World Imagery under the hexes (not remembered between visits)
  var BASE_MAX_ZOOM = 7, IMG_MAX_ZOOM = 10;                            // imagery is worth a closer look
  try { var savedLayers = JSON.parse(localStorage.getItem("nf-map-layers") || "null"); if (savedLayers) layersOn = Object.assign(layersOn, savedLayers); } catch (e) { /* defaults */ }
  var mapEl = document.getElementById("map");
  if (!mapEl || !window.L || !window.h3) return;

  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function readColors() {
    colors = { ocean: css("--map-ocean"), land: css("--map-land"), coast: css("--map-coast"), quiet: css("--map-quiet"),
               low: css("--map-low"), ramp: [css("--ramp-1"), css("--ramp-2"), css("--ramp-3"), css("--ramp-4")],
               focus: css("--fg"), event: css("--map-event"), ring: css("--map-ocean"), test: css("--ink-2"),
               border: css("--map-border"), label: css("--map-label"), halo: css("--map-halo"), area: css("--map-area"),
               spoof: css("--map-spoof"), cyg: css("--map-cyg") };
    mapEl.style.background = colors.ocean;
  }

  // value and class for a cell under the current measure; null = not drawn
  function evaluate(c) {
    var n, bad;
    if (state.measure === "miss") {                  // today's aircraft against the hex's usual count
      var u = state.iun >= 0 ? c[state.iun] : null;
      if (u === null || u === undefined || u < MISS_MIN) return null;
      var drop = 100 * (1 - c[1] / u), bm = MEASURES.miss.breaks, km = 0;
      while (km < bm.length && drop >= bm[km]) km++;
      return { cls: km === 0 ? "quiet" : km - 1, share: drop, n: c[1], bad: c[2], usual: u, today: c[1] };
    }
    if (state.measure === "acc") { n = c[4]; bad = c[5]; }
    else { n = c[1]; bad = state.raw && state.measure === "jam" ? c[3] : c[2]; }
    if (n < 3) return null;
    if (n < 5) return { cls: "low", share: null, n: n, bad: bad };
    var share = 100 * Math.max(bad - 1, 0) / n;        // one bad aircraft never colours a hex (GPSJam's formula)
    var today = share, usual = null;
    if (state.measure === "chg") {
      usual = state.iu >= 0 ? c[state.iu] : null;
      if (usual === null || usual === undefined) return { cls: "low", share: null, n: n, bad: bad, nobase: true };
      share = today - usual;
    }
    var b = MEASURES[state.measure].breaks, k = 0;
    while (k < b.length && share >= b[k]) k++;
    return { cls: k === 0 ? "quiet" : k - 1, share: share, n: n, bad: bad, today: today, usual: usual };
  }

  var map = L.map(mapEl, { minZoom: 1, maxZoom: BASE_MAX_ZOOM, zoomSnap: 0.5, worldCopyJump: false,
                           maxBounds: [[-85, -200], [85, 200]], attributionControl: true });
  map.attributionControl.setPrefix(false);
  map.attributionControl.addAttribution('ADS-B: <a href="https://www.adsb.lol/">adsb.lol</a> contributors (ODbL 1.0) · Land: Natural Earth');

  // ---------- geometry in Web Mercator units (0..1), converted once; a redraw is then scale * x + offset
  function mercArr(pts) {                              // [[lat, lon], ...] -> Float64Array [x0, y0, x1, y1, ...]
    var out = new Float64Array(pts.length * 2);
    for (var i = 0; i < pts.length; i++) {
      var s = Math.sin(Math.max(-85.0511, Math.min(85.0511, pts[i][0])) * Math.PI / 180);
      out[2 * i] = (pts[i][1] + 180) / 360;
      out[2 * i + 1] = 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI);
    }
    return out;
  }
  function mercBox(m) {
    var x0 = 1, y0 = 1, x1 = 0, y1 = 0;
    for (var i = 0; i < m.length; i += 2) {
      if (m[i] < x0) x0 = m[i]; if (m[i] > x1) x1 = m[i];
      if (m[i + 1] < y0) y0 = m[i + 1]; if (m[i + 1] > y1) y1 = m[i + 1];
    }
    return [x0, y0, x1, y1];
  }
  var vw = { k: 256, ox: 0, oy: 0, w: 0, h: 0 };     // the current view: container = k * merc + offset
  function setView(m) {
    var k = 256 * Math.pow(2, m.getZoom()), c = m.latLngToContainerPoint([0, 0]), sz = m.getSize();
    vw = { k: k, ox: c.x - 0.5 * k, oy: c.y - 0.5 * k, w: sz.x, h: sz.y };
  }
  function onScreen(bx) {
    return !(bx[0] * vw.k + vw.ox > vw.w + 40 || bx[2] * vw.k + vw.ox < -40 || bx[1] * vw.k + vw.oy > vw.h + 40 || bx[3] * vw.k + vw.oy < -40);
  }
  function trace(g, m, close) {
    var k = vw.k, ox = vw.ox, oy = vw.oy;
    g.moveTo(m[0] * k + ox, m[1] * k + oy);
    for (var i = 2; i < m.length; i += 2) g.lineTo(m[i] * k + ox, m[i + 1] * k + oy);
    if (close) g.closePath();
  }
  function cp(lat, lon) {                              // one container point in the current view
    var m = mercArr([[lat, lon]]);
    return { x: m[0] * vw.k + vw.ox, y: m[1] * vw.k + vw.oy };
  }

  var Canvas = L.Layer.extend({
    onAdd: function (m) {
      this._c = L.DomUtil.create("canvas", "nf-canvas leaflet-zoom-hide");
      m.getPanes().overlayPane.appendChild(this._c);
      m.on("moveend zoomend resize viewreset", this.redraw, this);
      this.redraw();
    },
    onRemove: function (m) { L.DomUtil.remove(this._c); m.off("moveend zoomend resize viewreset", this.redraw, this); },
    redraw: function () {                              // requests in one task become one draw
      if (this._queued) return;
      this._queued = true;
      var self = this;
      Promise.resolve().then(function () { self._queued = false; self._draw(); });
    },
    _draw: function () {
      if (!this._map) return;                          // data can arrive before the layer is on the map
      var m = this._map, size = m.getSize(), dpr = window.devicePixelRatio || 1, c = this._c;
      c.width = size.x * dpr; c.height = size.y * dpr; c.style.width = size.x + "px"; c.style.height = size.y + "px";
      L.DomUtil.setPosition(c, m.containerPointToLayerPoint([0, 0]));
      var g = c.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
      setView(m);
      if (!imagery.on) {                               // under satellite imagery the land fill would hide it
        g.fillStyle = colors.land; g.strokeStyle = colors.coast; g.lineWidth = 0.6;
        g.beginPath();
        land.forEach(function (ring) { if (onScreen(ring.mb)) trace(g, ring.m, true); });
        g.fill(); g.stroke();
      }
      // one choice per view: a resolution-4 hex is about 45 km across (0.00112 of the equator), wider in Mercator nearer
      // the poles; under 6 pixels at the view's centre, every hex is drawn as a rectangle
      var useRects = 0.00112 / Math.max(0.2, Math.cos(m.getCenter().lat * Math.PI / 180)) * vw.k < 6;
      var byCls = { low: [], quiet: [], 0: [], 1: [], 2: [], 3: [] };
      cellList.forEach(function (cl) {
        if (!onScreen(cl.s.mb)) return;
        var e = evaluate(cl.d); if (!e) return;
        byCls[e.cls].push(cl);
      });
      [["low", colors.low], ["quiet", colors.quiet], [0, colors.ramp[0]], [1, colors.ramp[1]], [2, colors.ramp[2]], [3, colors.ramp[3]]]
        .forEach(function (pair) {
          g.fillStyle = pair[1]; g.beginPath();
          // over imagery: quiet and low-coverage hexes faint, the interference classes still strong
          g.globalAlpha = !imagery.on ? 1 : pair[0] === "low" || pair[0] === "quiet" ? 0.22 : 0.72;
          var small = [];
          byCls[pair[0]].forEach(function (cl) {
            if (useRects) small.push(cl);              // hexes a few pixels across: rectangles look the same
            else trace(g, cl.s.m, true);
          });
          g.fill();
          small.forEach(function (cl) {                // filling thousands of tiny polygons is slow; rectangles aren't
            var bx = cl.s.mb, x0 = Math.floor(bx[0] * vw.k + vw.ox), y0 = Math.floor(bx[1] * vw.k + vw.oy);
            g.fillRect(x0, y0, Math.max(1, Math.ceil(bx[2] * vw.k + vw.ox) - x0), Math.max(1, Math.ceil(bx[3] * vw.k + vw.oy) - y0));   // whole pixels: no seams
          });
        });
      g.globalAlpha = 1;
      if (state.focus && cells[state.focus]) {
        g.strokeStyle = colors.focus; g.lineWidth = 2; g.beginPath();
        trace(g, cells[state.focus].s.m, true); g.stroke();
      }
      var labels = [];
      if (layersOn.borders && borders.length) {
        g.save(); g.lineWidth = 0.9; g.strokeStyle = colors.border;
        [0, 1].forEach(function (cls) {
          g.setLineDash(cls ? [3, 3] : []); g.beginPath();
          borders.forEach(function (l) { if (l.cls === cls && onScreen(l.mb)) trace(g, l.m, false); });
          g.stroke();
        });
        g.restore();
      }
      var inView = function (q) { return q.x > -20 && q.x < vw.w + 20 && q.y > -20 && q.y < vw.h + 20; };
      if (layersOn.areas && areas.length) {
        g.save(); g.setLineDash([2, 4]); g.strokeStyle = colors.area; g.lineWidth = 1.3;
        areas.forEach(function (a) {
          var p0 = cp(a[2], a[3]), p1 = cp(a[1], a[4]);
          g.strokeRect(p0.x, p0.y, p1.x - p0.x, p1.y - p0.y);
          labels.push({ text: a[0], x: p0.x + 4, y: p0.y + 13, kind: "area" });
        });
        g.restore();
      }
      if (layersOn.places && places.length) {
        var z = m.getZoom(), maxRank = z < 2 ? 0 : z < 3 ? 1 : z < 4 ? 2 : z < 5 ? 3 : z < 6 ? 4 : 7;
        places.forEach(function (p) {
          if (p[3] > maxRank && !(p[4] && z >= 3.5)) return;
          var q = cp(p[1], p[2]);
          if (!inView(q)) return;
          labels.push({ text: p[0], x: q.x + 5, y: q.y + 4, dot: q, cap: !!p[4], kind: "place" });
        });
      }
      if (state.cygShow && state.cyg && state.cyg.cells) {          // CYGNSS: raised noise-floor cells (H3 res 3)
        g.save(); g.strokeStyle = colors.cyg; g.fillStyle = colors.cyg;
        state.cyg.cells.forEach(function (c) {
          var sh = shapeOf(c[0]);
          if (sh.wrap || !onScreen(sh.mb)) return;
          g.globalAlpha = c[1] >= 2 ? 0.35 : 0.18; g.beginPath(); trace(g, sh.m, true); g.fill();
          g.globalAlpha = 0.9; g.lineWidth = c[1] >= 2 ? 1.6 : 0.8; g.stroke();
        });
        g.restore();
      }
      if (state.spoofShow && state.spoof) {                           // spoofing: where spoofed aircraft really were
        g.save(); g.strokeStyle = colors.spoof; g.fillStyle = colors.spoof;
        (state.spoof.cells || []).forEach(function (c) {
          var sh = shapeOf(c[0]);
          if (sh.wrap || !onScreen(sh.mb)) return;
          g.globalAlpha = Math.min(0.55, 0.15 + 0.08 * c[1]); g.beginPath(); trace(g, sh.m, true); g.fill();
          g.globalAlpha = 1; g.lineWidth = 1.2; g.stroke();
        });
        g.globalAlpha = 1; g.lineWidth = 2;                         // where their receivers were told they were
        (state.spoof.spoofed_to_top || []).forEach(function (p) {
          var q = cp(p.lat, p.lon), r = 6;
          g.beginPath(); g.moveTo(q.x - r, q.y - r); g.lineTo(q.x + r, q.y + r); g.moveTo(q.x + r, q.y - r); g.lineTo(q.x - r, q.y + r); g.stroke();
        });
        g.restore();
      }
      if (state.evShow && state.ev && state.ev.tests) {
        g.save(); g.setLineDash([6, 5]); g.strokeStyle = colors.test; g.lineWidth = 1.5;
        state.ev.tests.forEach(function (t) {
          var nm = t.radii_nm.FL250 || Math.max.apply(null, Object.keys(t.radii_nm).map(function (k) { return t.radii_nm[k]; }).concat([0]));
          var ctr = cp(t.centre[0], t.centre[1]), top = cp(t.centre[0] + nm * 1.852 / 111.32, t.centre[1]);
          g.beginPath(); g.arc(ctr.x, ctr.y, Math.abs(ctr.y - top.y), 0, 2 * Math.PI); g.stroke();
        });
        g.restore();
      }
      if (state.evShow && state.ev) {
        var rows = evRows();
        var outline = function (e) {
          if (!e.polyM) e.polyM = poly(e).map(function (loops) { return loops.map(mercArr); });
          g.beginPath();
          e.polyM.forEach(function (loops) { loops.forEach(function (loop) { trace(g, loop, true); }); });
          g.stroke();
        };
        g.strokeStyle = colors.event; g.lineWidth = 2;
        rows.anom.forEach(function (e) { if (e !== state.evFocus) outline(e); });
        rows.burst.forEach(function (e) {
          if (e === state.evFocus) return;
          var q = cp(e.lat, e.lon);
          g.beginPath(); g.arc(q.x, q.y, 5, 0, 2 * Math.PI); g.fillStyle = colors.event; g.fill();
          g.lineWidth = 2; g.strokeStyle = colors.ring; g.stroke(); g.strokeStyle = colors.event;
        });
        if (state.evFocus) {
          g.strokeStyle = colors.focus; g.lineWidth = 3;
          if (state.evFocus.t0) {
            var q = cp(state.evFocus.lat, state.evFocus.lon);
            g.beginPath(); g.arc(q.x, q.y, 7, 0, 2 * Math.PI); g.fillStyle = colors.event; g.fill(); g.stroke();
          } else outline(state.evFocus);
        }
      }
      // labels last, with a halo, skipping any that would overlap one already drawn
      if (labels.length) {
        var taken = [], font = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
        g.save(); g.lineJoin = "round"; g.textBaseline = "alphabetic";
        labels.forEach(function (l) {
          g.font = (l.kind === "area" ? "italic 11px " : l.cap ? "600 11.5px " : "11px ") + font;
          var w = g.measureText(l.text).width, r = [l.x - 2, l.y - 11, l.x + w + 2, l.y + 3];
          if (taken.some(function (t) { return r[0] < t[2] && r[2] > t[0] && r[1] < t[3] && r[3] > t[1]; })) return;
          taken.push(r);
          if (l.dot) {
            g.fillStyle = colors.label;
            if (l.cap) g.fillRect(l.dot.x - 2.5, l.dot.y - 2.5, 5, 5);
            else { g.beginPath(); g.arc(l.dot.x, l.dot.y, 2, 0, 2 * Math.PI); g.fill(); }
          }
          g.strokeStyle = colors.halo; g.lineWidth = 3; g.strokeText(l.text, l.x, l.y);
          g.fillStyle = l.kind === "area" ? colors.area : colors.label; g.fillText(l.text, l.x, l.y);
        });
        g.restore();
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
    if (state.measure !== "acc") {
      lines.push(["Aircraft", d[1]]);
      lines.push(["Worse than 93 m", (state.raw ? d[3] : d[2]) + (state.raw ? "" : " (live)")]);
      if (!state.raw && d[3] !== d[2]) lines.push(["Incl. post-exposure", d[3]]);
    } else {
      lines.push(["10 m-capable aircraft", d[4]]);
      lines.push(["Worse than 10 m", d[5]]);
    }
    if (state.measure === "miss") {
      lines.push(["Usual aircraft (14-day median)", e ? e.usual : "under " + MISS_MIN + " or not enough history"]);
      if (e) lines.push(["Change", e.share >= 0 ? Math.round(e.share) + "% fewer" : Math.round(-e.share) + "% more"]);
    } else if (state.measure === "chg" && e && e.share !== null) {
      lines.push(["Share today", e.today.toFixed(1) + "%"]);
      lines.push(["Usual (14-day median)", e.usual.toFixed(1) + "%"]);
      lines.push(["Change", (e.share >= 0 ? "+" : "") + e.share.toFixed(1) + " points"]);
    } else {
      lines.push(["Share", e && e.share !== null ? e.share.toFixed(1) + "%" :
        (e && e.nobase ? "no usual level yet (fewer than 5 earlier days)" : e ? "low coverage (3–4 aircraft)" : "too few aircraft")]);
    }
    if (state.spoofShow && state.spoof && state.spoof.cells) {
      var sc = state.spoof.cells.filter(function (c) { return c[0] === h; })[0];
      if (sc) lines.push(["Spoofing", sc[1] + " active episode" + (sc[1] === 1 ? "" : "s") + " (aircraft really here)"]);
    }
    if (state.cygShow && state.cyg && state.cyg.cells) {
      var p3 = h3.cellToParent(h, 3), cc = state.cyg.cells.filter(function (c) { return c[0] === p3; })[0];
      if (cc) lines.push(["CYGNSS", "+" + cc[1].toFixed(1) + " dB noise floor" + (state.cyg.day !== state.day ? " (" + state.cyg.day + ")" : "")]);
    }
    lines.push(["", "Click for this area's history"]);
    if (state.evShow && state.ev) {
      var r2 = h3.cellToParent(h, 2);
      evRows().anom.forEach(function (a) {
        if (a.cells.indexOf(r2) >= 0) lines.push(["Anomaly", TIER[a.tier] + ", " + pad(a.h0) + ":00–" + pad(a.h1) + ":59Z"]);
      });
      (state.ev.tests || []).forEach(function (t) {
        var nm = t.radii_nm.FL250 || 0, d = h3.greatCircleDistance(ll, t.centre, "km");
        if (nm && d <= nm * 1.852) lines.push(["Announced test", t.id]);
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
    if (cells[h]) { state.pinned = true; state.focus = h; showTip(h, ev.containerPoint); layer.redraw(); openHistory(h); }
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
      var shareText = state.measure === "chg" ? "+" + x.e.share.toFixed(1) + " pts (" + x.e.today.toFixed(0) + "% vs " + x.e.usual.toFixed(0) + "%)"
        : state.measure === "miss" ? Math.round(x.e.share) + "% fewer (" + x.e.today + " vs " + x.e.usual + ")" : x.e.share.toFixed(1) + "%";
      [ll[0].toFixed(1) + ", " + ll[1].toFixed(1), x.e.n, x.e.bad, shareText].forEach(function (v, i) {
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
  var TZ = window.TicTime ? window.TicTime.zone() : "America/Chicago", HC = window.TicTime && !window.TicTime.hour12() ? "h23" : "h12";
  var CT = new Intl.DateTimeFormat("en-US", { timeZone: TZ, month: "short", day: "numeric",
                                              hour: "numeric", minute: "2-digit", hourCycle: HC, timeZoneName: "short" });
  var UT = new Intl.DateTimeFormat("en-US", { timeZone: "UTC", month: "short", day: "numeric" });
  function central(day, mins) {
    var p = day.split("-"), d = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2], 0, mins)), x = {};
    CT.formatToParts(d).forEach(function (q) { x[q.type] = q.value; });
    return { time: x.hour + ":" + x.minute + (x.dayPeriod ? " " + x.dayPeriod.toLowerCase() : ""), zone: x.timeZoneName,
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
    var anomAll = ev.anomalies.filter(function (e) { return e.m === emeasure(); });
    var anom = state.evAll.anom ? anomAll : anomAll.filter(function (e) { return e.tier !== "minor"; }).slice(0, EV_ROWS.anom);
    var burstAll = emeasure() === "jam" ? ev.bursts : [];
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
  function heavyCell(tr, hs) {     // A350/A380 share of the event's degraded aircraft (null before 25 Oct 2026)
    if (hs === null || hs === undefined) return cell(tr, "–", "mut num");
    var td = cell(tr, "", "num"), txt = Math.round(hs * 100) + "%";
    if (hs >= 0.5) { var b = document.createElement("strong"); b.textContent = txt; td.appendChild(b); td.title = "Mostly A350/A380 reports"; }
    else td.textContent = txt;
    return td;
  }
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
    var ev = state.ev, rows = evRows(), jam = emeasure() === "jam";
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
    else { var nS = sbasSplit(ev.sbas).main.length; parts.push(nS ? "SBAS flags: " + nS + "." : "No SBAS flags."); }
    sum.textContent = parts.join(" ");
    var testsEl = document.getElementById("ev-tests"); testsEl.textContent = "";
    if (ev.tests && ev.tests.length) {
      testsEl.appendChild(document.createTextNode("Announced GPS tests this day (FAA flight advisories): "));
      ev.tests.forEach(function (t, k) {
        var a = document.createElement("a"); a.href = t.url; a.textContent = t.id; a.rel = "noopener";
        if (k) testsEl.appendChild(document.createTextNode("; "));
        testsEl.appendChild(a);
        var w0 = t.windows[0], w1 = t.windows[t.windows.length - 1];
        testsEl.appendChild(document.createTextNode(", " + t.place + ", " + w0[0].slice(11, 16) + "–" + w1[1].slice(11, 16) + "Z"));
      });
      testsEl.appendChild(document.createTextNode("."));
    }

    rows.anom.forEach(function (e) {
      var tr = document.createElement("tr"), w = when(state.day, e.h0 * 60, e.h1 * 60 + 59);
      cell(tr, TIER[e.tier]); cell(tr, w[0]); cell(tr, w[1], "mut"); cell(tr, ll2(e.lat, e.lon));
      cell(tr, e.regions, "num"); cell(tr, e.peak.toFixed(0) + "%", "num"); cell(tr, "+" + e.excess.toFixed(0) + " pts", "num");
      heavyCell(tr, e.m === "jam" ? e.hs : null);
      cell(tr, e.test || "–", e.test ? "" : "mut");
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
      heavyCell(tr, e.hs);
      cell(tr, e.test || "–", e.test ? "" : "mut");
      showButton(tr, e, "burst at " + w[0]); burstBody.appendChild(tr);
    });
    document.getElementById("ev-burst-note").textContent = rows.burstAll.length ? "Ranked by peak aircraft." : "No bursts on this day.";
    moreButton("ev-burst-more", "burst", rows.burst.length, rows.burstAll.length, "bursts");

    if (!jam) {
      var sp = sbasSplit(ev.sbas), rk = Object.keys(sp.routine);
      if (!sp.main.length) {
        var p0 = document.createElement("p"); p0.className = "small";
        p0.textContent = rk.length ? "No other SBAS service area was flagged on this day." : "No SBAS service area was flagged on this day.";
        sbasEl.appendChild(p0);
      }
      else {
        var ul = document.createElement("ul");
        sp.main.forEach(function (s) {
          var li = document.createElement("li"), w = when(state.day, s.start * 60, s.end * 60 + 59);
          li.textContent = s.area + ": " + s.state + ", " + w[0] + " (" + w[1] + ")"; ul.appendChild(li);
        });
        sbasEl.appendChild(ul);
      }
      if (rk.length) {
        var pr = document.createElement("p"); pr.className = "small";
        pr.textContent = (sp.main.length ? "Also flagged" : "Flagged") + ", as on most days: " + rk.map(function (a) { return a + " (" + sp.routine[a] + " h)"; }).join(", ") +
          ". Most aircraft there don't use these SBAS services, so the 10 m measure is unreliable in these areas; the flag drops it there rather than signalling an outage.";
        if (sp.main.length) sbasEl.appendChild(pr); else sbasEl.insertBefore(pr, sbasEl.firstChild);
      }
    }
  }

  // ---------- legend, stats, controls
  function renderLegend() {
    var m = MEASURES[state.measure], el = document.getElementById("map-legend");
    el.textContent = "";
    var items = (state.measure === "miss" ? [] : [["low", "Low coverage (3–4 aircraft)"]])
      .concat([["quiet", m.classes[0]]]).concat(m.classes.slice(1).map(function (t, i) { return [i, t]; }));
    items.forEach(function (it) {
      var s = document.createElement("span"), sw = document.createElement("i");
      sw.style.background = it[0] === "low" ? colors.low : it[0] === "quiet" ? colors.quiet : colors.ramp[it[0]];
      s.appendChild(sw); s.appendChild(document.createTextNode(it[1])); el.appendChild(s);
    });
    var cap = document.getElementById("map-measure-note");
    cap.textContent = state.measure === "miss"
      ? "Aircraft in the hex today against its median over its previous 14 days (days without traffic count as zero; shown where that median is 10 or more). Strong jamming can stop aircraft sending a position at all, so they vanish instead of showing as degraded. Weekends, holidays, airspace closures and receiver outages also lower counts."
      : state.measure === "chg"
      ? "Today's jamming-scale share minus the hex's own median over its previous 14 days with traffic (live counts). Persistent hotspots fade; new or growing activity stands out."
      : state.measure === "jam"
      ? (state.raw ? "Raw: includes aircraft still degraded after leaving interference (comparable with GPSJam)."
                   : "Live: aircraft still degraded after leaving interference elsewhere are left out.")
      : "Counted only for aircraft that showed 10 m accuracy at least once that day. Space weather and SBAS outages show here.";
  }
  // ---------- timeline: one bar per available day (selected measure), a slider and previous/next
  var TL = {
    jam: { key: "jam_hexes", title: "Hexes at jamming scale (10% or more of aircraft degraded), per day" },
    acc: { key: "acc_hexes", title: "Hexes where 50% or more of 10 m-capable aircraft fell below 10 m, per day" }
  };
  var tlTimer = null;
  function dayIndex(day) { for (var i = 0; i < days.length; i++) if (days[i].day === day) return i; return -1; }
  function renderTimeline() {
    var strip = document.getElementById("tl-strip"); if (!strip || !days.length) return;
    var key = TL[emeasure()].key, n = days.length, W = Math.max(280, strip.clientWidth), H = 56;
    var vals = days.map(function (d) { return d[key] || 0; }), max = Math.max.apply(null, vals.concat([1]));
    var NS = "http://www.w3.org/2000/svg", bw = W / n, cur = dayIndex(state.day);
    document.getElementById("tl-title").textContent = TL[emeasure()].title;
    document.getElementById("tl-range").textContent = " · " + days[0].day + " to " + days[n - 1].day + " · peak " + max.toLocaleString();
    strip.textContent = "";
    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H); svg.setAttribute("width", W); svg.setAttribute("height", H);
    svg.setAttribute("aria-hidden", "true");
    days.forEach(function (d, i) {
      var h = Math.max(vals[i] > 0 ? 1 : 0, (H - 8) * vals[i] / max), x = i * bw;
      var r = document.createElementNS(NS, "rect");
      r.setAttribute("x", x + (bw > 3 ? 0.5 : 0)); r.setAttribute("width", Math.max(1, bw - (bw > 3 ? 1 : 0)));
      r.setAttribute("y", H - 6 - h); r.setAttribute("height", h);
      r.setAttribute("class", i === cur ? "tl-bar on" : "tl-bar");
      svg.appendChild(r);
      if (d.note) {                                        // a named day: small mark under its bar
        var c = document.createElementNS(NS, "rect");
        c.setAttribute("x", x); c.setAttribute("y", H - 3); c.setAttribute("width", Math.max(2, bw)); c.setAttribute("height", 3);
        c.setAttribute("class", "tl-mark"); svg.appendChild(c);
      }
    });
    strip.appendChild(svg);
    var tipEl = document.getElementById("tl-tip");
    if (!tipEl) { tipEl = document.createElement("div"); tipEl.id = "tl-tip"; tipEl.className = "tl-tip"; tipEl.hidden = true; strip.parentNode.appendChild(tipEl); }
    function at(ev) { var b = strip.getBoundingClientRect(); return Math.max(0, Math.min(n - 1, Math.floor((ev.clientX - b.left) / (b.width / n)))); }
    strip.onmousemove = function (ev) {
      var i = at(ev), d = days[i];
      tipEl.textContent = d.day + " · " + (d[key] || 0).toLocaleString() + " hexes" + (d.note ? " · " + d.note : "") + (d.daily ? "" : " · validated");
      tipEl.hidden = false;
      var b = strip.getBoundingClientRect(), p = strip.parentNode.getBoundingClientRect();
      tipEl.style.left = Math.max(0, Math.min(ev.clientX - p.left + 10, p.width - tipEl.offsetWidth)) + "px";
      tipEl.style.top = (b.top - p.top - tipEl.offsetHeight - 4) + "px";
    };
    strip.onmouseleave = function () { tipEl.hidden = true; };
    strip.onclick = function (ev) { var i = at(ev); if (days[i].day !== state.day) { document.getElementById("map-day").value = days[i].day; loadDay(days[i].day); } };
    syncTimeline();
  }
  function syncTimeline() {
    var sl = document.getElementById("tl-slider"); if (!sl || !days.length) return;
    var i = dayIndex(state.day), d = days[i];
    sl.max = days.length - 1; if (i >= 0) sl.value = i;
    sl.setAttribute("aria-valuetext", state.day);
    document.getElementById("tl-day").textContent = state.day + (d && d.daily ? "" : " · validated");
    document.getElementById("tl-prev").disabled = document.getElementById("mp-prev").disabled = i <= 0;
    document.getElementById("tl-next").disabled = document.getElementById("mp-next").disabled = i >= days.length - 1;
    document.getElementById("mp-day").textContent = state.day || "";
    var bars = document.querySelectorAll("#tl-strip .tl-bar");
    for (var k = 0; k < bars.length; k++) bars[k].setAttribute("class", k === i ? "tl-bar on" : "tl-bar");
  }
  function stepTo(i, now) {
    i = Math.max(0, Math.min(days.length - 1, i));
    var day = days[i].day;
    document.getElementById("tl-day").textContent = day + (days[i].daily ? "" : " · validated");
    clearTimeout(tlTimer);
    var go = function () { if (day !== state.day) { document.getElementById("map-day").value = day; loadDay(day); } };
    if (now) go(); else tlTimer = setTimeout(go, 250);   // dragging: load once the slider rests
  }

  function renderStats() {
    var d = days.filter(function (x) { return x.day === state.day; })[0];
    var el = document.getElementById("map-stats");
    var drawn = cellList.filter(function (c) { var e = evaluate(c.d); return e && e.share !== null; }).length;
    var hot = cellList.filter(function (c) { var e = evaluate(c.d); return e && typeof e.cls === "number" && e.cls >= 2; }).length;
    el.textContent = drawn.toLocaleString() + (state.measure === "miss" ? " hexes with a usual count of " + MISS_MIN + " or more" : " hexes with 5 or more aircraft") +
      " · " + hot.toLocaleString() + " in the top two classes";
    var a = document.getElementById("map-download"); a.href = "/data/gnss/" + state.day + ".json"; a.textContent = "Download " + state.day + " (JSON, ODbL)";
    var note = document.getElementById("map-day-note");
    note.textContent = d && d.daily ? "Daily run: automatic, not reviewed by a person" : d && d.note ? d.note : "";
  }
  function hashFor() {
    var c = map.getCenter();
    return "#day=" + state.day + "&m=" + state.measure + (state.raw ? "&raw=1" : "") + (imagery.on ? "&img=esri" : "") +
           (state.spoofShow ? "&sp=1" : "") + (state.cygShow ? "&cy=1" : "") +
           "&v=" + c.lat.toFixed(2) + "," + c.lng.toFixed(2) + "," + map.getZoom();
  }
  function writeHash() { if (state.day) history.replaceState(null, "", hashFor()); }

  // loaded days (last 12) and hex shapes (by H3 index, shared across days)
  var dayCache = {}, dayOrder = [], shapes = {};
  function fetchDay(day) {
    if (dayCache[day]) return dayCache[day];
    var p = fetch("/data/gnss/" + day + ".json").then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
    dayCache[day] = p; dayOrder.push(day);
    p.catch(function () { delete dayCache[day]; });
    while (dayOrder.length > 12) delete dayCache[dayOrder.shift()];
    return p;
  }
  function shapeOf(h) {
    var sh = shapes[h];
    if (!sh) {
      var bnd = h3.cellToBoundary(h), lo0 = 999, lo1 = -999;
      bnd.forEach(function (p) { if (p[1] < lo0) lo0 = p[1]; if (p[1] > lo1) lo1 = p[1]; });
      var mm = mercArr(bnd);
      sh = shapes[h] = { m: mm, mb: mercBox(mm), wrap: lo1 - lo0 > 180 };   // wrap: crosses the antimeridian (skipped)
    }
    return sh;
  }
  function prefetchAround(day) {
    var i = days.map(function (x) { return x.day; }).indexOf(day);
    [i - 1, i + 1].forEach(function (k) { if (days[k]) fetchDay(days[k].day).catch(function () {}); });
  }

  var layerIndex = {};                                 // days with spoofing / CYGNSS files (data/<kind>/index.json)
  function layerFor(kind, day) {                       // the day's file, or for CYGNSS the newest day up to 3 days before
    var idx = layerIndex[kind] || [];
    var pick = idx.indexOf(day) >= 0 ? day : null;
    if (!pick && kind === "cygnss") {
      for (var k = 1; k <= 3 && !pick; k++) {
        var d = new Date(Date.parse(day + "T00:00:00Z") - k * 86400000).toISOString().slice(0, 10);
        if (idx.indexOf(d) >= 0) pick = d;
      }
    }
    if (!pick) return Promise.resolve(null);
    return fetch("/data/" + kind + "/" + pick + ".json").then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });
  }
  function nearest(kind, day) {                        // the closest day that has a layer file, for the "none" note
    var t = Date.parse(day + "T00:00:00Z"), best = null;
    (layerIndex[kind] || []).forEach(function (d) {
      if (best === null || Math.abs(Date.parse(d + "T00:00:00Z") - t) < Math.abs(Date.parse(best + "T00:00:00Z") - t)) best = d;
    });
    return best ? " Nearest day with one: " + best + "." : "";
  }
  function layerNote() {
    var note = document.getElementById("lyr-note"), parts = [];
    if (!note) return;
    if (state.spoofShow) parts.push(state.spoof ? "Spoofing " + state.spoof.day + ": " + state.spoof.active + " active episodes; outlines show where spoofed aircraft really were, crosses where their receivers were told they were."
      : "No spoofing layer for this day (daily from 27 Oct 2026, plus 17 earlier days)." + nearest("spoof", state.day));
    if (state.cygShow) parts.push(state.cyg ? "CYGNSS " + state.cyg.day + ": " + state.cyg.raised_cells + " cells raised 1 dB or more (exposure within a beam a few hundred km wide, not a transmitter site; about 38°N to 38°S). Source: NASA CYGNSS L1 V3.2 (PO.DAAC), NASA open data."
      : "No CYGNSS file within 3 days of this day (CYGNSS runs about six days behind)." + nearest("cygnss", state.day));
    note.textContent = parts.join(" ");
  }
  function loadLayers(day) {
    if (state.spoofShow) layerFor("spoof", day).then(function (j) { if (state.day !== day) return; state.spoof = j; layerNote(); layer.redraw(); });
    if (state.cygShow) layerFor("cygnss", day).then(function (j) { if (state.day !== day) return; state.cyg = j; layerNote(); layer.redraw(); });
    layerNote();
  }

  function loadDay(day) {
    state.day = day; state.focus = null; state.pinned = false; tip.hidden = true;
    state.spoof = null; state.cyg = null; loadLayers(day);
    state.ev = null; state.evFocus = null; state.evAll = { anom: false, burst: false }; state.evLoading = true;
    syncTimeline();
    fetch("/data/events/" + day + ".json").then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; })
      .then(function (ev) { if (state.day !== day) return; state.ev = ev; state.evLoading = false; renderEvents(); layer.redraw(); });
    renderEvents();
    mapEl.classList.add("loading");
    return fetchDay(day).then(function (j) {
      if (state.day !== day) return;                  // a later choice won
      cells = {}; cellList = [];
      j.cells.forEach(function (d) {
        var sh = shapeOf(d[0]);
        if (sh.wrap) return;
        var c = { h: d[0], d: d, s: sh }; cells[d[0]] = c; cellList.push(c);
      });
      state.iu = (j.cols || []).indexOf("usual");
      document.getElementById("mp-chg-wrap").classList.toggle("off", state.iu < 0);
      document.querySelector('input[name="measure"][value="chg"]').disabled = state.iu < 0;
      state.iun = (j.cols || []).indexOf("usual_n");
      document.getElementById("mp-miss-wrap").classList.toggle("off", state.iun < 0);
      document.querySelector('input[name="measure"][value="miss"]').disabled = state.iun < 0;
      mapEl.classList.remove("loading");
      layer.redraw(); renderStats(); renderTable(); writeHash(); if (state.hist) drawHistory();
      setTimeout(function () { prefetchAround(day); }, 300);
    });
  }

  // ---------- play through the days (waits for each day to load; any other control stops it)
  function setPlaying(on) {
    state.playing = on;
    var b = document.getElementById("tl-play");
    b.textContent = on ? "❚❚" : "▶"; b.setAttribute("aria-pressed", on); b.setAttribute("aria-label", on ? "Pause" : "Play through the days");
    if (on) playStep();
  }
  function playStep() {
    if (!state.playing) return;
    var i = dayIndex(state.day);
    if (i >= days.length - 1) { setPlaying(false); return; }
    var next = days[i + 1].day;
    if (days[i + 2]) fetch("/data/gnss/" + days[i + 2].day + ".json");     // warm the cache for the step after
    document.getElementById("map-day").value = next;
    loadDay(next).then(function () { setTimeout(playStep, 900); }, function () { setPlaying(false); });
  }

  // ---------- click-for-history: the H3 resolution-3 area around a clicked hex, every day
  var histCache = {};
  function openHistory(h) {
    var r3 = h3.cellToParent(h, 3), r2 = h3.cellToParent(r3, 2);
    state.hist = { r3: r3, data: null };
    var sec = document.getElementById("hist");
    sec.hidden = false;
    document.getElementById("hist-sub").textContent = "Loading…";
    histImagery();
    document.getElementById("hist-chart").textContent = "";
    (histCache[r2] ? Promise.resolve(histCache[r2]) : fetch("/data/history/" + r2 + ".json").then(function (r) { return r.ok ? r.json() : null; }))
      .then(function (j) {
        histCache[r2] = j;
        if (!state.hist || state.hist.r3 !== r3) return;
        state.hist.data = j && j.areas[r3] ? { days: j.days, s: j.areas[r3] } : null;
        drawHistory();
      }).catch(function () { document.getElementById("hist-sub").textContent = "No history for this area in this build."; });
  }
  function histImagery() {                 // links to the providers' own imagery viewers for the area's centre and the day shown
    var hi = document.getElementById("hist-img");
    if (!hi || !window.NFImagery || !state.hist) return;
    var c = h3.cellToLatLng(state.hist.r3);
    hi.innerHTML = "Satellite imagery of this area (opens the provider's viewer): " + NFImagery.linksHtml(c[0], c[1], state.day, 8);
  }
  function drawHistory() {
    var hst = state.hist, box = document.getElementById("hist-chart"), sub = document.getElementById("hist-sub"), note = document.getElementById("hist-note");
    if (!hst) return;
    histImagery();
    if (!hst.data) { sub.textContent = "No history for this area in this build."; box.textContent = ""; note.textContent = ""; return; }
    var acc = emeasure() === "acc", s = hst.data.s, dd = hst.data.days, n = dd.length;
    var vals = dd.map(function (_, i) {
      var a = acc ? s.k[i] : s.a[i], b = acc ? s.kb[i] : s.b[i];
      return a >= (acc ? 10 : 20) ? 100 * b / a : null;
    });
    var have = vals.filter(function (v) { return v !== null; }), sorted = have.slice().sort(function (x, y) { return x - y; });
    var med = sorted.length ? sorted[Math.floor(sorted.length / 2)] : null, mx = sorted.length ? sorted[sorted.length - 1] : null;
    var evs = (s.ev && s.ev[acc ? "acc" : "jam"]) || [];
    var ci = dd.indexOf(state.day), cv = ci >= 0 ? vals[ci] : null;
    sub.textContent = "Around " + ll2(s.c[0], s.c[1]) + " (H3 area of about 12,000 km² containing the hex). " +
      (acc ? "Share of 10 m-capable aircraft-hexes below 10 m" : "Share of aircraft-hexes worse than 93 m (live)") + ", per day; days with too little traffic are gaps.";
    var peakDay = mx !== null ? dd[vals.indexOf(mx)] : null;
    note.textContent = (med !== null ? "Median " + med.toFixed(1) + "%; highest " + mx.toFixed(1) + "% on " + peakDay + ". " : "") +
      (cv !== null ? "On " + state.day + ": " + cv.toFixed(1) + "%. " : "") +
      (evs.length ? evs.length + " day" + (evs.length === 1 ? "" : "s") + " with an anomaly event over this region (marked above the line; darker = larger)." : "No anomaly events over this region.") +
      " Click a point to open that day.";
    histImagery();
    // chart: one series, 2px line, crosshair tooltip, event marks, the selected day
    box.textContent = "";
    var NS = "http://www.w3.org/2000/svg", W = Math.max(300, box.clientWidth), H = 190, m = { l: 38, r: 12, t: 16, b: 24 };
    var iw = W - m.l - m.r, ih = H - m.t - m.b, ymax = Math.max(10, Math.ceil((mx || 0) / 10) * 10);
    var X = function (i) { return m.l + (n === 1 ? iw / 2 : iw * i / (n - 1)); }, Y = function (v) { return m.t + ih * (1 - v / ymax); };
    function el(name, attrs, parent) { var e = document.createElementNS(NS, name); for (var k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; }
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H, role: "img", "aria-label": "Daily share for this area" });
    for (var k = 0; k <= 4; k++) {
      var gy = Y(ymax * k / 4);
      el("line", { x1: m.l, x2: W - m.r, y1: gy, y2: gy, class: "hgrid" }, svg);
      var t = el("text", { x: m.l - 6, y: gy + 4, "text-anchor": "end", class: "htext" }, svg); t.textContent = Math.round(ymax * k / 4) + "%";
    }
    [0, Math.floor((n - 1) / 2), n - 1].forEach(function (i, j) {
      if (n < 2 && j) return;
      var t = el("text", { x: X(i), y: H - 6, "text-anchor": j === 0 ? "start" : j === 2 ? "end" : "middle", class: "htext" }, svg); t.textContent = dd[i];
    });
    evs.forEach(function (e) { el("rect", { x: X(e[0]) - 1.5, y: 2, width: 3, height: 8, class: "hev l" + e[1] }, svg); });
    if (ci >= 0) el("line", { x1: X(ci), x2: X(ci), y1: m.t, y2: m.t + ih, class: "hcur" }, svg);
    var d = "", pen = false;
    vals.forEach(function (v, i) { if (v === null) { pen = false; return; } d += (pen ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1); pen = true; });
    el("path", { d: d, class: "hline" }, svg);
    var dot = el("circle", { r: 4, class: "hdot", visibility: "hidden" }, svg);
    var hit = el("rect", { x: m.l, y: m.t, width: iw, height: ih, fill: "transparent", tabindex: 0 }, svg);
    var tipEl = document.getElementById("hist-tip");
    if (!tipEl) { tipEl = document.createElement("div"); tipEl.id = "hist-tip"; tipEl.className = "tl-tip"; tipEl.hidden = true; box.parentNode.appendChild(tipEl); }
    function at(ev) { var r = svg.getBoundingClientRect(); return Math.max(0, Math.min(n - 1, Math.round((ev.clientX - r.left - m.l) / (iw * r.width / W) * (n - 1)))); }
    hit.addEventListener("mousemove", function (ev) {
      var i = at(ev), v = vals[i], a = acc ? s.k[i] : s.a[i];
      var e = evs.filter(function (x) { return x[0] === i; })[0];
      tipEl.textContent = dd[i] + " · " + (v === null ? "too little traffic" : v.toFixed(1) + "% of " + a + " aircraft-hexes") + (e ? " · anomaly event" : "");
      tipEl.hidden = false;
      var r = box.getBoundingClientRect(), p = box.parentNode.getBoundingClientRect();
      tipEl.style.left = Math.max(0, Math.min(ev.clientX - p.left + 10, p.width - tipEl.offsetWidth)) + "px";
      tipEl.style.top = (r.top - p.top - 4) + "px";
      if (v !== null) { dot.setAttribute("cx", X(i)); dot.setAttribute("cy", Y(v)); dot.setAttribute("visibility", "visible"); } else dot.setAttribute("visibility", "hidden");
    });
    hit.addEventListener("mouseleave", function () { tipEl.hidden = true; dot.setAttribute("visibility", "hidden"); });
    hit.addEventListener("click", function (ev) {
      var day = dd[at(ev)];
      if (dayIndex(day) >= 0 && day !== state.day) { document.getElementById("map-day").value = day; loadDay(day); }
    });
    box.appendChild(svg);
  }

  function refresh() { state.evFocus = null; layer.redraw(); renderLegend(); renderStats(); renderTable(); renderEvents(); renderTimeline(); writeHash(); }

  fetch("/data/borders.json").then(function (r) { return r.json(); }).then(function (j) {
    borders = j.lines.map(function (l) { var mm = mercArr(l[1]); return { cls: l[0], m: mm, mb: mercBox(mm) }; });
    layer.redraw();
  }).catch(function () { /* the map works without borders */ });
  fetch("/data/places.json").then(function (r) { return r.json(); }).then(function (j) {
    places = j.places; areas = j.areas; layer.redraw();
    var dl = document.getElementById("map-search-list"), seen = {};
    areas.concat(places).forEach(function (p) {
      if (seen[p[0]]) return; seen[p[0]] = 1;
      var o = document.createElement("option"); o.value = p[0]; dl.appendChild(o);
    });
  }).catch(function () { /* the map works without labels */ });

  ["spoof", "cygnss"].forEach(function (k) {
    fetch("/data/" + k + "/index.json").then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; })
      .then(function (j) { layerIndex[k] = (j && j.days) || []; if (state.day) loadLayers(state.day); });
  });
  Promise.all([fetch("/data/gnss/days.json").then(function (r) { return r.json(); }),
               fetch("/data/land.json").then(function (r) { return r.json(); })]).then(function (res) {
    days = res[0];
    res[1].features.forEach(function (f) {
      var polys = f.geometry.type === "MultiPolygon" ? f.geometry.coordinates : [f.geometry.coordinates];
      polys.forEach(function (poly) {
        var ring = poly[0], mm = mercArr(ring.map(function (p) { return [p[1], p[0]]; }));
        land.push({ m: mm, mb: mercBox(mm) });
      });
    });
    readColors();
    var sel = document.getElementById("map-day");
    var daily = days.filter(function (d) { return d.daily; }).reverse();        // newest first
    var tested = days.filter(function (d) { return !d.daily; });
    var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    var groups = [], seen = {};
    daily.forEach(function (d) {
      var m = d.day.slice(0, 7);
      if (!seen[m]) { seen[m] = []; groups.push([MONTHS[+m.slice(5, 7) - 1] + " " + m.slice(0, 4) + " · daily", seen[m]]); }
      seen[m].push(d);
    });
    groups.push(["Validated test days", tested]);
    groups.forEach(function (g) {
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
      if (hp.m === "chg") state.measure = "chg";
      var v = (hp.v || "").split(",").map(Number);
      state.view = v.length === 3 && v.every(function (x) { return isFinite(x); }) ? v : null;
      imagery.want = hp.img === "esri";
      state.spoofShow = hp.sp === "1"; state.cygShow = hp.cy === "1";
      return d;
    }
    var day = fromHash();
    window.addEventListener("hashchange", function () {
      if (location.hash === hashFor()) return;         // our own replaceState
      var d = fromHash(); renderLegend();
      setImagery(imagery.want);
      if (state.view) map.setView([state.view[0], state.view[1]], state.view[2], { animate: false });
      if (d !== state.day) loadDay(d); else refresh();
    });
    sel.addEventListener("change", function () { loadDay(sel.value); });
    document.querySelectorAll('input[name="measure"]').forEach(function (r) {
      r.addEventListener("change", function () {
        state.measure = r.value; document.getElementById("map-raw-wrap").hidden = state.measure !== "jam"; refresh(); if (state.hist) drawHistory();
      });
    });
    document.getElementById("map-raw").addEventListener("change", function (e) { state.raw = e.target.checked; refresh(); });
    document.getElementById("ev-show").addEventListener("change", function (e) { state.evShow = e.target.checked; layer.redraw(); });
    var sl = document.getElementById("tl-slider");
    sl.addEventListener("input", function () { stepTo(+sl.value, false); });
    sl.addEventListener("change", function () { stepTo(+sl.value, true); });
    document.getElementById("tl-prev").addEventListener("click", function () { stepTo(dayIndex(state.day) - 1, true); });
    document.getElementById("tl-next").addEventListener("click", function () { stepTo(dayIndex(state.day) + 1, true); });
    var tlResize;
    window.addEventListener("resize", function () { clearTimeout(tlResize); tlResize = setTimeout(renderTimeline, 150); });
    [["ev-anom-more", "anom"], ["ev-burst-more", "burst"]].forEach(function (p) {
      document.getElementById(p[0]).addEventListener("click", function () {
        state.evAll[p[1]] = !state.evAll[p[1]]; state.evFocus = null; renderEvents(); layer.redraw();
      });
    });
    if (state.view) map.setView([state.view[0], state.view[1]], state.view[2], { animate: false });
    else map.setView([35, 15], window.innerWidth < 700 ? 1.5 : 2.5);
    map.on("moveend", writeHash);
    ["borders", "places", "areas"].forEach(function (k) {
      var box = document.getElementById("lyr-" + k);
      box.checked = layersOn[k];
      box.addEventListener("change", function () {
        layersOn[k] = box.checked;
        try { localStorage.setItem("nf-map-layers", JSON.stringify(layersOn)); } catch (e) { /* this visit only */ }
        layer.redraw();
      });
    });
    // satellite imagery (Esri World Imagery, imagery.js): offered only where /api/imagery returns a key
    var imgBox = document.getElementById("lyr-imagery"), imgNote = document.getElementById("map-img-note");
    function setImagery(on) {
      on = !!(on && imagery.key);
      if (on === imagery.on) return;
      imagery.on = on; imgBox.checked = on;
      if (on) {
        imagery.layer = NFImagery.esriLayer(imagery.key, function () {
          imgNote.textContent = "Esri imagery isn't loading (the free monthly allowance may be used up).";
          imgNote.hidden = false;
        }).addTo(map);
        map.setMaxZoom(IMG_MAX_ZOOM);
      } else {
        if (imagery.layer) { map.removeLayer(imagery.layer); imagery.layer = null; }
        imgNote.hidden = true;
        map.setMaxZoom(BASE_MAX_ZOOM);
      }
      layer.redraw(); writeHash();
    }
    imgBox.addEventListener("change", function () { setImagery(imgBox.checked); });
    if (window.NFImagery) NFImagery.esriKey().then(function (k) {
      if (!k) return;
      imagery.key = k;
      document.getElementById("lyr-imagery-opt").hidden = false;
      if (imagery.want) {
        setImagery(true);
        if (state.view && state.view[2] > BASE_MAX_ZOOM) map.setView([state.view[0], state.view[1]], state.view[2], { animate: false });
      }
    });
    // on-map panel: a Leaflet control so clicks and scrolls inside it don't move the map
    var panel = document.getElementById("map-panel"), ptoggle = document.getElementById("mp-toggle");
    var pctl = L.control({ position: "topright" });
    pctl.onAdd = function () { L.DomEvent.disableClickPropagation(panel); L.DomEvent.disableScrollPropagation(panel); return panel; };
    pctl.addTo(map);
    function setPanel(open) { panel.classList.toggle("closed", !open); ptoggle.setAttribute("aria-expanded", open); }
    setPanel(window.innerWidth >= 700);
    ptoggle.addEventListener("click", function () { setPanel(panel.classList.contains("closed")); });
    document.getElementById("mp-prev").addEventListener("click", function () { setPlaying(false); stepTo(dayIndex(state.day) - 1, true); });
    document.getElementById("mp-next").addEventListener("click", function () { setPlaying(false); stepTo(dayIndex(state.day) + 1, true); });
    document.getElementById("tl-play").addEventListener("click", function () { setPlaying(!state.playing); });
    ["tl-prev", "tl-next", "tl-slider", "map-day"].forEach(function (id) {
      document.getElementById(id).addEventListener("pointerdown", function () { setPlaying(false); });
    });
    [["spoof", "spoof"], ["cyg", "cyg"]].forEach(function (k) {
      var box = document.getElementById("lyr-" + k[0]);
      if (!box) return;
      box.checked = !!state[k[0] + "Show"];
      box.addEventListener("change", function () {
        state[k[0] + "Show"] = box.checked;
        if (!box.checked) state[k[1]] = null;
        loadLayers(state.day); layer.redraw(); writeHash();
      });
    });
    var evBox = document.getElementById("lyr-events"), evBox2 = document.getElementById("ev-show");
    function setEvents(on) { state.evShow = on; evBox.checked = evBox2.checked = on; layer.redraw(); }
    evBox.addEventListener("change", function () { setEvents(evBox.checked); });
    evBox2.addEventListener("change", function () { setEvents(evBox2.checked); });
    document.getElementById("hist-close").addEventListener("click", function () { state.hist = null; document.getElementById("hist").hidden = true; });
    var search = document.getElementById("map-search");
    search.addEventListener("change", function () {
      var q = search.value.trim().toLowerCase(); if (!q) return;
      var a = areas.filter(function (x) { return x[0].toLowerCase() === q; })[0];
      if (a) { map.fitBounds([[a[1], a[3]], [a[2], a[4]]], { animate: false }); search.value = ""; return; }
      var p = places.filter(function (x) { return x[0].toLowerCase() === q; })[0] ||
              places.filter(function (x) { return x[0].toLowerCase().indexOf(q) === 0; })[0];
      if (p) { map.setView([p[1], p[2]], 6, { animate: false }); search.value = ""; }
    });
    var jump = document.getElementById("map-jump");
    jump.addEventListener("change", function () {
      var v = jump.value.split(",").map(Number);
      if (v.length === 3) map.setView([v[0], v[1]], v[2], { animate: false });   // instant: animations stall in hidden tabs
      jump.value = "";
    });
    layer.addTo(map); renderLegend();
    loadDay(day);
    renderTimeline();
    if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () { readColors(); refresh(); });
  });
})();
