# Noisefloor: project notes for Claude

Product name: **Noisefloor**, one word (Tom, 27 Oct 2026; it was "Noise Floor" from 14 Oct). Repo and local folder stay `noise-floor`.

Tom's own project under **The Intelligence Company**, to be hosted on theintelligence.company. Restarted 6 Oct 2026.
**Merged with Interference Watch on 14 Oct 2026.** The "Merged plan" section at the end of `docs/DESIGN.md` decides what wins.
Read `docs/DESIGN.md` (the plan and open decisions) and `docs/research/2026-10-06-sources.md` (sources, licences, methods).
**Also read `CLAUDE.local.md` if present.** It holds private notes that are deliberately kept out of this public repo.
**`HISTORY.md`** holds dated history, measurements and finished work moved out of this file (5 Nov 2026). It is not
loaded automatically; read it when you need the background.

## Hard rules
- **This repo is public:** https://github.com/metacog-osint/noise-floor (created and first pushed 14 Oct 2026; CI checks the private
  term list from the `FORBIDDEN_TERMS` secret). No employer names, old-project names, credentials, personal paths or watch configuration
  (AOIs, keywords, watch lists, alert history) in tracked files. Those go in `CLAUDE.local.md`, `private/` (gitignored)
  or the private store. The pre-commit hook `tools/check_public.py` enforces a private term list.
  **One exception (Tom, 28 Oct 2026):** the NISAR areas that `nisar_rfi export` publishes are public coverage
  (`docs/nisar-public-plan.md`, decision D1). Any area whose config says `"public": false` stays private.
- **Nothing from Tom's employer or its projects.** No code, names, accounts or infrastructure (details in `CLAUDE.local.md`).
  Methods may be re-derived. emso-watch is Tom's own code and may be ported.
- **Licence-clean sources only** in anything published. Every source is recorded with its licence before it feeds a layer.
  **Non-commercial licences are allowed (Tom, 29 Oct 2026):** Noisefloor is non-commercial, so NC sources (airplanes.live,
  adsb.fi, OpenSky, Stanford RFI, Cloudflare Radar, OONI, GFW and others) may be ingested once their terms are recorded,
  with the credit they ask for. Only sources whose terms forbid republishing stay out. Rows still marked `visual-only`
  under the old rule are reviewed one at a time before they change; the ODbL rule below still applies to the hex data.
- adsb.lol-derived downloadable data is published under ODbL, with attribution on every map.
- **The main checkout stays on `main` (15 Nov 2026).** The PC's scheduled tasks (daily collectors, NISAR, AIS, the ESA
  capture) run the main checkout's own files, so a branch checked out there is what runs: from 5 to 15 Nov a docs
  branch did. Work in a worktree and never switch the main checkout's branch. `collectors/run_daily.cmd` fast-forwards
  main from GitHub when it has no tracked changes, and logs a warning in `data/logs/collectors.log` on any other branch.
- Free tier only. Ask before anything billable. **Commits and pushes:** commit finished steps, and push any commit that passes
  the pre-commit checks (standing permission, Tom, 14 Oct 2026). Creating repos or services, changing deploy settings, and
  publishing anything outside this repo (posts, products, the subdomain) still need Tom's OK each time.
- Store UTC. On the site, show UTC with the visitor's own time zone alongside, always named; the Time button
  (`site_src/tic-time.js`, The Intelligence Company's shared module, v1.3) lets them pick any zone and a 12/24-hour
  clock (Tom, 27 Oct 2026). Messages to Tom use Central time.
- Tom is a domain expert (intel, SDA, weather): cite sources and flag anything unverified.

## Doctrine kit (30 Oct 2026)
- `doctrine/kit/` is a vendored copy of The Intelligence Company's shared kit (`D:\Projects\tic-doctrine`): never edit it
  here; change the kit and run `python D:/Projects/tic-doctrine/tools/sync.py D:/Projects/noise-floor`. CI runs
  `doctrine/kit/tic.py kitcheck` and `registers doctrine`.
- `doctrine/` holds Noisefloor's requirements, warning problems and indicators, assumptions, function map, source
  extras (grades, independence groups, health probes) and method summary. Area-specific warning problems stay private.
- `tools/feed_v2.py` writes `site/data/feed.geojson` (feed contract `tic-feed/2`) from the status board at deploy;
  `board.py` calls it, and a failure only skips the feed. Every item is a measurement (kind observation) for now.
  Every item but an event covers a whole UTC day, so it carries `data_as_of_precision: "day"` with `data_as_of` at
  `T00:00:00Z` (kit 0.5.6 rule; was `T23:59:59Z`, which COP showed as "5:59 PM CST"; 16 Nov 2026). The feed header's own
  `data_as_of` stays at `T23:59:59Z`. The vendored kit (0.3.3) doesn't know the field yet; it is not rejected.
  **Events (16 Nov 2026, suite review Mistakes 3 and 5):** every major and notable jamming event goes in (no cap):
  majors `tier: anomaly`, notables `routine` (Tom's choice; the summary says they are above their own baseline but
  below the major grade). Each is a MultiPolygon of its H3 res-2 regions (`precision_class: area`), `data_as_of` is
  the end of its last UTC hour with `period {start, end}`, and its measure is `peak_severe_share_pct` (with `unit`;
  it was misnamed `peak_degraded_aircraft`). **Country tags** come from each cell's corners, centre and res-5 children
  plus the named place's country (`place_country`, rings out to 25 km where the kit's outlines miss a coastal town).
  **Side effect on COP:** its freshness is the newest item's `data_as_of` (Noisefloor's windows: 36 h late, 72 h stale), so
  the day's items now read about a day older and may show "late" for part of each day until COP treats `day` items
  as end-of-day for freshness or widens the windows.

## Products and tools
- `products/`: written products, dated. First: `2026-10-07-sun-outage-season.md` (Weekly Topic draft, not yet published).
- `tools/sun_transit.py`: sun-outage windows for GEO satellites from fixed receivers (`--daily`, `--start`, `--end`,
  `--threshold`).
- `tools/check_public.py`: pre-commit check for private terms.
- **Maritime lane (planned 23 Oct 2026; M1 started 24 Oct):** read `docs/maritime-plan.md` first (sources, detectors D1–D13, database, validation,
  build steps M0–M7, open decisions). Private handoff and watch configuration are listed in `CLAUDE.local.md`.
  `tools/ship_detect.py` finds ships in Sentinel-1 GRD (Planetary Computer, anonymous); boxes come from private config.
  `tools/s2_check.py` checks its detections against Sentinel-2 (`docs/validation/ships-s1.md`: at the default k = 6 most are clutter;
  use `--min-contrast 10 --ghosts drop --landmask` for better precision).
- **GEO globe (planned 27 Oct 2026, Tom approved every idea):** read `docs/geo-globe-plan.md` first (Space-Track data
  and credentials, the region and membership events, the 3D viewer, callouts C1–C8 to validate on history, footprints
  and their licence checks, build steps G1–G5, all built). `tools/geo_region.py` (Space-Track gp daily in `daily.yml`;
  gp_history held once in `data/geo/region/history/`, never re-fetched; `replay` rebuilds the day files offline;
  from 16 Nov 2026 its gp query skips when Orbit, on the same Space-Track account, queried under an hour ago (Orbit's
  public snapshot, `maneuvers.read_at`), when that snapshot can't be read, or from :38 to :05 around 00, 06, 12 and
  18 UTC, Orbit's start times: `orbit_busy`, Tom's yes 15 Nov; a skipped day is left to the next run) writes
  `<day>.geo-region.json` and `geo-elements-YYYY-MM.parquet` to the pnt-data releases; the /geo page's "Arrivals and
  departures" reads them through `geo.py build`. The globe at the top of /geo is `site_src/globe.js` (data from
  `tools/geo_globe.py` at deploy into `site/data/geo/`, gitignored). Callouts are pre-registered and scored
  (`docs/validation/geo-callouts.md`, `tools/geo_callouts.py`); C3–C7 on by default, C1, C2, C8 off. The globe also
  has look angles and sun outages from a place, sun direction and the belt's shadow, relative motion, closest objects
  over time, board findings on the globe, CSVs, and hypothetical beams and local footprint files. Published
  footprints wait on licences (registry rows `satbeams`, `operator-coverage`, `fcc-space-filings`, `itu-space-filings`).
- **NISAR on the public map (approved 28 Oct 2026):** read `docs/nisar-public-plan.md` first (gate, decisions D1–D7,
  build steps N1–N5). `python -m nisar_rfi export` writes the public repeat-site file; `nisar/run_daily.cmd` runs every
  extra area in `private/watch/nisar.d/*.json` after the main one, then the export (uploaded to the `nisar-data`
  release), then, only after a good upload, a site deploy (`gh workflow run deploy-site.yml`; Tom approved 29 Oct 2026,
  because GitHub's daily deploy runs before the upload), then the private publish. Each detection is a lead, not attribution.
- **Other satellites (planned 30 Oct 2026; Tom: develop every option):** read `docs/space-sensors-plan.md` first, and
  `docs/validation/space-receivers.md` for the receiver lanes.
  - **On the map (each Tom approved, 31 Oct 2026):** four daily jobs run from the 06:30 collectors task
    (`collectors/run_daily.cmd`). Each uploads `<day>.<layer>.json` to the `<layer>-data` release, which
    `site_layers.py` copies to `site/data/<layer>/` at deploy.
    - `s6`: `tools/s6_daily.py` (needs EARTHDATA_TOKEN and the Space-Track account; complete days about three days
      behind; frozen method `tools/s6_rfi.py`, `tools/rx_rfi.py`, `cosmic2_rfi` back-projection). Sentinel-6A places
      regions, not sites, and doesn't track the Gulf's spring 2026 rise.
    - `cosmic2`: `tools/cosmic2_daily.py` (no account; each complete UCAR day, about 450-650 MB, gridded at 2,500 km
      with the fore/aft split; method `tools/cosmic2_rfi.py`). Low latitudes only (24° orbit).
    - `smap`: `tools/smap_daily.py` (needs EARTHDATA_TOKEN; one L1C day, about 160 MB; 7 days of stand-out cells and
      busy H3 res-3 regions; the cuts are display choices; method `tools/smap_rfi.py`). It finds L-band radars
      against a quiet background and saturates in crowded regions.
    - `s1`: `tools/s1_daily.py` (Planetary Computer, no account; `tools/s1_rfi_global.py day`; a day with more than
      5% failed reads isn't saved; a 28-day window of res-3 cells). It shows C-band radar activity by region, never
      GPS interference or sites
      (`docs/validation/s1-rfi.md` sections 9-10).
  - Events (rule S3; `tools/orbit_checks.py`, `docs/assessment/events.md`): Sentinel-6A and COSMIC-2 both place
    jamming regions, but neither rises on event days within a region. The grading stays at v1.1.
  - Probes only: ALOS-2 (`tools/alos2_rfi.py`) and SMOS (`tools/smos_rfi.py`, browse product, CDSE keys) failed their
    North Warning System tests. **HydroGNSS** waits on credentials. **Biomass** needs an ESA account.
  - **Step E, Sentinel navigation receivers** (Sentinel-1C/1D/2B/2C/3A/3B, Copernicus `AUX_GNSSRD`, the SAT-JAM
    method; ~6 days behind). `tools/sentinel_gnss.py` (`fetch`, `day`, `latest`) writes
    `data/sentinel_gnss/days/<day>.parquet` (one row per link and epoch, ~10 MB a day). The index is
    `tools/sentinel_rfi.py` (`docs/validation/sentinel-gnss.md`, frozen section 1): a regional sensor about 2,000 km
    across, not a cell map. E4 waits on Tom. Downloads use S3 keys in the user variables `CDSE_S3_ACCESS_KEY` and
    `CDSE_S3_SECRET_KEY`; Sentinel-6A stays in step P (PO.DAAC). `tools/sentinel_trend.py` (box trends and maps from
    a private config) and `tools/sentinel_daily.py` (daily, from `collectors/run_daily.cmd`; private products in
    `private/sentinel/`, nothing uploaded; it also builds the X3 band files and GPS L2C products, `<area>_l2c*`).
    **E2.1 in the products (from 16 Nov 2026, Tom's yes):** E2 reads 0.5-1 dB low across about 60-160°E even over
    empty ocean (BeiDou/QZSS/SBAS overhead); the E2.1 correction (`tools/sentinel_e21.py`,
    `docs/validation/sentinel-gnss-e21.md`) passed all five checks on 4 Nov. The products use its section-3
    definition: D″ = D − β·(L − L̄), no offset, fitted per unit-day and signal (L1, L2C, E5a), with the
    broadcast file's regional load. `sentinel_e21.py product` writes `data/sentinel_gnss/e21p/<day>.parquet` (load
    and fits; E2 epoch and band files are unchanged), `sentinel_daily.py` builds missing ones in the window (at most
    14 a run, about 5 min each), and `sentinel_trend.py` reads E2.1 by default; `--index e2` on either writes the
    uncorrected products as `*_e2*` for comparison. From late May 2026 no IGS merged file or MGEX orbit carries the
    BeiDou-3 regional satellites C59, C60 or C38-C40; the product code positions them from Space-Track (dated
    PRN table; C59's slot changed satellite in April 2026) and records their load, but a pre-stated test found no sign
    they lower the signal, so they stay out (`FILL_LOAD`). SAT-JAM: no contact (Tom, 31 Oct); replicate and improve.
- **Space weather files (from 15 Nov 2026; Tom decided Noisefloor is the suite's source for PNT and space weather
  data, read from its published files):** COSMIC-2 limb S4 and ground ROTI. Always label the first "limb S4 measured
  along radio-occultation paths, which reads higher than a ground receiver's S4", and never compare it with the ground
  S4 alert levels, on the site, in files or in docs. Label the second "ROTI, a measured TEC fluctuation index at fixed
  stations": a proxy for irregularities, never an S4 value, never read against S4 alert levels.
  - `.github/workflows/cosmic2.yml` runs `tools/cosmic2_job.py` on GitHub: one pass over UCAR's podTc2 day archive
    makes `<day>.cosmic2-limb-s4.json` (`tools/cosmic2_s4.py`; release `swx-data-YYYY-MM`) and the interference file
    `<day>.cosmic2.json` (uploaded to `cosmic2-data` only if the PC's `cosmic2_daily.py` hasn't, and compared if it
    has; from 16 Nov 2026 the PC run likewise keeps a copy the job made and logs `Compared with it: {...}`,
    and a clean week of match lines is the case for retiring it). UCAR posts about 04:35 UTC; the limb file is due
    by 14:00 UTC. The gate (the day's file already in the release) makes extra starts cheap. GitHub's cron runs hours late (crons at 01:15, 03:15, 05:15, 08:15 UTC are the
    fallback), so tic-dispatch starts it at :50 past 04-08 and 10-13 UTC (Tom's yes 15 Nov 2026, hub 1739e03; noise-floor
    was added to the `tic-dispatch` token's repository access the same day). Keep the PC path until the GitHub
    one is proven.
  - Method facts (`docs/validation/cosmic2-limb-s4.md`): UCAR's on-board S4 is one value per 10 s, repeated at 1 Hz;
    link files overlap and must be made unique per second; the first 60 s of a track are dropped; GPS links only;
    tangent points 150-500 km; H3 res 1. **Validated 15 Nov 2026** against INGV eSWua ground receivers on 25 held-out
    days (AUC 0.834; night-only 0.763; chance test p = 0.0005). **Tom approved map and feed use on 16 Nov 2026**
    (not built yet; the label rule above applies). Only C2E2, C2E5
    and C2E6 deliver podTc2 data in Oct-Nov 2026.
  - Ground ROTI (built 15 Nov 2026; `docs/validation/ground-roti.md`): `.github/workflows/ground-roti.yml` runs
    `tools/ground_roti_job.py`, which reads 17 IGS stations' daily 30 s files from BKG (anonymous; the belt from Cape
    Verde to Diego Garcia where no scintillation receiver sits, plus the station nearest each eSWua receiver) and
    writes `<day>.ground-roti.json` (`tools/ground_roti.py`) to `swx-data-YYYY-MM`: per station and UTC hour, n, p95
    and max of 5-minute ROTI (TECU/min), GPS L1/L2 and Galileo E1/E5a, 30 deg mask, Melbourne-Wubbena slips over 2
    wide-lane cycles, pierce points at 350 km. BKG lists the files 00:05-13:00 UTC on D+1; before 09:00 UTC a day is
    published only when all 17 are in, from 09:00 with what is in, and a later start up to D+3 remakes it when a
    missing station turns up. Compact RINEX 3.1 (RNX2CRX 4.2.0, e.g. MAL200KEN) is read as 3.0. Check:
    `tools/ground_roti_check.py` (needs the eSWua cache, `--ground`). **Validated 15 Nov 2026** against eSWua on
    the 25 held-out days (AUC 0.887; night-only 0.871; chance test p = 0.0005; Hanoi had no eSWua records, Dhaka /
    Shillong weakest at 0.651; backfill run 43746680913). **Tom approved map and feed use on 16 Nov 2026** (not built
    yet; the label rule above applies).
- **`watch.py` sources (31 Oct 2026):** Cloudflare Radar (`CLOUDFLARE_RADAR_TOKEN`, private digest) and Page watch
  (pages in `private/watch/pollers.json` `pagewatch`, each with a link pattern). FAA NOTAMs wait on API credentials
  (requested 30 Oct); the public NOTAM Search site refuses automated clients.
- **Every constellation and band (planned 1 Nov 2026):** read `docs/multi-gnss-plan.md` first (signal table,
  sensors by band, checks that separate interference from outages, scintillation and equipment, steps X1–X6, decisions
  D1–D4). **X1:** `tools/station_bands.py day STATION DAY --window HH:MM-HH:MM` scores every signal of every system at
  an EPN/IGS station and writes band signatures and the GLONASS channel ladder; `station_cn0.fetch` uses held files
  first, then BKG, then CDDIS (IGS stations, EARTHDATA_TOKEN). **X3:** `tools/sentinel_bands.py` (`bands`, `checks`)
  runs the frozen E2 index on Galileo E5a and GPS L2C beside paired L1/E1 (`docs/validation/sentinel-gnss-x3.md`);
  `tools/sentinel_trend.py --signal l2c|e5a|l1p` builds box trends from the band files. **Caveat (section 2.6):**
  over East Asia, L2C and E5a slid 1.2–2.2 dB or more from Oct 2025 to Oct 2026 while other regions held; ground
  stations in Japan, Korea, Guam and Australia saw no change on GPS or QZSS L2C (not a GPS transmitter change);
  cause not established.
- **AIS beyond the Baltic (28 Oct 2026, Tom approved):** `collectors/run_aisstream.cmd` (global aisstream, private only;
  focus boxes in `private/watch/maritime.json`) and `collectors/barentswatch_ais.py` + `run_barentswatch.cmd` (Norway's open
  AIS, NLOD; Finnmark and the western Barents Sea). Both skip until Tom's credentials exist (AISSTREAM_API_KEY;
  BARENTSWATCH_CLIENT_ID/SECRET) and run from Task Scheduler tasks Tom registers. Data stay private in `data/ais/`; publishing
  anything derived waits on the terms answers (registry rows `barentswatch-ais`, `dma-ais`).
- **Lanes added 23–24 Oct 2026 (prototypes; each has a write-up in `docs/validation/` or `docs/assessment/`):**
  `tools/cygnss_rfi.py` (CYGNSS noise floor, needs `EARTHDATA_TOKEN`; held-out checks in `tools/cygnss_checks.py`), `tools/s1_rfi.py` (Sentinel-1 RFI annotations),
  `tools/events.py` (observations → graded events, private register in `data/events/`; from v1.1, 27 Oct 2026, EASA's FIR
  tables drive rule D1: `tools/easa_history.py` keeps Internet Archive copies in the private archive, `tools/fir_approx.py`
  builds the country stand-ins in `data/declared/fir_approx.json`), `collectors/digitraffic_ais.py` and
  `tools/ais_detect.py` (Finland's open AIS), `tools/station_cn0.py` (EPN station C/N0), `tools/trace_box.py types` (by aircraft family),
  `tools/horizon_fix.py --balance`, `tools/spoof_day.py` (ADS-B spoofing; reads the raw archives; v0.6 by default from 15 Nov 2026, `--no-v06` for v0.5,
  `docs/validation/spoofing-v06.md`; v0.6.1 by default from 15 Nov 2026: rule A for category A2 only at or above
  36,000 ft, `--slow-hi-a2-ft 25000` for v0.6, `docs/validation/spoofing-v061.md`). **Testing detector changes (16 Nov
  2026):** read `docs/spoofing-light-plan.md` first: day caches (`spoof_day.py run --cache`, `rerun --set`), shadow
  variants in the daily run (`tools/spoof_shadow.json`, `tools/spoof_shadow.py`, `<day>.spoof-shadow.json`) and the
  lighter procedure. Caches of the 18 test days are in `data/spoof_cache/` (local). `spoof_day.py` summaries carry
  `seconds` (wall), `seconds_read` and `cpu_seconds` (main process plus pool workers: compare this one, wall time is
  unreliable on the shared PC); `spoof_day.py cache-convert` writes faster format-2 caches into a new root;
  `tools/spoof_variant.py` scores a variant from the caches in one command (reruns, held-out H1–H8, outside-list
  P1/P2, diff against a reference, one report JSON); `tools/spoof_same.py` compares two output folders day by day
  (exit 1 on a real difference); `tools/heavy_lock.py` is the machine-wide lock that heavy local jobs (multi-day
  `spoof_day.py` run/rerun/cache-convert, `spoof_variant.py`) take and wait on. `tools/year_trends.py`
  (`docs/assessment/year-trends.md`), and position loss: aircraft heard by MLAT but sending no GNSS position
  (`tools/position_loss.py`, and `pipeline/pnt_daily.py --position-loss`, set in the daily workflow from late Oct 2026 (release files `<day>.loss*.parquet`); `docs/validation/position-loss.md`).
  The degraded share can't see those aircraft: check position loss before reading any share trend. CI runs each `tests/test_*.py` as a plain script with only `requirements.txt` and
  `nisar/requirements.txt` installed (no matplotlib, no pytest).
- **The public site `site/` is generated.** Edit `site_src/` (page bodies, `lanes.json`) and run `python tools/build_site.py`;
  the Sources page comes from `registry/sources.csv`. CI fails if `site/` is out of step. Cloudflare Pages deploys `site/` from `main`.
  **Deploys run from GitHub Actions** (`.github/workflows/deploy-site.yml`): after CI passes on `main`, `site/` is uploaded
  straight to Cloudflare Pages. Cloudflare's own Git-triggered builds stuck in "queued" from 15 Oct 2026; `tools/cf_pages_kick.py`
  is the manual fallback. Check the live page after site changes.
  **Site design (27 Oct 2026, Tom approved the mockup):** one token system in `site_src/style.css` (7 type sizes, 5 radii,
  light and dark; IBM Plex served from `site_src/fonts/`, SIL OFL). Navigation is five tabs plus an About menu (`TABS` and
  `SECTIONS` in `tools/build_site.py`), with a section bar on Space and About pages; every page shares the header's 75rem grid.
  The home page is a daily briefing: `board.py` writes the bottom-line sentence (`brief`, fixed rules, tested), `board.js` and
  `dash.js` fill the page, and `tools/map_thumb.py` draws the map thumbnail at deploy (`site/data/today-map*.svg`).
  The hub (theintelligence.company) quotes `brief` too, so it must make sense to someone who has never seen Noisefloor
  (Tom, 31 Oct 2026): it names the measure ("the share of aircraft with severe GPS error was above/near/below its usual
  level", i.e. against the 30-day median, never "rose" or "fell") and says "GPS interference started in … / has stopped
  in …"; the rules are in `brief()`'s docstring.
  Tool pages (Map, Sea, Trends, Sun, GEO) open with a `.page-head` (title, one-line subtitle, "How to read" link) and the tool; their
  explanations live in one `<section id="howto" class="howto">` at the end (site.js scrolls there without touching the hash,
  which holds map and filter state).
  **Site wording (Tom, 27 Oct 2026):** headlines say "GPS interference"; the measure is "severe GPS error (worse than 93 m)";
  "cell", never "hex"; plain dates ("26 Oct 2026") and times "14:00 UTC (9:00 AM CDT)", local date only when it differs;
  place names, with coordinates only in tooltips and downloads; effects, not causes; no internal words ("lane", "phase",
  "aircraft-hexes", "post-exposure") outside Methods, Data and Roadmap, which keep the exact terms. Validation results stay
  word for word. `site_src/guide.html` (About → Plain-language guide) explains every measure in everyday words.
- **Daily pipeline (Phase 2, from 22 Oct 2026):** `.github/workflows/daily.yml` runs `pipeline/daily_job.py` at 05:40 UTC (again at 12:40 for late releases).
  It processes each new adsb.lol day, uploads the outputs to the release `pnt-data-YYYY-MM` (ODbL; `<day>.map.json` last,
  as the done marker) and calls `deploy-site.yml`, which adds every release's map files to `site/data/gnss/`
  (`tools/site_days.py`). Rerun or fill days with Actions → daily → Run workflow (`days`, `force`; `reanalyse` reruns only the analyses,
  with no adsb.lol download, after `pnt_analysis.py` changes). The map page's events panel reads `site/data/events/<day>.json`;
  the charts page's daily trend reads `site/data/trend.json` (both built at deploy for daily days). The home page status board
  reads `site/data/board.json`, built at deploy by `tools/board.py` (day maps, trend, events, position loss, FAA tests,
  `site_src/official_notices.json`, and live EASA FIR and ESA scintillation snapshots; a failing source is listed in
  `problems`, never fatal). The daily run also uploads `<day>.spoof.json` (`daily_job.py --spoofing`, from late Oct 2026) and, from 14 Nov 2026,
  `<day>.spoof-targets.json` (every spoofed-to cluster, `tools/spoof_summary.py`; `docs/validation/spoofing-lima.md`); redo
  them on published days with backfill.yml `spoofing_only` (`daily_job.py --spoof-only`, downloads the raw archive).
  **Scoring a detector variant on GitHub (16 Nov 2026):** `.github/workflows/spoof-variant.yml` (Run workflow: `set`,
  `label`, `days`; each run is Tom's call) reruns the 12 held-out days from their caches and scores H1-H6. The caches
  and the H6 baseline's events hold ICAO addresses, so they sit in a PRIVATE release (`spoof-cache` in
  metacog-osint/noise-floor-archive; Tom, 16 Nov 2026), uploaded with `tools/spoof_cache_release.py upload` and read
  with the read-only secret `SPOOF_CACHE_TOKEN`; only aggregate scores leave the job. The Lima check stays on the PC.
  **Spoofing on the site (Nov 2026):** `tools/spoof_site.py` runs at deploy after `site_layers.py`: it adds every spoofed-to
  place (`targets`, `unplaced`) to `site/data/spoof/<day>.json` and writes `site/data/spoof/history.json` (Trends:
  daily active episodes, victim cells by the validation's region groups, places followed day to day, new places).
  `board.py` adds `new_places` to the spoofing card and `feed_v2.py` up to five feed items for them (observations,
  placed where the aircraft really were). `<day>.spoof.json` gains `share2` (active share of aircraft-hours per H3
  res-2 region, from spoof_day's hex2 table) for the map's "Spoofed share" layer; days published before it lack it
  until redone. From 16 Nov 2026 spoof_site also adds `sent2`/`unplaced2` (where each region's aircraft were shown), `level2` (each
  region against its own usual level) and `share2_7` (7 days pooled) to each day file, and `regions` to history.json;
  board.py adds `region_levels` and `line` (the Today page's spoofing sentence); feed_v2 adds up to five
  `noisefloor-spoof-region-above-<day>-<n>` items. The map's Measure → Spoofing (`m=spf`) shows only spoofing.
  `tools/cygnss_daily.py` makes CYGNSS day summaries on this PC (needs `EARTHDATA_TOKEN`) from the 06:30 collectors task
  (`collectors/run_daily.cmd`) and uploads them to the `cygnss-data` release (Tom approved 26 Oct 2026); the newest
  complete day runs about six days behind. **Map layers (27 Oct 2026):** the map page's Spoofing and CYGNSS checkboxes read
  `site/data/spoof/` and `site/data/cygnss/`, copied at deploy by `tools/site_layers.py` from release files that carry `cells`
  (spoofing: `tools/spoof_summary.py`, daily from 27 Oct plus 17 earlier days; CYGNSS: every gridded day, refreshed with
  `cygnss_daily.py --resummarise`). The 20 validated days are
  in the releases too (`pnt-data-2025-10`, `-2025-11`, `-2026-09`; uploaded with `daily_job.py ... --upload-local`).
- **Backfill (22–23 Oct 2026):** `.github/workflows/backfill.yml` (Run workflow: `start`, `end`) filled 1 Oct 2025 – 6 Oct 2026.
  Phase 1 processes one month per job, two at a time (`--skip-analysis`); phase 2 runs the analyses in date order
  (`--reanalyse --min-seconds 30`); then the site redeploys. Reruns skip published days. Gaps are at the source: adsb.lol
  has no archive for 31 Dec 2025 or 6 May 2026, its 5 May archive holds no traces, and 7 May covers about 6 hours. Deploys fetch only changed release files (`tools/fetch_release_files.py`, cached). GitHub disables
  scheduled workflows after 60 days without a push to the repo.
