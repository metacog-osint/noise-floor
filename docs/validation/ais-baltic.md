# AIS lane, Baltic development sample: first results (24 Oct 2026)

**Lane:** `ais` (maritime plan, `docs/maritime-plan.md`, detectors D3–D7). **Code:** `collectors/digitraffic_ais.py`
(collector), `tools/ais_detect.py` (detectors), `tests/test_ais_detect.py` (synthetic tests). **Data:** Digitraffic AIS
from Fintraffic (registry id `digitraffic-ais`, CC BY 4.0: "Source: Fintraffic / digitraffic.fi, license CC 4.0 BY").

Finland's open AIS covers the northern Baltic, where GNSS jamming and spoofing are heavy. It is the development ground
for detectors meant to move later to the South China Sea and Indian Ocean, where no licence-clean AIS exists.
AIS-derived event lists (vessel identities, positions) stay private in `data/ais/digitraffic/events/` (gitignored), as
the plan requires (Section 11). This page gives counts and anonymised examples only.

**Update, 26 Oct 2026: detector D7 (GNSS interference likely) passed its pre-registered held-out test, regional (Finnish waters and the approaches); see "Held-out test: results" at the end. The check against the ships' own lost-fix reports came out 2.6x, short of the 3x set in advance.**

**This is one short development sample: 1.9 hours, 03:31–05:27 UTC on 24 Oct 2026** (06:31–08:27 Finnish time;
22:31–00:27 US Central, CDT). Nothing here is validated. Durations for D3–D5 were scaled down to fit it (Section 2).

## Bottom line

- **GNSS spoofing of ships in the eastern Gulf of Finland is visible in open AIS, and the detectors find it without
  tuning.** In 1.9 hours, 8 vessels had position reports flagged as GNSS interference.
  - 7 of them reported positions on one small circle in inland north-western Russia, about **57.67°N 32.53°E**, roughly
    340–380 km south-east of where they really were. Those reports showed impossible speeds over ground (median 71–80 kn),
    a course over ground that swung round the circle while the heading stayed fixed, and the position-accuracy and
    RAIM flags both off.
  - The 8th vessel, a tug in Russian waters near the Finnish border (about 60.5°N 28.0°E), reported 102.2 kn (the
    maximum code) with positions scattered over about 30 km for the full two hours.
  - Of the 8, the 3 with trusted positions before or after were in the **eastern Gulf of Finland, east of 27°E**. The
    other 5 were spoofed for the whole time they were received.
  - Flagged reports came in all three clock hours of the sample, from 5 vessels in each hour.
- **Independent GNSS-degradation signs agree on the same area.** In the eastern Gulf, 25 of 48 vessels (52%) flipped
  their position-accuracy flag, against 8–16% elsewhere, and 5 of 48 reported speed "not available". The aircraft map
  shows 80% of aircraft reports degraded there over 8–21 Oct, against 0.7–5% over the other covered sea areas.
- **D3–D6 run, but a 2-hour sample can't test them.** Rendezvous and loitering hits are almost all ports, anchorages and
  moored pairs. Going-dark hits are 2 stationary craft without IMO numbers. No identity changes and no
  destination-field statements were seen.
- **Coverage is the main limit for this test area.** Kaliningrad is outside Digitraffic's reach and Narva Bay (the
  Estonia–Russia border) had no positions at all. Spoofed vessels with no trusted fix can't be located, because the
  feed doesn't say which station heard them.
- **Next:** collect for several days with the plan's durations (command in Section 7), then score spoofing events
  prospectively against public notices, since Digitraffic keeps no history.

## 14-hour run (24 Oct 2026, 03:31–17:45 UTC)

The collector then ran for 12 hours on its own; with the earlier sample the day covers 14.2 hours: 1.81 million position
rows from 928 vessels (1,432 duplicates dropped), with four reconnects and no message errors. Detectors used the plan's
durations (`--preset plan`: dark gap 6 h, rendezvous 2 h, loiter 6 h).

- **GNSS interference: 26 vessels whose trusted positions were in the Gulf of Finland east of 27°E**, plus 1 each in the
  Bothnian Bay, the northern Baltic Proper and the Gulf of Finland west of 27°E, and 4 with no trusted position.
- **Where they were shown:**
  - 13 on the same circle as in the first sample, near 57.7°N 32.5°E in inland north-western Russia (one more 0.1° west),
    330–380 km from where they really were, at 66–81 kn.
  - One each near 58.4°N 30.7°E, 57.9°N 33.4°E and **60.12°N 31.37°E, east of St Petersburg**.
- **Timing:** 5 vessels an hour at 03–05Z, 1–3 an hour through the morning, then a burst of 10 vessels at 11Z and 18 at
  12Z (2,039 flagged positions in that hour), back to 2–7 an hour from 13Z.
- **Cross-sensor match:** the ship centre east of St Petersburg lies 0.5 km from the aircraft spoofed-to point that the
  ADS-B spoofing detector found on 20 Jun 2026 (57 aircraft; `docs/validation/spoofing.md`). That is the same place on
  different days, seen by two independent sensors. What is at that point is unverified.
- **Other detectors** (counts; context in the private event lists): 861 rendezvous pairs, nearly all in ports,
  anchorages or moored together; 215 loitering runs over 6 hours; 1 dark gap over 6 hours; 76 single-vessel circles, read
  as real manoeuvres or vessels without a reported heading; 3 IMO numbers with a bad check digit (one a test transponder);
  48 destination texts classed unusual; the eight printed first were all ferry-route descriptions (the rest unread).
- Still one day, with no ground truth beyond the consistency checks above. Kaliningrad and Narva Bay remain uncovered.

## 1. Data

| Item | Value |
|---|---|
| Feed | MQTT over WebSocket, `wss://meri.digitraffic.fi:443/mqtt`, topics `vessels-v2/+/location`, `vessels-v2/+/metadata`, `vessels-v2/status`. No account. Identified as `noise-floor` (MQTT client id and `Digitraffic-User` header) |
| History | None found. `GET /api/ais/v1/locations` takes `from`/`to`, but returns only each vessel's latest position (checked with one MMSI over 6 h). `GET /api/ais/v1/vessels` returns the latest metadata; the collector stores one snapshot a day |
| Sample | 232,195 position messages (232,032 after removing 163 exact duplicates); 631 vessels with positions; 13,880 metadata messages plus two REST snapshots (892 vessels each); 899 vessels with metadata |
| Rate and health | About 33 position messages a second; 1 connection, no reconnects, no unparseable messages. Compacted Parquet: 4.2 MB of positions for the 1.9 h (about 50 MB a day) |
| Timing | The location `time` field trails our receive time by a median of 0.6 s (99.9th percentile 1.2 s, maximum 3.2 s), so it is the shore reception time, not the transponder's own clock |
| Decimation | None evident. Median per-vessel interval: 10 s when moving (10th percentile 3.1 s) and 179 s when stationary. These match the ITU-R M.1371 Class A reporting rates (10 s at 0–14 kn, faster above; 3 min at anchor or moored) |
| Coverage (positions in the named sea areas, 0.1–99.9 percentile) | 58.9–65.8°N, 18.5–29.6°E: Gulf of Bothnia, Åland and the Archipelago Sea, the Gulf of Finland to about the approaches of St Petersburg, and the northern Baltic Proper. **Kaliningrad: 0 positions. Narva Bay: 0. Gulf of Riga: 2** |
| Vessel mix | By AIS type: cargo 185, passenger 110, tug 81, tanker 62, pilot 58, other 48, unknown 28, search and rescue 20, sailing and pleasure 8. By MMSI country code: Finland 303, Sweden 49, Estonia 44, Russia 32, Portugal (Madeira) 23, Marshall Islands 18, Liberia 17 |

## 2. Method

All thresholds are the plan's starting points (Section 5 of the plan) unless marked. Rule version `ais-0.1 (2026-10-24)`.

| ID | Rule as built | Sample setting |
|---|---|---|
| D7 speed | Consecutive positions more than 1 km apart that need more than the class threshold: 1.5 × the class's typical maximum, and at least 10 kn above it (tanker 30 kn, cargo 37.5, passenger 48, tug 26, high-speed craft 75, unknown 67.5). A track walker keeps the last trusted position and sorts each break into a **spike** (one report, returns), **excursion** (2–8 reports, returns) or **jump** (no return within 8 reports or 1 h; the track continues from the new place). Breaks within 30 min on one vessel are merged into one episode. | same |
| D7 reported speed | Reported SOG above the same threshold, up to 102.2 kn (102.3 means "not available"). SOG and COG normally come from the GNSS receiver, so a spoofed receiver reports them too. | same |
| D7 land | Position more than 3 km inside Natural Earth 10m land (lakes removed), outside H3 res-8 cells used by 3 or more vessels with clean tracks. "Strong" when the vessel also has impossible jumps or speeds, or the position is 20 km or more inland. | same |
| D7 cluster | 4 or more vessels within 50 m of each other in a 10-min bin, with at least 2 of them flagged (jump, impossible SOG or on land). Also: identical coordinates (1e-5°) from different MMSIs in the same minute while moving. | same |
| D7 circles | A track that turns through 720° or more within 30 min, RMS radius 1.5 km or less, median SOG 3 kn or more. Windows sharing a centre (within 2 km) and time are grouped. **Several vessels circling one centre** is the spoofing pattern. One vessel alone is read by whether its heading follows its course: if it does, the manoeuvre is real; if the course swings while the heading doesn't, it is checked for spoofing. | same |
| Victims | For each vessel with flagged positions: the last trusted position before and the first after (where the interference reached it), the centre of its flagged positions (where its receiver was told it was), and a reading. "GNSS interference likely" means over 30% of flagged reports have an impossible SOG, or over half have COG more than 45° from heading. Otherwise it is "shared MMSI, data error or interference: check". | same |
| D5 going dark | Reporting gap over 6 h, starting and ending in H3 res-5 cells (about 250 km²) that kept receiving 3 or more other vessels in at least 75% of the 10-min bins inside the gap. The vessel must also have been heard regularly: 5 or more reports within the gap's length (at most 1 h) before and after. This drops vessels at the edge of coverage. | gap over 0.5 h |
| D3 rendezvous | Two vessels within 500 m, both under 2 kn (unflagged positions), for over 2 h (1-min bins, positions held up to 6 min, holes up to 5 min). Each pair is labelled moored together, port or anchorage zone, near shore (under 2 km from the Natural Earth coastline), or open water. Zones are H3 res-7 cells where, in the sample, 2 or more vessels were moored, 3 or more anchored or 3 or more stationary; res-6 cells with 3 or more anchored; and 2 rings around Natural Earth ports. Pairs under 15 m apart are marked as one hull or rafted (two transponders). | over 20 min |
| D4 loitering | One vessel under 2 kn for over 6 h with no faster report and no gap over 30 min in between; moored runs dropped; same zone labels. | over 1 h |
| D6 identity | Name, call sign, IMO or type changes on one MMSI (live metadata plus the REST snapshot); one IMO on several MMSIs; 7-digit IMO numbers with a wrong check digit. Destination text is sorted into LOCODE or route, port name, generic, service (pilot, channel), statement (crew, owner, armed guards, "no link" and similar) or other. | same |
| GNSS signatures | By region: posAcc and RAIM shares; flag changes along a track; vessels reporting SOG "not available"; positions not available (91/181); positions frozen for 5 min or more while SOG is over 3 kn; COG more than 45° from heading at over 5 kn; reported SOG far from track speed. Compared with the aircraft GNSS map (`data/pnt/year/<day>.parquet`, H3 res 4): the share of aircraft reports with degraded NACp (`bad_nacp_live / aircraft`), summed over the last 14 days available. This is a plain share, not the GPSJam-style score. | same |

Regions are generic sea areas (Gulf of Finland east and west of 27°E, Narva Bay, Archipelago Sea and Åland, Bothnian
Sea, Bothnian Bay, northern Baltic Proper, Gulf of Riga, inland lakes, Kaliningrad), not watch areas.

## 3. Results

### 3.1 Spoofing and GNSS interference (D7)

| Detector | Events | What they are |
|---|---|---|
| Victims, "GNSS interference likely" | 8 vessels | 7 spoofed to the inland circle; 1 tug with 102.2 kn and scattered positions near 60.5°N 28.0°E |
| D7 reported speed | 15 runs, 8 vessels, 2,358 reports | All 8 victims; nothing else in the sample |
| D7 circles | 1 shared-centre group; 8 single-vessel windows | The group is 5 vessels on one circle (median radius 0.65 km, median SOG 76 kn, COG more than 45° off heading in 73% of reports). Of the 8 single windows (4 vessels), 6 had the heading following the course (real manoeuvres) and 2 had no heading reported |
| D7 land | 9 runs: 7 strong, 2 weak | Strong: the 7 spoofed vessels, 27–37 km inside land. Weak: 2 small craft without IMO numbers about 3.2 km "inland" in harbours the Natural Earth coastline misses |
| D7 speed | 6 episodes, 68 breaks before merging | The 102.2 kn tug (63 breaks, positions spread over about 30 km); jumps into and out of the circle (345 and 382 km); a 5.2 km jump and a 1.5 km excursion within the spoofed area; one 1.8 km jump at 352 kn by another vessel at 60.50°N 28.46°E |
| D7 cluster | 1 | 4 spoofed vessels on the circle in the same 10 min. The other 129 tight groups of 4 or more vessels had no flagged members (harbour berths and tug bases, from spot checks) |
| D7 shared fix | 1 | 2 spoofed vessels with identical coordinates on the circle |
| Frozen position while under way | 1 | A spoofed vessel whose reported position stayed fixed for 33 min while it reported 71 kn |

**The circle.** The 7 inland-spoofed vessels' flagged positions centre within about 12 km of one another (6 of them
within 1 km of 57.672°N 32.529°E). Flagged reports carried posAcc 0 and RAIM 0, except posAcc 1 in 15–18% of reports
from two tugs. All 8 affected vessels, by MMSI country code and AIS type: Russia 4 (2 tugs, 2 towing vessels), Hong Kong
1 (cargo), Marshall Islands 1 (cargo), Liberia 1 (cargo), Panama 1 (type not given). Where trusted positions exist, they
are at about 59.99°N 28.57°E, 60.18°N 27.98°E and 60.52°N 28.17°E: eastern Gulf of Finland, in or near Russian waters.
One cargo ship was spoofed for about 2 min around 03:58 UTC, then not heard for 80 min, then heard at a real position
(60.18°N 27.98°E). What is at the circle's centre has not been checked.

**Why this reads as GNSS spoofing of the receivers, not false AIS from the ships.**
- Unrelated vessels with five different MMSI country codes shared one centre at the same time.
- Their headings, which come from the gyro and not GNSS, stayed steady while the GNSS-derived course and speed traced
  the circle.
- The pattern matches what the Finnish Coast Guard has described in the Gulf of Finland since 2024: jamming that
  degrades AIS, with spoofing linked to tankers using Russian ports near St Petersburg (Yle, 31 Oct 2024).

Deliberate AIS falsification by a single vessel shows a different pattern: Windward reported a tanker whose AIS showed
circles off the Gulf of Finland while satellite images showed no ship there (vendor analysis, Oct 2025). Circle-shaped
spoofing around Russian sites was also described in C4ADS's 2019 report "Above Us Only Stars". That report is cited from
memory and was not re-read this session.

### 3.2 GNSS signatures by region, and the aircraft map

| Region | Vessels | posAcc = 1 | RAIM = 1 | Vessels flipping posAcc | Vessels with SOG n/a | COG more than 45° off heading (over 5 kn) | Aircraft reports degraded, 8–21 Oct |
|---|---|---|---|---|---|---|---|
| Gulf of Finland east of 27°E | 48 | 58% | 17% | **25 (52%)** | **5** | 0.2% | **80%** (91 aircraft-hex-days) |
| Gulf of Finland 22.5–27°E | 244 | 55% | 13% | 24 (10%) | 4 | 0.02% | 5% (14,467) |
| Archipelago Sea and Åland | 137 | 64% | 9% | 15 (11%) | 1 | 0.3% | 3% (7,595) |
| Bothnian Sea | 60 | 60% | 11% | 5 (8%) | 0 | 0% | 0.7% (3,565) |
| Bothnian Bay and Kvarken | 80 | 51% | 4% | 13 (16%) | 3 | 0.06% | 1.4% (1,483) |
| Northern Baltic Proper | 43 | 51% | 10% | 4 (9%) | 0 | 0% | 3% (15,862) |
| Inland lakes | 25 | 40% | 33% | 4 (16%) | 2 | 3% | 35% (96) |
| Outside the named areas (mostly the spoofed positions) | 27 | 62% | 17% | 3 | 1 | **47%** | – |

- **posAcc and RAIM shares** vary little between areas (51–64% and 4–17% at sea). They look like fixed transponder
  settings, not interference indicators.
- **Flag flipping does vary.** Over half the vessels in the eastern Gulf changed posAcc during the sample (521 changes,
  3.5% of reports; 511 of them not from the flagged tug), against about 1 in 10 elsewhere (0.1–0.5% of reports). This
  is an indicator only. The fleet mix differs in the east, and the cause of each change (loss of corrections or
  interference) can't be read from AIS.
- **RAIM changes** came almost entirely from a few vessels (one vessel made 916 of 1,199 in the western Gulf) and are
  not useful.
- No positions "not available" (91/181) were received at all. Either transponders don't send them, or the feed drops
  them; this is unverified.
- **Aircraft comparison.** The eastern Gulf is the only covered sea area where the aircraft map is high (80%). The
  aircraft sample there is small: Russian airspace and the border area see few aircraft in adsb.lol. A cell-by-cell
  rank correlation is not meaningful yet. Flagged AIS positions sit in inland Russia or in cells with fewer than 20
  aircraft, and the posAcc share against aircraft degradation gives rho = 0.15 over 80 cells. The aircraft days
  (8–21 Oct) don't overlap the AIS sample (24 Oct).

### 3.3 Behaviour (D3, D4, D5)

| Detector | Events | Breakdown |
|---|---|---|
| D3 rendezvous (over 20 min) | 622 pairs | Moored together 302; port or anchorage zone 301; near shore 18; same hull or rafted (under 15 m) 20, counted within those; **open water 1**: two cargo ships about 28 km off the Bothnian Bay coast for 44 min, one anchored, 234 m apart (median), probably an anchorage too small to form a zone |
| D4 loitering (over 1 h) | 209 runs | 28 outside ports and anchorages. 19 are anchored ships in the Gulf of Finland (11 tankers, 7 cargo, 1 tug) and 4 are anchored cargo ships in the Bothnian Bay, Bothnian Sea and Archipelago Sea. The other 5 were not anchored: a drifting cargo ship, a passenger vessel and 3 small craft without IMO numbers |
| D5 going dark (over 0.5 h) | 2 | 19 gaps over 0.5 h. 13 failed the coverage test. 4 came from vessels heard only now and then, including two in the eastern Gulf heard only 3–5 times in 2 h. The 2 kept are stationary craft without IMO numbers |

The first D4 run showed a field of about 30 ships anchored 1–3 km apart in the central Gulf of Finland (around
59.83–59.92°N 25.5–26.2°E, 18–34 km offshore). It was missed because the res-7 zone rule needed 3 anchored ships in one
5 km² cell, so the res-6 anchorage rule was added. This is a likely waiting area for ships bound to and from Russian
ports. That reading is unverified, and it is exactly where the plan's D3 and D4 should look with multi-day data.

### 3.4 Identity and text (D6)

- **No name, call sign, IMO or type changes** on any MMSI, and no IMO number shared by two MMSIs. Two hours is too short
  to expect any.
- **IMO field:**
  - 642 valid;
  - 247 empty;
  - 7 hold a number that is not 7 digits (domestic craft entering another number);
  - 3 are 7-digit numbers with a wrong check digit, one of them a test transponder.
- **Destination text:**
  - 382 LOCODE or route;
  - 329 port names;
  - 66 service (pilots with their channel);
  - 16 generic ("FOR ORDERS");
  - 45 other, almost all archipelago ferry routes such as "A<>B<>C".
  - **No statements** of the Red Sea kind.

## 4. What works

- **The collector.** It ran for 1.9 h with no reconnects or errors. It also passed a backoff test against an unreachable
  host (10, 20, 40 s and on) and a clean stop through the STOP file.
- **Spoofing detection on several independent signatures at once:**
  - impossible GNSS speed;
  - course detached from heading;
  - positions deep inland;
  - several vessels on one centre;
  - posAcc and RAIM off.
  All of them point at the same vessels and the same circle, with no tuning on this sample.
- **Separating the victims' real area from the spoofed point.** This is the part that transfers to other regions: it
  shows where a spoofer's coverage reaches ships, which the aircraft map can't see at sea level or away from air routes.
- **The noise filters behave:**
  - single-vessel circles whose heading follows the course are read as real manoeuvres;
  - weak on-land hits are labelled as coastline gaps;
  - D5 drops vessels at the edge of coverage.

## 5. Limits

- **1.9 hours, one morning, one weekday.** No rates, no baselines, no diurnal pattern. Every number above can change.
- **No ground truth and no known case scored.** The Baltic cases in the plan (for example Eagle S, December 2024)
  predate any data we have, and Digitraffic offers no history. Validation has to be prospective.
- **Coverage.**
  - Finnish (and contributing) shore stations only.
  - Kaliningrad, Narva Bay and most of the Estonian coast are out of reach. The Estonia–Russia border case in the brief
    can't be tested with this feed.
  - Receiving-station IDs aren't published, so a vessel spoofed the whole time can't be located.
- **Coarse coastline.** Natural Earth 10m puts harbours 1–3 km "inland". The 3 km depth threshold hides real on-land
  errors smaller than that.
- **Zones are learned from the sample itself.** Ports and anchorages that saw fewer than 3 vessels in 2 h count as open
  water.
- **Aircraft comparison is indirect.** It uses different days, H3 res 4, and few aircraft in the eastern Gulf.
- **Unverified points:**
  - what is at the circle's centre;
  - whether Digitraffic filters any messages (for example 91/181 positions);
  - whether the central-Gulf anchored field is a designated anchorage.

## 6. Next steps

1. Run the collector for several days (Section 7) and rerun `tools/ais_detect.py --preset plan` (gap 6 h, rendezvous
   2 h, loitering 6 h). This gives D3–D5 something to work on, and gives hourly spoofing rates.
2. Track the spoofing footprint over time: hourly victims, the trusted positions around each episode, and whether the
   circle's centre moves. Compare with the aircraft hourly table for the same days once those days are processed.
3. Prospective scoring: log each spoofing episode and check it against Finnish Coast Guard and Traficom notices, and
   NGA broadcast warnings (already polled by `collectors/watch.py`).
4. Replace the coastline with OSM land polygons (ODbL) or GSHHG (licence to check) to cut the weak on-land hits, and add
   a ports and anchorages layer (NGA World Port Index, plan Section 3).
5. Write events into the private store planned in Section 7 (SQLite or DuckDB under `private/`) with rule versions.
6. Transfer: `tools/ais_detect.py` needs only mmsi, time, lat, lon, sog, cog, heading, navStat, posAcc and raim, so the
   same code can read aisstream (if its terms allow) for the focus areas, or Norway's open AIS (NLOD, plan Section 3) as
   a second test region.
7. **The ship's own "fix lost" flag (added 25 Oct 2026).** AIS position reports carry a UTC-second field: 0–59 is the
   second of the fix, 60 not available, 61 manual input, 62 dead reckoning, 63 positioning system inoperative
   (ITU-R M.1371). Digitraffic's MQTT messages leave it out; its REST `locations` endpoint has it. The collector now
   polls REST every 10 minutes (`--rest-min`) into `fixflags.parquet`. In one live snapshot (25 Oct 2026, 05:45 UTC),
   6 of 971 vessels reported 62 or 63: four near Vysotsk and the Primorsk approaches (60.0–60.6N, 28.0–28.6E) and two
   Russian-flag ships placed at a false inland position (57.67N 32.52E). Next: count 62/63 by area and hour beside the
   spoofing tests, once a day or more of polls is collected; a ship that reports 63 is telling us its GNSS failed.
8. Housekeeping for the main session:
   - add `paho-mqtt` to the requirements;
   - the registry row `digitraffic-ais` says "CC BY 4.0 (stated)". The terms-of-service page (retrieved 24 Oct 2026)
     confirms CC BY 4.0 and gives the attribution text quoted at the top of this page.

## 7. Running it

From the repository root, with the project venv (`paho-mqtt` is needed for the collector only):

```powershell
# Overnight run (12 h), hidden. Writes data/ais/digitraffic/<UTC day>/ and collector.log there.
Start-Process -WindowStyle Hidden -FilePath .\.venv\Scripts\python.exe -ArgumentList 'collectors\digitraffic_ais.py','--hours','12'

# Is it alive? (worker PID, counts, last message and flush; times in UTC)
Get-Content data\ais\digitraffic\status.json
Get-Content data\ais\digitraffic\collector.log -Tail 5

# Stop early and cleanly (flushes and merges the day's parts, then exits within a few seconds)
New-Item -ItemType File data\ais\digitraffic\STOP

# Detectors on everything collected (preset plan once 12 h or more are on disk; --preset sample for short runs)
.\.venv\Scripts\python.exe tools\ais_detect.py
```

- **Stopping.** Use the STOP file to stop a run. The venv's `python.exe` is a launcher, so the process id that
  Start-Process returns is not the worker's. `status.json` holds the worker PID.
- **Robustness.** The collector:
  - flushes every 5 minutes;
  - reconnects with backoff (10 s to 5 min);
  - drops a connection that has been quiet for 3 min;
  - merges each UTC day's parts at day end and on exit (`--compact-only` merges leftovers after a crash).
- **Detector run time.** 30–70 s for this sample, so roughly 5–10 minutes for a day of data.
- **The PC must stay awake** for the run.

## 8. Sources (retrieved 24 Oct 2026 unless noted)

- Digitraffic, marine traffic APIs (MQTT address, topics, message fields): https://www.digitraffic.fi/en/marine-traffic/
- Digitraffic, instructions (Digitraffic-User header, gzip, rate limits): https://www.digitraffic.fi/en/support/instructions/
- Digitraffic, terms of service (CC BY 4.0, attribution text): https://www.digitraffic.fi/en/terms-of-service/
- Digitraffic Marine API OpenAPI document (version tag 2026.10.12-1; `locations` and `vessels` parameters): https://meri.digitraffic.fi/swagger/openapi.json
- Natural Earth vector v5.1.2 (10m land, lakes, European lakes, ports; public domain): https://github.com/nvkelso/natural-earth-vector
- ITU-R M.1371 (AIS reporting intervals, posAcc, RAIM and SOG codes) and ITU-R M.585 (MMSI formats): https://www.itu.int/rec/R-REC-M.1371 ; https://www.itu.int/rec/R-REC-M.585 (from memory, not re-read this session)
- Yle News, Finnish Coast Guard on GNSS jamming and AIS spoofing in the Gulf of Finland (31 Oct 2024): https://yle.fi/a/74-20121555
- Windward via Hellenic Shipping News, tanker AIS circles off the Gulf of Finland with no ship in satellite images (25 Oct 2025; vendor analysis): https://www.hellenicshippingnews.com/?p=1110298
- C4ADS, "Above Us Only Stars: Exposing GPS Spoofing in Russia and Syria" (2019; from memory, not re-read this session)

## Held-out test (pre-registered 26 Oct 2026, before the run was read)

**Why.** The detector (D7 "GNSS interference likely") was built and described on 24 Oct (1.9 h, then 14 h). The 24-hour
collection that started at **19:51:35 UTC on 25 Oct 2026** and ends about 19:51 UTC on 26 Oct had not been read by any
detector when this section was written. It is the held-out set. Nothing above this line changes after scoring.

**Frozen.** `tools/ais_detect.py` rules version "ais-0.1 (2026-10-24)", unchanged except the `--since`/`--until` time
window added with this section (data selection only). Command:
`python tools/ais_detect.py --days 2026-10-25 2026-10-26 --since 2026-10-25T19:51:00Z --preset plan`.
The ship-reported fix flags come from the same run's REST polls (`fixflags.parquet`, rows from 19:51 UTC on 25 Oct on).

**Development-day reference (24 Oct, 14 h).** 26 of 206 vessels in the Gulf of Finland east of 27°E were flagged
(12.6%); 3 of 813 in the other covered sea areas (0.37%); 26 of 29 flagged vessels with a trusted position were in the
eastern Gulf (90%).

**Definitions.** A flagged vessel is one in the detector's `spoof_victims` list; its area is the region of its trusted
positions (`victims_by_trusted_region`). The eastern Gulf is the region "Gulf of Finland east of 27E"
(59.3–60.8°N, 27.0–30.6°E). Control areas: every other named sea region in the detector (Bothnian Bay and Kvarken,
Bothnian Sea, Archipelago Sea and Aland, Gulf of Finland 22.5–27E, Northern Baltic Proper, Gulf of Riga, Narva Bay);
not "Other" or the inland lakes. Denominators: vessels with positions in each region (`gnss_by_region[...].vessels`).

| # | Check | Pass if |
|---|---|---|
| H1 | False-positive rate in the control areas | flagged ÷ vessels ≤ 1.5% |
| H2 | Concentration where interference is known | ≥ 60% of flagged vessels with a trusted position are in the eastern Gulf, **and** the eastern Gulf's flagged share is ≥ 10× the control share |
| H3 | The ships' own reports (independent of the detector, which never reads them) | Among vessels with positions in the eastern Gulf and at least one REST poll, the share reporting UTC-second 62 (dead reckoning) or 63 (positioning inoperative) at least once is ≥ 3× higher for flagged than for unflagged vessels, with at least 3 flagged vessels reporting 62 or 63 |
| H4 | The aircraft map (independent sensor, area level) | On 26 Oct (the daily table published on 27 Oct; if it isn't out at scoring, 25 Oct, stated), the share of aircraft at jamming scale (`bad_nacp_live` ÷ `aircraft`, summed over hexes whose centres fall in the region box) in the eastern Gulf is ≥ 5× the share over the control-area boxes combined |

**Verdict rule.** Validated (regional: Finnish waters and the approaches) if H1 and H2 pass and at least one of H3 and
H4 passes. Partly validated if H1 and H2 pass but neither H3 nor H4 does. Not validated if H1 or H2 fails. H4 is the
weaker independent check, because the eastern Gulf's aircraft degradation was known before this test; H3 is the
stronger. Reported but not scored: flagged vessels per hour, the spoofed-to centres, and whether the circle near
57.7°N 32.5°E is used again.

## Held-out test: results (scored 26 Oct 2026, 19:55–20:05 UTC)

Scored exactly as pre-registered above: `python tools/ais_detect.py --days 2026-10-25 2026-10-26 --since
2026-10-25T19:51:00Z --preset plan` (with `--quiet`, which only stops the printout), rules "ais-0.1 (2026-10-24)",
unchanged since the pre-registration commit. The capture ran from 19:51:35 UTC on 25 Oct to its 24-hour limit at
19:51:35 UTC on 26 Oct: 2,998,814 position messages, 164,549 metadata messages, 144 REST polls (122,517 rows from 19:51
on), 792 lost-fix reports, no failed polls. The scoring code was checked first against the development day: it
reproduces the reference numbers above (26 of 206, 3 of 813, 26 of 29).

| # | Check | Result | Pass if | Verdict |
|---|---|---|---|---|
| H1 | False positives in the control areas | 1 of 746 vessels flagged (0.13%) | ≤ 1.5% | **Pass** |
| H2 | Concentration in the eastern Gulf | 37 of 38 flagged vessels with a trusted position there (97.4%); 37 of 197 vessels there flagged (18.8%), 140× the control share | ≥ 60% and ≥ 10× | **Pass** |
| H3 | The ships' own reports (UTC second 62 or 63) | Eastern-Gulf vessels with a REST poll: 8 of 40 flagged reported it (20.0%), 12 of 157 unflagged (7.6%): 2.6× | ≥ 3× with ≥ 3 flagged reporting | **Fail** (2.6×) |
| H4 | The aircraft map | Eastern Gulf 85.7% of aircraft at jamming scale against 3.9% over the control boxes: 22× (25 Oct table: the 26 Oct table publishes on 27 Oct, as provided for above) | ≥ 5× | **Pass** |

**Verdict by the rule set in advance: validated (regional: Finnish waters and the approaches).** H1 and H2 pass, and so
does H4. **H3, the stronger independent check, failed narrowly:** flagged ships did report dead reckoning or
positioning inoperative more often than unflagged ships in the same water, 2.6 times as often, but not the 3 times set
in advance. Two readings, neither tested: many unflagged ships in the eastern Gulf were also affected but kept a
plausible track (the detector flags impossible positions, not every affected receiver), which lifts the unflagged
rate; and the field depends on how each ship's AIS unit reports a lost fix. H4 is the weaker check, because the eastern
Gulf's aircraft degradation was known before the test, and its table covers 25 Oct, of which only the last four hours
fall inside the capture.

**Reported, not scored:**

- **Flagged vessels by hour (UTC):** a night peak of 8–15 an hour from 21:00 to 06:00 (23:00–08:00 Finnish time,
  EET since 25 Oct), against 2–8 an hour from 09:00 to 18:00.
- **Where receivers were spoofed to:** the circle near 57.7°N 32.5°E (inland Russia, Tver region; seen on 24 Oct) was
  used again, by 19 ships; one ship each near 59.6°N 33.0°E and 60.5°N 28.0°E.
- **Other readings:** 8 vessels came out "shared MMSI, data error or interference: check", as on the development day;
  they aren't counted as flagged.
- **To add when published:** H4 recomputed on the 26 Oct aircraft table (reported beside the scored result, not
  replacing it).
