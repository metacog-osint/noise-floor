# Sun outages: calculator, status board and alerts (26 Oct 2026)

Tom asked (26 Oct 2026) for the sun-outage calculator to work both ways: **manually**, whenever someone wants it, and
**automatically**, as a heads-up display on the home page that raises alerts when satellites or parts of the
geostationary arc are **predicted and observed** to be in blackout conditions. His choices: observed evidence from NOAA's
solar radio data, our own aircraft GNSS data and outage reports; coverage by a broad public list and by the whole arc;
the home page becomes the dashboard; alerts on the site and in the Atom feed.

## What's built

| Part | Where | Updates |
|---|---|---|
| Calculator | `/sun` (`site_src/sun.html`, `sun.js`) | Live in the browser |
| Shared geometry | `site_src/sunoutage.js` (port of `tools/sun_transit.py`) | – |
| Status board | home page (`site_src/index.html`, `dash.js`) | Live in the browser; "now" refreshes each minute |
| Watch list | `site/data/sun/targets.json` (32 nominal slots, 36 cities) | By hand |
| Deploy-time alerts | `tools/sun_alerts.py` → `site/data/sun/alerts.json` → feed entries (`tools/site_days.py`) | Each deploy (daily, and on pushes) |
| Curated outage reports | `site/data/sun/reports.json` | By hand, public sources only |

## Prediction

- **Geometry.** Low-precision solar ephemeris (Meeus, about 0.01°), an ideal geostationary satellite at its nominal
  longitude, a WGS84 receiver at sea level. Outage: the sun's centre within the threshold angle of the satellite.
- **Threshold.** Half the 3 dB beamwidth (70 × wavelength ÷ dish diameter, in degrees) plus the sun's radius (0.267°).
  The board and the alerts use a 0.9 m Ku-band dish at 12 GHz: 1.24°. The calculator takes any dish and band.
- **Checked.** `tests/test_sunoutage.mjs` compares the browser code with the Python tool on six receiver and satellite
  pairs in both hemispheres (36 windows; start, peak and end within 5 s, closest approach within 0.001°). The Python
  tool was checked against a separately written calculator (Tehran windows and times agree). The calculator reproduces
  the spring 2027 window for Tehran and Yahsat 1A in `products/2026-10-07-sun-outage-season.md` (3–9 March).
- **The whole arc.** For a receiver looking at a satellite on its own meridian, the outage happens near local noon on the
  days when the sun's declination matches the satellite's apparent declination from that latitude. One band of latitude
  per hemisphere is in outage each day, the same for every slot (times shift with longitude); the board states today's
  band and the calculator draws the year.
- **Watch list.** Broad and public on purpose (major broadcast and weather slots over the Americas, Europe, the Middle
  East and Asia; capitals and large cities), so it reveals no watch focus. Slots are nominal; fleets change.

## Observed evidence

1. **NOAA SWPC solar radio data** (US public domain; registry `noaa-swpc`), read live by the board and at deploy:
   - Daily flux from the US Air Force Radio Solar Telescope Network at 245 MHz–15.4 GHz
     (`json/solar-radio-flux.json`, about 30 days). Each band's latest value is compared with its 30-day median.
     **Elevated** at 1.25× (about 1 dB more solar noise in the beam), **high** at 2× (3 dB). Provisional.
   - Fixed-frequency radio bursts (`json/edited_events.json`, type RBR: frequency in MHz, peak in sfu), last 7 days.
   - Radio alerts (`products/alerts.json`): 10 cm burst summaries (SUM10R), Type II and Type IV sweeps.
   Band matching: Ku and Ka downlinks use 15.4 GHz (else 8.8 GHz), C band 5.0 GHz, L band 1.4 GHz.
2. **Our aircraft GNSS data**: not yet in the alerts. A radio burst of thousands of sfu near 1.4 GHz raises the noise in
   GNSS receivers on the sunlit side. The check will compare, during each strong L-band burst, the number of aircraft
   with degraded accuracy per minute in sunlit hexes (minute table, `<day>.minute.parquet`) against the hour around it.
   **Validation first:** find L-band bursts of 1,000 sfu or more inside the data period (1 Oct 2025 onward) in NOAA's
   archived event lists, pre-register the comparison and its pass line, then run it. Until that passes, the board says
   only that a burst was observed.
3. **Outage reports**: `reports.json`, public sources only (operator and broadcaster notices, ITU Radio Regulations Board
   documents, news), each cited. A report inside its predicted window is consistent with a sun outage (the loss itself is
   then not evidence of interference); one outside is not explained by sun transit.

## Alerts

| Kind | Fires when | Level |
|---|---|---|
| burst-in-window | a radio burst at 4 GHz or above peaks inside a predicted window on the list | predicted and observed |
| bright-sun | the board: an outage on the list now while the Ku-band flux is ≥ 1.25× its median; deploy: a day with windows when that day's flux was | predicted and observed |
| l-burst | a burst at 1–2 GHz of 1,000 sfu or more (GNSS on the sunlit side) | observed |
| report | a curated report within 30 days, checked against its window | predicted and observed if inside, observed if outside |
| aircraft | (after validation) the aircraft check confirms a burst's effect | observed |

The board computes the first three live for the last 24 hours and shows the deploy-time "report" and "aircraft" alerts;
the feed carries all kinds from the last 7 days, one entry each, with stable ids so a redeploy doesn't repeat them.
The 1,000 sfu line is provisional: a round level far above the quiet sun at 1.4 GHz (about 60–90 sfu in October 2026),
to be tested against the aircraft data.

## Limits

- "Observed" here is the cause (how bright the sun is, and bursts), not a measured fade at a receiver. No public feed
  measures geostationary downlinks at receivers.
- The board uses one reference dish (0.9 m, Ku). Larger dishes fade deeper but for less time; C band longer.
- Receivers sit at city centres; slots are nominal (±0.1° station keeping moves window edges by up to a day).
- RSTN fluxes are daily noon values per observatory; NOAA edits event lists with some delay.

## Next

1. The aircraft check: archived bursts, pre-registration, run, then the "aircraft" alert.
2. Reports: add cited public reports as they appear (the 2022 Eutelsat statement on jamming from Iran is the kind of
   source; see the Weekly Topic draft).
3. The GEO threat board (proximity of inspector satellites) could share the board's sun-outage panel and slot list.
