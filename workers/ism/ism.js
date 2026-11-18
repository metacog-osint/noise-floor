// ism.js: the ESA SWE / CLS ISM capture logic, ported from noise-floor-data's capture/ism_capture.py so the Worker
// writes the same hour files and summary values as the Python capture did. Pure functions, no Cloudflare APIs, so
// Node can test it (tests/test_ism_worker.mjs).
//
// ESA publishes only the current hour of its worldwide ionospheric nowcast (S4, sigma-phi, TEC on a 2.5 deg grid).
// ESA's S2P data terms (3.2) allow passing the raw grids only to people who accept the same terms, so the hour files
// go to a private R2 bucket, never to this public repo. Data: (c) ESA. "Data provided by the European Space Agency
// (ESA) as part of its Space Safety Programme (S2P)".

export const BASE = "https://swe.ssa.esa.int/assets/ism/ism_nowcast/";
export const PRODUCTS = [["s4", 1000, 100], ["sigma_phi", 1000, 100], ["tec", 1, 1]]; // [name, value scale, error scale]
export const REGIONS = {
  centcom: [12, 42, 30, 65], eucom: [35, 72, -25, 45], africom: [-35, 35, -20, 50],
  indopacom: [-10, 45, 95, 150], northcom: [15, 50, -125, -65], southcom: [-56, 15, -95, -30],
}; // [lat min, lat max, lon min, lon max], inclusive
export const MIN_CELLS = 10000; // the grid is 145 x 71 = 10,295 cells; fewer means a truncated file
export const DATA_HEADER = "s4,s4_err,sigma_phi,sigma_phi_err,tec,tec_err";
export const SUMMARY_COLS = ["valid_utc", "captured_utc", "global_max_s4", "global_max_sigma_phi",
  "n_s4_mod", "n_s4_sev", "n_sp_mod", "n_sp_sev",
  ...Object.keys(REGIONS).flatMap((r) => [`${r}_max_s4`, `${r}_max_sigma_phi`])];

const REC = /<ns2:date>([^<]+)<\/ns2:date><ns2:stringValue>([^<]+)<\/ns2:stringValue><ns2:stringValue>([^<]+)<\/ns2:stringValue><ns2:stringValue>([^<]+)<\/ns2:stringValue><ns2:stringValue>([^<]+)<\/ns2:stringValue>/g;

// Python's round(): half to even on the exact double. JS Math.round sends halves up, and halves do occur here
// (0.025 * 100 is exactly 2.5 as a double: Python gives 2, Math.round 3).
export function pyRound(y) {
  const f = Math.floor(y), d = y - f;
  if (d < 0.5) return f;
  if (d > 0.5) return f + 1;
  return f % 2 === 0 ? f : f + 1;
}

// One product's XML -> records [date, lon, lat, value, error] as strings, in file order.
export function parseRecords(xml) {
  return Array.from(xml.matchAll(REC), (m) => [m[1], m[2], m[3], m[4], m[5]]);
}

const pad = (n) => String(n).padStart(2, "0");

// xmls: { s4, sigma_phi, tec } -> the hour's files. Throws on a truncated file or a grid mismatch, like the Python.
export function buildHour(xmls, capturedAt = new Date()) {
  const grids = {}, times = new Set();
  let cells = null;
  for (const [name] of PRODUCTS) {
    const recs = parseRecords(xmls[name]);
    if (recs.length < MIN_CELLS) throw new Error(`${name}: only ${recs.length} cells`);
    for (const r of recs) times.add(r[0]);
    const ll = recs.map((r) => [r[1], r[2]]);
    if (cells === null) cells = ll;
    else if (ll.length !== cells.length || ll.some((c, i) => c[0] !== cells[i][0] || c[1] !== cells[i][1]))
      throw new Error(`${name}: grid order differs`);
    grids[name] = recs.map((r) => [parseFloat(r[3]), parseFloat(r[4])]);
  }
  const sorted = [...times].sort();
  const mixedTimes = sorted.length !== 1 ? sorted : null; // the Python only printed this and used the earliest
  const t = sorted[0].slice(0, 19); // YYYY-MM-DDTHH:MM:SS
  const vt = new Date(t + "Z");
  if (Number.isNaN(vt.getTime())) throw new Error(`bad valid time ${sorted[0]}`);
  const Y = vt.getUTCFullYear(), M = pad(vt.getUTCMonth() + 1), D = pad(vt.getUTCDate()), H = pad(vt.getUTCHours());
  const stem = `ism/${Y}/${M}/ism_${Y}${M}${D}T${H}Z`;

  const lines = [DATA_HEADER];
  for (let i = 0; i < cells.length; i++) {
    const row = [];
    for (const [name, k, ke] of PRODUCTS) {
      const [v, e] = grids[name][i];
      row.push(String(pyRound(v * k)), String(pyRound(e * ke)));
    }
    lines.push(row.join(","));
  }
  const dataCsv = lines.join("\n") + "\n";
  const gridCsv = "lon,lat\n" + cells.map(([a, b]) => `${a},${b}\n`).join("");

  const lon = cells.map(([a]) => parseFloat(a)), lat = cells.map(([, b]) => parseFloat(b));
  const s4 = grids.s4.map(([v]) => v), sp = grids.sigma_phi.map(([v]) => v);
  const max = (xs) => xs.reduce((m, x) => (x > m ? x : m), -Infinity);
  const count = (xs, th) => xs.reduce((n, x) => n + (x >= th ? 1 : 0), 0);
  const iso = (d) => `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}Z`;
  const vals = [iso(vt), iso(capturedAt), max(s4).toFixed(3), max(sp).toFixed(3),
    count(s4, 0.5), count(s4, 0.8), count(sp, 0.4), count(sp, 0.7)];
  for (const [a, b, c, d] of Object.values(REGIONS)) {
    const idx = [];
    for (let i = 0; i < cells.length; i++) if (a <= lat[i] && lat[i] <= b && c <= lon[i] && lon[i] <= d) idx.push(i);
    vals.push(max(idx.map((i) => s4[i])).toFixed(3), max(idx.map((i) => sp[i])).toFixed(3));
  }
  const summaryRow = vals.join(",");
  return {
    validUtc: vals[0], mixedTimes,
    dataKey: `${stem}.csv.gz`, summaryKey: `${stem}.summary.csv`, gridKey: "ism/grid.csv",
    dataCsv, gridCsv, summaryCsv: SUMMARY_COLS.join(",") + "\n" + summaryRow + "\n", summaryRow,
  };
}

export async function gzip(text) {
  const stream = new Blob([text]).stream().pipeThrough(new CompressionStream("gzip"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}
