# EMSO tracker: redesign proposal (DRAFT, 6 Oct 2026)

Status: **proposed, waiting on Tom's decisions** (bottom of this file). The working folder name `emso-tracker` holds until
the product is named. Sources and licences: `docs/research/2026-10-06-sources.md`.

## What it is

An open-source picture of where the electromagnetic spectrum is being contested, and what that does to positioning,
navigation and timing (PNT) and to satellite communications (SATCOM). It belongs to **The Intelligence Company**, is
hosted on theintelligence.company, and uses only sources whose licences allow commercial use.

## What changes from the Oct 2025 attempt

| 2025 | 2026 |
|---|---|
| UI first; the data pipeline never processed a full day | **Method first:** frozen test days, a published method card, validation before any UI |
| Firebase project, Cloud Functions, sign-in | **Static-first:** daily batch writes Parquet history plus small per-day files, served from Cloudflare (free tier). No servers, no database bill. |
| OpenSky plus adsb.lol, licences unchecked | **Licence registry:** each source has its licence recorded, and a source can't feed a public layer without one. Non-commercial sources are excluded. |
| GNSS only | **PNT plus SATCOM** as two halves of one picture |
| Hex colours only | **Assessment:** a daily per-region status that states its basis (observed, declared, natural) |

## Architecture

```
adsb.lol daily archive ─┐                       ┌─ Parquet history (one file per day, kept forever)
Digitraffic/Kystverket AIS ─┼─ daily batch (Python) ─┼─ per-day hex/event files (ODbL where derived from adsb.lol)
NGA/NAVCEN warnings ─┤   on GitHub Actions or this PC   └─ method card + validation report
CelesTrak GEO elements ─┤
ITU RRB register ───────┤                         Cloudflare Pages site (static)
NOAA space weather ─────┘                           MapLibre globe + deck.gl H3 hexes + time slider
                                                     DuckDB-WASM in the browser for ad-hoc queries over the history
light pollers (Cloudflare Worker cron): warnings, space weather, Starlink health ──► alerts via ntfy
```

- **Processing:** streams each day's tar without unpacking it, keeps version-2 `adsb_icao` reports only, samples each
  aircraft every 30 s, and classifies aircraft per H3 hex. Spike estimate was about 10 CPU-minutes per worldwide day. **Measured (v1, 14 Oct 2026): 53–70 s per day** on this PC, reading the tar sequentially from the USB drive.
- **Storage:** adsb.lol keeps the raw history on GitHub, so we keep only processed output (MBs per day, not GBs).
- **Times:** stored in UTC; anything a person reads shows Central time with the zone named.

## The two halves

**PNT**
1. GNSS jamming: daily worldwide hex map from ADS-B NACp/NIC, plus hourly detail for hotspots.
2. GNSS spoofing: events from position jumps, convergence on false points, and geometric/barometric altitude divergence.
3. Spoofing at sea: AIS from Digitraffic (Gulf of Finland) and Kystverket (Norway to the Russian border).
4. Declared: NGA maritime warnings and NAVCEN test notices; FAA NOTAMs once access is granted.
5. Natural context: Kp and GloTEC, to separate natural degradation from deliberate interference.

**SATCOM.** Open data can't see satcom jamming RF directly, so this half is built from effects, orbits and the official record.
1. **GEO threat board:** daily positions of known inspector satellites (Olymp-K 1/2, the SJ series) against the comsats
   near them, with longitude-drift and maneuver flags. Thresholds are set no tighter than public-element accuracy (~50 km).
2. **Interference register:** curated, geolocated cases from ITU RRB decisions and operator disclosures, each with a source.
3. **Starlink health:** RIPE Atlas probes, IODA and M-Lab, to tell a constellation-wide outage from a local one
   (needs permission before commercial use).
4. **L-band risk overlay:** where observed GNSS jamming lies near Inmarsat/Iridium/Thuraya L-band. This is an
   inference layer, labelled as such.
5. **Scintillation context:** GloTEC.

## Phases (each one finished and committed before the next)

1. **Foundation:** repo, licence registry, PNT processor v1 on three frozen days, method card, validation report against
   known hotspots and gpsjam's maps for the same dates.
2. **Daily and backfill:** daily job; backfill from Oct 2025 to today; static map live on the subdomain.
3. **SATCOM v1:** GEO threat board plus the interference register seeded from ITU RRB.
4. **Spoofing and maritime:** ADS-B spoofing detectors, AIS layers, declared-warning layers.
5. **Assessment:** per-region daily status, ntfy alerts, weekly written assessment.

## Decisions for Tom

1. Product name and subdomain.
2. Public site, or sign-in?
3. Public GitHub repo (free unlimited Actions minutes, so the daily job runs without this PC) or private (the job runs on this PC)?
4. Permission requests, to be sent by Tom: RIPE NCC (Atlas), Georgia Tech (IODA), adsb.lol (live API in production), and
   later 18 SDS (derived orbital products).
5. Move the Oct 2025 adsb.lol tars (on D:, path in `CLAUDE.local.md`) into this project? This is optional, since adsb.lol keeps them.

## Standing rules

- No code, names, accounts or infrastructure from Tom's employer. A check fails the build if they appear (`tools/check_public.py`).
- Free tier only; ask before anything billable.
- Fact-check domain claims, cite sources, and flag anything unverified.

---

## Merged plan: EMSO tracker + Interference Watch (14 Oct 2026)

Tom decided on 14 Oct to merge the two efforts into one project here. The Interference Watch build guide (Rev 2) and the emso-watch fixes from its first live run are in `private/reference/`. That folder is gitignored because the guide names AOIs. Read them as input; this section decides what wins.

### Rules that carry over unchanged from this design

- **Licence-clean.** Every source is in the licence registry. Non-commercial or closed sources are for **visual comparison only** and never ingested. That covers GPSJam, Stanford RFI, OpenSky, Cloudflare Radar, OONI, Reddit's free API, Earth Engine and Global Fishing Watch.
- **Static-first and free tier.** No database bill, and ask before anything billable. Commits that pass the pre-commit checks may be pushed (standing permission, Tom, 14 Oct 2026); creating services, changing deploy settings and publishing outside the repo still need Tom's OK each time.
- **Method first.** Use frozen test days, a method card and a validation report before any UI.

### What Interference Watch adds

| From the guide | Where it lands |
|---|---|
| Event model and five-field grading (signal type, support in SOP terms, localization, attribution, verdict) | The assessment layer (phase 6) |
| Validation set, with each row verified against its source before scoring | Phase 1 validation report, alongside known hotspots |
| emso-watch trigger board: NGA MSI, NAVCEN, UKMTO (JSON API), SWPC, KingOfSat, Chayka (DL0AO), sun transit | Phase 2 light pollers (Worker cron) plus ntfy |
| emso-watch's GPSJam module | The Phase 1 **validation comparison** only (GPSJam is visual-comparison-only) |
| Sentinel-1 RFI emitter board, weather-radar spoke detection (FMI and DWD, CC BY) | Phase 5 |
| Community-text lane (RSS, Bluesky, Mastodon, Telegram, WarSpotting, IARUMS, ITU RRB), with the Claude task as a least-privilege reader | Phase 6 |
| Attribution and exclusion layers (licensed transmitters, weather radars, navaids, space weather, ducting) | Phase 6 |
| CYGNSS, NISAR, COSMIC-2, CORS/IGS, SMOS/SMAP | Phase 7 |

**emso-watch code:** Tom's own code, so it may be ported. Apply the 14 Oct patch in `private/reference/`. Move its watch lists into private config when porting, because this repo is public.

### Storage and access

- **History:** Parquet history and per-day files in R2, as above.
- **Event and alert state:** **Cloudflare D1** (free tier) instead of Supabase. A new Supabase project in Tom's org costs **$10/month** (checked 14 Oct 2026), which breaks the free-tier rule.
- **Public site:** licence-clean layers, the method card and the validation report, as static files only.
- **Private watch:** AOIs, keywords, alert log and digests live in D1 behind **Cloudflare Access**. They are never in the repo, never in the public site, and never in ntfy message text.
- **Claude scheduled task (digests):** reads through a role that cannot see AOIs or keywords. Collected text is data, never instructions.

### Source status updates (live checks of 14 Oct 2026)

- NGA MSI `issueDate` is a date-time group (`101133Z MAY 2024`).
- UKMTO lists come from `sccd.royalnavy.mod.uk/api/ukmto/`. The site footer says "© Crown copyright", reuse terms UNVERIFIED.
- The Chayka image host `vlf.u01.de` serves an incomplete TLS chain. The patch adds a CA fallback.
- KingOfSat and DF6NM reuse terms are UNVERIFIED, so keep them in the private watch until checked.
- IODA stays "ask first", as above.

### Merged phases (each finished and committed before the next)

1. **Foundation:** as above. Repo, licence registry (merge both research docs), PNT processor v1 on three frozen days, method card, and a validation report against known hotspots and GPSJam maps (visual) for the same dates.
2. **Daily and backfill, plus the declared lane:** daily job, backfill, static map live. Port emso-watch's pollers to Worker cron, with ntfy alerts. **Status 22 Oct 2026:** daily job, backfill and map done in GitHub Actions; announced US GPS tests from FAA advisories on the public map; the pollers run daily on Tom's PC with a private digest (`collectors/watch.py`). Worker cron and ntfy wait for Tom's OK (new services).
3. **SATCOM v1:** GEO threat board and the ITU RRB interference register.
4. **Spoofing and maritime:** ADS-B spoofing detectors, AIS (Digitraffic, Kystverket), declared-warning layers. **Extended 23 Oct 2026** by the maritime lane plan (`docs/maritime-plan.md`): vessels and their signals in the South China Sea and Indian Ocean, led by one validated method (dark ships and phantom tracks).
5. **Emitters:** Sentinel-1 RFI board and weather-radar spokes.
6. **Assessment:** event fusion and grading, attribution and exclusion layers, community lane, Claude digests, private dashboard behind Access.
7. **Extensions:** spaceborne and network GNSS (CYGNSS, NISAR, COSMIC-2, CORS/IGS, SMOS/SMAP).

### Maritime lane plan (23 Oct 2026)

**Plan: `docs/maritime-plan.md`.** A vessel-focused lane and a separate Sea map, starting in four focus areas of the South China Sea and Indian Ocean. It combines AIS behaviour, ships seen by radar satellites while silent on AIS, RF emitters at sea, GNSS interference footprints, HF signal metadata and declared activity, with a private database of vessels, identities, observations, signals and behaviour events. Limits: no open AIS feed in the region (aisstream kept private until its terms are clear) and no free view of per-vessel SATCOM. First milestone: dark ships and phantom tracks validated at one focus area. Open decisions are in Section 14 of the plan.

### Decisions still open (supersedes items 2 and 3 above)

1. ~~Product name~~ **Decided 14 Oct: Noise Floor.** Site live at https://noisefloor.theintelligence.company (Cloudflare Pages project `noise-floor`, output dir `site/`, CNAME at Squarespace; 14 Oct). Code licence: MIT (14 Oct).
2. ~~Repo visibility~~ **Decided 14 Oct: public; created and pushed 14 Oct** (github.com/metacog-osint/noise-floor). It gets free unlimited Actions minutes, and the repo and site are the showcase. Private config stays in D1, secrets and `private/`.
3. ~~Enable R2~~ **Superseded 22 Oct 2026:** outputs are stored as GitHub Release assets (`pnt-data-YYYY-MM`, `declared-data`), free and public; R2 stays an option if the history outgrows releases.
4. Permission requests (unchanged): RIPE NCC, Georgia Tech (IODA), adsb.lol, later 18 SDS.

### Progress (14 Oct 2026)

- **Phase 1, Phase 1.1 and Phase 1.2 are built and validated.** See `docs/validation/phase1.md` and `docs/method-card.md`.
- **The Bluesky collector was pulled forward from the Phase 6 community lane.** It lives in `collectors/bluesky.py`, with the account list and keywords in `private/watch/` (never in the repo).
- **The 22 Sep 2026 NOTAM couldn't be retrieved publicly.** Closing that case needs FAA NOTAM API access (decision 4).

### Progress (22 Oct 2026)

- **Phase 2 daily job is live.** `.github/workflows/daily.yml` runs `pipeline/daily_job.py` each day at 05:40 UTC: it downloads
  the new adsb.lol day (published about 03:30 UTC the next day), runs the processor and the analyses, and redeploys the site.
  The map shows daily days from 2026-10-07.
- **Storage: GitHub Releases instead of R2.** Each month's outputs are assets on the release `pnt-data-YYYY-MM` of this repo
  (about 3 MB a day, ODbL). It needs no new service and no billing, and the files are public downloads. The earlier days a
  baseline needs (30 days back) are fetched from there. R2 stays an option if the history outgrows releases.
- **Site deploys** add the map files from every release at deploy time, so daily data never goes into git.
- **Backfill to 1 Oct 2025** (22–23 Oct 2026, `.github/workflows/backfill.yml`): one month per job, two at a time, then
  the analyses in date order. About 1.3 TB downloaded and discarded; about 3 MB a day kept. The map has a time slider
  over the whole history, and the charts page's daily trend covers it too.

### Progress (21 Oct 2026)

- **NISAR L-band lane pulled forward from Phase 7** (`nisar/`). It detects emitters inside NISAR's receive bands from cross-pol excess, checks band specificity, streak shape and unpolarized change, groups detections into sites and cross-fixes them. The offline self-test passes (in CI). It has not run on live data yet. Next: the Shiraz known-answer run (`nisar/validation/shiraz.json`), then an `inspect` of one provisional granule to see how much the processor's RFI filter leaves. Open decision: where the daily run lives, because its logs and outputs are watch data (public Actions with `--quiet` and outputs to the private store, or this PC).
- **Second Shiraz check on PROVISIONAL products** (`nisar/validation/shiraz_provisional.json`). The GPS World case uses BETA products, which predate the processor's RFI filter. ASF says the filter, applied to PROVISIONAL products (17 Jun 2026 onward), sometimes leaves residual RFI and sometimes removes real features, and it advises caution when mixing BETA and PROVISIONAL. So a BETA pass doesn't show the detector works on filtered data. CMR on 21 Oct: 40 PROVISIONAL granules cover the site, from tracks 56 and 157 ascending and 107 descending, all 20+5 MHz HH+HV. That gives the first real ascending/descending cross-fix test if the jammer is still on. The BETA set is 6 granules (track 157 ascending; 27 Dec, 8 Jan, 20 Jan).
- **Decisions (Tom, 21 Oct):**
  - The daily run starts on this PC until the time per granule is measured.
  - No phone pushes until the Shiraz checks and a regional positive control pass.
  - Outputs stay private until validated.
- **Data volume shapes the daily run.** GCOV files are 1.5–2.0 GB, and the detector streams most of band A. A large regional box can see ~14 granules a day (~24 GB of files). A cheap first pass on the processor's per-channel `rfiLikelihood` (a few bytes per granule) should decide which frames get the full read.
- **Method change (21 Oct, after the first live runs).**
  - **The image method failed the Shiraz BETA known answer:** 56 detections, none within 50 km of the jammer, 21 of them on the jammer-off date.
  - **The default is now the table method.** It reads the RSLC processor's tone-rank tables: per-block interference-to-signal ratio and the share of pulses hit at each frequency, recorded before mitigation. Detection and geolocation come from the orbit. It costs 70–130 MB per pass instead of streaming the 1–2 GB image.
  - **The QA `rfiLikelihood` is tier 0.** Under tone-rank it is the maximum ISR over blocks, so near-zero-signal blocks can push it past 10^11. It is a coarse screen with a per-frame rotation, not a detector.
  - **Two instrument tones** (1233.125 and 1296.002 MHz), present in every pass checked in two regions, are excluded.
  - The image method stays for BETA products only. Details: `nisar/README.md`.
- **Validation (21 Oct, `docs/validation/nisar.md`).**
  - The table method ran on 40 PROVISIONAL passes over the Shiraz case area. Detections repeat within 9–24 km, and one site agrees across ascending and descending geometries.
  - But no HIGH or MEDIUM detection fell within 50 km of the published jammer site, though the site was inside the swath on every pass.
  - Status: plausible, not validated against ground truth; outputs private.
  - Next: a positive control with ground truth in the PROVISIONAL period.
- **Broadband detector (21 Oct, `nisar/nisar_rfi/bbdetect.py`).**
  - Tone-rank misses noise jammers. The broadband detector scores the processor's per-block signal power, flagging HV far above the frame's HH-to-HV/HH relationship, with an excess-power and absolute-ratio gate.
  - On a documented L1/L2/L5 jamming area it detects on 12 of 13 covering passes, where the tone method saw nothing at the L2 centre. Forested regions without reported jamming stay near zero.
  - Both detectors run on every table read and merge within 20 km.
- **Public site expanded (Tom, 22 Oct):** Home, Lanes (all 25 lanes: status, what, how, data, limits; build order), Methods, Validation (failures included) and Sources (the licence registry, filterable). Generated by `tools/build_site.py` from `site_src/`. No watch areas or private detections.
- **Private web view (Tom, 22 Oct):** the NISAR outputs publish daily to a Cloudflare Pages project behind Cloudflare Access (Zero Trust Free, one-time PIN to the owner's email).
- **Daily run (Tom, 22 Oct):** on this PC through Task Scheduler (`nisar/run_daily.cmd`, 07:00 Central), about 0.85 GB and 3–4 minutes a day. Phone pushes stay off and outputs stay private. The full backfill to 17 Jun is on hold.
- **The Shiraz known answer is uncertain (22 Oct):** the article's coordinate is 257 km from the place it describes ("about 50 km SW of Shiraz"). A re-score against the description doesn't pass either (a persistent source on the off date too). A cleaner known answer is needed: an announced test or a surveyed emitter.
