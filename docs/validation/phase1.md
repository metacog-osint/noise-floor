# Phase 1 validation report: PNT processor v1

**Date:** 14 Oct 2026 · **Method:** `docs/method-card.md` (v1) · **Code:** `pipeline/pnt_daily.py` · **Generated tables and maps:** `phase1_results.md`

## Bottom line

The processor finds the known Baltic, Black Sea and Caucasus hotspots on all three test days. The controls stay quiet, and the maps agree by eye with GPSJam's for the same dates. A G2 geomagnetic storm produced no measurable rise at high latitudes at the 93 m threshold. Phase 1.1 found the storm effect at the 10 m threshold (verdict 9).

One rule needs work before backfill. The avionics-suspect filter works as intended over western Europe, but on the quiet day it also dropped about one in six suspects that flew mostly inside the hotspots. Some of those may be genuinely jammed flights.

A worldwide day processes in about a minute on this PC, not the 10 CPU-minutes estimated, so a full backfill is hours, not days.

## Test days

| Day | Why | Space weather (GFZ Kp) |
|---|---|---|
| Thu 16 Oct 2025 | Quiet weekday; also the 6 Oct spike day | Max Kp 1.3 |
| Sat 18 Oct 2025 | G2 storm; weekend traffic | Max Kp 6.3 |
| Wed 22 Oct 2025 | Quiet weekday a week later (stability) | Max Kp 1.3 |

Kp source: GFZ Potsdam Kp index (`kp.gfz.de`, CC BY 4.0), retrieved 14 Oct 2026.

## Verdicts

| # | Check | Result | Verdict |
|---|---|---|---|
| 1 | Known hotspots reproduce | Share of aircraft degraded, across the three days:<br>• Southern Black Sea offshore Turkey **46–59%**, with every busy hex (10+ aircraft) red<br>• Gulf of Finland / Estonia–Russia border **32–41%**<br>• Kaliningrad **20–35%**<br>• Caucasus **15–39%**<br>• Western Black Sea coast 6–8% | **Pass** |
| 2 | Controls stay quiet | • US Midwest 0.0%<br>• Central Europe 0.7–1.0%<br>• High latitude away from Russia 0.1–1.4%<br>• No red hexes, except one on 22 Oct | **Pass** |
| 3 | Agreement with GPSJam (by eye only; GPSJam is never an input) | 16 and 18 Oct match on the Baltic states, Kaliningrad, Gulf of Finland, western Black Sea coast, Turkish Black Sea coast and Caucasus. On 18 Oct both show Scandinavia, Iceland and the UK green, and a larger Baltic footprint toward Lithuania and Poland. On 16 Oct both show the Levant mostly green. | **Pass, with differences below** |
| 4 | Storm-day effect (G2) | High-latitude control lowest on the storm day (0.1%, against 0.3% and 1.4%). No storm signature on either map. | **Pass at 93 m only.** Corrected by Phase 1.1 verdict 9: the storm shows at 10 m. |
| 5 | Avionics-suspect rule | Suspects: 93 (Thu), 252 (Sat), 82 (Wed). Over central Europe alone: 27, 170, 19. The Saturday excess is weekend light aviation (most common types: Ikarus C42, Breezer, ultralight, FK9, DR40, glider), correctly removed. Several sorties in a day stretch past the 3-hour span. On 16 Oct, 16 of 93 suspects flew mostly over western Russia, the Baltic states or the Black Sea, including airliners. | **Open:** may remove real signal |
| 6 | Throughput | 53–70 s per worldwide day (3.1–3.5 GB archive, read sequentially from the USB drive) | **Pass**; the earlier estimate was about 10× too high |

### Differences from GPSJam

- **Coverage.** GPSJam (fed by ADS-B Exchange and airplanes.live) sees far more of Russia's interior than adsb.lol does. Our map has gaps there, and they show as no data, not as quiet.
- **Levant.** GPSJam shows isolated red hexes near Adana, the Syrian coast and southern Israel and Jordan on 16 Oct. Our Cyprus–Levant box reads 0.5–0.7% with no red hexes among those with 10+ aircraft. This is probably the aircraft threshold: those hexes carry little traffic. Check once hourly resolution exists.

## What the data shows (beyond pass/fail)

- **The southern Black Sea is the most consistent hotspot.** Every busy hex on the airways off Turkey's Black Sea coast (41.3–42.5°N, 34–41°E) was red on all three days, at 46–59% degraded. Per the method card, this marks where receivers degraded, not where a transmitter is.
- **The Estonia–Russia border and the eastern Gulf of Finland** hold the highest single-hex scores: 90%+ on all three days, with NIC degraded alongside NACp.
- **Kaliningrad** rose from 20% (Thu) to about 35% (Sat and Wed). This is a variation worth tracking day by day once backfill exists.

## Open items for Phase 1.1 (before backfill)

1. **Avionics-suspect rule.** Flag an aircraft only where it is bad and most other aircraft in the same hex and hour are good. That keeps faulty avionics out without dropping flights that spent hours inside a jammed area. Re-run all three days and compare the hotspot shares.
2. **Hourly resolution.** It is needed to time storm effects and separate events within a day.
3. **Coverage layer.** Publish aircraft per hex with the score, and decide a minimum aircraft count for colouring public maps.
4. **Validation set.** None of the planning guide's validation events fall in October 2025. Once those rows are verified, add test days that match them (for example the October 2024 Kaliningrad case, if adsb.lol's 2024 archive covers it).

## Reproduce

```bash
python pipeline/pnt_daily.py 2025-10-16 --raw <folder with the adsb.lol tar or split parts>
python pipeline/pnt_daily.py 2025-10-18 --raw <...>
python pipeline/pnt_daily.py 2025-10-22 --raw <...>
python tools/validate_phase1.py 2025-10-16 2025-10-18 2025-10-22
```

Each run's `data/pnt/daily/<day>.summary.json` records the input files, their SHA-256 and every method parameter.

---

# Phase 1.1: processor v1.1 (14 Oct 2026)

**Generated tables and figures:** `phase1_1_results.md` (v1 vs v1.1, October storm test, coverage) and `cases_results.md` (November storm, Bay Area).

## Bottom line

- **The peer-based avionics rule leaves the hotspot figures unchanged** (within half a point of v1) while removing more faulty avionics elsewhere.
- **The 10 m accuracy metric, counted over aircraft that showed 10 m capability that day, detects two geomagnetic storms and a documented EGNOS outage.** The 93 m (gross) metric stays flat through all three. The two thresholds therefore separate natural and infrastructure degradation from jamming-scale loss.
- **A deliberate event, the Bay Area GPS loss of 22 Sep 2026, shows in the gross metric on a geomagnetically quiet day.** Its timing matches the published account.

## Verdicts

| # | Check | Result | Verdict |
|---|---|---|---|
| 7 | Peer-based avionics rule | Hotspot shares within ±0.5 points of v1 on all three days. Suspects 164 / 421 / 133 (v1: 93 / 252 / 82), with 0–2 per day centred in a hotspot. | **Pass** |
| 8 | Raw NACp < 10 share | 61–100% in northern Europe on every day. Many aircraft without SBAS report NACp 9 all the time, so it measures equipage. | **Fail:** replaced by the capable-aircraft share |
| 9 | Capable share, G2 storm (18 Oct 2025, Kp 6.3 at 18–21Z) | North America northern tier: 12.4% against 2.1–3.2% on quiet days, peaking at 29–39% at 20–22Z. Southern US control 2.2% against 3.0–3.5%. Gross flat. | **Pass.** This corrects Phase 1 verdict 4: the storm had an effect, below the gross threshold. |
| 10 | Capable share, G4 storm (12 Nov 2025, Kp 8.7 at 00–06Z) | North America northern tier **38.5%** against a 3.7% baseline. Gross 0.03% against 0.04%. Maps show onset over southern Canada at 01Z, a coast-to-coast band at 02–03Z and southward spread at 04–05Z. | **Pass.** Independently reproduces the sequence John Wiseman showed from his own data |
| 11 | EGNOS outage (unplanned finding) | On 16 Oct 2025, 80–100% of capable aircraft were below 10 m across Europe (Scandinavia to Iberia) all day, against 10–25% on 18 and 22 Oct. North America normal (3–5%). EGNOS had a total loss of signal from 13 Oct 11:14 to 17 Oct 10:10. | **Detected.** Needs an SBAS-outage exclusion. 16 Oct is not a valid quiet baseline for Europe on this metric. |
| 12 | Deliberate interference (22 Sep 2026, Kp ≤ 1.7) | Bay Area and Central Valley, aircraft-hexes worse than 93 m: 0 every hour 04–17Z; **8 at 18Z, 11 at 19Z, 25 at 20Z**; 1 at 21Z. Capable share 7.8% at 20Z against 2–4% otherwise. | **Pass.** Matches the reported early burst around 18:00Z and the larger burst near 20:00Z inside the Point Mugu NOTAM window (18:30–20:29Z). The NOTAM text was not independently retrieved (UNVERIFIED). |
| 13 | Coverage and public maps | Hexes with 3–4 aircraft score red 2.0% of the time, against 1.3–1.4% for 5–49. | **Decided:** colour public maps at 5+ aircraft (method card) |

## Open items (Phase 1.2, before backfill)

1. **SBAS-outage exclusion.** Ingest EGNOS service notices and historical status, and FAA WAAS NOTAMs. Flag the capable metric as unusable for a region while its SBAS is down.
2. **Burst detection.** The hourly majority rule dampens short events. At 20Z the Bay Area case shows 25 aircraft-hexes, while the source thread counts about 80 aircraft affected in its peak minute. Add a per-minute count of aircraft with any degraded report, for event timing.
3. **Baselines.** Add a rolling same-hour median per region over the previous 14 days. The storm and EGNOS cases show that a fixed threshold isn't enough on the fine metric.
4. **Leads seen in passing (not yet explained):**
   - A gross spike over northern Europe at 02Z on all three October days (low traffic).
   - A gross spike over the southern US at 03–08Z on 16 and 22 Oct, both weekdays. Check NAVCEN GPS test notices.
5. **Retrieve the 22 Sep 2026 NOTAM** from the FAA archive to close the Bay Area case.

## Sources for this section

- Kp: GFZ Potsdam (`kp.gfz.de`, CC BY 4.0), retrieved 14 Oct 2026.
- EGNOS outage:
  - [EGNOS Monthly Performance Report, October 2025](https://egnos.gsc-europa.eu/sites/default/files/documents/174%20-%20Monthly%20Performance%20Report%20-%20October%202025.pdf?v=1762523670) ("total loss of SiS occurring on October 13")
  - [LPPR NOTAM, EGNOS outage](https://notamify.com/notams/LPPR/c0b92b77-ed7b-4b00-974c-7544f05f6a5b) (13 Oct 11:14 to 17 Oct 10:10; time zone not stated)
- Storm and Bay Area accounts: John Wiseman on Bluesky, 7 Oct 2026, [storm figure](https://bsky.app/profile/lemonodor.bsky.social/post/3mxcife7bw22t) and [Bay Area GPS loss](https://bsky.app/profile/lemonodor.bsky.social/post/3mxccciuhlk2z). His data is independent of ours, and we used his posts only as accounts of the events, never as data.
