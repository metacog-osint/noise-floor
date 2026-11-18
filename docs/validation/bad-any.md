# `bad_any`: an aircraft counts as bad on any gross-bad report (17 Nov 2026)

## Why
Noisefloor's per-cell counts read below GPSJam's in some regions. Over 20 days (27 Oct – 15 Nov 2026), comparing
high cells (more than 10% of aircraft bad, 3 or more aircraft) region by region, two causes separate cleanly:

- **Feeder coverage.** adsb.lol's archive has almost no aircraft in some regions. On 10 Nov 2026 it held 0 airborne
  aircraft over Ethiopia and 3 over the Volga-Urals box, against GPSJam's 50 and 94 covered cells. Noisefloor covered
  about 1 cell in 8 of GPSJam's in western Russia and 1 in 3 over Pakistan and northern India. Where both have
  coverage there, the high counts agree (Pakistan / northern India 22.6 vs 22.7 a day) or Noisefloor's is higher.
  No change to the method can fix these regions; only more feeders can. ADS-B v2 filtering removes just 3–12% of the
  aircraft heard.
- **The 50% rule.** In the Gulf, coverage is good (200 of GPSJam's 316 cells, 80% of the aircraft per shared cell),
  but Noisefloor read 12.3 high cells a day on shared cells against GPSJam's 19.8. An aircraft counts as bad in a
  cell only when 50% or more of its reports there are bad (method card, step 2). Aircraft that cross the edge of
  interference, or meet it for part of their time in a cell, are left out. GPSJam's FAQ says an aircraft is bad if it
  "reported bad navigation accuracy" during the period.

Removing post-exposure aircraft (`bad_live` against `bad_raw`) is a small effect: 0–15% of the high cells.

## What changed
`pipeline/pnt_daily.py` adds `bad_nacp_any` to the daily and hourly tables: aircraft with at least one sampled
gross-bad report (NACp < 8) in the cell. Like `bad_nacp`, it is raw (post-exposure aircraft are not removed), and
avionics suspects are dropped from every column. `<day>.map.json` gains the column `bad_any`, appended after
`capable_bad10`, for days processed from 17 Nov 2026. Every existing column is unchanged: rebuilt days matched the
published files in every cell and column (26,697 to 27,594 cells a day, 9 days). Run time does not change measurably.

## Test
Ten weekdays were rebuilt locally from adsb.lol's raw archive: 29 Oct, 3–6 Nov and 10–13 Nov 2026 (30 Oct's output
file was damaged by two overlapping local runs and is left out). Each rule's high cells (more than 10% bad, 3 or more
aircraft) were counted in 11 regions with frequent interference reports and compared with GPSJam's files for the same
day. Two middle rules were tried in a scratch build on the four days that carry all five (29 Oct, 3, 4 and 10 Nov):
bad on 25% or more of reports, and bad on 2 or more reports.

Mean high cells a day, four days, ratio to GPSJam in brackets:

| Region | GPSJam | live | raw (50%) | 25% | 2+ reports | any |
|---|---|---|---|---|---|---|
| Gulf | 23.8 | 8.0 (0.34) | 8.5 (0.36) | 11.5 (0.48) | 4.8 (0.20) | 16.8 (0.71) |
| Pakistan / N. India | 70.8 | 18.5 (0.26) | 21.2 (0.30) | 25.0 (0.35) | 14.5 (0.20) | 27.2 (0.39) |
| Western Russia | 72.0 | 23.2 (0.32) | 23.2 (0.32) | 23.5 (0.33) | 21.2 (0.30) | 23.5 (0.33) |
| Myanmar | 32.0 | 35.2 (1.10) | 39.8 (1.24) | 44.2 (1.38) | 30.2 (0.95) | 47.2 (1.48) |
| Latvia / Estonia | 41.8 | 38.0 (0.91) | 41.0 (0.98) | 50.5 (1.21) | 34.2 (0.82) | 59.0 (1.41) |
| Baltic | 126.5 | 100.5 (0.79) | 109.2 (0.86) | 133.5 (1.06) | 99.5 (0.79) | 155.8 (1.23) |
| Caucasus | 51.2 | 30.0 (0.59) | 33.2 (0.65) | 38.2 (0.75) | 17.2 (0.34) | 40.8 (0.80) |
| Kaliningrad | 20.0 | 14.2 (0.71) | 14.5 (0.72) | 15.0 (0.75) | 13.2 (0.66) | 15.0 (0.75) |
| Black Sea | 94.8 | 71.8 (0.76) | 79.0 (0.83) | 90.0 (0.95) | 67.8 (0.72) | 95.8 (1.01) |
| Whole world | 780.0 | 448.0 (0.57) | 490.2 (0.63) | 585.0 (0.75) | 395.0 (0.51) | 693.2 (0.89) |

Ethiopia and the Volga-Urals box read 0 under every rule (no coverage). Over all nine days, `bad_any` reads 0.89 of
GPSJam worldwide (raw 0.63) and 0.77 in the Gulf (raw 0.39).

Over the seven regions where Noisefloor has coverage, the mean absolute log ratio to GPSJam is 0.34 for raw, 0.28 for
25%, and 0.26 for any. `bad_any` is the closest overall and the simplest to explain, and it matches GPSJam's own
wording. It over-reads in the Baltic, Latvia / Estonia and Myanmar (1.2–1.5 times GPSJam), where many aircraft cross
interference edges and GPSJam has a little more coverage of quieter cells.

## How to read it
- `bad_live` stays the better measure of current interference: post-exposure aircraft are removed, and an aircraft
  must be mostly bad in the cell.
- `bad_any` is for comparing with GPSJam and for catching interference that an aircraft meets for only part of its
  time in a cell. It counts an aircraft with one bad report, so a cell with few aircraft can turn high on one
  brief dropout: read it with the aircraft count, and use 5 or more aircraft for public colouring (method card,
  step 6).
- Nothing on the site uses `bad_any` yet.

## Known over-read: busy daytime traffic in the US Southwest (checked 18 Nov 2026)
Against GPSJam on 2-15 Nov 2026 (10 weekday cutoffs, 3+ aircraft, b/n on both sides), `bad_any` reads 3.5 times
GPSJam's high cells in a Mexico / SW US box (18-37°N, 118-96°W; `bad_live` 0.39). Of the 192 cell-days `bad_any`
calls high there, 127 are low in GPSJam (not even 2%), and they are busy cells, not thinly flown ones: median 256
aircraft (GPSJam 268), median 36 counted bad by `bad_any`, 1 by `bad_live`.

- **Where.** Worldwide, of 97,602 cell-days with 100+ aircraft, only 93 read over 10% on `bad_any` while `bad_live`
  and GPSJam both read 2% or less. 62 of them are in the Phoenix-Tucson corridor (20 distinct cells overall); the rest
  are near San Diego, Utah Valley, the Willamette Valley, western Oklahoma and west of San Antonio.
- **When.** In six of the Phoenix-Tucson cells, hour by hour on 4, 5 and 10 Nov (`<day>.hourly.parquet`): 13-22% of
  aircraft count as bad on `bad_any` in each hour from 14:00 to 24:00 UTC (7 AM-5 PM MST), against at most 1.5% on
  `bad_live`; 1-17% in the evening to 04:00 UTC; overnight few aircraft fly there and few of them count. The cells
  turn up on every day of 2-15 Nov, fewer at weekends.
- **Not an announced test.** The nearest notices in `faa_gps_tests.json` don't fit: White Sands (within reach at
  altitude) ran 04:00-12:00 UTC each night, when these cells read clean; Thermal, CA and Middlegate, NV are out of
  range.
- **Likely cause (unverified):** brief NACp dips on aircraft that turn hard or fly training patterns, where the GPS
  antenna loses sky for a moment. These areas have heavy flight training, civil and military. Aircraft types were not
  checked (the release files hold no per-aircraft data).
- **Effect.** `bad_live` and GPSJam are not affected; one-report rules are. A guard such as two or more bad reports per
  aircraft in the cell, or a share of its reports, would need the raw archive and a pre-registered test before any
  change.

Comparison with GPSJam: GPSJam daily files (gpsjam.org/data/<day>-h3_4.csv) for side-by-side validation only, as in
the source registry.
