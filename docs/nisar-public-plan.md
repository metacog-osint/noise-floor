# NISAR on the public map: plan

Approved by Tom on 28 Oct 2026, with decisions D1-D7 as recommended (below). Lane details: `nisar/README.md`. Validation: `docs/validation/nisar.md`.

## Why

The NISAR outputs were kept private until validated. No licence requires that: NISAR is NASA-ISRO data via ASF DAAC, NASA open data, CC0. Validation now stands at:
- one positive control passed (broadband detector, documented L1/L2/L5 jamming area, 12 of 13 passes);
- the Shiraz known answer not confirmed;
- announced US tests not seen;
- position accuracy unmeasured;
- a clean off/on pattern at the Pankovo site on Novaya Zemlya: absent on 29 dual-pol passes 17 Jun - 5 Oct 2026, present on every one from 7 to 19 Oct.

Published as leads with that status beside them, the sites are useful and honest about their limits.

## What a visitor sees

- **Map page:** a third layer, "L-band emitters (NISAR radar)", next to Spoofing and CYGNSS.
- **One dot per site,** with a ring at the site's position spread (typically 10-25 km), so nobody reads it as a pinpoint. Colour by band: 1219-1239 MHz (contains GPS L2) or 1291-1296 MHz.
- **Time.** The layer shows sites with a detection in the 30 days up to the selected day. NISAR revisits every few days and ASF posts about 2 days after acquisition.
- **Tooltip:** place name; frequencies; first and last seen; passes seen out of passes that covered it; viewing geometries; and "A lead, not attribution: something transmitted here inside NISAR's receive band." Coordinates appear only in the tooltip and downloads.
- **Layer note:** the validation status in one sentence, linked to the Validation page.
- **Wording:** effects, not causes. No site is labelled a jammer, whatever its frequency.

## What is published (the gate)

- A site appears once it has **MEDIUM or HIGH detections on at least two different passes**.
- Frame-wide detections (no usable position) and sites on an area's ignore list never count.
- Private: alert history and NEW/RETURNED/QUIET state, LOW detections, the vessel page, and any area marked `"public": false`.
- Each site record carries its qualifying detections (time, track and direction, band, frequency runs, share of pulses, blocks, polarizations, confidence, granule ID so anyone can re-check against ASF) and every pass that covered it.

## Build steps

| # | Step | Status |
|---|---|---|
| N1 | `python -m nisar_rfi export` writes `<day>.nisar.json` from every public area (`nisar/nisar_rfi/public.py`; test `nisar/tests/test_public.py`) | Done 28 Oct (branch) |
| N2 | `run_daily.cmd` runs the export after the area runs and uploads it to the `nisar-data` release | Done 28 Oct (branch); release created on first upload |
| N3 | `tools/site_layers.py` gains a `nisar` kind (`site/data/nisar/<day>.json`, `index.json`); `site_src/map.html` and `map.js`: checkbox, loader, drawing, tooltip, note | To do |
| N4 | Pages: Methods (the layer), Validation (pointer to the layer, results unchanged), Guide (replace "its maps stay private until it passes"), Data (download and licence), `lanes.json`, `registry/sources.csv` | To do |
| N5 | Local build and look; CI; merge to `main`; check the live map | To do |

The deploy at 12:40 UTC picks up the file from the 12:00 UTC (7:00 AM CDT) run the same day.

## Decisions (Tom, 28 Oct 2026)

| # | Decision |
|---|---|
| D1 | The two NISAR areas are public coverage: the Baltic and Nordic region (9-31°E, 53-66°N) and the Novaya Zemlya test sites (51.0-57.5°E, 70.8-74.2°N). Any future narrow area stays private with `"public": false`. |
| D2 | All sites are published the same way, allied radars included (the Baltic set has repeat sites at Trondheim/Værnes, north of Jena and offshore NE of Umeå), with effect-only wording. Filtering by country would read as attribution. |
| D3 | Gate as above. Tighten to two viewing geometries if the map looks noisy. |
| D4 | New release `nisar-data` in this repo. |
| D5 | Licence line: "Derived from NASA-ISRO NISAR (ASF DAAC), NASA open data, CC0". |
| D6 | Built on branch `nisar/novaya-zemlya`, merged to `main` after Tom has looked at a local build. |
| D7 | The Baltic area reads every pass. Its QA screen (read only if the processor's score is at least 10, or every 3rd pass) was dropped, and the state was rebuilt with every pass read. |

**Why D7.** Passes scoring under 10 that were read anyway had a MEDIUM/HIGH detection 40% of the time (30 of 75), against 48% (142 of 297) for passes scoring 10 or more. The score is a frame-wide maximum of the interference-to-signal ratio and barely predicts emitters. The 114 passes it skipped would have hidden about 45 passes with detections.

## Open items

- **One emitter, two sites.** Site matching joins a detection to the nearest site within 25 km. At Pankovo, the 15 Oct descending fix landed nearer an older site about 25 km north of the main one, so one emitter shows as two sites. Consider re-centring sites, or matching on frequency signature as well as distance, before the layer goes live.
- **1221.0 MHz (checked 28 Oct).** It isn't an instrument spur or a Russian signature. Detections touching 1220.8-1221.8 MHz are common at the US validation sites: 56 near Connecticut and New York, 48 in Hawaii, 36 around Michigan and Ontario, 25-34 on the Gulf Coast. They're absent at two US sites with 101 and 571 detections, so it isn't common to every pass. That fits L-band air-surveillance radars (unverified). The Novaya Zemlya summer cluster at 1221 MHz is most likely radar activity, not GNSS interference.
- **Place names.** The offline gazetteer (Natural Earth populated places) has no towns on Novaya Zemlya, so sites there are described by coordinates. The map should fall back to the area name in the tooltip's headline and keep coordinates on the detail line.
- **"Seen on X of Y passes"** must be counted inside the map's window from `coverage_from` on: `sites.prune` keeps only each site's latest 60 covering passes.
- **History starts** on 22 Sep 2026 in the Baltic area and 17 Jun 2026 at Novaya Zemlya. The Baltic backfill to 17 Jun (about 75 GB) is still held.
