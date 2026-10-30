# Interference seen from orbit, beyond NISAR: plan

Written 30 Oct 2026 at Tom's request ("what can we do to bring in potential observed interference from satellites other
than NISAR, such as Sentinel and others?"). Nothing here is built yet. Registry rows: `cosmic2-ro`, `hydrognss-l1`,
`sentinel6-ro`, `metop-gras`, `smap-rfi`, `sentinel1-rfi`, `alos2-scansar`, `saocom-l1`, `biomass-l1`, `smos-rfi`.

## Why

- **Two orbital sensors are in use today, and both have limits.**
  - **CYGNSS** (`docs/validation/cygnss.md`) is validated against the aircraft map, with AUC 0.974 over a year. It
    sees only between ±38° latitude, and its end is near. Our daily run processed 24 Oct on 30 Oct. Catalogues give an
    end of life of Sep 2026 (eoHandbook) and a projected deorbit in 2027, and NASA has asked for partners to keep it
    flying (Military & Aerospace, 2026).
  - **NISAR** (`nisar/README.md`) hears 1219–1239 and 1291–1296 MHz, and only on passes in a mode that can hear the
    signal.
- **Nothing in orbit covers the Baltic, Kola or the Arctic at GPS L1** today. That is where the aircraft map is busiest
  and where NISAR's 5 MHz mode is deaf.

## What each source can hear

| Source | What it receives | Ground it can see | Access and terms | Verdict |
|---|---|---|---|---|
| **COSMIC-2** radio occultation (6 satellites, 24° inclination, about 550 km) | GPS L1 C/A and L2 directly, on its navigation (POD) antennas and occultation antennas | Receiver within ±24°. An emitter is in view up to about 45° latitude at the horizon (geometry, not measured), so the Gulf, Levant, Iraq, Iran, Red Sea, Africa and South Asia, but not the Baltic | UCAR CDAAC, anonymous HTTPS. UCAR data terms (CC BY 4.0) | **Build first** |
| **HydroGNSS** (ESA Scout, 2 satellites, sun-synchronous, about 550 km; launched 28 Nov 2025) | Reflected GPS and Galileo at L1/E1 and L5/E5a, both circular polarizations, plus a measured noise power | Near-polar: the Baltic, Kola and the Arctic | Open since 31 Jul 2026 after registration at hydrognss.org (ESA owns the data, SSTL runs it). No terms found on the pages read | **Build after Tom registers** |
| **Sentinel-6A** and **Metop GRAS** radio occultation | GPS L1/L2 directly | Near-polar orbits, so Eastern Europe and the Baltic | Sentinel-6 L1B at NASA GES DISC (Earthdata token, which we have). Metop through the EUMETSAT Data Store (account). Terms not read for either | **Probe, then decide** |
| **SMAP** radiometer | 1400–1427 MHz (the protected passive band), with on-board RFI detection | Global | NSIDC, Earthdata login. NASA open data (CC0), citation required | **Build as an emitter layer** |
| **Sentinel-1** RFI annotation | C-band, 5.405 GHz | Global | Built (`tools/s1_rfi.py`). Copernicus terms allow republishing | **Decide: public region layer or keep private** |

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
- ESA, Biomass data open (26 Jan 2026): https://www.esa.int/Applications/Observing_the_Earth/FutureEO/Biomass/ESA_s_Biomass_goes_live_with_data_now_open_to_all ; SOTR restriction: https://hal.archives-ouvertes.fr/hal-01807817
