# Sentinel navigation receivers, X3 (lower L-band from orbit): pre-registered checks (1 Nov 2026)

**Lane:** spaceborne, step X3 of `docs/multi-gnss-plan.md`. **Builds on:** E2 and E3
(`docs/validation/sentinel-gnss.md`). **Question:** do the regions where aircraft lose GPS also show a drop at
1176 MHz (Galileo E5a) and 1227 MHz (GPS L2C) on the Sentinel receivers, and how large is it compared with L1 on the
same receivers?

## 0. What is known before this run

- **Signals held:** the E1 tables keep `s5q` (Galileo E5a) and `s2l` (GPS L2C) for the PODRIX units (Sentinel-1C, 1D
  and 2C). The RUAG units (2B, 3A, 3B) log neither. On 6 Oct 2025, Sentinel-1C had 68,393 E5a and 61,629 L2C link
  values and Sentinel-2C 57,953 and 63,287 (counted 1 Nov to plan this run; no index computed).
- **No E5a or L2C index has been computed on any day.**
- **Already measured in E3** (all units unless stated, AUC of aircraft-jammed against clean cell-windows): GPS L1 C/A
  0.862 (PODRIX units 0.872), Galileo E1 0.863, GPS L2 P(Y) 0.858.
- **Ground stations** (`docs/multi-gnss-plan.md`, X1 results): one development case only, at a station that no aircraft
  data covered.

## 1. Pre-registration

Written 1 Nov 2026, 14:10 UTC, before any E5a or L2C index exists. Results go in section 2 and do not change this
section.

### 1.1 Indices

- **Units:** Sentinel-1C, 1D and 2C (PODRIX), every day each one published. No RUAG unit, so all bands compare on the
  same receivers.
- **Method:** the frozen E2 index (`docs/validation/sentinel-gnss.md` section 1.1) applied unchanged to each signal on
  its own: per unit-day baseline in 5° bins from 10°, epoch median over 4+ links, three passes leaving out that
  signal's own res-2 cells at ≤ −1 dB.
- **Six signals:**

| Name | Links | Value |
|---|---|---|
| L1 | GPS | `s1c` |
| L1 paired | GPS links that also have `s2l` | `s1c` |
| L2C | GPS | `s2l` |
| E1 | Galileo | `s1c` |
| E1 paired | Galileo links that also have `s5q` | `s1c` |
| E5a | Galileo | `s5q` |

- The *paired* versions use exactly the satellites and epochs the lower band uses, so the ratios in 1.3 compare like
  with like.
- **Cells, judging and labels:** as E2/E3. Res-2 cells by sub-satellite point, judged at 12+ epochs from 2+ passes;
  GPSJam-style aircraft share per cell and window, paired at 140+ aircraft; jammed ≥ 10%, clean < 2%. The spacecraft
  positions and cells are taken from the E2 epoch files of the same day.
- **Windows:** the nine E3 windows (every sixth Monday from 6 Oct 2025; 63 days, all held).
- **Boxes:** Baltic and Persian Gulf as frozen in E3; the Central Pacific and Australia interior controls as in E3.

### 1.2 Checks with marks

| # | Check | Holds | Fails |
|---|---|---|---|
| X3-1 | E5a pooled AUC, jammed against clean cell-windows | ≥ 0.75 | < 0.65 |
| X3-2 | L2C pooled AUC, jammed against clean cell-windows | ≥ 0.75 | < 0.65 |

Between the marks the check is *weakened*. These ask only whether the lower band carries the signature at all. A fail
is a result, not a fault: it would mean the interference the aircraft see doesn't reach 1176 or 1227 MHz at a level
these receivers notice.

### 1.3 Band ratios (measured, with fixed readings)

For each pair, over cell-windows judged on both signals:

- **Drop** on a signal = median over jammed cell-windows − median over clean cell-windows.
- **Ratio** R = drop on the lower band ÷ drop on its paired L1 signal:
  - E5a ÷ E1 paired (same Galileo links);
  - L2C ÷ L1 paired (same GPS links).
- **Interval:** 95% bootstrap over cell-windows (2,000 resamples of the jammed and the clean sets, seed 1).
- **Where:** all jammed cell-windows pooled, the Baltic box and the Persian Gulf box. A box needs 10+ jammed cell-windows
  judged on both signals, otherwise "not judged".
- **Readings, fixed here:**
  - R < 0.33: *mostly L1* (from orbit, the lower band barely moves where L1 drops);
  - 0.33 ≤ R ≤ 0.67: *partial*;
  - R > 0.67: *wideband* (the lower band drops nearly as much as L1);
  - an interval that spans two readings is reported as both, e.g. "partial to wideband".

### 1.4 Descriptive, reported without marks

- **Each band's own background over busy airspace.** E5a shares 1164–1215 MHz with aviation DME and TACAN, and L2C sits
  in the 1215–1400 MHz radar band. For each of the six signals: median over all clean cell-windows (busy airspace with no
  jamming) minus median over the Central Pacific cells. **Flag** a lower band whose difference is ≤ −0.5 dB while its
  paired L1 signal's is above −0.25 dB: that band has a background of its own over busy land.
- **The regional dip** (`docs/validation/sentinel-gnss.md` section 2.5): Australia interior and Central Pacific box
  medians for all six signals. E5a shares its carrier with BeiDou B2a and QZSS L5, and L2C with QZSS L2C.
- Hit and false-alarm rates at −1 dB, and the AUCs of the paired L1 and E1 signals, for reference.
- Links per scored epoch for each signal, and the share of PODRIX epochs scored.

### 1.5 What would change the reading

- If X3-1 and X3-2 fail and both ratios read *mostly L1*: from orbit, the jamming behind the aircraft map is an L1
  phenomenon, and the lower bands give a cleaner background for navigation in those regions.
- If either holds and its ratio reads *wideband*: the interference covers the lower band too, and receivers that fall
  back to L5/E5a or L2C in those regions get little relief.
- A flagged own background (1.4) limits any lower-band map to the regions where the flag doesn't apply.

## 2. Results

Not yet run.
