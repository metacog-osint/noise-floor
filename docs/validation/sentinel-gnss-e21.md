# Sentinel navigation receivers, E2.1 (regional signal load): pre-registered checks (1 Nov 2026)

**Lane:** spaceborne, plan step E2.1 (`docs/space-sensors-plan.md`). **Builds on:** E2 and E3
(`docs/validation/sentinel-gnss.md`). **Question:** does correcting the index for regional navigation and augmentation
satellites overhead remove the dip over roughly 80–140°E without weakening detection?

## 0. What has been seen (exploration, 1 Nov 2026, on the 63 E3 days only)

The tests below were run on the nine E3 windows' days. The held-out windows in section 1.2 have not been downloaded.

- **Regional satellites** (from each day's merged broadcast file):
  - BeiDou geostationary (C01–C05, C59–C62) and inclined geosynchronous (C06–C16, C38–C40);
  - every SBAS geostationary satellite;
  - QZSS, whose records were absent from the merged files on all 63 days.
- **Positions:** checked against the nominal slots: C03 at 110.5°E, C04 at 160°E, C05 at 58.7°E, C59 at 140°E and C60 at
  80°E, all at about 42,160 km. The BeiDou geostationary rotation was applied as the ICD gives it.
- **Count against the index, quiet southern band (60–10°S):** the median epoch index falls steadily with the number of
  regional satellites above 10°.
  - −0.05 dB with 0–1 overhead;
  - −0.39 dB with 14–15;
  - −0.72 dB with 20–21.
  - With no regional satellite and 0–3 SBAS satellites over the Americas or Europe/Africa, it stays between +0.08 and
    −0.07 dB.
- **Within one place** (90–130°E, 45–10°S), epochs with 4–10 inclined satellites overhead read −0.86 to −1.16 dB,
  against −0.59 dB with 3. The correlation with the inclined count is −0.12. The geostationary count also differs between
  those groups, so this is supportive, not clean.
- **Models, fitted on 10–45°S:** the range of 20-degree longitude-bin medians across the band, 1.07 dB uncorrected, fell
  to:
  - 0.62 dB with a single count;
  - 0.47 dB with an elevation-weighted count (−0.062 dB per unit);
  - 0.29–0.35 dB with per-group coefficients. These had implausible signs, such as BeiDou-3 geostationary satellites
    raising the signal, a sign of collinearity, so they are not used.
- **The Baltic box median** moved from −4.28 to −4.11 dB under the elevation-weighted model.

## 1. Pre-registration

Written 1 Nov 2026, 02:40 UTC, before any held-out window is fetched. Results go in section 2 and do not change this
section.

### 1.1 Frozen correction (E2.1)

- **Load** L for each unit and epoch: the sum of sin(elevation) over the regional satellites above 10° in the spacecraft
  frame (antenna to zenith).
  - The satellites: BeiDou geostationary and inclined geosynchronous satellites (semi-major axis above 36,000 km), QZSS
    when present, and every SBAS geostationary satellite in that day's merged broadcast file (BKG, or CDDIS as fallback).
  - Ephemerides: the nearest healthy record within 4 h.
  - BeiDou time is GPS − 14 s and BDT week 0 is GPS week 1356. BeiDou geostationary satellites use the ICD's −5° rotation.
- **Fit, per unit and day:** least squares of the E2 epoch index D on L, over the unit-day's scored epochs outside the
  cells that E2's final pass leaves out of its baseline. The fit gives the slope β.
- **Corrected index:** D′ = D − β·L. Everything else is E2 unchanged:
  - cell values per res-2 cell and window, judged at 12+ epochs from 2+ passes;
  - degraded at −1 dB;
  - aircraft labels, boxes and the region rules as in `docs/validation/sentinel-gnss.md` section 1.
- **The uncorrected index D is computed on the same windows** for every comparison.

### 1.2 Held-out windows, by a date rule

- **Rule:** seven-day windows, Monday to Sunday, every sixth Monday from 27 Oct 2025 (k = 0 … 7). They are offset three
  weeks from the E3 windows and end before the September–October 2026 days already processed.
- **The eight windows** (start dates): 2025-10-27, 2025-12-08, 2026-01-19, 2026-03-02, 2026-04-13, 2026-05-25,
  2026-07-06, 2026-08-17.
- 2 Mar and 25 May fall in the Hormuz surges; 2 Mar is the first week of the March war period.
- **Missing data:** a missing unit-day is skipped and reported. A window averaging fewer than four units a day is
  reported as thin.

### 1.3 Checks with pass marks

| # | Check | Holds if | Fails if |
|---|---|---|---|
| 1 | Quiet-band flatness: range of the 20-degree longitude-bin medians of epoch D′ over 10–45°S | ≤ 0.50 dB | > 0.80 dB |
| 2 | Pooled AUC against the aircraft map (E3 check 1, with D′) | ≥ 0.80, and no more than 0.01 below D's AUC on the same windows | < 0.70, or more than 0.03 below D's |
| 3 | The Baltic's own AUC (E3 check 3, with D′) | ≥ 0.80, and no more than 0.02 below D's | < 0.70 |
| 4 | Controls called degraded (≤ −1 dB): central Pacific, southern Africa interior and inland Australia | ≤ 2% | > 5% |
| 5 | Within place (90–130°E, 45–10°S): Pearson r between the inclined-satellite part of L and epoch D′ | \|r\| ≤ 0.05 | \|r\| > 0.10 |

Between the two marks the result is "weakened". Check 4 now includes inland Australia, which failed E3's control check;
the two South Atlantic Anomaly boxes stay reported only.

### 1.4 Reported without a pass mark

- The same five quantities for D (uncorrected) on the same windows.
- β by unit (median and range over unit-days), and the longitude profiles of D and D′ for each band (0–20°N,
  10–45°S, 45–62°S).
- Every box, every window, for D and D′; the South China Sea and Myanmar boxes in particular.
- E3's region-held-out AUC and Gulf change computed with D′ (descriptive here, since the Gulf windows differ).

### 1.5 Rules for the run

- The held-out windows are fetched only after this file is committed.
- The code that computes L and D′ is committed before any held-out result is seen, and its hash is recorded with the
  results.
- No mark, window or definition changes after a result is seen. If a bug turns up, the frozen result is reported first.
- E2.1 replaces E2 in products only if checks 1–5 hold or are weakened, with none failed, and Tom agrees.

## 2. Results (run 4 Nov 2026, 23:03 UTC)

**Code:** `tools/sentinel_e21.py`, committed as d54059d (4 Nov 2026, 20:56 UTC) before any held-out day was processed;
blob 38e574f, unchanged for the run. Tests in `tests/test_sentinel_e21.py`. Output `data/sentinel_gnss/e21_results.json`.
**Data:** all 56 held-out days fetched and processed (no unit-day failed); 5 units a day to the 2 Mar window, 6 from
13 Apr (Sentinel-1D); no window thin. The recomputed E2 index matched the epoch files on every unit-day.

**Bottom line: all five checks hold.** The correction removes the 80–140°E dip without weakening detection, and the
inland-Australia control that failed in E3 now passes.

### 2.1 Checks

| # | Check | D′ (corrected) | D (uncorrected) | Mark | Verdict |
|---|---|---|---|---|---|
| 1 | Quiet-band flatness, 10–45°S | 0.43 dB | 1.13 dB | ≤ 0.50 holds; > 0.80 fails | **holds** |
| 2 | Pooled AUC (168 jammed, 6,431 clean cell-windows) | 0.858 | 0.855 | ≥ 0.80 and within 0.01 of D | **holds** |
| 3 | Baltic AUC (24 jammed cell-windows) | 0.919 | 0.918 | ≥ 0.80 and within 0.02 of D | **holds** |
| 4 | Controls degraded (1,728 cell-windows) | 0.12% | 10.0% | ≤ 2% holds; > 5% fails | **holds** |
| 5 | Within place, r(inclined load, epoch value), 57,488 epochs | −0.022 | −0.068 | \|r\| ≤ 0.05 holds; > 0.10 fails | **holds** |

Check 4 by box: central Pacific 0.0% (D 0.08%), southern Africa interior 0.0% (D 0.6%), inland Australia 0.66% (D 56%).

### 2.2 Choices made before the run (in the module docstring at d54059d)

- **SBAS and QZSS count whatever their health value.** In these files most SBAS satellites report 31 or 63 (not for
  ranging) and QZSS reports 1 or 16 (signal bits); those describe service, not transmission, and section 0 counted
  every SBAS satellite. BeiDou records need health 0.
- **The inclined part of L** (check 5): BeiDou and QZSS satellites at 20° inclination or more.
- **Fit:** least squares with an intercept; β = 0 below 100 fit epochs or a load spread under 0.05. No unit-day hit
  the fallback (308 unit-days; the smallest fit used 2,679 epochs).
- **Check 1** uses 20° longitude bins from −180° with 100 epochs or more; every bin qualified.

### 2.3 Descriptive

- **β by unit** (median, range over unit-days, dB per unit of load): Sentinel-1C −0.041 (−0.053 to −0.024), 1D −0.045
  (−0.067 to −0.031), 2B −0.043 (−0.070 to −0.026), 2C −0.037 (−0.067 to −0.022), 3A −0.049 (−0.063 to −0.038), 3B
  −0.053 (−0.069 to −0.036). Section 0's single fit gave −0.062.
- **Longitude profiles** (20° bins, median epoch value, dB):
  - 10–45°S: D falls to −1.04 at 100–140°E; D′ stays between −0.26 and +0.17.
  - 0–20°N: D −0.98 to −1.20 at 80–140°E; D′ −0.10 to −0.25 there.
  - 45–62°S: D −0.41 to −0.48 at 80–160°E; D′ −0.13 to +0.05 there.
- **Week by week**, the quiet-band flatness of D′ is noisier than the pooled value: 0.57, 0.77, 0.58, 0.44, 0.63, 0.58,
  0.40 and 0.53 dB (D: 1.12–1.47). Weekly products would still show 0.4–0.8 dB of structure along the band.
- **Boxes** (median of judged cells, D → D′, range over the eight windows): South China Sea −0.95 to −1.52 → +0.01 to
  −0.51; Myanmar −0.80 to −1.41 → +0.06 to −0.64; India–Pakistan border −0.68 to −1.18 → −0.05 to −0.55; inland
  Australia −0.85 to −1.20 → +0.02 to −0.40. Jamming boxes keep their signal: Baltic −3.12 to −5.70 → −2.97 to −5.58;
  Persian Gulf −0.78 to −2.67 → −0.37 to −2.11; Iraq −2.48 to −3.68 → −2.02 to −3.27; Levant −1.57 to −3.38 → −1.22
  to −3.09.
- **Region-held-out minimum AUC:** D′ 0.865, D 0.858.
- **A positive offset:** D′ = D − β·L subtracts the whole load, though each unit-day baseline already absorbs the
  average load, so D′ reads above zero wherever regional satellites are in view: the Central Pacific +0.02 to +0.41 dB,
  Brazil interior +0.07 to +0.52 dB, the 0–20°N band +0.17 to +0.49 dB. No check is affected. A product would need
  the offset removed (for example, β·(L − mean L) per unit-day), which is a new definition and would be stated as one.
- **The broadcast files changed.** From the 25 May 2026 window the IGS merged file (BRDC00IGS_R) no longer carries
  several operating BeiDou-3 satellites (geostationary C59 and C60, inclined C39 and C40, medium-orbit C43–C50), and
  C05, C13 and C16 left the regional set. The regional count fell from 7 geostationary and 10 inclined to 4 and 5, and
  the median load over 90–130°E, 45–10°S from about 19–20 to 15. The per-unit-day slope absorbs much of this (flatness
  0.40–0.58 dB in those windows), but a product should take the load from a fuller merged file.
- **The lower-band drift over East Asia replicates on these held-out weeks** (band files, median minus the Central
  Pacific, dB): GPS L2C over 30–65°N, 100–150°E −0.77, −0.90, −1.08, −1.13, −1.52, −1.77, −1.87, −2.52 from Oct 2025
  to Aug 2026; Galileo E5a −0.90 to −2.84; inland Australia (L2C) −0.20 to −0.67, the central US −0.52 to +0.17 and
  the North Atlantic −0.48 to +0.13 with no trend. See `docs/validation/sentinel-gnss-x3.md` section 2.6.

### 2.4 What follows

- By section 1.5, E2.1 may replace E2 in products once Tom agrees, since every check held.
- Before it does: remove the offset (2.3) as a stated new definition, and take the load from a merged file that carries
  every BeiDou-3 satellite. Neither changes this result.
