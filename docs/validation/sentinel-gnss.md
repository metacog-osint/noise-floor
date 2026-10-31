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

## 2. Results

Not run yet.
