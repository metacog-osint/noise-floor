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

## 2. Results (run 1 Nov 2026, 14:48 UTC)

`python tools/sentinel_bands.py bands` on the 63 window days, then `checks` (`data/sentinel_gnss/x3_results.json`).
The pre-registration was committed as 5a718af at 14:06 UTC; the "14:10 UTC" in section 1 should read 14:05.

**Bottom line: both checks hold, and the lower bands drop more than L1, not less.** On the same Galileo and GPS links,
the index falls two to three times as far at 1176 MHz (E5a) and 1227 MHz (L2C) as at 1575 MHz. By the fixed readings
that is *wideband*. The reading's wording, "nearly as much as L1", understates it.

### 2.1 Checks

| # | Signal | AUC | Jammed / clean cell-windows | Verdict |
|---|---|---|---|---|
| X3-1 | Galileo E5a | 0.911 | 177 / 6,355 | **holds** |
| X3-2 | GPS L2C | 0.898 | 178 / 6,433 | **holds** |

For reference, on the same PODRIX units: GPS L1 0.872, L1 paired 0.870, Galileo E1 0.863, E1 paired 0.863. Both lower
bands separate the aircraft-jammed regions better than L1 does.

### 2.2 Band ratios

| Pair | Where | Jammed | Drop, lower band | Drop, paired L1 | R (95% interval) | Reading |
|---|---|---|---|---|---|---|
| E5a / E1 paired | pooled | 177 | −8.67 dB | −3.25 dB | 2.67 (2.47–2.93) | wideband |
| E5a / E1 paired | Baltic | 28 | −10.61 dB | −4.98 dB | 2.13 (1.92–2.38) | wideband |
| E5a / E1 paired | Persian Gulf | 7 | | | | not judged |
| L2C / L1 paired | pooled | 178 | −8.87 dB | −3.39 dB | 2.62 (2.38–2.92) | wideband |
| L2C / L1 paired | Baltic | 28 | −11.12 dB | −4.97 dB | 2.24 (2.03–2.55) | wideband |
| L2C / L1 paired | Persian Gulf | 7 | | | | not judged |

The Persian Gulf had 7 jammed cell-windows judged on both signals, under the 10 required.

### 2.3 Descriptive

- **Own background over busy airspace** (clean cell-windows minus the Central Pacific): L1 −0.45, L1 paired −0.50,
  L2C −0.44, E1 −0.50, E1 paired −0.49, E5a −0.81 dB. **No flag:** every band reads low there, so the paired L1 signals
  are not quiet. E5a reads 0.3 dB lower than E1. That could be aviation DME and TACAN, or E5a's larger response to
  jamming nearby (clean cells within 2,000 km of jammed ones read low on L1 too; E3). This run can't tell them apart.
- **The regional dip** (box medians, dB):

| Signal | Central Pacific | Australia interior | Difference |
|---|---|---|---|
| GPS L1 | −0.14 | −1.39 | −1.25 |
| Galileo E1 | −0.17 | −1.24 | −1.07 |
| Galileo E5a | −0.10 | −1.27 | −1.17 |
| GPS L2C | +0.01 | −0.30 | −0.31 |

  The dip is a quarter as deep on L2C. Its 1227.60 MHz carrier is the only one of the four that no BeiDou signal shares
  (only QZSS L2C sits there). L1 and E1 share 1575.42 MHz with BeiDou B1C, and E5a shares 1176.45 MHz with BeiDou B2a.
  This supports the regional-signal explanation of the dip (`docs/validation/sentinel-gnss.md` section 2.5, plan step
  E2.1), from a direction the E2.1 correction doesn't use.
- **Hit and false-alarm rates at −1 dB:** L1 0.97 / 0.35; L2C 0.98 / 0.30; E1 0.95 / 0.39; E5a 1.00 / 0.47. The fixed
  −1 dB call suits E5a least, because its spread is wider.
- **Links per scored epoch** (median): 7 for the GPS signals and 6 for the Galileo ones. **Share of PODRIX epochs
  scored:** 0.988–1.000.
- **Units:** Sentinel-1C and 2C in every window; 1D from the 4 May 2026 window.

### 2.4 Robustness (exploratory, not pre-registered)

- **Per unit:** E5a / E1 paired 2.45 (Sentinel-1C), 2.40 (1D), 2.76 (2C); L2C / L1 paired 2.15, 2.61, 2.25.
- **Per window** (the seven with 10+ jammed cell-windows): E5a / E1 paired 2.04–2.93; L2C / L1 paired 1.76–4.49.
- **Lost links don't drive it:** jammed and clean cell-windows both keep a median of 6 links per scored epoch on every
  signal. The paired L1 signals use only links where the lower band was tracked, so both sides of each ratio lose the
  same links.

### 2.5 What it means, and what it doesn't

- **The regions where aircraft lose GPS are at least as disturbed at 1176 and 1227 MHz, as these receivers hear them.**
  By section 1.5, a receiver that falls back to L5/E5a or L2C in those regions would get little relief.
- **The size of the ratio has two possible sources, not separated here** (unverified):
  - the emitters put more power into the lower L-band than at L1;
  - the receivers pick up the ground better at lower frequencies. Their antennas point away from Earth, so a ground
    emitter arrives through side and back lobes, and how much leaks around an antenna depends on frequency. The PODRIX
    antenna patterns were not checked.
- **In interference terms:** a 3.25 dB drop means interference about equal to the receiver's noise (J/N ≈ 1.1); an
  8.67 dB drop means J/N ≈ 6.4. As received, the lower band carries about 7.6 dB more interference relative to noise.
- **The ground station case points the same way.** At Vaiņode (`docs/multi-gnss-plan.md`, X1 results) the lower L-band
  fell furthest on both evenings. That was a single development case at a site no aircraft data covered.
- **Effects only.** Nothing here identifies an emitter or its type.

### 2.6 After the fact: a lower-band drift over East Asia (exploratory, 1 Nov 2026, 16:40 UTC)

Found while building box trends on L2C. Not pre-registered; the regions were drawn after the first look.

- **What:** median index minus the Central Pacific, PODRIX units, per E3 week (Oct 2025 – Sep 2026) and for the weeks
  of 28 Sep and 19 Oct 2026:

| Region | L2C, Oct 2025 | L2C, Sep–Oct 2026 | L1 (same receivers), Oct 2025 | L1, Sep–Oct 2026 |
|---|---|---|---|---|
| China interior (28–40°N, 100–115°E) | −1.23 | −1.86 to −2.96 | −1.36 | −1.18 to −1.81 |
| North-east China and Amur (45–55°N, 120–135°E) | −1.17 | −2.49 to −3.05 | −0.58 | −0.95 to −1.32 |
| East Siberia (55–68°N, 105–135°E) | −0.76 | −2.68 to −3.42 | +0.20 | −0.48 to −0.92 |
| Japan (33–42°N, 135–145°E) | −0.63 | −2.02 to −2.84 | −1.01 | −1.17 to −1.95 |
| North-west Pacific (30–42°N, 150–170°E) | −0.20 | −1.75 to −2.01 | −0.75 | −1.12 to −1.49 |
| Australia interior | −0.31 | −0.38 to −0.55 | −0.73 | −0.81 to −1.32 |
| Indian Ocean (35–10°S, 60–95°E) | −0.17 | −0.25 to −0.53 | −0.57 | −0.41 to −1.13 |
| Central US (35–45°N, 105–90°W) | −0.42 | −0.17 to −0.55 | −0.32 | −0.11 to +0.01 |
| North Atlantic (40–55°N, 45–25°W) | −0.43 | −0.44 to −0.55 | +0.10 | −0.38 to +0.14 |

- **East Asia slid 1.2–2.2 dB on L2C over the year** (mean of the three late weeks against October 2025, by region); **the other regions didn't.** On L1 from the same receivers the East
  Asian change is smaller (about 0.3–1 dB) and noisier.
- **Galileo E5a slid over East Asia too** (30–65°N, 100–150°E: from −0.4 to −0.6 dB in Oct 2025 to −1.9 to −3.9 dB in
  Sep–Oct 2026, every unit).
- **Not a change of receivers:** Sentinel-1C and 2C each show it (L2C −0.84 and −1.07 dB in Oct 2025; −2.38 to −3.07
  and −2.36 to −2.80 dB in Sep–Oct 2026), and Sentinel-1D matches them from May 2026.
- **Not obviously a GPS transmitter change:** per GPS satellite, on the same links over East Asia, L2C minus L1 C/A was
  about 0 dB in Oct 2025 and −0.5 to −2.9 dB for 27 of 28 satellites in Oct 2026. GPS "flex power" can shift power
  between signals over chosen regions, but it would not move Galileo E5a, which slid as well.
- **Not the BeiDou overlap behind the L1 dip:** L2C shares no carrier with BeiDou, and Australia and the Indian Ocean,
  under the same BeiDou satellites, stayed flat.
- **Not explained:** a broad rise in lower L-band interference over East Asia would fit (the lower bands respond
  about 2.6 times as strongly, section 2.2), and so would other regional emitters in 1164–1300 MHz, such as L-band
  radars. Western Europe and West Siberia read far lower on every band, within reach of the Baltic and Russian jamming.
- **Ground check (1 Nov 2026, 17:40 UTC; exploratory).** Six IGS stations, one day in each E3 week plus 30 Sep and
  21 Oct 2026, from NASA CDDIS, with `tools/station_bands.load_day` (all systems and signals, broadcast orbits). On each
  satellite at 15° or more, each band minus L1 C/A on the same satellite, averaged over 5° elevation bins (dB):

| Station | GPS L2C − L1, Oct 2025 | GPS L2C − L1, Sep–Oct 2026 | QZSS L2C − L1, Oct 2025 | QZSS L2C − L1, Sep–Oct 2026 | Galileo E5a − E1, Oct 2025 → Sep–Oct 2026 |
|---|---|---|---|---|---|
| STK200JPN (Hokkaido) | +0.53 | +0.40 to +0.61 | +3.56 | +3.30 to +3.61 | +1.37 → +1.09 to +1.30 |
| MIZU00JPN (northern Honshu) | −2.03 | −1.98 to −1.85 | +1.39 | +1.22 to +1.40 | +3.27 → +2.89 to +3.04 |
| MCIL00JPN (Minamitorishima) | +0.76 | +1.10 to +1.32 | +4.00 | +4.00 | +2.04 → +1.74 to +1.87 |
| DAEJ00KOR (Daejeon; files to 29 Jul) | +2.46 | +2.43 (Jul) | +5.24 | +5.30 (Jul) | +4.24 → +3.80 (Jul) |
| GUAM00GUM (control) | −1.36 | −1.37 to −1.31 | +2.33 | +2.12 to +2.18 | +3.63 → +3.03 to +3.20 |
| ALIC00AUS (inland Australia, control) | −0.05 | −0.28 to −0.10 | +3.02 | +2.76 to +2.86 | +3.74 → +3.46 to +3.59 |

  - **Not a GPS transmitter change.** A change in what the GPS satellites send would reach these antennas too. GPS L2C
    relative to L1 ended the year within 0.25 dB of where it started at every station except Minamitorishima, where it
    rose 0.3–0.6 dB, the opposite direction (Daejeon swung 0.5 dB within the year and came back). QZSS L2C relative to
    L1 ended within 0.3 dB everywhere.
  - **No lower-band change at ground level near these stations.** Galileo E5a against E1 eased by 0.1–0.6 dB at every
    station, the controls included, so it isn't East Asian. L1 C/A at 40–60° held within 0.4 dB at four stations;
    Daejeon varied 0.7 dB with no trend, and at Minamitorishima it eased about 0.6 dB while L2C and L5 held, an L1-only
    change at that site, the opposite of the orbital pattern.
  - **Equipment:** firmware updates at Mizusawa, Guam and Alice Springs during the year left no step.
  - **So the drift is in what the orbiting receivers hear, not in the signals the satellites send.** A ground antenna
    hears an emitter only within line of sight (`docs/validation/ground-stations.md` section 6). Emitters spread over
    the region, or elevated or airborne ones, could reach 700–800 km altitude without reaching these sites. Cause still
    not established.
- **Rhythm check (1 Nov 2026, 18:10 UTC; exploratory).** The PODRIX units are sun-synchronous, so each passes a place at
  nearly the same local solar time every day: over East Asia, Sentinel-1C and 1D at about 06:30 and 17:00, Sentinel-2C
  at about 11:00 and 22:00. Each value below is East Asia (30–65°N, 100–150°E) minus the Central Pacific for the same unit
  and pass, which cancels receiver and pass-direction effects (dB; Oct–Nov 2025 = the first two E3 weeks; Sep–Oct
  2026 = 7 Sep – 25 Oct, 49 days):

| Pass over East Asia | L2C, Oct–Nov 2025 | L2C, Sep–Oct 2026 | E5a, Oct–Nov 2025 | E5a, Sep–Oct 2026 | L1 (same receivers), Oct–Nov 2025 | L1, Sep–Oct 2026 |
|---|---|---|---|---|---|---|
| about 06:30 (Sentinel-1C; 1D from May) | −0.35 | −2.70 (1D −2.75) | −0.60 | −3.36 (1D −3.50) | −0.19 | −1.33 (1D −1.28) |
| about 11:00 (Sentinel-2C) | −0.83 | −2.20 | +0.09 | −1.92 | +0.57 | +0.16 |
| about 17:00 (Sentinel-1C; 1D from May) | −1.20 | −2.77 (1D −2.83) | −1.72 | −2.19 (1D −2.28) | −1.20 | −1.07 (1D −1.05) |
| about 22:00 (Sentinel-2C) | −0.88 | −2.95 | −0.87 | −2.41 | −1.74 | −1.83 |

  - **No daily rhythm at the sampled times:** in Sep–Oct 2026, L2C reads 2.2–3.0 dB low on all four passes, morning,
    midday, evening and night. The orbits sample only those four times; the hours between them, including the night
    from about 22:00 to 06:00 local, are unchecked.
  - **No weekly rhythm:** East Asia minus the Central Pacific by local day of week, Sep–Oct 2026 (14 values each):
    L2C −2.60 (Saturday) to −3.19 (Sunday), every day within that range; E5a −2.58 to −3.06; L1 −1.03 to −1.37. No
    weekend relief.
  - **L1 moved on one pass only:** about 1.1 dB on Sentinel-1's morning pass and 0.4 dB or less on the other three.
  - **Reading:** whatever lowers the lower band over East Asia was there at every sampled hour and on every day of the
    week. That fits something running continuously rather than working-hours or scheduled activity. Still effects only;
    cause not established.
- **Next:** ITU and NOTAM records of lower L-band activity in the region, and the same regional table on the held-out
  E2.1 weeks once they are fetched.
