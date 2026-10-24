# CYGNSS noise-floor lane: first validation (23 Oct 2026)

**Lane:** spaceborne (planned, Phase 7). **Tool:** `tools/cygnss_rfi.py`, tests in `tests/test_cygnss_rfi.py`.
**Data:** NASA CYGNSS Level 1 Science Data Record V3.2 (PO.DAAC), six UTC days: 2 Jan, 24 Feb, 9, 10 and 16 May, and 19 Oct 2026.
**Reference:** the project's aircraft map, H3 res-4 daily tables in `data/pnt/year/<day>.parquet`, aggregated to res 3.

## Bottom line

- **CYGNSS sees GNSS interference from orbit, and the aircraft map agrees where both can look.**
  - Indicator: the DDM noise floor (power in the delay rows ahead of any surface reflection), normalised by instrument gain and compared with a same-day baseline for the same spacecraft, antenna and land/sea mix.
  - Over 11,463 cell-days with 20+ aircraft, the indicator separates aircraft-jammed cells (share ≥ 10%, n = 92) from aircraft-clean cells (share < 2%, n = 11,185) with **AUC 0.98**.
  - At a 1 dB threshold, chosen before the comparison, it catches **98% of the jammed cells**.
  - The median excess rises with aircraft share: −0.03 dB (< 2%), 2.2 dB (2–5%), 2.3 dB (5–10%), 3.5 dB (10–25%), 4.0 dB (≥ 25%).
- **It tracks change as well as place.**
  - In the Persian Gulf, aircraft share went from 0.5% (Jan, Feb) to 39–53% (May) and back to 2.4% (Oct).
  - CYGNSS went 1.9–2.0 dB → 3.6–4.2 dB → 3.5 dB over the same days: the same order on all six days.
- **Quiet controls stay quiet.**
  - 0.8% of 11,751 control cell-days read ≥ 1 dB (central Pacific, South Atlantic, interior Brazil, Australia, southern Africa).
  - Box medians run from −0.26 to +0.46 dB.
- **"False alarms" against aircraft are mostly not random.**
  - 16% of aircraft-clean cells read ≥ 1 dB, but most lie inside or near regions with published interference reports, where antenna smear and spoofing (which need not degrade NACp) are expected.
  - More than 2,000 km from those regions, the rate is **3.2%** (1.6% below 33° latitude), and most of the rest is over Japan, Korea and eastern China. Maritime advisories describe GNSS interference there; this is unverified for our days.
- **CYGNSS loses data inside the strongest interference.**
  - Every spacecraft has multi-minute gaps in the L1 series over Iraq, Iran and the Levant: up to 13 minutes per pass on 10 May, typically 1–4 minutes (at most 7) in January and February.
  - Counted as their own indicator, the dropouts are specific (1.7% false alarms at half the samples missing) but cover few cells.
  - The cause isn't confirmed. The spacecraft losing its own GPS fix is the likely candidate.
- **What CYGNSS adds:**
  - It covers the open sea and closed airspace: the Red Sea, Arabian Sea, Gulf of Oman, Iraq, Iran, Myanmar and Sudan.
  - About 80% of the cells it flags have no aircraft coverage, and a third of those are over water.
- **Limits:**
  - Location is coarse. The noise enters through an antenna beam a few hundred km wide, plus sidelobes, so one emitter lights up a region.
  - The validation positives come from four regions. Three-quarters of the 92 aircraft-jammed cells are in the Gulf, Gulf of Oman and UAE.
  - The sample is six days.
- **Next:**
  - Same-hour comparison against the hourly aircraft tables.
  - A test against a known emitter: an announced US test, or the Shiraz case already used in the NISAR lane.
  - A daily run.

## 1. Data and access

| Item | Value |
|---|---|
| Product | CYGNSS Level 1 Science Data Record **V3.2**, `CYGNSS_L1_V3.2`, CMR collection C2832195379-POCLOUD, DOI 10.5067/CYGNS-L1X32. Latest L1 science version in CMR on 23 Oct 2026. No RFI-specific or noise-floor product exists. |
| Licence | NASA open data. ESDIS treats data from NASA-led missions as CC0. Citation expected (registry id `cygnss-l1`). |
| Granules | One file per spacecraft per UTC day, about 1.1 GB each. Seven spacecraft files per day (cyg01–05, 07, 08) for the January–May days; six on 19 Oct (no cyg02). The days 20–21 Oct had 5 and 4 files on 23 Oct, still arriving. |
| Access | NASA cloud OPeNDAP (Hyrax, DAP4). The tool asks for 10 variables and every 2nd sample (1 Hz): about 5–6 MB per spacecraft-day, **205 MB for all six days** (data/cygnss/l1/, gitignored). Earthdata Login bearer token from the `EARTHDATA_TOKEN` environment variable, sent only in the request header. |
| Variables | `ddm_noise_floor`, `inst_gain`, `sp_lat`, `sp_lon`, `ddm_ant`, `quality_flags`, `quality_flags_2` (per DDM); `ddm_timestamp_utc`, `sc_lat`, `sc_lon` (per sample). |
| Land mask | Natural Earth 50 m land v5.1.2 (public domain), already cached by the project. |

## 2. Method

**Physics.**

- Each CYGNSS receiver correlates the signal from its nadir antenna with four GPS C/A codes every 0.5 s and writes four delay-Doppler maps.
- Surface reflections can only arrive at or after the specular delay. So the rows ahead of it carry no surface signal, only what the antenna hears that doesn't correlate with the code: scene brightness, receiver noise, background GPS energy and any interference.
- The L1 field `ddm_noise_floor` is the mean raw count over the first 45 of the 128 delay rows (netCDF comment).
- A jammer's power, spread by the correlation, raises that mean: across the whole map for wideband signals, along a Doppler stripe for narrowband ones.
- Chew, Roberts & Lowe (2023) mapped RFI hotspots worldwide from this quantity. Shin & Son (2026) built an epoch detector from the four channel values and validated it at White Sands against NOTAMs and ADS-B.

**Indicator, step by step.**

1. **Gain.** x = 10 log10(`ddm_noise_floor` / `inst_gain`). `inst_gain` (count/W, from the on-board black-body calibration) removes gain drift with LNA temperature. Gain settings were fixed at 33 dB on the spacecraft-day checked (FM04, 10 May); other spacecraft and days weren't checked.
2. **Baseline.** That day's median of x for the same spacecraft, same antenna (port or starboard) and same decile of footprint land fraction.
   - The land fraction is the Natural Earth mask at 0.25°, smoothed with a 1.5° Gaussian, roughly the main beam on the ground.
   - **Land footprints read 0.9–1.4 dB below open ocean.** The probable cause, background GPS energy scattered by the sea (Gleason et al. 2020 describe a variable background component), is unverified. Without this term, every continent looks quiet and every ocean noisy.
   - Large interference areas are kept out of their own reference: res-2 cells with a median excess of 1 dB or more (7–9% of DDMs each day) are dropped and the baseline recomputed, three passes.
3. **Excess** = x − baseline (dB). Per H3 res-3 cell (about 12,000 km²) the tool keeps:
   - the median excess, its 90th percentile, and the shares of DDMs ≥ 1 dB and ≥ 2 dB;
   - the shares carrying the product's own `rfi_detected` (kurtosis) and `poor_quality_bin_ratio` flags;
   - the number of separate overpasses.
   - Cells need 20+ DDMs to be judged; the median cell has about 70 from 5 passes.
4. **Excluded DDMs:**
   - black-body, idle, test-pattern, reconfigured or bad-attitude samples, and samples with the direct signal in the map;
   - `noise_floor_cal_error` (signal in the top rows, which is common over high terrain such as Tibet);
   - **wrong-antenna and sidelobe specular points.** The noise belongs to the antenna beam, not to the point (section 4).
5. **Dropouts.**
   - Multi-sample gaps in the 1 Hz series of each spacecraft are filled with interpolated sub-satellite positions, for gaps up to 15 minutes.
   - dropout = missing / (present + missing) per cell, by sub-satellite point, for cells with 30+ expected samples.
6. **Calls.** A cell is *elevated* at a median excess ≥ 1 dB (26% more noise power; fixed in advance). It *drops out* when half its expected samples are missing. It is *affected* if either holds.

**Comparison with aircraft.**

- Per res-3 cell, the aircraft share is the GPSJam-style sum over its res-4 children: Σ max(bad − 1, 0) / Σ aircraft, using `bad_nacp_live`.
- Cells with 20+ aircraft are paired. *Jammed*: share ≥ 10%. *Clean*: share < 2%.
- Metrics:
  - AUC: the chance a jammed cell scores above a clean one;
  - hit and false-alarm rates at fixed thresholds;
  - Spearman rank correlation, worldwide and over 0–42°N, 20–110°E;
  - fixed region boxes: nine with published interference reports, five quiet controls (coordinates in the tool).
- The boxes were set before the comparison and were not changed afterwards.

## 3. Results

### 3.1 Against the aircraft map, cell by cell (H3 res 3)

| Day (UTC) | Spacecraft | DDMs used | Paired cells | Jammed cells | AUC | Hit @ 1 dB | False alarm @ 1 dB | Spearman ρ (world / ME–Asia) | Samples missing |
|---|---|---|---|---|---|---|---|---|---|
| 2 Jan | 7 | 2,076,751 | 2,001 | 5 | 0.84 | 60% | 17.7% | 0.30 / 0.18 | 0.42% |
| 24 Feb | 7 | 1,967,236 | 2,014 | 1 | 0.96 | 100% | 15.6% | 0.17 / 0.14 | 0.37% |
| 9 May | 7 | 1,730,960 | 1,772 | 20 | 0.99 | 100% | 13.7% | 0.30 / 0.46 | 2.00% |
| 10 May | 7 | 1,734,512 | 1,767 | 24 | 0.99 | 100% | 13.9% | 0.32 / 0.50 | 2.20% |
| 16 May | 7 | 1,952,084 | 1,855 | 33 | 0.99 | 100% | 16.1% | 0.32 / 0.52 | 1.69% |
| 19 Oct | 6 | 1,678,564 | 2,054 | 9 | 0.98 | 100% | 17.5% | 0.31 / 0.38 | 0.88% |
| **Pooled** | | | **11,463** | **92** | **0.984** | **97.8%** | **15.9%** | **0.28 / 0.36** | |

Every ρ has p < 0.005. Pooled thresholds: 0.5 dB catches 100% with 28% false alarms; 1.5 dB, 96% and 8.3%; 2 dB, 91% and 5.1%. At res 2 (sensitivity check) the pooled AUC is 0.983, hit and false alarm at 1 dB are 97% and 15%, and ρ is 0.37 / 0.47.

![CYGNSS excess by aircraft share](img/cygnss_vs_aircraft_r3.png)

**Where the positives come from.**

- The 92 jammed cell-days:
  - 69 in the Gulf, Gulf of Oman and UAE;
  - 12 on the Myanmar–Thailand border;
  - 7 on the India–Pakistan border (all on 2 Jan and 19 Oct);
  - 4 in the Levant.
- So the AUC rests on four regions, mostly one, and repeated days aren't independent.
- **The misses.** The two misses at 1 dB and the two weakest hits are all on 2 Jan in Pakistan: Punjab near Lahore and the border, and near Islamabad (aircraft share 11–37%). CYGNSS read only 0.8–1.2 dB there. A time-of-day mismatch is possible: the aircraft share covers the whole day, CYGNSS a few passes.

### 3.2 Regions with published interference reports, and quiet controls

Median excess of the cells in each box (dB), per day: 2 Jan, 24 Feb, 9 May, 10 May, 16 May, 19 Oct.

| Box | CYGNSS median excess | Cells ≥ 1 dB | Dropout ≥ 50% (share of cells) | Aircraft share (GPSJam-style) |
|---|---|---|---|---|
| Levant | 3.5, 3.6, 2.8, –, 3.4, 3.5 | 100% every day | 0.12, 0, 0.94, 1.00, 0.85, 0.54 | 1.3, 0.0, 13.7, 6.0, 11.1, 3.0% |
| Egypt / Sinai / Suez | 3.2, 3.2, 2.5, 2.5, 3.1, 3.1 | 100% | 0–0.40 | 0.0–3.8% |
| Iraq | 3.8, 3.7, 3.5, 3.5, 3.9, 3.6 | 100% | 0.20, 0.11, 0.97, 1.00, 0.94, 0.58 | almost no aircraft |
| Persian Gulf | 1.9, 2.0, 3.6, 3.8, 4.2, 3.5 | 88–100% | 0, 0, 0.36, 0.35, 0.09, 0 | 0.5, 0.5, 39.4, 47.2, 53.2, 2.4% |
| Iran (interior) | 3.2, 3.2, 2.7, 3.9, 3.8, 3.2 | 100% | 0.17–0.91 | no aircraft |
| Red Sea | 1.7, 1.1, 2.8, 2.7, 2.5, 2.2 | 54–100% | ~0 | almost no aircraft |
| India–Pakistan border | 0.8, 0.4, 3.7, 3.3, 3.0, 2.5 | 3–100% | ~0 | 5.4, 2.4, 0.0, 0.1, 0.1, 2.0% |
| Myanmar | 2.7, 2.7, 2.6, 2.5, 2.8, 2.8 | 100% | 0 | 0.0–2.3% (few aircraft) |
| South China Sea | 0.9, 0.8, 0.7, 0.7, 0.6, 0.7 | 17–41% | 0 | 0.0–0.2% |
| *Central Pacific* (control) | −0.04 to 0.10 | 0–2% | 0 | – |
| *South Atlantic* (control) | −0.10 to 0.00 | 0% | 0 | – |
| *Brazil interior* (control) | −0.26 to −0.23 | 0% | 0–0.07 | 0.0% |
| *Australia interior* (control) | −0.01 to 0.46 | 0–10% | 0 | 0.0% |
| *Southern Africa interior* (control) | −0.12 to −0.06 | 0–1% | 0 | 0.0% |

- **Box-days elevated:** 46 of 54 (8 of the 9 boxes on every day). The exceptions are the South China Sea (median 0.6–0.9 dB, never ≥ 1) and the India–Pakistan border on 2 Jan and 24 Feb.
- **The Levant on 10 May** has no cells with 20+ DDMs: the whole box dropped out.
- **Persian Gulf:** the six-day ordering matches the aircraft ordering exactly (n = 6, so this is illustrative, not a test).
- **India–Pakistan border: the two maps disagree in time.**
  - The aircraft see more in Jan/Feb; CYGNSS sees much more in May (3.0–3.7 dB) and Oct.
  - The number of aircraft in the box fell from 4,126 (2 Jan) to 1,173–1,346 on the May days. We haven't checked for airspace restrictions.

![Middle East and South Asia, 10 May 2026](img/cygnss_2026-05-10_r3.png)

The 2 Jan map for comparison: [img/cygnss_2026-01-02_r3.png](img/cygnss_2026-01-02_r3.png). Whole band: [10 May](img/cygnss_world_2026-05-10_r3.png), [2 Jan](img/cygnss_world_2026-01-02_r3.png).

### 3.3 Dropouts: no data where interference is strongest

- **Scale and pattern.**
  - Each spacecraft's 1 Hz series has multi-minute holes on the passes over Iraq, Iran and the Levant, near the northern turning latitude.
  - On 10 May the seven spacecraft lost 2.2% of their day.
  - The holes began over the eastern Mediterranean or Egypt (20–38°E) and ended over Iran, Pakistan or India (45–77°E).
  - Elsewhere, gaps are rare and short.
- **On a single pass (figure below).** FM04, 10 May, 17:28–17:46 UTC (12:28–12:46 CDT):
  - the noise floor climbs on both antennas to +4 to +4.5 dB;
  - then the series stops for 6.4 minutes, from 29°N 38°E to 35°N 66°E;
  - it resumes still at +4.5 dB.
  - The line ends at 17:45 because the DDMs over Tibet fail `noise_floor_cal_error`.
- **What it means for the noise metric.** The hole is the core of the interference, so the noise floor is censored from above there. The core cells' 3.5–4 dB probably understates the true level.
- **Cause, unconfirmed.** It looks like the satellite losing its own GPS fix: the L1 processing needs a navigation solution. Data withheld on purpose would look the same. Radio-occultation receivers show a similar data void over the region (GPS World, March 2024; secondary, not read in full).
- **As an indicator:**
  - AUC 0.78; at ≥ 50% missing, 44% hit and 1.7% false alarms (39 jammed and 4,646 clean cell-days with enough samples);
  - the dropout cells grow from 17–19 per day (Jan/Feb) to 126–155 (May), the same direction as the aircraft maps.

![One pass with a data gap](img/cygnss_pass_2026-05-10_fm04.png)

### 3.4 Where CYGNSS reads high and aircraft read clean

Aircraft-clean cells with ≥ 1 dB, by distance from the nearest box with published reports (pooled, res 3):

| Distance | Clean cells | ≥ 1 dB | ≥ 2 dB |
|---|---|---|---|
| inside a box | 316 | 65.5% | 47.8% |
| < 500 km | 1,008 | 52.0% | 24.4% |
| 500–1,000 km | 923 | 26.1% | 4.6% |
| 1,000–2,000 km | 1,139 | 48.1% | 6.9% |
| > 2,000 km | 7,799 | 3.2% | 0.6% |

- **Eastern Mediterranean, Levant, Jordan, Egypt.**
  - Every aircraft-clean cell reads high, mostly above 2 dB. Examples from 2 Jan:
    - the Jordan–Syria border: 117 aircraft, share 0.0%, +3.9 dB;
    - Turkey's south coast, Antalya to Adana: 214–789 aircraft per cell, share 0–1%, +2.6 to +3.4 dB.
  - Two candidate reasons:
    - The beam and sidelobes reach the Syrian, Iraqi and Israeli emitters.
    - Spoofing is widely reported here (EASA SIB 2022-02R3), and a spoofed receiver can report good NACp, so the aircraft share can stay low while the RF environment is far from clean.
- **Gulf of Oman, Strait of Hormuz, Arabian Sea, Bay of Bengal.**
  - These read 1–2 dB with clean aircraft cells.
  - Maritime advisories name the Arabian Sea, Gulf of Oman and Hormuz (Marshall Islands Maritime Administrator, YSA 05-25, Oct 2025; MARAD 2019-012).
  - Smear from inland sources is the other candidate.
- **Japan, Korea, eastern China, the Taiwan Strait.**
  - These read 1–1.5 dB (rarely 2) on most days, with aircraft clean.
  - The same advisory reports interference in the East and South China Seas, the Yellow Sea, the Taiwan Strait and near the Korean Peninsula.
  - Not verified for our days.
- **Northern Mexico, 9–10 May (a lead, unverified).**
  - 20–22 of 25 cells in Sinaloa, Durango and Chihuahua read ≥ 1 dB (median +2 dB), on many passes from 03 to 12 UTC and on both antennas. That rules out the single-antenna artifact found in section 4.
  - The box read 0.2–0.5 dB on 2 Jan and 24 Feb, and about 0 on 16 May and 19 Oct.
  - Only about 300 aircraft cross it, all clean.
- **Quiet-ocean structure.**
  - Open oceans away from all boxes show a residual ±0.3–0.5 dB pattern: −0.5 dB toward ±36–40° in the eastern Pacific and Atlantic, +0.3 dB in the western Pacific.
  - The rise in the northern Indian Ocean toward the Arabian Sea and Bay of Bengal (+1 dB at 12–24°N) is larger and points at the sources around it.
  - The 1 dB threshold is two to three times the quiet structure.

### 3.5 What CYGNSS sees that aircraft can't

- **Scale.** Each day, 1,546–2,043 CYGNSS-affected cells have fewer than 5 aircraft, out of 1,940–2,465 affected cells in all. That is about 80%; 558–704 of them are mostly water.
- **The largest groups:**
  - the Red Sea (75–133 cells a day);
  - Iran and Iraq (closed or empty airspace);
  - Myanmar;
  - Sudan, South Sudan, Eritrea, Ethiopia and the Horn of Africa;
  - Yemen and Somalia, the Arabian Sea and Gulf of Oman;
  - Afghanistan and western Pakistan;
  - the seas around Taiwan and Okinawa.
- **Caveat.** "Seen over the sea" is not "emitter at sea": a coastal or inland source lights up the water within reach of the beam.
- **Inland water.** Chew et al. (2023) caution that calm inland water can mimic hotspots.
  - One spot check on 10 May (FM04, Sudan and South Sudan, 0–10°N 20–40°E, +1.1 dB) showed excess *anti*-correlated with reflected signal strength (`ddm_snr`, Pearson r = −0.25).
  - That points to external noise, not reflection, but it is a single check.
  - Ethiopia's highlands read 0.4–1.4 dB on the four days checked. Chew et al. reported a Tigray hotspot from 2020–2022.

### 3.6 Other indicators on the same cells (pooled AUC, jammed vs clean)

| Indicator | AUC | Note |
|---|---|---|
| Noise-floor excess (this lane) | **0.984** | 1 dB: 98% hit, 16% false alarm |
| Share of DDMs with the product's `poor_quality_bin_ratio` flag | 0.949 | ADC bit-count ratio; nearly as good, and needs no baseline |
| Change against the cell's own median on the other days | 0.815 | 1 dB: 54% hit, **1.5%** false alarm. Finds new interference and misses persistent interference. |
| Dropout share | 0.782 | Few cells, very specific |
| Share with the product's `rfi_detected` (kurtosis) flag | 0.711 | Weakest, as Chew et al. 2023 and Shin & Son 2026 found |

## 4. Mistake found and fixed during the work

The first run kept DDMs flagged `incorrect_ddmi_antenna_selection`, because the flag is far more frequent in the Gulf (36%) and Levant (88%) than worldwide (16%), and dropping it looked like dropping signal. That was wrong. The flag is frequent there because those regions sit near the ±35° turning latitude, not because of interference. On 9 May the starboard antenna, looking south from about 35°N, logged specular points at 36–40°N over Nevada, Colorado and Kansas (97–99% flagged) at +2 dB while the port antenna on the same passes read −0.2 dB. Aircraft over those states were clean. The noise belongs to the beam, so a point outside it puts the noise in the wrong place. The tool now drops wrong-antenna and sidelobe points (`sp_in_sidelobe`), about 24% of DDMs. The western-US "hotspots" vanished, and the false-alarm rate against aircraft fell from 18.5% to 15.9% with the hit rate unchanged.

## 5. Limits

- **Coarse location.**
  - The antenna beam spans a few hundred km on the ground. A strong source is also heard in the sidelobes out to the radio horizon (about 2,500 km from 520 km altitude).
  - Gridding by specular point (main-lobe points only) spreads one emitter over a region.
  - The maps say where receivers in orbit were exposed, not where a transmitter is.
- **Censoring in the core.** Dropouts remove the strongest-interference samples, so core cells are biased low, and some (the Levant on 10 May) have no noise value at all.
- **Few independent positives.** 92 jammed cell-days from four regions, three-quarters in one. The AUC would not survive a region-held-out test on this sample. Controls and far-field rates are the stronger evidence of specificity.
- **Different clocks.**
  - Aircraft share is a whole-day aggregate weighted by traffic; CYGNSS is a handful of passes at fixed times on each day.
  - Intermittent jammers will disagree for that reason alone.
  - The hourly aircraft tables exist but weren't used yet.
- **The aircraft reference is imperfect.** NACp responds to jamming more reliably than to spoofing, and coverage is thin exactly where interference is heaviest.
- **Baseline residue.**
  - About ±0.4 dB of latitude and ocean-basin structure remains in quiet areas.
  - The land/ocean offset is empirical and its cause unverified.
  - Wet soil and inland water could raise weak land signals. Not tested.
- **Coverage gaps.**
  - Nothing poleward of about ±38°: no Baltic, Black Sea, Caucasus or Kaliningrad.
  - High terrain such as Tibet is masked by `noise_floor_cal_error`.
  - Latency: the newest days arrive over several days (5 of 7 files for 20 Oct on 23 Oct).
- **Six days.** One day each in January, February and October, three in May.

## 6. Next steps

1. **Same-hour comparison.** Match each CYGNSS pass to the aircraft share in the same hour and H3 cell (the `.hourly.parquet` tables). That should explain the 2 Jan Punjab misses and part of the false alarms.
2. **Known emitters.**
   - Score CYGNSS against FAA-announced GPS tests (`data/declared/faa_gps_tests.json`, used by the site's events panel) inside ±38°: White Sands, China Lake, the Nevada ranges.
   - Score it against the Shiraz case from the NISAR lane, using days when the jammer was reported on and off.
3. **Localisation.** Fit an emitter position from the antenna gain pattern and pass geometry (beam-weighted back-projection) instead of gridding by point, as Chew et al. did with boresight positions.
4. **Dropouts.** Find the cause (CYGNSS team, data notes), and check whether the zenith navigation signal (`zenith_sig_i2q2`) collapses before each gap.
5. **Region-held-out test.** Once more days are processed, report AUC with one region left out at a time.
6. **Daily run.** CMR search and subset fetch are cheap (about 36 MB a day). Output would go to the site only after Tom's review, with the CYGNSS citation and the location caveat on the map.
7. **Registry.** `registry/sources.csv` row `cygnss-l1` still says "later". Update it when the lane is adopted.

## 7. Reproduce

```
python tools/cygnss_rfi.py fetch 2026-01-02 2026-02-24 2026-05-09 2026-05-10 2026-05-16 2026-10-19   # needs EARTHDATA_TOKEN
python tools/cygnss_rfi.py grid 2026-01-02 2026-02-24 2026-05-09 2026-05-10 2026-05-16 2026-10-19
python tools/cygnss_rfi.py validate 2026-01-02 2026-02-24 2026-05-09 2026-05-10 2026-05-16 2026-10-19 --figures --map-days 2026-05-10 2026-01-02
python tools/cygnss_rfi.py grid --res 2 <same days> && python tools/cygnss_rfi.py validate --res 2 <same days>
python tools/cygnss_rfi.py pass 2026-05-10 --sc 4 --hours 17.45 17.80
python tests/test_cygnss_rfi.py
```

Outputs: `data/cygnss/grid/<day>.r3.parquet` (per cell: n, passes, med_db, p90_db, frac1, frac2, rfi_flag, bin_flag, land, sub_present, sub_missing, dropout) and `data/cygnss/validation_r3.json`. All under the gitignored `data/`. Runtime needs numpy, scipy, h5py, requests and h3 (all in `nisar/requirements.txt`), plus pyarrow and matplotlib (`requirements.txt`). The tests need only numpy, h3 and matplotlib.

## Sources

Retrieved 23 Oct 2026 unless noted. "Via Shin & Son" means cited from that paper's reference list, not read directly.

- NASA CYGNSS L1 V3.2: CMR collection C2832195379-POCLOUD and granule records (queried 23 Oct 2026); product page https://podaac.jpl.nasa.gov/dataset/CYGNSS_L1_V3.2 ; DOI 10.5067/CYGNS-L1X32. Variable definitions and flag meanings come from the netCDF attributes, read through OPeNDAP (DMR of `cyg04.ddmi.s20260510-000000-e20260510-235959.l1.power-brcs.a32.d33`).
- NASA Earthdata data use policy: https://www.earthdata.nasa.gov/learn/use-data/data-use-policy (recorded in `registry/sources.csv`).
- C. Chew, T. M. Roberts, S. Lowe, "RFI mapped by spaceborne GNSS-R data," *NAVIGATION* 70(4), navi.618, 2023, doi:10.33012/navi.618. https://navi.ion.org/content/70/4/navi.618 (page read: method uses the forbidden-zone mean noise of the first 45 delay rows; hotspots include Syria, Libya, Yemen, Kashmir, Ethiopia, Myanmar).
- J.-H. Shin, P.-W. Son, "Wide-Area GNSS Interference Monitoring with CYGNSS GNSS-R Delay-Doppler Noise Floor Observations," arXiv:2603.04813 (v4, 28 Jul 2026). https://arxiv.org/abs/2603.04813 (full text read: four-channel maximum, 41 dB threshold, White Sands PD 0.595 at zero observed false alarms; L1 V3.2, May 2025).
- A. Boumeftah, P. Klimas, G. Karabulut Kurt, "Space-Based GNSS Radio Frequency Interference Detection Evaluation Through Multi-Satellite Data Integration," arXiv:2606.14056 (12 Jun 2026). https://arxiv.org/abs/2606.14056 (abstract read).
- S. Gleason, J. Johnson, C. Ruf, C. Bussy-Virat, "Characterizing background signals and noise in spaceborne GNSS reflection ocean observations," *IEEE GRSL* 17(4):587–591, 2020, doi:10.1109/LGRS.2019.2926695 (via Shin & Son).
- M. M. Al-Khaldi, J. T. Johnson, S. Gleason, "Global detection, geolocation, and analysis of terrestrial GPS RFI using spaceborne GNSS-R receivers," *IEEE TGRS* 63, 2025; and Al-Khaldi, Johnson, McKague, Gleason, "Detection and analysis of GPS L1-band radio frequency interference using spaceborne GNSS-R receivers," *IEEE TGRS* 63, 2025 (both via Shin & Son).
- M. J. Murrian et al., "First results from three years of GNSS interference monitoring from low Earth orbit," *NAVIGATION* 68(4):673–685, 2021, doi:10.1002/navi.449 (via Shin & Son).
- EASA, Safety Information Bulletin 2022-02R3, "Global Navigation Satellite System Outage and Alterations Leading to Communication / Navigation / Surveillance Degradation," 5 Jul 2024. https://www.easa.europa.eu/en/domains/air-operations/global-navigation-satellite-system-outages-and-alterations (summary only; not read in full).
- Republic of the Marshall Islands Maritime Administrator, Yacht Safety Advisory No. 05-25, "Global Navigation Satellite System (GNSS) interference," 14 Oct 2025. https://www.register-iri.com/wp-content/uploads/YSA-2025-05.pdf (read: lists the Eastern Mediterranean; Asia, meaning the East and South China Seas, Yellow Sea and Taiwan Strait, with Korean Peninsula jamming; and the Middle East, meaning the Arabian Sea, Red Sea, Persian Gulf, Gulf of Oman and Hormuz).
- US MARAD, Advisory 2019-012, Persian Gulf, Strait of Hormuz, Gulf of Oman, Arabian Sea, Red Sea. https://www.maritime.dot.gov/msci/2019-012-persian-gulf-strait-hormuz-gulf-oman-arabian-sea-red-sea-threats-commercial-vessels (summary only).
- Government of India, written reply in the Lok Sabha, 20 Mar 2025: about 465 GPS interference/spoofing reports in the border region, mostly Amritsar/Jammu, Nov 2023 – Feb 2025, as reported by ETV Bharat. https://www.etvbharat.com/en/!bharat/several-airlines-operating-aircraft-in-around-amritsar-report-gps-interference-govt-enn25032004486 (secondary).
- GPS World, March 2024 issue, "A Black Hole in Earth Science" (radio-occultation data void over Europe and the Middle East). https://editions.mydigitalpublication.com/article/A+Black+Hole+in+Earth+Science/4737387/816882/article.html (search summary only; not read).
- S. Gorman, "Converging on the jammer," GPS World, 18 May 2026 (the Shiraz case; see `docs/validation/nisar.md`). That CYGNSS contributed to the fix comes from a secondary summary: **unverified**.
- Natural Earth 50 m land, v5.1.2 (public domain). Aircraft tables: the project's own, from adsb.lol (ODbL 1.0).
