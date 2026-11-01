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

## Results

*Not run yet.*
