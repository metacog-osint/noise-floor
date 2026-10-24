# ADS-B spoofing detector: validation (24 Oct 2026)

**Lane:** adsb-spoofing (planned). **Code:** `tools/spoof_day.py` v0.3, tests in `tests/test_spoof_day.py`. **Data:** 22 full adsb.lol days (ODbL), Feb 2024 – May 2026. **Outputs:** `data/spoofing/` (gitignored; the event files hold ICAO addresses and stay local). **Known answers:** public reporting of where, when and to which points aircraft were spoofed (section 3). It is region-and-period evidence; no source gives day-level ground truth.

## Bottom line

- **Spoofing can be detected from the same archive the jamming processor reads, and it is a different signal.** The detector looks for positions an aircraft can't physically have flown: ground speed under 100 kt at altitude, staying in one spot at altitude, and jumps to a separate track and back. It doesn't rely on NACp: 61% of spoofing episodes kept NACp at 8 or better while the position was false.
- **Known regions light up and quiet controls don't.** Pooled over 22 days, active spoofing was 0.61% of aircraft-hours in the Middle East boxes, 1.04% in the Baltic and western Russia, 1.11% in Myanmar and on the India–Pakistan border, and 0.20% around the Black Sea. Six control regions (25.6 million aircraft-hours) were at 0.002%.
- **The spoofed-to points match the published ones, and they change when the sources say they did.**
  - Beirut airport (within 1 km) was the top point in Feb–Mar 2024; Cairo airport (9 km) on 5 Mar 2024.
  - Amman Queen Alia airport (3 km) took over in Oct 2024, with 488–695 aircraft a day. OPSGROUP dates that switch to 24 Aug 2024.
  - Smolensk (9 km) appears on every day with coverage; Moscow Sheremetyevo (2 km) from 2025.
  - Points on the Kaliningrad coast appear only from Apr 2025, after the Nov 2024 onset that Stanford reports.
  - During the June 2025 Israel–Iran war, aircraft were shown near Bandar Abbas and Asaluyeh. Windward reported ships' AIS positions moved to the same two places in the same week.
- **MLAT, the only independent truth in the data, agrees.** Where MLAT positions exist, 90% of episodes are confirmed (MLAT 20 km or more from the ADS-B position). MLAT also shows what the detector misses: offset tracks with no jump, mostly over Poland and central Europe in 2025–2026. At least 43% of the positions MLAT shows as false are flagged.
- **Spoofing and jamming are mostly separate.** Per hex and day, spoofing share and jamming share correlate weakly (Spearman 0.18–0.38). Every day has hexes with one and not the other. The Black Sea is mostly jammed (13.6% of aircraft-hours, against 0.2% spoofed); Egypt and Jordan are mostly spoofed, with clean NACp.
- **Held-out test passed (24 Oct 2026).** On 12 days fixed by date rule and never used for tuning, all five pre-registered checks passed: controls 0.002%, Middle East 0.39%, Baltic and western Russia 0.81%, MLAT confirmation 91.5%, and the Beirut-to-Amman switch on the 2024 dates (section "Held-out test").
- **Still not published:**
  - Iraq has no adsb.lol coverage and Iran almost none.
  - 24% of episodes can't be located.
  - The control false alarms include one unexplained cluster over Florida.

## 1. Data

22 worldwide days already on disk for other work (the Baltic localizer, the 2024 validation set): 27 Feb, 5–6 Mar and 13–15 Oct 2024; 3, 15, 17 and 25 Apr, 15 and 25 May, 11 (partial), 15 and 21 Jun 2025; 2 and 17 Jan, 1 and 24 Feb, and 8, 9 and 16 May 2026. They weren't chosen for spoofing, which avoids picking days to fit, but they aren't a random sample either.

1,029,634 aircraft-days in all. Each worldwide day took 2.5–5 minutes on 7 workers (84 minutes in all), sharing the PC with other jobs.

## 2. Method (v0.3)

A spoofed receiver can keep reporting good accuracy while its position is false. Stanford found NACp stayed at 8–9 inside the Smolensk spoof circle while NIC swung between 8 and 0 [Lo25]. So the detector tests physics, not accuracy codes. It uses ADS-B positions only (`adsb_icao`), any version, airborne at 1,000 ft or above, every position.

**Indicators that build episodes.** These apply only to "fast" aircraft: emitter category A2–A5 with 10 or more reports at 250 kt or more above 10,000 ft that day, or no category and jet-like speeds above 20,000 ft. Light aircraft, rotorcraft, gliders and balloons are left out.

| Indicator | Rule | What it catches |
|---|---|---|
| slow | Ground speed under 100 kt at or above 10,000 ft baro (18,000 ft for category A2) | A receiver held at a fixed point. Seen: 0.7 kt at FL410 at the Amman point. |
| loiter | Within 3 km of one point for 3 minutes or more, with no coverage gap over 2 minutes, at the same floor | Circle and fixed-point spoofing |
| excursion | The track is split at jumps (20 km or more at an implied 1,200 kt or more) and where slow/loiter status changes. Plausible segments are chained into tracks an aircraft could fly (700 kt plus 5 km), choosing the nearest dead-reckoned position. The track with the most observed time is taken as true. A segment of another track with true-track segments on both sides, at most 2 h apart, is an excursion. | False tracks that move at normal speed. A jump with no return is counted but not used, because it can't say which side is true. |

An **episode** is a run of these positions (gaps under 15 min), at least 2 positions over at least 20 s. Its **victim location** is where the aircraft really was during it:
- the last trusted position before it and the first after (each within 60 min), joined by a great circle and sampled each minute over the episode's own span;
- otherwise one of them, if within 15 minutes;
- otherwise MLAT positions.

Episodes with none of these are *unlocated*. Each located episode is then classed:
- **active:** another aircraft (not post-exposure) was spoofed in the same res-2 cell within an hour. This means spoofing where the aircraft was, and it is the map metric.
- **post-exposure:** no such peer, and the same aircraft had an earlier episode 300 km or more away. The false positions carried on after it left a spoofed area. OPSGROUP warns receivers can stay "contaminated" after spoofing [OG24].
- **isolated:** neither of the above.

**Supporting indicators** (computed and reported, not used to build episodes):
- **geo_flag:** geometric minus baro altitude jumps by 1,000 ft or more within 60 s, or sits at the ADS-B encoding limit (\|diff\| ≥ 3,100 ft), on 2 or more trusted positions in a hex-hour. Seen: geometric altitude exactly 3,150 ft below baro while a receiver was held at Amman.
- **geo_out:** an aircraft's median (geometric − baro) is 1,500 ft or more from the hex-hour median of 4 or more aircraft.
- **kin:** reported speed or track disagrees with the movement between consecutive positions (over 100 kt or 45°).
- **mlat:** an MLAT position within 30 s disagrees with the ADS-B position, moved on by its speed and track, by 20 km or more. MLAT doesn't use GNSS.
- **jam:** a jamming proxy from the same pass (50% or more of trusted version-2 reports at NACp < 8).

**Metric.** Share = active-spoofed aircraft-hours / aircraft-hours, over res-4 hex-hours inside a region box. An aircraft counts once per hex-hour, at its trusted positions or victim locations; false positions are left out of the denominator. Region boxes are in `REGIONS` in the code. A cell counts in the first box that holds it.

## 3. Known cases: what public sources lead us to expect

All retrieved 23 Oct 2026, and used only as comparisons.

| Days | Region | Expectation | Source |
|---|---|---|---|
| Feb–Mar 2024 | Eastern Med, Lebanon, Israel, Egypt (Cairo and Jeddah FIRs), Jordan | Spoofing across whole FIRs. Spoofed-to position mostly Beirut (OLBA); also named are Tel Aviv, Cairo and Amman. | [OG24] |
| Oct 2024 | Same | Nicosia the most-spoofed FIR worldwide. "As of August 24, 2024", spoofed-to position mostly Amman (OJAI). | [OG24] |
| 27 Feb, 5–6 Mar 2024 | Turkish Black Sea coast, Bulgaria, Romania | "Region active since March 2024", spoofed to Simferopol, with a second point "near Krasnodar" from June 2024. More often preceded by jamming. | [OG24] |
| All days | Riga and Vilnius FIRs (airway M864), Helsinki FIR | Spoofed to Smolensk | [OG24], [Lo25] |
| 2024 days | Kaliningrad and the southern Baltic | Jamming, not spoofing. Regular spoofing from Kaliningrad began about 9 Nov 2024. | [Lo26] |
| 2025–2026 | Kaliningrad, out to about 250 km | Regular spoofing: points, and 3/4 circles then a straight line | [Lo26] |
| All days | Moscow and Samara FIRs | Spoofed to Moscow and Yaroslavl | [OG24] |
| Oct 2024 | Iraq, Iran | "Now minor", with sporadic spoofing in Aug 2024 | [OG24] |
| 15, 21 Jun 2025 | Persian Gulf, Strait of Hormuz (war of 13–24 Jun) | Ships' AIS redirected "to areas near Asaluyeh and Bandar Abbas in Iran", about 970 ships a day on 15–18 Jun. This is maritime evidence. | [WW25] |
| From Aug 2024 | Myanmar | Spoofing near Yangon, then more widespread, with small circles | [Lo26] |
| From May 2024 | India–Pakistan border | Daily, spoofed to points along the border | [OG24], [Lo26] |
| Jan 2026 | Iraqi corridor along Iran's western boundary (UL602, UM860, UM688) | GPS interference "including the more insidious spoofing" is "prevalent" | [OG26] |

## 4. Results

### 4.1 Active-spoofed share of aircraft-hours, by region and period

Pooled share in bold, daily range in brackets, %. A dot means too few aircraft (under 200 aircraft-hours a day). Per-day tables come from `python tools/spoof_day.py report <days>`.

| Region | Feb–Mar 2024 | Oct 2024 | Apr–May 2025 | Jun 2025 | Jan–Feb 2026 | May 2026 |
|---|---|---|---|---|---|---|
| East Med (Cyprus, Lebanon coast) | **3.66** (2.31–6.10) | **3.39** (2.74–4.34) | **0.17** (0.07–0.28) | **0.51** (0.00–0.82) | **0.26** (0.00–0.73) | **1.39** (0.64–2.93) |
| Egypt (north), Sinai, Jordan | **0.57** (0.24–1.16) | **7.29** (6.67–7.61) | **0.14** (0.07–0.24) | **0.48** (0.00–0.94) | **0.10** (0.00–0.31) | **0.44** (0.16–0.96) |
| Iraq | · | · | · | · | · | · |
| Persian Gulf | **0.00** | **0.00** | **0.00** | **0.39** (0.00–0.51) | **0.02** (0.00–0.06) | **0.62** (0.56–0.86) |
| Iran (outside the Gulf box) | · | · | **0.00** | **0.75** (0.00–1.63) | **0.00** | · |
| Black Sea, Turkish coast | **0.42** (0.00–1.22) | **0.34** (0.17–0.46) | **0.19** (0.01–0.59) | **0.06** (0.00–0.10) | **0.19** (0.05–0.51) | **0.06** (0.02–0.14) |
| Black Sea, Bulgarian and Romanian coast | **0.00** | **0.21** (0.11–0.40) | **0.29** (0.06–0.83) | **0.12** (0.00–0.18) | **0.36** (0.07–0.84) | **0.10** (0.00–0.27) |
| Baltic east (Kaliningrad, Baltic states) | **0.41** (0.26–0.59) | **0.44** (0.35–0.54) | **1.69** (0.75–3.63) | **4.82** (3.44–6.72) | **2.03** (1.06–5.23) | **2.27** (1.40–4.78) |
| Baltic south-west (sea, Poland west of 19°E) * | **0.15** (0.00–0.48) | **0.16** (0.11–0.19) | **0.64** (0.32–1.00) | **1.37** (0.79–2.04) | **1.62** (0.32–3.93) | **0.79** (0.13–2.15) |
| Western Russia (thin coverage) | · | · | **2.83** (0.54–5.37) | **2.74** (1.80–3.81) | **3.90** (0.71–7.75) | **0.28** (0.00–0.56) |
| Myanmar | **0.00** | **0.00** | **0.77** (0.06–2.34) | **1.52** (0.30–7.39) | **1.54** (0.11–2.92) | **1.51** (0.26–2.38) |
| India–Pakistan border | **0.00** | · | **0.37** (0.00–0.84) | **0.00** | **1.93** (1.56–3.03) | **0.00** |
| *Control:* central Europe (46–52°N, 2–15°E) | **0.00** | **0.00** (0.00–0.01) | **0.01** | **0.00** | **0.03** (0.01–0.06) | **0.00** |
| *Control:* UK and Ireland | **0.00** | **0.00** | **0.00** | **0.00** | **0.00** (0.00–0.01) | **0.00** |
| *Control:* US east, US west, Canada, Australia | **0.00** (daily max 0.01) | **0.00** | **0.00** (max 0.01) | **0.00** | **0.00** (max 0.01) | **0.00** |

\* The south-west Baltic box was added after the first runs showed episodes there. Kaliningrad's reported reach of about 250 km [Lo26] covers most of it.

### 4.2 Spoofed-to points

The top res-6 cell of false positions by distinct aircraft. Distances are to the published point.

| Published point | Found | Days |
|---|---|---|
| Beirut OLBA [OG24] | 1 km | 27 Feb (101 aircraft), 5 Mar (55), 6 Mar 2024 (62) |
| Cairo HECA [OG24] | 9 km | 5 Mar 2024 (74), the top point that day |
| Amman OJAI [OG24] | 3 km | 13–15 Oct 2024 (695, 558, 488), and through 2025–2026 (up to 173 on 9 May 2026) |
| Smolensk [OG24], [Lo25] | 9 km | Every day with coverage (5–22 aircraft) |
| Moscow [OG24] | 2 km from Sheremetyevo (UUEE) | 2025–2026 (14–44) |
| Yaroslavl [OG24] | 45 km | 21 Jun 2025 (15) |
| Simferopol / Belbek [OG24] | 25 km from Belbek | 15 Oct 2024; 2 Jan and 24 Feb 2026 (12–19) |
| Kaliningrad coast [Lo26] | 23–96 km from the city, on the coast and at sea | From 15 Apr 2025 only; none in the 2024 top lists |
| Bandar Abbas, Asaluyeh (ships) [WW25] | 24–26 km and 6 km | 15 and 21 Jun 2025 (14–15 aircraft each) |
| "Near Krasnodar" [OG24] | Near Sochi, in Krasnodar Krai, 50 km from Sochi | 15–17 Apr 2025. It may or may not be the point meant. |
| India–Pakistan border [OG24] | Near Amritsar and Jammu | Jan–Feb 2026 (13–25) |

**Points not in the sources read (unverified):**
- near Ufa, Perm and Veliky Novgorod, east of St Petersburg (59.9°N 30.6°E; 68 aircraft on 1 Feb 2026) and east of Moscow (55.6°N 39.7°E);
- a slow-moving track 100–150 km off the Lebanese coast (33.0–33.4°N, 34.0–34.5°E, about 58 kt);
- southern Myanmar (14.6°N 97.9°E, up to 43 aircraft);
- inland UAE (22.5°N 54.0°E, 47 aircraft on 16 May 2026).

These are where receivers were *shown*, not where a transmitter is [OG24].

### 4.3 Timing checks

- **Beirut to Amman:** Beirut was the top point on all three early-2024 days; Amman was on all three Oct 2024 days. This matches the 24 Aug 2024 switch [OG24].
- **Kaliningrad onset:** active share in the south-west Baltic was 0.00–0.48% on the 2024 days and 0.32–3.93% from Apr 2025. In the eastern Baltic it was 0.26–0.59% against 0.75–6.72%. Kaliningrad points appear only in 2025–2026. The 2024 Baltic episodes are mostly Smolensk victims, which [OG24] reports.
- **Black Sea onset:** the Turkish coast was 0.00% on 27 Feb 2024 and 1.22% on 5 Mar 2024, against "active since March 2024" [OG24]. With 6 Mar back at 0.00%, this is one day of evidence, not a test.
- **Gulf:** 0.00% on every 2024 and spring 2025 day; 0.38–0.51% on 15 and 21 Jun 2025, during the war, and 0.56–0.86% in May 2026. The May 2026 cause wasn't checked.
- **Iraq corridor, Jan 2026 [OG26]:** untested; adsb.lol has under 100 aircraft-hours over Iraq across all 22 days.

### 4.4 False alarms in the controls

151 episodes over 22 days had a victim location in a control box: 66 active, 37 post-exposure, 48 isolated. That is 0.002% of 25.6 million control aircraft-hours for active, 0.003% for all classes.

- **21 of the 66 are one cluster: northern Florida, 6 Mar 2024, 18:07–18:34 UTC.** About 36 aircraft at different true positions (south Georgia, Fort Myers, offshore Atlantic) were shown 15–270 km away, several of them near 29.2°N 82.9°W, with NACp 9–10. This is not a feeder time-shift: the false positions aren't on the aircraft's own tracks. No FAA GPS-test advisory for that date was found. The Eglin advisory EGLNFL 24-02 is for 1–12 Apr 2024. Unexplained; follow-up below.
- **12 are in New Mexico, around White Sands Missile Range** (mostly 3 Apr, 17 Apr and 15 May 2025), mostly with NACp 0. Announced GPS tests are common there; these dates weren't checked.
- **Most of the rest are long-haul aircraft over central Europe, the UK and eastern Canada.** MLAT confirms their positions were false (for example 53 of 53 pairs, 42 of 42). Most had been spoofed earlier near Smolensk or Kaliningrad. So these are real false positions, but post-exposure: two such aircraft in one res-2 cell within an hour corroborate each other. This is the main known leak in the peer rule.
- **Tuning that removed false alarms (in-sample):**
  - v0.2 dropped light aircraft from the excursion test, after duplicate-address GA pairs in the US.
  - v0.3 raised the floor to 18,000 ft for category A2, after skydiving aircraft (Shorts 360, EMB-120), Beechjet/T-1 trainers near Pensacola and a circling King Air. On the 8 days run under both versions, control episodes fell from 76 to 56 (active from 42 to 33), at a cost of 2 of 2,211 known-region episodes.

### 4.5 Which indicators work

Pooled over 22 days, % of aircraft-hours. "0.000" means under 0.0005%.

| Indicator | Middle East | Black Sea | Baltic and W Russia | S Asia | Controls | Verdict |
|---|---|---|---|---|---|---|
| spoofed, active (map metric) | 0.606 | 0.202 | 1.037 | 1.111 | 0.002 | Use |
| slow | 0.562 | 0.219 | 1.073 | 1.252 | 0.000 | Strongest: most episodes, almost no false alarms |
| loiter | 0.380 | 0.007 | 0.140 | 0.653 | 0.000 | Mostly overlaps slow; adds circles |
| excursion | 0.138 | 0.114 | 0.178 | 0.281 | 0.003 | Adds moving false tracks; the main source of control false alarms (post-exposure) |
| geo_flag (supporting) | 0.393 | 0.409 | 0.583 | 0.635 | 0.027 | Useful corroboration: 15–24 times the control rate, and 85% of episodes have a geo hit |
| geo_out (peer altitude outlier) | 0.765 | 0.188 | 0.093 | 0.392 | 0.023 | Not usable: fires at 1.4% in the Gulf box with little spoofing (cause not found) |
| kin (speed/track vs movement) | 0.095 | 0.022 | 0.014 | 0.011 | 0.003 | Weak. Spoofed receivers report a spoofed velocity too (0.7 kt while held at Amman), so the two agree. |
| jam proxy (context) | 2.743 | 13.580 | 6.375 | 4.316 | 0.196 | Matches the jamming tables, Spearman 0.76–0.86 per day |

**NACp on false positions:** 61% of all episodes (6,460 of 10,542) had false positions mostly at NACp 8 or better. By region of active episodes: Egypt and Jordan 87% clean, the eastern Med 75%, the Baltic about 50% (spoofing mixed with jamming there [Lo26]).

### 4.6 MLAT as independent truth

adsb.lol rarely has MLAT and ADS-B for the same aircraft at the same time, except where readsb rejects ADS-B positions, which is often during spoofing. MLAT pairs were common only over Europe in 2025–2026.

- **Episodes with an MLAT pair within 30 s:** 1,072, of which 963 (90%) are confirmed.
- **ADS-B positions the detector called false:** 6,718 pairs, of which 91.5% disagree with MLAT by 20 km or more.
- **ADS-B positions it trusted:** 36,101 pairs, of which 22.8% disagree. These are misses, concentrated over Poland, Czechia and Slovakia, southern Finland and Germany in 2025–2026: tracks offset by tens of km with no jump, after Kaliningrad or Smolensk spoofing. In the US and Australian controls, 3–10% of trusted pairs disagree, which is a rough floor for MLAT error.
- **Recall:** at least 43% of the positions MLAT shows as false are flagged (6,147 against 8,239). That figure counts positions; a spoofed *area* is found when one aircraft there is flagged.

### 4.7 Spoofing against jamming

Using the jamming processor's daily tables (13 days: the 2024 set and the 2026 backfill), res-4 hexes with 30 or more aircraft:
- Spearman correlation per day between active-spoofed share and jammed share (`bad_nacp_live`): 0.18–0.38.
- Each day: 10–104 hexes spoofed 2% or more with jamming under 10%; 12–55 jammed 25% or more with spoofing under 0.5%; 5–80 with both.
- So the two layers carry different information, as the lane plan assumed. The Apr–Jun 2025 days have no jamming tables (the backfill starts Oct 2025).

## Verdicts

| # | Check | Result | Verdict |
|---|---|---|---|
| 1 | Known regions above controls | Active share 0.20–1.11% in the four known groups against 0.002% in the controls | **Pass** |
| 2 | Spoofed-to points match published ones | Beirut 1 km, Amman 3 km, Cairo 9 km, Smolensk 9 km, Sheremetyevo 2 km, Belbek 25 km, Kaliningrad coast; Gulf points 6–26 km from the ship-reported ones | **Pass** |
| 3 | Timing matches the sources | Beirut to Amman (2024); Kaliningrad onset (2024 against 2025); Gulf during the June 2025 war | **Pass**. Black Sea onset is one day only. |
| 4 | False alarms in controls | 0.002% of aircraft-hours. 66 active episodes: one unexplained Florida cluster (21), probable White Sands tests (12), the rest post-exposure | **Pass, with an open item** (Florida) |
| 5 | Independent check (MLAT) | 90% of episodes confirmed where MLAT exists; at least 43% of false positions caught | **Pass on precision; recall limited** (offset tracks without jumps are missed) |
| 6 | Indicator choice | slow (with loiter and excursion) carries the detector; geo_flag corroborates; geo_out and kin don't work as built | Decided |
| 7 | Spoofing distinct from jamming | Spearman 0.18–0.38 per day | **Pass** |
| 8 | Iraq, Iran, Jan 2026 corridor | No coverage | **Untested** |

## 5. Limits

- **In-sample tuning.** v0.1 to v0.3 were tuned on these 22 days (light-aircraft exclusions, the A2 floor, victim spans, the peer rule). The numbers above are not a held-out test.
- **Coverage.** No adsb.lol coverage over Iraq, very little over Iran and Russia, and MLAT almost only in Europe. 24% of episodes (2,479) have no victim location, mostly aircraft shown at Russian points while over Belarus or Russia, or entering coverage already spoofed. They are listed but not mapped.
- **Victim locations are estimates.** They are interpolated between trusted positions up to 60 minutes apart, so they are good at res-2, rough at res-4.
- **The peer rule leaks.** Post-exposure aircraft whose earlier exposure wasn't seen can corroborate each other over busy airspace downstream of a spoofed area (central Europe in 2025–2026).
- **Misses.** Realistic false tracks without a jump, and slow offsets, aren't caught unless MLAT is present. Spoofing on approach below 10,000 ft is caught only as an excursion.
- **Self-reported fields.** Emitter category, ground speed and geometric altitude come from the aircraft. A wrong category can put a slow aircraft into the test.
- **Unverified.** The Florida cluster and the White Sands dates. Points that don't match a published place are leads, not findings.

## Held-out test (pre-registered 24 Oct 2026, about 07:00 UTC, before any of these days was processed)

**Method frozen** at v0.3 (`tools/spoof_day.py` as committed in 898da3f). No parameter changes until the test is scored.

**Days, by date rule:** the 20th of February, June and October from 2024 to June 2026 (2024-02-20, 2024-06-20, 2024-10-20,
2025-02-20, 2025-06-20, 2025-10-20, 2026-02-20, 2026-06-20), plus four days already on disk that were chosen by date for the
localizer test and never used for spoofing (2025-04-10, 2025-04-20, 2025-05-10, 2025-05-20). None of the twelve was used to
build or tune this detector.

**Checks, with the in-sample value (22 days) for reference:**

| # | Check | Pass if | In-sample |
|---|---|---|---|
| H1 | Controls: pooled active share of aircraft-hours in the six control regions | ≤ 0.01% | 0.002% |
| H2 | Known regions: pooled active share in the Middle East and in the Baltic and western Russia groups | each ≥ 0.2% and ≥ 20× the control share | 0.61%, 1.04% |
| H3 | MLAT: episodes confirmed by MLAT, of those MLAT can test | ≥ 75% | 90% (963 of 1,072) |
| H4 | Spoofed-to points: top res-6 cells per day with ≥ 5 aircraft that lie within 25 km of a named published point | ≥ 25% | 31% (33 of 106) |
| H5 | Timing: in the eastern Mediterranean, the named point with the most aircraft among each day's top cells | Beirut on 20 Feb and 20 Jun 2024, Amman on 20 Oct 2024 (OPSGROUP dates the switch to 24 Aug 2024) | Beirut Feb–Mar 2024, Amman Oct 2024 |

H4 is deliberately modest. In-sample, most of the top spoofed-to cells (73 of 106) aren't within 25 km of any named point, so
"matches the published points" holds for the top point of the main regions, not for every cluster.

**Result (scored 24 Oct 2026, about 09:40 UTC): all five checks pass.**

| # | Pass if | Held-out (12 days) | Result |
|---|---|---|---|
| H1 | ≤ 0.01% | 0.002% of 15.2 million control aircraft-hours | Pass |
| H2 | each ≥ 0.2% and ≥ 20× controls | Middle East 0.39% (194×); Baltic and western Russia 0.81% (407×) | Pass |
| H3 | ≥ 75% | 530 of 579 MLAT-testable episodes confirmed (91.5%) | Pass |
| H4 | ≥ 25% | 25 of 63 top cells within 25 km of a named point (40%) | Pass |
| H5 | Beirut, Beirut, Amman | Beirut airport 1 km (40 aircraft) on 20 Feb 2024; Beirut 1 km (414) on 20 Jun 2024; Amman airport 3 km (245) on 20 Oct 2024 | Pass |

- The known regions read lower than in-sample (0.39% against 0.61%, 0.81% against 1.04%), but far above the pass marks.
- **Points seen on held-out days that the published list doesn't name** (unverified, for follow-up):
  - near Moscow Sheremetyevo (2 km), on four of the six days from May 2025 (the published source names only Moscow);
  - a point near Dawei, Myanmar, on seven days (67 km from the town);
  - points in the Tel Aviv area on 20 Jun 2025, during the Israel–Iran war, beside the Asaluyeh point (6 km) that Windward reported for ships;
  - a new point east of St Petersburg on 20 Jun 2026 (57 aircraft). On 24 Oct 2026 the AIS lane found a ship in the eastern
    Gulf of Finland shown 0.5 km from the same point (`docs/validation/ais-baltic.md`): two independent sensors, same place.
- What the test does and doesn't show: the frozen method generalises to days it never saw, at region level and for the main published points. It doesn't test position accuracy beyond the MLAT cross-check, or offset-track spoofing, which v0.3 misses.

## Control-area episodes against FAA advisories (checked 24 Oct 2026)

The project's FAA file (`data/declared/faa_gps_tests.json`) starts in September 2025, so the in-sample control episodes were
checked against the FAA SPANS advisories directly.

- **White Sands area: 12 of 14 episodes fall inside announced test windows.**
  - 17 Apr 2025, 19:16–19:42Z (2 episodes): WSMRNM 25-08 Rev 1, 17 Apr 1830–2059Z.
  - 15 May 2025, 03:07–05:40Z (4): WSMRNM 25-06 Rev 2, 12–17 May daily 0300–0659Z.
  - 15 May 2025, 08:33 and 10:16Z (2): WSMRNM 25-05 Rev 2, 12–17 May daily 0700–1130Z.
  - 15 May 2025, 19:07–20:01Z (4): WSMRNM 25-30, 5–16 May daily 1830–2230Z.
  - 3 Apr 2025, 08:25–08:51Z (2): no advisory found. WSMRNM 25-41 lists 13–15 March and 6–9 April, not 3 April.
- **Northern Florida, 6 Mar 2024, 17:51–18:34Z (23 episodes): no advisory found** (searched for Jacksonville, Eglin and
  Okaloosa; the nearest is EGLNFL 24-02, 1–12 April 2024). About 20 aircraft jumped to separate tracks within the same few
  minutes (18:20–18:24Z), mostly with good NACp (9–10) and no MLAT to cross-check.
  - **Resolved (24 Oct 2026): a stale-data replay, not spoofing.** In the raw traces, 34 of the 37 flagged positions lie
    within 2 km of the same aircraft's own position 17–26 minutes earlier (the other 3 within 2.1–3.7 km). Something in
    the feed re-sent positions about 20 minutes old for aircraft over northern Florida. No episodes elsewhere started in
    the same minutes, so it was local, not an aggregator-wide stall.

Advisories (retrieved 24 Oct 2026): WSMRNM 25-08 Rev 1 (https://www.faasafety.gov/files/notices/2025/Apr/WSMRNM_25-08_GPS_Flight_Advisory_Revision_1.pdf);
WSMRNM 25-06 Rev 2 (https://www.faasafety.gov/files/notices/2025/May/WSMRNM_25-06_GPS_Flight_Advisory_(Revision_2).pdf);
WSMRNM 25-05 Rev 2 (https://www.faasafety.gov/files/notices/2025/May/WSMRNM_25-05_GPS_Flight_Advisory_(Revision_2).pdf);
WSMRNM 25-30 (https://www.faasafety.gov/files/notices/2025/Apr/WSMRNM_25-30_GPS_Flight_Advisory.pdf);
WSMRNM 25-41 (https://www.faasafety.gov/files/notices/2025/Mar/WSMRNM_25-41_GPS_Flight_Advisory.pdf, search summary only);
EGLNFL 24-02 (https://www.faasafety.gov/files/notices/2024/Mar/EGLNFL_24-02_GPS_Flight_Advisory.pdf, search summary only).

## 6. Next

1. **Held-out test, rules fixed first:** v0.3 frozen, on days not used here (for example from the Oct 2025 – Oct 2026 backfill period), scored on the same checks.
2. **Florida, 6 Mar 2024:** search the FAA SPANS archive and NOTAMs around that date (Navy and Air Force exercises in the Jacksonville area). Check the White Sands dates against the advisories (`pipeline/faa_gps_tests.py --crawl`).
3. **MLAT-anchored offset detector:** where MLAT exists, flag runs of ADS-B positions offset from MLAT. Keep a share of MLAT out as the check.
4. **Post-exposure:** trace an aircraft back to its last exposure across days, and look at the A350/A380 latching lead (`docs/validation/phase1.md`) with the spoofing episodes.
5. **Pipeline and map:** only after the held-out test. A res-2 map of active-spoofed share, separate from jamming, with spoofed-to points as a second layer. Events without ICAO addresses.
6. **geo_out in the Gulf:** find why it fires there (aircraft mix, reference mismatch, or altitude-only spoofing).

## Sources

- [OG24] OPSGROUP and the 2024 GPS Spoofing Workgroup, *GPS Spoofing: Technical Guide* (Sep 2024), regions as of Aug 2024: https://ops.group/dashboard/wp-content/uploads/2024/09/GPS-Spoofing-Technical-Guide-WG2024-OG2.pdf. It also gives about 300 spoofed flights a day in Jan 2024, about 1,500 a day by Aug 2024, and 41,000 flights from 15 Jul to 15 Aug 2024.
- [Lo25] Lo, Liu, Ibrahim, Chen, Walter, "Observations of GNSS Spoofing in Russia in 2023–2024", ION ITM 2025: https://web.stanford.edu/group/scpnt/gpslab/pubs/papers/Lo_ION_ITM_2025_Russia_Spoofing.pdf
- [Lo26] Lo, Liu, Ibrahim, Chen, Akos, Walter, "Global Incidents of Aviation Spoofing in 2024–2025 Detected with Automatic Dependent Surveillance Broadcast", ION ITM 2026: https://web.stanford.edu/group/scpnt/gpslab/pubs/papers/Lo_ION_ITM_2026_Observations_of_Spoofing.pdf
- [OG26] OPSGROUP, "Crisis in Iran: elevated airspace risk", 20 Jan 2026: https://ops.group/blog/crisis-in-iran-elevated-airspace-risk/
- [WW25] Windward, "Middle East on the precipice: GPS jamming in the Arabian Gulf and Strait of Hormuz disrupts 970 ships daily", 19 Jun 2025: https://windward.ai/blog/middle-east-on-the-precipice-gps-jamming-in-the-arabian-gulf-and-strait-of-hormuz-disrupts-970-ships-daily/ (a commercial vendor's blog; maritime AIS)
- FAA SPANS notice 13512, "Flight Advisory – Eglin Air Force Base, FL" (tests 1–12 Apr 2024), published 27 Mar 2024: https://www.faasafety.gov/SPANS/noticeView.aspx?nid=13512

Day-level public trackers (GPSJam, rfi.stanford.edu, the SkAI/ZHAW tracker) are non-commercial or unclear in licence and weren't used.

## Reproduce

```bash
# each day: the adsb.lol archive parts in data/raw/trace_box/<day>/ (or --raw <folder>); about 3-5 min per day
python tools/spoof_day.py run 2024-02-27 2024-03-05 2024-03-06 2024-10-13 2024-10-14 2024-10-15 \
  2025-04-03 2025-04-15 2025-04-17 2025-04-25 2025-05-15 2025-05-25 2025-06-11 2025-06-15 2025-06-21 \
  2026-01-02 2026-01-17 2026-02-01 2026-02-24 2026-05-08 2026-05-09 2026-05-16
python tools/spoof_day.py report 2024-02-27 2024-03-05 ...   # every table in section 4, per day and pooled
python tests/test_spoof_day.py
```
