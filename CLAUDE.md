# Noisefloor: project notes for Claude

Product name: **Noisefloor**, one word (Tom, 27 Oct 2026; it was "Noisefloor" from 14 Oct). Repo and local folder stay `noise-floor`.

Tom's own project under **The Intelligence Company**, to be hosted on theintelligence.company. Restarted 6 Oct 2026.
**Merged with Interference Watch on 14 Oct 2026.** The "Merged plan" section at the end of `docs/DESIGN.md` decides what wins.
Read `docs/DESIGN.md` (the plan and open decisions) and `docs/research/2026-10-06-sources.md` (sources, licences, methods).
**Also read `CLAUDE.local.md` if present.** It holds private notes that are deliberately kept out of this public repo.

## Hard rules
- **This repo is public:** https://github.com/metacog-osint/noise-floor (created and first pushed 14 Oct 2026; CI checks the private
  term list from the `FORBIDDEN_TERMS` secret). No employer names, old-project names, credentials, personal paths or watch configuration
  (AOIs, keywords, watch lists, alert history) in tracked files. Those go in `CLAUDE.local.md`, `private/` (gitignored)
  or the private store. The pre-commit hook `tools/check_public.py` enforces a private term list.
- **Nothing from Tom's employer or its projects.** No code, names, accounts or infrastructure (details in `CLAUDE.local.md`).
  Methods may be re-derived. emso-watch is Tom's own code and may be ported.
- **Licence-clean sources only** in anything published. Every source is recorded with its licence before it feeds a layer.
  Non-commercial sources (airplanes.live, adsb.fi, ADSBx, OpenSky, Stanford RFI, Cloudflare Radar, OONI, GFW, GPSJam) are
  visual comparison only.
- adsb.lol-derived downloadable data is published under ODbL, with attribution on every map.
- Free tier only. Ask before anything billable. **Commits and pushes:** commit finished steps, and push any commit that passes
  the pre-commit checks (standing permission, Tom, 14 Oct 2026). Creating repos or services, changing deploy settings, and
  publishing anything outside this repo (posts, products, the subdomain) still need Tom's OK each time.
- Store UTC. On the site, show UTC with the visitor's own time zone alongside, always named; the Time button
  (`site_src/tic-time.js`, The Intelligence Company's shared module, v1.0) lets them pick any zone and a 12/24-hour
  clock (Tom, 27 Oct 2026). Messages to Tom use Central time.
- Tom is a domain expert (intel, SDA, weather): cite sources and flag anything unverified.

## Products and tools
- `products/`: written products, dated. First: `2026-10-07-sun-outage-season.md` (Weekly Topic draft, not yet published).
- `tools/sun_transit.py`: sun-outage windows for GEO satellites from fixed receivers (`--daily`, `--start`, `--end`,
  `--threshold`). Checked against a separately written calculator: Tehran windows and times agree.
- `tools/check_public.py`: pre-commit check for private terms.
- **Maritime lane (planned 23 Oct 2026; M1 started 24 Oct):** read `docs/maritime-plan.md` first (sources, detectors D1–D13, database, validation,
  build steps M0–M7, open decisions). Private handoff and watch configuration are listed in `CLAUDE.local.md`.
  `tools/ship_detect.py` finds ships in Sentinel-1 GRD (Planetary Computer, anonymous); boxes come from private config.
  `tools/s2_check.py` checks its detections against Sentinel-2 (`docs/validation/ships-s1.md`: at the default k = 6 most are clutter;
  use `--min-contrast 10 --ghosts drop --landmask` for better precision).
- **Lanes added 23–24 Oct 2026 (prototypes; each has a write-up in `docs/validation/` or `docs/assessment/`):**
  `tools/cygnss_rfi.py` (CYGNSS noise floor, needs `EARTHDATA_TOKEN`; held-out checks in `tools/cygnss_checks.py`), `tools/s1_rfi.py` (Sentinel-1 RFI annotations),
  `tools/events.py` (observations → graded events, private register in `data/events/`; from v1.1, 27 Oct 2026, EASA's FIR
  tables drive rule D1: `tools/easa_history.py` keeps Internet Archive copies in the private archive, `tools/fir_approx.py`
  builds the country stand-ins in `data/declared/fir_approx.json`), `collectors/digitraffic_ais.py` and
  `tools/ais_detect.py` (Finland's open AIS), `tools/station_cn0.py` (EPN station C/N0), `tools/trace_box.py types` (by aircraft family),
  `tools/horizon_fix.py --balance`, `tools/spoof_day.py` (ADS-B spoofing; reads the raw archives; v0.5 by default, `--no-airspeed-fast` for v0.4), `tools/year_trends.py`
  (`docs/assessment/year-trends.md`), and position loss: aircraft heard by MLAT but sending no GNSS position
  (`tools/position_loss.py`, and `pipeline/pnt_daily.py --position-loss`, set in the daily workflow from late Oct 2026 (release files `<day>.loss*.parquet`); `docs/validation/position-loss.md`).
  The degraded share can't see those aircraft: check position loss before reading any share trend. CI runs each `tests/test_*.py` as a plain script with only `requirements.txt` and
  `nisar/requirements.txt` installed (no matplotlib, no pytest).
- **The public site `site/` is generated.** Edit `site_src/` (page bodies, `lanes.json`) and run `python tools/build_site.py`;
  the Sources page comes from `registry/sources.csv`. CI fails if `site/` is out of step. Cloudflare Pages deploys `site/` from `main`.
  **Deploys run from GitHub Actions** (`.github/workflows/deploy-site.yml`): after CI passes on `main`, `site/` is uploaded
  straight to Cloudflare Pages. Cloudflare's own Git-triggered builds stuck in "queued" from 15 Oct 2026; `tools/cf_pages_kick.py`
  is the manual fallback. Check the live page after site changes.
- **Daily pipeline (Phase 2, from 22 Oct 2026):** `.github/workflows/daily.yml` runs `pipeline/daily_job.py` at 05:40 UTC (again at 12:40 for late releases).
  It processes each new adsb.lol day, uploads the outputs to the release `pnt-data-YYYY-MM` (ODbL; `<day>.map.json` last,
  as the done marker) and calls `deploy-site.yml`, which adds every release's map files to `site/data/gnss/`
  (`tools/site_days.py`). Rerun or fill days with Actions → daily → Run workflow (`days`, `force`; `reanalyse` reruns only the analyses,
  with no adsb.lol download, after `pnt_analysis.py` changes). The map page's events panel reads `site/data/events/<day>.json`;
  the charts page's daily trend reads `site/data/trend.json` (both built at deploy for daily days). The home page status board
  reads `site/data/board.json`, built at deploy by `tools/board.py` (day maps, trend, events, position loss, FAA tests,
  `site_src/official_notices.json`, and live EASA FIR and ESA scintillation snapshots; a failing source is listed in
  `problems`, never fatal). The daily run also uploads `<day>.spoof.json` (`daily_job.py --spoofing`, from late Oct 2026).
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

## History
- An Oct 2025 attempt never processed a full day. Its raw adsb.lol traces for Oct 2025 are still on D: (path in
  `CLAUDE.local.md`). adsb.lol also keeps them on GitHub.
- 6 Oct 2026 spike (`spikes/spike_day.py`, set `TRACES_DIR`): 3% of 16 Oct 2025, version-2 `adsb_icao` only, H3 res 4.
  It took 45 s with all reports and 18 s with 30 s sampling, both with a warm cache. A cold read from the USB drive took 222 s.
  The top hotspot was the Georgia/eastern Black Sea coast.
