# NISAR L-band lane

Finds places where NISAR's L-band radar picked up emissions inside its own receive band. It maps them, groups them into emitter sites across passes, and flags sites that are new or come back. This is Phase 7 (spaceborne GNSS), pulled forward on 21 Oct 2026.

It measures an **effect inside the radar's band**, not attribution. Every detection is a lead.

**Status:** built and passing its offline self-test. It has **not yet run on live data**. The Shiraz validation below comes first.

## What it measures

NISAR's L-band SAR listens in 1215–1300 MHz. Over most land it acquires in **20+5 MHz** mode, HH+HV:

| Sub-band | Covers | GNSS in band |
|---|---|---|
| A | 1219–1239 MHz | GPS L2 (1227.6 MHz) |
| B | 1291–1296 MHz | edge of Galileo E6 / QZSS L6 |

Other modes (40+5, 77, 20+20, 5+5) are handled from the product's mode tag. The whole range is also the L-band air-surveillance radar allocation.

An emitter in band adds noise-like, unpolarized power. That power lands equally in HH and HV, and HV is normally much weaker than HH, so the HV/HH ratio climbs well above what the ground produces. The detector works in four steps:

1. **Score.** It learns each scene's own HH → HV/HH relationship (median and spread per 1 dB HH bin) and scores each ~500 m cell's cross-pol excess.
2. **Shape.** It smooths along the radar range direction, because interference streaks run cross-track, and keeps connected regions above a hysteresis threshold.
3. **Weigh the evidence** for each candidate:
   - **Band-specific:** present in one sub-band and absent in the other. The ground looks the same in both; interference does not.
   - **Streak-shaped:** elongated along the range direction.
   - **Unpolarized change since the frame's previous pass:** HH and HV rose by about the same linear power. A rise in the surface's own HV/HH ratio (wetness, wind, vegetation) counts against it.
4. **Grade.** Candidates with no supporting evidence are dropped; the rest are graded LOW, MEDIUM or HIGH.

Across passes, detections within 25 km form a **site**. A site can be NEW, RETURNED or QUIET. When streak axes from two different viewing geometries cross at 20° or more, the site gets a **cross-fix**.

The band pattern is a hint, not an attribution:

- **A only:** consistent with a GPS L2 jammer.
- **B only:** points away from GPS.
- **A + B:** a wideband emitter.

## Run

```sh
pip install -r nisar/requirements.txt
cp nisar/config.example.json private/watch/nisar.json      # set your area there; private/ is gitignored
export EARTHDATA_TOKEN=...                                   # urs.earthdata.nasa.gov > Generate Token
cd nisar
python -m nisar_rfi run                       # last 10 days over the area; first run records a baseline quietly
python -m nisar_rfi run --start 2026-07-01 --end 2026-10-20 --seed   # backfill without alerts
python -m nisar_rfi inspect <GranuleUR or file.h5>    # what RFI fields a product carries and what the scorer sees
python -m nisar_rfi run --quiet               # one summary line, for logs others can read
```

Searching NASA's catalog (CMR) needs no login. Reading products needs an Earthdata token. Band A is read at full resolution (~1 GB per frame, streamed with byte-range reads) and averaged down; band B is small. Per-granule seconds are logged in the state file.

## Where things go

Everything the run writes is private: it is watch output.

| Path | What |
|---|---|
| `private/watch/nisar.json` | Area, thresholds, and the ignore list (known benign sites) |
| `private/nisar/state/` | Processed granules, detections, sites; `baselines/` holds each frame's last pass for the change check |
| `private/nisar/out/map.html` | Self-contained map: blobs by band, sites, cross-fixes, imaged frames with times (Central) |
| `private/nisar/out/latest.json`, `alerts.jsonl` | Last run and the alert log |
| `private/nisar/out/observations.jsonl` | One row per detection in the observation shape (lane `emitters`), ready for D1 |
| `private/nisar/out/*.geojson` | Detections and sites for GIS tools |

- **Pushes.** ntfy is used only when `NISAR_PUSH=1` and `NTFY_TOPIC` are set. Push text carries the site number and band only, with no place, coordinates or link.
- **Times.** Stored in UTC; the map and alert text show Central time with the zone named.

## Validate before trusting it

1. **Self-test (offline, also in CI).** Run `python tests/test_nisar.py` from the repo root. It builds four synthetic GCOV files in the real product layout:
   - two clean passes;
   - a band-A test jammer;
   - a band-B test radar;
   - a calm-water patch and a wind front as false-alarm bait.

   It then checks every outcome. Current result:
   - no false detections;
   - both emitters found in the right band;
   - NEW alerts on first appearance;
   - a cross-fix 0.9 km from truth (stated ±4.8 km).
2. **Shiraz known answer (live, public case).** NISAR saw a jammer ~50 km SW of Shiraz on 8 and 20 Jan 2026 and not on 27 Dec 2025 (GPS World, "Converging on the jammer", 18 May 2026). The granules are BETA products: track 157 ascending, frames 15–16, 20+5 MHz, HH+HV.

   From `nisar/`, run `python -m nisar_rfi run --config validation/shiraz.json --start 2025-12-20 --end 2026-01-21`.

   Expect a band-A site near 27.32°N 52.87°E on the January passes and nothing on 27 Dec. Write the result to `docs/validation/`.
3. **One provisional granule from your area.** Run `inspect` on it. The output shows:
   - the processor's `rfiLikelihood`;
   - whether mitigation was applied, and which algorithm;
   - the runconfig's RFI section.

**Why step 3 matters.** PROVISIONAL products (17 Jun 2026 onward) are processed with an RFI filter that can weaken the image signature this detector uses. If detections look thin against the processor's `rfiLikelihood`, the filter is the first suspect.

If the runconfig shows the processor ran **tone-rank**, the RSLC product carries a per-block RFI table: azimuth time × slant range, plus the fraction of pulses hit per frequency bin. That table survives filtering and names the frequencies. `product.rfi_block_grid` reads it.

## Limits

- **Snapshots.** Each spot is imaged every few days, so latency is days, not hours.
- **Blob-level location.** Within one pass the centroid can sit a few km toward the darker surface (sea) along the streak. A cross-fix needs two geometries.
- **GPS L1 is out of band.** L1-only jammers do not appear here; the ADS-B lane covers L1.
- **Tuned on synthetic data.** Thresholds in `detect` and `sites` were set on the self-test and will need tuning on the validation runs.

## Code

| File | Role |
|---|---|
| `cmr.py` | Catalog search and UMM parsing |
| `product.py` | HDF5 reads, local or streamed: identification, RFI metadata, block-averaged grids |
| `detect.py` | Scene relationship, scoring, candidates, evidence |
| `sites.py` | Sites, coverage, NEW/RETURNED/QUIET, cross-fixes |
| `bands.py` | Sub-band edges and GNSS overlap |
| `places.py` | Offline place wording from Natural Earth |
| `report.py` | Alerts, observations, GeoJSON, map |
| `pipeline.py` | One run |
| `__main__.py` | Command-line interface |

## Data and licences

| Data | Licence and use |
|---|---|
| NISAR | NASA/JPL-ISRO via ASF DAAC. NASA Earth science data, CC0 unless marked. Ingested; cite NISAR via ASF DAAC |
| Natural Earth | Public domain. Basemap land, countries and places |

Both are recorded in `registry/sources.csv`.

**Method references:**

- isce3 NISAR product specification and RFI detection code;
- NISAR Data User Guide (ASF);
- GPS World, "Converging on the jammer" (18 May 2026), for the streak geometry and the Shiraz case.
