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
              ownerColor: {}, strip: { x0: -180, x1: 180, y: "alt" }, beams: new Map(), aim: null, files: [],
              place: null, pickPlace: false, sun: false, over: false, dish: 0.9, ghz: 12, open: {}, rel: null, near: null, look: null, sunwins: null,
              co: null, coHash: null, coData: null };
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
    if (kv.sun === "1") S.sun = true;
    if (kv.ov === "1") S.over = true;
    if (kv.co != null) S.coHash = kv.co.split(",").filter((x) => /^C[1-8]$/.test(x));
    if (kv.pl) {                                                          // lat~lon~name
      const p = kv.pl.split("~");
      if (p.length >= 2 && isFinite(+p[0]) && isFinite(+p[1]) && p[0] !== "" && p[1] !== "") S.place = { lat: Math.max(-90, Math.min(90, +p[0])), lon: ((+p[1] + 540) % 360) - 180, name: p.slice(2).join(" ") };
    }
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
    if (S.sun) parts.push("sun:1");
    if (S.over) parts.push("ov:1");
    if (S.co && S.coData) { const def = S.coData.rules.filter((r) => r.default_on).map((r) => r.id).join(","), cur = [...S.co].sort().join(","); if (cur !== def) parts.push("co:" + cur); }
    if (S.place) parts.push("pl:" + [S.place.lat.toFixed(3), S.place.lon.toFixed(3), (S.place.name || "").replace(/[;~,:]/g, " ")].join("~"));
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
  const sunGroup = new THREE.Group(), placeGroup = new THREE.Group(), overGroup = new THREE.Group(), coGroup = new THREE.Group();
  scene.add(trailGroup, predGroup, fpGroup, beamGroup, fileGroup, sunGroup, placeGroup, overGroup, coGroup);

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
    drawSun();
    drawPlace();
    drawOverlays();
    drawCallouts();
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


  // ---------------------------------------------------------------- G3: the sun, a place on the ground, board overlays
  const SUN_COL = "#f2c94c", SHADOW_COL = "#ff6b6b", PLACE_COL = "#e7e9ed", OMEGA = 7.2921159e-5;   // rad/s, the Earth's spin
  const OVER = [["close", "#ff6b6b", "Close to another owner"], ["man", "#c792ea", "Orbit change this week (not station-keeping)"], ["ev", "#56ccf2", "Arrival or departure"]];
  const ringTex = dotTexture(true), discTex = dotTexture(false);
  const ptsOf = (vs, color, size) => new THREE.Points(new THREE.BufferGeometry().setFromPoints(vs),
    new THREE.PointsMaterial({ size, sizeAttenuation: false, color, map: size > 12 ? ringTex : discTex, alphaTest: 0.3, transparent: true, depthTest: false }));
  const sunDir = (ms) => (window.NFSun ? window.NFSun.sunEcef(ms) : null);          // Earth-fixed unit vector to the sun
  function inShadow(p, s) {                                               // behind the Earth and within its cylinder of shadow
    const k = v3.dot(p, s);
    return k < 0 && Math.hypot(...v3.sub(p, v3.mul(s, k))) < 1;
  }
  function circleOn(lat, lon, lam, r) {                                   // a small circle of angular radius lam around (lat, lon)
    const f1 = lat * DEG, l1 = lon * DEG, pts = [];
    for (let k = 0; k <= 180; k++) {
      const th = (k / 180) * 2 * Math.PI, f2 = Math.asin(Math.sin(f1) * Math.cos(lam) + Math.cos(f1) * Math.sin(lam) * Math.cos(th));
      const l2 = l1 + Math.atan2(Math.sin(th) * Math.sin(lam) * Math.cos(f1), Math.cos(lam) - Math.sin(f1) * Math.sin(f2));
      pts.push(fromLLR(l2 / DEG, f2 / DEG, r));
    }
    return pts;
  }
  function drawSun() {
    clearGroup(sunGroup);
    const s = S.sun ? sunDir(nowMs()) : null;
    if (!s) { dirty = true; return; }
    const a = sc(...s), b = sc(...v3.mul(s, GEO_R * 1.35));
    sunGroup.add(lineSet([a.x, a.y, a.z, b.x, b.y, b.z], SUN_COL, 0.7));
    sunGroup.add(ptsOf([b], SUN_COL, 12));
    const sub = { lat: Math.asin(s[2]) / DEG, lon: Math.atan2(s[1], s[0]) / DEG };
    sunGroup.add(ptsOf([fromLLR(sub.lon, sub.lat, 1.003)], SUN_COL, 8));
    const term = circleOn(sub.lat, sub.lon, Math.PI / 2, 1.003);
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(term), new THREE.LineDashedMaterial({ color: SUN_COL, dashSize: 0.02, gapSize: 0.015, transparent: true, opacity: 0.8 }));
    line.computeLineDistances();
    sunGroup.add(line);
    const sh = [];                                                        // the arc of the belt inside the Earth's shadow
    for (let lon = -180; lon < 180; lon += 0.5) {
      const p = [GEO_R * Math.cos(lon * DEG), GEO_R * Math.sin(lon * DEG), 0], q = [GEO_R * Math.cos((lon + 0.5) * DEG), GEO_R * Math.sin((lon + 0.5) * DEG), 0];
      if (inShadow(p, s) && inShadow(q, s)) { const u = sc(...p), w = sc(...q); sh.push(u.x, u.y, u.z, w.x, w.y, w.z); }
    }
    if (sh.length) { const m = lineSet(sh, SHADOW_COL, 1); m.material.depthTest = false; sunGroup.add(m); }
    dirty = true;
  }
  function stationEcef(lat, lon) {                                        // km, WGS84 at sea level
    const F = 1 / 298.257223563, E2 = F * (2 - F), la = lat * DEG, lo = lon * DEG, n = RE / Math.sqrt(1 - E2 * Math.sin(la) ** 2);
    return [n * Math.cos(la) * Math.cos(lo), n * Math.cos(la) * Math.sin(lo), n * (1 - E2) * Math.sin(la)];
  }
  function lookFrom(pl, p) {                                              // bearing and elevation (degrees) and range (km) from a place
    const d = v3.sub(v3.mul(p, RE), stationEcef(pl.lat, pl.lon)), la = pl.lat * DEG, lo = pl.lon * DEG;
    const e = -Math.sin(lo) * d[0] + Math.cos(lo) * d[1];
    const n = -Math.sin(la) * Math.cos(lo) * d[0] - Math.sin(la) * Math.sin(lo) * d[1] + Math.cos(la) * d[2];
    const u = Math.cos(la) * Math.cos(lo) * d[0] + Math.cos(la) * Math.sin(lo) * d[1] + Math.sin(la) * d[2], r = Math.hypot(e, n, u);
    return { az: (Math.atan2(e, n) / DEG + 360) % 360, el: Math.asin(u / r) / DEG, range: r };
  }
  const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
  const bearingTxt = (az) => Math.round(az) % 360 + "° (" + COMPASS[Math.round(az / 22.5) % 16] + ")";
  const placeName = () => (S.place.name ? S.place.name : latTxt(S.place.lat) + ", " + lonTxt(S.place.lon));
  function drawPlace() {
    clearGroup(placeGroup);
    if (!S.place) { dirty = true; return; }
    const st = v3.mul(stationEcef(S.place.lat, S.place.lon), 1.002 / RE), at = sc(...st);
    placeGroup.add(ptsOf([at], PLACE_COL, 13));
    const pts = [];
    S.sel.slice(0, 12).map((id) => S.byId.get(id)).filter((o) => o && o.p && lookFrom(S.place, o.p).el > 0).forEach((o) => {
      const b = sc(...o.p); pts.push(at.x, at.y, at.z, b.x, b.y, b.z);
    });
    if (pts.length) placeGroup.add(lineSet(pts, PLACE_COL, 0.45));
    dirty = true;
  }
  function overlayItems() {                                               // the board's findings, by object
    const b = S.board || {}, out = { close: [], man: [], ev: [] };
    (b.close_other_owner || []).forEach((p) => out.close.push([p.a[0], p.b[0]]));
    (b.manoeuvres || []).forEach((m) => { if (m.kind && m.kind !== "station-keeping" && !out.man.includes(m.id)) out.man.push(m.id); });
    ((b.region || {}).events || []).forEach((e) => { if (!out.ev.includes(e.norad)) out.ev.push(e.norad); });
    return out;
  }
  function drawOverlays() {
    clearGroup(overGroup);
    if (!S.over || !S.board) { dirty = true; return; }
    const it = overlayItems(), at = (id) => { const o = S.byId.get(id); return o && o.p ? o.p : null; };
    const close = [], links = [];
    it.close.forEach(([a, b]) => {
      const A = at(a), B = at(b); if (!A || !B) return;
      close.push(sc(...v3.mul(v3.add(A, B), 0.5)));
      const u = sc(...A), w = sc(...B); links.push(u.x, u.y, u.z, w.x, w.y, w.z);
    });
    if (close.length) overGroup.add(ptsOf(close, OVER[0][1], 22));
    if (links.length) overGroup.add(lineSet(links, OVER[0][1], 0.9));
    const man = it.man.map(at).filter(Boolean).map((p) => sc(...p)), ev = it.ev.map(at).filter(Boolean).map((p) => sc(...p));
    if (man.length) overGroup.add(ptsOf(man, OVER[1][1], 17));
    if (ev.length) overGroup.add(ptsOf(ev, OVER[2][1], 13.5));
    dirty = true;
  }

  // ---------------------------------------------------------------- G3: positions over a window, relative motion, charts
  function posAt(o, ms) {                                                 // the same rule as updatePositions: recorded track, else SGP4
    const T = S.track;
    if (T && ms <= T.end) return tracked(o, ms) || (T.dec.has(o.norad) ? null : propagated(o, new Date(ms), satellite.gstime(new Date(ms))));
    const d = new Date(ms);
    return propagated(o, d, satellite.gstime(d));
  }
  function sampleTimes() {                                                // [ms, predicted]: the recorded window, then 48 hours ahead
    const now = Date.now(), T = S.track, out = [];
    if (T) for (let t = Math.max(T.t0, now - S.win * 86400000); t <= Math.min(T.end, now); t += T.step) out.push([t, false]);
    for (let m = 0; m <= 2880; m += 30) out.push([now + m * 60000, true]);
    return out;
  }
  function inertialVel(o, ms, p) {                                        // velocity in Earth-fixed axes plus the Earth's spin (radii per second)
    const a = posAt(o, ms - 600000), b = posAt(o, ms + 600000), ve = a && b ? v3.mul(v3.sub(b, a), 1 / 1200) : [0, 0, 0];
    return v3.add(ve, [-OMEGA * p[1], OMEGA * p[0], 0]);
  }
  function relative(A, B) {                                               // B as seen from A: separation and radial, along-track, cross-track
    return sampleTimes().map(([t, pred]) => {
      const pa = posAt(A, t), pb = posAt(B, t);
      if (!pa || !pb) return null;
      const d = v3.mul(v3.sub(pb, pa), RE), R = v3.unit(pa), C = v3.unit(v3.cross(pa, inertialVel(A, t, pa))), I = v3.cross(C, R);
      return { t, pred, sep: Math.hypot(...d), r: v3.dot(d, R), i: v3.dot(d, I), c: v3.dot(d, C) };
    }).filter(Boolean);
  }
  function neighbours(o, n) {                                             // the n objects that come closest over the window and the next 48 hours
    const times = sampleTimes(), mine = times.map(([t]) => posAt(o, t)), rec = times.filter((x) => !x[1]).length;
    const scored = [];
    S.objs.forEach((x) => {
      if (x === o || !x.p) return;
      let min = x.p && o.p ? Math.hypot(...v3.sub(x.p, o.p)) * RE : Infinity;
      for (let k = 0; k < rec; k++) { if (!mine[k]) continue; const q = posAt(x, times[k][0]); if (q) min = Math.min(min, Math.hypot(...v3.sub(q, mine[k])) * RE); }
      scored.push([min, x]);
    });
    scored.sort((a, b) => a[0] - b[0]);
    return scored.slice(0, 15).map(([, x]) => {                           // the 15 nearest so far, then their predicted part too
      const pts = [];
      times.forEach(([t, pred], k) => { const q = posAt(x, t); if (q && mine[k]) pts.push([t, Math.hypot(...v3.sub(q, mine[k])) * RE, pred]); });
      return { o: x, pts, min: pts.reduce((m, p) => (p[1] < m[1] ? p : m), [0, Infinity]) };
    }).sort((a, b) => a.min[1] - b.min[1]).slice(0, n);
  }
  function cssVar(name, fb) { const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim(); return v || fb; }
  function niceStep(x) { const p = Math.pow(10, Math.floor(Math.log10(x))), f = x / p; return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p; }
  function lineChart(cv, cfg) {                                           // one km axis; recorded solid, predicted dashed and shaded
    cv._cfg = cfg;
    const dpr = Math.min(window.devicePixelRatio || 1, 2), w = cv.clientWidth, h = cv.clientHeight;
    if (!w || !h) return;
    if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    const x = cv.getContext("2d");
    x.setTransform(dpr, 0, 0, dpr, 0, 0); x.clearRect(0, 0, w, h);
    const mut = cssVar("--ink-3", "#6b7480"), grid = cssVar("--grid", "#e6e9ee"), fg = cssVar("--fg", "#141a23");
    x.font = "11px " + getComputedStyle(document.body).fontFamily;
    const L = 44, R = 8, T = 6, B = 18, pw = w - L - R, ph = h - T - B;
    let lo = Infinity, hi = -Infinity;
    cfg.series.forEach((s) => s.pts.forEach((p) => { lo = Math.min(lo, p[1]); hi = Math.max(hi, p[1]); }));
    if (!isFinite(lo)) { x.fillStyle = mut; x.fillText("No positions in this window", L, T + 14); return; }
    if (cfg.cap) hi = Math.min(hi, cfg.cap);
    const m = cfg.sym ? Math.max(Math.abs(lo), Math.abs(hi), 1) : Math.max(hi, 1), step = niceStep(m / (cfg.sym ? 2 : 4));
    hi = Math.ceil(m / step) * step; lo = cfg.sym ? -hi : 0;
    const X = (t) => L + ((t - cfg.t0) / (cfg.t1 - cfg.t0)) * pw, Y = (v) => T + (1 - (Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo)) * ph;
    x.fillStyle = cssVar("--wash", "rgba(42,111,203,0.10)"); x.fillRect(X(cfg.now), T, X(cfg.t1) - X(cfg.now), ph);
    x.strokeStyle = grid; x.lineWidth = 1; x.fillStyle = mut; x.textAlign = "right";
    for (let v = lo; v <= hi + step / 2; v += step) { x.beginPath(); x.moveTo(L, Math.round(Y(v)) + 0.5); x.lineTo(w - R, Math.round(Y(v)) + 0.5); x.stroke(); x.fillText(fmtN(Math.round(v)), L - 5, Y(v) + 4); }
    const days = (cfg.t1 - cfg.t0) / 86400000, dstep = days > 60 ? 15 : days > 20 ? 7 : days > 6 ? 2 : 1;
    x.textAlign = "center";
    for (let t = Math.ceil(cfg.t0 / 86400000) * 86400000; t <= cfg.t1; t += dstep * 86400000) {
      const d = new Date(t); if (X(t) > L + 14 && X(t) < w - R - 14) x.fillText(d.getUTCDate() + " " + MON[d.getUTCMonth()], X(t), h - 4);
    }
    cfg.series.forEach((s) => {
      x.strokeStyle = s.color; x.lineWidth = 2;
      [false, true].forEach((pred) => {
        x.setLineDash(pred ? [5, 3] : []); x.beginPath();
        let on = false, last = 0;
        s.pts.forEach((p) => {
          if (p[2] !== pred || (cfg.cap && p[1] > cfg.cap)) { on = false; return; }   // above the cap: a break, not a flat line
          const px = X(p[0]), py = Y(p[1]);
          if (on && p[0] - last <= cfg.gap) x.lineTo(px, py); else x.moveTo(px, py);
          on = true; last = p[0];
        });
        x.stroke();
      });
      x.setLineDash([]);
    });
    const tm = nowMs();
    if (tm >= cfg.t0 && tm <= cfg.t1) { x.strokeStyle = fg; x.globalAlpha = 0.55; x.beginPath(); x.moveTo(Math.round(X(tm)) + 0.5, T); x.lineTo(Math.round(X(tm)) + 0.5, T + ph); x.stroke(); x.globalAlpha = 1; }
    if (cfg.hover != null) { x.strokeStyle = mut; x.setLineDash([2, 2]); x.beginPath(); x.moveTo(Math.round(X(cfg.hover)) + 0.5, T); x.lineTo(Math.round(X(cfg.hover)) + 0.5, T + ph); x.stroke(); x.setLineDash([]); }
    cfg.X = X; cfg.L = L; cfg.pw = pw;
  }
  function chartHover(e) {                                                // the readout under a chart follows the pointer
    const cv = e.target.closest("canvas.globe-chart"); if (!cv || !cv._cfg) return;
    const cfg = cv._cfg, r = cv.getBoundingClientRect(), t = cfg.t0 + ((e.clientX - r.left - cfg.L) / cfg.pw) * (cfg.t1 - cfg.t0);
    if (t < cfg.t0 || t > cfg.t1) return;
    cfg.hover = t; lineChart(cv, cfg);
    const vals = cfg.series.map((s) => {
      let best = null; s.pts.forEach((p) => { if (!best || Math.abs(p[0] - t) < Math.abs(best[0] - t)) best = p; });
      return best && Math.abs(best[0] - t) <= cfg.gap ? [s, best] : null;
    }).filter(Boolean);
    const out = cv.parentElement.querySelector(".globe-read");
    if (out && vals.length) out.textContent = utcTxt(vals[0][1][0]) + (vals[0][1][2] ? " (predicted): " : " (recorded): ") +
      vals.map(([s, p]) => s.name + " " + fmtN(Math.round(p[1])) + " km").join(", ");
  }
  function chartLeave(e) { const cv = e.target.closest("canvas.globe-chart"); if (cv && cv._cfg) { cv._cfg.hover = null; lineChart(cv, cv._cfg); } }
  function chartFrame(series) {
    const now = Date.now(), all = series.flatMap((s) => s.pts.map((p) => p[0]));
    return { t0: Math.min(...all, now), t1: Math.max(...all, now + 1), now, gap: Math.max(S.track ? S.track.step : 0, 1800000) * 2.5 };
  }
  function relSection(A, B) {
    const rel = relative(A, B);
    if (!rel.length) return '<p class="small">No common positions for these two in this window.</p>';
    const closest = rel.reduce((m, p) => (p.sep < m.sep ? p : m), rel[0]);
    S.rel = { A, B, rel };
    return '<h4 class="globe-h4">Relative motion</h4><p class="small">' + esc(B.name) + " as seen from " + esc(A.name) + ". Closest in the window: <strong>" +
      fmtN(Math.round(closest.sep)) + " km</strong>, " + esc(bothTxt(closest.t, true)) + (closest.pred ? " (predicted)" : " (recorded)") + ".</p>" +
      '<div class="globe-chartbox"><canvas class="globe-chart" data-chart="sep" aria-label="Separation over time"></canvas><p class="small globe-read">Separation, km. Point at the chart to read it.</p></div>' +
      '<div class="globe-chartbox"><canvas class="globe-chart" data-chart="ric" aria-label="Radial, along-track and cross-track offsets over time"></canvas>' +
      '<p class="small globe-key"><i style="background:' + cssVar("--series-1", PAL[0]) + '"></i>Radial (up) <i style="background:' + cssVar("--series-2", PAL[1]) + '"></i>Along-track (ahead) <i style="background:' + PAL[2] + '"></i>Cross-track</p>' +
      '<p class="small globe-read">Offsets, km. Point at the chart to read it.</p></div>' +
      '<p class="small">Solid: recorded elements; dashed and shaded: the next 48 hours predicted from the latest elements. Public elements are good to tens of kilometres, so offsets under about 50 km are within the error.</p>' +
      '<p class="globe-tools"><button type="button" data-act="csv-rel">Download relative motion (CSV)</button></p>';
  }
  function drawRelCharts() {
    if (!S.rel) return;
    const rel = S.rel.rel, pts = (k) => rel.map((p) => [p.t, p[k], p.pred]);
    const sep = [{ name: "Separation", color: cssVar("--series-1", PAL[0]), pts: pts("sep") }];
    const ric = [{ name: "Radial", color: cssVar("--series-1", PAL[0]), pts: pts("r") }, { name: "Along-track", color: cssVar("--series-2", PAL[1]), pts: pts("i") },
                 { name: "Cross-track", color: PAL[2], pts: pts("c") }];
    const cs = document.querySelector('#g-panel canvas[data-chart="sep"]'), cr = document.querySelector('#g-panel canvas[data-chart="ric"]');
    if (cs) lineChart(cs, { ...chartFrame(sep), series: sep });
    if (cr) lineChart(cr, { ...chartFrame(ric), series: ric, sym: true });
  }
  function nearSection(o) {
    const box = $("g-near"); if (!box) return;
    const near = neighbours(o, 5);
    S.near = { o, near };
    if (!near.length) { box.innerHTML = '<p class="small">No other objects with positions in this window.</p>'; return; }
    const series = near.map((nb, k) => ({ name: nb.o.name, color: PAL[k], pts: nb.pts }));
    box.innerHTML = '<div class="globe-chartbox"><canvas class="globe-chart" data-chart="near" aria-label="Separation from the closest objects over time"></canvas><p class="small globe-read">Separation, km, up to 1,000 km. Point at the chart to read it.</p></div>' +
      '<ol class="globe-near">' + near.map((nb, k) => '<li><i style="background:' + PAL[k] + '"></i><button type="button" class="linkish" data-act="add" data-id="' + nb.o.norad + '">' + esc(nb.o.name) + "</button> " +
        esc(nb.o.owner || "?") + " · closest " + fmtN(Math.round(nb.min[1])) + " km, " + esc(utcTxt(nb.min[0])) + (nb.min[2] ? " (predicted)" : "") + "</li>").join("") + "</ol>" +
      '<p class="small">Any owner, any type, including debris. Solid: recorded; dashed: predicted. Click a name to add it to the selection.</p>' +
      '<p class="globe-tools"><button type="button" data-act="csv-near">Download (CSV)</button></p>';
    const cv = box.querySelector("canvas");
    lineChart(cv, { ...chartFrame(series), series, cap: 1000 });
  }
  function seasons(wins) {                                                // consecutive outage days grouped into seasons
    const out = [];
    wins.forEach((w) => {
      const s = out[out.length - 1];
      if (s && w.peak - s.days[s.days.length - 1].peak < 1.6 * 86400000) s.days.push(w); else out.push({ days: [w] });
    });
    return out;
  }
  function sunSection(o) {
    const box = $("g-sunwin"); if (!box || !S.place || !window.NFSun) return;
    const g = o.p ? geodetic(o.p) : null;
    if (!g) { box.innerHTML = '<p class="small">No position at this time.</p>'; return; }
    if (Math.abs(o.drift) >= 0.1) { box.innerHTML = '<p class="small">This satellite is drifting, so its sun outages move from day to day; they are worked out only for satellites holding a longitude.</p>'; return; }
    const th = window.NFSun.threshold(S.dish, S.ghz), res = window.NFSun.windows(S.place.lat, S.place.lon, g.lon, Date.now(), 366, th);
    if (res.elev <= 0) { box.innerHTML = '<p class="small">Below the horizon from ' + esc(placeName()) + ": no sun outages there.</p>"; return; }
    S.sunwins = { o, wins: res.windows, th };
    const ss = seasons(res.windows);
    box.innerHTML = '<p class="small">Sun within ' + th.toFixed(2) + "° of the satellite (half the beamwidth of a " + S.dish + " m dish at " + S.ghz + " GHz, plus the sun's radius), for a satellite sitting on the equator at " + lonTxt(g.lon) + ".</p>" +
      (ss.length ? '<ul class="globe-near">' + ss.slice(0, 2).map((s) => {
        const a = s.days[0], z = s.days[s.days.length - 1], top = s.days.reduce((m, d) => (d.minutes > m.minutes ? d : m), a);
        return "<li><strong>" + a.peak.getUTCDate() + " " + MON[a.peak.getUTCMonth()] + " – " + z.peak.getUTCDate() + " " + MON[z.peak.getUTCMonth()] + " " + z.peak.getUTCFullYear() +
          "</strong>: " + s.days.length + " days, longest " + Math.round(top.minutes) + " min, centred " + esc(bothTxt(top.peak.getTime(), true)) + "</li>";
      }).join("") + "</ul>" : '<p class="small">No outages in the next year at this threshold.</p>') +
      '<p class="globe-tools"><label>Dish <input data-sun="dish" type="number" min="0.3" max="15" step="0.1" value="' + S.dish + '"> m</label><label>at <input data-sun="ghz" type="number" min="1" max="40" step="0.5" value="' + S.ghz + '"> GHz</label>' +
      (res.windows.length ? '<button type="button" data-act="csv-sun">Daily windows (CSV)</button>' : "") + "</p>" +
      '<p class="small">The same method as the <a href="/sun">Sun outages</a> page.</p>';
  }
  function lookTable() {                                                  // every shown object above the horizon from the place
    const rows = drawn.map((o) => ({ o, l: lookFrom(S.place, o.p) })).filter((r) => r.l.el > 0).sort((a, b) => b.l.el - a.l.el);
    S.look = rows;
    const act = rows.filter((r) => r.o.active).length;
    return '<h4 class="globe-h4">Seen from ' + esc(placeName()) + "</h4><p class=\"small\">" + fmtN(rows.length) + " of the objects shown are above the horizon (" + fmtN(act) + " listed as active), at " + esc(bothTxt(nowMs(), true)) + ". Highest first.</p>" +
      '<div class="tw"><table class="globe-list"><thead><tr><th>Object</th><th>Owner</th><th class="num">Elev.</th><th class="num">Bearing</th></tr></thead><tbody>' +
      rows.slice(0, 30).map((r) => '<tr><td><button type="button" class="linkish" data-act="pick" data-id="' + r.o.norad + '">' + esc(r.o.name) + "</button></td><td>" + esc(r.o.owner || "") +
        '</td><td class="num">' + r.l.el.toFixed(1) + '°</td><td class="num">' + Math.round(r.l.az) + "°</td></tr>").join("") + "</tbody></table></div>" +
      (rows.length > 30 ? '<p class="small">The first 30 of ' + fmtN(rows.length) + "; the CSV has them all.</p>" : "") +
      '<p class="globe-tools"><button type="button" data-act="csv-look">Look angles (CSV)</button></p>';
  }
  function download(name, head, rows) {
    const q = (v) => (/[",\n]/.test(String(v)) ? '"' + String(v).replace(/"/g, '""') + '"' : v);
    const blob = new Blob([head.join(",") + "\n" + rows.map((r) => r.map(q).join(",")).join("\n") + "\n" + '"' + S.cite + '"\n'], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }
  const iso = (ms) => new Date(ms).toISOString().slice(0, 16) + "Z", stamp = () => iso(Date.now()).replace(/[:]/g, "");
  function csvRel() {
    if (!S.rel) return;
    download("geo-relative-" + S.rel.A.norad + "-" + S.rel.B.norad + "-" + stamp() + ".csv",
      ["time_utc", "kind", "from_norad", "to_norad", "separation_km", "radial_km", "along_track_km", "cross_track_km"],
      S.rel.rel.map((p) => [iso(p.t), p.pred ? "predicted" : "recorded", S.rel.A.norad, S.rel.B.norad, p.sep.toFixed(1), p.r.toFixed(1), p.i.toFixed(1), p.c.toFixed(1)]));
  }
  function csvNear() {
    if (!S.near) return;
    const rows = [];
    S.near.near.forEach((nb) => nb.pts.forEach((p) => rows.push([iso(p[0]), p[2] ? "predicted" : "recorded", S.near.o.norad, nb.o.norad, nb.o.name, nb.o.owner || "", p[1].toFixed(1)])));
    download("geo-closest-" + S.near.o.norad + "-" + stamp() + ".csv", ["time_utc", "kind", "norad", "neighbour_norad", "neighbour_name", "neighbour_owner", "separation_km"], rows);
  }
  function csvLook() {
    if (!S.look || !S.place) return;
    const t = iso(nowMs());
    download("geo-look-angles-" + stamp() + ".csv", ["norad", "name", "owner", "active", "elevation_deg", "bearing_deg", "range_km", "place", "place_lat", "place_lon", "time_utc"],
      S.look.map((r) => [r.o.norad, r.o.name, r.o.owner || "", r.o.active ? 1 : 0, r.l.el.toFixed(2), r.l.az.toFixed(2), Math.round(r.l.range), S.place.name || "", S.place.lat.toFixed(4), S.place.lon.toFixed(4), t]));
  }
  function csvSun() {
    if (!S.sunwins || !S.place) return;
    download("geo-sun-outages-" + S.sunwins.o.norad + "-" + stamp() + ".csv", ["norad", "name", "place", "place_lat", "place_lon", "threshold_deg", "start_utc", "peak_utc", "end_utc", "minutes", "closest_deg"],
      S.sunwins.wins.map((w) => [S.sunwins.o.norad, S.sunwins.o.name, S.place.name || "", S.place.lat.toFixed(4), S.place.lon.toFixed(4), S.sunwins.th.toFixed(3),
        w.start.toISOString().slice(0, 19) + "Z", w.peak.toISOString().slice(0, 19) + "Z", w.end.toISOString().slice(0, 19) + "Z", w.minutes.toFixed(1), w.sep.toFixed(3)]));
  }

  // ---------------------------------------------------------------- G4: callouts (docs/validation/geo-callouts.md, v1)
  const CO_COL = { C1: "#ff8c42", C2: "#ffb380", C3: "#ff5d8f", C4: "#ff9ec0", C5: "#c792ea", C6: "#4dd0e1", C7: "#9be7f0", C8: "#9aa5b1" };
  const coRule = (id) => (S.coData ? S.coData.rules.find((r) => r.id === id) : null) || { name: id, score: "" };
  function coShown() {                                                    // enabled callouts in the 14 days up to the time shown
    if (!S.coData || !S.co) return [];
    const day = new Date(nowMs()).toISOString().slice(0, 10), from = new Date(nowMs() - 13 * 86400000).toISOString().slice(0, 10);
    return S.coData.callouts.filter((c) => S.co.has(c.r) && c.d <= day && (c.end || c.d) >= from);
  }
  function drawCallouts() {
    clearGroup(coGroup);
    const by = {};
    coShown().forEach((c) => [c.a, c.b].filter(Boolean).forEach((x) => {
      const o = S.byId.get(x[0]); if (o && o.p && shown(o)) (by[c.r] = by[c.r] || new Set()).add(o);
    }));
    Object.keys(by).forEach((r) => coGroup.add(ptsOf([...by[r]].map((o) => sc(...o.p)), CO_COL[r], 19)));
    dirty = true;
  }
  function calloutText(c, me) {
    const other = c.b ? (c.b[0] === me ? c.a : c.b) : null;
    const who = other ? " · " + other[1] + " (" + (other[2] || "?") + ")" : "";
    let n = "";
    if (c.min_km != null) n = ", closest " + fmtN(Math.round(c.min_km)) + " km";
    else if (c.km != null) n = ", " + fmtN(Math.round(c.km)) + " km" + (c.from_km != null ? " (from " + fmtN(Math.round(c.from_km)) + ")" : "");
    else if (c.r === "C3" && c.deg != null) n = ", " + c.deg.toFixed(2) + "° apart in longitude";
    else if (c.r === "C4" && c.days != null) n = ", about " + c.days + " days away at " + Math.abs(c.drift || 0).toFixed(2) + "° a day";
    else if (c.r === "C5") n = ": drift changed " + (c.drift_change || 0).toFixed(3) + "° a day, inclination " + (c.inc_change || 0).toFixed(3) + "°, longitude " + (c.lon_off_deg || 0).toFixed(2) + "° off";
    else if (c.kind) n = " (" + c.kind + ")";
    const d = (s) => { const x = new Date(s + "T00:00:00Z"); return x.getUTCDate() + " " + MON[x.getUTCMonth()]; };
    return d(c.d) + (c.end && c.end !== c.d ? "–" + d(c.end) : "") + " · " + c.r + " " + coRule(c.r).name + who + n + (c.role ? " · listed " + c.role + " role" : "");
  }
  function coFor(o) {
    if (!S.coData || !S.co) return [];
    const list = S.coData.callouts.filter((c) => S.co.has(c.r) && (c.a[0] === o.norad || (c.b && c.b[0] === o.norad)));
    return list.length ? [["Callouts", list.slice(-8).reverse().map((c) => esc(calloutText(c, o.norad))).join("<br>")]] : [];
  }
  function coRecent() {
    const list = coShown().slice().sort((a, b) => (a.d < b.d ? 1 : -1)).slice(0, 20);
    if (!S.coData) return "";
    return '<h4 class="globe-h4">Callouts in the 14 days to ' + esc(utcTxt(nowMs(), true).split(",")[0]) + "</h4>" +
      (list.length ? '<ul class="globe-near">' + list.map((c) => '<li><i style="background:' + CO_COL[c.r] + '"></i><button type="button" class="linkish" data-act="copick" data-ids="' +
        [c.a[0]].concat(c.b ? [c.b[0]] : []).join(",") + '">' + esc(c.a[1]) + "</button> " + esc(calloutText(c, c.a[0])) + "</li>").join("") + "</ul>"
        : '<p class="small">None for the rules switched on.</p>') +
      '<p class="small">Behaviour only, never intent. Each rule was tested on published cases before it was switched on; see Callouts above for the scores.</p>';
  }
  function coUI() {
    const el = $("g-callouts");
    if (!S.coData) { el.innerHTML = '<p class="small">The callouts file could not be loaded.</p>'; return; }
    el.innerHTML = "<fieldset><legend>Callouts, last 14 days</legend>" + S.coData.rules.map((r) => '<label><input type="checkbox" data-co="' + r.id + '"' +
      (S.co.has(r.id) ? " checked" : "") + '> <i class="co-key" style="background:' + CO_COL[r.id] + '"></i>' + esc(r.id + " " + r.name) +
      ' <span class="small">(' + esc(r.score) + ")</span></label>").join("") + '</fieldset><p class="small">Behaviour only, never intent. ' +
      '<a href="https://github.com/metacog-osint/noise-floor/blob/main/docs/validation/geo-callouts.md">How each rule was tested</a>.</p>';
  }

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
    } else if (!down.moved && S.pickPlace) {
      const ray = new THREE.Raycaster(), hit = (ray.setFromCamera(new THREE.Vector2((x / r.width) * 2 - 1, 1 - (y / r.height) * 2), camera), ray.intersectObject(earth)[0]);
      if (hit) { const p = hit.point; setPlace({ lat: Math.asin(p.y / p.length()) / DEG, lon: Math.atan2(-p.z, p.x) / DEG, name: "" }); }
      S.pickPlace = false; canvas.classList.remove("aiming");
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
    let extra = "";
    if (S.over && S.board) { const it = overlayItems(), n = { close: it.close.length, man: it.man.length, ev: it.ev.length };
      extra = OVER.map((v) => '<span><i class="ring" style="border-color:' + v[1] + '"></i>' + esc(v[2]) + " " + fmtN(n[v[0]]) + "</span>").join(""); }
    if (S.co && S.coData) { const on = S.coData.rules.filter((r) => S.co.has(r.id)); if (on.length) extra += on.map((r) => '<span><i class="ring" style="border-color:' + CO_COL[r.id] + '"></i>' + esc(r.id + " " + r.name) + "</span>").join(""); }
    if (S.sun) extra += '<span><i style="background:' + SUN_COL + '"></i>Sun, day–night line</span><span><i class="bar" style="background:' + SHADOW_COL + '"></i>Belt in the Earth\u2019s shadow</span>';
    $("g-legend").innerHTML = items.map((i) => '<span><i style="background:' + i[0] + '"></i>' + esc(i[1]) + " " + fmtN(i[2]) + "</span>").join("") + extra;
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
  function lookTxt(o) {
    if (!o.p || !S.place) return "not computed at this time";
    const l = lookFrom(S.place, o.p);
    return l.el > 0 ? "elevation " + l.el.toFixed(1) + "°, bearing " + bearingTxt(l.az) + ", " + fmtN(Math.round(l.range)) + " km away"
                    : "below the horizon (elevation " + l.el.toFixed(1) + "°)";
  }
  function sunlitTxt(o) {
    const s = sunDir(nowMs());
    if (!o.p || !s) return "not computed";
    return inShadow(o.p, s) ? "in the Earth's shadow at the time shown" : "sunlit at the time shown";
  }
  let panelKey = "";
  const keyOf = () => [S.sel.join(","), [...S.beams.keys()].filter((id) => S.sel.includes(id)).join(","), S.win, S.track ? S.track.t0 : 0,
    S.place ? S.place.lat + "," + S.place.lon : "", S.sel.length ? "" : drawn.length + "/" + S.q, S.co ? [...S.co].join(",") : "-",
    S.sel.length ? "" : new Date(nowMs()).toISOString().slice(0, 10)].join("|");
  function panelUpdate() {
    const key = keyOf();
    if (key !== panelKey) { panel(true); return; }
    document.querySelectorAll("#g-panel canvas.globe-chart").forEach((cv) => { if (cv._cfg) lineChart(cv, cv._cfg); });
    const sel = S.sel.map((id) => S.byId.get(id)).filter(Boolean);
    if (sel.length === 1) {
      const o = sel[0], g = o.p ? geodetic(o.p) : null, age = (nowMs() - epochMs(o.epoch)) / 86400000, pos = $("g-pos"), ag = $("g-age");
      if (pos) pos.textContent = g ? lonTxt(g.lon) + ", " + latTxt(g.lat) + ", " + signed(g.dalt) + " from GEO" : "not computed at this time";
      if (ag) ag.textContent = (age < 1 ? Math.round(age * 24) + " hours" : age.toFixed(1) + " days") + " before the time shown";
      const lk = $("g-look"); if (lk && S.place) lk.textContent = lookTxt(o);
      const sl = $("g-sunlit"); if (sl) sl.textContent = sunlitTxt(o);
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
    panelKey = keyOf();
    S.rel = null; S.near = null;
    const el = $("g-panel"), sel = S.sel.map((id) => S.byId.get(id)).filter(Boolean);
    if (!sel.length) {
      el.innerHTML = '<p class="small">Click a dot to see what it is. Shift-click adds to the selection; Shift-drag a box selects every dot inside it. Search finds names, catalogue numbers, owners and countries.</p>' +
        coRecent() + (S.place ? lookTable() : '<p class="small">Pick a place under "Look from" to list what can be seen from it.</p>');
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
        ["Sunlight", '<span id="g-sunlit">' + esc(sunlitTxt(o)) + "</span>"],
      ].concat(S.place ? [["From " + esc(placeName()), '<span id="g-look">' + esc(lookTxt(o)) + "</span>"]] : []).concat(coFor(o)).concat(boardFor(o));
      el.innerHTML = "<h3>" + esc(o.name) + '</h3><p class="small">Catalogue ' + o.norad + (o.cospar ? " · " + esc(o.cospar) : "") +
        ' · <a href="https://celestrak.org/satcat/table-satcat.php?CATNR=' + o.norad + '">CelesTrak record</a></p><dl class="globe-dl">' +
        rows.map((r) => "<dt>" + r[0] + "</dt><dd>" + r[1] + "</dd>").join("") + "</dl>" +
        '<details class="globe-more" data-more="near"' + (S.open.near ? " open" : "") + '><summary>Closest objects over time</summary><div id="g-near"><p class="small">Working…</p></div></details>' +
        (S.place ? '<details class="globe-more" data-more="sun"' + (S.open.sun ? " open" : "") + '><summary>Sun outages from ' + esc(placeName()) + '</summary><div id="g-sunwin"><p class="small">Working…</p></div></details>' : "") +
        beamForm(o) + tools;
      if (S.open.near) nearSection(o);
      if (S.open.sun && S.place) sunSection(o);
    } else {
      let sep = "";
      if (sel.length === 2 && sel[0].p && sel[1].p) {
        const d = Math.hypot(sel[0].p[0] - sel[1].p[0], sel[0].p[1] - sel[1].p[1], sel[0].p[2] - sel[1].p[2]) * RE;
        sep = '<p class="small">Separation at the time shown: <strong id="g-sep">' + fmtN(Math.round(d)) + " km</strong> (public elements: good to tens of km).</p>";
      }
      el.innerHTML = "<h3>" + sel.length + " selected</h3>" + sep + '<div class="tw"><table class="globe-list"><thead><tr><th>Object</th><th>Owner</th><th class="num">Longitude</th><th class="num">Drift °/day</th></tr></thead><tbody>' +
        sel.map((o) => { const g = o.p ? geodetic(o.p) : null; return '<tr data-id="' + o.norad + '"><td><button type="button" class="linkish" data-act="focus" data-id="' + o.norad + '">' + esc(o.name) + '</button></td><td>' + esc(o.owner || "") +
          '</td><td class="num" data-lon="' + o.norad + '">' + (g ? lonTxt(g.lon) : "–") + '</td><td class="num">' + (o.drift >= 0 ? "+" : "") + o.drift.toFixed(3) + "</td></tr>"; }).join("") + "</tbody></table></div>" +
        (sel.length === 2 ? relSection(sel[0], sel[1]) : "") + tools;
      if (sel.length === 2) drawRelCharts();
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
  $("g-panel").addEventListener("change", (e) => {
    const f = e.target.dataset.sun;
    if (f) { const v = +e.target.value; if (f === "dish" && v >= 0.3 && v <= 15) S.dish = v; if (f === "ghz" && v >= 1 && v <= 40) S.ghz = v; const o = S.byId.get(S.sel[0]); if (o) sunSection(o); return; }
    beamInput(e);
  });
  $("g-panel").addEventListener("toggle", (e) => {                       // the slower sections are worked out when opened
    const d = e.target; if (!d.dataset || !d.dataset.more) return;
    S.open[d.dataset.more] = d.open;
    const o = S.byId.get(S.sel[0]); if (!d.open || !o) return;
    if (d.dataset.more === "near") setTimeout(() => nearSection(o), 0); else if (d.dataset.more === "sun") setTimeout(() => sunSection(o), 0);
  }, true);
  $("g-panel").addEventListener("pointermove", chartHover);
  $("g-panel").addEventListener("pointerleave", chartLeave, true);
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
    if (act === "csv-rel") { csvRel(); return; }
    if (act === "csv-near") { csvNear(); return; }
    if (act === "csv-look") { csvLook(); return; }
    if (act === "csv-sun") { csvSun(); return; }
    if (act === "add") { const o = S.byId.get(+b.dataset.id); if (o && !S.sel.includes(o.norad)) { S.sel.push(o.norad); selectionChanged(); } return; }
    if (act === "pick") { const o = S.byId.get(+b.dataset.id); if (o) { select([o], false); focus(o); } return; }
    if (act === "copick") { const os = b.dataset.ids.split(",").map((x) => S.byId.get(+x)).filter(Boolean); if (os.length) { select(os, false); focus(os[0]); } return; }
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
  $("g-sun").addEventListener("change", (e) => { S.sun = e.target.checked; drawSun(); legend(); writeHash(); });
  $("g-over").addEventListener("change", (e) => { S.over = e.target.checked; drawOverlays(); legend(); writeHash(); });
  $("g-callouts").addEventListener("change", (e) => {
    const r = e.target.dataset.co; if (!r || !S.co) return;
    if (e.target.checked) S.co.add(r); else S.co.delete(r);
    drawCallouts(); legend(); writeHash(); panel(true);
  });
  let PLACES = [];
  function setPlace(pl) {
    S.place = pl; $("g-place").value = pl ? (pl.name || pl.lat.toFixed(3) + ", " + pl.lon.toFixed(3)) : ""; $("g-noplace").hidden = !pl;
    drawPlace(); writeHash(); panel(true);
  }
  $("g-place").addEventListener("change", (e) => {
    const v = e.target.value.trim(), hit = PLACES.find((p) => p[0].toLowerCase() === v.toLowerCase());
    const m = v.match(/^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$/);
    if (!v) setPlace(null);
    else if (hit) setPlace({ lat: hit[1], lon: hit[2], name: hit[0] });
    else if (m && Math.abs(+m[1]) <= 90 && Math.abs(+m[2]) <= 180) setPlace({ lat: +m[1], lon: +m[2], name: "" });
    else $("g-placenote").textContent = "Pick a city from the list, or type latitude, longitude (such as 35.7, 51.4).";
    if (hit || m || !v) $("g-placenote").textContent = "";
  });
  $("g-pick").addEventListener("click", () => { S.pickPlace = true; S.aim = null; canvas.classList.add("aiming"); $("g-placenote").textContent = "Click a point on the Earth."; });
  $("g-noplace").addEventListener("click", () => setPlace(null));
  fetch("/data/places.json").then((r) => (r.ok ? r.json() : null)).then((j) => {
    if (!j) return;
    PLACES = j.places.filter((p) => isFinite(p[1]) && isFinite(p[2]));
    $("g-places").innerHTML = PLACES.map((p) => '<option value="' + esc(p[0]) + '">').join("");
  }).catch(() => {});

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
  $("g-sun").checked = S.sun; $("g-over").checked = S.over;
  if (S.place) { $("g-place").value = S.place.name || S.place.lat.toFixed(3) + ", " + S.place.lon.toFixed(3); $("g-noplace").hidden = false; }
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
    fetch("/data/geo/callouts.json", { cache: "no-cache" }).then((r) => (r.ok ? r.json() : null)).catch(() => null).then((co) => {
      S.coData = co;
      S.co = new Set(co ? (S.coHash || co.rules.filter((r) => r.default_on).map((r) => r.id)) : []);
      coUI(); drawCallouts(); legend(); panel(true);
    });
    clearInterval(liveTimer);
    liveTimer = setInterval(() => { if (S.t == null) { timeLabel(); updatePositions(); } }, 30000);
    requestAnimationFrame(frame);
  });
}
