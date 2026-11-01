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

## 2. Results

Not run yet.
