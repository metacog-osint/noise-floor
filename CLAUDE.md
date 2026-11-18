# Noisefloor

GPS/GNSS interference, spoofing, space-receiver RFI and space-weather measurements from publicly available data (TIC
program; product name **Noisefloor**, one word, Tom 27 Oct 2026; repo and folder stay `noise-floor`; public repo
https://github.com/metacog-osint/noise-floor). Merged with Interference Watch on 14 Oct 2026.

**Slimmed 18 Nov 2026** from 33 KB to the durable rules. Full earlier text: `.claude/notes-archive-2026-11-18.md` in
the main checkout (`D:\Projects\noise-floor`, gitignored). **Current state and open items: `.claude/HANDOFF.md`** in
the main checkout; read it before starting work. Dated history and finished work: `HISTORY.md`. Plan and open
decisions: `docs/DESIGN.md` ("Merged plan" section wins); sources, licences, methods:
`docs/research/2026-10-06-sources.md`. **Also read `CLAUDE.local.md` if present** (private notes, kept out of the
repo). Keep this file under 12 KB (global rule); state and narrative go in the handoff, shas in git.

## Hard rules
- **The repo is public.** No employer names, old-project names, credentials, personal paths or watch configuration
  (AOIs, keywords, watch lists, alert history) in tracked files; those go in `CLAUDE.local.md`, `private/` (gitignored)
  or the private store. Pre-commit hook `tools/check_public.py` and CI (`FORBIDDEN_TERMS` secret) block a private term
  list. Exception (Tom, 28 Oct): NISAR areas that `nisar_rfi export` publishes are public coverage
  (`docs/nisar-public-plan.md` D1); an area with `"public": false` stays private.
- **Nothing from Tom's employer or its projects** (details in `CLAUDE.local.md`). Methods may be re-derived.
  emso-watch is Tom's own code and may be ported.
- **Licence-clean sources only** in anything published; record each source's licence before it feeds a layer.
  Non-commercial licences are allowed (Tom, 29 Oct; Noisefloor is non-commercial) with the credit they ask for; only
  terms forbidding republishing keep a source out. Rows still `visual-only` under the old rule are reviewed one at a
  time. adsb.lol-derived downloadable data is ODbL, with attribution on every map.
- **The main checkout stays on `main`** (15 Nov). The PC's scheduled tasks run its files, so a branch checked out there
  is what runs. Work in a worktree. `collectors/run_daily.cmd` fast-forwards main when it has no tracked changes and
  warns in `data/logs/collectors.log` on any other branch.
- Free tier only; ask before anything billable. **Commits and pushes:** commit finished steps and push any commit that
  passes the pre-commit checks (standing permission, Tom 14 Oct). Creating repos or services, changing deploy
  settings, and publishing outside this repo (posts, products, the subdomain) need Tom's OK each time.
- **Pushing `main` deploys:** `deploy-site.yml` uploads `site/` to Cloudflare Pages after CI passes on a push to
  `main` (fallback `tools/cf_pages_kick.py`). Check the live page after site changes.
- Store UTC. Site shows UTC with the visitor's zone alongside, always named; Time button `site_src/tic-time.js`
  (hub's shared module, v1.3) picks any zone and 12/24 h. Messages to Tom use Central time.
- Cite sources; flag anything unverified (Tom is a domain expert).
- **Boundary with Orbit (Tom, 16 Nov):** Orbit owns objects in orbit, Noisefloor owns signals; sun outages stay here.
  **Noisefloor is the suite's source for PNT and space-weather data** (Tom, 15 Nov), read from its published files.

## Stack and commands
- Python; static site. `site/` is generated: edit `site_src/` (pages, `lanes.json`) and run
  `python tools/build_site.py`; Sources page from `registry/sources.csv`. CI fails if `site/` is out of step.
- CI runs each `tests/test_*.py` as a plain script with only `requirements.txt` and `nisar/requirements.txt`.
- Doctrine kit `doctrine/kit/` is vendored from `D:\Projects\tic-doctrine`: never edit here; change the kit and run
  `python D:/Projects/tic-doctrine/tools/sync.py D:/Projects/noise-floor`. CI runs `doctrine/kit/tic.py kitcheck` and
  `registers doctrine`. Area-specific warning problems stay private.
- `tools/heavy_lock.py`: machine-wide lock for heavy local jobs. Scheduled workflows stop after 60 days without a
  push; cron runs hours late, so tic-dispatch starts `cosmic2.yml` at :50 past 04-08 and 10-13 UTC.

## Daily pipeline and site
- `.github/workflows/daily.yml` runs `pipeline/daily_job.py` 05:40 UTC (and 12:40): each new adsb.lol day to release
  `pnt-data-YYYY-MM` (ODbL; `<day>.map.json` last, as the done marker), plus `<day>.spoof.json`,
  `<day>.spoof-targets.json`, `<day>.loss*.parquet` (position loss) and `<day>.coverage.json` (covered res-4 cells per
  res-2 region, `thin` < 10; `tools/feeder_coverage.py`), then calls `deploy-site.yml`, which adds release files to
  `site/data/` (`site_days.py`, `fetch_release_files.py` cached, `site_layers.py`, `spoof_site.py`, `swx_site.py`).
  Rerun: Actions → daily (`days`, `force`, `reanalyse`). `backfill.yml` (`start`, `end`, `spoofing_only`) filled
  1 Oct 2025 on. Source gaps: no archive 31 Dec 2025, 6 May 2026; 5 May empty; 7 May ~6 h.
- `tools/board.py` builds `board.json` at deploy (failing sources go in `problems`) and `brief`, which the hub
  quotes. **Brief wording (Tom 31 Oct, 16 Nov):** clear to a newcomer; names the measure ("the share of aircraft with severe GPS error was above/near/below its usual level",
  against the 30-day median, never "rose"/"fell"); "GPS interference started in …"; under the 3-cell mark a region
  "fell below jamming scale"; "ended" only with 500+ aircraft-cells (and half its usual number) on each of the last
  7 days and a 7-day severe share <= 1% (`ended_check`). Rules in `brief()`'s docstring.
- **Site design (Tom, 27 Oct):** tokens in `site_src/style.css`; tabs in `build_site.py` (`TABS`, `SECTIONS`); tool
  pages: `.page-head`, explanations in one `<section id="howto">` at the end. **Wording:** "GPS interference"; "severe GPS error
  (worse than 93 m)"; "cell", never "hex"; dates "26 Oct 2026", times "14:00 UTC (9:00 AM CDT)"; place names, with
  coordinates only in tooltips and downloads; effects, not causes; no internal words ("lane", "phase") outside
  Methods, Data and Roadmap. Validation results stay word for word. `site_src/guide.html` is the plain-language guide.
- The degraded share can't see aircraft that drop GNSS position: check position loss
  (`tools/position_loss.py`, `docs/validation/position-loss.md`) before reading any share trend.

## Feed (`tools/feed_v2.py`, `site/data/feed.geojson`, contract `tic-feed/2`)
- Written from the board at deploy; a failure only skips the feed. Every item is an observation.
- Day items: `data_as_of_precision: "day"`, `data_as_of` at `T00:00:00Z` (kit 0.5.6 rule); the header stays
  `T23:59:59Z`. The vendored kit (0.3.3) doesn't know the field; it isn't rejected.
- **Events (16 Nov, suite review):** every major and notable jamming event, no cap; majors `tier: anomaly`, notables
  `routine` (Tom's choice). MultiPolygon of H3 res-2 regions, `data_as_of` = end of last UTC hour with `period`,
  measure `peak_severe_share_pct`. Country tags from each cell's corners, centre and res-5 children plus
  `place_country` (rings to 25 km for coastal towns).
- **Names (Tom 17-18 Nov; rule in `tools/area_names.py`):** a listed place within 150 km in a country the area
  covers; else the point's country, or the land-majority one when half the cells' samples are land; else its
  Natural Earth sea (`tools/sea_areas.py`). Countries and seas carry `near_ref` ("220 km W of Tbilisi"); events
  of 10+ regions over 5+ countries read "across N countries, centred ...". Full words in `where` (board rows, map
  events files, spoofing rows). Cell countries: `site/data/cell_countries.json` (rebuild on kit border changes).
- Spoofing items: up to five new places and up to five `noisefloor-spoof-region-above-<day>-<n>`; ids
  `noisefloor-below-`/`noisefloor-ended-`. Space weather items are routine, no `baseline_ref` (see below).

## Lanes
| Lane | What and where | Rules and gotchas |
|---|---|---|
| ADS-B jamming | adsb.lol archive (ODbL), `pnt_analysis.py`, `tools/events.py` (graded v1.1; EASA FIR tables drive rule D1) | Severe share vs 30-day median |
| ADS-B spoofing | `tools/spoof_day.py` (v0.6.1 default: rule A for A2 only >= 36,000 ft; `docs/validation/spoofing-v06*.md`), `spoof_summary.py`, `spoof_site.py` | Test detector changes per `docs/spoofing-light-plan.md` (day caches, shadow variants, `spoof_variant.py`, `spoof_same.py`; compare `cpu_seconds`, not wall). `spoof-variant.yml` scores the 12 held-out days (each run Tom's call); caches hold ICAO addresses, so they sit in the PRIVATE `spoof-cache` release of noise-floor-archive (`SPOOF_CACHE_TOKEN`); only aggregates leave. Region "above" = 2x usual and >= 5 aircraft-hours over (`REGION_MIN_OVER`, pre-registered). A region above inside an announced US GPS test (`faa_gps_tests.json`) names the test, tier unchanged |
| GEO region | Orbit's published `<day>.geo-region.json` (`geo_region.py pull --from-orbit`, no Space-Track request); globe `site_src/globe.js`, `tools/geo_globe.py`, callouts `geo_callouts.py` (C3-C7 on) | Moving to Orbit (`doctrine/geo-move-plan.md` in Orbit). Plan `docs/geo-globe-plan.md`. Footprints wait on licences |
| NISAR | `python -m nisar_rfi export`, `nisar/run_daily.cmd` (extra areas `private/watch/nisar.d/`), `nisar-data` release, then deploy | Plan `docs/nisar-public-plan.md`. Each detection is a lead, not attribution |
| Sentinel-6A `s6`, COSMIC-2 `cosmic2`, SMAP `smap`, Sentinel-1 `s1` | Daily from the PC 06:30 collectors task; `<day>.<layer>.json` to `<layer>-data` | S6 places regions, not sites; COSMIC-2 low latitudes only; SMAP saturates in crowded regions; S1 shows C-band radar by region, never GPS interference. Neither S6 nor COSMIC-2 rises on event days (rule S3), grading stays v1.1. Plan `docs/space-sensors-plan.md` |
| Sentinel nav receivers (step E) | `tools/sentinel_gnss.py`, index `sentinel_rfi.py` (frozen), `sentinel_daily.py`; CDSE S3 keys in user env vars; private products only | Regional sensor ~2,000 km, not a cell map. **E2.1 in the products** (Tom's yes 16 Nov; `docs/validation/sentinel-gnss-e21.md` section 3); `--index e2` for comparison. BeiDou-3 C59/C60/C38-40 stay out (`FILL_LOAD`). |
| Multi-GNSS bands | `docs/multi-gnss-plan.md`; `station_bands.py`, `sentinel_bands.py` | East Asia L2C/E5a slid 1.2-2.2 dB in a year, cause unknown |
| COSMIC-2 limb S4 | `cosmic2.yml` → `cosmic2_job.py`, `cosmic2_s4.py`; release `swx-data-YYYY-MM` | Always labelled "limb S4 measured along radio-occultation paths, which reads higher than a ground receiver's S4"; never compared with ground S4 alert levels. Validated 15 Nov; map and feed approved 16 Nov |
| Ground ROTI | `ground-roti.yml` → `ground_roti_job.py` (17 IGS stations, BKG anonymous), `swx-data-YYYY-MM` | Labelled "ROTI, a measured TEC fluctuation index at fixed stations": a proxy, never an S4 value. Validated 15 Nov; approved 16 Nov |
| Space weather on site/feed | `swx_site.py`; map `ls=1`, `rt=1`; feed up to 5 limb S4 cells + one item per ROTI station | Shading steps are display choices, never alert levels. All routine, no baseline_ref; a higher tier needs a stated baseline and Tom's yes. `NF-EEI-5`, NCF `space-weather` |
| CYGNSS | `cygnss_daily.py` to `cygnss-data`; ~6 days behind | |
| Military air | `milair.py`, `docs/validation/milair.md` | Lower bounds; routine |
| Maritime / AIS | `docs/maritime-plan.md`; `ship_detect.py`, `s2_check.py`; Digitraffic, aisstream and BarentsWatch collectors | Ships: `--min-contrast 10 --ghosts drop --landmask`. Data private in `data/ais/`; publishing waits on terms (`barentswatch-ais`, `dma-ais`) |
| `watch.py` | Cloudflare Radar, Page watch | Private digests |

Also `tools/sun_transit.py` (sun outages) and `products/` (dated). Failed probes: ALOS-2, SMOS.

## How other programs use Noisefloor
- **COP** reads the feed; its freshness is the newest item's `data_as_of` (Noisefloor windows 36 h late, 72 h stale).
- **Hub** quotes `brief`. **Orbit** supplies the GEO region files; Noisefloor's gp query (`orbit_busy`) defers to
  Orbit on the shared Space-Track account. Downstream users read the releases (private details in `CLAUDE.local.md`).
