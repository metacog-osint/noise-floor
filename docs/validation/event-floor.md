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

## Results

Not yet run.
