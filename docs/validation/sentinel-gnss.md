# Sentinel navigation receivers: pre-registered checks (31 Oct 2026)

**Lane:** spaceborne, step E of `docs/space-sensors-plan.md` (E2 indicator, E3 checks). **Reader:**
`tools/sentinel_gnss.py` as committed in bccdba9 (E1), tests in `tests/test_sentinel_gnss.py`. **Data:** Copernicus
POD Service `AUX_GNSSRD` (RINEX 3.03 signal strength) from Sentinel-1C, 1D, 2B, 2C, 3A and 3B, with the aircraft map
(adsb.lol, `data/pnt/year/`) and CYGNSS (`cygnss-data`) for comparison. Method after SAT-JAM (K. Bostani Nezhad, DTU).

## 1. Pre-registration

Written 31 Oct 2026, 18:21 UTC, and committed before any Sentinel file for a test window is downloaded. Results go in
section 2 and do not change this section.

**What has been seen.** One day, 24 Oct 2026, was processed for E1 to check the format and the geometry: GPS L1 signal
strength by elevation band, worldwide, per unit, and the spacecraft positions against ESA's orbit file. No regional or
cell value was computed, and 24 Oct is in no test window. The aircraft labels in section 1.3 were counted from the
aircraft tables alone.

### 1.1 Frozen indicator (E2)

Input is the E1 table (one row per link and epoch on each unit's own 10 s grid). Primary signal: GPS L1 C/A (`s1c` on
GPS links). Every listed unit that published for a day is used. Sentinel-1A is not used.

1. **Links scored:** GPS links with elevation ≥ 10° in the spacecraft frame and a value for `s1c`.
2. **Baseline:** for each unit and day, the median `s1c` in each 5° elevation bin (10–15° … 85–90°).
3. **Residual:** r = `s1c` − baseline (dB).
4. **Epoch value D:** the median r over that epoch's scored links, when there are at least 4. Epochs with fewer are
   not scored; their share is reported per cell (section 1.5).
5. **Interference kept out of its own baseline:** three passes. After each, res-2 cells (by the sub-satellite point,
   that unit and day) whose median D is ≤ −1 dB are dropped and the baseline recomputed. This is the CYGNSS rule.
6. **Cell value, per window:** H3 res 2 (about 300 km across), by the spacecraft's sub-satellite point. The value is
   the median D over the window's scored epochs in the cell, all units pooled.
7. **Judged cells:** at least 12 scored epochs from at least 2 passes. A pass is one unit's consecutive epochs with
   no gap over 60 s.
8. **Call:** a cell is *degraded* at a cell value ≤ −1 dB. The threshold is fixed here, with no in-sample basis.

The E2 code may reuse step P's functions (`tools/s6_rfi.py`) where they compute exactly this. Any difference from the
definition above is reported with the results.

### 1.2 Windows, by a date rule

- **Rule:** seven-day windows, Monday to Sunday, every sixth Monday from 6 Oct 2025 (k = 0 … 8).
- **The nine windows** (start dates): 2025-10-06, 11-17, 12-29; 2026-02-09, 03-23, 05-04, 06-15, 07-27, 09-07.
- **What the rule happens to cover:** the Kaliningrad winter surge (28 Dec – 3 Jan), both Hormuz surges (2 Mar – 3 Apr
  and 8 May – 21 Jun 2026; `docs/assessment/year-trends.md`), and quiet Gulf weeks before and after.
- **Missing data:** the aircraft tables lack 31 Dec 2025 and 6 May 2026 (adsb.lol has no archive). A Sentinel unit-day
  that is missing is skipped and reported, never replaced. A window averaging fewer than four units a day is reported
  as thin and still scored.
- **Volume:** 63 days, about 4.7 GB of Sentinel files.

### 1.3 Labels and boxes

**Aircraft labels.** Per res-2 cell and window, the GPSJam-style share is Σ max(bad − 1, 0) ÷ Σ aircraft over the
cell's res-4 children and the window's days (`bad_nacp_live`), exactly as the CYGNSS lane builds it.
- A cell is paired at 140+ aircraft in the window (20 a day).
- *Jammed* at a share ≥ 10%; *clean* below 2%.

Counted on 31 Oct from the aircraft tables only:

| Window | Paired cells | Jammed | Clean | Persian Gulf box share (jammed / paired) | Baltic box share (jammed / paired) |
|---|---|---|---|---|---|
| 2025-10-06 | 829 | 20 | 784 | 0.7% (0 / 6) | 5.2% (3 / 8) |
| 2025-11-17 | 838 | 15 | 805 | 0.6% (0 / 6) | 4.5% (2 / 8) |
| 2025-12-29 | 835 | 22 | 784 | 0.6% (0 / 6) | 11.8% (5 / 8) |
| 2026-02-09 | 856 | 19 | 816 | 0.4% (0 / 6) | 7.9% (3 / 8) |
| 2026-03-23 | 827 | 26 | 771 | 44.6% (2 / 2) | 5.3% (2 / 8) |
| 2026-05-04 | 789 | 21 | 741 | 23.4% (3 / 4) | 10.5% (3 / 7) |
| 2026-06-15 | 845 | 24 | 796 | 16.1% (3 / 6) | 6.3% (4 / 8) |
| 2026-07-27 | 911 | 20 | 864 | 2.8% (0 / 6) | 6.5% (4 / 8) |
| 2026-09-07 | 943 | 14 | 901 | 2.1% (0 / 6) | 4.2% (2 / 7) |
| **All** | **7,673** | **181** | **7,262** | | |

**Boxes** (lat_min, lat_max, lon_min, lon_max):
- **Persian Gulf** (23.5, 30.5, 47.5, 57.0), as in `tools/cygnss_rfi.py`.
- **Baltic** (53.5, 61.0, 17.0, 30.0), the daily deck's trend box.
- **Quiet controls, judged:** central Pacific (−20, 20, −160, −130), Australia interior (−32, −20, 120, 145) and
  southern Africa interior (−30, −18, 15, 30), as in the CYGNSS lane.
- **Controls under the South Atlantic Anomaly, reported only:** South Atlantic (−30, −10, −30, −10) and Brazil interior
  (−20, −5, −60, −45). Radiation there can disturb receivers in low orbit, which CYGNSS's measure doesn't share. They
  were taken out of the judged set now, before any value was seen.
- The other CYGNSS boxes with published reports (Levant, Egypt, Iraq, Iran, Red Sea, India–Pakistan, Myanmar, South
  China Sea) are reported per window without a pass mark.

### 1.4 Checks with pass marks

| # | Check | Holds if | Fails if |
|---|---|---|---|
| 1 | Pooled AUC, aircraft-jammed vs aircraft-clean cells (all windows, judged cells) | ≥ 0.80 | < 0.70 |
| 2 | Region-held-out AUC, every region left out in turn | every value ≥ 0.75 | any value < 0.65 |
| 3 | The Baltic's own AUC: its jammed cells against all clean cells | ≥ 0.80 | < 0.70 |
| 4 | Change: Persian Gulf box median cell value, window 2026-03-23 minus window 2026-02-09 | ≤ −1.0 dB | > −0.5 dB |
| 5 | Judged controls: share of control cell-windows called degraded (≤ −1 dB) | ≤ 2% | > 5% |
| 6 | Agreement with CYGNSS: Spearman ρ between −(cell value) and CYGNSS median excess, res-2 cells judged by both within ±38°, same windows pooled | ≥ 0.20 (p < 0.01) | < 0.10 |

Between the two marks the result is "weakened".

- **Check 2:** regions are single-linkage clusters of the jammed cell-windows (all windows pooled) at 1,000 km, as in
  the CYGNSS lane. Leaving a region out removes every paired cell within 1,000 km of any of its jammed cells. A value
  is judged only with 10 or more jammed cells left.
- **Check 3:** the Baltic's jammed cells are those with centres in the Baltic box. The check is judged only if there
  are at least 10 across the windows; the aircraft table above shows 28.
- **Check 4:** the box median is the median of its judged cells' values in that window. The judged-control median
  change between the same two windows is reported beside it; a change of more than 0.5 dB either way is flagged.
- **Check 6:** CYGNSS values come from the lane's frozen daily grids (`data/cygnss/grid/<day>.r3.parquet`, held for
  every window day). A res-2 cell's value for a window is the median of its res-3 children's daily `med_db`, each
  weighted by its DDM count `n`. A cell needs 20+ DDMs in total.

### 1.5 Reported without a pass mark

- **Hit and false-alarm rates** at −0.5, −1 and −2 dB.
- **SAT-JAM's indicator** on the same cells: per unit and day, z = (`s1c` − mean) ÷ standard deviation over all GPS
  links, with no elevation term. The cell value is the share of links with z < −1. Reported: its AUC beside ours, to
  test the plan's claim that binning by elevation helps.
- **Low-link share:** per cell, the share of the units' grid epochs with fewer than 4 scored GPS links, where the
  broadcast ephemeris puts 6 or more healthy GPS satellites above 10°. Absent epochs are counted separately as missing
  data, since a gap in the file cannot be told from a jammed receiver.
- **Back-projection:** epoch values D spread to every cell within R of the sub-satellite point, at R = 500, 1,000 and
  1,500 km, with the COSMIC-2 lane's correlation score where its functions apply. AUC for each R.
- **Per receiver type:** AUC for PODRIX (S1C, S1D, S2C) and RUAG (S2B, S3A, S3B) units separately.
- **Other signals:** Galileo E1 (`s1c` on Galileo links, PODRIX units) and GPS L2 semi-codeless (`s2w`) with the same
  indicator.
- **Latitude:** pooled AUC for cells within ±60° only, since auroral scintillation may also lower signal strength
  poleward of that.
- **Detection reach:** epoch values D binned every 100 km by the sub-satellite point's distance, to 3,000 km, from
  Kaliningrad (54.8, 20.0) over all windows, and from the Persian Gulf box centre (27.0, 52.25) over the 2026-03-23,
  05-04 and 06-15 windows. The reach is the largest distance at which the median D is at least 0.5 dB below the
  judged controls' median.
- **Where false alarms sit:** clean cells called degraded, by distance from the nearest jammed cell (0–500, 500–1,000,
  1,000–2,000 and over 2,000 km).
- **Every box, every window:** median cell value and the share of its judged cells called degraded.
- **Confounders, flagged and never removed:**
  - days with Kp ≥ 5 (NOAA SWPC);
  - days on the EKS (Molniya) event list in Clements, Kriezis and Humphreys, arXiv:2606.03673, if the paper is read
    before the results; otherwise this is reported as unchecked.

### 1.6 Rules for the run

- The Sentinel files for the nine windows are fetched only after this file is committed.
- No threshold, box, window or definition above changes after any result is seen. If a bug turns up, the result with
  the frozen code is reported first, and the fixed result beside it.
- The code's commit hash is recorded with the results.
- Nothing from this lane goes on the public map until checks 1–6 are reported and Tom says yes (plan step E4).

## 2. Results (31 Oct 2026, 22:00 UTC)

**Bottom line: four checks hold and two fail.**
- The indicator separates aircraft-jammed from aircraft-clean cells (pooled AUC 0.862), holds with each region left
  out, does best in the Baltic (0.917), and agrees with CYGNSS (ρ 0.557).
- It fails the Gulf change check and the control check. From orbit, the Gulf was never quiet: it read −1.2 dB or
  lower in every week, including before the surge. One control box, inland Australia, read about −1 dB almost every
  week.
- Most clean cells near jammed areas are called degraded: 97% within 500 km, 82% at 1,000–2,000 km. The indicator marks
  a region about 2,000 km across, not a cell.
- By the pre-registered rule, nothing goes on the public map (plan step E4).

**Run.**
- **Code:** `tools/sentinel_rfi.py` and `tools/rx_rfi.py` as committed in 6bb86cd, before any window was scored. The
  shared modules it imports are unchanged since.
- **Fixes during the run,** none changing a value:
  - ranged S3 downloads (8148a89);
  - a CDDIS fallback for the broadcast navigation, since BKG and IGN refused connections (6bb86cd);
  - retried renames (e9a714e).
- **Before results,** one crash test of the checks code ran on two windows with the values hidden.
- **The drive** dropped for about 80 minutes when the PC went into standby on battery. All 167 product files held at
  the time matched their recorded SHA-256 afterwards, and every table read cleanly.
- **Data:** all 63 days, 5 units a day to February and 5–6 from May (Sentinel-1D). No window was thin. Of the 5,844
  res-2 cells the units overflew, 5,842–5,844 were judged each week. Every aircraft-paired cell was judged: 181 jammed
  and 7,262 clean, the counts in section 1.3.

### 2.1 Checks

| # | Check | Result | Holds if / fails if | Verdict |
|---|---|---|---|---|
| 1 | Pooled AUC, jammed vs clean | **0.862** (181 jammed, 7,262 clean) | ≥ 0.80 / < 0.70 | **holds** |
| 2 | Region-held-out AUC, lowest | **0.827** (the Europe–Middle East region left out; 25 jammed left) | ≥ 0.75 / < 0.65 | **holds** |
| 3 | The Baltic's own AUC | **0.917** (28 jammed) | ≥ 0.80 / < 0.70 | **holds** |
| 4 | Persian Gulf box, 23 Mar window minus 9 Feb window | **−0.34 dB** (−1.28 to −1.62; 8 cells each) | ≤ −1.0 / > −0.5 | **fails** |
| 5 | Judged controls called degraded | **10.8%** of 1,944 cell-weeks | ≤ 2% / > 5% | **fails** |
| 6 | Spearman ρ with CYGNSS, within ±38° | **0.557** (32,288 cell-weeks; p below double precision) | ≥ 0.20 / < 0.10 | **holds** |

The judged controls changed by +0.16 dB between the two Gulf windows, below the 0.5 dB flag.

**Regions for check 2** (single linkage at 1,000 km):

| Region (centre) | Jammed cell-weeks (windows) | Its own AUC | Pooled AUC without it (jammed left) |
|---|---|---|---|
| Baltic, western Russia, Black Sea, Caucasus and one Levant cell, linked into one (51.3N, 35.7E) | 156 (9) | 0.878 | 0.827 (25) |
| Gulf and UAE (24.0N, 55.1E) | 16 (3) | 0.770 | 0.872 (165) |
| Myanmar and the Andaman coast (15.3N, 96.6E) | 8 (8) | 0.749 | 0.867 (173) |
| Central Siberia (57.1N, 85.6E) | 1 (1) | 0.845 | 0.863 (180) |

### 2.2 Why the two checks fail

**Check 4, the Gulf.**
- Aircraft over the Gulf read 0.4% degraded in the 9 Feb week and 44.6% in the 23 Mar week. The Sentinel receivers
  read −1.28 dB and −1.62 dB.
- The box never read quiet in any of the nine weeks: −1.18 to −2.05 dB. Its neighbours read lower every week:
  - Iraq −2.3 to −4.8 dB;
  - inland Iran −1.7 to −3.2 dB;
  - the Levant −2.4 to −3.6 dB.
- The receivers hear emitters out to about 3,000 km, so the Gulf box carries its neighbours' interference. The surge
  shows only as a small extra drop.
- CYGNSS also read Iraq and Iran raised all year (`docs/validation/cygnss.md`, section 3.2).

**Check 5, the controls.** One box carries it:

| Box | Median by window, dB (share of cells degraded) |
|---|---|
| Central Pacific | −0.15 to +0.27 (0–1%) |
| Southern Africa interior | −0.39 to −0.12 (0%) |
| **Australia interior** | **−1.22 to −0.63 (5–84%)**; ≤ −0.97 in eight of nine weeks |
| South Atlantic (reported only) | −0.10 to +0.21 (0%) |
| Brazil interior (reported only) | +0.10 to +0.49 (0%) |

- The drop over inland Australia is unexplained and was not investigated here. It is not the latitude or the orbit:
  southern Africa sits in the same band and stays quiet.
- CYGNSS's noisiest control was also inland Australia: up to +0.51 dB, its one flagged control box-day in the held-out
  test. Two independent sensors point the same way, which leans toward a real source rather than an artefact.
  Unverified.
- The two boxes under the South Atlantic Anomaly stayed quiet, so the reason for leaving them out of the judged set did
  not materialise.

### 2.3 Reported without a pass mark

- **Thresholds:**

  | Threshold | Hit | False alarm |
  |---|---|---|
  | −0.5 dB | 100% | 45% |
  | −1 dB | 95.6% | 28.9% |
  | −2 dB | 59.7% | 13.6% |

- **False alarms by distance to the nearest jammed cell** (−1 dB):

  | Distance | Clean cells called degraded |
  |---|---|
  | 0–500 km | 97% (of 69) |
  | 500–1,000 km | 94% (of 375) |
  | 1,000–2,000 km | 82% (of 879) |
  | Over 2,000 km | 16% (of 5,939) |

  This is the receivers' footprint, not noise.
- **Back-projection** is better than the sub-satellite cell:

  | Radius | AUC (mean) | AUC (correlation score) |
  |---|---|---|
  | 500 km | 0.882 | 0.880 |
  | 1,000 km | 0.897 | 0.894 |
  | 1,500 km | 0.918 | 0.917 |

- **SAT-JAM's indicator** (z < −1, no elevation term): AUC 0.849, against 0.862 for the elevation-binned index. Binning
  helps, a little.
- **Receivers and signals:**
  - PODRIX units 0.872, RUAG units 0.845;
  - Galileo E1 0.863, GPS L2 semi-codeless 0.858 (RUAG units; the PODRIX files leave S2W empty);
  - cells within ±60°: 0.881.
- **Low-link and missing epochs carry nothing** (AUC 0.497 and 0.502; the median share is 0 in both groups). The
  receivers keep tracking under interference; the effect shows only in signal strength.
- **Detection reach:**
  - Epochs within 1,000 km of Kaliningrad read −4.4 to −4.8 dB. The reading is −3.6 dB at 1,500 km, −2.2 dB at
    2,100 km and −1.1 dB at 2,700–2,800 km, against −0.16 dB over the controls.
  - Around the Gulf: −1.4 to −2.0 dB within 700 km and about −1.1 dB at 2,000–3,000 km.
  - Both "reach" the 3,000 km edge of the profile. Neither area is a single emitter (Belarus, western Russia and
    Ukraine lie within that distance of Kaliningrad; Iraq, Iran and the Levant of the Gulf), so these are profiles of
    regions, not a range for one jammer.
- **The Baltic box over the year:** −3.21, −3.10, −2.80, −3.66, −4.57, −4.63, −4.49, −4.56 and −5.85 dB for the nine
  windows in order. That is a steady deepening from October 2025 to September 2026.
- **Other boxes** (median range over the nine windows):
  - Egypt / Sinai / Suez −2.1 to −7.5 dB;
  - the Levant −2.4 to −3.6;
  - South China Sea −1.1 to −1.5 (72–100% of cells degraded);
  - Myanmar −0.7 to −1.3;
  - Red Sea −0.1 to −1.2;
  - India–Pakistan −0.6 to −1.3.
- **Confounders:**
  - Days with Kp ≥ 5 inside the windows: 12 Oct 2025; 2 Jan, 15 Feb, 23 Mar, 25 Mar, 4 May, 2 Aug and 8 Sep 2026.
    Flagged, not removed.
  - The EKS event list was not checked: the paper was not read before the run.

**Deviations from section 1.**
- Kp came from GFZ Potsdam (CC BY 4.0, the events lane's source), not NOAA SWPC. It is the same index.
- Galileo E1 and GPS L2 each come from the units that log them (Galileo: PODRIX; L2: RUAG).

### 2.4 What changes

- **Not a cell-level map layer.**
  - The two failures and the false-alarm profile show the indicator can't say which 300 km cell is jammed.
  - It says a region roughly 2,000 km across is. That is consistent with the receivers' 2,850–3,060 km horizon.
- **It is a working regional sensor** where nothing else in orbit reaches at GPS L1: the Baltic AUC is 0.917, and the
  Baltic deepened over the year.
- **Inland Australia** needs its own look before any reading in a quiet area is trusted.
- **Plan step E4** (a public layer) waits on Tom. A regional weekly product, captioned with the footprint and the
  Australia caveat, is the realistic form.

### 2.5 After the run (31 Oct 2026, evening; descriptive, not pre-registered)

**The EKS confounder, checked.**
- The paper is Clements, Kriezis and Humphreys, "Chasing Lightning" (arXiv:2606.03673, 2 Jun 2026), read 31 Oct.
- It counts days with wide-area L1 events (75 days with a drop of 5 dB or more, 2019–2026) but publishes no list of
  dates, so the windows can't be matched day by day.
- Each event lasts under 10 seconds and covers continental Europe, Greenland and Canada. One event touches at most
  one 10 s epoch per pass, which cannot move a weekly cell median.
- Not a material confounder for these checks.

**Inland Australia, looked at.** The drop is not centred on Australia. Over the nine windows, in 5-degree boxes:
- It is −1.0 to −1.3 dB everywhere from 100 to 130°E, open Indian Ocean included, at every latitude from 10°S to
  45°S. It fades to −0.1 to −0.4 dB by 160–170°E.
- It shows on every unit (−0.8 to −1.5 dB in the Australia interior box) and at every pass time (−0.85 to −1.69 dB),
  and in all nine windows.

A longitude profile over quiet bands finds the same dip around the world (median index, dB):

| Band | 100–140°E | Elsewhere |
|---|---|---|
| 0–20°N | −0.9 to −1.2 | −0.2 to +0.3 |
| 10–45°S | −0.7 to −1.0 | −0.4 to +0.0 |
| 45–62°S | −0.4 to −0.5 | −0.3 to +0.1 |

("Elsewhere" is every 20-degree longitude bin outside 60–160°E.)

- **What it looks like:** an Earth-fixed effect thousands of km wide, weaker where the band sits far from the equator.
- **Hypothesis (unverified):** that is where BeiDou's geostationary (80, 110.5 and 140°E) and inclined (centred near
  118°E) satellites and QZSS sit overhead. Their L1-band signals would raise a low-orbit receiver's noise floor.
  - A rough link budget: ten signals, each about 17 dB below the noise in a 2 MHz band, add about 0.8 dB.
  - SBAS satellites over the Americas and Africa don't show it. That fits only a few signals there against many over
    Asia, but it isn't tested.
- **What it explains:** check 5's failure (inland Australia), and part of the East Asian readings, including the
  South China Sea (−1.1 to −1.5 dB). It does not explain the Gulf (about 50°E, outside the dip).
- **What it means for the result:** the four checks that held are unaffected, since the aircraft-jammed cells lie
  mostly outside 80–140°E.
- **Next:** plan step E2.1 proposes a corrected index and a pre-registered test of it.
