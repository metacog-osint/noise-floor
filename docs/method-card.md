# Method card: daily GNSS degradation from ADS-B (PNT processor v1)

**Status:** v1, 14 Oct 2026. Validated on three days with open items (`docs/validation/phase1.md`); the avionics-suspect rule changes in v1.1. **Code:** `pipeline/pnt_daily.py`.
**Data:** adsb.lol globe_history daily archive, ODbL 1.0. Derived hex data is published under ODbL with attribution.

## What it measures

The share of aircraft in each H3 hex (resolution 4, about 1,770 km² on average) whose own GNSS position quality was
degraded on a given UTC day. It is an **effect** measure: it shows where receivers on aircraft lost accuracy, not
who caused it or why. On its own it is never evidence of deliberate jamming (see "What it can't tell you").

## How

1. **Reports kept:**
   - ADS-B **version 2** (version 0 reports NUCp, not NIC/NACp).
   - Position type **`adsb_icao`** only. MLAT, TIS-B and ADS-R positions are not the aircraft's own GNSS, and `~` addresses are non-ICAO.
   - **Airborne:** barometric altitude of 1,000 ft or more.
   - **Sampled at most once every 30 s** per aircraft, so slow and fast reporters weigh alike.
2. **Bad report:** NACp < 8 (estimated position uncertainty of 0.05 NM, about 93 m, or worse). NIC < 7 (containment radius of 0.2 NM or more) is tracked alongside.
3. **Bad aircraft in a hex:** 50% or more of its kept reports in that hex are bad.
4. **Avionics suspects:**
   - An aircraft that is bad in 95% or more of its reports, over 3 or more hours airborne, is dropped from every hex for that day.
   - Persistently faulty avionics would otherwise paint whole routes. The daily count is published in the run summary.
5. **Hex score:** `100 × max(bad − 1, 0) / (good + bad)`, the formula GPSJam publishes. Subtracting one bad aircraft keeps a single faulty aircraft from colouring a quiet hex.
6. **Provenance:** each run records the input file names, their SHA-256 (hashed while streaming) and every method parameter in `YYYY-MM-DD.summary.json`.

## What it can't tell you

- **Cause.** Jamming, spoofing, space weather, receiver faults and terrain masking can all lower NACp. Deliberate interference needs a separate corroborant, such as an official warning or operator or government reporting.
- **Spoofing can look clean.** A spoofed receiver may report good NACp at a false position. Spoofing needs separate detectors (Phase 4).
- **Latching.** Some avionics hold NIC or NACp low until reset after landing, which smears an event downstream in time and space.
- **Coverage.** adsb.lol depends on volunteer feeders. Sparse feeders mean few aircraft per hex and noisy scores, so read the `aircraft` column alongside `score`. No feeders means no data, not no interference.
- **Location.** A degraded aircraft is somewhere inside the jammer's reach, not at the jammer. Hex patterns along routes show where aircraft flew, not the transmitter.
- **Time.** A daily figure hides when in the day the degradation happened. Hourly detail comes later.
- **Space weather.** Geomagnetic storms can degrade GNSS widely, especially at high latitudes. Phase 1 validation includes a storm day (18 Oct 2025, max Kp 6.3) to measure this.

## Validation (Phase 1)

There are three test days, two quiet and one disturbed. They are compared against known, cited hotspots and, by eye only, against GPSJam's maps for the same dates. GPSJam is built on sources whose licences don't allow commercial use, so it is never an input. Results are in `docs/validation/phase1.md`.
