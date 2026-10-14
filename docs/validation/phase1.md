# Phase 1 validation report: PNT processor v1

**Date:** 14 Oct 2026 · **Method:** `docs/method-card.md` (v1) · **Code:** `pipeline/pnt_daily.py` · **Generated tables and maps:** `phase1_results.md`

## Bottom line

The processor finds the known Baltic, Black Sea and Caucasus hotspots on all three test days. The controls stay quiet, and the maps agree by eye with GPSJam's for the same dates. A G2 geomagnetic storm produced no measurable rise at high latitudes.

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
| 4 | Storm-day effect (G2) | High-latitude control lowest on the storm day (0.1%, against 0.3% and 1.4%). No storm signature on either map. | **Pass** for G2; stronger storms untested |
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
