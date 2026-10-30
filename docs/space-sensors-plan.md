# Interference seen from orbit, beyond NISAR: plan

Written 30 Oct 2026 at Tom's request ("what can we do to bring in potential observed interference from satellites other
than NISAR, such as Sentinel and others?"). Nothing here is built yet. Registry rows: `cosmic2-ro`, `hydrognss-l1`,
`sentinel6-ro`, `metop-gras`, `smap-rfi`, `sentinel1-rfi`, `alos2-scansar`, `saocom-l1`, `biomass-l1`, `smos-rfi`,
`sentinel-gnss-rinex`, `sat-jam`. Step E (the Sentinel navigation receivers) and the collectors section were merged in
the same day from a separate build note of Tom's.

## Why

- **Two orbital sensors are in use today, and both have limits.**
  - **CYGNSS** (`docs/validation/cygnss.md`) is validated against the aircraft map, with AUC 0.974 over a year. It
    sees only between ±38° latitude, and its end is near. Our daily run processed 24 Oct on 30 Oct. Catalogues give an
    end of life of Sep 2026 (eoHandbook) and a projected deorbit in 2027, and NASA has asked for partners to keep it
    flying (Military & Aerospace, 2026).
  - **NISAR** (`nisar/README.md`) hears 1219–1239 and 1291–1296 MHz, and only on passes in a mode that can hear the
    signal.
- **Nothing we run covers the Baltic, Kola or the Arctic at GPS L1** today. That is where the aircraft map is busiest
  and where NISAR's 5 MHz mode is deaf. The Sentinel navigation receivers (step E) do, from polar orbits, and they also
  cover the North Pacific and other areas where aircraft reports are thin.

## What each source can hear

| Source | What it receives | Ground it can see | Access and terms | Verdict |
|---|---|---|---|---|
| **COSMIC-2** radio occultation (6 satellites, 24° inclination, about 550 km) | GPS L1 C/A and L2 directly, on its navigation (POD) antennas and occultation antennas | Receiver within ±24°. An emitter is in view up to about 45° latitude at the horizon (geometry, not measured), so the Gulf, Levant, Iraq, Iran, Red Sea, Africa and South Asia, but not the Baltic | UCAR CDAAC, anonymous HTTPS. UCAR data terms (CC BY 4.0) | **Build first** |
| **HydroGNSS** (ESA Scout, 2 satellites, sun-synchronous, about 550 km; launched 28 Nov 2025) | Reflected GPS and Galileo at L1/E1 and L5/E5a, both circular polarizations, plus a measured noise power | Near-polar: the Baltic, Kola and the Arctic | Open since 31 Jul 2026 after registration at hydrognss.org (ESA owns the data, SSTL runs it). No terms found on the pages read | **Build after Tom registers** |
| **Sentinel-6A** and **Metop GRAS** radio occultation | GPS L1/L2 directly | Near-polar orbits, so Eastern Europe and the Baltic | Sentinel-6 L1B at NASA GES DISC (Earthdata token, which we have). Metop through the EUMETSAT Data Store (account). Terms not read for either | **Probe, then decide** |
| **SMAP** radiometer | 1400–1427 MHz (the protected passive band), with on-board RFI detection | Global | NSIDC, Earthdata login. NASA open data (CC0), citation required | **Build as an emitter layer** |
| **Sentinel-1** RFI annotation | C-band, 5.405 GHz | Global | Built (`tools/s1_rfi.py`). Copernicus terms allow republishing | **Decide: public region layer or keep private** |
| **Sentinel-1C/1D, -2B/2C and -3A/3B** navigation receivers (sun-synchronous, about 693–814 km) | GPS L1 and L2 directly, plus L2C and Galileo E1/E5a on the newer units; signal strength every 10 s | Near-global, including the Baltic, Kola, the Arctic and the North Pacific | Copernicus Data Space Ecosystem: anonymous catalogue, download with S3 keys (set 30 Oct). Copernicus terms allow republishing with credit | **Build (step E)** |

**What COSMIC-2 files hold** (measured 30 Oct 2026; day 302 is 29 Oct):
- **Live:** the near-real-time files for 29 Oct were posted at 04:32 UTC on 30 Oct (11:32 PM CDT on 29 Oct).
- **`podTc2` (navigation-antenna links, 458 MB a day):**
  - One file per receiver–GPS link, at 1 Hz.
  - Each sample carries `RFI`, a "Radio Frequency Interference index" (unitless; the attribute `RFI_threshold` is 1e-4;
    fill −999), plus `caL1_SNR`, `pL2_SNR`, link elevation, occultation height, TEC, S4, and both satellites' positions.
  - This is the RFI index UCAR has described since 2022. It is not published as a separate file.
- **`conPhs` (occultations, 2.67 GB a day):** high-rate `caL1Snr`, `pL1Snr`, `pL2Snr`, excess phase and `occheight`.
  This is what Wu (2024) reads at deeply occulted heights (−140 km), where any signal above noise counts as jamming.
- **A first look, not a test:**
  - Sample: 91 links from the first minutes of 29 Oct.
  - Share of samples above the threshold: 37–48% while the receiver was over the Bay of Bengal and Myanmar, against
    0–5% over the open Pacific and Atlantic.
  - These are receiver positions, not emitter positions.

## Build steps

COSMIC-2 first, because it needs no account and its index already exists. HydroGNSS as soon as Tom has access. Each
lane writes its checks into `docs/validation/` with a timestamp before any test day is fetched, as CYGNSS did.

### C: COSMIC-2 (GPS L1/L2, low latitudes)

| # | Step |
|---|---|
| C1 | `tools/cosmic2_rfi.py` (commands `fetch` and `day`): stream a day's `podTc2` archive, keep per-link rows (time, receiver position, link direction, elevation, RFI index, L1 and L2 SNR), drop the rest. About 458 MB in, a few MB out |
| C2 | **Locate.** The receiver hears an emitter anywhere within about 2,500 km, so one link says little. Back-project each flagged and unflagged sample along its link's ground-facing view, as `s1_rfi.py` does with stripes. Score cells by flagged share over all samples that could see them. Test it offline with synthetic emitters first. Freeze the method and the threshold (start from UCAR's 1e-4) before C3 |
| C3 | **Checks, pre-registered:** (1) place: score against the aircraft map's jammed and clean cells on the CYGNSS validation days, with AUC reported at region scale (stated before running); (2) change: the March 2026 Gulf surge must show, as it did for aircraft and CYGNSS; (3) quiet controls (central Pacific, South Atlantic, Australia) stay below a stated share; (4) agreement with CYGNSS on the same days and cells |
| C4 | If C3 passes: a daily job (GitHub Actions; global, so no watch configuration) uploading `<day>.cosmic2.json` to a `cosmic2-data` release, and a map layer, "GPS interference seen from orbit (COSMIC-2)". If it fails: the write-up says so and the data stay out of the map |
| C5 | Optional: the Wu (2024) indicator from `conPhs` (2.67 GB a day) as a second, independent COSMIC-2 measure |

### H: HydroGNSS (GPS/Galileo L1 and L5, high latitudes)

| # | Step |
|---|---|
| H0 | **Tom:** register at hydrognss.org and read the terms. Record them in `hydrognss-l1`. **Done 30 Oct:** registered, and the ESA terms are recorded; credentials pending |
| H1 | Probe one Level 1 file: whether users get delay-Doppler maps with delay rows ahead of the reflection (the noise rows the CYGNSS method reads), at L1 and L5, and how the measured noise power is reported |
| H2 | Port the CYGNSS indicator (noise floor over gain against a same-day baseline per spacecraft and antenna), for L1 and, new, L5 |
| H3 | **Checks, pre-registered:** the Baltic, Kola and Finnmark against the aircraft map; quiet controls; and the overlap band (35–38°) against CYGNSS on the same days |
| H4 | Extend the map's CYGNSS layer north, or add a second layer. Only two satellites: the arXiv paper 2606.14056 (Jun 2026) finds the largest gains in persistence monitoring between one and three satellites, so expect weekly rather than daily maps (an inference, not measured) |

### P: Polar radio occultation (Sentinel-6, Metop GRAS)

| # | Step |
|---|---|
| P0 | Probe Sentinel-6A L1B at GES DISC: whether SNR profiles are present, or only bending angles. Read its terms |
| P1 | Only if P0 has no SNR: Tom opens a EUMETSAT Data Store account for Metop GRAS |
| P2 | Indicators: missed and degraded occultations per region (the EUMETSAT approach) and deep-occultation SNR (Wu's) |
| P3 | **Check:** EUMETSAT reports a rise in missed and degraded GRAS occultations from 2021 to 2024, "particularly in Eastern Europe" (Parra Ortega, 13 Sep 2024). Reproduce that, then test against the Baltic aircraft map |

### R: SMAP (1400–1427 MHz emitters)

| # | Step |
|---|---|
| R0 | Probe the SMAP L1B brightness-temperature product's RFI flags (registry `smap-rfi`) for one day: size and fields |
| R1 | Weekly flagged share per cell, using ascending and descending footprint crossings to narrow positions |
| R2 | **Check, pre-registered:** long-range L-band air-surveillance radars with public positions (the FAA site file, `open-air-data-atc-radar`) should stand out. Unverified premise: that their out-of-band emissions reach 1400–1427 MHz. A miss tests that premise too |
| R3 | If R2 passes: add to the map's emitter layer beside NISAR, labelled by band. It shows radars, not GPS jammers |

### S: Sentinel-1 (C-band)

- **Built:** `tools/s1_rfi.py`, with results in `docs/validation/s1-rfi.md`.
- **Results:** it failed the site-location check on 24 Oct, but it shows region-scale C-band activity reliably: 82%
  of bursts flagged over the Gulf, none at the quiet control.
- **Option:** a public weekly map of C-band radar activity by region, never as sites. That needs global coverage
  rather than private boxes. The volume is unmeasured, but it should be a few hundred MB of small files a day.

### E: Sentinel-1, -2 and -3 navigation receivers (GPS L1/L2, Galileo E1/E5a; near-global)

- **The method follows SAT-JAM** (K. Bostani Nezhad, DTU; sat-jam.com), which maps the share of weak-signal
  observations from these same files. SAT-JAM uses six units: Sentinel-1C, 1D, 2B, 2C, 3A and 3B.
- **Sentinel-6A belongs to step P,** built as `tools/s6_rfi.py` from NASA PO.DAAC's 1 Hz RINEX. That copy has a
  higher rate and a shorter lag than the Copernicus one.

**What the files hold** (measured 30 Oct 2026):
- **Product:** Copernicus POD Service "L1B Rinex" (`AUX_GNSSRD`). Each unit has one TGZ a day, holding a RINEX 3.03
  observation file (`.DBL`) and an XML header (`.HDR`).
- **Sampling:** 10 s. Sentinel-2C's file for 24 Oct has 8,640 epochs, no gaps and a median of 17 satellites tracked.
- **Signals,** from the header's `SYS / # / OBS TYPES` lines:
  - **Sentinel-1C, 1D and 2C** (PODRIX receivers): GPS signal strength S1C, S1W, S2W and S2L; Galileo S1C and S5Q.
  - **Sentinel-2B, 3A and 3B** (RUAG receivers): GPS only, S1C, S1W and S2W.
- **Levels** (Sentinel-2C, 24 Oct):
  - GPS L1 C/A median 45.7 dB-Hz (5th–95th percentile 36.7–53.6).
  - Galileo E1 median 43.6 dB-Hz.
  - The header says "Temperature-dependent code and SNR biases applied".
- **Lag:** all seven units, including Sentinel-6A, posted 24 Oct between 11:44 and 12:33 UTC on 30 Oct, so the data run
  about six days behind. SAT-JAM gives one to three weeks for its map.
- **Size:** about 5.3 MB a day for Sentinel-1C, 1D and 2C, 2.9 MB for 2B, and 28 MB each for 3A and 3B. That is about
  75 MB a day for the six units.
- **Archive:** online back to at least March 2025 (Sentinel-2B and 2C, 1–3 Mar 2025), so the March 2026 Gulf surge can
  serve as a check.
- **Access:**
  - Catalogue: anonymous OData.
  - Download: the S3 endpoint `eodata.dataspace.copernicus.eu`, with keys in the user variables `CDSE_S3_ACCESS_KEY` and
    `CDSE_S3_SECRET_KEY` (Tom, 30 Oct). A signed download worked that day.
  - The free quota is 12 TB a month.
- **Terms:** Copernicus Sentinel data are free, including for commercial use. Credit: "Contains modified Copernicus
  Sentinel data 2026".
- **Announced gaps:** Sentinel-1D data were unavailable on 28 Oct, and Sentinel-3B made a manoeuvre on 29 Oct (CDSE news,
  30 Oct).

**Limits to carry into any caption:**
- **A flagged cell shows where the satellite was, not the emitter.**
  - The navigation antenna points away from Earth, so a ground emitter reaches it through side and back lobes.
  - The geometric horizon is about 2,850 km from Sentinel-1 and about 3,060 km from Sentinel-3.
  - The distance at which a real jammer shows up depends on its power. It is unmeasured here, and E3 measures it.
- **Spoofing may not show.** The indicator sees jamming, which lowers signal strength; spoofing often uses strong
  signals (SAT-JAM's own caveat).
- **Two confounders get flagged, not removed:**
  - geomagnetic storms (Kp ≥ 5);
  - brief, wide-area L1 interference that Clements, Kriezis and Humphreys trace to Russia's EKS early-warning
    satellites ("Chasing Lightning", arXiv:2606.03673, Jun 2026; not yet read here).

| # | Step |
|---|---|
| E0 | **Done 30 Oct:** access, file contents, lag, sizes and archive depth, as above |
| E1 | `tools/sentinel_gnss.py` (commands `fetch` and `day`): catalogue query, signed S3 download, RINEX parse. Keep, per link and epoch: time, unit, PRN, signal, signal strength, and the GNSS satellite's elevation and azimuth in the spacecraft's local frame (zenith-pointing antenna assumed). Spacecraft position comes from Space-Track elements and SGP4: a few km of error, small against cells about 300 km across; the Copernicus orbit files are optional. GNSS positions come from broadcast navigation (`station_cn0.parse_nav`, `sat_xyz`). A few MB a day out |
| E2 | **Indicators, frozen before E3.** (a) SAT-JAM's, for comparison: per unit and signal, z < −1 against the global mean. (b) Ours, shared with step P: a trailing 30-day signal-strength baseline per unit, signal and 5° elevation bin; per epoch, the median residual across links and the number tracked, so jamming shows as a drop on every link at once. (c) Back-projection to cells as in `cosmic2_rfi.py`. E imports the step P functions rather than writing a second version |
| E3 | **Checks, pre-registered** in `docs/validation/sentinel-gnss.md` before any test day is fetched: (1) place: region-scale AUC against the aircraft map's jammed and clean cells on the CYGNSS validation days; (2) change: the March 2026 Gulf surge must show; (3) the Baltic and Kaliningrad must show, since no other orbital L1 source reaches them; (4) quiet controls (central Pacific, South Atlantic, Australia) stay below a stated share; (5) agreement with SAT-JAM's map for the same window (by eye, since it has no export), and with COSMIC-2 and CYGNSS where they overlap; (6) Kp ≥ 5 days and EKS events are flagged |
| E4 | If E3 passes: a weekly job and a `sentinel-gnss-data` release (`<week>.sentinel-gnss.json`: cell, observations, flagged share, units, window). A map layer, "GPS interference seen from orbit (Sentinel)", goes live only after Tom says yes. Its caption carries the limits above and credits Copernicus and SAT-JAM's method. If E3 fails, the write-up says so and the data stay off the map |
| E5 | Watch areas in `private/watch/` read the same weekly files for private products. No areas go in this repo |

## Collectors for ground truth and context

Same build note. These give the orbital layers something to check against: official notices and outage records.

| Source | Status | Next |
|---|---|---|
| NGA MSI navigation warnings | Running in `collectors/watch.py` (the `smaps` endpoint; the older `broadcast-warn` endpoint froze on 10 May 2024) | Tag warnings that cross test and range areas from a private list |
| FAA GPS test notices | Running (`pipeline/faa_gps_tests.py`) | None |
| FAA NOTAM Management Service (`faa-notam`) | Not built. API credentials by request to NOTAMS@faa.gov | Tom requests access; GNSS NOTAMs then enter events as declared items |
| Cloudflare Radar (`cloudflare-radar`) | Read-only token set 30 Oct (`CLOUDFLARE_RADAR_TOKEN`, Account › Radar › Read); a test call worked. Terms: CC BY-NC 4.0 | A `watch.py` source for traffic anomalies and outage annotations: Starlink (AS14593) and watched countries, private digest first |
| IODA (`ioda`) | Not built: responses say "All Rights Reserved" | Permission request (DESIGN decision 4) |
| KingOfSat (`kingofsat`) | Running privately in `watch.py`; the pages its robots.txt disallows are never fetched | Nothing published. A listing change is not a reception report |
| ITU RRB, Kratos public posts (`kratos-public`), national regulators | Not built | A page-change monitor (URL, hash, title, time) whose changes an analyst reads. Cite only |

## Decisions for Tom

**Tom, 30 Oct 2026:**
- **Every option is to be developed,** including those listed under "Not pursued now", where access allows.
- **Tom registered at hydrognss.org the same day;** credentials are due within a few working days.
- **ESA's terms** (ESA-EOPG-PDGS-PR-1, issue 1.1, 20 Sep 2023, with the ESA Data Policy) cover HydroGNSS, SMOS and
  Biomass:
  - Results may be published, with the credit "Data provided by the European Space Agency (ESA)" and "© ESA" plus the
    year of reception.
  - The data themselves may not be republished.
  - ESA asks for a copy of any publication, sent to eopi@esa.int.
- **Publishing:** each lane still stops before the public map. A layer goes live only after its checks pass and Tom
  says yes.

| # | Decision | Recommendation |
|---|---|---|
| D1 | Order | C, then H once registered, then R, then P |
| D2 | HydroGNSS registration | Tom registers (accounts are Tom's) |
| D3 | Where COSMIC-2 runs | GitHub Actions, daily, with a new `cosmic2-data` release in this repo. No credentials are needed and nothing is watch configuration |
| D4 | Sentinel-1 public layer | Later, after C. It shows radars, while the site's headline is GPS interference |
| D5 | EUMETSAT account | Only if Sentinel-6 L1B lacks SNR (P0) |
| D6 | Where E runs | This PC, weekly, from the 06:30 collectors task, where the keys already are. Move to GitHub Actions after E3 passes; Tom then sets two repository secrets |
| D7 | SAT-JAM exports | Tom emails the author (kbone@dtu.dk, as given on sat-jam.com) for cell exports, code and the paper, so E3 compares numbers rather than images |
| D8 | Cloudflare Radar | Private digest first. A public layer needs its own check that a traffic drop means a service outage |

## Not pursued now

| Source | Why |
|---|---|
| **ALOS-2 PALSAR-2 ScanSAR** (1257.5 MHz) | JAXA's free L2.2 data run Aug 2014 – Jul 2025 (JAXA page, 30 Oct), so they are history only. Terms are "per platform", and ASF's EULA is non-commercial (allowed since 29 Oct if republishing derived maps is permitted; unread). No RFI tables, so interference must be found in the images |
| **SAOCOM** (1275 MHz) | Access depends on ASI or CONAE approving a project; not open data |
| **Biomass** (P-band, 435 MHz) | Open since 26 Jan 2026, but switched off over Europe and North America to protect US space-tracking radars. It might show UHF radars elsewhere: exploratory |
| **SMOS** (1400–1427 MHz) | Same band as SMAP. ESA's terms limit onward sharing (row `smos-rfi`) |
| **Spire, PlanetiQ, Yunyao** radio occultation | Commercial, paid. EUMETSAT's 2024 comparison includes them |

## Sources

- Wu, D. L. (2024). "GNSS Signal Jamming as Observed from Radio Occultation." *IEEE JSTARS*, doi:10.1109/JSTARS.2024.3385738. Abstract read at https://espo.nasa.gov/attrex/node/104579
- Song et al. (2024). COSMIC-2 RFI prediction model. *Sensors* 24, 7745. https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11645085/
- UCAR, COSMIC-2 POD RFI risk mapping: https://impacts.ucar.edu/en/publications/gnss-radio-frequency-interference-risk-mapping-of-cosmic-2-pod-an/
- COSMIC-2 data (read 30 Oct 2026): https://data.cosmic.ucar.edu/gnss-ro/cosmic2/nrt/
- Parra Ortega, M. J. (EUMETSAT), "Assessing the impact of Radio Frequency Interference on GNSS Radio Occultation Measurements", 13 Sep 2024: https://www.cosmic.ucar.edu/sites/default/files/2024-09/11%20-%20ParraOrtega_M_2024.09.13.pdf
- ESA, "HydroGNSS data open for new insights into Earth's water", 31 Jul 2026: https://www.esa.int/Applications/Observing_the_Earth/FutureEO/HydroGNSS/HydroGNSS_data_open_for_new_insights_into_Earth_s_water
- HydroGNSS products and access: https://www.hydrognss.org/data-products/product-explanation/ and https://www.hydrognss.org/data-products/access-and-tools/
- eoPortal, HydroGNSS (orbit): https://www.eoportal.org/satellite-missions/hydrognss
- Boumeftah, Klimas and Kurt (Jun 2026), arXiv 2606.14056: https://arxiv.org/abs/2606.14056
- Sentinel-6A EUMETSAT GNSS-RO L1B at GES DISC: https://catalog.data.gov/dataset/sentinel-6a-eumetsat-gnss-ro-non-time-critical-level-1b-v1-s6a_ro_1b_bnd_____-at-ges-disc
- SMAP status: https://database.eohandbook.com/database/missionsummary.aspx?missionID=614 ; monthly RFI maps: https://salinity.oceansciences.org/smap-radiometer.htm
- CYGNSS: https://database.eohandbook.com/database/missionsummary.aspx?missionID=740 ; https://www.militaryaerospace.com/sensors/article/55356733/nasa-issues-partnership-call-to-continue-cygnss-satellite-data-collection
- JAXA, PALSAR-2 ScanSAR L2.2: https://www.eorc.jaxa.jp/ALOS/en/dataset/palsar2_l22_e.htm ; ASF EULA: https://asf.alaska.edu/?p=16104
- SAOCOM: ASI, June 2025: https://www.asi.it/wp-content/uploads/2025/06/Sacco_ASI_SAOCOM.pdf
- Bostani Nezhad, K. (2026). SAT-JAM: Satellite GNSS Interference Map (method and author pages read 30 Oct 2026): https://sat-jam.com
- Copernicus Data Space Ecosystem (read 30 Oct 2026): S3 access https://documentation.dataspace.copernicus.eu/APIs/S3.html ; quotas https://documentation.dataspace.copernicus.eu/Quotas.html ; OData catalogue https://documentation.dataspace.copernicus.eu/APIs/OData.html
- Clements, Kriezis and Humphreys (Jun 2026), "Chasing Lightning", arXiv 2606.03673 (cited from secondary reports; not yet read): https://arxiv.org/abs/2606.03673
- Cloudflare Radar API data under CC BY-NC 4.0 (read 30 Oct 2026): https://developers.cloudflare.com/radar/
- ESA, Biomass data open (26 Jan 2026): https://www.esa.int/Applications/Observing_the_Earth/FutureEO/Biomass/ESA_s_Biomass_goes_live_with_data_now_open_to_all ; SOTR restriction: https://hal.archives-ouvertes.fr/hal-01807817
