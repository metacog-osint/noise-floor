# Noise Floor: project notes for Claude

Product name decided 14 Oct 2026: **Noise Floor** (repo and local folder `noise-floor`).

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
- Store UTC; show people Central time with the zone named.
- Tom is a domain expert (intel, SDA, weather): cite sources and flag anything unverified.

## Products and tools
- `products/`: written products, dated. First: `2026-10-07-sun-outage-season.md` (Weekly Topic draft, not yet published).
- `tools/sun_transit.py`: sun-outage windows for GEO satellites from fixed receivers (`--daily`, `--start`, `--end`,
  `--threshold`). Checked against a separately written calculator: Tehran windows and times agree.
- `tools/check_public.py`: pre-commit check for private terms.
- **The public site `site/` is generated.** Edit `site_src/` (page bodies, `lanes.json`) and run `python tools/build_site.py`;
  the Sources page comes from `registry/sources.csv`. CI fails if `site/` is out of step. Cloudflare Pages deploys `site/` from `main`.
  **Deploys run from GitHub Actions** (`.github/workflows/deploy-site.yml`): after CI passes on `main`, `site/` is uploaded
  straight to Cloudflare Pages. Cloudflare's own Git-triggered builds stuck in "queued" from 15 Oct 2026; `tools/cf_pages_kick.py`
  is the manual fallback. Check the live page after site changes.
- **Daily pipeline (Phase 2, from 22 Oct 2026):** `.github/workflows/daily.yml` runs `pipeline/daily_job.py` at 05:40 UTC (again at 12:40 for late releases).
  It processes each new adsb.lol day, uploads the outputs to the release `pnt-data-YYYY-MM` (ODbL; `<day>.map.json` last,
  as the done marker) and calls `deploy-site.yml`, which adds every release's map files to `site/data/gnss/`
  (`tools/site_days.py`). Rerun or fill days with Actions → daily → Run workflow (`days`, `force`). GitHub disables
  scheduled workflows after 60 days without a push to the repo.

## History
- An Oct 2025 attempt never processed a full day. Its raw adsb.lol traces for Oct 2025 are still on D: (path in
  `CLAUDE.local.md`). adsb.lol also keeps them on GitHub.
- 6 Oct 2026 spike (`spikes/spike_day.py`, set `TRACES_DIR`): 3% of 16 Oct 2025, version-2 `adsb_icao` only, H3 res 4.
  It took 45 s with all reports and 18 s with 30 s sampling, both with a warm cache. A cold read from the USB drive took 222 s.
  The top hotspot was the Georgia/eastern Black Sea coast.
