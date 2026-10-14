# Method card: GNSS degradation from ADS-B (PNT processor v1.1)

**Status:** v1.2, 14 Oct 2026. Validation is in `docs/validation/phase1.md`. **Code:** `pipeline/pnt_daily.py`, `pipeline/pnt_analysis.py`.
**Data:** adsb.lol globe_history daily archive, ODbL 1.0. Derived hex data is published under ODbL with attribution.
**Changes:**

- **v1.1:** a peer-based avionics-suspect rule, hourly output, and a capable-aircraft 10 m threshold.
- **v1.2:** per-minute burst counts, plus post-processing (SBAS flag, baselines, bursts).

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
4. **Hex score:** `100 × max(bad − 1, 0) / (good + bad)`, the formula GPSJam publishes. Subtracting one bad aircraft keeps a single faulty aircraft from colouring a hex, including lone aircraft the peer test can't judge.
5. **Public maps:**
   - Colour only hexes with **5 or more aircraft**. Show 3–4 as low coverage, and leave out 1–2.
   - On 16 Oct 2025, hexes with 3–4 aircraft scored red 2.0% of the time, against 1.3–1.4% for 5–49, because one extra bad aircraft is enough to tip them. 78% of hexes with data had 5 or more aircraft.
6. **Outputs:**
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
- **Latching.** Some avionics hold NIC or NACp low until reset after landing, which smears an event downstream in time and space.
- **Coverage.** adsb.lol depends on volunteer feeders. Sparse feeders mean few aircraft per hex and noisy scores, so read `aircraft` alongside `score`. No feeders means no data, not no interference.
- **Location.** A degraded aircraft is somewhere inside the jammer's reach, not at the jammer. Hex patterns along routes show where aircraft flew, not the transmitter.

## Validation

See `docs/validation/phase1.md`:

- **Phase 1:** three test days compared against known, cited hotspots and, by eye only, against GPSJam's maps for the same dates. GPSJam is built on sources whose licences don't allow commercial use, so it is never an input.
- **Phase 1.1:** v1 compared with v1.1, an hourly storm test at both thresholds, and coverage.
