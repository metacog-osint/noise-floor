# Noisefloor: history and background

Dated history, measurements and finished work, moved verbatim from `CLAUDE.md` on 5 Nov 2026 (at `ef399c5`) so that
`CLAUDE.md` holds only what every session needs. This file is not loaded automatically; read it when you need the
background. Where `CLAUDE.md` now carries a condensed entry, the full original entry is kept here word for word, with
its dates and statuses as they stood then. Add new dated entries at the end.

## Products and tools: `tools/sun_transit.py` (original entry)

- `tools/sun_transit.py`: sun-outage windows for GEO satellites from fixed receivers (`--daily`, `--start`, `--end`,
  `--threshold`). Checked against a separately written calculator: Tehran windows and times agree.

## Products and tools: GEO globe (original entry)

- **GEO globe (planned 27 Oct 2026, Tom approved every idea):** read `docs/geo-globe-plan.md` first (Space-Track data
  and credentials, the region and membership events, the 3D viewer, callouts C1–C8 to validate on history, footprints
  and their licence checks, build steps G1–G5). **G1 done 27 Oct:** `tools/geo_region.py` (Space-Track gp daily in
  `daily.yml`; gp_history held once in `data/geo/region/history/`, never re-fetched; `replay` rebuilds the day files
  offline) writes `<day>.geo-region.json` and `geo-elements-YYYY-MM.parquet` to the pnt-data releases; the /geo page's
  "Arrivals and departures" reads them through `geo.py build`. **G2 done 28 Oct:** the globe at the top of /geo
  (`site_src/globe.js`; data from `tools/geo_globe.py` at deploy into `site/data/geo/`, gitignored). **G4 done 1 Nov:** callouts pre-registered and scored (`docs/validation/geo-callouts.md`, `tools/geo_callouts.py`); C3–C7 on by default, C1, C2, C8 off. **G3 done 31 Oct:** look angles and sun outages from a place, sun direction and the belt's shadow, relative motion, closest objects over time, board findings on the globe, CSVs. **G5 done 28 Oct:**
  hypothetical beams and local footprint files in the globe; published footprints wait on licences (registry rows
  `satbeams`, `operator-coverage`, `fcc-space-filings`, `itu-space-filings`).

## Products and tools: Other satellites (original entry, with Step E and the `watch.py` sources)

- **Other satellites (planned 30 Oct 2026; Tom: develop every option):** read `docs/space-sensors-plan.md` first, and
  `docs/validation/space-receivers.md` for the receiver lanes.
  - **Sentinel-6A is live on the map (31 Oct 2026, Tom approved):** `tools/s6_daily.py` runs from the 06:30 collectors
    task. It needs EARTHDATA_TOKEN and the Space-Track account, and processes complete days about three days behind
    with the frozen method (`tools/s6_rfi.py`, `tools/rx_rfi.py`, `cosmic2_rfi` back-projection). It uploads
    `<day>.s6.json` to the `s6-data` release, which `site_layers.py` copies to `site/data/s6/` at deploy.
  - **The Sentinel-6A result:** all four held-out checks pass (AUC 0.956). It places regions, not sites, and doesn't
    track the Gulf's spring 2026 rise.
  - **COSMIC-2** (`tools/cosmic2_rfi.py`): all five pre-registered checks held on 21 held-out days (31 Oct: AUC 0.919;
    the Gulf's spring rise shows, narrowly). Low latitudes only (24° orbit).
  - **COSMIC-2 on the map (31 Oct 2026, Tom approved):** `tools/cosmic2_daily.py` runs from the 06:30 collectors task
    (no account). It fetches each complete UCAR day (about 450-650 MB) and grids it at 2,500 km with the fore/aft
    split, writing `<day>.cosmic2.json` (cells at or above 0.23, named peaks, satellites) to the `cosmic2-data`
    release, which `site_layers.py` copies to `site/data/cosmic2/`.
  - **Events corroboration (31 Oct 2026, pre-registered):** Sentinel-6A and COSMIC-2 were tested as a sensor family
    for rule S3 (`tools/orbit_checks.py`, `docs/assessment/events.md`). Both place jamming regions (O1 holds), but
    neither rises on event days within a region (O2: Sentinel-6A weakened, COSMIC-2 failed). The grading stays at v1.1.
  - **SMAP** (`tools/smap_rfi.py`): the 2010 FAA-site check failed. The pre-registered North Warning System check held
    (AUC 0.988, 10 of 14 sites): it finds L-band radars against a quiet background and saturates in crowded regions.
  - **SMAP on the map (31 Oct 2026, Tom approved):** `tools/smap_daily.py` runs from the 06:30 collectors task (needs
    EARTHDATA_TOKEN). It fetches one L1C day (about 160 MB) and writes `<day>.smap.json` for the 7 days to that day:
    stand-out cells (share 0.5 or more, contrast 0.5 or more, ring 0.10 or less) and busy H3 res-3 regions. Files go
    to the `smap-data` release, which `site_layers.py` copies to `site/data/smap/`. The cuts are display choices.
  - **Sentinel-1 on the map (31 Oct 2026, Tom approved):** `tools/s1_daily.py` runs from the 06:30 collectors task
    (Planetary Computer, no account). Each day (`tools/s1_rfi_global.py day`, about 950 IW GRD annotations, 3 minutes;
    a day with more than 5% failed reads isn't saved) feeds a 28-day window of res-3 cells (4+ passes; share 0.25 or
    more shown) in `<day>.s1.json` on the `s1-data` release, which `site_layers.py` copies to `site/data/s1/`. It shows
    C-band radar activity by region, never GPS interference or sites (`docs/validation/s1-rfi.md` sections 9-10).
  - The **ALOS-2** probe (`tools/alos2_rfi.py`): built.
    ALOS-2's North Warning System test failed (L2.2 shows no radar streaks), so it stays a probe.
  - **HydroGNSS** waits on credentials. **Biomass** needs an ESA account. **SMOS** (`tools/smos_rfi.py`, browse product,
    CDSE keys): its North Warning System test failed on 31 Oct (2 of 14 sites, AUC 0.535), so it stays a probe.
  **Step E (added 30 Oct 2026):** the Sentinel-1C/1D/2B/2C/3A/3B navigation receivers (Copernicus `AUX_GNSSRD`, the
  SAT-JAM method; E0 done: signal strength present, 10 s, ~6 days behind). **E1 built 31 Oct:** `tools/sentinel_gnss.py`
  (`fetch`, `day`, `latest`) writes `data/sentinel_gnss/days/<day>.parquet` (one row per link and epoch, ~10 MB a day,
  with elevation and azimuth in the spacecraft frame). **E2/E3 done 31 Oct** (`tools/sentinel_rfi.py`;
  `docs/validation/sentinel-gnss.md`, frozen section 1): four checks hold (AUC 0.862, Baltic 0.917), two fail (Gulf
  change, inland-Australia control); a regional sensor about 2,000 km across, not a cell map. E4 waits on Tom. Downloads use S3 keys in
  the user variables
  `CDSE_S3_ACCESS_KEY` and `CDSE_S3_SECRET_KEY`; Sentinel-6A stays in step P (PO.DAAC). **E5 (31 Oct):**
  `tools/sentinel_trend.py` (box trends and maps from a private config) and `tools/sentinel_daily.py` (daily, from
  `collectors/run_daily.cmd`; private products in `private/sentinel/`, nothing uploaded; from 4 Nov it also builds the X3
  band files and GPS L2C products, `<area>_l2c*`). **Caveat:** the index reads
  0.5-1 dB low across about 60-160°E even over empty ocean (probably BeiDou/QZSS overhead; validation section 2.5);
  plan step E2.1 corrects it: **E2.1 run 4 Nov on eight held-out weeks, all five checks hold** (`tools/sentinel_e21.py`,
  `docs/validation/sentinel-gnss-e21.md` section 2; flatness 0.43 dB, AUC 0.858, Australia control 0.66% degraded). Products
  keep E2 until Tom agrees. SAT-JAM: no contact (Tom, 31 Oct); replicate and improve.
  **`watch.py` sources added 31 Oct:** Cloudflare Radar (`CLOUDFLARE_RADAR_TOKEN`, private digest) and Page watch (pages in
  `private/watch/pollers.json` `pagewatch`, each with a link pattern). FAA NOTAMs wait on API credentials (requested 30 Oct);
  the public NOTAM Search site refuses automated clients.

## Products and tools: Every constellation and band (original entry)

- **Every constellation and band (planned 1 Nov 2026):** read `docs/multi-gnss-plan.md` first (signal table,
  sensors by band, checks that separate interference from outages, scintillation and equipment, steps X1–X6, decisions
  D1–D4). **X1 built 1 Nov:** `tools/station_bands.py day STATION DAY --window HH:MM-HH:MM` scores every signal of
  every system at an EPN/IGS station (GLONASS by RK4 from broadcast state vectors; BeiDou GEO rotation; per-constellation
  baselines) and writes band signatures and the GLONASS channel ladder; `station_cn0.fetch` uses held files first, then
  BKG, then CDDIS (IGS stations, EARTHDATA_TOKEN). Vaiņode, 17 May 2026: every band fell at once; Riga quiet.
  **X3 done 1 Nov:** `tools/sentinel_bands.py` (`bands`, `checks`) runs the frozen E2 index on Galileo E5a and GPS L2C
  (PODRIX units) beside paired L1/E1 (`docs/validation/sentinel-gnss-x3.md`): both checks hold (AUC 0.911, 0.898), the
  lower bands drop 2.1–2.7x as far as L1 on the same links, and the 60–160°E dip is a quarter as deep on L2C.
  `tools/sentinel_trend.py --signal l2c|e5a|l1p` builds box trends from the band files. **Caveat (section 2.6):** over
  East Asia, L2C and E5a slid 1.2–2.2 dB or more from Oct 2025 to Oct 2026 while other regions held; ground stations in
  Japan, Korea, Guam and Australia saw no change on GPS or QZSS L2C (not a GPS transmitter change); no daily or weekly
  rhythm at the sampled hours; cause not established.

## History

The "History" section of `CLAUDE.md`, moved whole.

- An Oct 2025 attempt never processed a full day. Its raw adsb.lol traces for Oct 2025 are still on D: (path in
  `CLAUDE.local.md`). adsb.lol also keeps them on GitHub.
- 6 Oct 2026 spike (`spikes/spike_day.py`, set `TRACES_DIR`): 3% of 16 Oct 2025, version-2 `adsb_icao` only, H3 res 4.
  It took 45 s with all reports and 18 s with 30 s sampling, both with a warm cache. A cold read from the USB drive took 222 s.
  The top hotspot was the Georgia/eastern Black Sea coast.
