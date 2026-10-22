/* Noise Floor charts: small SVG renderer for /data/charts.json and /data/trend.json (ODbL, derived from adsb.lol).
   Lines get a crosshair tooltip; bars get per-mark tooltips. Values also appear in each chart's table view. */
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";
  var DATA = null, TREND = null;     // TREND: null while loading, false when this build has no daily data

  function el(name, attrs, parent) {
    var e = document.createElementNS(NS, name);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function txt(parent, x, y, s, cls, anchor) {
    var t = el("text", { x: x, y: y, "text-anchor": anchor || "start" }, parent);
    if (cls) t.setAttribute("class", cls);
    t.textContent = s;
    return t;
  }
  function cssVar(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
  function niceMax(v) {
    if (!(v > 0)) return 1;
    var p = Math.pow(10, Math.floor(Math.log10(v))), m = v / p;
    return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p;
  }
  function parseHour(s) { // "2025-10-13T05Z"
    return new Date(Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10), +s.slice(11, 13)));
  }
  var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function utcLabel(d) { return d.getUTCDate() + " " + MON[d.getUTCMonth()] + " " + String(d.getUTCHours()).padStart(2, "0") + ":00 UTC"; }
  function central(d) {
    try { return d.toLocaleString("en-US", { timeZone: "America/Chicago", hour: "numeric", minute: "2-digit", timeZoneName: "short" }); }
    catch (e) { return ""; }
  }

  function tooltip(box) {
    var t = box.querySelector(".chart-tip");
    if (!t) { t = document.createElement("div"); t.className = "chart-tip"; t.hidden = true; box.appendChild(t); }
    return {
      show: function (x, y, title, rows) {
        t.textContent = "";
        var h = document.createElement("div"); h.className = "t"; h.textContent = title; t.appendChild(h);
        rows.forEach(function (r) {
          var row = document.createElement("div"); row.className = "r";
          if (r.color) { var i = document.createElement("i"); i.style.background = r.color; row.appendChild(i); }
          var b = document.createElement("b"); b.textContent = r.value; row.appendChild(b);
          var s = document.createElement("span"); s.textContent = r.label; row.appendChild(s);
          t.appendChild(row);
        });
        t.hidden = false;
        var w = box.clientWidth, tw = t.offsetWidth;
        t.style.left = Math.max(0, Math.min(x + 12, w - tw)) + "px";
        t.style.top = Math.max(0, y - t.offsetHeight - 10) + "px";
      },
      hide: function () { t.hidden = true; }
    };
  }

  // ---------- multi-series line chart over a shared x index
  function lineChart(box, o) {
    box.querySelectorAll("svg").forEach(function (s) { s.remove(); });
    var W = Math.max(300, box.clientWidth), H = o.height || 240, m = { l: 40, r: 14, t: 12, b: 26 };
    var iw = W - m.l - m.r, ih = H - m.t - m.b, n = o.x.length;
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H, role: "img", "aria-label": o.aria });
    var ymax = o.yMax || niceMax(Math.max.apply(null, o.series.map(function (s) { return Math.max.apply(null, s.values.filter(function (v) { return v !== null; })); })));
    var X = function (i) { return m.l + (n === 1 ? iw / 2 : iw * i / (n - 1)); }, Y = function (v) { return m.t + ih * (1 - v / ymax); };
    var g = el("g", { class: "grid" }, svg);
    for (var k = 0; k <= 4; k++) {
      var v = ymax * k / 4, y = Y(v);
      el("line", { x1: m.l, x2: W - m.r, y1: y, y2: y }, g);
      txt(svg, m.l - 6, y + 4, (Math.round(v * 10) / 10) + (o.unit || ""), null, "end");
    }
    (o.bands || []).forEach(function (b) {
      el("rect", { x: X(b.from), y: m.t, width: Math.max(1, X(b.to) - X(b.from)), height: ih, fill: cssVar("--band") }, svg);
      if (b.label) txt(svg, X(b.from) + 4, m.t + 12, b.label, "lbl");
    });
    (o.refs || []).forEach(function (r) {
      el("line", { x1: m.l, x2: W - m.r, y1: Y(r.y), y2: Y(r.y), class: "ref" }, svg);
      txt(svg, W - m.r, Y(r.y) - 4, r.label, "lbl", "end");
    });
    (o.xTicks || []).forEach(function (t) {
      el("line", { x1: X(t.i), x2: X(t.i), y1: m.t + ih, y2: m.t + ih + 4, class: "axis" }, svg);
      txt(svg, X(t.i), H - 8, t.label, null, t.anchor || "middle");
    });
    el("line", { x1: m.l, x2: W - m.r, y1: m.t + ih, y2: m.t + ih, class: "axis" }, svg);
    o.series.forEach(function (s) {
      var d = "", pen = false;
      s.values.forEach(function (v, i) {
        if (v === null || v === undefined) { pen = false; return; }
        d += (pen ? "L" : "M") + X(i).toFixed(1) + " " + Y(Math.min(v, ymax)).toFixed(1); pen = true;
      });
      el("path", { d: d, fill: "none", stroke: s.color, "stroke-width": s.width || 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
    });
    var xh = el("line", { class: "xhair", y1: m.t, y2: m.t + ih, x1: -10, x2: -10, visibility: "hidden" }, svg);
    var dots = o.series.map(function (s) { return el("circle", { r: 4, fill: s.color, stroke: cssVar("--surface-chart"), "stroke-width": 2, visibility: "hidden" }, svg); });
    var hit = el("rect", { x: m.l, y: m.t, width: iw, height: ih, fill: "transparent", tabindex: 0 }, svg);
    var tip = tooltip(box);
    function at(i) {
      i = Math.max(0, Math.min(n - 1, i));
      xh.setAttribute("x1", X(i)); xh.setAttribute("x2", X(i)); xh.setAttribute("visibility", "visible");
      var rows = o.series.map(function (s, j) {
        var v = s.values[i];
        if (v === null || v === undefined) { dots[j].setAttribute("visibility", "hidden"); return { color: s.color, value: "–", label: s.name }; }
        dots[j].setAttribute("cx", X(i)); dots[j].setAttribute("cy", Y(Math.min(v, ymax))); dots[j].setAttribute("visibility", "visible");
        return { color: s.color, value: (Math.round(v * 10) / 10) + (o.unit || ""), label: s.name };
      });
      tip.show(X(i), Math.min.apply(null, o.series.map(function (s) { var v = s.values[i]; return v === null || v === undefined ? m.t + ih : Y(Math.min(v, ymax)); })), o.xTitle(i), rows);
    }
    hit.addEventListener("pointermove", function (e) {
      var r = svg.getBoundingClientRect(); at(Math.round((e.clientX - r.left - m.l) / iw * (n - 1)));
    });
    hit.addEventListener("pointerleave", function () { tip.hide(); xh.setAttribute("visibility", "hidden"); dots.forEach(function (d) { d.setAttribute("visibility", "hidden"); }); });
    var cur = n - 1;
    hit.addEventListener("focus", function () { at(cur); });
    hit.addEventListener("keydown", function (e) {
      if (e.key === "ArrowRight") { cur = Math.min(n - 1, cur + 1); at(cur); e.preventDefault(); }
      if (e.key === "ArrowLeft") { cur = Math.max(0, cur - 1); at(cur); e.preventDefault(); }
    });
    hit.addEventListener("blur", function () { tip.hide(); xh.setAttribute("visibility", "hidden"); });
    box.insertBefore(svg, box.firstChild);
  }

  // ---------- thin columns (one series), optional shaded window
  function columnChart(box, o) {
    box.querySelectorAll("svg").forEach(function (s) { s.remove(); });
    var W = Math.max(300, box.clientWidth), H = o.height || 220, m = { l: 34, r: 10, t: 14, b: 26 };
    var iw = W - m.l - m.r, ih = H - m.t - m.b, n = o.values.length, step = iw / n, bw = Math.max(1, Math.min(24, step - 1));
    var ymax = niceMax(Math.max.apply(null, o.values)), Y = function (v) { return m.t + ih * (1 - v / ymax); };
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H, role: "img", "aria-label": o.aria });
    var g = el("g", { class: "grid" }, svg);
    for (var k = 0; k <= 4; k++) { var v = ymax * k / 4; el("line", { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v) }, g); txt(svg, m.l - 6, Y(v) + 4, String(Math.round(v)), null, "end"); }
    if (o.band) {
      el("rect", { x: m.l + o.band.from * step, y: m.t, width: (o.band.to - o.band.from) * step, height: ih, fill: cssVar("--band") }, svg);
      txt(svg, m.l + o.band.from * step + 4, m.t + 12, o.band.label, "lbl");
    }
    var tip = tooltip(box);
    o.values.forEach(function (v, i) {
      var x = m.l + i * step + (step - bw) / 2, h = ih * v / ymax;
      if (v > 0) el("rect", { x: x, y: Y(v), width: bw, height: h, rx: Math.min(2, bw / 2), fill: o.color }, svg);
      var hit = el("rect", { x: m.l + i * step, y: m.t, width: Math.max(step, 6), height: ih, fill: "transparent" }, svg);
      hit.addEventListener("pointermove", function () { tip.show(x, Y(v), o.label(i), [{ color: o.color, value: String(v), label: o.unitLabel }]); });
      hit.addEventListener("pointerleave", function () { tip.hide(); });
    });
    (o.xTicks || []).forEach(function (t) { txt(svg, m.l + t.i * step + step / 2, H - 8, t.label, null, "middle"); });
    el("line", { x1: m.l, x2: W - m.r, y1: m.t + ih, y2: m.t + ih, class: "axis" }, svg);
    box.insertBefore(svg, box.firstChild);
  }

  // ---------- horizontal bars with a reference value
  function barChart(box, o) {
    box.querySelectorAll("svg").forEach(function (s) { s.remove(); });
    var W = Math.max(300, box.clientWidth), row = 30, m = { l: 64, r: 56, t: 8, b: 24 }, n = o.rows.length;
    var H = m.t + m.b + n * row, iw = W - m.l - m.r;
    var xmax = niceMax(Math.max.apply(null, o.rows.map(function (r) { return r.v; }))), X = function (v) { return m.l + iw * v / xmax; };
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H, role: "img", "aria-label": o.aria });
    var g = el("g", { class: "grid" }, svg);
    for (var k = 0; k <= 4; k++) { var v = xmax * k / 4; el("line", { x1: X(v), x2: X(v), y1: m.t, y2: H - m.b }, g); txt(svg, X(v), H - 6, v + (o.unit || ""), null, "middle"); }
    var tip = tooltip(box);
    o.rows.forEach(function (r, i) {
      var y = m.t + i * row + (row - 18) / 2, w = Math.max(2, X(r.v) - m.l);
      txt(svg, m.l - 8, y + 13, r.label, "lbl", "end");
      var p = "M" + m.l + " " + y + "H" + (m.l + w - 4) + "Q" + (m.l + w) + " " + y + " " + (m.l + w) + " " + (y + 4) + "V" + (y + 14) +
              "Q" + (m.l + w) + " " + (y + 18) + " " + (m.l + w - 4) + " " + (y + 18) + "H" + m.l + "Z";
      el("path", { d: p, fill: o.color }, svg);
      txt(svg, m.l + w + 6, y + 13, r.text, "lbl");
      var hit = el("rect", { x: 0, y: m.t + i * row, width: W, height: row, fill: "transparent" }, svg);
      hit.addEventListener("pointermove", function () { tip.show(m.l + w, y, r.label, r.tip); });
      hit.addEventListener("pointerleave", function () { tip.hide(); });
    });
    if (o.ref !== undefined) {
      el("line", { x1: X(o.ref), x2: X(o.ref), y1: m.t - 4, y2: H - m.b, class: "ref" }, svg);
      txt(svg, X(o.ref) + 4, m.t + 6, o.refLabel, "lbl");
    }
    box.insertBefore(svg, box.firstChild);
  }

  // ---------- the charts
  function dayTicks(times) {
    var ticks = [];
    times.forEach(function (t, i) { if (t.slice(11, 13) === "00") ticks.push({ i: i, d: parseHour(t) }); });
    var every = Math.ceil(ticks.length / Math.max(2, Math.floor(document.documentElement.clientWidth / 110)));
    return ticks.filter(function (t, k) { return k % every === 0; }).map(function (t) { return { i: t.i, label: t.d.getUTCDate() + " " + MON[t.d.getUTCMonth()] }; });
  }
  function hourTitle(t) { var d = parseHour(t); return utcLabel(d) + " · " + central(d); }

  var DRAW = {
    egnos: function (box) {
      var e = DATA.egnos, times = e.map(function (r) { return r.t; });
      var bands = [], start = null;
      e.forEach(function (r, i) {
        var on = r.state === "outage";
        if (on && start === null) start = i;
        if ((!on || i === e.length - 1) && start !== null) { bands.push({ from: start, to: on ? i : i - 1 }); start = null; }
      });
      lineChart(box, {
        aria: "Hourly share of 10 m-capable aircraft below 10 m accuracy in the EGNOS area, 9 to 25 October 2025, with its baseline",
        x: times, unit: "%", yMax: 100, bands: bands, refs: [{ y: 60, label: "outage threshold 60%" }],
        series: [{ name: "EGNOS area", values: e.map(function (r) { return r.share; }), color: cssVar("--series-1") },
                 { name: "Baseline (median of earlier days)", values: e.map(function (r) { return r.base; }), color: cssVar("--series-base"), width: 1.5 }],
        xTicks: dayTicks(times), xTitle: function (i) { return hourTitle(times[i]); }
      });
    },
    storm10: function (box) { stormChart(box, "acc10", "acc10_base", "10 m-capable aircraft below 10 m"); },
    storm93: function (box) { stormChart(box, "gross", "gross_base", "aircraft worse than 93 m"); },
    bay: function (box) {
      var b = DATA.bay, m0 = b[0].m;
      columnChart(box, {
        aria: "Aircraft-hexes with a gross-bad GPS report per minute over the Bay Area and Central Valley, 22 September 2026, 17:30 to 20:45 UTC",
        values: b.map(function (r) { return r.aircraft; }), color: cssVar("--series-1"), unitLabel: "aircraft-hexes with a 93 m-or-worse report",
        band: { from: 18 * 60 + 30 - m0, to: 20 * 60 + 29 - m0, label: "NOTAM window per a public post (UNVERIFIED)" },
        label: function (i) { var d = new Date(Date.UTC(2026, 8, 22, Math.floor(b[i].m / 60), b[i].m % 60)); return b[i].t + " · " + central(d); },
        xTicks: b.map(function (r, i) { return { i: i, m: r.m }; }).filter(function (r) { return r.m % 30 === 0; }).map(function (r) { return { i: r.i, label: b[r.i].t.replace("Z", "") }; })
      });
    },
    types: function (box) {
      var t = DATA.types.rows;
      barChart(box, {
        aria: "Over-representation of aircraft types among aircraft still degraded after leaving interference, 9 to 25 October 2025",
        rows: t.map(function (r) {
          return { label: r.type, v: r.ratio, text: r.ratio + "×",
                   tip: [{ color: cssVar("--series-1"), value: r.ratio + "×", label: "over-representation" },
                         { value: r.pe_share + "%", label: "of post-exposure aircraft-days" },
                         { value: r.all_share + "%", label: "of all aircraft-days" }] };
        }), color: cssVar("--series-1"), unit: "×", ref: 1, refLabel: "1× = share of traffic"
      });
    }
  };
  function stormChart(box, key, base, name) {
    var s = DATA.storm, times = s.map(function (r) { return r.t; });
    lineChart(box, {
      aria: "Hourly share of " + name + " over the northern US and southern Canada, 11 to 12 November 2025, against quiet days", height: 200,
      x: times, unit: "%", yMax: key === "acc10" ? 100 : 10,
      bands: [{ from: 24, to: 30 }],
      series: [{ name: "11–12 Nov 2025", values: s.map(function (r) { return r[key]; }), color: cssVar("--series-1") },
               { name: "Quiet days (16 and 22 Oct)", values: s.map(function (r) { return r[base]; }), color: cssVar("--series-base"), width: 1.5 }],
      xTicks: times.map(function (t, i) { return { i: i, h: +t.slice(11, 13) }; }).filter(function (x) { return x.h % 6 === 0; })
                   .map(function (x) { return { i: x.i, label: (x.h === 0 ? times[x.i].slice(8, 10) + " Nov " : "") + String(x.h).padStart(2, "0") + "Z" }; }),
      xTitle: function (i) { return hourTitle(times[i]); }
    });
  }
  function hotspots(container) {
    var names = Object.keys(DATA.hotspots);
    container.textContent = "";
    var ymax = 60;
    names.forEach(function (name) {
      var cell = document.createElement("div"), h = document.createElement("h4"), box = document.createElement("div");
      h.textContent = name; box.className = "chart"; cell.appendChild(h); cell.appendChild(box); container.appendChild(cell);
      var rows = DATA.hotspots[name], times = rows.map(function (r) { return r.day; });
      lineChart(box, {
        aria: "Daily share of aircraft-hexes worse than 93 m, " + name, height: 150, x: times, unit: "%", yMax: ymax,
        series: [{ name: name, values: rows.map(function (r) { return r.share; }), color: cssVar("--series-1") }],
        xTicks: [{ i: 0, label: "9 Oct", anchor: "start" }, { i: times.length - 1, label: "25 Oct", anchor: "end" }],
        xTitle: function (i) { return times[i] + " · " + rows[i].aircraft_hexes.toLocaleString() + " aircraft-hexes"; }
      });
    });
  }

  // ---------- daily hotspot trend: one small multiple per named area, one shared scale
  function dayLabel(s, year) {
    var d = new Date(Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10)));
    return d.getUTCDate() + " " + MON[d.getUTCMonth()] + (year ? " " + d.getUTCFullYear() : "");
  }
  function boxLabel(b) {
    function lat(v) { return Math.abs(v).toFixed(1) + "°" + (v >= 0 ? "N" : "S"); }
    function lon(v) { return Math.abs(v).toFixed(1) + "°" + (v >= 0 ? "E" : "W"); }
    return lat(b[0]) + "–" + lat(b[1]) + ", " + lon(b[2]) + "–" + lon(b[3]);
  }
  // the scale choice is a per-viewer convenience; storage can be blocked, so fall back to the shared default
  var trendOwnState = null;
  function trendOwn() {
    if (trendOwnState === null) {
      try { trendOwnState = localStorage.getItem("nf-trend-scale") === "own"; } catch (e) { trendOwnState = false; }
    }
    return trendOwnState;
  }
  function setTrendOwn(v) {
    trendOwnState = v;
    try { localStorage.setItem("nf-trend-scale", v ? "own" : "shared"); } catch (e) { /* this visit only */ }
  }
  function trend() {
    var grid = document.getElementById("trend-grid"); if (!grid) return;
    var table = document.getElementById("trend-table");
    grid.textContent = ""; table.textContent = "";
    if (!TREND) {
      var p = document.createElement("p"); p.className = "small";
      p.textContent = TREND === false ? "No daily data in this build yet." : "Loading…"; grid.appendChild(p); return;
    }
    var days = TREND.days, names = Object.keys(TREND.regions), all = [];
    document.getElementById("trend-range").textContent = ", " + dayLabel(days[0], true) + " to " + dayLabel(days[days.length - 1], true);
    names.forEach(function (n) { TREND.regions[n].share.forEach(function (v) { if (v !== null) all.push(v); }); });
    // shared: one scale for all, rounded up to the next 10%; own: per panel, next 10% and never below 10%, so a quiet
    // control isn't blown up into noise that looks like a signal
    var own = trendOwn();
    var shared = Math.max(20, Math.ceil(Math.max.apply(null, all.concat([0])) / 10) * 10);
    function scaleFor(r) {
      if (!own) return shared;
      var vals = r.share.filter(function (v) { return v !== null; });
      return Math.max(10, Math.ceil(Math.max.apply(null, vals.concat([0])) / 10) * 10);
    }
    document.getElementById("trend-own").checked = own;
    document.getElementById("trend-scale-note").textContent = own
      ? "Each panel has its own scale (shown on its axis), so compare levels with the table, not the line heights."
      : "All panels share one scale, so levels compare directly.";
    var ticks = [{ i: 0, label: dayLabel(days[0]), anchor: "start" }];
    if (days.length > 60) {                          // long ranges: a middle date, with years on all three
      var mid = Math.floor((days.length - 1) / 2);
      ticks = [{ i: 0, label: dayLabel(days[0], true), anchor: "start" }, { i: mid, label: dayLabel(days[mid], true) }];
      ticks.push({ i: days.length - 1, label: dayLabel(days[days.length - 1], true), anchor: "end" });
    } else if (days.length > 1) ticks.push({ i: days.length - 1, label: dayLabel(days[days.length - 1]), anchor: "end" });
    names.forEach(function (name) {
      var r = TREND.regions[name], cell = document.createElement("div"), h = document.createElement("h4"), box = document.createElement("div");
      h.textContent = name;
      if (r.box) { var bx = document.createElement("span"); bx.className = "bx"; bx.textContent = boxLabel(r.box); h.appendChild(bx); }
      box.className = "chart"; cell.appendChild(h); cell.appendChild(box); grid.appendChild(cell);
      lineChart(box, {
        aria: "Daily share of aircraft-hexes worse than 93 m, " + name + (own ? ", own scale 0–" + scaleFor(r) + "%" : ""),
        height: 150, x: days, unit: "%", yMax: scaleFor(r),
        series: [{ name: name, values: r.share, color: cssVar("--series-1") }], xTicks: ticks,
        xTitle: function (i) { return dayLabel(days[i], true) + " · " + (r.aircraft_hexes[i] || 0).toLocaleString() + " aircraft-hexes"; }
      });
    });
    var thead = document.createElement("thead"), hr = document.createElement("tr");
    ["Day"].concat(names).forEach(function (s) { var th = document.createElement("th"); th.textContent = s; hr.appendChild(th); });
    thead.appendChild(hr); table.appendChild(thead);
    var tbody = document.createElement("tbody");
    days.slice().reverse().forEach(function (d) {
      var i = days.indexOf(d), tr = document.createElement("tr"), td = document.createElement("td");
      td.textContent = d; tr.appendChild(td);
      names.forEach(function (n) {
        var v = TREND.regions[n].share[i], c = document.createElement("td"); c.className = "num";
        c.textContent = v === null || v === undefined ? "–" : v.toFixed(1) + "%"; tr.appendChild(c);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
  }

  function drawAll() {
    document.querySelectorAll(".chart[data-chart]").forEach(function (box) {
      var f = DRAW[box.getAttribute("data-chart")]; if (f) f(box);
    });
    var hm = document.getElementById("hotspot-grid"); if (hm) hotspots(hm);
    trend();
  }
  trend();
  var ownBox = document.getElementById("trend-own");
  if (ownBox) ownBox.addEventListener("change", function () { setTrendOwn(ownBox.checked); trend(); });
  fetch("/data/trend.json").then(function (r) { return r.ok ? r.json() : false; }).catch(function () { return false; })
    .then(function (t) { TREND = t; trend(); });
  fetch("/data/charts.json").then(function (r) { return r.json(); }).then(function (j) {
    DATA = j; drawAll();
    var t; window.addEventListener("resize", function () { clearTimeout(t); t = setTimeout(drawAll, 150); });
    if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", drawAll);
  });
})();
