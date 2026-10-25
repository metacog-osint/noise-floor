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

## Results (run 25 Oct 2026, 12:58 UTC; code 80dc5a3, thresholds unchanged): checks 1 and 2 pass, check 3 fails

1,855,127 aircraft-hours on the 14 days had 5 or more valid pairs.

| Check | Fixed in advance | Result | Verdict |
|---|---|---|---|
| 1. Control, central Europe | at most 1.0% | 7 of 84,539 aircraft-hours (0.008%) | **Pass** |
| 2. Inside active v0.4 spoofing episodes | at least 5% and at least 5 times the control | 452 of 2,023 (22.3%), about 2,700 times the control | **Pass** |
| 3. Jammed (NACp < 8 on half the pairs), no v0.4 episode, Baltic | at most 3 times the control (0.025%) | 14 of 1,503 (0.93%) | **Fail** |

By the rule written above, **the approach as built ends here**: check 3 failed. Mismatch pairs (not runs) were 0.05% of
pairs in the control and 38.5% inside active episodes. Across all aircraft-hours outside any episode, 774 of 1,851,977
(0.04%) had a run.

Two small changes to the reporting code after the pre-registration, neither touching a threshold: check 1 is computed over
every aircraft-hour in the box, as written above (the code first used only aircraft-hours outside episodes: 6 of 84,506,
0.007%, the same verdict); and check 4's MLAT part wasn't done.

### Exploratory (check 4, no pass or fail): why check 3 failed, and where else runs occur

**The check 3 runs sit at fixed points.** The 14 aircraft-hours' median positions repeat to within about 0.01° across
different aircraft and days, which flown tracks don't do:

| Median position | Aircraft-hours | Days | Note |
|---|---|---|---|
| 54.66–54.70N 31.91–31.95E | 8 | 1 Feb, 24 Feb, 9 May, 16 May | Near Smolensk; the spoofing write-up names Smolensk spoofing as a source of offset tracks |
| 60.59N 28.16–28.24E | 3 | 2 Jan, 15 Jan, 17 Jan | Near Vyborg, by the Finnish border |
| 60.12N 31.38E | 2 | 20 Jun | The spoofed-to point east of St Petersburg seen in ADS-B and AIS (60.12N 31.37E) |
| 55.52N 19.00E | 1 | 15 Aug | Baltic Sea west of Kaliningrad |

So the "jammed, not spoofed" group held aircraft shown at false fixed points that v0.4 didn't turn into episodes: the
check's premise (no v0.4 episode means not spoofed) didn't hold. This explains the failure; it doesn't reverse it.

**Where untagged runs cluster** (5-degree boxes with 200 or more aircraft-hours): 55–60N 35–40E (the Moscow region), 253 of
1,266 aircraft-hours (20%); 55–60N 30–35E, 8 of 308 (2.6%); 60–65N 25–30E, 5 of 749 (0.7%); everywhere else 0.6% or less,
most under 0.25%. In the Moscow box the runs again sit at fixed points: 172 aircraft-hours at 56.0N 37.4E (Sheremetyevo
airport, listed in the spoofing write-up as a new unverified point), 54 at 55.6N 39.7E and 17 at 58.2N 39.0E. They come
mostly from January and February (19–42 aircraft-hours a day) and are rarer from May (0–19).

### What this means

- The inertial check separates known spoofing from controls very sharply (22% against 0.008%).
- It also flags aircraft held at fixed false points that the v0.4 detector misses: near Smolensk, near Vyborg, east of St
  Petersburg and at Sheremetyevo. That makes it a candidate spoofing indicator, not a jamming indicator.
- Next, as a new pre-registration on held-out days: check 3 redefined to exclude aircraft-hours whose positions sit at a
  shared fixed point (the spoofing detector's own shared-point rule), with MLAT disagreement as independent truth where it
  exists. Nothing here goes on the site until that passes and Tom has reviewed it.
