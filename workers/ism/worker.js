// nf-ism: captures ESA's ionospheric scintillation nowcast into the private R2 bucket nf-ism-archive.
// Replaces noise-floor-data's ism-hourly workflow and the PC task "noise-floor ESA scintillation capture"
// (18 Nov 2026: Worker + R2, so the archive costs no Actions minutes and needs no PC).
//
// Each run fetches the three current products, and writes the hour unless its summary object already exists:
//   ism/YYYY/MM/ism_YYYYMMDDTHHZ.csv.gz        the grid values (same layout and values as the Python capture)
//   ism/YYYY/MM/ism_YYYYMMDDTHHZ.summary.csv   header + one summary row (written last: it marks the hour done)
//   ism/grid.csv                               cell order, written once
// No public URL (workers_dev = false); the bucket is private. Optional secret HC_PING_URL: a Healthchecks.io check,
// pinged on success and at /fail on a failed run.
import { BASE, PRODUCTS, buildHour, gzip } from "./ism.js";

const UA = "noise-floor-ism/1.0 (+https://noisefloor.theintelligence.company)";

async function fetchProduct(name, attempts = 3) {
  let err;
  for (let i = 0; i < attempts; i++) {
    try {
      const r = await fetch(`${BASE}${name}_nowcast_grid.xml`, {
        headers: { "User-Agent": UA }, signal: AbortSignal.timeout(60_000),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return await r.text();
    } catch (e) {
      err = e;
      if (i < attempts - 1) await new Promise((res) => setTimeout(res, 5_000));
    }
  }
  throw new Error(`fetch ${name} failed: ${err?.message ?? err}`);
}

export async function capture(env, now = new Date(), fetcher = fetchProduct) {
  const xmls = {};
  for (const [name] of PRODUCTS) xmls[name] = await fetcher(name);
  const h = buildHour(xmls, now);
  if (h.mixedTimes) console.log("mixed valid times across products:", h.mixedTimes.join(" "));
  if (await env.ISM.head(h.summaryKey)) return { status: "already", valid: h.validUtc };
  const meta = { customMetadata: { valid_utc: h.validUtc, source: "ESA S2P SWE ISM nowcast" } };
  const data = await gzip(h.dataCsv);
  // a .gz file as such: no Content-Encoding header, which would make downloads arrive unzipped
  await env.ISM.put(h.dataKey, data, { ...meta, httpMetadata: { contentType: "application/gzip" } });
  if (!(await env.ISM.head(h.gridKey))) await env.ISM.put(h.gridKey, h.gridCsv, { httpMetadata: { contentType: "text/csv" } });
  await env.ISM.put(h.summaryKey, h.summaryCsv, { ...meta, httpMetadata: { contentType: "text/csv" } });
  return { status: "captured", valid: h.validUtc, bytes: data.length, summary: h.summaryRow };
}

async function ping(env, path = "") {
  if (!env.HC_PING_URL) return;
  try { await fetch(env.HC_PING_URL + path, { method: "POST", signal: AbortSignal.timeout(10_000) }); } catch { /* best effort */ }
}

export default {
  async scheduled(event, env, ctx) {
    try {
      const r = await capture(env, new Date(event.scheduledTime));
      console.log(JSON.stringify(r));
      ctx.waitUntil(ping(env));
    } catch (e) {
      console.log("capture failed:", e?.message ?? e);
      ctx.waitUntil(ping(env, "/fail"));
      throw e;
    }
  },
  async fetch() {
    return new Response("Not found", { status: 404 });
  },
};
