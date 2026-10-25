# Method card: GNSS degradation from ADS-B (PNT processor v1.4)

**Status:** v1.4, 14 Oct 2026. Validation is in `docs/validation/phase1.md`. **Code:** `pipeline/pnt_daily.py`, `pipeline/pnt_analysis.py`.
**Data:** adsb.lol globe_history daily archive, ODbL 1.0. Derived hex data is published under ODbL with attribution.
**Changes:**

- **v1.1:** a peer-based avionics-suspect rule, hourly output, and a capable-aircraft 10 m threshold.
- **v1.2:** per-minute burst counts, plus post-processing (SBAS flag, baselines, bursts).
- **v1.3:** a latching tag, with live counts kept separate from latched aircraft.
- **v1.4:** a post-exposure tag replacing latching (catches intermittent degradation), plus type counts.

## What it measures

The share of aircraft in each H3 hex (resolution 4, about 1,770 km² on average) whose own GNSS position quality was
degraded, per UTC day and per UTC hour. It is an **effect** measure: it shows where receivers on aircraft lost
accuracy, not who caused it or why. On its own it is never evidence of deliberate jamming (see "What it can't tell you").

There are two thresholds, because they answer different questions:

| Measure | Threshold | What it is for |
|---|---|---|
| **Gross** (`bad_nacp`, `score`) | NACp < 8: estimated position uncertainty of 0.05 NM (about 93 m) or worse | Jamming-scale loss. Directly comparable with GPSJam's maps. NIC < 7 (`bad_nic`) is tracked alongside. |
| **Accuracy** (`capable`, `cap_bad_acc10`) | NACp < 10 (uncertainty of 10 m or worse), counted **only for aircraft that reported NACp ≥ 10 at least once that day** | Finer degradation, including space weather. Storms degrade accuracy to tens of metres, rarely past 93 m (Phase 1.1 storm tests). Many aircraft without SBAS report NACp 9 all the time, so the raw NACp < 10 share (`bad_acc10`) mostly measures fleet equipage. Use the capable share. |

## How

1. **Reports kept:**
   - ADS-B **version 2** (version 0 reports NUCp, not NIC/NACp).
   - Position type **`adsb_icao`** only. MLAT, TIS-B and ADS-R positions are not the aircraft's own GNSS, and `~` addresses are non-ICAO.
   - **Airborne:** barometric altitude of 1,000 ft or more.
   - **Sampled at most once every 30 s** per aircraft, so slow and fast reporters weigh alike.
   - **Inside the UTC day** being processed.
2. **Bad aircraft in a hex (or a hex-hour):** 50% or more of its kept reports there are bad on that measure.
3. **Avionics suspects (peer test):**
   - An aircraft is dropped from every hex for the day if **80% or more of its reports are gross-bad** and it is bad **where its peers are fine**.
   - "Where its peers are fine" means this: of the hex-hours where it is bad and at least two other aircraft are present, 75% or more have fewer than 25% of those others bad. At least three such hex-hours are needed to judge.
   - Faulty avionics are bad among healthy neighbours, while a jammed flight is bad among bad neighbours and stays in. (v1 dropped any aircraft bad for 95% of a 3-hour span, which also removed some genuinely jammed flights.)
   - Each day's suspects are listed in the run summary by rough centre point, hours and type designator, with no identifiers.
4. **Post-exposure (v1.4, replacing v1.3 latching):**
   - Some avionics stay degraded after leaving interference. They may be latched, or flip on and off for hours (21–25 Oct 2025: mostly A350s, first degraded over the eastern Black Sea).
   - An aircraft's **exposure point** is its first hex-hour with gross-bad reports where its peers were bad too (2 or more peers, 25% or more of them bad). That marks genuine interference.
   - Any **later** hex-hour with gross-bad reports **300 km or more** from the exposure point, where peers are mostly good, is **post-exposure**: evidence of earlier exposure, not new interference there. No continuity is required.
   - A second genuinely jammed area later in the flight has bad peers, so it stays live.
   - Post-exposure reports are counted in `latched` and left out of `bad_nacp_live` and `score_live`. `bad_nacp` and `score` stay raw and comparable with GPSJam.
   - The run summary records exposure regions (H3 res 2), post-exposure counts by aircraft type, and type counts for all aircraft.
   - Analysis (anomalies, bursts) and the suspect test use live reports.
5. **Hex score:** `100 × max(bad − 1, 0) / (good + bad)`, the formula GPSJam publishes. Subtracting one bad aircraft keeps a single faulty aircraft from colouring a hex, including lone aircraft the peer test can't judge.
6. **Public maps:**
   - Colour only hexes with **5 or more aircraft**. Show 3–4 as low coverage, and leave out 1–2.
   - On 16 Oct 2025, hexes with 3–4 aircraft scored red 2.0% of the time, against 1.3–1.4% for 5–49, because one extra bad aircraft is enough to tip them. 78% of hexes with data had 5 or more aircraft.
7. **Outputs:**
   - `YYYY-MM-DD.parquet`: daily per hex.
   - `YYYY-MM-DD.hourly.parquet`: per hex and UTC hour.
   - `YYYY-MM-DD.minute.parquet` (v1.2): per hex and minute, the number of aircraft with at least one gross-bad report. It holds non-zero rows only and is used for timing short bursts, which the hourly majority rule dampens.
   - `YYYY-MM-DD.summary.json`: the input file names, their SHA-256 (hashed while streaming), counts and every method parameter.

## Post-processing (`pipeline/pnt_analysis.py`, v1.2)

- **SBAS service flag.** For each SBAS service area (approximate boxes) and UTC hour, an hour is flagged as an outage when 60% or more of 10 m-capable aircraft across the whole area are below 10 m, and as degraded at 35% or more. GFZ Kp of 5 or more labels the hour as storm; otherwise it is a probable service problem. Flagged hours don't count toward 10 m baselines.
- **Baselines and anomalies.** Each H3 res-2 region and UTC hour is compared against the median of the same hour over up to 14 earlier days within 30 days, with at least 5 needed. An anomaly is a share above the median by more than the larger of a floor (2 points gross, 10 points capable) and 4 × MAD, with at least 30 aircraft-hex-hours.
- **Bursts.** For each H3 res-2 region, a burst is a run of 3 or more minutes in which the count of aircraft with a gross-bad report reaches the larger of 5 aircraft and the day's median + 5 × MAD.

## What it can't tell you

- **Cause.** Jamming, spoofing, space weather, receiver faults and terrain masking can all lower NACp. Deliberate interference needs a separate corroborant, such as an official warning or operator or government reporting.
- **Spoofing can look clean.** A spoofed receiver may report good NACp at a false position. Spoofing needs separate detectors (Phase 4).
- **SBAS outages.** If EGNOS, WAAS or another SBAS goes down, capable aircraft drop to NACp 9 across its whole service area. The 10 m metric then reads high everywhere, as it did in Europe during EGNOS's 13–17 Oct 2025 loss of signal. Check SBAS service status before reading the 10 m metric. The 93 m metric is unaffected.
- **Short bursts.** The hourly majority rule (50% of an aircraft's reports in the hour) dampens events of a few minutes. Use counts, not shares, for timing until a per-minute counter exists.
- **Post-exposure.** Since v1.4, aircraft still degraded after leaving interference are tagged (step 4). The tag needs peers both at the exposure point and later, so in sparse coverage such an aircraft can still count as live.
- **Strong jamming removes aircraft.** An aircraft that loses GNSS completely can stop sending a usable ADS-B position, so it drops out of the counts instead of counting as degraded. On 9 May 2026, three in four aircraft crossing the southern Baltic lost their position across it, while the daily share was computed over the few that kept one (verdict 34). Read the share with the aircraft count, or use the map's "Fewer aircraft than usual" view (each hex's count against its 14-day median). Some types, notably the A350, keep broadcasting a degraded position where most go dark, so heavy-jamming days over-represent them.
- **A350s and A380s over-report degradation.** In 19 days of raw traces they kept broadcasting positions flagged as poor where other types went dark (89% of A350 crossings seen on jammed days, against 43% for narrowbodies), and their degraded episodes lasted 4–8 times longer (median 8–17 minutes against 2). Australia reported to ICAO in June 2025 that on these types the AESS sets NACp to zero when the ADIRU flags one satellite as degraded, even when the position is valid (CNS SG/29 IP/05). Their reports can dominate shares and minute bursts far from any jammer, notably in the overnight long-haul wave (verdict 43). Inside real jamming they are among the best witnesses, because they keep reporting while other types go dark, so removing them by type also removes real detections (compared on the 20 validated days, 24 Oct 2026). Instead, from 25 Oct 2026 the processor writes `heavy_live` (hourly, daily) and `heavy` (minute), and every burst and 93 m anomaly event carries `heavy_share`, the share of its live gross-bad aircraft that were A350s or A380s.
- **SBAS areas few aircraft use.** Over India (GAGAN) and Australia/New Zealand (SouthPAN) the SBAS flag fires on most days, because most aircraft there don't use those services. The 10 m measure is unreliable there; the 93 m measure is unaffected.
- **Coverage.** adsb.lol depends on volunteer feeders. Sparse feeders mean few aircraft per hex and noisy scores, so read `aircraft` alongside `score`. No feeders means no data, not no interference.
- **Location.** A degraded aircraft is somewhere inside the jammer's reach, not at the jammer. Hex patterns along routes show where aircraft flew, not the transmitter.

## Validation

See `docs/validation/phase1.md`:

- **Phase 1:** three test days compared against known, cited hotspots and, by eye only, against GPSJam's maps for the same dates. GPSJam is built on sources whose licences don't allow commercial use, so it is never an input.
- **Phase 1.1:** v1 compared with v1.1, an hourly storm test at both thresholds, and coverage.
