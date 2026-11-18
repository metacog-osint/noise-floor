// workers/ism (the nf-ism Worker): capture logic and R2 writes, on synthetic grids. No ESA data is kept in this
// public repo (ESA's S2P terms, 3.2), so the XML here is made up in ESA's format. Run: node tests/test_ism_worker.mjs
import { gunzipSync } from "node:zlib";
import { pyRound, parseRecords, buildHour, gzip, SUMMARY_COLS, DATA_HEADER } from "../workers/ism/ism.js";
import { capture } from "../workers/ism/worker.js";

let bad = 0, n = 0;
const ok = (cond, msg) => { n++; if (!cond) { bad++; console.log("FAIL", msg); } };
const eq = (a, b, msg) => ok(a === b, `${msg}: got ${JSON.stringify(a)}, want ${JSON.stringify(b)}`);
const throws = (f, re, msg) => { try { f(); ok(false, `${msg}: no error`); } catch (e) { ok(re.test(e.message), `${msg}: ${e.message}`); } };

// Python round(): half to even on the exact double
eq(pyRound(0.025 * 100), 2, "0.025*100 is exactly 2.5, Python rounds to 2");
eq(pyRound(0.035 * 100), 4, "0.035*100 just above 3.5");
eq(pyRound(2.5), 2, "2.5"); eq(pyRound(3.5), 4, "3.5"); eq(pyRound(-2.5), -2, "-2.5"); eq(pyRound(-3.5), -4, "-3.5");
eq(pyRound(77.00000000000001), 77, "near-integer from 0.077*1000"); eq(pyRound(12.4), 12, "12.4"); eq(pyRound(12.6), 13, "12.6");

// a synthetic hour in ESA's format: 145 x 71 cells, lon fastest, as in ism/grid.csv
const LONS = Array.from({ length: 145 }, (_, i) => (-180 + 2.5 * i).toFixed(1));
const LATS = Array.from({ length: 71 }, (_, j) => (-87.5 + 2.5 * j).toFixed(1));
function xml(valueAt, { date = "2026-11-18T17:00:00.000Z", cells = null } = {}) {
  const recs = [];
  for (const lat of LATS) for (const lon of LONS) {
    const [v, e] = valueAt(+lon, +lat);
    recs.push(`<ns2:record><ns2:date>${date}</ns2:date><ns2:stringValue>${lon}</ns2:stringValue><ns2:stringValue>${lat}</ns2:stringValue><ns2:stringValue>${v}</ns2:stringValue><ns2:stringValue>${e}</ns2:stringValue></ns2:record>`);
  }
  return `<?xml version="1.0"?><sweDataTypeXML><dataType>${(cells ? recs.slice(0, cells) : recs).join("")}</dataType></sweDataTypeXML>`;
}
// S4 0.900 at one CENTCOM cell (lon 45, lat 25), 0.600 at one EUCOM cell (10, 50), 0.012 elsewhere
const s4At = (lon, lat) => [lon === 45 && lat === 25 ? "0.900" : lon === 10 && lat === 50 ? "0.600" : "0.012", "0.025"];
const spAt = (lon, lat) => [lon === 120 && lat === 20 ? "0.450" : "0.030", "0.035"];
const tecAt = (lon, lat) => [lat > 0 ? "12.5" : "13.5", "2.5"];
const X = { s4: xml(s4At), sigma_phi: xml(spAt), tec: xml(tecAt) };

eq(parseRecords(X.s4).length, 10295, "cells parsed");
const cap = new Date("2026-11-18T19:07:31Z");
const h = buildHour(X, cap);
eq(h.validUtc, "2026-11-18T17:00Z", "valid time");
eq(h.dataKey, "ism/2026/11/ism_20261118T17Z.csv.gz", "data key matches the repo layout");
eq(h.summaryKey, "ism/2026/11/ism_20261118T17Z.summary.csv", "summary key");
eq(h.mixedTimes, null, "one valid time");
const rows = h.dataCsv.trimEnd().split("\n");
eq(rows[0], DATA_HEADER, "data header"); eq(rows.length, 10296, "header + one row per cell");
eq(h.dataCsv.endsWith("\n") && !h.dataCsv.includes("\r"), true, "LF only, trailing newline");
// first cell (-180, -87.5): s4 12, err 0.025*100 -> 2 (half-even), sp 30, err 0.035*100 -> 4, tec 13.5 -> 14, err 2.5 -> 2
eq(rows[1], "12,2,30,4,14,2", "first cell row");
// a northern cell: tec 12.5 -> 12 (half-even)
eq(rows[1 + 145 * 70].split(",")[4], "12", "tec 12.5 rounds to 12 like Python");
eq(h.gridCsv.split("\n")[1], "-180.0,-87.5", "grid first cell"); eq(h.gridCsv.split("\n").length, 10297, "grid lines");
const s = Object.fromEntries(SUMMARY_COLS.map((c, i) => [c, h.summaryRow.split(",")[i]]));
eq(s.captured_utc, "2026-11-18T19:07Z", "captured time");
eq(s.global_max_s4, "0.900", "global max S4"); eq(s.global_max_sigma_phi, "0.450", "global max sigma-phi");
eq(s.n_s4_mod, "2", "S4 >= 0.5 count"); eq(s.n_s4_sev, "1", "S4 >= 0.8 count");
eq(s.n_sp_mod, "1", "sigma-phi >= 0.4 count"); eq(s.n_sp_sev, "0", "sigma-phi >= 0.7 count");
eq(s.centcom_max_s4, "0.900", "CENTCOM max S4"); eq(s.eucom_max_s4, "0.600", "EUCOM max S4");
eq(s.indopacom_max_sigma_phi, "0.450", "INDOPACOM max sigma-phi"); eq(s.northcom_max_s4, "0.012", "NORTHCOM max S4");
eq(h.summaryCsv, SUMMARY_COLS.join(",") + "\n" + h.summaryRow + "\n", "summary file is header + row");

throws(() => buildHour({ ...X, tec: xml(tecAt, { cells: 9000 }) }), /tec: only 9000 cells/, "truncated file");
const swapped = X.sigma_phi.replace("<ns2:stringValue>-180.0</ns2:stringValue>", "<ns2:stringValue>-179.0</ns2:stringValue>");
throws(() => buildHour({ ...X, sigma_phi: swapped }), /grid order differs/, "grid mismatch");
const mixed = buildHour({ ...X, tec: xml(tecAt, { date: "2026-11-18T18:00:00.000Z" }) }, cap);
eq(mixed.validUtc, "2026-11-18T17:00Z", "mixed times use the earliest, like the Python");
ok(Array.isArray(mixed.mixedTimes) && mixed.mixedTimes.length === 2, "mixed times reported");

// gzip round trip
eq(gunzipSync(await gzip(h.dataCsv)).toString(), h.dataCsv, "gzip round trip");

// capture(): writes data, grid and summary (summary last), then skips the stored hour
function fakeBucket() {
  const store = new Map(), order = [];
  return {
    store, order,
    async head(k) { return store.has(k) ? { key: k } : null; },
    async put(k, v, opts) { store.set(k, { v, opts }); order.push(k); return { key: k }; },
  };
}
const env = { ISM: fakeBucket() };
const fetcher = async (name) => X[name];
const r1 = await capture(env, cap, fetcher);
eq(r1.status, "captured", "first run captures");
eq(env.ISM.order.join(" "), `${h.dataKey} ism/grid.csv ${h.summaryKey}`, "write order: data, grid, summary last");
eq(gunzipSync(env.ISM.store.get(h.dataKey).v).toString(), h.dataCsv, "stored data decompresses to the CSV");
eq(env.ISM.store.get(h.dataKey).opts.customMetadata.valid_utc, "2026-11-18T17:00Z", "metadata valid time");
eq(env.ISM.store.get(h.dataKey).opts.httpMetadata.contentEncoding, undefined, "no Content-Encoding: downloads stay .gz");
eq(env.ISM.store.get(h.dataKey).opts.httpMetadata.contentType, "application/gzip", "gzip content type");
const r2 = await capture(env, cap, fetcher);
eq(r2.status, "already", "second run skips the stored hour"); eq(env.ISM.order.length, 3, "nothing rewritten");
// an hour whose data was written but whose summary write failed is written again in full
env.ISM.store.delete(h.summaryKey);
eq((await capture(env, cap, fetcher)).status, "captured", "missing summary means the hour is redone");
ok(!env.ISM.order.slice(3).includes("ism/grid.csv"), "grid written only once");

// a fetch failure throws (the Worker then pings /fail)
let threw = false;
try { await capture({ ISM: fakeBucket() }, cap, async () => { throw new Error("fetch s4 failed: HTTP 503"); }); } catch { threw = true; }
ok(threw, "fetch failure propagates");

console.log(`${n - bad}/${n} checks passed`);
process.exit(bad ? 1 : 0);
