// site_src/sunoutage.js against tools/sun_transit.py: the same windows for the cases in tests/fixtures/sun_transit_cases.json
// (made by the Python tool). Run: node tests/test_sunoutage.mjs
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const S = require(join(here, "..", "site_src", "sunoutage.js"));
const fx = JSON.parse(readFileSync(join(here, "fixtures", "sun_transit_cases.json"), "utf8"));

let bad = 0, n = 0;
const sec = (a, b) => Math.abs(Date.parse(a) - (b instanceof Date ? b.getTime() : Date.parse(b))) / 1000;
for (const c of fx.cases) {
  const r = S.windows(c.lat, c.lon, c.satLon, c.from, c.days, 1.2);
  if (Math.abs(r.elev - c.elev) > 0.01) { bad++; console.log("elevation", c.name, r.elev, c.elev); }
  if (r.windows.length !== c.windows.length) { bad++; console.log("count", c.name, r.windows.length, c.windows.length); continue; }
  c.windows.forEach((w, i) => {
    const j = r.windows[i]; n++;
    const worst = Math.max(sec(w.start, j.start), sec(w.end, j.end), sec(w.peak, j.peak));
    if (worst > 5 || Math.abs(w.sep - j.sep) > 0.001) { bad++; console.log("window", c.name, w, j, worst); }
  });
}
// threshold: a 0.9 m dish at 12 GHz gives about 1.2 deg (the Python default)
const th = S.threshold(0.9, 12);
if (Math.abs(th - 1.24) > 0.02) { bad++; console.log("threshold", th); }
// the fast scan finds the same Tehran window as the daily routine
const c0 = fx.cases[0], w0 = c0.windows[0], day0 = Date.parse(w0.peak.slice(0, 10) + "T00:00:00Z");
const s = S.scan([{ lat: c0.lat, lon: c0.lon, satLon: c0.satLon }], day0, 1440, 1.2);
if (s.length !== 1 || sec(w0.peak, s[0].peak) > 60 || sec(w0.start, s[0].start) > 60) { bad++; console.log("scan", s, w0); }
console.log(bad ? `test_sunoutage: ${bad} problem(s)` : `test_sunoutage: ok (${n} windows match)`);
process.exit(bad ? 1 : 0);
