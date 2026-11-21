# The 20 Nov 2026 "major" event across central Europe: what it was

**Event:** `noisefloor-event-2026-11-20-1`, graded major: 13 res-2 regions, 29 region-hours, 02:00-06:59 UTC, peak severe
share 44.6%, excess 40.4 points, A350/A380 share of its degraded counts 0.516. Checked 21 Nov 2026 from the published
release files and the adsb.lol archives for 19 and 20 Nov. Only counts were kept; no aircraft address left the run.

## Finding

**Two things overlap, and neither is one jammer across 20 countries.**

1. **The major grade rests mostly on A350s and A380s**, the reporting pattern in `phase1.md` (verdicts 43 and 48). With
   their degraded counts left out of the day and of its 14-day baseline, the peak excess falls from 40.4 to about 13.3
   points, which is notable. Their numbers were ordinary: 42 of 86 degraded in the area on 20 Nov, 38 of 74 on 19 Nov.
   Of the 42, 27 were already degraded before they entered it, a median 1.6 hours and 1,160 km earlier. Among all
   aircraft types that arrived degraded, the commonest first places were the Turkish-Georgian Black Sea coast and the
   Caucasus.
2. **Spoofing to the Lima ring was present and accounts for part of the real rise** (`spoofing-lima.md`). Among other
   aircraft types, 74 were degraded on 20 Nov against 34 on 19 Nov. The Lima signature marks 18 of those 74, and none of
   the 34. The other 22 of the extra 40 remain **unexplained**.

**Cause: partly identified.** Lima-ring spoofing is the supported explanation for part of the rise in other types. The
rest is unverified. Spoofed-to points show what receivers were told, not where a transmitter is, so this attributes
nothing to any source.

## Evidence

| Check | 20 Nov | 19 Nov (control) |
|---|---|---|
| Aircraft in the area, 02:00-06:59 UTC | 1,254 | 1,151 |
| Aircraft with the Lima signature | 57 (none A350/A380) | 4 |
| A350/A380 degraded | 42 of 86 | 38 of 74 |
| Other types degraded | 74 of 1,168 | 34 of 1,077 |
| Of those, with the Lima signature | 18 | 0 |
| Event regions above their usual spoofing level (`level2`) | 4 of 13 | 0 of 13 |

**Signature**, taken from `spoofing-lima.md` before it was counted here: a position within 5 km of Lima (-12.043, -77.050)
or the Romanian ring (47.959, 23.276), or a reported ground speed of 105-113 kt at or above 25,000 ft on at least two
reports within 3 minutes. ADS-B and MLAT positions both count. 34 of the 57 marked aircraft were first marked in the
05 UTC hour.

- **Across days:** the detector's Lima cluster held 46 episodes on 17 Nov and 25 on 20 Nov, and 8 or fewer on each of the
  other 13 days from 6 to 19 Nov. The share of other aircraft types with severe error in these regions and hours was
  2.57% on 20 Nov, against a 14-day median of 1.18% and a previous high of 2.02% on 17 Nov.
- **No single footprint:** 83% of degraded reports had nearby aircraft (within 100 km and 2 minutes, A350/A380 left out)
  that were mostly healthy. Of the degraded aircraft that first degraded inside the area, no more than 3 did so within
  100 km and 10 minutes of each other.
- **Space weather:** GFZ Kp was 1.67 or lower from 21:00 UTC on 19 Nov to 09:00 UTC on 20 Nov (preliminary values).
- **EGNOS:** Noisefloor's area check flagged no hour on 20 Nov. No EGNOS service notice for the date was found.
- **GPS:** no NANU covering 20 Nov was found. The newest in the CelesTrak mirror is dated 11 Nov, and NAVCEN's page
  refused the request, so this is an absence of evidence only.

## Limits

- This is a check after the fact on one event, with one control day at aircraft level. It is not a held-out test.
- Leaving out A350/A380 uses the published hourly tables, which count only their degraded aircraft, so their healthy
  aircraft stay in the denominator. The 13.3 is therefore approximate.
- The archive drops many false positions for these flights (`spoofing-lima.md`), so 18 is a lower bound on the degraded
  aircraft affected by this spoofing.
- **Shared receivers could not be tested.** The archive carries no receiver identity. The burst near Belgrade
  (03:59-04:51 UTC) and the one near Doha (04:39-04:52 UTC) are 3,668 km apart, and nothing here links them.

## What this does not change

The grade stays as it is. `event-floor.md` tested an A350/A380 demotion (variant H), and it failed because it also
demotes real events in validated hotspots. H would make this event notable, but one event is no reason to adopt a rule
that failed its test. Any new rule needs its own pre-registered, held-out check.
