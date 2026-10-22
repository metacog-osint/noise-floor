# NISAR L-band lane

Finds places where NISAR's L-band radar picked up emissions inside its own receive band. It maps them, groups them into emitter sites across passes, and flags sites that are new or come back. This is Phase 7 (spaceborne GNSS), pulled forward on 21 Oct 2026.

It measures an **effect inside the radar's band**, not attribution. Every detection is a lead.

**Status (21 Oct 2026):** two methods.

- **Table method (default for PROVISIONAL products):** reads the RSLC processor's own per-block RFI tables. It has run on live data (see Validation).
- **Image method (BETA products only):** scores cross-pol excess in GCOV images. It **failed** the Shiraz known-answer test on live BETA data, so treat its output as unvalidated.

## What NISAR can see

NISAR's L-band SAR listens in 1215–1300 MHz. Over most land it acquires in **20+5 MHz** mode, HH+HV ([ASF frequency table](https://nisar-docs.asf.alaska.edu/frequencies-polarization)):

| Sub-band | Covers | GNSS in band |
|---|---|---|
| A | 1219–1239 MHz | GPS L2 (1227.6 MHz) |
| B | 1291–1296 MHz | upper edge of Galileo E6 / QZSS L6 |

Other modes (40+5, 77, 20+20, 5+5) exist. The table method reads each pass's real frequency axis, so it doesn't depend on the mode. The whole range is also the L-band air-surveillance radar allocation. GPS L1 is out of band, so L1-only jammers don't appear.

## Table method

PROVISIONAL products (acquired from 17 Jun 2026) are processed with RFI **tone-rank** detection and mitigation. Along the way the processor writes, into each RSLC, a grid of analysis blocks (azimuth time × slant range) holding:

- **`interferenceSignalRatio`:** RFI power over signal power per block;
- **`signalMean`:** the estimated signal power;
- **`hitCount`:** the share of pulses with RFI at each frequency bin.

Sources: isce3 `isce3/signal/rfi_tone_rank.py` and `nisar/workflows/focus.py`.

These tables are computed on the raw data **before** mitigation, so the image filter can't hide what they record. They are small next to the image: 70–130 MB read per pass against 6–14 GB RSLC files.

**Two tiers per pass:**

1. **Tier 0, every pass (~0.1 MB):** the processor's `rfiLikelihood` per channel, from the GCOV's QA statistics file.
   - For tone-rank it is the **maximum** interference-to-signal ratio over blocks (isce3 `focus.py`, `rfi_likelihood = np.max(isr)`), not the 0–1 fraction of the older algorithms.
   - Because it is a maximum, one block with a near-zero signal estimate (open water, gaps) can push it to 10^11 or more. So it is only a coarse screen.
   - Passes with every channel below `screen.min_score` (default 10) skip tier 1, unless their frame is due a look (every `screen.every` passes, default 3).
   - Screened passes still count as clean coverage for the site logic.
2. **Tier 1, flagged passes:** read the RSLC tables and orbit (`tables.py`), then detect (`tabdetect.py`):
   - Score each block by the share of pulses hit at its most-hit frequency bin, ignoring the radar's own tones. **1233.125 MHz** and **1296.002 MHz** were present in every pass we checked, in two regions, and are excluded with ±0.15 MHz.
   - Drop degenerate blocks, where the signal estimate is below 1/1000 of the median.
   - Group hot blocks (≥ 50% of pulses hit) across both polarizations into candidates.
   - Locate each candidate at the centroid of its blocks within 6 dB of the peak RFI power (ratio × signal mean). Turn that time and range into latitude and longitude from the orbit (`geoloc.py`: zero-Doppler, WGS84, configurable terrain height).
   - Report the frequency runs that were hit and the GNSS signals they fall in.

**Why one pass gives a position.** The receive beam confines an emitter's interference to part of the swath in range: about 14 of 53 range blocks on the strongest row at Shiraz. The azimuth beam confines it to a few seconds along track. So a detection is a point with an extent, not a streak needing a second geometry.

**Data volume.** Measured over the private watch box (30 days to 21 Oct 2026):
- ~14 passes a day and ~24 GB of GCOV files a day.
- Tier 0 is ~1.4 MB a day.
- Tier 1 is at most ~1.4 GB a day if every pass is read. With the default screen, about 78% of passes were read in that sample: ~1 GB and ~6–7 minutes a day.
- A tier-1 read takes about 30–40 s. The run resolves the Earthdata redirect once (the signed URL is never logged), walks ~8 MB of HDF5 metadata, then fetches the hit arrays by concurrent byte-range requests.

## Run

```sh
pip install -r nisar/requirements.txt
cp nisar/config.example.json private/watch/nisar.json      # set your area there; private/ is gitignored
# EARTHDATA_TOKEN must be set (urs.earthdata.nasa.gov > Generate Token; user tokens last 60 days)
cd nisar
python -m nisar_rfi run                       # last 10 days over the area; first run records a baseline quietly
python -m nisar_rfi run --start 2026-07-01 --end 2026-10-20 --seed   # backfill without alerts
python -m nisar_rfi tables <GranuleUR> [--height 1500]   # table method on one pass, printed, nothing saved
python -m nisar_rfi inspect <GranuleUR or file.h5>    # RFI fields a GCOV carries (also reads the full image)
python -m nisar_rfi run --quiet               # one summary line, for logs others can read
```

**Config keys for the table method:**
- `method`: `tables` or `image`. The default is `image` if any collection is BETA, otherwise `tables`.
- `screen.min_score`, `screen.every`.
- `tables.height_m`: terrain height for geolocation. A wrong height shifts positions across track by about h / tan(incidence), roughly 2 km per 1.5 km of height.
- `workers`: parallel table reads, default 4.
- `cache_tables`: keep each pass's tables (3–7 MB compressed) in `state_dir/cache/`, so detection can be re-run offline.

## Where things go

Everything the run writes is private: it is watch output.

| Path | What |
|---|---|
| `private/watch/nisar.json` | Area, thresholds, and the ignore list (known benign sites) |
| `private/nisar/state/` | Processed granules (with tier, screen reason and MB read), detections, sites, per-frame rotation counters |
| `private/nisar/out/map.html` | Self-contained map: detections, sites, imaged frames with times (Central) |
| `private/nisar/out/latest.json`, `alerts.jsonl` | Last run and the alert log |
| `private/nisar/out/observations.jsonl` | One row per detection in the observation shape, ready for D1 |
| `private/nisar/out/*.geojson` | Detections and sites for GIS tools |

- **Pushes.** ntfy is used only when `NISAR_PUSH=1` and `NTFY_TOPIC` are set. Push text carries the site number and band only, with no place, coordinates or link.
- **Times.** Stored in UTC; the map and alert text show Central time with the zone named.

## Validation

1. **Offline tests (also in CI):** `python tests/test_nisar.py` from the repo root.
   - `test_tables.py`: geolocation round trip on a synthetic orbit; a synthetic L2 emitter found within 3 km, while the instrument tones and degenerate blocks raise nothing; QA parsing; screening and rotation.
   - The image self-test on four synthetic GCOV files.
2. **Shiraz known answer, BETA, image method: failed (21 Oct 2026).**
   - GPS World ("Converging on the jammer", 18 May 2026) reports a jammer about 50 km SW of Shiraz (27.32°N 52.87°E) on 8 and 20 Jan 2026, absent on 27 Dec 2025. The data is track 157 ascending, frames 15–16.
   - The image method made 56 detections at 30 sites over the six passes, 21 of them on 27 Dec. None was within 50 km of the jammer.
   - The processor's own score on those BETA passes flags band B heavily (28–61% of blocks on 8 Jan) and band A barely. So check the band assumption before re-tuning.
   - BETA products carry no per-block tables (their RFI algorithm is ST-EVD, with mitigation disabled), so the table method can't run on them.
3. **Shiraz area, PROVISIONAL, table method:** see `docs/validation/nisar.md`.

## Limits

- **Snapshots.** Each spot is imaged every few days, so latency is days, not hours.
- **Positions are block-scale.** Blocks are about 3 km in range and 1–2 km along track. The centroid sits where received power peaks, which a strong emitter's sidelobes can smear. Terrain height matters (see `tables.height_m`).
- **Frame-wide interference.** A strong emitter can light up most of a frame; such candidates are flagged `widespread`, and their position is the power peak only.
- **The instrument-tone list is empirical.** Two tones from five passes in two regions. Re-check it if detections cluster at one frequency everywhere.
- **The table method needs tone-rank,** so it covers PROVISIONAL products only.
- **Broadband jamming may be missed.** Tone-rank flags loud narrowband tones. A noise jammer that raises the whole spectrum may not register, so the table method is strongest on CW and narrowband emitters. This is a hypothesis from a control-area run (see `docs/validation/nisar.md` §4).
- **Radars hop.** Long-range L-band radars hop across 1215–1400 MHz, and NISAR's 25 MHz of slices catch only part of that. A quiet radar site is expected often.

## Code

| File | Role |
|---|---|
| `cmr.py` | Catalog search, granule lookup and UMM parsing |
| `qa.py` | Tier 0: per-channel processor scores from the QA files |
| `tables.py` | Tier 1 reads: RSLC tone-rank tables and orbit; local cache |
| `geoloc.py` | Radar coordinates to latitude and longitude (and back) from the orbit |
| `tabdetect.py` | Table method: block scores, instrument tones, candidates, frequency signatures |
| `product.py`, `detect.py` | Image method: HDF5 reads and cross-pol scoring (BETA) |
| `sites.py` | Sites, coverage, NEW/RETURNED/QUIET, cross-fixes (image method) |
| `bands.py` | Sub-band edges and GNSS overlap |
| `places.py` | Offline place wording from Natural Earth |
| `report.py` | Alerts, observations, GeoJSON, map |
| `pipeline.py` | One run: search, screen, read, detect, sites, outputs |
| `__main__.py` | Command-line interface |

## Data and licences

| Data | Licence and use |
|---|---|
| NISAR | NASA/JPL-ISRO via ASF DAAC. NASA Earth science data, CC0 unless marked; the CMR collections carry no use constraint (checked 21 Oct 2026). Ingested; cite NISAR via ASF DAAC |
| Natural Earth | Public domain. Basemap land, countries and places |

Both are recorded in `registry/sources.csv`.

**Method references:**

- isce3 (`rfi_tone_rank.py`, `focus.py`, the NISAR product specifications);
- the [NISAR Data User Guide (ASF)](https://nisar-docs.asf.alaska.edu/), including the provisional known issues on the RFI filter;
- GPS World, "Converging on the jammer" (18 May 2026), for the Shiraz case.

If the work is shown publicly, credit @auonsson's post (20 Oct 2026) as the prompt for the idea.
