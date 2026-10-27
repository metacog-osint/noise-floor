# Ground reference stations (C/N0): first test, southern Baltic (24 Oct 2026)

**Lane:** spaceborne and network GNSS (prototype). **Tool:** `tools/station_cn0.py`, tests in `tests/test_station_cn0.py`.
**Data:** EPN and IGS daily RINEX 3 observation files (30 s) and merged broadcast navigation, from the BKG GNSS Data Center.
**Reference:** aircraft NACp from the adsb.lol raw-trace extracts in `data/trace_box/` (southern Baltic region, 52–60°N, 8–26°E).

## Bottom line

- **Clean null on the pre-stated test.** Six EPN stations 110–486 km from the Kaliningrad coast, six jammed days and two quiet controls: **0 flagged minutes on all 48 station-days** (GPS L1 C/A). All six stations: NULL.
  - The station's 5-minute median C/N0 residual never went below −1.35 dB-Hz on a jammed day (threshold −3).
  - Around the stations, aircraft were heavily degraded at the same time: 1,945 minutes on the jammed days had at least 30% of ADS-B reports within 150 km at NACp < 8. The stations flagged none of them.
  - In the worst aircraft hour at Redzikowo (2 Jan, 03Z), 99.5% of reports within 150 km were degraded. The station's residual was −0.07 dB-Hz.
- **The timing test couldn't run:** it needs station-days with 10+ flagged minutes, and there were none.
- **This is what geometry predicts.** A coastal ground jammer reaches only about 35–60 km to a ground antenna by line of sight, while aircraft at cruise see it from about 410 km. Geodetic antennas are also built to reject signals near the horizon. Every station tested is beyond that line-of-sight range from the reported sites. So these stations can't corroborate aircraft detections from Kaliningrad, and the null says nothing about the aircraft data.
- **The detector works and is sensitive.** On quiet days the station residual stays within about ±1 dB-Hz.
  - It caught one real event, outside the test design: a local drop at Vaiņode (VAIN00LVA) on the evenings of 16–17 May 2026, strongest on L5/E5a (to −6.5 dB-Hz). On 17 May at 00:09–00:18Z GPS L1 C/A fell 4.9 dB-Hz on every satellite.
  - Neighbours 126 and 148 km away saw nothing then, so the cause is local to the site and unknown.
- **Sub-threshold structure is mostly common-mode.** Small dips (1.0–1.3 dB-Hz) appeared at four Baltic stations at once on 9 May (02:25–02:50Z and 04:05–04:30Z), inside the aircraft-jammed hours.
  - A reference station in Czechia (GOPE00CZE, 680 km from the box) showed the same dips.
  - Subtracting it removed them. They are not Baltic interference.
- **Next:** stations that can see the emitters, a positive control with known times, and reference differencing. Details in section 7.

## 1. Why ground stations

Nearly every Noisefloor detection comes from one sensor family, ADS-B aircraft reports. An event can only be graded "Multiple sources" when an independent sensor agrees in time and place. Permanent GNSS reference stations are independent of aircraft. They are fixed, surveyed antennas with geodetic receivers that log every satellite's carrier-to-noise density (C/N0) every 30 s, and they publish it openly.

A jammer adds noise across the band it covers, so every satellite on that band loses about the same number of dB of C/N0 at the same moment. Multipath, obstructions, a satellite setting behind a building or ionospheric scintillation hit a few satellites at a time. The station-level signature is therefore a simultaneous drop on most satellites, measured against that station's normal behaviour.

**Published precedent.**

- **Lantmäteriet (SWEPOS).** Lantmäteriet runs SNR-based interference monitoring on the Swedish CORS network. It models SNR for each signal and station, accounting for receiver, satellite elevation, azimuth and satellite block. It compares reference and evaluation windows of the residuals, and separates interference from equipment faults and multipath (Abraha, Frisk, Westberg & Wiklund 2021; Abraha, Frisk & Wiklund 2024). Thresholds weren't checked here.
- **Virginia Tech.** VT's GNSS RFI map (registry `vt-gnss-rfi`, cite-only) processes NOAA CORS and IGS data. It looks for simultaneous C/N0 drops on all satellites in view, against satellite- and station-specific jamming-free models (Jada et al. 2021).
  - The journal version models each satellite's mean C/N0 as a quartic in elevation.
  - It adds an azimuth–elevation model from about eight jamming-free days to capture repeating multipath.
  - It sums inverse-variance-weighted residuals over all satellites, with a false-alarm requirement of 10⁻⁶ (Jada, Psiaki & Joerger 2026).
- **This tool** takes the same idea in a simpler form: a per-satellite baseline at the same place in the sky on quiet days, a median across satellites, and a fixed dB threshold.

## 2. Data, sources and licences

| Item | Value |
|---|---|
| Station data | Daily RINEX 3 observation files, 30 s, Hatanaka-compressed (`*_01D_30S_MO.crx.gz`), from `https://igs.bkg.bund.de/root_ftp/EUREF/obs/` (EPN) and `.../IGS/obs/` (IGS). Anonymous HTTPS; no account. |
| Broadcast orbits | Merged daily navigation file `BRDC00IGS_R_<yyyyddd>0000_01D_MN.rnx.gz` from `https://igs.bkg.bund.de/root_ftp/IGS/BRDC/`. |
| Station list | EPN Central Bureau, `https://epncb.oma.be/pub/station/general/EPN_stations.txt` (active stations, coordinates). |
| EPN licence | **CC BY 4.0 by default; a station operator may choose CC0.** EPN Data Access and Use Policy (EUREF Governing Board, version 2 Jul 2026), section 4: the accepted licences are CC0 and CC BY, the latter allowing use "including for commercial purposes"; assets with no declared licence "are considered to be distributed under CC BY 4.0". EPN CB FAQ 2.7 says the same. Attribution means crediting the data providers and the EPN, citing the DOI where one exists, and saying what was changed. Policy: `https://epncb.oma.be/_documentation/EPNDataAccessandUsePolicy_2026.pdf`; FAQ: `https://epncb.oma.be/_documentation/faq.php` (both read 23 Oct 2026). |
| Per-station licence | The EUREF Historical Data Center record of each station used (`https://w3id.org/EUREF-HDC/<station>`, resolving to `https://epncb.oma.be/PID/<station>`) gives the dataset licence **CC-BY-4.0** for all nine: LAMA00POL, REDZ00POL, VAIN00LVA, VIS600SWE, OSK600SWE, BUDP00DNK, and IRBE00LVA, RIGA00LVA and GOPE00CZE (used in section 5.3). Dataset DOIs: 10.24414/ROB-EUREF-LAMA00POL, -REDZ00POL, -VAIN00LVA, -BUDP00DNK; none found for VIS600SWE or OSK600SWE. The RINEX 3.04 headers carry no licence record. |
| IGS licence | Open to scientific, educational and commercial users, free, attribution required (IGS Data and Product Terms of Use, 5 Aug 2020; registry row `cors-igs`). LAMA00POL, RIGA00LVA and GOPE00CZE come from the IGS directory and are also EPN stations. |
| BKG | The BKG GNSS Data Center is an EPN regional and IGS data centre. Its access page documents anonymous HTTPS download (FTP ended Oct 2026). No separate terms were found on the site; the data carry the EPN or IGS terms above. |
| NASA CDDIS | Not used. BKG holds the same IGS files without a login, so no Earthdata token was needed. |
| Aircraft | adsb.lol raw traces (ODbL 1.0), as extracted by `tools/trace_box.py`. |
| Volume | 321 station-days (283 for the pre-stated test, the rest for the checks in section 5.3) plus daily broadcast navigation: 402 files, 1.4 GB (`data/stations/raw/`, gitignored). Parsed caches 0.5 GB. |

**Credit line for any figure:** "Station data: EUREF Permanent Network and IGS, via the BKG GNSS Data Center (CC BY 4.0). C/N0 residuals computed by Noisefloor. Aircraft: adsb.lol (ODbL 1.0)."

## 3. Method

**Signals.**

- GPS L1 C/A (RINEX code S1C) decides.
- GPS L2 (S2W, else S2L or S2X), GPS L5 (S5Q, S5X or S5I), Galileo E1 (S1C or S1X) and Galileo E5a (S5Q or S5X) are computed and reported but don't enter the verdict.
- The same code is used on the test and baseline days.

**Sky positions.**

- Satellite positions come from the broadcast ephemeris: the IS-GPS-200 Keplerian model, with Galileo constants for Galileo. The tool uses the healthy record nearest in time, within 2 h.
- Elevation and azimuth are computed from the station position in the RINEX header. Only satellites at or above 15° count.
- GLONASS and BeiDou are not used.

**GPS baseline, per satellite.**

- GPS satellites return to the same place in a station's sky about 4 minutes earlier each day: Agnew & Larson (2007) give an average of 247 s less than a day. The multipath and antenna gain each satellite sees repeat with it.
- For each test-day epoch and satellite, the tool searches each baseline day within ±15 min of t + k × 246 s, where k is the number of days between the two. It takes the epoch where that satellite's az/el is closest, and accepts it within 1°.
- The baseline is the median over the baseline days, with at least 3 days required.
- Matching on sky position means the exact repeat time doesn't matter.

**Galileo baseline.**

- Galileo repeats only every 10 sidereal days, so the same matching doesn't work over a few days.
- The Galileo figures use a pooled median over all Galileo satellites and baseline days in each 2.5° elevation bin. This is coarse, and losses aren't counted.

**Per epoch.**

- Residual r = C/N0 − baseline, for each scored satellite.
- **Loss of lock:** a satellite the baseline days tracked at that place in the sky (3 or more days), but missing on the test day on an epoch present in the file, counts as lost. Its residual is set to −40 dB-Hz, which acts as −∞ in medians and thresholds.
- D = median of r over the scored satellites (at least 4).
- F = share of scored satellites with r ≤ −3 dB-Hz.

**Drop rule.**

- An epoch is flagged when the centred 5-minute (11-epoch) running medians of D ≤ −3 dB-Hz **and** of F ≥ 0.75.
- Flagged epochs form runs. Runs merge across gaps of up to 2 minutes and must last at least 2 minutes.
- Flagged minutes are UTC minutes containing an epoch of a kept run.

Why these thresholds:

- 3 dB is a halving of C/N0, which means interference power at the receiver about equal to the thermal noise floor. It is several times the scatter of the station median on quiet days (section 5.1).
- F ≥ 0.75 is the "simultaneous" part. Three-quarters of the satellites must be down together, which a single multipath or obstruction event can't produce.

**Baseline days.**

- For each station and test day: the 5 nearest days (within ±21) that are quiet for that station.
- Quiet means the share of aircraft-hexes with bad NACp (live) within 150 km of the station, from the daily tables in `data/pnt/year/`, is at or below that station's median over 1 Oct 2025 – 21 Oct 2026, with at least 50 aircraft-hexes. The station medians are LAMA 14.7%, REDZ 6.2%, VAIN 10.9%, VIS6 4.8%, OSK6 3.1% and BUDP 0.8%.
- The jammed days and both quiet controls are never used as baseline days.
- The 2025 test days come before the daily tables, so their baseline is the 6 nearest days (±3), unscreened. If those days were also jammed, the baseline is depressed and drops are underestimated.

**Aircraft side.**

- Per UTC minute: the share of ADS-B position reports (source `adsb_icao`) within 150 km of the station with NACp < 8, from `data/trace_box/<day>.jsonl.gz`. Minutes need at least 20 reports to be scored.
- NACp is the last value the aircraft reported.
- Aircraft that lose their position entirely drop out of this share. On the strongest days most crossings near Kaliningrad were dark (Phase 1 verdicts 34–35), so the share understates the effect.

**Times.** RINEX epochs are GPS time. They are converted to UTC (GPS − 18 s) before any comparison with aircraft. All times here are UTC.

## 4. The pre-stated test

The rule was written down on 23 Oct 2026 at about 23:55 UTC, before any station observation file was downloaded. One detail was settled while writing the code, also before any station data were seen. The written rule excluded only the jammed days and the test day from baselines; the code also keeps the two quiet controls out of each other's baselines, so the controls stay independent.

**Stations.** All are EPN stations; distances are from the Kaliningrad coast reference point at 54.8°N 20.0°E.

- No EPN station exists near Klaipėda.
- Vilnius (VLNS00LTU, 341 km) was left out because its 150 km aircraft circle runs past the 26°E edge of the trace extracts.

| Station | Place | km | Receiver / antenna |
|---|---|---|---|
| LAMA00POL | Olsztyn, Poland | 110 | Leica GR50 / LEIAR20 LEIM |
| REDZ00POL | Redzikowo, Polish coast | 189 | Trimble Alloy / TRM59900.00 SCIS |
| VAIN00LVA | Vaiņode, Latvia | 214 | Leica GR30 / LEIAR20 LEIM |
| VIS600SWE | Visby, Gotland | 333 | Trimble Alloy / TPSCR.G5 OSOS |
| OSK600SWE | Oskarshamn, Swedish coast | 354 | Trimble Alloy / TPSCR.G5 OSOS |
| BUDP00DNK | Copenhagen | 486 | Septentrio PolaRx5 / LEIAR20 LEIM |

**Days.**

- Jammed: 9 May 2026, 2 Jan 2026, 1 Feb 2026, 24 Feb 2026, 15 Jun 2025 and 25 May 2025, the strongest southern Baltic days in Phase 1.
- Quiet controls: 16 May 2026 and 17 Jan 2026.

**Verdicts, per station.**

- **PRESENT:** at least 10 flagged minutes on at least 2 of the 6 jammed days, and at most 2 flagged minutes on each quiet control.
- **NULL:** no jammed day reaches 10 flagged minutes.
- **MIXED:** anything else.

**Timing.**

- Applies to station-days with at least 10 flagged minutes.
- It compares the aircraft share in flagged minutes with unflagged minutes of the same day.
- It also finds the lag (−60 to +60 min) of peak correlation between the station drop (max(0, −D), 5-minute median, per minute) and the aircraft share.
- **Aligned** if the flagged-minute share is at least 10 percentage points higher and the peak lag is within ±15 min.
- For every station-day it also reports the minutes with aircraft share ≥ 30% (aircraft-side jamming minutes), and how many of those the station flagged.

## 5. Results

### 5.1 The pre-stated test

Every station-day had all 2,880 epochs except Redzikowo on 9 May (2,876) and 17 Jan (2,785). The median count of GPS satellites scored per epoch was 7–8.

**GPS L1 C/A.** Each cell gives flagged minutes / 1st percentile of the 5-minute residual / minimum, in dB-Hz:

| Station | km | 9 May 26 | 2 Jan 26 | 1 Feb 26 | 24 Feb 26 | 15 Jun 25 | 25 May 25 | 16 May 26 (quiet) | 17 Jan 26 (quiet) | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| LAMA00POL | 110 | 0 / −0.35 / −0.45 | 0 / −1.10 / −1.35 | 0 / −0.20 / −0.33 | 0 / −0.40 / −0.45 | 0 / −0.50 / −0.59 | 0 / −0.32 / −0.42 | 0 / −0.30 / −0.50 | 0 / −0.55 / −0.65 | NULL |
| REDZ00POL | 189 | 0 / −1.00 / −1.30 | 0 / −0.35 / −0.45 | 0 / −0.35 / −0.42 | 0 / −0.60 / −1.00 | 0 / −0.43 / −0.60 | 0 / −0.35 / −0.43 | 0 / −0.50 / −0.80 | 0 / −0.37 / −0.52 | NULL |
| VAIN00LVA | 214 | 0 / −0.65 / −0.75 | 0 / −0.67 / −0.85 | 0 / −0.15 / −0.25 | 0 / −0.20 / −0.35 | 0 / −0.51 / −0.65 | 0 / −0.35 / −0.40 | 0 / −1.43 / −1.96 | 0 / −0.20 / −0.30 | NULL |
| VIS600SWE | 333 | 0 / −0.70 / −1.05 | 0 / −0.40 / −0.60 | 0 / −0.40 / −0.52 | 0 / −0.50 / −0.80 | 0 / −0.45 / −0.50 | 0 / −0.32 / −0.60 | 0 / −0.57 / −0.95 | 0 / −0.30 / −0.40 | NULL |
| OSK600SWE | 354 | 0 / −0.90 / −1.30 | 0 / −0.35 / −0.40 | 0 / −0.33 / −0.50 | 0 / −0.60 / −0.80 | 0 / −0.40 / −0.62 | 0 / −0.32 / −0.75 | 0 / −0.65 / −0.75 | 0 / −0.35 / −0.40 | NULL |
| BUDP00DNK | 486 | 0 / −0.88 / −1.12 | 0 / −0.30 / −0.50 | 0 / −0.50 / −0.75 | 0 / −0.50 / −0.75 | 0 / −0.62 / −0.88 | 0 / −0.50 / −0.62 | 0 / −0.62 / −0.88 | 0 / −0.38 / −0.50 | NULL |

- Nothing on a jammed day came within 1.6 dB-Hz of the threshold.
- The lowest value overall is on a quiet control: Vaiņode on 16 May, −1.96 dB-Hz, part of the local evening event in section 5.3.

**Aircraft near each station.** Each cell gives the day share of ADS-B reports within 150 km at NACp < 8 / minutes with share ≥ 30% (of those, flagged by the station):

| Station | 9 May 26 | 2 Jan 26 | 1 Feb 26 | 24 Feb 26 | 15 Jun 25 | 25 May 25 | 16 May 26 (quiet) | 17 Jan 26 (quiet) |
|---|---|---|---|---|---|---|---|---|
| LAMA00POL | 13.7% / 35 (0) | 36.3% / 69 (0) | 14.2% / 35 (0) | 14.7% / 27 (0) | 21.3% / 71 (0) | 17.5% / 91 (0) | 7.5% / 44 (0) | 8.7% / 26 (0) |
| REDZ00POL | 20.5% / 30 (0) | 36.9% / 48 (0) | 22.0% / 69 (0) | 26.2% / 56 (0) | 25.3% / 101 (0) | 11.7% / 78 (0) | 5.6% / 24 (0) | 5.4% / 27 (0) |
| VAIN00LVA | 14.3% / 66 (0) | 16.0% / 45 (0) | 6.7% / 34 (0) | 9.3% / 25 (0) | 17.9% / 62 (0) | 12.7% / 79 (0) | 7.8% / 54 (0) | 3.8% / 7 (0) |
| VIS600SWE | 27.9% / 203 (0) | 11.5% / 86 (0) | 7.5% / 23 (0) | 6.7% / 30 (0) | 11.4% / 76 (0) | 7.6% / 46 (0) | 4.9% / 20 (0) | 4.4% / 14 (0) |
| OSK600SWE | 22.7% / 218 (0) | 9.9% / 45 (0) | 6.8% / 25 (0) | 6.1% / 33 (0) | 8.7% / 49 (0) | 4.4% / 14 (0) | 3.2% / 12 (0) | 2.7% / 3 (0) |
| BUDP00DNK | 8.0% / 55 (0) | 1.8% / 3 (0) | 1.2% / 5 (0) | 1.4% / 13 (0) | 2.8% / 0 (0) | 1.0% / 0 (0) | 1.2% / 14 (0) | 0.8% / 8 (0) |

- Across the 36 jammed station-days there were 1,945 aircraft-side jamming minutes. The stations flagged none of them.
- The quiet controls also have such minutes. On a few aircraft a single minute easily reaches 30%, and the background around Kaliningrad is not zero.

**Highest-share hours** (all reports in the hour; 200+ reports), with the station's mean L1 residual over the same hour:

| Station | Hour (UTC) | Aircraft share | Station residual |
|---|---|---|---|
| REDZ00POL | 2 Jan 2026, 03Z | 99.5% | −0.07 dB-Hz |
| VAIN00LVA | 24 Feb 2026, 03Z | 98.6% | −0.03 |
| REDZ00POL | 24 Feb 2026, 03Z | 95.1% | −0.14 |
| VIS600SWE | 9 May 2026, 02Z | 78.8% | −0.28 |
| LAMA00POL | 2 Jan 2026, 20Z | 72.9% | −0.12 |
| OSK600SWE | 9 May 2026, 02Z | 70.7% | −0.43 (common-mode; section 5.3) |

**Timing.** No station-day reached 10 flagged minutes, so the pre-stated timing test has nothing to compare.

### 5.2 Other signals

- **GPS L2, GPS L5, Galileo E1, Galileo E5a:** no flagged minutes on any jammed day at any station.
- **The only flags in the whole set** are at Vaiņode on the 16 May control: L5 for 14 minutes (22:39–22:52Z, minimum −5.6 dB-Hz) and E5a for 30 minutes (22:38–23:39Z, minimum −6.5). The L1 C/A verdict is unaffected (0 minutes).
- **The Galileo pooled baseline is too coarse as it stands.** On 24 Feb every station, including Copenhagen, reads −1.4 to −1.9 dB-Hz at the 1st percentile on Galileo E1, and on 17 Jan Olsztyn reads −2.5. A shift that is the same 486 km apart, with quiet aircraft around Copenhagen, is a baseline effect, not interference.

### 5.3 Exploratory checks (after the fact, not pre-stated)

**Sub-threshold link to aircraft.** Hourly mean L1 residual against hourly aircraft share, pooled over the 8 days (148–187 hours per station):

| Station | Spearman r | 95% bootstrap | Residual in hours with share ≥ 30% | Residual in hours with share < 5% |
|---|---|---|---|---|
| LAMA00POL | −0.19 | −0.36 to −0.04 | −0.06 (30 h) | +0.03 (26 h) |
| REDZ00POL | +0.01 | −0.13 to +0.17 | +0.01 (35 h) | −0.01 (25 h) |
| VAIN00LVA | −0.29 | −0.43 to −0.15 | −0.03 (11 h) | +0.04 (53 h) |
| VIS600SWE | −0.09 | −0.24 to +0.06 | −0.02 (15 h) | +0.03 (52 h) |
| OSK600SWE | +0.05 | −0.11 to +0.21 | +0.02 (12 h) | −0.00 (80 h) |
| BUDP00DNK | +0.11 | −0.04 to +0.25 | +0.05 (2 h) | +0.02 (165 h) |

- Two of six intervals exclude zero, but the differences are under 0.1 dB-Hz.
- Aircraft degradation in the Baltic peaks at night (Phase 1), so time of day confounds this comparison. There is no usable signal at this level.

**Common-mode dips.** The per-minute L1 residuals correlate between stations on every day, quiet days included: the mean pairwise r over the six stations was 0.31–0.62.

- On 9 May, Redzikowo, Oskarshamn, Visby and Copenhagen dipped 1.0–1.3 dB-Hz together at 02:25–02:50Z and 04:05–04:30Z. That gave 24 minutes with three or more stations at or below −0.75 dB-Hz, against 0–6 on the other days.
- Those were also hours when 70–82% of aircraft reports near Visby, Oskarshamn and Redzikowo were degraded.
- **A far reference shows the same dips.** GOPE00CZE (Ondřejov, Czechia; 680 km from the southern Baltic box, beyond line of sight of anything over it) was analysed against the same baseline days. It showed the same dips and correlated with the Baltic stations at r = 0.60–0.74 that day.
- Subtracting its per-satellite residuals removed the dips: the station-minus-reference minimum was −0.50 to −0.90 dB-Hz at every station.
- So the 9 May dips are common to central and northern Europe, not Baltic interference. The cause wasn't identified; satellite-side signal-level changes are one candidate.
- Olsztyn's Leica receiver didn't show them.

**Vaiņode, 16–17 May 2026: a local event.**

- **16 May, from about 20:00Z:** all signals fall. By 22:40Z L1 C/A was about 1–2 dB-Hz down, L2 up to 2.7, L5 5.6 and E5a 6.5.
- **17 May, 00:09–00:18Z:** L1 C/A fell 4.9 dB-Hz on every satellite (F = 1.0). That is 10 flagged minutes, which would meet the 10-minute mark. L2 fell 5.6 and L5/E5a 6.2.
- **17 May, 18:55–21:50Z:** L5 flagged 103 minutes that day, and E5a 72.
- **The neighbours saw nothing.** Irbene (IRBE00LVA, 126 km) and Riga (RIGA00LVA, 148 km) had no flags on either day; their minima were −0.4 to −1.75 dB-Hz.
- **The reference doesn't explain it.** Subtracting GOPE leaves −1.82 dB-Hz at Vaiņode on 16 May.
- The event is local to the site. The cause is unknown: local interference in the lower L-band (the drop is largest at 1176 MHz), or equipment.
- There is no aircraft extract for 17 May, and the 16 May aircraft data near Vaiņode are too sparse at that hour to compare.

**Olsztyn, low-elevation losses on 2 Jan 2026.**

- Olsztyn lost 5.0% of its scored satellite-epochs between 15° and 30° elevation, against 0.08–2.1% on the other seven days (controls 1.25% and 0.46%). Every loss was below 25°.
- Hourly losses don't track the aircraft share (Spearman +0.10, −0.03 to +0.29).
- Weak interference arriving near the horizon would knock out low satellites first. So would snow or ice, or a change in receiver tracking. This is not resolved.

## 6. Limits

- **Line of sight.** The radio horizon between two antennas is about 4.12 × (√h₁ + √h₂) km, with heights in metres, under standard refraction.
  - A jammer on a 30–100 m mast and a station antenna at 10–20 m: about 35–60 km.
  - Aircraft at 10 km: about 410 km.
  - A station 110 km away would need the jammer about 500 m up to be in line of sight. The published 2025 fixes put the Baltic emitters at coastal sites (Phase 1 verdicts 41–44).
  - Only an airborne or elevated source, or anomalous propagation (ducting over a cold sea), reaches these stations. Ducting wasn't checked for these days.
- **Antennas.** Choke-ring and similar geodetic antennas are designed to suppress signals arriving near the horizon, which is where a distant ground jammer's signal arrives. Gain figures weren't checked for these models.
- **Sensitivity.** The 3 dB threshold sits well above the ±1 dB-Hz quiet-day scatter. Subtracting a far reference shrank the worst 5-minute residual on 9 May from −0.75 to −1.30 dB-Hz to −0.50 to −0.90 dB-Hz (section 5.3), so a lower threshold is possible later.
- **Sampling.** With 30 s sampling and a 5-minute median, bursts shorter than about 2.5 minutes can't be flagged. BKG holds 1 Hz files.
- **Day edges.** A baseline day k days from the test day can't match the first or last k × 4 min of the test day, because the matching epoch falls on the neighbouring calendar day. With baseline days up to 19 days away (Vaiņode in May), GPS scoring stops up to about 75 min before midnight. Loading the adjacent days would fix this.
- **2025 baselines** are unscreened (no daily tables before October 2025).
- **The aircraft measure** counts degraded reports, not dark aircraft. It is also inflated by aircraft that degraded elsewhere and carry it in (Phase 1, latching and post-exposure verdicts). A jammed minute in the air near a station doesn't mean the interference reached the ground there.
- **Galileo** figures use a pooled baseline that shifts by up to about 2 dB-Hz between days (section 5.2). They are not usable for detection yet.
- **Sample size:** 6 stations and 8 days. Russian and Kaliningrad stations are not in the EPN, so nothing inside line-of-sight range was available.

## 7. Next steps

1. **Stations that can see the emitters.** National networks near the coast and the border: Polish ASG-EUPOS, Lithuanian LitPOS, Swedish SWEPOS beyond the EPN subset, and the Danish station on Bornholm (Tejn) that DR reported logging 30 jamming or spoofing events in 2026. Their data terms are **not checked**. Each needs its own registry row before use.
2. **A positive control with known times.**
   - Jammertest on Andøya: no EPN station is there; the Norwegian national network's terms are not checked.
   - Announced US tests near NOAA CORS stations (open data).
   - Near-ground jamming in the Eastern Mediterranean at IGS or EPN stations within line of sight.
3. **Reference differencing in the tool.** Subtract a far station's per-satellite residual, as in section 5.3, to remove common-mode variation. Then set a lower threshold with a fresh pre-stated test.
4. **Vaiņode.** Run the station over all of May 2026 to see how often the evening event recurs, and whether it follows the clock (equipment or local activity) or anything else.
5. **Day-edge fix** (load adjacent days) and a per-satellite Galileo baseline from 10-day-apart repeats.
6. Only after a positive control passes: feed station flags into event grading as an independent source.

## Reproduce

```
python -m pip install hatanaka          # Hatanaka decompression (pulls in ncompress); not needed for the unit tests
python tools/station_cn0.py stations --max-km 500 --day 2026-05-09
python tools/station_cn0.py test --plan-only    # baseline days per station and test day
python tools/station_cn0.py test                # downloads ~1.3 GB into data/stations/raw (gitignored), writes
                                                # data/stations/<STATION>/<day>.json and .png and test_results.json
python tools/station_cn0.py day VAIN00LVA 2026-05-17 --baseline 2026-04-27,2026-04-28,2026-05-01,2026-05-04,2026-06-02
python tests/test_station_cn0.py
```

The aircraft side needs `data/trace_box/<day>.jsonl.gz` (from `tools/trace_box.py extract`). The quiet-day screen needs the daily tables in `data/pnt/year/` (`tools/leads_year.py fetch`). The exploratory checks in section 5.3 were one-off scripts on the per-station-day outputs and are not in the tool.

## Sources

- Abraha, K. E., Frisk, A., Westberg, M. & Wiklund, P. (2021). SWEPOS data quality monitoring: GNSS signal disturbances detection system. Lantmäterirapport 2021:1. `https://www.lantmateriet.se/globalassets/geodata/gps-och-geodetisk-matning/rapporter/lantmaterirapport-2021-1-swepos-data-quality-monitoring.pdf`.
- Abraha, K. E., Frisk, A. & Wiklund, P. (2024). GNSS interference monitoring and detection based on the Swedish CORS network SWEPOS. *Journal of Geodetic Science* 14(1): 20220157. doi:10.1515/jogs-2022-0157.
- Jada, S., Psiaki, M., Landerkin, S., Langel, S., Scholz, J. & Joerger, M. (2021). Evaluation of PNT situational awareness algorithms and methods. *Proc. ION GNSS+ 2021*, 816–833.
- Jada, S., Psiaki, M. & Joerger, M. (2026). Network-based GNSS jamming prediction enabling wideband interference observation. *NAVIGATION* 73(1), navi.763. doi:10.33012/navi.763.
- Agnew, D. C. & Larson, K. M. (2007). Finding the repeat times of the GPS constellation. *GPS Solutions* 11(1): 71–76. doi:10.1007/s10291-006-0038-4.
- EUREF Governing Board (2026). EPN Data Access and Use Policy, version 2 Jul 2026. `https://epncb.oma.be/_documentation/EPNDataAccessandUsePolicy_2026.pdf`.
- EPN Central Bureau. FAQ, questions 2.2 and 2.7. `https://epncb.oma.be/_documentation/faq.php`.
- Bruyninx, C., Habrich, H., Söhne, W., Kenyeres, A., Stangl, G. & Völksen, C. (2012). Enhancement of the EUREF Permanent Network services and products. *Geodesy for Planet Earth*, IAG Symposia 136: 27–35. doi:10.1007/978-3-642-20338-1_4 (the EPN's suggested citation).
- IGS (2020). IGS Data and Product Disclaimer and Terms of Use, 5 Aug 2020.
- BKG GNSS Data Center, archive access page: `https://igs.bkg.bund.de/access`.
- Virginia Tech GNSS RFI Tracking: `https://rfi.aoe.vt.edu/` (cited, not used as data).
- DR, as reported by European Pravda (10 Aug 2026), on the Bornholm station's 2026 event count (secondary; see Phase 1).
