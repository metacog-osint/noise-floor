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
