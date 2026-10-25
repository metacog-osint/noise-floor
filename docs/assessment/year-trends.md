# A year of GNSS degradation: what changed, when, and where (1 Oct 2025 – 21 Oct 2026)

*Written 25 Oct 2026 from the daily tables (383 days with data; adsb.lol has no archive for 31 Dec 2025 or 6 May 2026).
Code: `tools/year_trends.py`; output `data/pnt/year_trends.json` (aggregates, ODbL 1.0). Automatic analysis, not yet
reviewed by a person beyond the checks below.*

## Summary

- **Gulf of Finland / Estonia–Russia border: degradation roughly halved since late July 2026,** from a median 30.6% of
  aircraft-hexes (1 Oct 2025 – 29 Jul 2026) to 20.4% (30 Jul – 3 Sep) and 15.2% (4 Sep – 21 Oct). Traffic fell only
  14% over the same period, so this isn't a coverage artefact on its face. It's the year's clearest sustained decline.
- **Strait of Hormuz and Cyprus–Levant: two surges at the same time as traffic collapsed.** Hormuz went from 0.8% to a
  median 66% (2 Mar – 3 Apr 2026) and 83% (8 May – 21 Jun), with aircraft-hexes down from about 9,000 to under 400 a
  day. Cyprus–Levant rose from 0.9% to 19% from 28 Feb. Both are back near baseline since June.
- **The same dates surge in several areas at once:** around New Year (Kaliningrad, the southern Black Sea and the
  Caucasus, 28 Dec – 3 Jan) and around 7–17 May (Kaliningrad, the Gulf of Finland, the southern Black Sea and the
  Caucasus). The May run brackets 9 May. A link to Victory Day security measures is a hypothesis, not tested here.
- **One new persistent area:** a res-3 cell centred at 53.92N 23.70E, where Lithuania, Belarus and Poland meet (Grodno
  is about 28 km south), went from active on 4% of days (Oct–Dec 2025) to 96% (late Jul – Oct 2026). No published
  report specific to this area was found; unverified.
- **No weekday pattern of any practical size.** The night peak is strong everywhere in the
  Baltic and Black Sea: 63–87% of aircraft-hexes degraded at 00–02 UTC against 4–19% in the morning.
- **Worldwide, the total held steady:** a median 231 hexes at jamming scale a day in the first 92 days and 245 in the
  last 92; about 54 and 58 active res-3 cells.

## Measures and method

- **Area share:** in each named area's box, aircraft-hexes whose aircraft reported live gross degradation (NACp below 8,
  post-exposure reports left out), over all aircraft-hexes. This is the charts page's daily hotspot trend. Days with
  fewer than 200 aircraft-hexes in the area are left out.
- **Step changes:** binary segmentation of each area's daily share after a 9-day running median (so surges of 4 days or
  fewer don't split it), segments of at least 21 days, a split kept when it cuts the squared error by more than
  3 σ² ln n (σ from the raw day-to-day differences), and only when the medians either side differ by 2 points and 30%.
  Unit-tested on synthetic steps and surges (`tests/test_year_trends.py`).
- **Surges:** days 3 robust deviations and 5 points above the previous 28 days' median, grouped into runs.
- **Started / stopped / persistent:** res-3 cells (about 12,400 km²) active on a day when 2 or more of their res-4 hexes
  are at jamming scale (5 or more aircraft, 100 × max(bad − 1, 0) / aircraft ≥ 10). Compared over the first and last 92
  days, counting only cells with 5-aircraft hexes on 70% or more of days in both windows, so a coverage change isn't
  read as a change in interference.

**The main caveat: the share depends on who is flying.** When traffic collapses (Hormuz, Cyprus–Levant) or receiver
coverage drops (Kaliningrad from May), the remaining aircraft may not be representative. Aircraft that lose their
position entirely don't count at all, and earlier work (verdict 34, 9 May 2026) found jamming makes many aircraft go
dark. A350s and A380s flag degradation more readily than other types (verdict 43), so a change in the widebody mix can
move the share. Each step below lists the aircraft-hex count beside the share for that reason.

## Step changes by area

| Area | Period | Median share | Aircraft-hexes a day (median) | Read |
|---|---|---|---|---|
| Gulf of Finland / Estonia–Russia border | 1 Oct 2025 – 29 Jul 2026 | 30.6% | 1,129 | |
| | 30 Jul – 3 Sep 2026 | 20.4% | 1,039 | Decline, traffic steady |
| | 4 Sep – 21 Oct 2026 | 15.2% | 971 | Decline continues |
| Kaliningrad and approaches | 1–25 Oct 2025 | 26.0% | 585 | |
| | 26 Oct – 25 Dec 2025 | 18.7% | 470 | |
| | 26 Dec 2025 – 16 Jan 2026 | 49.7% | 485 | The known winter surge (verdict 35) |
| | 17 Jan – 2 May 2026 | 24.7% | 466 | |
| | 3 May – 21 Oct 2026 | 45.0% | 139 | **Coverage fell**: only 29 of 171 days with data reach 200 aircraft-hexes. Not readable as more interference |
| Southern Black Sea offshore Turkey | 1 Oct – 23 Dec 2025 | 47.4% | 1,237 | |
| | 24 Dec 2025 – 6 Sep 2026 | 64.8% | 858 | |
| | 7 Sep – 21 Oct 2026 | 38.7% | 223 | Coverage fell too; read with care |
| Western Black Sea coast | 1 Oct – 17 Nov 2025 | 6.4% | 2,539 | |
| | 18 Nov 2025 – 4 Feb 2026 | 8.8% | 4,112 | |
| | 5 Feb – 18 Apr 2026 | 12.5% | 3,464 | Late-winter high |
| | 19 Apr – 21 Oct 2026 | 9.6% | 4,530 | |
| Caucasus | 1–21 Oct 2025 | 14.8% | 2,034 | |
| | 22 Oct – 11 Dec 2025 | 19.6% | 1,576 | |
| | 12 Dec 2025 – 26 Mar 2026 | 32.0% | 1,200 | Winter high, with less traffic |
| | 27 Mar – 13 May 2026 | 14.1% | 2,197 | |
| | 14 May – 4 Jun 2026 | 20.3% | 1,989 | |
| | 5 Jun – 24 Aug 2026 | 28.0% | 1,533 | Summer high |
| | 25 Aug – 21 Oct 2026 | 15.1% | 3,691 | Traffic more than doubled |
| Cyprus–Levant | 1 Oct 2025 – 27 Feb 2026 | 0.9% | 5,425 | |
| | 28 Feb – 22 Mar 2026 | 18.8% | 1,131 | Surge, traffic down about 80% |
| | 23 Mar – 19 Apr 2026 | 13.8% | 1,440 | |
| | 20 Apr – 5 Jun 2026 | 6.3% | 3,841 | |
| | 6 Jun – 21 Oct 2026 | 2.7% | 7,378 | Near baseline |
| Strait of Hormuz / Gulf of Oman | 1 Oct 2025 – 1 Mar 2026 | 0.8% | 9,055 | |
| | 2 Mar – 3 Apr 2026 | 66.0% | 395 | Surge, traffic down 96% |
| | 4 Apr – 7 May 2026 | 5.3% | 2,598 | |
| | 8 May – 21 Jun 2026 | 82.6% | 368 | Second surge, traffic down 96% |
| | 22 Jun – 21 Oct 2026 | 2.0–8.1% | 5,926–7,591 | Three short segments near baseline |
| High latitude excl. Baltic/Russia (control) | whole year | 0.1% | 10,028 | No change |

## Short surges (2 days or more)

| Area | Dates | Peak | Usual (prior 28 days) |
|---|---|---|---|
| Strait of Hormuz / Gulf of Oman | 2–15 Mar 2026 | 86.1% | 0.8% |
| Strait of Hormuz / Gulf of Oman | 7–19 May 2026 | 97.0% | 4.9% |
| Cyprus–Levant | 28 Feb – 13 Mar 2026 | 25.1% | 0.5% |
| Caucasus | 15–21 Dec 2025 | 34.8% | 21.0% |
| Gulf of Finland / Estonia–Russia border | 18–19 Dec 2025 | 45.0% | 29.1% |
| Southern Black Sea offshore Turkey | 28–30 Dec 2025 | 89.5% | 52.0% |
| Caucasus | 28–30 Dec 2025 | 41.5% | 21.9% |
| Kaliningrad and approaches | 29–30 Dec 2025, 1–3 Jan 2026 | 50.0%, 54.4% | 21.4% |
| Caucasus | 7–8 May, 16–17 May 2026 | 37.2%, 35.5% | 13–14% |
| Gulf of Finland / Estonia–Russia border | 8–13 May 2026 | 45.1% | 29.7% |
| Kaliningrad and approaches | 9–10 May 2026 | 59.9% | 26.5% |
| Southern Black Sea offshore Turkey | 15–17 May, 22–23 May 2026 | 77.5%, 71.9% | 52–53% |
| Kaliningrad and approaches | 1–2 Dec 2025 | 33.5% | 15.1% |
| Cyprus–Levant | 25–26 May 2026 | 22.2% | 6.3% |

The 9 May surge in the southern Baltic matches the raw-trace finding (verdict 34): position loss, with 75% of crossings
dark. The New Year run matches the 30 Dec – 11 Jan surge with missing aircraft (verdict 35).

## Time of day and day of week

| Area | Worst UTC hour (share) | Best UTC hour (share) |
|---|---|---|
| Gulf of Finland / Estonia–Russia border | 02 (80.4%) | 08 (5.7%) |
| Southern Black Sea offshore Turkey | 00 (86.8%) | 08 (18.7%) |
| Kaliningrad and approaches | 00 (62.7%) | 09 (15.3%) |
| Caucasus | 01 (40.1%) | 07 (9.7%) |
| Western Black Sea coast | 02 (39.8%) | 06 (4.4%) |
| Cyprus–Levant | 01 (4.8%) | 22 (2.3%) |
| Strait of Hormuz / Gulf of Oman | 00 (5.2%) | 14 (1.8%) |

The year's hourly profile in Hormuz and Cyprus–Levant is flat because the surges are a few weeks of a year. Night
traffic differs from day traffic (fewer flights, more long-haul widebodies); an earlier check (verdict 36) found the
Baltic night effect is mostly local, not altitude or aircraft carried in degraded.

Weekday medians differ little (Kruskal–Wallis per area). The high-latitude control passes the Bonferroni threshold for
eight areas (p = 0.0007 against 0.006), but on shares of 0.1–0.2%, too small to matter. The Gulf of Finland just misses
it (p = 0.007; Saturday 31.9% against 27–30% on other days). No other area comes close. Weekdays are UTC days.

## Where interference started, stopped or persisted

**Started (1 cell):** 53.92N 23.70E (centre of a res-3 cell, about 12,400 km², covering the Lithuania–Belarus–Poland
border area around Druskininkai and Grodno). Active on 4.3% of covered days from 1 Oct to 1 Jan, and 95.7% from 22 Jul to
21 Oct 2026; first active 23 Oct 2025. The cell marks where aircraft were affected, not where a transmitter is. Lithuania's
regulator reports ongoing GNSS interference nationally ([LRT, 9 Mar 2026](https://www.lrt.lt/en/news-in-english/19/2862230/gps-jamming-incidents-reported-by-pilots-continue-in-lithuania-regulator-says)),
but nothing found names this area.

**Stopped:** none by the rule (the Gulf surges started and ended inside the year, so neither window catches them).

**Persistent (48 cells active on half or more of covered days):** the expected Baltic, Black Sea and Caucasus belts,
and some outside the named areas:

| Centre | Country (Natural Earth) | Active days | Note |
|---|---|---|---|
| 59.81N 32.17E, 60.72N 33.21E, 59.81N 34.07E | Russia | 69–97% | East of St Petersburg towards Lake Ladoga, the same area as the spoofed-to point at 60.12N 31.37E seen in both ADS-B and AIS |
| 56.00N 37.15E | Russia | 76% | Moscow region |
| 57.76N 39.40E | Russia | 77% | Near Yaroslavl |
| 54.64N 26.51E | Belarus | 55% | About 76 km from Vilnius |
| 14.74N 98.60E, 13.61N 98.28E | Thailand / sea off Myanmar | 71%, 58% | Myanmar–Thailand border near Dawei; southern Myanmar is described as Asia's GPS-jamming hotspot ([The Diplomat, Oct 2024](https://thediplomat.com/2024/10/gps-jamming-in-myanmar)) |
| 39.62N 32.58E | Turkey | 53% | About 42 km from Ankara; unexplained |
| 43.96N 27.00E | Bulgaria | 60% | Northeast Bulgaria; unexplained |

## What's next

1. **Gulf of Finland decline:** check it route by route and by aircraft type (A350/A380 share by month), and against the
   AIS GNSS-interference counts from Finland's open AIS, which have their own coverage.
2. **Kaliningrad from May:** find out why aircraft-hexes fell (a feeder outage, rerouting, or position loss as on 9 May).
   The "fewer aircraft than usual" map view and the raw traces can tell these apart.
3. **The Grodno-area cell:** pull raw traces for a few active days and see whether it's jamming, spoofing or a few
   aircraft types.
4. **Ankara and northeast Bulgaria:** check the aircraft types and hours; a single operator's fleet can make a cell
   look persistent.
5. **On the site:** a "what changed this year" panel on the charts page from `year_trends.json`, after review.
