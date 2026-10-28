/* Noisefloor GEO globe (/geo): every object near GEO from /data/geo/globe.json (tools/geo_globe.py), placed with
   satellite.js (SGP4/SDP4, the same propagation the tracks use), observed tracks from /data/geo/tracks-<N>d.json and
   coastlines from /data/land.json (Natural Earth). Earth-fixed frame. Positions are good to tens of kilometres at GEO.
   Beams are hypothetical: a circular main lobe G = Gm - 3(psi/psi_half)^2 dB (the form ITU-R S.1528 gives after S.672),
   beamwidth about 70 lambda/D, projected from the satellite's position. Footprint files an analyst loads stay in their
   browser: nothing is uploaded. */
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import * as satellite from "satellite.js";

const $ = (id) => document.getElementById(id);
if ($("globe")) main();

function main() {
  "use strict";
  const RE = 6378.137, GEO_ALT = 35786, GEO_R = (RE + GEO_ALT) / RE, DEG = Math.PI / 180, SIDEREAL = 360.98564736629;
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const PAL = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9"], OTHER = "#8e97a3";
  const SPACE = "#0b0e12", OCEAN = "#111822", COAST = "#3a4656", GRID = "#1a222d", RING = "#2c3644", SEL = "#ffffff";
  const REGIONS = [["zone", "Protected zone"], ["graveyard", "Graveyard"], ["crossing", "Crossing the zone"], ["inclined", "Inclined"], ["below", "Below the zone"]];
  const TYPES = [["PAYLOAD", "Payload"], ["ROCKET BODY", "Rocket body"], ["DEBRIS", "Debris"], ["OTHER", "Other or unknown"]];
  const WHERE = { zone: "in the protected zone", graveyard: "in the graveyard above the zone", crossing: "on an orbit crossing the zone",
                  inclined: "on an inclined geosynchronous orbit", below: "below the zone" };
  const BANDS = [["uhf", "UHF 0.3 GHz", 0.3], ["l", "L band 1.5 GHz", 1.5], ["s", "S band 2.2 GHz", 2.2], ["c-d", "C down 4 GHz", 4], ["c-u", "C up 6 GHz", 6],
                 ["x-d", "X down 7.5 GHz", 7.5], ["x-u", "X up 8 GHz", 8], ["ku-d", "Ku down 12 GHz", 12], ["ku-u", "Ku up 14 GHz", 14],
                 ["ka-d", "Ka down 20 GHz", 20], ["ka-u", "Ka up 30 GHz", 30]];
  const beamwidth = (ghz, dia) => (70 * (0.299792458 / ghz)) / dia;      // degrees, -3 dB full width: about 70 lambda / D
  const typeKey = (t) => (t === "PAYLOAD" || t === "ROCKET BODY" || t === "DEBRIS" ? t : "OTHER");
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtN = (x) => Number(x).toLocaleString("en-US");
  const lonTxt = (x) => Math.abs(x).toFixed(2) + "°" + (x < 0 ? "W" : "E");
  const latTxt = (x) => Math.abs(x).toFixed(2) + "°" + (x < 0 ? "S" : "N");

  // ---------------------------------------------------------------- time words: UTC first, the viewer's zone beside it
  const TZ = window.TicTime ? window.TicTime.zone() : "UTC";
  const HC = window.TicTime && !window.TicTime.hour12() ? "h23" : "h12";
  let LT = null;
  try { LT = new Intl.DateTimeFormat("en-US", { timeZone: TZ, month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit", hourCycle: HC, timeZoneName: "short" }); } catch (e) { LT = null; }
  function utcTxt(ms, year) {
    const d = new Date(ms), p = (n) => String(n).padStart(2, "0");
    return d.getUTCDate() + " " + MON[d.getUTCMonth()] + (year ? " " + d.getUTCFullYear() : "") + ", " + p(d.getUTCHours()) + ":" + p(d.getUTCMinutes()) + " UTC";
  }
  function bothTxt(ms, year) {
    if (TZ === "UTC" || !LT) return utcTxt(ms, year);
    const x = {}, d = new Date(ms);
    LT.formatToParts(d).forEach((q) => { x[q.type] = q.value; });
    const day = +x.day + " " + MON[+x.month - 1], same = day === d.getUTCDate() + " " + MON[d.getUTCMonth()];
    return utcTxt(ms, year) + " (" + (same ? "" : day + ", ") + x.hour + ":" + x.minute + (x.dayPeriod ? " " + x.dayPeriod : "") + " " + x.timeZoneName + ")";
  }
  const epochMs = (s) => Date.parse(s.length > 19 ? s.slice(0, 19) + "Z" : s + "Z");

  // ---------------------------------------------------------------- state
  const S = { objs: [], byId: new Map(), sel: [], q: "", regions: new Set(REGIONS.map((r) => r[0])), types: new Set(TYPES.map((t) => t[0])),
              activeOnly: false, color: "region", trails: "sel", win: 7, fp: "", t: null, track: null, tracks: {}, board: null, owners: {},
              ownerColor: {}, strip: { x0: -180, x1: 180, y: "alt" }, beams: new Map(), aim: null, files: [] };
  function readHash() {
    if (!location.hash.startsWith("#g=")) return;
    const kv = {};
    decodeURIComponent(location.hash.slice(3)).split(";").forEach((p) => { const i = p.indexOf(":"); if (i > 0) kv[p.slice(0, i)] = p.slice(i + 1); });
    if (kv.s) S.sel = kv.s.split(",").map(Number).filter(Boolean);
    if (kv.w && ["1", "7", "30", "90"].includes(kv.w)) S.win = +kv.w;
    if (kv.tr && ["off", "sel", "all"].includes(kv.tr)) S.trails = kv.tr;
    if (kv.fp != null && ["", "0", "5", "10"].includes(kv.fp)) S.fp = kv.fp;
    if (kv.c && ["region", "type", "active", "owner"].includes(kv.c)) S.color = kv.c;
    if (kv.q) S.q = kv.q;
    if (kv.r) S.regions = new Set(kv.r.split(",").filter((r) => REGIONS.some((x) => x[0] === r)));
    if (kv.ty) S.types = new Set(kv.ty.split(",").map((t) => t.replace("_", " ")).filter((t) => TYPES.some((x) => x[0] === t)));
    if (kv.a === "1") S.activeOnly = true;
    if (kv.b) kv.b.split(",").forEach((x) => {                            // norad~lat~lon~beamwidth~band~dia~levels
      const p = x.split("~");
      if (p.length < 4 || !+p[0]) return;
      S.beams.set(+p[0], { lat: +p[1], lon: +p[2], bw: Math.min(20, Math.max(0.05, +p[3])), band: p[4] || "ku-d", dia: +p[5] || 2,
                           c6: (p[6] || "").includes("6"), c10: (p[6] || "").includes("10"), manual: true });
    });
  }
  function writeHash() {
    const parts = [];
    if (S.sel.length) parts.push("s:" + S.sel.join(","));
    if (S.win !== 7) parts.push("w:" + S.win);
    if (S.trails !== "sel") parts.push("tr:" + S.trails);
    if (S.fp !== "") parts.push("fp:" + S.fp);
    if (S.color !== "region") parts.push("c:" + S.color);
    if (S.q) parts.push("q:" + S.q.replace(/[;]/g, " "));
    if (S.regions.size !== REGIONS.length) parts.push("r:" + [...S.regions].join(","));
    if (S.types.size !== TYPES.length) parts.push("ty:" + [...S.types].map((t) => t.replace(" ", "_")).join(","));
    if (S.activeOnly) parts.push("a:1");
    if (S.beams.size) parts.push("b:" + [...S.beams].map(([id, b]) => [id, b.lat.toFixed(2), b.lon.toFixed(2), b.bw.toFixed(2), b.band, b.dia,
      (b.c6 ? "6" : "") + (b.c10 ? "10" : "")].join("~")).join(","));
    const h = parts.length ? "#g=" + encodeURIComponent(parts.join(";")) : "";
    if (h !== location.hash && (h || location.hash.startsWith("#g="))) history.replaceState(null, "", h || location.pathname + location.search);
  }

  // ---------------------------------------------------------------- scene
  const canvas = $("g-canvas"), view = $("g-view");
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true }); } catch (e) {
    $("g-status").textContent = "This browser can't draw the globe (WebGL is off or missing). The tables below hold the same data.";
    return;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(SPACE);
  const camera = new THREE.PerspectiveCamera(35, 1, 0.0005, 400);
  camera.position.set(4, 9, 21);
  const controls = new OrbitControls(camera, canvas);
  Object.assign(controls, { enableDamping: true, dampingFactor: 0.09, minDistance: 0.003, maxDistance: 60, rotateSpeed: 0.55, zoomSpeed: 1.1 });
  if ("zoomToCursor" in controls) controls.zoomToCursor = true;
  const sc = (x, y, z) => new THREE.Vector3(x, z, -y);                     // Earth-fixed (x to 0°E, y to 90°E, z north) -> scene (y up)
  const fromLLR = (lon, lat, r) => { const c = Math.cos(lat * DEG); return sc(r * c * Math.cos(lon * DEG), r * c * Math.sin(lon * DEG), r * Math.sin(lat * DEG)); };

  const earth = new THREE.Mesh(new THREE.SphereGeometry(0.998, 96, 64), new THREE.MeshBasicMaterial({ color: OCEAN }));
  scene.add(earth);
  function lineSet(pts, color, opacity) {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    return new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color, transparent: opacity < 1, opacity }));
  }
  (function graticule() {
    const pts = [], push = (a, b) => { pts.push(a.x, a.y, a.z, b.x, b.y, b.z); };
    for (let lat = -60; lat <= 60; lat += 30) for (let lon = -180; lon < 180; lon += 3) push(fromLLR(lon, lat, 1.0005), fromLLR(lon + 3, lat, 1.0005));
    for (let lon = -180; lon < 180; lon += 30) for (let lat = -90; lat < 90; lat += 3) push(fromLLR(lon, lat, 1.0005), fromLLR(lon, lat + 3, 1.0005));
    scene.add(lineSet(pts, GRID, 1));
    const ring = [];
    for (let lon = -180; lon < 180; lon += 1) { const a = fromLLR(lon, 0, GEO_R), b = fromLLR(lon + 1, 0, GEO_R); ring.push(a.x, a.y, a.z, b.x, b.y, b.z); }
    scene.add(lineSet(ring, RING, 0.9));
  })();
  fetch("/data/land.json").then((r) => (r.ok ? r.json() : null)).then((land) => {
    if (!land) return;
    const pts = [];
    land.features.forEach((f) => {
      const polys = f.geometry.type === "MultiPolygon" ? f.geometry.coordinates : [f.geometry.coordinates];
      polys.forEach((poly) => poly.forEach((ring) => {
        for (let k = 1; k < ring.length; k++) {
          const a = fromLLR(ring[k - 1][0], ring[k - 1][1], 1.0015), b = fromLLR(ring[k][0], ring[k][1], 1.0015);
          pts.push(a.x, a.y, a.z, b.x, b.y, b.z);
        }
      }));
    });
    scene.add(lineSet(pts, COAST, 1));
    dirty = true;
  }).catch(() => {});

  function dotTexture(ring) {                                            // round dots (and a ring for the selection)
    const c = document.createElement("canvas"); c.width = c.height = 64;
    const x = c.getContext("2d");
    x.beginPath(); x.arc(32, 32, ring ? 26 : 28, 0, 2 * Math.PI);
    if (ring) { x.lineWidth = 7; x.strokeStyle = "#fff"; x.stroke(); } else { x.fillStyle = "#fff"; x.fill(); }
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
  }
  const dotGeo = new THREE.BufferGeometry(), selGeo = new THREE.BufferGeometry();
  const dots = new THREE.Points(dotGeo, new THREE.PointsMaterial({ size: 6, sizeAttenuation: false, vertexColors: true, map: dotTexture(false), alphaTest: 0.4, transparent: true }));
  const selDots = new THREE.Points(selGeo, new THREE.PointsMaterial({ size: 15, sizeAttenuation: false, color: SEL, map: dotTexture(true), alphaTest: 0.3, transparent: true, depthTest: false }));
  selDots.renderOrder = 2;
  scene.add(dots, selDots);
  const trailGroup = new THREE.Group(), predGroup = new THREE.Group(), fpGroup = new THREE.Group(), beamGroup = new THREE.Group(), fileGroup = new THREE.Group();
  scene.add(trailGroup, predGroup, fpGroup, beamGroup, fileGroup);

  // ---------------------------------------------------------------- colours and filters
  const col = new THREE.Color(), bgCol = new THREE.Color(SPACE);
  function colorOf(o) {
    if (S.color === "region") return PAL[REGIONS.findIndex((r) => r[0] === o.region)] || OTHER;
    if (S.color === "type") return PAL[TYPES.findIndex((t) => t[0] === o.tk)] || OTHER;
    if (S.color === "active") return o.active ? PAL[0] : PAL[1];
    return S.ownerColor[o.owner] || OTHER;
  }
  const shown = (o) => S.regions.has(o.region) && S.types.has(o.tk) && (!S.activeOnly || o.active);
  let terms = [];
  const matches = (o) => !terms.length || terms.every((t) => o.key.indexOf(t) >= 0);

  // ---------------------------------------------------------------- positions
  function satrecOf(o) {
    try {
      return satellite.json2satrec({ OBJECT_NAME: o.name, OBJECT_ID: o.cospar, EPOCH: o.epoch, MEAN_MOTION: o.n, ECCENTRICITY: o.e, INCLINATION: o.i,
        RA_OF_ASC_NODE: o.raan, ARG_OF_PERICENTER: o.argp, MEAN_ANOMALY: o.M, EPHEMERIS_TYPE: 0, CLASSIFICATION_TYPE: "U", NORAD_CAT_ID: o.norad,
        ELEMENT_SET_NO: 999, REV_AT_EPOCH: 0, BSTAR: o.bstar || 0, MEAN_MOTION_DOT: 0, MEAN_MOTION_DDOT: 0 });
    } catch (e) { return null; }
  }
  function propagated(o, date, gmst) {                                    // Earth-fixed, Earth radii
    if (!o.sr) return null;
    try {
      const pv = satellite.propagate(o.sr, date);
      if (!pv || !pv.position) return null;
      const f = satellite.eciToEcf(pv.position, gmst);
      return [f.x / RE, f.y / RE, f.z / RE];
    } catch (e) { return null; }
  }
  function tracked(o, ms) {
    const T = S.track, tr = T && T.dec.get(o.norad);
    if (!tr) return null;
    const f = (ms - T.t0) / T.step - tr.start, k = Math.floor(f), n = tr.v.length / 3;
    if (f < 0 || k > n - 1) return null;
    const a = Math.min(k, n - 1), b = Math.min(k + 1, n - 1), u = f - k, v = tr.v;
    let dl = v[3 * b] - v[3 * a]; dl = ((dl + 540) % 360) - 180;
    const lon = v[3 * a] + dl * u, lat = v[3 * a + 1] + (v[3 * b + 1] - v[3 * a + 1]) * u, dalt = v[3 * a + 2] + (v[3 * b + 2] - v[3 * a + 2]) * u;
    const r = (RE + GEO_ALT + dalt) / RE, c = Math.cos(lat * DEG);
    return [r * c * Math.cos(lon * DEG), r * c * Math.sin(lon * DEG), r * Math.sin(lat * DEG)];
  }
  const geodetic = (p) => { const r = Math.hypot(p[0], p[1], p[2]); return { lon: Math.atan2(p[1], p[0]) / DEG, lat: Math.atan2(p[2], Math.hypot(p[0], p[1])) / DEG, dalt: r * RE - RE - GEO_ALT, r }; };
  function nowMs() { return S.t == null ? Date.now() : S.t; }
  function updatePositions() {
    const ms = nowMs(), date = new Date(ms), gmst = satellite.gstime(date), useTrack = S.track && ms <= S.track.end;
    S.objs.forEach((o) => { o.p = (useTrack ? tracked(o, ms) : null) || (useTrack && S.track.dec.has(o.norad) ? null : propagated(o, date, gmst)); });
    rebuildDots();
  }

  // ---------------------------------------------------------------- draw buffers
  let drawn = [];                                                         // draw index -> object
  function rebuildDots() {
    drawn = S.objs.filter((o) => o.p && shown(o));
    const pos = new Float32Array(drawn.length * 3), cols = new Float32Array(drawn.length * 3);
    drawn.forEach((o, k) => {
      const v = sc(o.p[0], o.p[1], o.p[2]);
      pos.set([v.x, v.y, v.z], 3 * k);
      col.set(colorOf(o));
      if (!matches(o)) col.lerp(bgCol, 0.72);
      cols.set([col.r, col.g, col.b], 3 * k);
    });
    dotGeo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    dotGeo.setAttribute("color", new THREE.BufferAttribute(cols, 3));
    dotGeo.computeBoundingSphere();
    const sel = S.sel.map((id) => S.byId.get(id)).filter((o) => o && o.p), sp = new Float32Array(sel.length * 3);
    sel.forEach((o, k) => { const v = sc(o.p[0], o.p[1], o.p[2]); sp.set([v.x, v.y, v.z], 3 * k); });
    selGeo.setAttribute("position", new THREE.BufferAttribute(sp, 3));
    selGeo.computeBoundingSphere();
    drawFootprints();
    drawBeams();
    legend();
    drawStrip();
    panelUpdate();
    dirty = true;
  }

  // ---------------------------------------------------------------- tracks, predictions, footprints
  function clearGroup(g) { while (g.children.length) { const c = g.children.pop(); c.geometry.dispose(); c.material.dispose(); } }
  function drawTrails() {
    clearGroup(trailGroup);
    if (S.trails === "off" || !S.track) { dirty = true; return; }
    const list = S.trails === "sel" ? S.sel.map((id) => S.byId.get(id)).filter(Boolean) : S.objs.filter(shown);
    const pts = [], cs = [];
    list.forEach((o) => {
      const tr = S.track.dec.get(o.norad);
      if (!tr) return;
      col.set(colorOf(o));
      if (S.trails === "all" && !matches(o)) col.lerp(bgCol, 0.72);
      const v = tr.v, n = v.length / 3;
      let prev = null;
      for (let k = 0; k < n; k++) {
        const r = (RE + GEO_ALT + v[3 * k + 2]) / RE, p = fromLLR(v[3 * k], v[3 * k + 1], r);
        if (prev) { pts.push(prev.x, prev.y, prev.z, p.x, p.y, p.z); cs.push(col.r, col.g, col.b, col.r, col.g, col.b); }
        prev = p;
      }
    });
    if (pts.length) {
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
      g.setAttribute("color", new THREE.Float32BufferAttribute(cs, 3));
      trailGroup.add(new THREE.LineSegments(g, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: S.trails === "all" ? 0.45 : 0.85 })));
    }
    dirty = true;
  }
  function drawPredictions() {                                            // the next 48 hours from the latest elements, dashed
    clearGroup(predGroup);
    const start = Date.now();
    S.sel.slice(0, 12).map((id) => S.byId.get(id)).filter((o) => o && o.sr).forEach((o) => {
      const pts = [];
      for (let m = 0; m <= 2880; m += 30) {
        const d = new Date(start + m * 60000), p = propagated(o, d, satellite.gstime(d));
        if (p) pts.push(sc(p[0], p[1], p[2]));
      }
      if (pts.length < 2) return;
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineDashedMaterial({ color: colorOf(o), dashSize: 0.012, gapSize: 0.01 }));
      line.computeLineDistances();
      predGroup.add(line);
    });
    dirty = true;
  }
  function drawFootprints() {                                             // where each selected satellite stands above the chosen elevation
    clearGroup(fpGroup);
    if (S.fp === "") return;
    const el = +S.fp * DEG;
    S.sel.slice(0, 12).map((id) => S.byId.get(id)).filter((o) => o && o.p).forEach((o) => {
      const g = geodetic(o.p), lam = Math.acos(Math.cos(el) / g.r) - el, f1 = g.lat * DEG, l1 = g.lon * DEG, pts = [];
      for (let k = 0; k <= 120; k++) {
        const th = (k / 120) * 2 * Math.PI, f2 = Math.asin(Math.sin(f1) * Math.cos(lam) + Math.cos(f1) * Math.sin(lam) * Math.cos(th));
        const l2 = l1 + Math.atan2(Math.sin(th) * Math.sin(lam) * Math.cos(f1), Math.cos(lam) - Math.sin(f1) * Math.sin(f2));
        pts.push(fromLLR(l2 / DEG, f2 / DEG, 1.004));
      }
      fpGroup.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: colorOf(o) })));
    });
  }

  // ---------------------------------------------------------------- hypothetical beams
  const v3 = { dot: (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2], add: (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]],
               sub: (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]], mul: (a, k) => [a[0] * k, a[1] * k, a[2] * k],
               cross: (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]] };
  v3.unit = (a) => v3.mul(a, 1 / Math.hypot(a[0], a[1], a[2]));
  const ecefLL = (lon, lat) => { const c = Math.cos(lat * DEG); return [c * Math.cos(lon * DEG), c * Math.sin(lon * DEG), Math.sin(lat * DEG)]; };
  const visibleFrom = (Sv, lon, lat) => v3.dot(ecefLL(lon, lat), Sv) > 1;   // the point is above the satellite's horizon
  function beamContour(Sv, B, psi) {                                      // where a cone of half-angle psi around the boresight meets the Earth
    const b = v3.unit(v3.sub(B, Sv)), u = v3.unit(v3.cross(b, Math.abs(b[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0])), w = v3.cross(b, u), ss = v3.dot(Sv, Sv) - 1;
    const runs = [];
    let run = [];
    for (let k = 0; k <= 240; k++) {
      const ph = (k / 240) * 2 * Math.PI, d = v3.add(v3.mul(b, Math.cos(psi)), v3.mul(v3.add(v3.mul(u, Math.cos(ph)), v3.mul(w, Math.sin(ph))), Math.sin(psi)));
      const sd = v3.dot(Sv, d), disc = sd * sd - ss;
      if (disc < 0) { if (run.length > 1) runs.push(run); run = []; continue; }   // past the Earth's edge: the contour breaks there
      run.push(v3.add(Sv, v3.mul(d, -sd - Math.sqrt(disc))));
    }
    if (run.length > 1) runs.push(run);
    return runs;
  }
  function drawBeams() {
    clearGroup(beamGroup);
    S.beams.forEach((bm, id) => {
      const o = S.byId.get(id);
      if (!o || !o.p || !S.sel.includes(id) || !visibleFrom(o.p, bm.lon, bm.lat)) return;
      const B = ecefLL(bm.lon, bm.lat), half = (bm.bw / 2) * DEG, c = colorOf(o);
      [[3, 1], [6, 0.7], [10, 0.45]].forEach(([X, op]) => {
        if ((X === 6 && !bm.c6) || (X === 10 && !bm.c10)) return;
        const pts = [];
        beamContour(o.p, B, half * Math.sqrt(X / 3)).forEach((run) => {
          for (let k = 1; k < run.length; k++) {
            const a = sc(...v3.mul(run[k - 1], 1.004)), b = sc(...v3.mul(run[k], 1.004));
            pts.push(a.x, a.y, a.z, b.x, b.y, b.z);
          }
        });
        if (pts.length) beamGroup.add(lineSet(pts, c, op));
      });
      const s = sc(...o.p), t = sc(...v3.mul(B, 1.004));                  // a faint line from the satellite to the aim point
      beamGroup.add(lineSet([s.x, s.y, s.z, t.x, t.y, t.z], c, 0.35));
    });
    dirty = true;
  }
  function newBeam(o) {
    const g = geodetic(o.p || [GEO_R, 0, 0]);
    return { lat: 0, lon: g.lon, band: "ku-d", dia: 2, bw: beamwidth(12, 2), c6: true, c10: false, manual: false };
  }
  function beamSize(o, bm) {                                              // the -3 dB width across the line of sight, at the aim point
    const B = ecefLL(bm.lon, bm.lat), range = Math.hypot(...v3.sub(B, o.p)) * RE;
    return 2 * range * Math.tan((bm.bw / 2) * DEG);
  }

  // ---------------------------------------------------------------- footprint files the analyst loads (never uploaded)
  function parseFootprint(name, text) {
    const lines = [];
    if (/^\s*</.test(text)) {                                             // KML: every <coordinates> block, as a line
      const doc = new DOMParser().parseFromString(text, "application/xml");
      [...doc.getElementsByTagName("coordinates")].forEach((c) => {
        const pts = c.textContent.trim().split(/\s+/).map((t) => t.split(",").map(Number)).filter((p) => p.length >= 2 && isFinite(p[0]) && isFinite(p[1]));
        if (pts.length > 1) lines.push(pts);
      });
    } else {                                                              // GeoJSON: lines and polygon rings
      const j = JSON.parse(text), geoms = [];
      const walk = (x) => { if (!x) return; if (x.type === "FeatureCollection") x.features.forEach(walk); else if (x.type === "Feature") walk(x.geometry); else if (x.type === "GeometryCollection") x.geometries.forEach(walk); else geoms.push(x); };
      walk(j);
      geoms.forEach((g) => {
        if (g.type === "LineString") lines.push(g.coordinates);
        else if (g.type === "MultiLineString" || g.type === "Polygon") g.coordinates.forEach((r) => lines.push(r));
        else if (g.type === "MultiPolygon") g.coordinates.forEach((p) => p.forEach((r) => lines.push(r)));
      });
    }
    return { name, lines };
  }
  function drawFiles() {
    clearGroup(fileGroup);
    S.files.forEach((f, k) => {
      const pts = [];
      f.lines.forEach((ln) => { for (let i = 1; i < ln.length; i++) { const a = fromLLR(ln[i - 1][0], ln[i - 1][1], 1.003), b = fromLLR(ln[i][0], ln[i][1], 1.003); pts.push(a.x, a.y, a.z, b.x, b.y, b.z); } });
      if (pts.length) fileGroup.add(lineSet(pts, k % 2 ? "#f2c94c" : "#e7e9ed", 0.95));
    });
    $("g-files").innerHTML = S.files.map((f, k) => '<span class="globe-file-tag">' + esc(f.name) + ' <button type="button" class="linkish" data-file="' + k + '" aria-label="Remove ' + esc(f.name) + '">×</button></span>').join(" ");
    dirty = true;
  }
  $("g-file").addEventListener("change", (e) => {
    [...e.target.files].forEach((file) => {
      const r = new FileReader();
      r.onload = () => {
        try {
          const f = parseFootprint(file.name, String(r.result));
          if (!f.lines.length) throw new Error("no lines");
          S.files.push(f); drawFiles(); $("g-filenote").textContent = "";
        } catch (err) { $("g-filenote").textContent = file.name + ": no lines or polygons found (KML and GeoJSON are read)."; }
      };
      r.readAsText(file);
    });
    e.target.value = "";
  });
  $("g-files").addEventListener("click", (e) => { const b = e.target.closest("button[data-file]"); if (b) { S.files.splice(+b.dataset.file, 1); drawFiles(); } });

  // ---------------------------------------------------------------- picking
  const tip = $("g-tip"), box = $("g-box"), labels = $("g-labels");
  function occluded(v) {                                                  // the Earth between the camera and the point
    const c = camera.position, d = v.clone().sub(c), a = d.dot(d), b = 2 * c.dot(d), cc = c.dot(c) - 1, disc = b * b - 4 * a * cc;
    if (disc < 0) return false;
    const s = (-b - Math.sqrt(disc)) / (2 * a);
    return s > 0 && s < 1;
  }
  function screenOf(o) {
    const v = sc(o.p[0], o.p[1], o.p[2]);
    if (occluded(v)) return null;
    const q = v.clone().project(camera);
    if (q.z > 1) return null;
    const r = canvas.getBoundingClientRect();
    return { x: (q.x + 1) / 2 * r.width, y: (1 - q.y) / 2 * r.height };
  }
  function nearest(x, y, px) {
    let best = null, bd = px * px;
    drawn.forEach((o) => { const s = screenOf(o); if (!s) return; const d = (s.x - x) ** 2 + (s.y - y) ** 2; if (d < bd) { bd = d; best = o; } });
    return best;
  }
  function select(list, add) {
    const ids = list.map((o) => o.norad);
    if (add) ids.forEach((id) => { const i = S.sel.indexOf(id); if (i >= 0 && list.length === 1) S.sel.splice(i, 1); else if (i < 0) S.sel.push(id); });
    else S.sel = ids;
    selectionChanged();
  }
  function selectionChanged() { S.aim = null; canvas.classList.remove("aiming"); rebuildDots(); drawPredictions(); if (S.trails === "sel") drawTrails(); writeHash(); }
  let down = null;
  canvas.addEventListener("pointerdown", (e) => {
    const r = canvas.getBoundingClientRect();
    down = { x: e.clientX - r.left, y: e.clientY - r.top, shift: e.shiftKey, moved: false };
    if (e.shiftKey) { controls.enabled = false; canvas.setPointerCapture(e.pointerId); }
  });
  canvas.addEventListener("pointermove", (e) => {
    const r = canvas.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    if (down) {
      if (Math.abs(x - down.x) + Math.abs(y - down.y) > 5) down.moved = true;
      if (down.shift && down.moved) {
        box.hidden = false;
        Object.assign(box.style, { left: Math.min(x, down.x) + "px", top: Math.min(y, down.y) + "px", width: Math.abs(x - down.x) + "px", height: Math.abs(y - down.y) + "px" });
      }
      return;
    }
    const o = e.pointerType === "mouse" ? nearest(x, y, 10) : null;
    if (o) { tip.hidden = false; tip.textContent = o.name + " · " + (o.owner || "?"); Object.assign(tip.style, { left: x + 12 + "px", top: y + 12 + "px" }); }
    else tip.hidden = true;
  });
  canvas.addEventListener("pointerup", (e) => {
    if (!down) return;
    const r = canvas.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    if (down.shift && down.moved) {
      const x0 = Math.min(x, down.x), x1 = Math.max(x, down.x), y0 = Math.min(y, down.y), y1 = Math.max(y, down.y);
      select(drawn.filter((o) => { const s = screenOf(o); return s && s.x >= x0 && s.x <= x1 && s.y >= y0 && s.y <= y1 && matches(o); }), true);
    } else if (!down.moved && S.aim != null) {
      const ray = new THREE.Raycaster(), hit = (ray.setFromCamera(new THREE.Vector2((x / r.width) * 2 - 1, 1 - (y / r.height) * 2), camera), ray.intersectObject(earth)[0]);
      const o = S.byId.get(S.aim), bm = S.beams.get(S.aim);
      if (hit && o && o.p && bm) {
        const p = hit.point, lat = Math.asin(p.y / p.length()) / DEG, lon = Math.atan2(-p.z, p.x) / DEG;
        if (visibleFrom(o.p, lon, lat)) { bm.lat = lat; bm.lon = lon; drawBeams(); writeHash(); panel(true); }
        else $("g-aimnote").textContent = "That point is beyond the satellite's horizon. Click a point it can see.";
      }
      if (!hit || (o && o.p && hit && visibleFrom(o.p, Math.atan2(-hit.point.z, hit.point.x) / DEG, Math.asin(hit.point.y / hit.point.length()) / DEG))) {
        S.aim = null; canvas.classList.remove("aiming");
      }
    } else if (!down.moved) {
      const o = nearest(x, y, 12);
      if (o) select([o], e.shiftKey || e.ctrlKey || e.metaKey);
      else if (!e.shiftKey) { S.sel = []; selectionChanged(); }
    }
    box.hidden = true; controls.enabled = true; down = null;
  });
  canvas.addEventListener("pointerleave", () => { tip.hidden = true; });
  let fly = null;
  function focus(o) {
    if (!o || !o.p) return;
    const target = sc(o.p[0], o.p[1], o.p[2]), dir = target.clone().normalize();
    fly = { t0: performance.now(), from: controls.target.clone(), to: target, cFrom: camera.position.clone(), cTo: target.clone().add(dir.multiplyScalar(0.15)).add(new THREE.Vector3(0, 0.01, 0)) };   // just outside it: the Earth sits behind, ready to aim at
  }
  function home() { fly = { t0: performance.now(), from: controls.target.clone(), to: new THREE.Vector3(), cFrom: camera.position.clone(), cTo: new THREE.Vector3(4, 9, 21) }; }

  // ---------------------------------------------------------------- render loop
  let dirty = true;
  function resize() {
    const w = view.clientWidth, h = view.clientHeight;
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); dirty = true; drawStrip();
  }
  window.addEventListener("resize", resize);
  controls.addEventListener("change", () => { dirty = true; });
  function placeLabels() {
    const html = [];
    S.sel.slice(0, 20).forEach((id) => {
      const o = S.byId.get(id); if (!o || !o.p) return;
      const s = screenOf(o); if (!s) return;
      html.push('<span class="globe-label" style="left:' + (s.x + 9) + "px;top:" + (s.y - 8) + 'px">' + esc(o.name) + "</span>");
    });
    labels.innerHTML = html.join("");
  }
  function frame(now) {
    if (fly) {
      const u = Math.min(1, (now - fly.t0) / 900), e = u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2;
      controls.target.lerpVectors(fly.from, fly.to, e); camera.position.lerpVectors(fly.cFrom, fly.cTo, e);
      if (u >= 1) fly = null;
      dirty = true;
    }
    if (controls.update()) dirty = true;
    if (dirty) { renderer.render(scene, camera); placeLabels(); dirty = false; }
    requestAnimationFrame(frame);
  }

  // ---------------------------------------------------------------- the belt, flat
  const strip = $("g-strip");
  function stripY(o) {
    const g = geodetic(o.p);
    return S.strip.y === "alt" ? { v: g.dalt, lo: -1500, hi: 1500 } : { v: g.lat, lo: -20, hi: 20 };
  }
  function drawStrip() {
    if (!strip) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2), w = strip.clientWidth, h = strip.clientHeight;
    if (!w || !h) return;
    if (strip.width !== Math.round(w * dpr)) { strip.width = Math.round(w * dpr); strip.height = Math.round(h * dpr); }
    const x = strip.getContext("2d");
    x.setTransform(dpr, 0, 0, dpr, 0, 0);
    x.fillStyle = SPACE; x.fillRect(0, 0, w, h);
    const { x0, x1 } = S.strip, pad = 18, X = (lon) => ((lon - x0) / (x1 - x0)) * w;
    const yr = S.strip.y === "alt" ? [-1500, 1500] : [-20, 20], Y = (v) => pad + (1 - (Math.max(yr[0], Math.min(yr[1], v)) - yr[0]) / (yr[1] - yr[0])) * (h - 2 * pad);
    if (S.strip.y === "alt") { x.fillStyle = "rgba(57,135,229,0.10)"; x.fillRect(0, Y(200), w, Y(-200) - Y(200)); }
    x.strokeStyle = RING; x.beginPath(); x.moveTo(0, Y(0)); x.lineTo(w, Y(0)); x.stroke();
    x.fillStyle = "#98a1ad"; x.font = "11px " + getComputedStyle(document.body).fontFamily;
    x.fillText(S.strip.y === "alt" ? "GEO" : "0°", 4, Y(0) - 3);
    if (S.strip.y === "alt") { x.fillText("+200 km", 4, Y(200) - 3); x.fillText("−200 km", 4, Y(-200) + 12); x.fillText("Graveyard ↑", 4, pad - 4); }
    const step = (x1 - x0) > 180 ? 30 : (x1 - x0) > 60 ? 10 : (x1 - x0) > 15 ? 2 : (x1 - x0) > 4 ? 0.5 : 0.1;
    for (let l = Math.ceil(x0 / step) * step; l <= x1; l += step) { x.fillText(lonTxt(+l.toFixed(2)).replace(".00", ""), X(l) + 2, h - 4); x.fillStyle = "#98a1ad"; }
    drawn.forEach((o) => {
      const g = geodetic(o.p); if (g.lon < x0 || g.lon > x1) return;
      col.set(colorOf(o)); if (!matches(o)) col.lerp(bgCol, 0.72);
      x.fillStyle = "#" + col.getHexString();
      x.beginPath(); x.arc(X(g.lon), Y(stripY(o).v), 2.4, 0, 2 * Math.PI); x.fill();
    });
    x.strokeStyle = SEL; x.lineWidth = 1.6; x.fillStyle = "#e7e9ed";
    S.sel.map((id) => S.byId.get(id)).filter((o) => o && o.p).forEach((o) => {
      const g = geodetic(o.p); if (g.lon < x0 || g.lon > x1) return;
      const px = X(g.lon), py = Y(stripY(o).v);
      x.beginPath(); x.arc(px, py, 5.5, 0, 2 * Math.PI); x.stroke(); x.fillText(o.name, px + 8, py - 6);
    });
  }
  if (strip) {
    let sd = null;
    const pos = (e) => { const r = strip.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top, w: r.width, h: r.height }; };
    const lonAt = (px, w) => S.strip.x0 + (px / w) * (S.strip.x1 - S.strip.x0);
    strip.addEventListener("wheel", (e) => {
      e.preventDefault();
      const p = pos(e), c = lonAt(p.x, p.w), k = e.deltaY > 0 ? 1.25 : 0.8, span = Math.min(360, Math.max(0.2, (S.strip.x1 - S.strip.x0) * k));
      S.strip.x0 = Math.max(-180, c - (p.x / p.w) * span); S.strip.x1 = Math.min(180, S.strip.x0 + span); S.strip.x0 = S.strip.x1 - span;
      drawStrip();
    }, { passive: false });
    strip.addEventListener("pointerdown", (e) => { const p = pos(e); sd = { ...p, x0: S.strip.x0, x1: S.strip.x1, shift: e.shiftKey, moved: false }; strip.setPointerCapture(e.pointerId); });
    strip.addEventListener("pointermove", (e) => {
      if (!sd) return;
      const p = pos(e);
      if (Math.abs(p.x - sd.x) + Math.abs(p.y - sd.y) > 4) sd.moved = true;
      if (!sd.shift && sd.moved) {
        const span = sd.x1 - sd.x0, d = ((p.x - sd.x) / p.w) * span;
        S.strip.x0 = Math.max(-180, Math.min(180 - span, sd.x0 - d)); S.strip.x1 = S.strip.x0 + span; drawStrip();
      }
    });
    strip.addEventListener("pointerup", (e) => {
      if (!sd) return;
      const p = pos(e), w = p.w, h = p.h, pad = 18;
      const yr = S.strip.y === "alt" ? [-1500, 1500] : [-20, 20], Y = (v) => pad + (1 - (Math.max(yr[0], Math.min(yr[1], v)) - yr[0]) / (yr[1] - yr[0])) * (h - 2 * pad);
      const X = (lon) => ((lon - S.strip.x0) / (S.strip.x1 - S.strip.x0)) * w;
      const at = (o) => { const g = geodetic(o.p); return { x: X(g.lon), y: Y(stripY(o).v) }; };
      if (sd.shift && sd.moved) {
        const x0 = Math.min(p.x, sd.x), x1 = Math.max(p.x, sd.x), y0 = Math.min(p.y, sd.y), y1 = Math.max(p.y, sd.y);
        select(drawn.filter((o) => { const s = at(o); return matches(o) && s.x >= x0 && s.x <= x1 && s.y >= y0 && s.y <= y1; }), true);
      } else if (!sd.moved) {
        let best = null, bd = 81;
        drawn.forEach((o) => { const s = at(o), d = (s.x - p.x) ** 2 + (s.y - p.y) ** 2; if (d < bd) { bd = d; best = o; } });
        if (best) { select([best], e.shiftKey || e.ctrlKey || e.metaKey); if (!e.shiftKey) focus(best); }
      }
      sd = null;
    });
    $("g-sreset").addEventListener("click", () => { S.strip.x0 = -180; S.strip.x1 = 180; drawStrip(); });
    $("g-sy").addEventListener("change", (e) => { S.strip.y = e.target.value; drawStrip(); });
  }

  // ---------------------------------------------------------------- legend, panel, search
  function legend() {
    let items;
    if (S.color === "region") items = REGIONS.map((r, k) => [PAL[k], r[1], drawn.filter((o) => o.region === r[0]).length]);
    else if (S.color === "type") items = TYPES.map((t, k) => [PAL[k], t[1], drawn.filter((o) => o.tk === t[0]).length]);
    else if (S.color === "active") items = [[PAL[0], "Active (CelesTrak)", drawn.filter((o) => o.active).length], [PAL[1], "Not listed as active", drawn.filter((o) => !o.active).length]];
    else items = Object.keys(S.ownerColor).map((k) => [S.ownerColor[k], S.owners[k] ? k + " · " + S.owners[k] : k, drawn.filter((o) => o.owner === k).length])
      .concat([[OTHER, "All other owners", drawn.filter((o) => !S.ownerColor[o.owner]).length]]);
    $("g-legend").innerHTML = items.map((i) => '<span><i style="background:' + i[0] + '"></i>' + esc(i[1]) + " " + fmtN(i[2]) + "</span>").join("");
  }
  const TYPE_WORD = { PAYLOAD: "Payload", "ROCKET BODY": "Rocket body", DEBRIS: "Debris", UNKNOWN: "Unknown", TBA: "Not yet identified" };
  function altitudes(o) {
    const a = Math.cbrt(398600.4418 / Math.pow((o.n * 2 * Math.PI) / 86400, 2));
    return [a * (1 - o.e) - RE - GEO_ALT, a * (1 + o.e) - RE - GEO_ALT];
  }
  const signed = (km) => (km >= 0 ? "+" : "−") + fmtN(Math.round(Math.abs(km))) + " km";
  function boardFor(o) {
    const b = S.board || {}, out = [];
    const bo = (b.objects || []).filter((x) => x.id === o.norad)[0];
    if (bo && bo["class"]) out.push(["Board class", bo["class"]]);
    const role = b.roles && b.roles[String(o.norad)];
    if (role) out.push(["Listed role", esc(role.role) + ": " + esc(role.basis) + ". " + role.sources.map((s) => '<a href="' + esc(s[1]) + '">' + esc(s[0]) + "</a>").join(", ")]);
    const close = (b.close_other_owner || []).filter((p) => p.a[0] === o.norad || p.b[0] === o.norad);
    if (close.length) out.push(["Close to another owner", close.map((p) => { const other = p.a[0] === o.norad ? p.b : p.a; return esc(other[1]) + " (" + esc(other[2]) + ") " + p.km + " km"; }).join("; ")]);
    const man = (b.manoeuvres || []).filter((m) => m.id === o.norad);
    if (man.length) out.push(["Orbit changes this week", man.map((m) => esc(m.kind) + ", elements of " + esc(m.between[0].slice(5, 10)) + " to " + esc(m.between[1].slice(5, 10))).join("; ")]);
    const ev = ((b.region || {}).events || []).filter((e) => e.norad === o.norad);
    if (ev.length) out.push(["Arrivals and departures", ev.map((e) => esc(e.day) + " " + esc(e.kind)).join("; ")]);
    return out;
  }
  let panelKey = "";
  function panelUpdate() {
    const key = S.sel.join(",") + "|" + [...S.beams.keys()].filter((id) => S.sel.includes(id)).join(",");
    if (key !== panelKey) { panel(true); return; }
    const sel = S.sel.map((id) => S.byId.get(id)).filter(Boolean);
    if (sel.length === 1) {
      const o = sel[0], g = o.p ? geodetic(o.p) : null, age = (nowMs() - epochMs(o.epoch)) / 86400000, pos = $("g-pos"), ag = $("g-age");
      if (pos) pos.textContent = g ? lonTxt(g.lon) + ", " + latTxt(g.lat) + ", " + signed(g.dalt) + " from GEO" : "not computed at this time";
      if (ag) ag.textContent = (age < 1 ? Math.round(age * 24) + " hours" : age.toFixed(1) + " days") + " before the time shown";
      const bs = $("g-bsize"), bm = S.beams.get(o.norad);
      if (bs && bm && o.p) bs.textContent = fmtN(Math.round(beamSize(o, bm)));
    } else {
      sel.forEach((o) => { const c = document.querySelector('#g-panel [data-lon="' + o.norad + '"]'); if (c) c.textContent = o.p ? lonTxt(geodetic(o.p).lon) : "–"; });
      const sp = $("g-sep");
      if (sp && sel.length === 2 && sel[0].p && sel[1].p) sp.textContent = fmtN(Math.round(Math.hypot(...v3.sub(sel[0].p, sel[1].p)) * RE)) + " km";
    }
  }
  function beamForm(o) {
    const bm = S.beams.get(o.norad);
    if (!bm) return '<p class="globe-tools"><button type="button" data-act="beam-on">Project a beam (hypothetical)</button></p>';
    const opt = BANDS.map((b) => '<option value="' + b[0] + '"' + (b[0] === bm.band ? " selected" : "") + ">" + esc(b[1]) + "</option>").join("");
    return '<div class="globe-beam"><h4>Hypothetical beam</h4>' +
      '<label>Band <select data-beam="band">' + opt + "</select></label>" +
      '<label>Antenna <input data-beam="dia" type="number" min="0.2" max="25" step="0.1" value="' + bm.dia + '"> m</label>' +
      '<label>Beamwidth <input data-beam="bw" type="number" min="0.05" max="20" step="0.05" value="' + bm.bw.toFixed(2) + '"> ° at −3 dB</label>' +
      '<p class="globe-tools"><button type="button" data-preset="17.4">Earth cover 17.4°</button><button type="button" data-preset="3">Regional 3°</button><button type="button" data-preset="0.6">Spot 0.6°</button></p>' +
      '<p class="globe-tools"><label><input type="checkbox" data-beam="c6"' + (bm.c6 ? " checked" : "") + '> −6 dB</label><label><input type="checkbox" data-beam="c10"' + (bm.c10 ? " checked" : "") + "> −10 dB</label></p>" +
      '<p class="globe-tools"><button type="button" data-act="aim">Click the Earth to aim</button><button type="button" data-act="beam-off">Remove beam</button></p>' +
      '<p class="small" id="g-aimnote">Aimed at ' + latTxt(bm.lat) + ", " + lonTxt(bm.lon) + '. About <span id="g-bsize">' + (o.p ? fmtN(Math.round(beamSize(o, bm))) : "–") +
      "</span> km across at −3 dB where it lands, more where it meets the Earth at a slant. A model of a circular beam, not this satellite's real coverage.</p></div>";
  }
  function panel(force) {
    if (!force) { panelUpdate(); return; }
    panelKey = S.sel.join(",") + "|" + [...S.beams.keys()].filter((id) => S.sel.includes(id)).join(",");
    const el = $("g-panel"), sel = S.sel.map((id) => S.byId.get(id)).filter(Boolean);
    if (!sel.length) {
      el.innerHTML = '<p class="small">Click a dot to see what it is. Shift-click adds to the selection; Shift-drag a box selects every dot inside it. Search finds names, catalogue numbers, owners and countries.</p>';
      return;
    }
    const tools = '<p class="globe-tools"><button type="button" data-act="csv">Download CSV</button> <button type="button" data-act="clear">Clear selection</button>' +
      (sel.length === 1 ? ' <button type="button" data-act="focus" data-id="' + sel[0].norad + '">Fly to it</button>' : ' <button type="button" data-act="home">Whole belt</button>') + "</p>";
    if (sel.length === 1) {
      const o = sel[0], g = o.p ? geodetic(o.p) : null, [pe, ap] = altitudes(o), age = (nowMs() - epochMs(o.epoch)) / 86400000;
      const rows = [
        ["Owner", esc(S.owners[o.owner] ? S.owners[o.owner] + " (" + o.owner + ")" : o.owner || "unknown")],
        ["Type", esc(TYPE_WORD[o.type] || o.type || "unknown") + (o.active ? ", listed as active" : "")],
        ["Where", esc(WHERE[o.region] || o.region)],
        ["Position", '<span id="g-pos">' + (g ? lonTxt(g.lon) + ", " + latTxt(g.lat) + ", " + signed(g.dalt) + " from GEO" : "not computed at this time") + "</span>"],
        ["Drift", (Math.abs(o.drift) < 0.0005 ? "none" : Math.abs(o.drift).toFixed(3) + "° a day " + (o.drift < 0 ? "west" : "east"))],
        ["Inclination", o.i.toFixed(3) + "°"], ["Eccentricity", o.e.toFixed(5)],
        ["Perigee, apogee", signed(pe) + ", " + signed(ap) + " from GEO"],
        ["Elements", esc(bothTxt(epochMs(o.epoch), true)) + ', <span id="g-age">' + (age < 1 ? Math.round(age * 24) + " hours" : age.toFixed(1) + " days") + " before the time shown</span>"],
        ["Launched", esc(o.launch || "unknown")], ["Radar size", esc(o.rcs || "not given")],
      ].concat(boardFor(o));
      el.innerHTML = "<h3>" + esc(o.name) + '</h3><p class="small">Catalogue ' + o.norad + (o.cospar ? " · " + esc(o.cospar) : "") +
        ' · <a href="https://celestrak.org/satcat/table-satcat.php?CATNR=' + o.norad + '">CelesTrak record</a></p><dl class="globe-dl">' +
        rows.map((r) => "<dt>" + r[0] + "</dt><dd>" + r[1] + "</dd>").join("") + "</dl>" + beamForm(o) + tools;
    } else {
      let sep = "";
      if (sel.length === 2 && sel[0].p && sel[1].p) {
        const d = Math.hypot(sel[0].p[0] - sel[1].p[0], sel[0].p[1] - sel[1].p[1], sel[0].p[2] - sel[1].p[2]) * RE;
        sep = '<p class="small">Separation at the time shown: <strong id="g-sep">' + fmtN(Math.round(d)) + " km</strong> (public elements: good to tens of km).</p>";
      }
      el.innerHTML = "<h3>" + sel.length + " selected</h3>" + sep + '<div class="tw"><table class="globe-list"><thead><tr><th>Object</th><th>Owner</th><th class="num">Longitude</th><th class="num">Drift °/day</th></tr></thead><tbody>' +
        sel.map((o) => { const g = o.p ? geodetic(o.p) : null; return '<tr data-id="' + o.norad + '"><td><button type="button" class="linkish" data-act="focus" data-id="' + o.norad + '">' + esc(o.name) + '</button></td><td>' + esc(o.owner || "") +
          '</td><td class="num" data-lon="' + o.norad + '">' + (g ? lonTxt(g.lon) : "–") + '</td><td class="num">' + (o.drift >= 0 ? "+" : "") + o.drift.toFixed(3) + "</td></tr>"; }).join("") + "</tbody></table></div>" + tools;
    }
  }
  function beamInput(e) {
    const f = e.target.dataset.beam, bm = S.beams.get(S.sel[0]); if (!f || !bm) return;
    if (f === "band" || f === "dia") {
      if (f === "band") bm.band = e.target.value; else bm.dia = Math.min(25, Math.max(0.2, +e.target.value || bm.dia));
      bm.bw = Math.min(20, Math.max(0.05, beamwidth(BANDS.find((b) => b[0] === bm.band)[2], bm.dia))); bm.manual = false;
      const i = document.querySelector('#g-panel [data-beam="bw"]'); if (i) i.value = bm.bw.toFixed(2);
    } else if (f === "bw") { const v = +e.target.value; if (v > 0) { bm.bw = Math.min(20, Math.max(0.05, v)); bm.manual = true; } }
    else bm[f] = e.target.checked;
    drawBeams(); panelUpdate(); writeHash();
  }
  $("g-panel").addEventListener("change", beamInput);
  $("g-panel").addEventListener("input", (e) => { if (e.target.dataset.beam === "bw" || e.target.dataset.beam === "dia") beamInput(e); });
  $("g-panel").addEventListener("click", (e) => {
    const pr = e.target.closest("button[data-preset]");
    if (pr) {
      const bm = S.beams.get(S.sel[0]); if (!bm) return;
      bm.bw = +pr.dataset.preset; bm.manual = true;
      const i = document.querySelector('#g-panel [data-beam="bw"]'); if (i) i.value = bm.bw.toFixed(2);
      drawBeams(); panelUpdate(); writeHash(); return;
    }
    const b = e.target.closest("button[data-act]"); if (!b) return;
    const act = b.dataset.act;
    if (act === "beam-on") { const o = S.byId.get(S.sel[0]); if (o) { S.beams.set(o.norad, newBeam(o)); drawBeams(); writeHash(); panel(true); } return; }
    if (act === "beam-off") { S.beams.delete(S.sel[0]); S.aim = null; canvas.classList.remove("aiming"); drawBeams(); writeHash(); panel(true); return; }
    if (act === "aim") { S.aim = S.sel[0]; canvas.classList.add("aiming"); $("g-aimnote").textContent = "Click a point on the Earth the satellite can see."; return; }
    if (act === "clear") { S.sel = []; selectionChanged(); }
    else if (act === "home") home();
    else if (act === "focus") focus(S.byId.get(+b.dataset.id));
    else if (act === "csv") csv();
  });
  function csv() {
    const head = ["norad", "name", "cospar", "owner", "type", "region", "active", "lon_deg", "lat_deg", "km_from_geo", "drift_deg_per_day", "inclination_deg", "eccentricity", "epoch_utc", "time_shown_utc"];
    const t = new Date(nowMs()).toISOString().slice(0, 16) + "Z";
    const rows = S.sel.map((id) => S.byId.get(id)).filter(Boolean).map((o) => {
      const g = o.p ? geodetic(o.p) : null;
      return [o.norad, o.name, o.cospar, o.owner, o.type, o.region, o.active ? 1 : 0, g ? g.lon.toFixed(3) : "", g ? g.lat.toFixed(3) : "", g ? Math.round(g.dalt) : "",
              o.drift.toFixed(4), o.i.toFixed(4), o.e.toFixed(6), o.epoch + "Z", t].map((v) => /[",]/.test(String(v)) ? '"' + String(v).replace(/"/g, '""') + '"' : v).join(",");
    });
    const blob = new Blob([head.join(",") + "\n" + rows.join("\n") + "\n" + '"' + S.cite + '"\n'], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "geo-selection-" + t.replace(/[:]/g, "") + ".csv"; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }
  const results = $("g-results");
  function searchChanged() {
    terms = S.q.toLowerCase().split(/\s+/).filter(Boolean);
    rebuildDots(); if (S.trails === "all") drawTrails(); writeHash();
    if (!terms.length) { results.hidden = true; return; }
    const hits = S.objs.filter(matches);
    results.innerHTML = '<li class="globe-res-head">' + fmtN(hits.length) + " match" + (hits.length === 1 ? "" : "es") +
      (hits.length ? ' <button type="button" class="linkish" data-all="1">Select all</button>' : "") + "</li>" +
      hits.slice(0, 40).map((o) => '<li><button type="button" class="linkish" data-id="' + o.norad + '">' + esc(o.name) + "</button> " + esc(o.owner || "") + " · " + esc(TYPE_WORD[o.type] || o.type || "") + "</li>").join("");
    results.hidden = false;
  }
  let qTimer = null;
  $("g-q").addEventListener("input", (e) => { clearTimeout(qTimer); qTimer = setTimeout(() => { S.q = e.target.value.trim(); searchChanged(); }, 150); });
  $("g-q").addEventListener("keydown", (e) => { if (e.key === "Escape") { e.target.value = ""; S.q = ""; searchChanged(); } });
  results.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.all) select(S.objs.filter((o) => matches(o) && o.p), false);
    else { const o = S.byId.get(+b.dataset.id); select([o], false); focus(o); }
    results.hidden = true;
  });
  document.addEventListener("click", (e) => { if (!e.target.closest(".globe-search")) results.hidden = true; });

  // ---------------------------------------------------------------- controls
  function filtersUI() {
    const box = (name, val, label, on) => '<label><input type="checkbox" data-f="' + name + '" value="' + esc(val) + '"' + (on ? " checked" : "") + "> " + esc(label) + "</label>";
    $("g-filters").innerHTML = '<fieldset><legend>Where</legend>' + REGIONS.map((r) => box("region", r[0], r[1], S.regions.has(r[0]))).join("") + "</fieldset>" +
      '<fieldset><legend>Type</legend>' + TYPES.map((t) => box("type", t[0], t[1], S.types.has(t[0]))).join("") + "</fieldset>" +
      '<fieldset><legend>Status</legend>' + box("active", "1", "Active only (CelesTrak's list)", S.activeOnly) + "</fieldset>";
  }
  $("g-filters").addEventListener("change", (e) => {
    const c = e.target; if (!c.dataset.f) return;
    if (c.dataset.f === "region") { if (c.checked) S.regions.add(c.value); else S.regions.delete(c.value); }
    else if (c.dataset.f === "type") { if (c.checked) S.types.add(c.value); else S.types.delete(c.value); }
    else S.activeOnly = c.checked;
    rebuildDots(); if (S.trails === "all") drawTrails(); writeHash();
  });
  $("g-color").addEventListener("change", (e) => { S.color = e.target.value; rebuildDots(); drawTrails(); drawPredictions(); writeHash(); });
  $("g-trails").addEventListener("change", (e) => { S.trails = e.target.value; drawTrails(); writeHash(); });
  $("g-fp").addEventListener("change", (e) => { S.fp = e.target.value; drawFootprints(); dirty = true; writeHash(); });
  $("g-win").addEventListener("change", (e) => { S.win = +e.target.value; loadWindow(); writeHash(); });

  // time: the recorded past from the tracks, the next 48 hours predicted from the latest elements
  const tIn = $("g-t");
  let playing = null, liveTimer = null;
  function timeLabel() {
    const ms = nowMs(), live = S.t == null, past = ms < Date.now() - 60000;
    $("g-tlabel").innerHTML = esc(bothTxt(ms, true)) + ' <span class="globe-tag">' + (live ? "now" : past ? "recorded" : "predicted") + "</span>";
  }
  function setTime(minutesFromNow) {
    S.t = minutesFromNow === 0 ? null : Date.now() + minutesFromNow * 60000;
    timeLabel(); updatePositions();
  }
  tIn.addEventListener("input", () => { stopPlay(); setTime(+tIn.value); });
  $("g-now").addEventListener("click", () => { stopPlay(); tIn.value = 0; setTime(0); });
  function stopPlay() { if (playing) { clearInterval(playing); playing = null; $("g-play").textContent = "Play"; } }
  $("g-play").addEventListener("click", () => {
    if (playing) { stopPlay(); return; }
    if (+tIn.value >= +tIn.max) tIn.value = tIn.min;
    $("g-play").textContent = "Pause";
    const span = +tIn.max - +tIn.min, stepMin = Math.max(+tIn.step, span / 300);
    playing = setInterval(() => {
      const v = Math.min(+tIn.max, +tIn.value + stepMin);
      tIn.value = v; setTime(v);
      if (v >= +tIn.max) stopPlay();
    }, 100);
  });
  function setSlider() {
    const step = S.win === 1 ? 15 : S.win === 7 ? 60 : S.win === 30 ? 240 : 720;
    tIn.min = -S.win * 1440; tIn.max = 2880; tIn.step = Math.min(step, 60);
    if (+tIn.value < +tIn.min) { tIn.value = 0; setTime(0); }
  }
  function loadWindow() {
    setSlider();
    const meta = S.globe.tracks[String(S.win)];
    if (!meta) { S.track = null; drawTrails(); updatePositions(); return; }
    const done = (T) => { S.track = T; drawTrails(); updatePositions(); };
    if (S.tracks[S.win]) { done(S.tracks[S.win]); return; }
    $("g-status").dataset.loading = "1";
    fetch("/data/geo/" + meta.file, { cache: "no-cache" }).then((r) => (r.ok ? r.json() : null)).then((j) => {
      if (!j) return;
      const T = { t0: Date.parse(j.start_utc.replace("Z", ":00Z")), step: j.step_min * 60000, dec: new Map() };
      T.end = T.t0 + (j.samples - 1) * T.step;
      Object.keys(j.tracks).forEach((k) => {
        const a = j.tracks[k], v = new Float32Array(a.length - 1);
        let lon = 0, lat = 0, dalt = 0;
        for (let i = 1; i < a.length; i += 3) {
          if (i === 1) { lon = a[1]; lat = a[2]; dalt = a[3]; } else { lon = ((lon + a[i] + 18000) % 36000 + 36000) % 36000 - 18000; lat += a[i + 1]; dalt += a[i + 2]; }
          v[i - 1] = lon / 100; v[i] = lat / 100; v[i + 1] = dalt;
        }
        T.dec.set(+k, { start: a[0], v });
      });
      S.tracks[S.win] = T; delete $("g-status").dataset.loading;
      done(T);
    }).catch(() => {});
  }

  // ---------------------------------------------------------------- load
  readHash();
  ["g-color", "g-trails", "g-fp", "g-win"].forEach((id) => { const v = { "g-color": S.color, "g-trails": S.trails, "g-fp": S.fp, "g-win": String(S.win) }[id]; $(id).value = v; });
  $("g-q").value = S.q;
  filtersUI();
  Promise.all([fetch("/data/geo/globe.json", { cache: "no-cache" }).then((r) => (r.ok ? r.json() : null)),
               fetch("/data/geo.json", { cache: "no-cache" }).then((r) => (r.ok ? r.json() : null)).catch(() => null)]).then(([g, board]) => {
    if (!g) { $("g-status").textContent = "The globe data could not be loaded. The tables below hold the board's own data."; return; }
    S.globe = g; S.board = board; S.owners = g.owners || {}; S.cite = g.source;
    const cols = g.cols, roleIds = new Set(Object.keys((board || {}).roles || {}).map(Number));
    S.objs = g.objects.map((row) => {
      const o = {}; cols.forEach((c, k) => { o[c] = row[k]; });
      o.tk = typeKey(o.type); o.drift = o.n * 360 - SIDEREAL; o.sr = satrecOf(o);
      const role = roleIds.has(o.norad) ? board.roles[String(o.norad)].role : "";
      o.key = [o.name, o.norad, o.cospar, o.owner, S.owners[o.owner], TYPE_WORD[o.type], o.region, role, o.active ? "active" : ""].join(" ").toLowerCase();
      return o;
    });
    S.objs.forEach((o) => S.byId.set(o.norad, o));
    const counts = {};
    S.objs.forEach((o) => { counts[o.owner] = (counts[o.owner] || 0) + 1; });
    Object.keys(counts).sort((a, b) => counts[b] - counts[a]).slice(0, PAL.length).forEach((k, i) => { S.ownerColor[k] = PAL[i]; });
    S.sel = S.sel.filter((id) => S.byId.has(id));
    $("g-status").innerHTML = "<strong>" + fmtN(S.objs.length) + "</strong> objects near GEO from Space-Track, elements fetched " + esc(bothTxt(Date.parse(g.elements_fetched_utc.replace("Z", ":00Z")), true)) +
      ". Positions are good to tens of kilometres. Tracks show what the published elements said at each time; the dashed line is the next 48 hours predicted from the latest elements.";
    resize(); timeLabel();
    terms = S.q.toLowerCase().split(/\s+/).filter(Boolean);
    loadWindow(); drawPredictions();
    if (terms.length) searchChanged();
    clearInterval(liveTimer);
    liveTimer = setInterval(() => { if (S.t == null) { timeLabel(); updatePositions(); } }, 30000);
    requestAnimationFrame(frame);
  });
}
