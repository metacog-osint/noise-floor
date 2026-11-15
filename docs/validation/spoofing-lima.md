# Spoofing to Lima, Peru: does Noisefloor see the flights another tracker sees? (pre-registered 14 Nov 2026)

**Lane:** adsb-spoofing (validated; `docs/validation/spoofing.md`). **Detector:** `tools/spoof_day.py` v0.5, unchanged
in this test (no parameter changes until it is scored). **Comparison:** GPSWise (SkAI Data Services) public day files,
registry row `gpswise`: validation only. Its terms forbid storing or republishing its data, so this report gives counts
only and the comparison files stay outside the repo. **Tool:** `tools/spoof_compare.py`.

## Why

Public reporting from 11 Nov 2026 (The New York Times) describes GNSS receivers on airliners over Hungary, Slovakia,
Poland and Romania being shown on a ring of about 1 km radius around central Lima, Peru (about -12.04, -77.05), and a
second, smaller ring in north-west Romania (about 47.96, 23.28). GPSWise's public data shows 6–14 such flights a day on
7–12 Nov 2026. A downstream product wants a daily count of flights spoofed to one place, and where those aircraft
really were, from Noisefloor's published files. Before that is worth building, Noisefloor's detector has to see most
of these flights.

## What changed for this (14 Nov 2026)

`<day>.spoof.json` kept only the top 10 spoofed-to points. Lima was never in them. From this change each day also gets
`<day>.spoof-targets.json`: every spoofed-to cluster, with where its aircraft really were (schema below). The detector
itself is unchanged.

## Disclosure: what was looked at before this was written

On 14 Nov 2026, before writing the checks, the 12 Nov archive was downloaded and the 14 aircraft GPSWise shows at Lima
that day were looked at, trace by trace, with the frozen v0.5 detector:

- adsb.lol holds ADS-B positions near Lima for 3 of the 14. For most of the rest, the archive has only MLAT positions
  (where the aircraft really was, over Slovakia and Hungary) during GPSWise's window. The aircraft's own ground speed
  reads 108–110 kt there, so the receiver was spoofed, but its false positions didn't reach the archive.
- The 3 with Lima positions show 15–32 positions at 108–110 kt, over 30 s to 7 minutes. None was flagged: 109 kt is
  above the slow test's 100 kt, the two short ones are under loiter's 3 minutes, two of them jumped to Lima and back
  (two jumps over 2,000 km, so the duplicate-address rule switched the excursion test off), and the third first appears
  at Lima (a one-way jump, which the detector counts but doesn't use).
- Two of the 3 were shown on the Romanian ring seconds before Lima.

So the result for 12 Nov (0 of 14) is known, and a fail is the expected outcome overall. 7–11 Nov were not looked at.
The checks are registered anyway: the request was to measure the detector as it is, then propose a fix as a separate,
separately tested step, not to tune it to pass.

## Checks (pass marks fixed before scoring)

**Days:** 7–12 Nov 2026 (UTC). **GPSWise Lima flights:** features of GPSWise's day file whose "during" (spoofed-to)
point lies within 100 km of (-12.043, -77.050). **Match:** spoof_day has an episode for the same ICAO address whose
spoofed-to point (the median of its false positions) lies within 100 km of the same point, and whose time overlaps
GPSWise's "during" window widened by 30 minutes each side (the day before and after are searched too). Any episode
class counts.

| # | Check | Pass if |
|---|---|---|
| L1 | GPSWise Lima flights that Noisefloor also places at Lima, pooled over the 6 days | ≥ 50% |
| L2 | Days with at least one match | ≥ 4 of 6 |

50% because a daily count built on Noisefloor's files would undercount badly below that. GPSWise isn't ground truth
either: it is another tracker with its own detector and receivers (a GPSWise news post describes adding Wingbits receiver data), so matches
show agreement, not accuracy.

**Reported, not scored:**
- the same counts for 7–11 Nov alone (the days not looked at first);
- for each miss, the reason from the raw trace (`spoof_compare.py --raw-root`): aircraft not in the archive, no
  position near Lima in the window, only MLAT positions there, or ADS-B positions there that no test flagged (and which
  test let them through);
- aircraft Noisefloor places at Lima that GPSWise doesn't list;
- the Lima cluster in each day's `<day>.spoof-targets.json` (episodes, aircraft, spread), and any cluster within 10 km
  of the Romanian ring (47.959, 23.276).

## `<day>.spoof-targets.json` (schema 1)

On the `pnt-data-YYYY-MM` release beside `<day>.spoof.json`:
`https://github.com/metacog-osint/noise-floor/releases/download/pnt-data-YYYY-MM/YYYY-MM-DD.spoof-targets.json`.
ODbL 1.0, derived from adsb.lol; aggregates only, no ICAO addresses, types or callsigns. `<day>.spoof.json` keeps every
field it had and gains `targets_file`.

Top level: `day`, `version` (detector), `targets_version`, `licence`, `radius_km` (5), `episodes` (all of the day's
episodes), `clustered`, `left_out` (`replay`: stale-data episodes, not spoofing; `no_false_position`), `fields` (the
definitions below, in the file), `clusters`, `method`.

Each cluster, largest first:

| Field | Meaning |
|---|---|
| `lat`, `lon` | Centre: median of the episodes' spoofed-to points (each the median of that episode's false positions) |
| `r50_km`, `r90_km` | Median and 90th-percentile distance of those points from the centre |
| `episodes`, `aircraft` | Spoofing episodes, and distinct aircraft, shown here that day |
| `classes` | Episodes by class: active, post (post-exposure), isolated, unlocated (`spoofing.md` section 2) |
| `kinds` | Episodes with slow, loiter or excursion positions (one episode can have several) |
| `first`, `last` | Start of the first episode and end of the last, UTC |
| `alt_ft` | Lowest and highest baro altitude at the start of an episode |
| `clean` | Episodes whose false positions were mostly NACp 8 or better |
| `mlat_confirmed` | Episodes where MLAT put the aircraft 20 km or more from its ADS-B position |
| `located` | Episodes with a victim location |
| `victim_cells` | `[H3 res-4 cell, episodes, distinct aircraft]`: where the aircraft really were during these episodes (interpolated between trusted positions: good at res 2, rough at res 4) |

**Clustering** (`tools/spoof_summary.py`, `targets()`): densest first, each cluster takes every ungrouped spoofed-to
point within 5 km of its seed; ties break by time, then position, so the output doesn't depend on input order. Any point
on a ring of radius under 2.5 km is within 5 km of every other, so a ring of about 1 km (GPSWise's Lima points lie
0.6–1.9 km from the centre) is always one cluster (tested at 60 random places on the grid). Clusters are at most 10 km
across, so separate spoofing points more than about 5 km apart stay apart. A moving false track becomes one point per
episode (its median), so excursions scatter into many small clusters. Spoofed-to points are where receivers were shown,
not where a transmitter is.

## Result (scored 14 Nov 2026, about 23:30 UTC): both checks fail

| Day | GPSWise Lima flights | Matched | Noisefloor at Lima, not in GPSWise |
|---|---|---|---|
| 7 Nov | 9 | 0 | 1 |
| 8 Nov | 7 | 0 | 0 |
| 9 Nov | 6 | 0 | 0 |
| 10 Nov | 8 | 0 | 0 |
| 11 Nov | 12 | 0 | 0 |
| 12 Nov | 14 | 0 | 0 |
| **All** | **56** | **0 (0%)** | 1 |

L1: 0% against ≥ 50%, **fail**. L2: 0 of 6 days against ≥ 4, **fail**. 7–11 Nov alone (not looked at first): 0 of 42.

**Why the 56 were missed** (`spoof_compare.py --raw-root`):
- 37: no position near Lima in the archive during GPSWise's window. adsb.lol mostly has MLAT positions there, over
  Slovakia and Hungary, with the aircraft's own ground speed at about 109 kt. readsb seems to have dropped the false
  positions, so the archive can't place these aircraft at Lima.
- 14: ADS-B positions at Lima that no test flagged: 108–110 kt (above slow's 100 kt), mostly 30–90 s (under loiter's 3
  minutes), and a jump to Lima and back (two jumps over 2,000 km), so the duplicate-address rule switched the excursion
  test off. The archive's ceiling is therefore about 14 of 56 (25%), even with a perfect detector.
- 5: aircraft not in the archive, or no positions at all in the window.

**Caught:** one aircraft on 7 Nov (06:10–06:13 UTC, loiter, isolated) that GPSWise doesn't list. Its victim location
came from the last trusted position before the episode, which was on the Romanian ring: itself a spoofed position at
about 109 kt that no test flagged. So that episode's victim cell is wrong. **Romanian ring:** one cluster, on 9 Nov (1
episode, excursion, 1.1 km from 47.959, 23.276).

**Release files:** `<day>.spoof-targets.json` for 7–13 Nov 2026 was rebuilt on GitHub (backfill.yml `spoofing_only`)
and is on the `pnt-data-2026-11` release. The files for 7–12 Nov are the same size as the local rerun's (sizes compared, not hashes).

**Fix proposed, not made (a separate, pre-registered step):**
1. Slow test: flag ground speed under about 150 kt at or above 25,000 ft. No jet cruises that slowly; this spoofer
   shows 108–110 kt on both rings.
2. Duplicate-address rule: don't switch off the excursion test for a short far segment (≤ 15 min) bracketed by the
   main track. Duplicate addresses show long alternating tracks.
3. Both checked against the six control regions on the held-out days, at the H1 limit, before adoption. Fix 1 also stops
   the Romanian ring positions being used as victim anchors.
4. The 37 dropped by readsb can only be counted as spoofed, not placed: an MLAT check of reported speed against MLAT
   movement (109 kt reported while moving at about 450 kt).
