# Event grade with A350/A380 left out (pre-registered 21 Nov 2026)

**Status:** frozen when this file is committed. Rule N below has not been run on any day. The live grade stays V0, and
the 20 Nov 2026 event stays major, unless N passes every mark here and the program owner says yes.

**Why.** `event-2026-11-20-central-europe.md` found that the major grade of `noisefloor-event-2026-11-20-1` rests mostly
on A350s and A380s, which report degraded accuracy far more readily than other types (`phase1.md`, verdicts 43 and 48).
The one existing rule that would lower it, variant H in `event-floor.md`, failed its frozen test: it demotes any event
with a high A350/A380 share, including real events in validated hotspots, where those types are most of the traffic.

**The question.** If an event is graded on the other aircraft alone, do events that rest on A350/A380 reporting lose
their grade while real events in established areas keep theirs?

## Rule N (one rule, no alternatives)

N changes only the tier of gross (93 m) events. V0's detection, its grouping into events, the capable (10 m) measure and
the burst analysis stay as they are. **N can lower a tier or leave it. It never raises a tier and never removes an event.**

1. **Two tables per day.** Each test day and each of its baseline days is processed twice from the same read: as usual
   (V0), and with A359, A35K and A388 removed from every record before the post-exposure and avionics steps
   (`pnt_daily.finish()` mode `drop`). Removing them there takes them out of both the numerator and the denominator.
2. **Share and baseline.** For each region-hour of a V0 gross event, from the second table:
   - `share_N` = 100 × live gross-bad aircraft / aircraft, rounded to 0.1, as V0 rounds it.
   - `median_N` = the median share of that region and UTC hour over **the same baseline days V0 used for this day**,
     counting only days with at least 50 aircraft in that region-hour (`ANOM_MIN_AIRCRAFT`), rounded to 0.1.
3. **Too few other aircraft to judge.** A region-hour is gradable if it has at least 50 aircraft in the second table and
   at least 5 usable baseline days (`BASE_MIN_DAYS`). Its excess is `share_N - median_N`. **A region-hour that is not
   gradable keeps its V0 excess**, because the other aircraft there cannot show whether the event was real.
4. **Tier.** The event's N excess is the largest excess among its region-hours. Its N tier comes from V0's thresholds:
   major at 25 points or more, notable at 10 or more, minor below. The final tier is the lower of the V0 tier and the N
   tier.

## Test days

- **Set A, the 20 validated days:** the same days as `event-floor.md`. They guard against losing what was validated and
  are not held out.
- **Set B, 25 Oct to 15 Nov 2026 (22 days):** the same days as `event-floor.md`. Not held out.
- **Set D, held out: 22 Nov to 5 Dec 2026 (14 days).** None of these days had begun when this file was written. If this
  file reaches `main` after 00:00 UTC on 22 Nov 2026, set D moves later by whole days, so that its first day starts after
  the commit, and stays 14 days long.
- **`event-floor.md`'s set C (16 to 29 Nov 2026) is not used here.** Its early days include the event that prompted this
  rule and days examined with it.

**Too few cases on set D.** Before N is computed on set D, count its V0 cases for P4, P5 and P6. If any of the three has
fewer than 10, extend set D by 7 days, and do so at most twice. If one is still under 10, N is not adopted.

## Corroboration

The three rules in `event-floor.md` apply unchanged, through the same code (`tools/event_floor.py`, `corroborated()`):
an established area, a declared test, or spoofing above usual in the same place.

## Pass marks

These are `event-floor.md`'s marks and thresholds, with N in place of FH and set D in place of set C.

| # | Set | Mark | Pass |
|---|---|---|---|
| P1 | A | V0 major events in a validation hotspot box that stay major under N | ≥ 90% |
| P2 | A | The same events that stay at least notable under N | ≥ 95% |
| P3 | A | Point Mugu declared test, 22 Sep 2026: every V0 major or notable event inside the advisory stays at least notable | All (not scored if V0 has none, as on 17 Nov) |
| P4 | B, D | Corroborated V0 major or notable events that stay at least notable under N | ≥ 90% |
| P5 | B, D | Corroborated V0 majors that stay major under N | ≥ 75% |
| P6 | B, D | Uncorroborated V0 major or notable events that N demotes | ≥ 50% |

**Decision.** N must pass every scored mark on sets A and B, then every mark on set D.
- If it passes, the results go to the program owner, and the grade changes only on the owner's yes.
- If any mark fails, the grade stays V0 and the results are reported here. N's thresholds are not adjusted and N is not
  rerun on these days. Any changed rule needs its own pre-registration and new held-out days.

**Reported, not scored:**
- the 20 Nov 2026 central Europe event;
- the 13 Nov notables (Irish Sea, Bay of Bengal), the 15 Nov Turkish-Georgian Black Sea coast majors, and the 1 Nov
  (near Iceland) and 6 Nov (Quebec) majors;
- events per day under V0 and N;
- the share of event region-hours that were not gradable, per set and per hotspot box.

## Disclosure: what was looked at before this was written

- `event-floor.md`'s results on sets A and B for V0, F, H and FH, including which events failed each mark.
- Verdict 48 on set A. Setting unsupported A350/A380 hex-hours apart cut major events from 35 to 13 and erased the
  Estonia–Russia border hotspot, because few other aircraft fly there. **Step 3 of the rule was written knowing this.**
  Its limits are the pipeline's existing minimums, not values chosen for this test. The `drop` mode already exists in
  `pnt_daily.py` for comparisons, and earlier comparison runs on set A may have used it.
- The 20 Nov check. With A350/A380 degraded counts taken out of the published hourly tables, that event's peak excess
  fell from 40.4 to about 13.3 points. That figure used those tables for 20 Nov and its baseline days (which include
  6 to 15 Nov, in set B), for that event's regions and hours only, and it left healthy A350s and A380s in the denominator.
- Rule N's tier has not been computed for any event on any day, and no day of set D existed.

## Procedure

1. Add N to `tools/event_floor.py` and the second table to `.github/workflows/event-floor.yml`, with tests on made-up
   counts. Run with `--no-upload`: nothing reaches the data releases, and only counts are kept, never aircraft addresses.
   Any difference from this file is written in an implementation note **before** scoring.
2. Score sets A and B. Each needs second tables for its baseline days as well.
3. When all of set D is published, apply the case-count check, then score set D.
4. Add the scorer's output below this section, unedited, with the run ids.

## Implementation note (21 Nov 2026, after freezing, before any scoring)

The rule, sets and marks above are unchanged. These details fix how the procedure runs:
- `tools/event_no_heavy.py` applies N, and the manual workflow `.github/workflows/event-no-heavy.yml` runs it.
- "At least 50 aircraft" is V0's own unit for `ANOM_MIN_AIRCRAFT`: the region-hour's aircraft summed over its res-4 cells.
- N uses the baseline days listed in each V0 day's `anomalies.json`. A missing table stops the score. It is never counted
  as "not gradable".
- 20 Nov 2026 is processed only for the reported case. It belongs to no scored set.
- The tool refuses set D until its case-count check has been added.

## Results

Not yet scored.
