# GEO callouts: frozen rules, published cases and scoring (G4)

Pre-registered 31 Oct 2026, before any rule was run on orbital history. This file is committed first; the scoring is
added below it afterwards, and nothing above the "Results" heading changes once the results exist. If a rule turns out
to need changing, the change is written as a new version (v2) with its reason, and scored again from scratch.

Callouts describe behaviour, never intent. Each names its rule and the numbers behind it.

## Common definitions (v1)

- **Data.** Space-Track element sets for every object near GEO (`geo-elements-YYYY-MM.parquet`, held from 1 Jul 2026;
  G1), with each object's owner code and object type from the Space-Track catalogue fields in the same pull.
- **Position at an instant.** The object's latest element set with an epoch at or before that instant (never a later
  one), if it is no more than 10 days old then; propagated with SGP4 (the `sgp4` library, WGS72 constants) to the
  instant. Positions are TEME, in km. Separation is the straight-line distance between two positions.
- **Day value.** For a pair on a UTC day: the smallest of the 24 separations on the hour (00:00 to 23:00 UTC). Hourly
  sampling catches the daily north-south swing of inclined orbits, where two objects can pass within 100 km once or
  twice a day and be 1,500 km apart in between.
- **Drift.** 360 × mean motion − 360.98564736629 degrees a day, from the element set in use. **Holding longitude:**
  drift under 0.1° a day in magnitude. **Station-kept neighbour** (C3 and C4 only): holding longitude and inclination
  under 1°, the board's own definition, because an inclined object within 0.5° of longitude is hundreds of km away
  most of the day.
- **Longitude.** Sub-satellite longitude at 12:00 UTC on the day, from the SGP4 position and Greenwich sidereal time.
- **Pairs.** For C1 to C4, both objects are payloads (catalogue object type PAYLOAD) with different owner codes (a
  missing owner code counts as different). Rocket bodies and debris are left out of these four rules.
- **Listed role.** An inspection or servicing role in `site_src/geo_roles.json`, each entry cited.
- **Evaluation span.** Every UTC day whose positions can be formed from the held history: 8 Jul 2026 (seven days after
  the first held epoch, so every object has a current element set) to the last complete day held.

## Rules (v1)

| # | Callout | Rule, frozen |
|---|---|---|
| C1 | Close to another owner's satellite | Day value under 100 km. Consecutive qualifying days form one episode (one missing or non-qualifying day does not break it). The callout fires on the episode's first day. Raised a level when either object has a listed role. An episode already running on the span's first day is "standing" and is not counted as new. |
| C2 | Approaching | Day values falling on three consecutive days (d(D−3) > d(D−2) > d(D−1) > d(D)), d(D) under 200 km, and a total fall d(D−3) − d(D) of at least 30 km (more than the day-to-day jitter of public elements). Fires on day D; at most once per pair in any 14 days. |
| C3 | Parked beside another owner | A payload whose drift was 0.1° a day or more in some element set in the previous 14 days, which manoeuvred in that time (its drift changed by more than 0.02° a day between two element sets no more than 3 days apart), whose drift on day D−1 and day D is under 0.05° a day, and whose longitude on day D is within 0.5° of a station-kept payload of another owner. Fires on day D; at most once per payload in any 30 days. |
| C4 | Heading for an occupied slot | A payload drifting (0.1° a day or more on day D) whose drift on day D is at most half its largest drift in the previous 7 days (it is slowing), and which, at its day-D drift, comes within 0.5° of a station-kept payload of another owner within 14 days, moving toward it. Fires on day D; at most once per payload in any 30 days. |
| C5 | Listed-role object changed orbit | Between consecutive element sets of a listed-role object at least 12 hours apart: drift changed by more than 0.02° a day, inclination by more than 0.02°, or the later set's longitude at its epoch is more than 0.15° from where the earlier set puts it by SGP4 (the board's manoeuvre thresholds). Fires on the later set's day; at most once per object per day. |
| C6 | Arrived | G1's "arrived" event (into the protected zone, with its 25 km / 0.25° hysteresis). |
| C7 | Retired to the graveyard | G1's "left up" event. Information only. |
| C8 | Went quiet | G1's "quiet" event: an active payload in the zone whose latest public elements passed 7 days old. |

C6 to C8 reuse G1's events unchanged; they are scored on their cases and their weekly counts. Case runs on objects
before the held history compute C1 to C5 only (G1's events need the whole population).

**Two changes before the first run.** The draft C3 and C4 were amended on 31 Oct 2026 after reading the case
research (its "traps" section), before any rule had run on real history: (1) C3 needs a manoeuvre, because
uncontrolled inclined objects slow at the ends of their libration and look as if they stopped (an automated
public-element detector withdrew a batch of such notices on 28 Aug 2026); (2) C3 and C4 neighbours must be
station-kept, because inclined objects such as TDRS 7 (13.3°) beside TJS-15 sit within 0.5° in longitude but far
away. Both are covered by synthetic tests in `tests/test_geo_callouts.py`.

## Scoring plan (v1)

1. **Published cases.** The list below is written, with sources, before any rule runs. A case is a **hit** when the
   rule it names fires for the named objects within the case's window, widened by 3 days at each end; otherwise a
   **miss**. Cases whose window is inside the held history are scored on the full population. Cases before 1 Jul 2026
   need element history for their objects only (one gp_history request per case, stored and never fetched again); they
   are scored on those objects alone, so they test detection but say nothing about false alarms.
2. **Quiet history.** New callouts per week, per rule, over the evaluation span, with the busiest week named. Every
   callout in the two busiest weeks is listed in the results with its numbers, so the reader can judge them.
3. **Switch-on criteria, fixed now.** A rule is shown by default on the globe only if (a) it hit at least half of the
   cases it was scored on, or had no scorable case and is one of C6 to C8, and (b) it averaged no more than 10 new
   callouts a week over the span. A rule that fails either is available behind its toggle, off by default, with its
   score stated beside it. No rule is tuned to pass.
4. **Stated limits.** Public elements place a GEO satellite to tens of kilometres; separations under about 50 km are
   not resolved; element sets arrive irregularly, so a manoeuvre is dated only to between two epochs.

## Published cases

The machine-readable list, with each expectation's rule, objects, window (already widened by 3 days each side) and
outcome, is `docs/validation/geo-callouts-cases.json`; the scorer reads only that file. Confidence tiers: **G**
government or operator statement; **C** commercial tracking firm; **I** independent observer with their own sensor, or
an analyst with a stated method; **N** a newsletter or automated detector working from the same public elements we
hold, so agreement with it shows the rules behave like other public-element detectors, not that they match ground
truth; **P** press relaying any of these.

**Inside the held history (scored on every object held):**

| Case | What was published | Expected | Tier | Sources |
|---|---|---|---|---|
| A1 | TJS-15 (63157) moved 94.4°E → 88.7°E, 25 Aug – 6 Sep 2026, passing about 64 km from WGS F4 (38070) at 12:50 UTC on 4 Sep, then held 0.2–0.3° away | C1, C2, C4, C3 | N | [ISR University Integrity Flash 153](https://isruniversity.com/2026/09/14/issue-153/) and [155](https://isruniversity.com/2026/10/12/issue-155/); [KeepTrack arrival notice](https://keeptrack.space/ktoc-notice/kt-20260908-63157-arr-tjs-15-arrival); [Orbital Focus GEO list](https://www.orbitalfocus.uk/Diaries/Launches/GeoSS/geo-loc.php) |
| A2 | SJ-23 (55131) drifted past WGS F4 at 132 km, 12:20 UTC 4 Sep 2026 | C2; C1 silent | C via N | ISR 153, quoting a commercial tracking figure |
| A3 | Cosmos 2589 (64467) drifted 98°E → about 128°E (20 Jul – 30 Sep 2026); braking burns on 24–25 Sep raised a predicted pass of USA 270 (41744) from 27–41 km to 112 km; it stopped beside JCSAT-3A and GEO-KOMPSAT-2A | C2; C1 silent; C3 (not against Cosmos 2526, same owner) | C + N | [ISR 150](https://isruniversity.com/2026/07/28/issue-150/), [154](https://isruniversity.com/2026/09/28/issue-154/) and 155; [KeepTrack relocation notice](https://keeptrack.space/ktoc-notice/kt-20261008-64467-rel-cosmos-2589-relocation) |
| A4 | USA 271 (41745, GSSAP) replaced USA 325 beside Cosmos 2589 at 98°E on 3–5 Jul 2026; 40–100 km passes on 12–13 Jul | C1 | N | ISR 150 |
| A6 | MEV-1 (44625) undocked from Optus D3 before 12 Aug 2026 (date not published) | C5 | G | [Northrop Grumman, 13 Aug 2026](https://news.northropgrumman.com/civil-space/northrop-grumman-continues-in-space-industry-leadership-second-mission-extension-vehicle-undocking); [FCC report SAT-02009](https://docs.fcc.gov/public/attachments/DOC-422465A1.txt) |
| A7 | ZhongXing-10 (37677) raised to a disposal orbit, burn about 18 Sep 2026 | C7 | N | [KeepTrack departure notice](https://keeptrack.space/ktoc-notice/kt-20260921-37677-dep-zhongxing-10-departure); CelesTrak catalogue |
| A8 | DirecTV 9S (29494, 12 Sep), USA 176 (28158, 15 Sep) and USA 149 (26356, 3 Sep 2026) left for the graveyard | C7 each | N | KeepTrack notices; CelesTrak catalogue |
| A10 | Arrivals: EOS-05 (100607, parked 86.5°E by 29 Sep), Tianlian 2-06 (100140, about 10 Aug), Tianlian 3-01 (100172) | C6 each | G + N | ISR [151](https://isruniversity.com/2026/08/10/issue-151/), 153 and 155 |
| A11 | Shijian-31 (69570) on a 12.5-hour, 63.5° orbit whose apogee sweeps GEO longitudes (a negative case) | C6 and C1 silent | P | [ThePrint, 18 Sep 2026](https://theprint.in/science/china-shijian-31-satellite-geostationary-orbit/3046456/), citing COMSPOC |
| A13 | Express 80 (45986): about 22 days without public elements from about 19 Sep 2026 | C8 | N | KeepTrack notice; catalogue number not confirmed on CelesTrak |

Same-owner cases (Cosmos 2589 with Cosmos 2526; Shiyan-12 01 with Tianlian 1-05; TJS-17 crossing TJS-19; WGS F3 beside
USA 167; Eutelsat 7B and 16A; SJ-21 with SJ-25) cannot raise C1 to C4 by construction, so they are not scored. Luch-5X
beside Intelsat 39 all window is a standing state; C3 is an event rule and is not expected to fire for it.

**Before the held history (one gp_history pull each, scored on the case's objects alone):**

| Case | What was published | Expected | Tier | Sources |
|---|---|---|---|---|
| B1 | Luch / Olymp-K 1 (40258) parked between Intelsat 7 (25473) and Intelsat 901 (26824) near 18°W from 22 Jun 2015, about 10 km away at times | C4, C3, C1 | G + I | [SpaceNews, 9 Oct 2015](https://spacenews.com/russian-satellite-maneuvers-silence-worry-intelsat/); [CSIS Luch timeline](https://aerospace.csis.org/luch) |
| B3 | Luch held 38.1°E from 24 Oct 2017 near Athena-Fidus (39509) and Paksat 1R (37779, number unverified) | C4, C3 | G + I | Reuters via [Morung Express, 7 Sep 2018](https://morungexpress.com/france-accuses-russia-spying-military-space); CSIS |
| B5 | MEV-1 docked with Intelsat 901 in the graveyard, 25 Feb 2020 | C1, C5 | G | [Spaceflight Now, 26 Feb 2020](https://spaceflightnow.com/2020/02/26/two-commercial-satellites-link-up-in-space-for-first-time/) |
| B6 | MEV-2 (46113) docked with Intelsat 10-02 (28358), 12 Apr 2021 | C2, C1, C5 | G | [Spaceflight Now, 13 Apr 2021](https://spaceflightnow.com/2021/04/13/northrop-grumman-servicer-docks-with-active-satellite-in-geosynchronous-orbit/) |
| B9 | Luch-5X (55841) stopped at 3.2°E from 4 Oct 2023 beside Eutelsat 3B (39773), about 18 km on 15 Oct | C4, C3, C1, C5 | I + C | [Breaking Defense, 17 Oct 2023](https://breakingdefense.com/2023/10/second-russian-luch-olymp-satellite-now-trailing-western-systems-in-orbit/); [Langbroek, SatTrackCam Leiden](https://sattrackcam.blogspot.com/2024/09/the-russian-sigint-satellite-luch-olymp.html) |
| B10 | SJ-21 (49330) parked at 127.6°E on 5 Jun 2025; SJ-25 (62485) moved to 127.4°E on 10–14 Jun | C5 each; C1 silent (same owner) | G + C | [Breaking Defense, 19 Jun 2025](https://breakingdefense.com/2025/06/chinese-sats-appear-to-be-attempting-first-ever-on-orbit-refueling-sat-tracking-firms-say/); [CSIS, Apr 2026](https://www.csis.org/analysis/new-rhythms-geo-quantitative-analysis-unusual-behavior-geosynchronous-orbit-chinese) |
| B13 | USA 324 (51280, GSSAP) passed TJS-16 (63397) at about 17 km on 26 Apr 2025 and TJS-17 (63524) at about 12 km on 29 Apr | C1 each | C via P | [Newsweek](https://www.newsweek.com/us-china-news-military-satellites-close-encounter-orbit-2067071), citing COMSPOC |

Published figures under about 20 km (B9, B13) are scored as "C1 fired", never on the number: public elements carry
errors of roughly 10–25 km at GEO ([GMV for ESA, 2017](https://conference.sdo.esoc.esa.int/proceedings/sdc7/paper/412/SDC7-paper412.pdf);
[ISRO, 2017](https://conference.sdo.esoc.esa.int/proceedings/sdc7/paper/657/SDC7-paper657.pdf)). The searches that
found nothing are listed in the private research note; an absence of reporting is not taken as quiet.

## Results (v1, run 1 Nov 2026)

Run once, after the commit that froze everything above (`1b6d8fd`). Held span 8 Jul – 30 Oct 2026: 1,368 payloads,
488,716 candidate pairs, 11,023 callouts. The seven pre-history cases used seven gp_history requests (3,098 element
sets), stored in `data/geo/region/history/cases/`. One change after the freeze, before the full run: the engine
cached each object's epoch list instead of rebuilding it for every lookup (speed only; the logic and every threshold
are unchanged, and the synthetic tests pass as before). Outputs: `data/geo/callouts/callouts-v1.json` and
`score-v1.json` (private data folder); every callout of each rule's two busiest weeks is in
[`geo-callouts-busiest-weeks.csv`](geo-callouts-busiest-weeks.csv).

**By rule, against the switch-on criteria fixed before the run** (on by default only with at least half the cases hit
and at most 10 new callouts a week):

| Rule | Cases hit | New per week (busiest) | Default |
|---|---|---|---|
| C1 Close to another owner's satellite | 10 of 12 | 162 (188 in the week of 19 Oct) | **off**: too many |
| C2 Approaching | 1 of 4 | 497 (565) | **off**: too many, and missed 3 of 4 |
| C3 Parked beside another owner | 4 of 5 | 2.3 (7) | on |
| C4 Heading for an occupied slot | 2 of 4 | 0.9 (3) | on |
| C5 Listed-role object changed orbit | 5 of 6 | 2.7 (5) | on |
| C6 Arrived | 4 of 4 | 1.2 (4) | on |
| C7 Retired to the graveyard | 3 of 4 | 0.5 (3) | on |
| C8 Went quiet | 0 of 1 | 1.3 (8) | **off**: missed its one case |

**Every expectation:**

| Case | Rule | Objects | Window | Expected | Result | Found |
|---|---|---|---|---|---|---|
| A1 | C1 | 63157, 38070 | 2026-09-01 to 2026-09-07 | fire | hit | C1 2026-09-04, 65.3 km |
| A1 | C2 | 63157, 38070 | 2026-08-29 to 2026-09-07 | fire | hit | C2 2026-09-04, 65.3 km |
| A1 | C4 | 63157 | 2026-08-22 to 2026-09-08 | fire | **miss** | – |
| A1 | C3 | 63157 | 2026-09-03 to 2026-09-11 | fire | hit | C3 2026-09-07 vs WGS F4 (USA 233) |
| A2 | C2 | 55131, 38070 | 2026-08-29 to 2026-09-07 | fire | **miss** | – |
| A2 | C1 | 55131, 38070 | 2026-08-29 to 2026-09-07 | silent | hit | – |
| A3 | C2 | 64467, 41744 | 2026-09-19 to 2026-09-28 | fire | **miss** | – |
| A3 | C1 | 64467, 41744 | 2026-09-19 to 2026-10-03 | silent | hit | – |
| A3 | C3 | 64467 | 2026-09-27 to 2026-10-04 | fire | hit | C3 2026-10-02 vs JCSAT 10 |
| A4 | C1 | 41745, 64467 | 2026-07-08 to 2026-07-19 | fire | hit | C1 2026-07-14, 67.7 km |
| A6 | C5 | 44625 | 2026-07-15 to 2026-08-15 | fire | **miss** | – |
| A7 | C7 | 37677 | 2026-09-13 to 2026-09-22 | fire | hit | C7 2026-09-19 |
| A8 | C7 | 29494 | 2026-09-09 to 2026-09-15 | fire | **miss** | – |
| A8 | C7 | 28158 | 2026-09-12 to 2026-09-18 | fire | hit | C7 2026-09-14 |
| A8 | C7 | 26356 | 2026-08-31 to 2026-09-06 | fire | hit | C7 2026-09-02 |
| A10 | C6 | 100607 | 2026-09-02 to 2026-10-02 | fire | hit | C6 2026-09-29 |
| A10 | C6 | 100140 | 2026-07-20 to 2026-08-13 | fire | hit | C6 2026-08-11 |
| A10 | C6 | 100172 | 2026-07-26 to 2026-09-30 | fire | hit | C6 2026-08-18 |
| A11 | C6 | 69570 | 2026-07-08 to 2026-10-30 | silent | hit | – |
| A11 | C1 | 69570 | 2026-07-08 to 2026-10-30 | silent | hit | – |
| A13 | C8 | 45986 | 2026-09-23 to 2026-10-02 | fire | **miss** | – |
| B1 | C4 | 40258 | 2015-06-08 to 2015-06-25 | fire | hit | C4 2015-06-19 vs INTELSAT 901 |
| B1 | C3 | 40258 | 2015-06-19 to 2015-06-25 | fire | **miss** | – |
| B1 | C1 | 40258 | 2015-06-19 to 2015-09-28 | fire | hit | C1 2015-06-22, 34.6 km; C1 2015-06-25, 34.9 km |
| B3 | C4 | 40258 | 2017-10-15 to 2017-10-26 | fire | **miss** | – |
| B3 | C3 | 40258 | 2017-10-21 to 2017-10-27 | fire | hit | C3 2017-10-23 vs PAKSAT 1R |
| B5 | C1 | 44625, 26824 | 2020-02-22 to 2020-02-28 | fire | hit | C1 2020-02-08, 0.0 km |
| B5 | C5 | 44625 | 2020-01-01 to 2020-04-30 | fire | hit | C5 2020-01-06; C5 2020-01-09 |
| B6 | C2 | 46113, 28358 | 2021-03-20 to 2021-04-15 | fire | **miss** | – |
| B6 | C1 | 46113, 28358 | 2021-04-05 to 2021-04-15 | fire | hit | C1 2021-03-01, 0.0 km |
| B6 | C5 | 46113 | 2021-03-01 to 2021-04-30 | fire | hit | C5 2021-03-10; C5 2021-03-14 |
| B9 | C4 | 55841 | 2023-09-22 to 2023-10-07 | fire | hit | C4 2023-10-01 vs EUTE 3B |
| B9 | C3 | 55841 | 2023-10-01 to 2023-10-07 | fire | hit | C3 2023-10-06 vs EUTE 3B |
| B9 | C1 | 55841, 39773 | 2023-10-04 to 2023-10-18 | fire | hit | C1 2023-10-03, 24.1 km |
| B9 | C5 | 55841 | 2023-09-22 to 2023-10-07 | fire | hit | C5 2023-09-26; C5 2023-09-27 |
| B10 | C5 | 62485 | 2025-06-07 to 2025-06-17 | fire | hit | C5 2025-06-11 |
| B10 | C5 | 49330 | 2025-06-01 to 2025-06-08 | fire | hit | C5 2025-06-03; C5 2025-06-04 |
| B10 | C1 | 62485, 49330 | 2025-05-15 to 2025-07-15 | silent | hit | – |
| B13 | C1 | 51280, 63397 | 2025-04-23 to 2025-04-29 | fire | **miss** | – |
| B13 | C1 | 51280, 63524 | 2025-04-26 to 2025-05-02 | fire | **miss** | – |

**Why each miss happened** (read from the data; no rule was changed):

- **A1 C4 (TJS-15).** It braked from 0.63° a day to a stop in one go, so it was never "drifting at half its recent
  speed" while still more than 0.5° from WGS F4. C4 can only see stops made in stages; C3 caught this one on 7 Sep.
- **A2 C2 (SJ-23).** SGP4 on the public elements puts its closest pass to WGS F4 at 285 km on 4 Sep; the published
  figure, from a commercial sensor network, is 132 km. C2 needs under 200 km. The daily falls were there
  (3,079 → 2,475 → 1,860 → 1,232 → 621 → 285 km).
- **A3 C2 (Cosmos 2589).** The same: closest 215 km on 26 Sep by public elements, 112 km published. It fell for eight
  days in a row but stayed 15 km above the 200 km mark.
- **A6 C5 (MEV-1).** Space-Track published no elements for MEV-1 while it was docked; its first set in the held
  history is dated 12 Aug 2026, after the undocking, so there was no earlier set to compare it with.
- **A8 C7 (DirecTV 9S).** G1 logged "left up" on 5 Sep, seven days before the published 12 Sep, which is the date
  KeepTrack saw it leave its slot. The callout was early, outside the window.
- **A13 C8 (Express 80).** Its last set before the 21-day gap put it outside the zone ("left", 20 Sep), so C8, which
  watches payloads in the zone, could not fire; G1 logged "arrived" when sets resumed on 11 Oct.
- **B1 C3 (Luch, 2015).** Its drift first fell under 0.05° a day on 25 Jun, so C3 fired on 26 Jun beside Intelsat
  901 (0.10° away), one day after the window. C4 fired on 19 Jun and C1 on 22 Jun (35 km).
- **B3 C4 (Luch, 2017).** By the time it had slowed to half its top speed (21 Oct) it was already within 0.5° of its
  stop, which C4 excludes; C3 fired on 23 Oct beside Paksat 1R.
- **B6 C2 (MEV-2).** Its public elements matched Intelsat 10-02's from the first day of the pulled window (C1 at
  0.0 km on 1 Mar 2021), so the separation could not fall. B5 shows the same: C1 at 0.0 km on 8 Feb 2020, 17 days
  before the reported docking. Identical element sets for a servicer and its client are a data property, not a
  measurement of 0 km.
- **B13 C1 (USA 324).** Space-Track returned no element sets for USA 324 in that window, so the case could not be
  tested; it is counted as a miss, as the plan requires.

**What the noise is.** C1's 2,654 new episodes involve 2,382 different pairs, and 1,984 of them last one day: mostly
inclined objects passing near another owner's satellite at a node crossing (median closest 73 km), plus slot-sharing
pairs whose separation jitters across 100 km. C2's 8,170 callouts involve 7,474 pairs, chiefly the same daily
crossings. Both rules find the published cases they were meant for (C1: 10 of 12), but at that volume they can't be
read as alerts. A v2 of C1 and C2 (for example, two or more consecutive days, or only station-kept pairs) would be a
new rule, written down and scored from scratch on new cases; none is adopted here.

**Agreement and independence.** Seven of the in-window cases come from a newsletter or an automated detector that
works from the same public elements (tier N), so those hits show the rules behave like other public-element
detectors. The independent anchors held up as well: Luch 2015 (C4, C1), Luch-5X 2023 (all four rules), SJ-21 and
SJ-25 2025 (C5 for both, C1 silent between same-owner satellites), MEV-1 and MEV-2 (C1, C5).

**Switch-on (next commit):** C3, C4, C5, C6 and C7 shown by default on the globe; C1, C2 and C8 behind their
toggles, off, each with its score beside it.
