# Military air against its own usual level (method 1.0, 18 Nov 2026)

**What it measures:** military aircraft seen on ADS-B and MLAT, per region and role, each UTC day, against the same
UTC hours over the 28 days before. It is a measurement, never an alert, and **every count is a lower bound**:
military aircraft often fly with ADS-B off, many send Mode S with no position, and receiver coverage is uneven. A count
that rises can mean more aircraft or the same aircraft transmitting more; a count that falls can mean fewer, or more
of them dark.

**Tools:** `tools/milair.py` (method, reading, deploy step, live probe), `tools/milair_job.py` (the daily job,
`.github/workflows/milair.yml`), `tools/feed_v2.py` (`milair_items`). Tables: `registry/mil_roles.csv` (ICAO type code
to role), `registry/plane_alert_mil.csv` (+ `.meta.json`), `tools/milair_regions.json`. Tests:
`tests/test_milair.py` (synthetic archive fixtures, the reading's levels, the feed items through the kit's linter).
**Sources:** `adsblol-archive` (adsb.lol daily archive, ODbL 1.0) and `plane-alert-db` (SDR-Enthusiasts, ODbL 1.0).
The live endpoint `api.adsb.lol/v2/mil` (`adsblol-mil`) was probed once and is not used: like `adsblol-live`, its
production use waits on permission, and the archive carries the same flag with the history a baseline needs.
The airplanes.live API is not used directly, and adsb.fi's terms rule it out (see the register).
**Product:** `<day>.milair.json` on the release `milair-data-YYYY` (ODbL 1.0: a derived database, so share-alike, with
attribution to adsb.lol contributors and plane-alert-db). Aggregates per region, role and UTC hour only: no aircraft
identifiers leave the day scan.
**Starting points:** World Monitor's military tracking (adsb.lol `/v2/mil`, a vendored plane-alert-db, a 48-hour
rolling baseline per theatre, surge at a ratio of 2.0 or more with floors, severity 2x/3x/4x, stand-down under 50%) and
Bellingcat Turnstone's weekly averages of aircraft per day per region. What this lane does differently: a longer,
same-hours baseline; roles from ICAO type codes, not model-drafted categories; MLAT positions flagged; every count
called a lower bound.

## 1. Method (version 1.0)

1. **Input:** the adsb.lol archive for the UTC day (`adsblol/globe_history_YYYY`, tag
   `vYYYY.MM.DD-planes-readsb-prod-0`, about 3.7 GB in two or three parts), streamed from its public links into a tar
   reader, hashed (SHA-256) on the way, never unpacked or kept.
2. **Military:** a trace counts if adsb.lol's own database flags it military (`dbFlags` bit 1) or its ICAO address is
   in the committed plane-alert-db snapshot (rows with `#CMPG = Mil`). A cheap pre-filter reads only the head of
   each file for the flag. The day file counts which list said so (`via`: both, adsblol, plane-alert).
3. **Role:** from the ICAO type code (the trace's `t`, else the snapshot's), through `registry/mil_roles.csv`. For
   airframes shared by several roles, a type-name rule in the same row decides, read from the snapshot's type name,
   else the archive's description: A330 MRTT (tanker) against A330 (transport), KC-130J (tanker) and EC-130H (ISR)
   against C-130 (transport), RC-135 (ISR) on the KC-135 code, E-8C (ISR) and KE-3 (tanker) on the 707 code, MC-12
   (ISR) against King Air (transport), G550 CAEW (ISR) against C-37 (transport). Headline roles: **tanker**, **isr**
   (ISR, airborne early warning, maritime patrol, SIGINT, large drones), **transport** (airlift and VIP), **bomber**,
   **fighter** (fighter and attack). Also counted: trainer, rotary, other (a military type not in the table, listed
   in the day file's `unmapped_types` for upkeep) and unknown (no type). No model assigns roles.
4. **Positions:** airborne (altitude not "ground"), not stale, from ADS-B, MLAT, TIS-B, ADS-R or ADS-C; Mode S-only
   and "other" positions are not used. Non-ICAO (`~`) addresses are left out.
5. **Regions:** Watchfloor's published zone boxes (`more-context`, `scripts/build_interests.py`), the Gulf first, in
   `tools/milair_regions.json`. Watchfloor's Red Sea box overlaps its Gulf box, so here it is split at the Gulf box's
   edge: no two regions overlap (tested). Watchfloor's Somalia box is left out for now (it overlaps the Red Sea box).
6. **Counts per region and role:** distinct aircraft per UTC hour (an aircraft counts in a region-hour with any usable
   position there), summed over the day as **aircraft-hours**; distinct aircraft over the day; and the same two for
   aircraft whose positions there were all from multilateration (**MLAT-only**), which places aircraft that send no
   position of their own. MLAT-only aircraft are counted and flagged.
7. **Baseline:** the median, over the **same kind of day** (workday or weekend) in the 28 days before, of each day's
   aircraft-hours summed over the same UTC hours (all 24 for a complete archive day; the rule keeps partial days
   comparable). At least 12 of the 20 workdays, or 5 of the 8 weekend days, must have files;
   before that the reading says "no usual level yet". Also the median of distinct aircraft on the same days and the
   7-day mean of distinct aircraft (Turnstone's weekly per-day average). Workdays and weekends are kept apart because
   military flying drops by about two thirds worldwide at weekends (section 4), so a plain 28-day median would read
   every weekend as "below". Each region names its weekend in `tools/milair_regions.json`: Friday-Saturday for the
   Gulf, Red Sea and Levant regions (the weekend of the Gulf states, Israel and Yemen, and where the data dip),
   Saturday-Sunday elsewhere.

   **Two changes on 18 Nov 2026, both made on the first backfill and both reported here (section 4):** the first
   design used all 28 days, which read every weekend as "below"; and it summed per-hour medians, which come out near
   zero where aircraft are sparse (most hours are empty on most days), so the Red Sea read "at least 4x usual" on 11
   of 12 days while its aircraft count was ordinary. The thresholds and floors in item 8 were not changed.
8. **Level** (descriptive; set before any reading, not tuned): ratio = aircraft-hours / max(usual aircraft-hours, 1).
   - **above:** ratio at least 2 and distinct aircraft at least the role's floor, banded 2x, 3x, 4x;
   - **below:** ratio at most 0.5 and the usual distinct aircraft at least the floor;
   - **near:** anything else.

   Floors (distinct aircraft): transport 5, fighter 4, tanker 3, ISR 3, bomber 2, all military 5 (World Monitor's
   transport 5 and fighter 4; the rest set here).
9. **Feed:** one item per region with aircraft seen that day or usually, kind observation, **tier routine whatever the
   level** (no tier above routine without approval), measure `military_aircraft_hours` with the usual level as
   `expected` and a `baseline_ref` once the baseline has its minimum days, the role break-down in `measures.by_role`, and the
   lane's `health` on each item (`fresh` up to 2 days behind, `late` to 4, `stale` after; items are withheld after 7).
   Requirements `NF-PIR-6`, `NF-EEI-6` under `NF-SQ-1` (the suite's SQ1, "Is a zone escalating?").

## 2. What can and cannot be read from it

- A level of "above" says more military aircraft were **heard** than usual for those hours. It does not say why (an
  exercise, a deployment, a ferry flight, an airshow, or one squadron leaving transponders on), and it is not a
  warning.
- "Below" can be a stand-down or the same aircraft flying dark. Neither is attribution.
- Fighters, bombers and ISR aircraft are the roles most often dark; their counts are the weakest lower bounds.
- Coverage changes move every count. adsb.lol's feeder coverage is thin on many region-days over the Gulf, the
  Caucasus and the Black Sea (`docs/validation/coverage-flag.md` counted 52 thin H3 region-days in its Gulf box on 2-15 Nov 2026),
  so a change in feeders can look like a change in activity.
- The live probe on 18 Nov 2026 (about 15:10 UTC) gives a sense of the dark share among aircraft that do transmit:
  of 452 aircraft on `/v2/mil`, 111 (25%) had no position at all.

## 3. First reading: 17 Nov 2026

From 29 archive days, 20 Oct - 17 Nov 2026, scanned on the PC on 18 Nov with `tools/milair_job.py --no-upload`
(about 3-4 minutes a day; the files are kept locally in `data/milair/`, not published). 17 Nov is a workday
everywhere, so its baseline is the 20 workdays of 20 Oct - 16 Nov. Every number is a lower bound.

| Region | Aircraft | Aircraft-hours | Usual aircraft-hours | Level | MLAT-only share | By role (aircraft) |
|---|---|---|---|---|---|---|
| Persian Gulf and Strait of Hormuz | 70 | 183 | 191.5 | near | 15% | tankers 6, ISR 1, transports 17 |
| Red Sea, Gulf of Aden, western Arabia | 9 | 10 | 8.5 | near | 0% | tankers 1, transports 5 |
| Levant coast | 25 | 65 | 42.5 | near | 31% | tankers 6, ISR 1, transports 8 |
| Baltic Sea | 52 | 169 | 153 | near (tankers 4, at least 2x usual) | 22% | tankers 4, ISR 3, transports 20, fighters 1 |
| Korea | 23 | 53 | 90 | near | 9% | ISR 2, transports 12 |
| Black Sea and Sea of Azov | 5 | 6 | 9.5 | near | 0% | transports 3 |

Worldwide on 17 Nov: 2,888 military aircraft with a position (88 tankers, 84 ISR, 626 transports, 33 fighters, 3
bombers; the rest trainers, helicopters and others). Over the Gulf no bomber was seen on any of the 29 days, and a fighter on 2 of them (one each).

## 4. Results of the backfill

- **Military aircraft in the archive per day, worldwide:** median 2,613 (range 613-3,313). Weekends drop by about
  two thirds (24-25 Oct: 981 and 869, against 2,566-3,313 on the weekdays around them); trainers drop most (148 with
  a position on 24 Oct, against about 800 on weekdays).
- **Weekends by region:** the Gulf dips on Friday and Saturday (on 30-31 Oct, 6-7 Nov and 13-14 Nov: 37, 19, 33, 26,
  41 and 20 aircraft, against 60-98 on Monday-Thursday); the Levant on Friday and Saturday; the Baltic and Korea on
  Saturday and Sunday. Gulf Sundays sit in between (59, 45, 32, 55), probably because US forces there keep a
  Saturday-Sunday weekend while host nations keep Friday-Saturday; the method treats Sunday as a Gulf workday, so a
  Gulf Sunday reads low (8 Nov read "below": 32 aircraft against a usual 71).
- **How often each level comes up** (12 regions, 5-17 Nov 2026, the days with a full baseline, 144 region-days; all
  military aircraft): near 130 (90%), above 5 (3.5%), below 9 (6%). By role: tankers above 5 and below 5; ISR above
  5 and below 4; transports above 8 and below 2; fighters and bombers near on every day (too few to pass a floor).
  These are the base rates to read any "above" against: with 12 regions, about one region-day in 30 reads above.
- **Which list said military:** both 30,385 aircraft-days, adsb.lol's flag only 34,100, plane-alert-db only 432.
  plane-alert-db adds 0.7%; adsb.lol's flag carries the lane.
- **Roles:** of 64,917 aircraft-days, helicopters 31%, trainers 26%, transports 23%, tankers 3.4%, ISR 3.1%,
  fighters 1.0%, bombers 0.06%, unknown type 5.3%, other 7.1%. The commonest unmapped types (AW169, Tucano, DA40,
  TBM 700, ATR 72-600, Kawasaki P-1, 737-600 and others) were added to the table afterwards, so the published files
  will put fewer aircraft in "other"; the first reading's roles come from the table before that.
- **MLAT-only share of aircraft-hours, 29 days:** Gulf 23%, Levant 42%, Baltic 21%, Korea 13%, Taiwan 48% (90
  aircraft-hours); 0% over the Red Sea, Black Sea, South China Sea and Arabian Sea, where no MLAT network reaches.
  Where MLAT is zero, aircraft that send no position are not counted at all.

## 5. Not done yet

- **Hit rate.** No check against announced deployments or exercises yet. A pre-registered test would take public
  announcements (exercise dates, deployment press releases) in a held-out period and ask whether "above" days in the
  named region exceed chance; until then the lane publishes counts and levels only.
- **Map and page.** The site shows nothing yet beyond the feed items; a Trends panel (`site/data/milair/history.json`
  is already written at deploy) and a map layer are next.
- **COP.** COP's entry for the new kind is a separate COP change.
