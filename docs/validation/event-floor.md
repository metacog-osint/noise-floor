# Event grade: a distinct-aircraft floor and an A350/A380 demotion (pre-registered 16 Nov 2026)

**Why.** The suite review of 15 Nov 2026 (Mistake 4) found two gaps in the anomaly-event grade
(`pipeline/pnt_analysis.py`, `anomalies()` and `anomaly_events()`):

1. A region-hour sums one count per aircraft per res-4 cell it crossed (`region_hours()`), and the binomial z treats
   those counts as independent aircraft. An airliner at cruise crosses several res-4 cells an hour, so one or two
   airframes can make a region-hour anomalous when the region's baseline is near zero. On 13 Nov 2026, 134 of 204
   anomalous gross region-hours had a baseline median and MAD of 0. Two notable events that day had a heavy share of
   1.0, with 9 to 12 bad counts: the Irish Sea at 04 UTC (54.33N 4.25W) and the Bay of Bengal at 17-18 UTC
   (13.27N 81.24E).
2. `heavy_share`, the share of an event's live gross-bad counts from A350s and A380s, is computed but not used in the
   tier. Measured from the live event files on 16 Nov 2026, 94 of 289 major or notable jamming events on 31 Oct to
   15 Nov 2026 had a heavy share of 0.5 or more (33%). Among majors it was 21 of 35 (60%). 101 of the 289 were a
   single region-hour.

**What earlier work says.** Verdict 48 (`phase1.md`, 22 Oct 2026) tested seven ways of setting A350/A380 degradation
apart by type on the 20 validated days. Every type-based variant cost real detections. Setting unsupported A350/A380
hex-hours apart cut major events from 35 to 13 and erased the Estonia–Russia border hotspot (94.3% to 5.0%), because
few other aircraft fly there. A350s and A380s carry a median 71% of degraded aircraft-minutes in Black Sea and
Caucasus bursts. The method stayed v1.4, and any detector change waits for a held-out check. This test is that check
for the two changes Tom approved on 16 Nov 2026. The risk it has to rule out is verdict 48's: demoting real events in
real hotspots because the aircraft there are mostly A350s and A380s.

## Variants (frozen when this file is committed)

Only the gross (93 m) measure changes; the capable (10 m) measure and the burst analysis stay as they are.

| Variant | Rule |
|---|---|
| V0 | The current grade: anomalous region-hours (`ANOM_MIN_AIRCRAFT` 50, z ≥ 4, excess over max(2 points, 4 × MAD)), grouped into events (ring 1, within one hour), tier by peak excess: major ≥ 25 points, notable ≥ 10, minor below |
| F | V0, but a gross region-hour counts as anomalous only if **3 or more distinct aircraft** sent a live gross-bad report in it. Events are then grouped from the region-hours that remain |
| H | V0, then every event with `heavy_share` ≥ 0.5 **drops one tier** (major to notable, notable to minor). `heavy_share` as computed now: A350/A380 live gross-bad counts over all live gross-bad counts, summed over the event's region-hours |
| FH | F, then H's demotion on the events F leaves. This is the change proposed for adoption |

**Distinct aircraft:** ICAO addresses with at least one report of NACp below 8 in any res-4 cell of the res-2 region
during the UTC hour, counted live (latched and post-exposure aircraft left out, as `bad_nacp_live` is). An aircraft
counts once per region-hour however many cells it crossed. This needs a new count from `pipeline/pnt_daily.py`, so
the test days are reprocessed from adsb.lol's raw archives; only counts are kept, never addresses. V0, F, H and FH are
all scored on the same reprocessed tables, so the comparison is like for like.

## Test days

- **Set A, the 20 validated days** (`tools/export_site_data.py` `DAYS` at 9ec9e6a): 9-25 Oct 2025, 11 and 12 Nov 2025,
  22 Sep 2026. They were used to build the method, so they guard against losing what was validated; they are not
  held out. Their published tables predate `heavy_live` (25 Oct 2026), so they are reprocessed.
- **Set B, 25 Oct to 15 Nov 2026** (22 days), the daily-run days with `heavy_live`. The review's counts came from
  31 Oct to 15 Nov, so these days motivated the question. The thresholds (3 aircraft, 0.5) were set by the review
  before any scoring and are not tuned here.
- **Set C, held out: 16 to 29 Nov 2026** (14 days), which did not exist when this was written. Scored once all 14
  are published.

## Corroboration (fixed before scoring)

An event is **corroborated** if any of these holds, using only files that exist independently of the event grade:

1. **Established area:** its res-2 region, or a ring-1 neighbour, had 3 or more res-4 cells at jamming scale
   (`tools/board.py` `jam_regions()` rule) on 3 or more of the 30 days before the event day, from the published day
   maps.
2. **Declared test:** an FAA GPS test in that day's event file (`tests`) whose window overlaps the event's hours and
   whose largest published radius reaches the event's point.
3. **Spoofing in the same place:** the day's spoofing file shows the event's region, or a ring-1 neighbour, above its
   usual level (`level2`), where the day has it.

Every other major or notable event is **uncorroborated**.

## Pass marks

FH is adopted only if every mark passes on sets A and B, and then again on set C. If FH fails but F or H alone passes
every mark, that variant goes to Tom with the results, and nothing changes without his yes. If none passes, the grade
stays V0, and the results are reported here.

| # | Set | Mark | Pass |
|---|---|---|---|
| P1 | A | V0 major events whose point lies in a validation hotspot box (the `HOTSPOTS` list in `tools/export_site_data.py` at 9ec9e6a without the high-latitude control: Kaliningrad and approaches, Gulf of Finland / Estonia–Russia border, Southern Black Sea offshore Turkey, Western Black Sea coast, Caucasus) that stay major under FH | ≥ 90% |
| P2 | A | The same events that stay at least notable under FH | ≥ 95% |
| P3 | A | The Point Mugu declared test, 22 Sep 2026 18:30-20:29Z: every V0 major or notable event inside the advisory's FL250 radius in that window stays at least notable under FH | All (if V0 has none, P3 is not scored and that is reported) |
| P4 | B, C | Corroborated V0 major or notable events that stay at least notable under FH | ≥ 90% |
| P5 | B, C | Corroborated V0 majors that stay major under FH | ≥ 75% |
| P6 | B, C | Uncorroborated V0 major or notable events that FH removes or demotes | ≥ 50% |

P5 is looser than P1, because a corroborated event outside the validated boxes can be a true weak event that F and H
should demote. P1, P2 and P5 are the guard against verdict 48's failure.

**Reported, not scored:** the two 13 Nov notable events (Irish Sea, Bay of Bengal), expected to drop under F; the two
15 Nov majors on the Turkish–Georgian Black Sea coast (41.26N 41.05E, heavy share 0.80 and 0.70), an established
exposure area (phase1 verdict 25), which H would demote to notable; events per day and majors per day under each
variant; and each mark for F and H alone.

## Disclosure: what was looked at before this was written

The review's counts (13 Nov anomalies file; 31 Oct to 13 Nov event files), the 16 Nov re-count of heavy shares on the
live event files for 31 Oct to 15 Nov (94 of 289, majors 21 of 35), the event list of 15 Nov, and verdict 48. No
distinct-aircraft count has been made for any day, and no variant has been run.

## Procedure

1. `pnt_daily.py` writes the distinct count per res-2 region and hour (a new column or table; addresses never leave
   the run). `pnt_analysis.py` takes `--variant F|H|FH` and writes to a separate folder; the default stays V0.
2. Sets A and B are reprocessed on GitHub Actions (the repo is public, so minutes are free), not on the shared PC.
3. A scoring script applies the corroboration rules and the marks above and writes the results under this file,
   unedited.

## Implementation note (17 Nov 2026, after freezing, before any scoring)

The rules, sets and marks above are unchanged. Two details of the procedure differ from step 1:
- `pnt_daily.py` writes the distinct counts as a new table, `<day>.region_hourly.parquet` (`region_hour_counts()`;
  the daily run uploads it from 17 Nov 2026, so set C needs no reprocessing).
- `pnt_analysis.py` is untouched, so the default grade stays V0. F, H and FH are applied in `tools/event_floor.py`.
  It regroups V0's anomalous region-hours with the analysis's own grouping and grading, and follows each V0 event into
  each variant by its region-hours.

`.github/workflows/event-floor.yml` reprocesses each day with `daily_job.py DAY --force --no-upload`, so nothing
reaches the data releases. It then scores; the day files and the report are workflow artifacts.

## Results

Scored 17 Nov 2026 on sets A and B: Actions run 44017695256 (44 jobs: plan, 42 days, score; all succeeded),
`tools/event_floor.py` at 891c1f1, report artifact `event-floor-report`. Set C is not yet scored. The values below are
the scorer's output, unedited; the checks after them were made before this section was written.

### Verdicts (value, n)

| Mark | Set | Pass | FH | F | H |
|---|---|---|---|---|---|
| P1 | A | ≥ 90% | 0.500, n 10: **fail** | 1.000, n 10: pass | 0.500, n 10: **fail** |
| P2 | A | ≥ 95% | 1.000, n 10: pass | 1.000, n 10: pass | 1.000, n 10: pass |
| P3 | A | all | not scored (n 0) | not scored (n 0) | not scored (n 0) |
| P4 | B | ≥ 90% | 0.613, n 271: **fail** | 0.823, n 271: **fail** | 0.760, n 271: **fail** |
| P5 | B | ≥ 75% | 0.425, n 40: **fail** | 1.000, n 40: pass | 0.400, n 40: **fail** |
| P6 | B | ≥ 50% | 0.899, n 109: pass | 0.872, n 109: pass | 0.330, n 109: **fail** |
| P4-P6 | C | | no cases yet | no cases yet | no cases yet |

**Outcome under the frozen rule: no variant passes every mark on A and B, so the grade stays V0.** FH fails P1, P4B
and P5B. F fails only P4B. H fails P1, P4B, P5B and P6B. Set C cannot change this: adoption needed every mark on A
and B first. `pipeline/pnt_analysis.py` is unchanged.

**P3 not scored:** V0 has no major or notable event within 623 NM of the Point Mugu advisory's centre (34.36N
121.69W) in 18-20 UTC on 22 Sep 2026. That day's nine V0 notables are in Norway, India (three), Montenegro, the
Turkish-Georgian Black Sea coast, Hungary-Romania, Algeria and Syria.

### What drives each failure (counts from the report's event rows)

- **H, P1:** 5 of the 10 V0 majors in the hotspot boxes have a heavy share of 0.5 or more and drop to notable:
  Caucasus 16 Oct 2025 (0.957, 11 distinct aircraft), Southern Black Sea offshore Turkey 18 Oct 2025 (0.873),
  Caucasus 20 Oct 2025 (0.542) and 23 Oct 2025 (0.667 and 0.58). This is verdict 48's failure: real events in
  validated hotspots demoted because most aircraft there are A350s and A380s. The 16 Oct 2025 Caucasus major is at the
  same point (41.26N 41.05E) as the 15 Nov 2026 Turkish-Georgian coast majors below. FH inherits this failure; F keeps
  all 10 majors.
- **F, P4B:** 48 of 271 corroborated set-B events (all V0 notables) drop below notable: 37 to none, 11 to minor.
  37 of the 48 had at most 2 distinct live gross-bad aircraft in every region-hour (23 with 2, 14 with 1). 46 were
  corroborated as established areas (16 also with spoofing above usual), 2 by spoofing alone; their established-day
  counts run from 3 to 30 of 30. The commonest places (rounded) are 20N 100E (4), 24N 62E, 30N 74E and 47N 26E (3 each). So the established-area rule corroborates the place, while the event itself rests on one or two
  aircraft. The rule is frozen and the mark is failed as written.
- **H, P4B and P5B:** 65 corroborated notables with a heavy share of 0.5 or more drop to minor; 24 of 40 corroborated
  majors drop to notable.
- **H, P6B:** H never removes an event, and only 36 of 109 uncorroborated events had a heavy share of 0.5 or more.
  F removes 89 of the 109 and demotes 6 more; FH removes the same 89 and demotes 9 more.

On set A, beyond the scored marks: of 293 V0 major or notable events, F keeps 175 at notable or above and 43 of 44
majors as major; H keeps 243 and 16 of 44 majors; FH keeps 152 and 15 of 44.

### Named cases (reported, not scored)

- **Irish Sea, 13 Nov 2026, 04 UTC** (54.33N 4.25W): V0 notable, heavy share 1.0, 1 distinct aircraft. F none, H minor,
  FH none. Uncorroborated.
- **Bay of Bengal, 13 Nov 2026, 17-18 UTC** (13.27N 81.24E): V0 notable, heavy share 1.0, 1-2 distinct aircraft.
  F none, H minor, FH none. Uncorroborated.
- **Turkish-Georgian Black Sea coast, 15 Nov 2026** (41.26N 41.05E): V0 majors at 00-02 UTC (heavy share 0.80, 20
  distinct aircraft) and 23 UTC (0.697, 12): F major, H notable, FH notable. A notable at 04 UTC (0.421, 8): notable
  under every variant. All three corroborated (established, 30 of 30 days).
- The two uncorroborated set-B majors are of the same kind as the 13 Nov notables: 1 Nov 2026 near Iceland (64.6N
  21.16W, 08 UTC) and 6 Nov 2026 in Quebec (47.43N 72.03W, 12 UTC), each 2 distinct aircraft and heavy share 1.0.
  F and FH remove both; H makes them notable.

### Days scored and not scored

All 42 days of sets A and B were reprocessed and scored; no day job failed and no day reported an error. 9-14 Oct
2025, the first six days of set A, had short baselines because no earlier days exist: 8, 9, 10, 11, 12 and 13 baseline
days (14 from 15 Oct 2025 on). 9 and 10 Oct 2025 show 418 and 387 anomalous region-hours (both measures) against
20-47 on every other day. Their events are scored as the pipeline graded them. Set C (16-29 Nov 2026) is not yet
scored.

### Checks on the scorer (made before this section was written)

- **Following events through:** the 18 Oct 2025 Kaliningrad major (28 region-hours) keeps 22 under F, regrouped as
  one major with the same peak excess (28.6); H and FH leave it major (heavy share 0.253, 0.274 after the floor). The
  16 Oct 2025 Caucasus major (1 region-hour, 11 aircraft, heavy share 0.957) stays major under F and becomes notable
  under H and FH. Each matches the rules.
- **Established areas, re-counted by hand:** an independent script (not `board.jam_regions`) re-applied the
  jamming-scale rule (5+ aircraft, 100 × (bad − 1) / aircraft ≥ 10, 3+ res-4 cells per res-2 region) to the 30
  published day maps before each event. 25 Oct 2026 notable at 39.28N 114.89E: 6 of 30 days (scorer: 6). 1 Nov 2026
  major near Iceland: 0 of 30 (scorer: uncorroborated). 15 Nov 2026 Turkish-Georgian coast: 30 of 30 (scorer: 30).
  None of the three had a region or ring-1 neighbour above usual in that day's spoofing file, as the scorer found.
- **Declared tests:** the events files split each advisory's windows by UTC day, so the scorer's hour match does not
  miss windows that cross midnight. 12 set-B events were corroborated by a White Sands (WSMR) advisory.
- No scorer bug was found, so nothing was re-scored.

### Events per day, by variant (majors / notables)

| Day | Set | V0 | F | H | FH | Gross region-hours (before / after floor) |
|---|---|---|---|---|---|---|
| 2025-10-09 | A | 1 / 10 | 1 / 6 | 1 / 8 | 1 / 4 | 105 / 33 |
| 2025-10-10 | A | 2 / 17 | 2 / 11 | 0 / 15 | 0 / 10 | 135 / 43 |
| 2025-10-11 | A | 1 / 13 | 1 / 6 | 0 / 12 | 0 / 6 | 104 / 39 |
| 2025-10-12 | A | 2 / 5 | 2 / 2 | 0 / 7 | 0 / 4 | 93 / 32 |
| 2025-10-13 | A | 1 / 11 | 1 / 5 | 0 / 10 | 0 / 6 | 110 / 35 |
| 2025-10-14 | A | 0 / 14 | 0 / 6 | 0 / 13 | 0 / 5 | 127 / 48 |
| 2025-10-15 | A | 4 / 11 | 3 / 5 | 1 / 8 | 0 / 7 | 122 / 37 |
| 2025-10-16 | A | 6 / 9 | 6 / 2 | 3 / 11 | 3 / 5 | 146 / 57 |
| 2025-10-17 | A | 3 / 13 | 3 / 8 | 1 / 13 | 1 / 9 | 162 / 65 |
| 2025-10-18 | A | 3 / 13 | 3 / 4 | 1 / 14 | 1 / 6 | 130 / 49 |
| 2025-10-19 | A | 0 / 9 | 0 / 6 | 0 / 8 | 0 / 6 | 126 / 39 |
| 2025-10-20 | A | 2 / 16 | 2 / 13 | 1 / 11 | 1 / 8 | 133 / 48 |
| 2025-10-21 | A | 1 / 16 | 1 / 12 | 0 / 15 | 0 / 13 | 199 / 98 |
| 2025-10-22 | A | 8 / 13 | 8 / 9 | 5 / 14 | 5 / 11 | 190 / 118 |
| 2025-10-23 | A | 5 / 10 | 5 / 6 | 2 / 11 | 2 / 9 | 198 / 113 |
| 2025-10-24 | A | 0 / 15 | 0 / 11 | 0 / 13 | 0 / 9 | 165 / 77 |
| 2025-10-25 | A | 4 / 23 | 4 / 10 | 1 / 19 | 1 / 10 | 153 / 58 |
| 2025-11-11 | A | 0 / 9 | 0 / 5 | 0 / 8 | 0 / 5 | 132 / 31 |
| 2025-11-12 | A | 1 / 13 | 1 / 6 | 0 / 12 | 0 / 7 | 146 / 44 |
| 2026-09-22 | A | 0 / 9 | 0 / 4 | 0 / 5 | 0 / 1 | 108 / 24 |
| 2026-10-25 | B | 3 / 11 | 3 / 5 | 1 / 8 | 1 / 6 | 173 / 77 |
| 2026-10-26 | B | 1 / 10 | 1 / 7 | 0 / 7 | 0 / 4 | 153 / 42 |
| 2026-10-27 | B | 3 / 10 | 3 / 8 | 1 / 9 | 1 / 7 | 139 / 56 |
| 2026-10-28 | B | 0 / 19 | 0 / 10 | 0 / 14 | 0 / 7 | 165 / 61 |
| 2026-10-29 | B | 1 / 18 | 1 / 6 | 1 / 11 | 1 / 3 | 167 / 48 |
| 2026-10-30 | B | 0 / 15 | 0 / 9 | 0 / 13 | 0 / 8 | 121 / 44 |
| 2026-10-31 | B | 3 / 21 | 3 / 10 | 2 / 16 | 2 / 10 | 174 / 67 |
| 2026-11-01 | B | 5 / 16 | 4 / 10 | 2 / 17 | 3 / 8 | 201 / 76 |
| 2026-11-02 | B | 2 / 8 | 2 / 6 | 1 / 3 | 1 / 3 | 138 / 56 |
| 2026-11-03 | B | 2 / 14 | 2 / 9 | 0 / 10 | 0 / 7 | 142 / 58 |
| 2026-11-04 | B | 2 / 16 | 2 / 12 | 0 / 14 | 0 / 12 | 179 / 66 |
| 2026-11-05 | B | 2 / 16 | 2 / 11 | 1 / 14 | 1 / 10 | 148 / 66 |
| 2026-11-06 | B | 4 / 20 | 3 / 10 | 2 / 18 | 2 / 9 | 164 / 64 |
| 2026-11-07 | B | 1 / 14 | 1 / 12 | 0 / 9 | 0 / 6 | 155 / 62 |
| 2026-11-08 | B | 1 / 10 | 1 / 8 | 0 / 8 | 0 / 6 | 165 / 49 |
| 2026-11-09 | B | 0 / 17 | 0 / 13 | 0 / 11 | 0 / 11 | 192 / 86 |
| 2026-11-10 | B | 1 / 19 | 1 / 10 | 1 / 13 | 1 / 6 | 168 / 75 |
| 2026-11-11 | B | 2 / 10 | 2 / 5 | 1 / 5 | 1 / 2 | 177 / 86 |
| 2026-11-12 | B | 2 / 19 | 2 / 11 | 0 / 17 | 0 / 9 | 198 / 89 |
| 2026-11-13 | B | 1 / 20 | 1 / 8 | 1 / 18 | 1 / 8 | 204 / 96 |
| 2026-11-14 | B | 3 / 18 | 3 / 10 | 1 / 17 | 1 / 10 | 201 / 81 |
| 2026-11-15 | B | 4 / 16 | 4 / 9 | 2 / 12 | 2 / 8 | 182 / 59 |
| **All 42 days** | | 87 / 586 | 84 / 336 | 33 / 491 | 33 / 301 | |
