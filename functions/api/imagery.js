// GET /api/imagery (Cloudflare Pages Function): which licensed imagery this visitor may be offered.
// Esri's ArcGIS Location Platform Agreement (E204, rev. 21 Nov 2025, 11.4) bars access "to, by or from" US-embargoed
// countries and regions (Iran, Syria, North Korea, Cuba, Crimea, DNR, LNR) and providing access to Russia or Belarus.
// So the Esri key, kept as the Pages secret ESRI_API_KEY (never in the repository), goes only to visitors whose country
// Cloudflare places elsewhere. Donetsk and Luhansk oblasts are blocked whole (the agreement names the so-called DNR and
// LNR; IP location can't draw the front line). Tor (T1) is blocked because its location is unknown.
// Background: docs/research/2026-10-26-imagery-options.md.

const BLOCKED_COUNTRIES = new Set(["IR", "SY", "KP", "CU", "RU", "BY", "T1"]);
const BLOCKED_REGIONS = new Set(["UA-43", "UA-40", "UA-14", "UA-09"]);   // Crimea, Sevastopol, Donetsk, Luhansk (ISO 3166-2)

function verdict(cf, key) {
  const country = (cf && cf.country) || "XX";
  const region = country + "-" + ((cf && cf.regionCode) || "");
  const blocked = BLOCKED_COUNTRIES.has(country) || BLOCKED_REGIONS.has(region);
  if (!key) return { esri: null, reason: "not configured" };
  if (blocked) return { esri: null, reason: "region" };
  return { esri: { key: key }, reason: null };
}

export function onRequestGet({ request, env }) {
  const body = verdict(request.cf, env.ESRI_API_KEY || "");
  return new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "private, no-store" },
  });
}
