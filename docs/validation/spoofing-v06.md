# Spoofing detector v0.6: three fixes from the Lima test (pre-registered 15 Nov 2026)

**Why.** The Lima test (`spoofing-lima.md`) matched 0 of GPSWise's 56 Lima flights on 7–12 Nov 2026. The misses had
three causes in the detector, and one in the archive:
- false positions at 108–110 kt at cruise: above the slow test's 100 kt;
- a short jump to Lima and back counts as two jumps over 2,000 km, so the duplicate-address rule switched the excursion
  test off;
- for 37 flights the archive has no position near Lima at all, only MLAT positions (where the aircraft really was)
  while the aircraft itself reported about 109 kt. readsb seems to have dropped the false positions. Nothing can place
  these, but the speed mismatch shows they were spoofed.

This step adds a fix for each and scores them before adoption, on the same held-out days and limits as v0.3–v0.5 (so
false alarms are measured, not just hits), and on the Lima flights.

## Method v0.6 (frozen when this file is committed)

`tools/spoof_day.py --v06` (v0.5 stays the default until adoption). Everything in v0.5 is kept, plus:

| # | Change | Rule |
|---|---|---|
| A | Slow at cruise | A point is also slow if ground speed is under 150 kt at or above 25,000 ft baro (fast aircraft only, as for slow). A jet can't fly that slowly at cruise: true airspeed there is about 400 kt or more, and headwinds over 200 kt are rare. |
| B | Short far excursions | A segment off the main track that lasts 15 minutes or less, with main-track segments either side (within 2 h), and jumps of more than 2,000 km into and out of it, is a short far excursion. Its two jumps don't count towards the duplicate-address rule, so the excursion test runs. At most 2 per aircraft-day: more than that looks like two aircraft sharing an address, and the rule applies as before. |
| C | MLAT speed | An MLAT position at or above 25,000 ft where the aircraft's reported ground speed is under 150 kt, while MLAT shows it moving at 300 kt or more (to the nearest MLAT position 60–300 s later), is a speed point. Runs of speed points (gaps under 15 min, at least 2 points over 20 s) are episodes of kind `speed`, unless they overlap one of the aircraft's ADS-B episodes (within 60 s). Their victim location is the MLAT positions themselves; they have no spoofed-to point. Emitter categories A2–A5 or none only. |

`<day>.spoof-targets.json` (schema 2) gains `unplaced`: episodes with no spoofed-to point, grouped by the aircraft's
reported ground speed rounded to 10 kt, with episodes, aircraft, classes, first and last time and victim cells. The
grouping is general (every speed band, every day): a reader looking for one spoofer's speed signature can pick it out.

## Checks (pass marks fixed before any v0.6 run)

**Held-out days:** the 12 days of the first held-out test (`spoofing.md`, "Held-out test"): 2024-02-20, 2024-06-20,
2024-10-20, 2025-02-20, 2025-06-20, 2025-10-20, 2026-02-20, 2026-06-20, 2025-04-10, 2025-04-20, 2025-05-10, 2025-05-20.
Scored by `tools/spoof_heldout.py`. **Reproduction check, done on the v0.5 outputs before any v0.6 run:** H1 0.0019%
(published 0.0020%), H2 0.391% and 0.868% (same), H3 531 of 580 (same), H5 Beirut, Beirut, Amman (same), and 101
control-box episodes against v0.4's 100. H4 doesn't reproduce exactly: the scorer's definition (each day's top 6 res-6
cells with 5 or more aircraft, within 25 km of a point named in a source) gives 21 of 66 (31.8%) for v0.5 against the
published 23 of 65, and 24 of 65 for v0.4 against 25 of 63. The original top-cell rule wasn't written down. So H4 for
v0.6 is scored with this scorer, beside its v0.5 value (21 of 66), at the same pass mark.

| # | Check | Pass if |
|---|---|---|
| H1 | Controls: pooled active share of aircraft-hours in the six control regions | ≤ 0.01% |
| H2 | Middle East and Baltic and western Russia: pooled active share | each ≥ 0.2% and ≥ 20× H1 |
| H3 | Episodes confirmed by MLAT, of those MLAT can test (ADS-B episodes) | ≥ 75% |
| H4 | Top res-6 spoofed-to cells per day with ≥ 5 aircraft within 25 km of a named published point | ≥ 25% |
| H5 | Eastern Mediterranean, named point with the most aircraft among the day's top cells | Beirut, Beirut, Amman |
| H6 | Episodes located in a control box, all classes, v0.6 against v0.5 on the same days | ≤ 1.5× v0.5 |

H6 is new: a looser detector can stay under H1 while doubling the control false alarms, which only show as isolated or
post-exposure episodes. Every new control-box episode is listed for review.

**Lima, 7–12 Nov 2026** (same matching as `spoofing-lima.md`: same ICAO address, time overlapping GPSWise's window ±30
min, days either side searched):

| # | Check | Pass if |
|---|---|---|
| P1 | Placed: of the GPSWise Lima flights whose aircraft has ADS-B positions within 100 km of Lima in the archive during the window (14 of 56 by the v0.5 diagnosis; recounted from the raw traces), the share v0.6 places at Lima (spoofed-to point within 100 km) | ≥ 75% |
| P2 | Counted: of all 56, the share with any v0.6 episode for that aircraft in the window, anywhere, any kind | ≥ 60% |

P2's ceiling is the flights with any position in the window (51 of 56 by the v0.5 diagnosis).

**Adoption rule:** v0.6 becomes the default (`daily.yml`, and 7–13 Nov redone with backfill.yml `spoofing_only`) if
H1–H6 all pass. P1 and P2 answer the Lima question and don't gate adoption. A fix that keeps the controls clean and
finds more is adopted even if the Lima numbers fall short. If any H check fails, v0.6 stays behind its flag and the
failure is reported.

**Also reported, not scored:** per day, GPSWise Lima flights, placed, counted, and Noisefloor-only; the Lima and
Romanian-ring clusters; the `unplaced` speed band holding the Lima flights; whether a daily Lima count from the
published files would be usable, and how far it would undercount.

## Result

Not yet scored.
