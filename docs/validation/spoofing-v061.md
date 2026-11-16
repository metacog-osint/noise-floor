# Spoofing detector v0.6.1: rule A for category A2 (pre-registered 15 Nov 2026)

**Why.** v0.6 (`spoofing-v06.md`) added rule A: a fast aircraft is also slow under 150 kt ground speed at or above
25,000 ft baro. Of the 33 control-box episodes that were new in v0.6 on the held-out days, 12 came from rule A on
emitter category A2 aircraft (King Air 200 and 350, PC-12, PA-46, Dornier 328, Brasília, one with no type): isolated
episodes over North America, Australia and central Europe, none with MLAT to check. Eleven began within 1,000 ft of
25,000 ft; one began at 28,375 ft. These are probably real flights, not spoofing. A turboprop cruises at about 250–310 kt
true airspeed, and a winter jet stream can take 120 kt or more off that. v0.6 named this as rule A's weak spot and left
the fix to a separate, pre-registered step: this one.

## Variants (frozen when this file is committed)

`tools/spoof_day.py --slow-hi-a2-ft N` sets rule A's floor for category A2 (default 25,000 ft, which is v0.6). Nothing
else changes: v0.5's slow test for A2 (under 100 kt at or above 18,000 ft), loiter, rules B and C, and rule A for
categories A3–A5 and for fast aircraft with no category all stay as in v0.6.

| Variant | Setting | Rule A for A2 |
|---|---|---|
| V1 | `--slow-hi-a2-ft 0` | Off: rule A applies to A3–A5 (and fast aircraft with no category) only |
| V2 | `--slow-hi-a2-ft 36000` | At or above 36,000 ft only |

V2's floor sits above the ceilings of the common A2 turboprops, so in practice only A2 jets (light and mid-size business
jets, some regional jets) are tested. Published maximum operating altitudes: King Air 350 35,000 ft, PC-12 30,000 ft
(manufacturer figures as quoted by [Precision Aviation Group](https://www.precisionaviationgroup.com/publications/king-air-350-specifications/)
and [Aviation Week](https://aviationweek.com/business-aviation/aircraft-overview/pilatus-pc-12); the AFMs were not
checked). The Dornier 328, Brasília and PA-46 turbine ceilings are about 30,000–32,000 ft (not re-checked here). Light
jets at 36,000 ft and above cruise at about 340 kt true airspeed or more, so 150 kt over the ground there needs a
headwind near 200 kt.

## Disclosure: what was looked at before this was written

Only v0.6's own review of its 33 new control-box episodes (type, category, class, start altitude, region; local list in
`data/spoofing_v06/new_controls.json`) and v0.6's published scores. No variant was run before this file was committed.
All 12 of the A2 episodes began below 36,000 ft, so both variants are expected to remove all 12: H7 below is an
implementation check. What this step measures is the cost, in the checks that can fail: H8, H1–H6 and the Lima loss.

## Checks (pass marks fixed before any v0.6.1 run)

**Held-out days:** the same 12 as v0.3–v0.6 (2024-02-20, 2024-06-20, 2024-10-20, 2025-02-20, 2025-06-20, 2025-10-20,
2026-02-20, 2026-06-20, 2025-04-10, 2025-04-20, 2025-05-10, 2025-05-20), scored by `tools/spoof_heldout.py` against the
v0.6 outputs of the same days (`data/spoofing_v06`, local). H1–H5 keep v0.6's pass marks; H6 now compares with v0.6.

| # | Check | v0.6 | Pass if |
|---|---|---|---|
| H1 | Controls: pooled active share of aircraft-hours in the six control regions | 0.0023% | ≤ 0.01% |
| H2 | Middle East and Baltic and western Russia: pooled active share | 0.397%, 0.904% | each ≥ 0.2% and ≥ 20× H1 |
| H3 | Episodes confirmed by MLAT, of those MLAT can test | 568 of 618 (91.9%) | ≥ 75% |
| H4 | Top res-6 spoofed-to cells per day with ≥ 5 aircraft within 25 km of a named published point | 22 of 67 (32.8%) | ≥ 25% |
| H5 | Eastern Mediterranean, named point with the most aircraft among the day's top cells | Beirut, Beirut, Amman | Beirut, Beirut, Amman |
| H6 | Episodes located in a control box, all classes, against v0.6 on the same days | 134 | ≤ 1.5× v0.6 (≤ 201) |
| H7 | Of the 12 A2 rule-A control-box episodes in v0.6's review, those still present (an episode of the same aircraft overlapping it in time, in a control box) | 12 | 0 |
| H8 | MLAT-confirmed episodes, all regions | 568 | ≥ 98% of v0.6 (≥ 557) |

H8 is the cost check: if rule A on A2 was finding real spoofing (business jets spoofed in the Middle East, for
example), MLAT-confirmed episodes fall. 98% allows at most 11 of v0.6's 568 to go.

**Lima, 7–12 Nov 2026** (`tools/spoof_compare.py`, same matching as `spoofing-v06.md`, against GPSWise's counts only).
Under v0.6: P1 12 of 14 placeable flights placed (86%), P2 47 of 56 counted (84%). P1 (≥ 75%) and P2 (≥ 60%) keep
their marks and, as in v0.6, don't gate adoption. Any flight that v0.6 placed or counted and the variant doesn't is
reported. The spoofer's 108–110 kt false positions at cruise are on airliners (A3), so no loss is expected.

**Also reported, not scored:** every control-box episode that changed against v0.6 (gone or new; the list holds ICAO
addresses and stays local); A2 episodes gone on the held-out days by class and region group, and how many MLAT could
test or confirmed; the same per day for 7–12 Nov.

**Adoption rule:** a variant can be adopted only if H1–H8 all pass. If both pass, V2 is adopted: it keeps rule A where
the physics holds (A2 jets at cruise). If only one passes, that one. If neither, v0.6 stays and the failures are
reported. Adoption sets the default of `--slow-hi-a2-ft` (detector version "0.6.1"; `--slow-hi-a2-ft 25000` gives
v0.6), through a pull request that Tom merges, and the affected published days (7 Nov to the last published day) are
redone with backfill.yml `spoofing_only` only on Tom's say.

**Runs:** each variant on the 12 held-out days and 7–12 Nov into `data/spoofing_v061a` (V1) and `data/spoofing_v061b`
(V2), local.

## Result (scored 15 Nov 2026): both variants pass every check; V2 adopted

**Held-out days** (`tools/spoof_heldout.py` against `data/spoofing_v06`; H7 and H8 from the variants' episode files
and summaries):

| # | Pass if | v0.6 | V1 (A2 off) | V2 (A2 at ≥ 36,000 ft) | Result |
|---|---|---|---|---|---|
| H1 | ≤ 0.01% | 0.0023% | 0.0023% of 15.2 million control aircraft-hours | 0.0023% | Both pass |
| H2 | each ≥ 0.2% and ≥ 20× H1 | 0.397%, 0.904% | 0.397% (173×), 0.904% (394×) | 0.397% (173×), 0.904% (394×) | Both pass |
| H3 | ≥ 75% | 568 of 618 (91.9%) | 568 of 618 (91.9%) | 568 of 618 (91.9%) | Both pass |
| H4 | ≥ 25% | 22 of 67 (32.8%) | 22 of 67 (32.8%) | 22 of 67 (32.8%) | Both pass |
| H5 | Beirut, Beirut, Amman | Beirut, Beirut, Amman | Beirut 1 km (49 aircraft), Beirut 1 km (441), Amman 3 km (252) | same | Both pass |
| H6 | ≤ 201 | 134 | 122 (0.91×) | 122 (0.91×) | Both pass |
| H7 | 0 of 12 | 12 | 0 | 0 | Both pass |
| H8 | ≥ 557 | 568 | 568 | 568 | Both pass |

Neither variant adds an episode anywhere; each only removes rule-A episodes of category A2.

| Held-out days, all regions | V1 | V2 |
|---|---|---|
| Episodes (v0.6: 5,837) | 5,814 (23 gone) | 5,818 (19 gone) |
| Gone, by class | 20 isolated, 2 active, 1 unlocated | 19 isolated |
| Gone, by region group | 12 controls (the 12 reviewed), 1 Middle East, 1 Baltic and western Russia, 9 outside every region | 12 controls (the 12 reviewed), 7 outside every region |
| Gone that MLAT could test | 0 | 0 |
| Start altitude of those gone | 25,000–50,000 ft | 25,000–34,975 ft |

The 4 that V1 removes and V2 keeps are all business jets at 38,000–50,000 ft: a Falcon 8X (unlocated) and a Legacy 600/650
(active, with 5 other aircraft) over the Jordan Valley on 20 Jun 2025, a PC-24 (active, 4 others) over central Poland
on 10 Apr 2025, and an isolated Citation III/VI near Memphis at 50,000 ft on 20 Feb 2026. The two active ones sit in spoofed
areas beside other spoofed aircraft. V2's 19 are all turboprops (King Air, PC-12, PA-46, Dornier 328, Brasília) plus
one Beechjet 400 and one with no type, all below 35,000 ft.

**7–12 Nov 2026** (not scored, reported):

| Day | v0.6 episodes | V1 gone | V2 gone | MLAT-confirmed, v0.6 / V1 / V2 |
|---|---|---|---|---|
| 7 Nov | 623 | 2 (1 active, 1 isolated) | 1 (isolated) | 92 / 92 / 92 |
| 8 Nov | 533 | 3 (1 active, 2 isolated) | 2 (isolated) | 117 / 117 / 117 |
| 9 Nov | 496 | 0 | 0 | 70 / 70 / 70 |
| 10 Nov | 467 | 1 (isolated) | 1 (isolated) | 51 / 51 / 51 |
| 11 Nov | 425 | 4 (3 isolated, 1 unlocated) | 2 (isolated) | 53 / 53 / 53 |
| 12 Nov | 489 | 2 (isolated) | 1 (isolated) | 80 / 80 / 80 |
| **All** | **3,033** | **12** (4 in control boxes, 2 western Black Sea, 1 Baltic, 5 outside every region) | **7** (3 in control boxes, 4 outside every region) | **463 / 463 / 463** |

V1 alone removes two active episodes over the western Black Sea at 40,000 ft (a Falcon 8X with 13 other aircraft on
7 Nov, and an untyped aircraft with 8 others on 8 Nov), a Falcon 7X at 45,000 ft with its false position there, and two
isolated ones. V2's 7 are a Dash 8-100, a King Air 350, a PC-12, one with no type, and three whose type codes read U2,
BALL (balloon) and B505 under category A2 (type codes as in the archive, not checked), all at 25,000–26,825 ft.

**Lima, 7–12 Nov 2026** (`spoof_compare.py --raw-root --v06`, compared per flight with v0.6's output):

| Day | GPSWise Lima flights | Placeable | Placed at Lima (v0.6 / V1 / V2) | Counted (v0.6 / V1 / V2) | Noisefloor at Lima, not in GPSWise |
|---|---|---|---|---|---|
| 7 Nov | 9 | 3 | 3 / 3 / 3 | 8 / 8 / 8 | 1 |
| 8 Nov | 7 | 2 | 1 / 1 / 1 | 7 / 7 / 7 | 2 |
| 9 Nov | 6 | 0 | 0 / 0 / 0 | 4 / 4 / 4 | 1 |
| 10 Nov | 8 | 1 | 1 / 1 / 1 | 6 / 6 / 6 | 0 |
| 11 Nov | 12 | 5 | 4 / 4 / 4 | 11 / 11 / 11 | 4 |
| 12 Nov | 14 | 3 | 4 / 4 / 4 | 11 / 11 / 11 | 4 |
| **All** | **56** | **14** | **13 / 13 / 13** (12 of the 14 placeable) | **47 / 47 / 47 (84%)** | 12 |

P1 12 of 14 (86%) and P2 47 of 56 (84%) for both variants, as under v0.6. No flight that v0.6 placed or counted is lost:
all 56 flights have the same placed, counted and placeable values under each variant.

**What stays:** V2 keeps rule A for A2 aircraft at or above 36,000 ft whatever their reported altitude, so an isolated
A2 episode at a reported 69,200 ft over north-eastern Germany on 11 Nov (an altitude no A2 aircraft flies, so probably a
bad altitude report rather than spoofing) remains, as it did under v0.6. It is in no control box and doesn't affect any
check.

**Adopted:** both variants pass H1–H8, so under the rule above V2 is adopted: `SLOW_HI_A2_FT` defaults to 36,000 ft
(detector version "0.6.1"; `--slow-hi-a2-ft 25000` gives v0.6). It keeps rule A where the physics holds (A2 jets at
cruise) and, unlike V1, keeps the active A2 jet episodes in the Jordan Valley, Poland and the western Black Sea. The
published days from 7 Nov are redone with backfill.yml `spoofing_only` only on Tom's say.
