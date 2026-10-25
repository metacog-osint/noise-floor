# Roll against turn rate: an inertial check on GNSS tracks (pre-registered 25 Oct 2026)

**Status:** pre-registration, written and committed before any residual was computed. Results will be added below the
line, without changing anything above it. Written by Claude while Tom was at drill; not yet reviewed by him.

## Why

The spoofing detector (`tools/spoof_day.py`, `docs/validation/spoofing.md`) misses false tracks that move smoothly,
with no jump, and its kinematic test (`kin`) is weak because a spoofed receiver reports a spoofed velocity too, so the
reported velocity agrees with the false positions. A check needs something the spoofer can't touch.

Many aircraft in European airspace also report their **roll angle** (Mode S Comm-B register BDS 5,0, from the inertial
reference and air data, not GNSS), and readsb stores it in the trace beside the indicated airspeed. In a coordinated
turn the true turn rate is set by bank and airspeed: ω = g·tan(roll) / TAS. The ADS-B ground track comes from GNSS. If
the GNSS-derived track turns while the aircraft flies level, or the aircraft banks while the GNSS track runs straight,
the two disagree. A feasibility probe of 1,500 traces on 15 Sep 2026 (counts only, no residuals) found roll on 29% of
points and indicated airspeed on 31%.

## Method, fixed before running

For each ICAO aircraft, consecutive ADS-B (`adsb_icao`) points with a ground track and ground speed, where the later
point also has roll and indicated airspeed (IAS), 8–40 s apart, at 10,000 ft or more (barometric), IAS 150 kt or more,
|roll| at most 45°:

- TAS from IAS and pressure altitude with the ISA density ratio (TAS = IAS·√(ρ0/ρ)); compressibility ignored (a few
  percent at cruise).
- Expected turn rate ω_exp = g·tan(roll) / TAS, in degrees per second.
- Observed turn rate ω_obs = (track change, wrapped to ±180°) / Δt.
- **Mismatch pair:** |ω_obs − ω_exp| ≥ 1.0°/s. (An airliner's turns are 1–3°/s; roll's resolution is 0.18°.)
- **Mismatch run:** 3 or more consecutive mismatch pairs spanning 60 s or more (a single pair can come from a roll sample
  that lags the track by a few seconds).
- **Unit:** aircraft-hour. A rate is the share of aircraft-hours with 5 or more valid pairs that contain a mismatch run.

Code: `tools/roll_turn.py` (to be written after this file is committed).

## Data, fixed before running

The 14 days of 2026 with raw adsb.lol archives on disk and v0.4 spoofing outputs: 2 Jan, 15 Jan, 17 Jan, 1 Feb, 20 Feb,
24 Feb, 8 May, 9 May, 16 May, 20 Jun, 15 Jul, 15 Aug, 15 Sep and 15 Oct 2026. Spoofing episodes from
`data/spoofing_v04/<day>.events.json.gz` as they stand (v0.4).

## Checks, fixed before running

1. **Control.** Central Europe (48–52N, 5–15E) over all 14 days: mismatch rate at most 1.0% of aircraft-hours.
2. **Known spoofing.** Aircraft-hours inside v0.4 *active* episodes (the episode's aircraft, between its start and end,
   anywhere) with 5 or more valid pairs: mismatch rate at least 5 times the control rate and at least 5%. If fewer than
   30 such aircraft-hours have roll data, the check is reported as untestable, not failed.
3. **Not jamming alone.** Aircraft-hours with half or more of their ADS-B points at NACp < 8 and no v0.4 episode, in the
   Baltic (53–61N, 14–32E): mismatch rate at most 3 times the control rate. Jamming degrades positions but shouldn't
   make a GNSS track turn differently from the aircraft, so a high rate here would mean the check reads degradation,
   not falseness.
4. **Exploratory, no pass or fail:** where mismatch runs occur outside v0.4 episodes, by region, and whether MLAT
   (where present) disagrees with those aircraft's positions.

A pass on checks 1–3 would make roll-turn mismatch a candidate indicator for the spoofing detector, to be tested on
held-out days before any use. A failure of check 1 or 3 ends this approach as built.

---

## Results

*(Added after the run.)*
