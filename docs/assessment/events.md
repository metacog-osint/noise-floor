# Events and grading (v0.1)

**Date:** 23 Oct 2026 · **Status:** first working version, built overnight and not yet reviewed by a person · **Code:** `tools/events.py` · **Tests:** `tests/test_events.py` · **Register:** `data/events/register.sqlite` (gitignored)

## Bottom line

Every input item becomes an **observation**. Observations on the same UTC day fuse into **events**. Each event is graded on five independent fields, and every grade is stored with the rule that set it and the observations behind it.

The first run covers 385 days (1 Oct 2025 – 22 Oct 2026, UTC): 81,038 observations fused into 50,678 events.

- Announced FAA GPS tests come out `planned` when every effect in the event falls inside a test window and radius. 887 effect events qualify, and the rule reproduces all 1,283 test tags on the public map's event files.
- Storm days get NATURAL events. 10 m-only effects at storm time, poleward of a latitude gate or inside a storm-flagged SBAS area, come out `benign_natural`. Worse-than-93 m effects on storm days stay `open` and are never called deliberate.
- The persistent hotspots are EFFECT · Single-source, unverified · open on almost every day. That's the correct grade for ADS-B alone.

**What this version can't do yet:**

- "Multiple sources" needs two independent sensor families, and only ADS-B feeds the lane today.
- `deliberate_suspected` needs an interference warning that isn't a planned test. No such input is wired in.
- No localization method feeds the lane, so `localization_error_km` is null everywhere.

## The model

The model is the event model and five-field grading adopted in the merged plan (`docs/DESIGN.md`, "Merged plan"). The five fields are independent. They are not a ladder: a `planned` verdict isn't "above" `open`, and a localized event can still be single-source.

| Field | Values | Meaning |
|---|---|---|
| `signal_type` | EFFECT · WARNING · NATURAL | Something measurably degraded · an official notice · a space-weather alert to rule out first |
| `support` | Single-source, unverified · Partially corroborated · Multiple sources | SOP terms. "Multiple sources" needs two or more **independent** sensors agreeing in time and space |
| `localization_error_km` | null or km | Null until a fix exists |
| `attribution_status` | none · candidate · attributed | "Attributed" also needs no surviving benign explanation |
| `verdict` | open · benign_natural · planned · deliberate_suspected | The result of the exclusion checks |

**Grades describe evidence strength. They never name perpetrators.** An EFFECT is never called jamming without a WARNING-level or operator/government corroborant.

## Observations

| Kind | Signal | What it is | Time resolution | Input |
|---|---|---|---|---|
| `adsb_anomaly` | EFFECT | An anomaly event from `pipeline/pnt_analysis.py`: region-hours above their own 14-day baseline, on the 93 m (gross) or 10 m (capable) measure | hour | The site's daily event file (`site/data/events/<day>.json`, committed or fetched from the live site) |
| `adsb_burst` | EFFECT | A minute-level burst event (aircraft with a gross-bad report above the region's level) | minute | same |
| `adsb_level` | EFFECT | **Level check (new):** an H3 res-2 region with 3 or more res-4 hexes at the map's jamming scale for the day (5 or more aircraft, hex score of 10 or more) | day | per-hex daily table (`<day>.parquet` from the data releases) |
| `adsb_sbas` | EFFECT | An SBAS service flag run: an area-wide 10 m loss in an SBAS service area | hour | `site/data/events/<day>.json` |
| `faa_test` | WARNING | An announced GPS test from an FAA SPANS flight advisory: one observation per test per UTC day, with that day's windows | minute | `data/declared/faa_gps_tests.json` |
| `kp_storm` | NATURAL | A run of 3-hour GFZ Kp intervals of 5 or more (NOAA G1 or stronger) touching the day | 3 hours | GFZ Kp |

**Why the level check.** The anomaly and burst checks compare each region with its own recent past, so interference that is there every day sets its own baseline and drops out. The level check doesn't use a baseline. It uses the same hex score and thresholds as the public map: 100 × max(bad − 1, 0) / aircraft, live counts, 5 or more aircraft.

**Independence.** All four ADS-B kinds come from one aggregator (adsb.lol) through one processor. They are **one sensor family**, however many measures agree. FAA advisories are declared notices, not sensors. Kp is a context index used by the exclusion checks; it never counts toward support.

## Fusion rule

Events are bounded by the UTC day, because every input is processed per UTC day. Sensor observations fuse; notices attach.

1. **Located observations** (anomalies, bursts, level regions; anything with H3 res-2 cells):
   - Two observations link when a cell of one is the same as, or adjacent to, a cell of the other (H3 grid distance ≤ 1 at resolution 2).
   - Their time spans must also overlap or be at most 60 minutes apart. For hourly observations that means overlapping or adjacent hours.
2. **Distance cap.** Links are taken closest first. Two groups merge only if every pair of member centroids stays within **600 km**.
   - Without the cap, whole-day level regions chain across adjacent cells. On 10 Mar 2026 that fused the Baltic, the Black Sea and the eastern Mediterranean into a single 51-region event.
   - 600 km is a little over the radio horizon from a ground emitter to an aircraft at FL350 (about 440 km). It is a clustering guard, not a physical limit.
   - It was set after looking at one case, 22 Sep 2026, where 900 km merged the Bay Area bursts with bursts about 630 km away. Treat it as tunable (`build --max-km`).
3. **SBAS runs** link when they are in the same service area and at most 60 minutes apart. They never fuse with located observations, because they describe a whole service area.
4. **Announced tests** never fuse anything. Each test attaches to every event that holds a located EFFECT observation consistent with it (see rule P1). With none, the test becomes its own WARNING event.
5. **Kp storms** are planetary, not local, so they are never linked. Each run is its own NATURAL event and enters other events only through the space-weather check, where it is recorded as context.

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
| support | S3 | EFFECT observations from two or more independent sensor families in the event (fusion already requires agreement in time and space) | Multiple sources |
| | S2 | One sensor family, plus an independent notice consistent with it in time and place (an attached announced test) | Partially corroborated |
| | S1 | Anything else, including any number of ADS-B measures, or a lone notice | Single-source, unverified |
| localization_error_km | L0 | No localization method feeds the lane yet | null |
| attribution_status | A1 | Verdict `planned` by rule P1: the candidate is the announced test, named by its FAA identifier | candidate |
| | A0 | Otherwise | none |
| | (A2) | Would need a fix, a candidate and no surviving benign explanation. Never applies in v0.1 | attributed |
| verdict | P1 | Every located EFFECT observation lies inside an announced test window **and** within its widest published radius (the FL400 one), measured from the observation's centroid | planned |
| | P2 | The event is an announced test with no ADS-B effect matched to it | planned |
| | N0 | The event is a Kp storm run | benign_natural |
| | N1 | SBAS-only event with every flagged hour within 3 h of Kp ≥ 5; **or** a 10 m-only located event inside an SBAS area flagged at storm time in the same or an adjacent hour | benign_natural |
| | N2 | A 10 m-only located event during Kp ≥ 5 (within 3 h), poleward of a geomagnetic-latitude gate: \|mlat\| ≥ 50° for Kp 5–6.x, ≥ 40° for Kp 7–7.x, any latitude for Kp ≥ 8 | benign_natural |
| | D1 | An EFFECT corroborated by an interference warning that isn't a planned test, with the natural and planned checks failing. **No input feeds this yet** | deliberate_suspected |
| | V0 | Otherwise | open |

**Precedence.** P1 outranks N1/N2: a notice matched in time and place is more specific than a storm-time heuristic. Both checks are still recorded.

**Basis for the NATURAL rules.**

- Storms degrade GNSS accuracy to tens of metres, rarely past 93 m. In the Phase 1.1 storm tests (`docs/validation/phase1.md`, verdicts 9–10), the G2 storm of 18 Oct 2025 and the G4 storm of 12 Nov 2025 moved the 10 m share in the North American northern tier (12.4% and 38.5%) but left the gross share flat (on 12 Nov, 0.03% against a 0.04% baseline). So only 10 m-only effects can be excused by a storm.
- The SBAS storm label uses Kp ≥ 5 within ±3 h, as `pnt_analysis.py` does (verdict 16).
- The latitude gate in N2 is a **heuristic, not validated**:
  - Geomagnetic latitude comes from a centred dipole (pole near 80.8°N, 72.7°W), good to a few degrees.
  - The 50°/40°/any steps follow the equatorward spread of storm effects with Kp. The G4 storm of 12 Nov 2025 flagged the Japanese and Korean SBAS areas, at roughly 21–38° geomagnetic on this dipole.
  - The rule has been checked against only those two storms.

**Exclusion checks recorded on every EFFECT event:**

| Check | Results |
|---|---|
| `space_weather` | benign_natural (N1/N2) · storm_partial (storm present, but the event has gross loss, is outside the gate, or is an SBAS flag only partly at storm time) · not_indicated · unknown (no Kp) |
| `planned_test` | planned (P1) · partial (some effects consistent) · not_indicated |
| `receiver_fault` | screened_upstream: the processor drops avionics suspects (peer test) and post-exposure aircraft before anything is counted (`docs/method-card.md`, steps 3–4) |
| `sbas_service` | probable (SBAS flag at quiet Kp: probable service problem) · likely_benign (GAGAN or SouthPAN, where most aircraft don't use the service and the flag fires on most days) |

An `open` event also carries a hint when a benign explanation is plausible but no verdict value fits it: `sbas_service`, `sbas_equipage`, `storm_partial` or `test_partial`.

## Results: 1 Oct 2025 – 22 Oct 2026

Built on 23 Oct 2026 from the public daily event files, the per-hex daily tables in the data releases, the FAA advisory file (updated 22 Oct 2026) and GFZ Kp (definitive to 30 Sep 2026, preliminary after). A full build takes about 2.5 minutes on this PC.

**Observations:**

| Kind | Count |
|---|---|
| Anomaly events | 56,902 |
| Burst events | 11,310 |
| Level regions (region-days) | 10,421 |
| SBAS flag runs | 984 |
| Announced test-days | 1,347 |
| Kp storm runs | 74 |

**Grades, all 50,678 events:**

| Field | Distribution |
|---|---|
| signal_type | EFFECT 49,871 · WARNING 733 · NATURAL 74 |
| support | Single-source, unverified 49,716 · Partially corroborated 962 · Multiple sources 0 |
| localization_error_km | null 50,678 |
| attribution_status | none 49,791 · candidate 887 · attributed 0 |
| verdict | open 48,068 · benign_natural 990 · planned 1,620 · deliberate_suspected 0 |

**EFFECT events by measure:**

| Measure | open | benign_natural | planned |
|---|---|---|---|
| 93 m only (gross) | 18,719 | 0 | 132 |
| both | 5,020 | 0 | 104 |
| 10 m only (capable) | 24,329 | 916 | 651 |

**Open events with a benign hint:** `storm_partial` 3,316 · `sbas_equipage` 643 · `sbas_service` 102 · `test_partial` 64. The other 43,943 open events have no hint.

**benign_natural by rule:** N2 820, N1 96, N0 74 (the NATURAL events themselves).

**By month (UTC):**

| Month | Events | EFFECT | WARNING | NATURAL | open | benign_natural | planned | Partially corroborated |
|---|---|---|---|---|---|---|---|---|
| 2025-10 | 2,869 | 2,788 | 70 | 11 | 2,686 | 68 | 115 | 54 |
| 2025-11 | 4,129 | 4,063 | 59 | 7 | 3,907 | 110 | 112 | 59 |
| 2025-12 | 4,317 | 4,287 | 25 | 5 | 4,210 | 67 | 40 | 19 |
| 2026-01 | 4,361 | 4,289 | 62 | 10 | 4,063 | 204 | 94 | 36 |
| 2026-02 | 3,802 | 3,753 | 44 | 5 | 3,627 | 60 | 115 | 78 |
| 2026-03 | 4,045 | 3,961 | 74 | 10 | 3,722 | 147 | 176 | 113 |
| 2026-04 | 3,638 | 3,567 | 64 | 7 | 3,357 | 92 | 189 | 133 |
| 2026-05 | 3,520 | 3,457 | 59 | 4 | 3,352 | 45 | 123 | 66 |
| 2026-06 | 3,689 | 3,651 | 35 | 3 | 3,561 | 21 | 107 | 77 |
| 2026-07 | 4,221 | 4,167 | 51 | 3 | 4,060 | 47 | 114 | 67 |
| 2026-08 | 4,434 | 4,361 | 69 | 4 | 4,218 | 49 | 167 | 102 |
| 2026-09 | 4,505 | 4,434 | 70 | 1 | 4,319 | 19 | 167 | 102 |
| 2026-10 (to 22nd) | 3,148 | 3,093 | 51 | 4 | 2,986 | 61 | 101 | 56 |

"Multiple sources" and `deliberate_suspected` are 0 in every month.

### Known-case checks

**1. Announced tests come out `planned`.**

- Of 1,347 announced test-days, 614 matched an ADS-B effect. The other 733 are WARNING events (planned, rule P2) with no effect seen.
- 887 effect events are `planned` by rule P1. Each carries its test as the `candidate` and is graded "Partially corroborated".
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

**3. Persistent hotspots are EFFECT · Single-source, unverified · open.**

- Level observations exist on 383 of 385 days. All 4,189 events holding one are EFFECT · Single-source, unverified · no fix · none · open. That is the correct grade for ADS-B alone, under the rule that an effect isn't called jamming without a warning-level corroborant.
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

- **One independent sensor family.** Every EFFECT so far comes from adsb.lol ADS-B, so "Multiple sources" cannot occur. It becomes possible once a second lane writes located observations, for example CYGNSS RFI or NISAR/Sentinel-1 RFI. The fusion code needs no change for that: any observation with H3 cells fuses, and its family decides independence.
- **No interference warnings yet.**
  - NGA broadcast warnings, NOTAMs and similar notices would be WARNING observations of a different kind from planned tests. Without them `deliberate_suspected` can't be set.
  - That is deliberate. Persistent hotspots stay `open` until something other than ADS-B corroborates them.
- **The 10 m measure dominates the count.** Most events are 10 m-only departures from baseline. Those are weak signals: SBAS use, equipage and the ionosphere all move them. Filter on `effect_measure` (gross, both, capable) when reading the register.
- **Announced-test radii are generous.** P1 uses the widest published radius (FL400), as the map's test tags do. For some ranges that is over 1,000 km (White Sands notices reach about 1,200 km), so `planned` can cover effects far from the range. A tighter radius (for example the 10,000 ft one) is a design choice still open.
- **Equatorial scintillation isn't handled.** Post-sunset scintillation at low latitudes happens at any Kp. Ingesting the ionospheric nowcast archive (context lane) is the next step for the NATURAL check.
- **SBAS service problems have no verdict value.** They stay `open` with a hint. The plan's verdict list has nothing for a benign, non-natural system fault.
- **Day-bounded events.** An event that runs across midnight UTC appears as two events. Level observations have day resolution, so a level region links to anything nearby that day.
- **Event IDs depend on the inputs.** An event ID is a hash of its member observations, so it stays the same across rebuilds as long as the inputs don't change. If an input day is reprocessed, its event IDs change.
- **Inherited limits.** Everything in `docs/method-card.md` "What it can't tell you" still applies: strong jamming removes aircraft, coverage depends on volunteer feeders, and spoofing can look clean.
- **No person has reviewed these grades yet.** Spot checks are below; the rules haven't been tested against held-out cases.

## Reproduce

```
python tools/events.py fetch                 # public inputs not on disk: the site's daily event files (~10 MB) and GFZ Kp
python tools/events.py build --all           # or --days 2026-03-01..2026-03-31
python tools/events.py stats
python tools/events.py show --day 2026-09-22 --full
python tools/events.py show --event EV-...
python tests/test_events.py
```

The register is SQLite. Tables:

- `observations`, `events`, `event_observations` (role `member` or `context`), `grades` (value, rule, reason, basis per field), `exclusions`, `episodes`.
- `day_inputs`: which input files fed each day.
- `meta`: build time and every parameter.

It stays in `data/` (gitignored). The event files it reads are already public; the register itself is a working store, not a publication.

## Sources and licences

- adsb.lol daily archive (ODbL 1.0), through the PNT processor. Derived data is published under ODbL with attribution.
- FAA SPANS flight advisories (US government, public domain).
- GFZ Potsdam Kp index (CC BY 4.0), `kp.gfz.de`.
- Natural Earth populated places (public domain), used only to label `show` output.
