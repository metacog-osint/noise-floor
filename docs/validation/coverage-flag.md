# Feeder coverage flag: where Noisefloor's ADS-B view is thin (17 Nov 2026)

## Why
adsb.lol's feeders leave some busy airspace almost unseen: Ethiopia and the Volga-Urals read zero aircraft on most
days, and western Russia and Pakistan / northern India read a fraction of the traffic GPSJam sees
(`docs/validation/bad-any.md`). A quiet reading there means "not seen", not "no interference". A reader needs to
know where that is, every day, from Noisefloor's own files.

## The flag
`<day>.coverage.json` (release `pnt-data-YYYY-MM`, ODbL, from 17 Nov 2026), one row per H3 res-2 region:
`[h3_2, covered, thin]`. A res-4 cell is **covered** when it has 3 or more aircraft. A region is **thin** when fewer
than 10 of its 49 res-4 cells are covered. **A region not listed has no covered cell and is thin.** Made by
`tools/feeder_coverage.py` from the day's `map.json`, after it, in the daily run. It uses only Noisefloor's own counts.

## Test (pre-registered before any data was read)
Truth, for testing only: a region-day is thin when Noisefloor covers fewer than half of the res-4 cells that GPSJam's
daily file covers (3 or more aircraft), scored only where GPSJam covers 10 or more cells. Three Noisefloor-only rules
were stated in advance: A, fewer than 10 covered cells; B, under half the region's own 30-day median; C, A or B.
Pass: recall 0.8 or more and precision 0.6 or more on C, with Ethiopia, the Volga-Urals and western Russia flagged
on at least 80% of their thin days. Days: 2-15 Nov 2026 (14 days, 15,660 scored region-days, 5,844 truly thin).

| Rule | Recall | Precision |
|---|---|---|
| A: fewer than 10 covered cells | 0.85 (4,952 / 5,844) | 0.95 |
| B: under half its own 30-day median | 0.05 | 0.92 |
| C: A or B | 0.85 (4,966 / 5,844) | 0.95 |

Thin region-days flagged, by area (centre in the box): Ethiopia 21 / 21, Volga-Urals 59 / 59, western Russia
124 / 124, Pakistan / N. India 126 / 126, Baltic 5 / 5, Myanmar 45 / 55, Black Sea 11 / 18, Gulf 37 / 52,
Caucasus 19 / 31. False flags: 0-7 per area.

**Passed.** Rule A is published; B adds almost nothing (a region that is always thin has a low median of its own).

## How to read it
- 37% of the scored region-days were thin: adsb.lol is short of feeders over much of the world, not only in the
  named gaps.
- Misses are partial coverage: a typical missed region has 14 covered cells where GPSJam has 42. Treat a region
  with 10-20 covered cells with care, above all in the Gulf, the Caucasus and the Black Sea.
- False flags fall in sparse airspace where GPSJam itself covers about 12 cells (median), so using another source
  there costs little.
- GPSJam's files were used only to score the rule (as in the source registry: validation comparison only). Nothing
  from them is in the published file.
