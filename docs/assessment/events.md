# Events and grading (v0.2)

**Date:** 24 Oct 2026 (v0.1: 23 Oct) · **Status:** working version, built overnight and not yet reviewed by a person · **Code:** `tools/events.py` · **Tests:** `tests/test_events.py` · **Register:** `data/events/register.sqlite` (gitignored)

## Bottom line

Every input item becomes an **observation**. Observations on the same UTC day fuse into **events**. Each event is graded on five independent fields, and every grade is stored with the rule that set it and the observations behind it.

The run covers 385 days (1 Oct 2025 – 22 Oct 2026, UTC): 94,651 observations fused into 52,260 events.

- **A second independent sensor family now feeds the lane.** CYGNSS noise-floor cells (`docs/validation/cygnss.md`) exist for six days.
  - On those days, 98 events reach "Multiple sources": ADS-B 93 m loss and a raised CYGNSS noise floor agree in place on the same day.
  - The rule is stricter than "both families in one event", because a single raised CYGNSS cell within 300 km is common by chance (see the chance rates below).
  - No such event sits in a quiet control area, and none rests on a CYGNSS cell with fewer than 20 DDMs.
- **Announced FAA GPS tests come out `planned`** when every effect in the event falls inside a test window and radius. 886 effect events qualify, and the rule reproduces all 1,283 test tags on the public map's event files.
- **Storm days get NATURAL events.** 10 m-only effects at storm time, poleward of a latitude gate or inside a storm-flagged SBAS area, come out `benign_natural`. Worse-than-93 m effects on storm days stay `open` and are never called deliberate.
- **The persistent hotspots are EFFECT · open on almost every day.** They are single-source except where CYGNSS covers them on its six days. The Baltic is out of CYGNSS reach.

**What this version can't do yet:**

- `deliberate_suspected` needs an interference warning that isn't a planned test. No such input is wired in.
- No localization method feeds the lane, so `localization_error_km` is null everywhere.
- CYGNSS exists for six days only, and it agrees with ADS-B in time only to the day.

## The model

The model is the event model and five-field grading adopted in the merged plan (`docs/DESIGN.md`, "Merged plan"). The five fields are independent. They are not a ladder: a `planned` verdict isn't "above" `open`, and a localized event can still be single-source.

| Field | Values | Meaning |
|---|---|---|
| `signal_type` | EFFECT · WARNING · NATURAL | Something measurably degraded · an official notice · a space-weather alert to rule out first |
| `support` | Single-source, unverified · Partially corroborated · Multiple sources | SOP terms. "Multiple sources" needs two or more **independent** sensors agreeing in time and space |
| `localization_error_km` | null or km | Null until a fix exists |
| `attribution_status` | none · candidate · attributed | "Attributed" also needs no surviving benign explanation |
| `verdict` | open · benign_natural · planned · deliberate_suspected | The result of the exclusion checks |

**Grades describe evidence strength. They never name perpetrators.** An EFFECT is never called jamming without a WARNING-level or operator/government corroborant. Support is not a verdict: two sensors agreeing makes an event better supported, not deliberate.

## Observations

| Kind | Signal | Family | What it is | Time resolution | Input |
|---|---|---|---|---|---|
| `adsb_anomaly` | EFFECT | adsb | An anomaly event from `pipeline/pnt_analysis.py`: region-hours above their own 14-day baseline, on the 93 m (gross) or 10 m (capable) measure | hour | The site's daily event file (`site/data/events/<day>.json`, committed or fetched from the live site) |
| `adsb_burst` | EFFECT | adsb | A minute-level burst event (aircraft with a gross-bad report above the region's level) | minute | same |
| `adsb_level` | EFFECT | adsb | **Level check:** an H3 res-2 region with 3 or more res-4 hexes at the map's jamming scale for the day (5 or more aircraft, hex score of 10 or more) | day | per-hex daily table (`<day>.parquet` from the data releases) |
| `adsb_sbas` | EFFECT | adsb | An SBAS service flag run: an area-wide 10 m loss in an SBAS service area | hour | `site/data/events/<day>.json` |
| `cygnss_noise` | EFFECT | cygnss | **New in v0.2:** an H3 res-3 cell with 20 or more DDMs and a median noise-floor excess of 1 dB or more. Both thresholds were fixed by the CYGNSS lane before its validation | day | `data/cygnss/grid/<day>.r3.parquet` (`tools/cygnss_rfi.py`) |
| `cygnss_dropout` | EFFECT | cygnss | **New in v0.2:** a res-3 cell where half or more of the expected samples are missing (by sub-satellite point) | day | same |
| `faa_test` | WARNING | faa | An announced GPS test from an FAA SPANS flight advisory: one observation per test per UTC day, with that day's windows | minute | `data/declared/faa_gps_tests.json` |
| `kp_storm` | NATURAL | gfz_kp | A run of 3-hour GFZ Kp intervals of 5 or more (NOAA G1 or stronger) touching the day | 3 hours | GFZ Kp |

**Why the level check.** The anomaly and burst checks compare each region with its own recent past, so interference that is there every day sets its own baseline and drops out. The level check doesn't use a baseline. It uses the same hex score and thresholds as the public map: 100 × max(bad − 1, 0) / aircraft, live counts, 5 or more aircraft.

**Independence.**

- **adsb:** all four ADS-B kinds come from one aggregator (adsb.lol) through one processor. They are one sensor family, however many measures agree.
- **cygnss:** an independent sensor family. It measures RF power arriving at a receiver in orbit, from a different instrument, platform and operator.
- **faa:** advisories are declared notices, not sensors.
- **gfz_kp:** a context index used by the exclusion checks. It never counts toward support.
- **CYGNSS dropouts** are recorded but never count toward support. They are placed by the spacecraft's position, not the antenna beam, and their cause is unconfirmed (the lane's most likely explanation is the spacecraft losing its own GPS fix). Dropout cells can also hold fewer than 20 DDMs.

## Fusion rule

Events are bounded by the UTC day, because every input is processed per UTC day. Sensor observations fuse; notices attach.

1. **Cell-located observations** (anomalies, bursts, level regions):
   - Two observations link when a cell of one is the same as, or adjacent to, a cell of the other (H3 grid distance ≤ 1 at resolution 2).
   - Their time spans must also overlap or be at most 60 minutes apart. For hourly observations that means overlapping or adjacent hours.
2. **CYGNSS noise cells link by distance, not adjacency.**
   - A raised cell links to another located observation when its centre lies within **300 km** of that observation's centroid or one of its res-2 cell centres, on the same UTC day.
   - **Why distance:** CYGNSS location error comes from the antenna beam, which is a few hundred km wide on the ground, not from the grid. Res-2 adjacency reaches anywhere from 0 to about 500 km depending on where two points fall in their cells. A fixed distance states the tolerance directly and the same way everywhere.
   - **Why 300 km:** about half a beam plus a res-3 cell. That is tighter than the ADS-B footprint of a ground emitter (about 440 km at FL350), so the rule errs toward not linking.
   - The CYGNSS grid is daily, so agreement in time is only "the same UTC day".
3. **CYGNSS dropouts** fuse only with other dropouts (centres within 300 km), never with other kinds. Their position is the spacecraft's, and the source can be anywhere in view of it.
4. **Distance cap.** Links are taken closest first. Two groups merge only if every pair of member centroids stays within **600 km**.
   - Without the cap, whole-day level regions chain across adjacent cells. On 10 Mar 2026 that fused the Baltic, the Black Sea and the eastern Mediterranean into a single 51-region event.
   - 600 km is a little over the radio horizon from a ground emitter to an aircraft at FL350 (about 440 km). It is a clustering guard, not a physical limit.
   - It was set after looking at one case, 22 Sep 2026, where 900 km merged the Bay Area bursts with bursts about 630 km away. Treat it as tunable (`build --max-km`).
5. **SBAS runs** link when they are in the same service area and at most 60 minutes apart. They never fuse with located observations, because they describe a whole service area.
6. **Announced tests** never fuse anything. Each test attaches to every event that holds a located EFFECT observation consistent with it (see rule P1). With none, the test becomes its own WARNING event.
7. **Kp storms** are planetary, not local, so they are never linked. Each run is its own NATURAL event and enters other events only through the space-weather check, where it is recorded as context.

**Episodes (persistence).** An episode is a run of days on which one res-2 region is at jamming scale all day (it has a level observation). One missing day is allowed, which covers flicker at the threshold and a day missing or partial at the source.

- Each event with a level observation takes the episode of its longest-running region so far. `episode_index` is how many level days the run has reached on the event's day.
- Episodes are kept per region on purpose. Linking whole events from day to day chained continents together, because 10 m anomalies turn up somewhere nearby on most days. Linking only jamming-scale events, with the 600 km cap, broke the obvious long-running hotspots into short pieces.

## Grading rules

Each grade is stored as (value, rule, reason, basis observations). `python tools/events.py show --event <id>` prints them all.

| Field | Rule | Condition | Value |
|---|---|---|---|
| signal_type | T1 | Any EFFECT observation | EFFECT |
| | T2 | No EFFECT, a WARNING observation | WARNING |
| | T3 | NATURAL observations only | NATURAL |
| support | S3 | A pair of counting observations from two independent sensor families **agrees**: they link directly (not through a chain of other members), and for ADS-B with CYGNSS the extra conditions below hold | Multiple sources |
| | S2 | No agreeing pair; sensor evidence plus an independent notice consistent with it in time and place (an attached announced test) | Partially corroborated |
| | S1 | Anything else: any number of ADS-B measures, CYGNSS alone, both families without an agreeing pair, dropouts only, or a lone notice | Single-source, unverified |
| localization_error_km | L0 | No localization method feeds the lane yet | null |
| attribution_status | A1 | Verdict `planned` by rule P1: the candidate is the announced test, named by its FAA identifier | candidate |
| | A0 | Otherwise | none |
| | (A2) | Would need a fix, a candidate and no surviving benign explanation. Never applies in v0.2 | attributed |
| verdict | P1 | Every located EFFECT observation lies inside an announced test window **and** within its widest published radius (the FL400 one), measured from the observation's centroid | planned |
| | P2 | The event is an announced test with no effect matched to it | planned |
| | N0 | The event is a Kp storm run | benign_natural |
| | N1 | SBAS-only event with every flagged hour within 3 h of Kp ≥ 5; **or** a 10 m-only located event inside an SBAS area flagged at storm time in the same or an adjacent hour | benign_natural |
| | N2 | A 10 m-only located event during Kp ≥ 5 (within 3 h), poleward of a geomagnetic-latitude gate: \|mlat\| ≥ 50° for Kp 5–6.x, ≥ 40° for Kp 7–7.x, any latitude for Kp ≥ 8 | benign_natural |
| | D1 | An EFFECT corroborated by an interference warning that isn't a planned test, with the natural and planned checks failing. **No input feeds this yet** | deliberate_suspected |
| | V0 | Otherwise | open |

**S3 for ADS-B with CYGNSS.** All three conditions must hold:

1. The ADS-B observation is on the **93 m measure**: a 93 m anomaly, a burst or a level region. That is the measure the CYGNSS lane was validated against (AUC 0.98 against aircraft-jammed cells).
2. A raised CYGNSS cell links to it (within 300 km, same day).
3. The **CYGNSS field around it is raised**: the median excess of all judged cells (20 or more DDMs) within 300 km of the ADS-B observation is at least 1 dB.

Conditions 1 and 3 come from the chance rates below:

- 10 m observations meet the simpler "any raised cell within 300 km" test exactly as often as random land points do.
- One raised cell in an otherwise quiet neighbourhood is common.

**Precedence.** P1 outranks N1/N2: a notice matched in time and place is more specific than a storm-time heuristic. Both checks are still recorded.

**Basis for the NATURAL rules.**

- Storms degrade GNSS accuracy to tens of metres, rarely past 93 m. In the Phase 1.1 storm tests (`docs/validation/phase1.md`, verdicts 9–10), the G2 storm of 18 Oct 2025 and the G4 storm of 12 Nov 2025 moved the 10 m share in the North American northern tier (12.4% and 38.5%) but left the gross share flat (on 12 Nov, 0.03% against a 0.04% baseline). So only 10 m-only effects can be excused by a storm.
- The SBAS storm label uses Kp ≥ 5 within ±3 h, as `pnt_analysis.py` does (verdict 16).
- The latitude gate in N2 is a **heuristic, not validated**:
  - Geomagnetic latitude comes from a centred dipole (pole near 80.8°N, 72.7°W), good to a few degrees.
  - The 50°/40°/any steps follow the equatorward spread of storm effects with Kp. The G4 storm of 12 Nov 2025 flagged the Japanese and Korean SBAS areas, at roughly 21–38° geomagnetic on this dipole.
  - The rule has been checked against only those two storms.
- The Kp rules don't apply to CYGNSS evidence. The noise floor measures RF power, not position accuracy.

**Exclusion checks recorded on every EFFECT event:**

| Check | Results |
|---|---|
| `space_weather` | benign_natural (N1/N2) · storm_partial (storm present, but the event has 93 m loss or CYGNSS evidence, is outside the gate, or is an SBAS flag only partly at storm time) · not_indicated · not_applicable (CYGNSS evidence only) · unknown (no Kp) |
| `planned_test` | planned (P1) · partial (some effects consistent) · not_indicated |
| `receiver_fault` | screened_upstream: the processor drops avionics suspects (peer test) and post-exposure aircraft before anything is counted (`docs/method-card.md`, steps 3–4) |
| `sbas_service` | probable (SBAS flag at quiet Kp: probable service problem) · likely_benign (GAGAN or SouthPAN, where most aircraft don't use the service and the flag fires on most days) |

An `open` event also carries a hint when a benign explanation is plausible but no verdict value fits it: `sbas_service`, `sbas_equipage`, `storm_partial` or `test_partial`.

## Results: 1 Oct 2025 – 22 Oct 2026

The register was built on 23–24 Oct 2026 from:

- the public daily event files;
- the per-hex daily tables in the data releases;
- the CYGNSS grids for six days;
- the FAA advisory file (updated 22 Oct 2026);
- GFZ Kp (definitive to 30 Sep 2026, preliminary after).

A full build takes about 4 minutes on this PC.

**Observations:**

| Kind | Count |
|---|---|
| Anomaly events | 56,902 |
| Burst events | 11,310 |
| Level regions (region-days) | 10,421 |
| SBAS flag runs | 984 |
| CYGNSS raised cells (six days) | 13,087 |
| CYGNSS dropout cells (six days) | 526 |
| Announced test-days | 1,347 |
| Kp storm runs | 74 |

**Grades, all 52,260 events:**

| Field | Distribution |
|---|---|
| signal_type | EFFECT 51,453 · WARNING 733 · NATURAL 74 |
| support | Single-source, unverified 51,199 · Partially corroborated 963 · Multiple sources 98 |
| localization_error_km | null 52,260 |
| attribution_status | none 51,374 · candidate 886 · attributed 0 |
| verdict | open 49,651 · benign_natural 990 · planned 1,619 · deliberate_suspected 0 |

**EFFECT events by measure:**

| Measure | open | benign_natural | planned |
|---|---|---|---|
| 93 m only (gross) | 18,692 | 0 | 132 |
| both | 5,026 | 0 | 104 |
| 10 m only (capable) | 24,299 | 916 | 650 |
| CYGNSS noise only | 1,554 | 0 | 0 |
| CYGNSS dropouts only | 80 | 0 | 0 |

**Open events with a benign hint:** `storm_partial` 3,348 · `sbas_equipage` 643 · `sbas_service` 102 · `test_partial` 66. The other 45,492 open events have no hint.

**benign_natural by rule:** N2 820, N1 96, N0 74 (the NATURAL events themselves).

**By month (UTC).** CYGNSS days fall in January, February, May and October.

| Month | Events | EFFECT | WARNING | NATURAL | open | benign_natural | planned | Partially corroborated | Multiple sources |
|---|---|---|---|---|---|---|---|---|---|
| 2025-10 | 2,869 | 2,788 | 70 | 11 | 2,686 | 68 | 115 | 54 | 0 |
| 2025-11 | 4,129 | 4,063 | 59 | 7 | 3,907 | 110 | 112 | 59 | 0 |
| 2025-12 | 4,317 | 4,287 | 25 | 5 | 4,210 | 67 | 40 | 19 | 0 |
| 2026-01 | 4,615 | 4,543 | 62 | 10 | 4,317 | 204 | 94 | 36 | 13 |
| 2026-02 | 4,049 | 4,000 | 44 | 5 | 3,874 | 60 | 115 | 78 | 12 |
| 2026-03 | 4,045 | 3,961 | 74 | 10 | 3,722 | 147 | 176 | 113 | 0 |
| 2026-04 | 3,638 | 3,567 | 64 | 7 | 3,357 | 92 | 189 | 133 | 0 |
| 2026-05 | 4,330 | 4,267 | 59 | 4 | 4,163 | 45 | 122 | 67 | 53 |
| 2026-06 | 3,689 | 3,651 | 35 | 3 | 3,561 | 21 | 107 | 77 | 0 |
| 2026-07 | 4,221 | 4,167 | 51 | 3 | 4,060 | 47 | 114 | 67 | 0 |
| 2026-08 | 4,434 | 4,361 | 69 | 4 | 4,218 | 49 | 167 | 102 | 0 |
| 2026-09 | 4,505 | 4,434 | 70 | 1 | 4,319 | 19 | 167 | 102 | 0 |
| 2026-10 (to 22nd) | 3,419 | 3,364 | 51 | 4 | 3,257 | 61 | 101 | 56 | 20 |

`deliberate_suspected` is 0 in every month.

### The second sensor family: CYGNSS on six days

**Multiple sources:** 98 events.

| Day (UTC) | 2 Jan | 24 Feb | 9 May | 10 May | 16 May | 19 Oct |
|---|---|---|---|---|---|---|
| Events at "Multiple sources" | 13 | 12 | 15 | 19 | 19 | 20 |

- Every one rests on ADS-B 93 m evidence: a 93 m anomaly in 84, a level region in 26, a burst in 17 (an event can hold more than one).
- All 98 are `open`. Support isn't a verdict.
- Of the 195 events with 93 m loss inside the CYGNSS band (±38°) on those days, 98 reach "Multiple sources".
- 76 events hold both families without an agreeing pair, and stay "Single-source, unverified" with that reason.
- **Strength varies a lot.** On the ADS-B side, 41 rest on a notable or major 93 m anomaly, a burst or a level region, and 57 on minor 93 m anomalies only (under 10 points of excess). On the CYGNSS side, 67 have a field median of 1.5 dB or more and 31 sit between 1 and 1.5 dB.
  - 38 events are strong on both sides.
  - 28 are thin on both: minor ADS-B and a field of 1–1.5 dB. One example is a +5.9-point anomaly over the Yellow Sea next to cells at +1.05 to +1.28 dB.
  - Read the basis before leaning on any single one.
- 20 events are "Partially corroborated" on those days.

**Where** (event centroids, aggregated):

| Area | Events |
|---|---|
| Gulf, Arabian Peninsula, Red Sea and Egypt (10 inside the CYGNSS lane's Persian Gulf box) | 24 |
| Eastern Mediterranean and Levant | 21 |
| East Asia: Korea, Japan, eastern and southern China, Okinawa | 22 |
| Myanmar, the Andaman Sea and Yunnan | 17 |
| South Asia and the Arabian Sea | 14 |

- The East Asian events need a second look. The CYGNSS lane reads 1–1.5 dB there on most days with clean aircraft cells. Interference reports there are unverified for these days.

**Sanity checks:**

- The smallest DDM count among the CYGNSS cells behind any "Multiple sources" grade is 20. No grade rests on a dropout cell.
- **Quiet controls:** the CYGNSS lane's five control boxes (central Pacific, South Atlantic, Brazil, Australia and southern Africa interiors) produced no "Multiple sources" event, and no such event has any member inside them.
  - The controls did hold 98 raised CYGNSS cells over the six days (47 central Pacific, 50 Australian interior, 1 southern Africa). With no ADS-B effect beside them, they are CYGNSS-only, single-source events.
- **Persistent hotspots with CYGNSS:** 26 of the 4,197 events that hold a level region reach "Multiple sources". 6 are in the eastern Mediterranean and Levant, 10 in the Iraq–Iran–Gulf area and 10 elsewhere in the band. The Baltic and Black Sea hotspots stay single-source: CYGNSS doesn't reach them.

**Chance rates.** How often would the test fire for points with no particular link to CYGNSS? Pooled over the six days, within 300 km:

| Points | Any raised CYGNSS cell | Median of judged cells ≥ 1 dB |
|---|---|---|
| ADS-B 93 m observations in the band (386) | 81% | 64% |
| ADS-B 10 m observations in the band (243) | 40% | 24% |
| Random land cells in the band (2,400) | 40% | 22% |
| Random cells, land and sea (2,400) | 26% | 8% |

- 10 m observations sit at the random-land rate, so they are left out of S3.
- For 93 m observations, the field-median condition separates better than "any raised cell" (64% against 22%, not 81% against 40%).
- The random-land rate includes the real interference regions, so it overstates pure coincidence. Even so, it shows that the CYGNSS condition alone is not strong evidence; the ADS-B side has to carry its own weight.

**A side lead, unverified.**

- On 9–10 May, raised CYGNSS cells (+1.0 to +2.4 dB) sat over southern New Mexico and West Texas. On 10 May they fused with a 10 m anomaly in south-western Kansas. That anomaly was `planned` before CYGNSS joined, so one planned event became partial (887 → 886).
- The only announced test in reach is Pinon Canyon, CO, 440–650 km from those cells.
- The cells sit at the northern edge of the CYGNSS lane's own "northern Mexico, 9–10 May" lead. No White Sands test is announced for those days in the FAA file.

### Known-case checks

**1. Announced tests come out `planned`.**

- Of 1,347 announced test-days, 614 matched an effect. The other 733 are WARNING events (planned, rule P2) with no effect seen.
- 886 effect events are `planned` by rule P1. Each carries its test as the `candidate` and is graded "Partially corroborated".
- Cross-check against the map's own test tags (`tools/site_days.py`): every one of the 1,283 tagged anomalies and bursts is matched.
  - The rule also matches 80 more. All of them are on the 20 validated days, whose committed event files carry no test tags, because tagging happens at deploy.
- Most planned effect events are at White Sands Missile Range (252), Fort Polk (93, under two spellings) and Fort Irwin (47).

**22 Sep 2026, the validated Bay Area case** (Phase 1.2):

- The 18:00–18:08Z burst is `open`. It came before the Point Mugu Sea Range test window.
- The 19:52–20:12Z burst is `planned`, with candidate PMSRCA GPS 26-03 REV 2 (window 18:30–20:29Z, 294 km from the test centre). That is what the validation found.
- The same day shows the generous-radius limit. Bursts around Phoenix (15:46–19:23Z) are partly consistent with the same notice, because its widest radius is 1,226 km. They stay `open` with a `test_partial` hint.

**2. Storm days get NATURAL events and are never called deliberate.**

- Kp ≥ 5 runs gave 74 NATURAL events. Kp reached 7 or more on 9 days: 12–13 Nov 2025, 19–21 Jan 2026, 21–22 Mar 2026, 4 Jul 2026 and 10 Oct 2026. (The 10–11 Oct 2024 storm is outside the data range.)
- On those 9 days:
  - 10 m-only events: 255 `benign_natural`, 346 `open`, 9 `planned`.
  - Events with 93 m loss: 609 `open`, 4 `planned`, none `benign_natural`.
  - None is `deliberate_suspected`, and none is anywhere in the register.
- On 12 Nov 2025 (Kp 8.7), the SBAS flags over Canada, Japan and Korea are all `benign_natural` by rule N1, as in validation verdict 16.
- The 346 10 m-only events that stay `open` on those days:
  - 178 are more than 3 h from any Kp ≥ 5 interval.
  - 165 are equatorward of the latitude gate (hint `storm_partial`).
  - 3 are SBAS flags only partly at storm time.

**3. Persistent hotspots are EFFECT · open.**

- Level observations exist on 383 of 385 days.
- Of the 4,197 events holding one, 4,171 are EFFECT · Single-source, unverified · no fix · none · open. The other 26 are the CYGNSS-day events above, at "Multiple sources".
- That is the correct grade for ADS-B alone, under the rule that an effect isn't called jamming without a warning-level corroborant.
- 14 res-2 regions are at jamming scale on 300 or more days.
- The five longest episodes run the whole range (380–383 days). They are in or next to the hotspots Phase 1 verdict 1 names (Kaliningrad, the western and southern Black Sea coasts, the Estonia–Russia border), plus the Gulf of Riga.
- Episode lengths, across 150 regions:

| Length | Episodes |
|---|---|
| 1 day | 667 |
| 2–6 days | 486 |
| 7–29 days | 163 |
| 30–89 days | 47 |
| 90 days or more | 15 |

## Limits

- **Two sensor families, and only six days of the second.**
  - "Multiple sources" exists only on the CYGNSS days, and only inside about ±38° latitude. The Baltic, Black Sea, Caucasus and Kaliningrad can't get it from CYGNSS.
  - The code is general. Any lane that writes located observations with its own family can pair with ADS-B under rule S3. NISAR or Sentinel-1 RFI would need their own agreement conditions, as CYGNSS got.
- **CYGNSS agreement is coarse:**
  - **Time:** to the day only. The grid holds a handful of passes; the ADS-B observation may be hours away from them.
  - **Place:** to the beam. The noise enters through a beam a few hundred km wide plus sidelobes, so one strong emitter raises a region. "Multiple sources" here means both sensors were exposed in the same area on the same day, not that the same transmitter was measured twice.
  - **Chance:** the field condition fires for about 22% of random land points in the band (an upper bound that includes the real interference regions).
  - **Validation:** the CYGNSS validation rests on four regions and six days. Nothing here is a region-held-out test.
- **No interference warnings yet.**
  - NGA broadcast warnings, NOTAMs and similar notices would be WARNING observations of a different kind from planned tests. Without them `deliberate_suspected` can't be set.
  - That is deliberate. "Multiple sources" raises support, not the verdict.
- **The 10 m measure dominates the count.** Most events are 10 m-only departures from baseline. Those are weak signals: SBAS use, equipage and the ionosphere all move them. Filter on `effect_measure` (gross, both, capable, rf, dropout) when reading the register.
- **Announced-test radii are generous.** P1 uses the widest published radius (FL400), as the map's test tags do. For some ranges that is over 1,000 km (White Sands and Point Mugu notices reach about 1,200 km), so `planned` can cover effects far from the range. A tighter radius (for example the 10,000 ft one) is a design choice still open.
- **Equatorial scintillation isn't handled.** Post-sunset scintillation at low latitudes happens at any Kp. Ingesting the ionospheric nowcast archive (context lane) is the next step for the NATURAL check.
- **SBAS service problems have no verdict value.** They stay `open` with a hint. The plan's verdict list has nothing for a benign, non-natural system fault.
- **Day-bounded events.** An event that runs across midnight UTC appears as two events. Level and CYGNSS observations have day resolution, so they link to anything nearby that day.
- **Event IDs depend on the inputs.** An event ID is a hash of its member observations, so it stays the same across rebuilds as long as the inputs don't change. If an input day is reprocessed, or a CYGNSS grid is added, its event IDs change.
- **Inherited limits.** Everything in `docs/method-card.md` "What it can't tell you" and in `docs/validation/cygnss.md` "Limits" still applies: strong jamming removes aircraft, coverage depends on volunteer feeders, spoofing can look clean, and CYGNSS censors the strongest interference through dropouts.
- **No person has reviewed these grades yet.** Spot checks are above; the rules haven't been tested against held-out cases.

## Reproduce

```
python tools/events.py fetch                 # public inputs not on disk: the site's daily event files (~10 MB) and GFZ Kp
python tools/cygnss_rfi.py grid <day>        # optional: CYGNSS grids (data/cygnss/grid/<day>.r3.parquet), read when present
python tools/events.py build --all           # or --days 2026-03-01..2026-03-31
python tools/events.py stats
python tools/events.py show --day 2026-05-10 --full
python tools/events.py show --event EV-...
python tests/test_events.py
```

The register is SQLite (WAL mode). Tables:

- `observations`, `events`, `event_observations` (role `member` or `context`), `grades` (value, rule, reason, basis per field), `exclusions`, `episodes`.
- `day_inputs`: which input files fed each day.
- `meta`: build time and every parameter.

ADS-B observations on CYGNSS days carry the local CYGNSS field median and cell count (`cyg_local_med`, `cyg_local_n`) in their details. The register stays in `data/` (gitignored). The event files it reads are already public; the register itself is a working store, not a publication.

## Sources and licences

- adsb.lol daily archive (ODbL 1.0), through the PNT processor. Derived data is published under ODbL with attribution.
- NASA CYGNSS Level 1 Science Data Record V3.2 (PO.DAAC; NASA open data, which ESDIS treats as CC0; registry id `cygnss-l1`), through `tools/cygnss_rfi.py`.
- FAA SPANS flight advisories (US government, public domain).
- GFZ Potsdam Kp index (CC BY 4.0), `kp.gfz.de`.
- Natural Earth populated places (public domain), used only to label `show` output.
