# Position loss: aircraft heard but sending no GNSS position (prototype, 25 Oct 2026)

**Code:** `tools/position_loss.py` (outputs in `data/position_loss/`, aggregates only, ODbL 1.0). **Status:** prototype,
not on the map. Written by Claude overnight; not yet reviewed by Tom.

## Why

Every Noise Floor GNSS measure so far counts aircraft that broadcast an ADS-B position. Under strong jamming most
aircraft stop sending a position at all. They drop out of both the numerator and the denominator, and a hex where nearly
everyone lost GNSS can show a modest degraded share from the few that kept a fix. Verdict 45 (`phase1.md`) found exactly
that east of Kaliningrad: 1–3% of crossings had ADS-B positions on summer days in 2026, while the per-hex share read
14–55%.

Where enough ground receivers hear an aircraft, readsb places it by multilateration (MLAT) and marks those positions as
such. An aircraft with MLAT positions in a hex and no ADS-B position there is being heard but is sending no GNSS position.

## Method

Per H3 hex (resolution 4) and UTC hour, aircraft at or above 10,000 ft, ICAO addresses only, from the raw adsb.lol
traces:

- **heard:** aircraft with any ADS-B or MLAT position there;
- **MLAT-only:** aircraft with MLAT positions there and no ADS-B position;
- **position loss** = MLAT-only / heard.

It's a lower bound: an aircraft with neither ADS-B nor MLAT positions can't be placed at all. It depends on MLAT
coverage, so a rise can also mean receivers were added (aircraft that used to be dark become MLAT-only). A background of
aircraft that never send ADS-B positions (older transponders, some state aircraft) shows in the controls: about 1–2%
across central Europe and 4–18% in central Poland.

## Results on eight days with raw traces on disk

Position loss in bold; in brackets, the daily tables' degraded share for the same box and day (aircraft-hexes, live).

| Box | 17 Jan | 1 Feb | 16 May | 20 Jun | 15 Jul | 15 Aug | 15 Sep | 15 Oct |
|---|---|---|---|---|---|---|---|---|
| Gulf of Finland (58.5–60.5N 24–32E) | **30%** (39%) | **20%** (26%) | **46%** (33%) | **36%** (31%) | **43%** (26%) | **65%** (30%) | **63%** (14%) | **64%** (18%) |
| Eastern Gulf of Finland (59.3–60.5N 27–30.5E) | **36%** (91%) | **33%** (87%) | **56%** (98%) | **42%** (93%) | **48%** (78%) | **76%** (86%) | **89%** (87%) | **85%** (87%) |
| Kaliningrad (54.0–55.6N 19–23E) | **13%** (18%) | **18%** (21%) | **50%** (46%) | **84%** (57%) | **79%** (62%) | **86%** (40%) | **86%** (50%) | **82%** (36%) |
| Suwałki–Ełk (53.5–54.35N 21.6–23E) | **26%** (9%) | **39%** (9%) | **66%** (18%) | **93%** (29%) | **95%** (25%) | **91%** (24%) | **90%** (14%) | **94%** (0%) |
| Grodno area (53.5–54.35N 23–24.4E) | **14%** (2%) | **21%** (4%) | **32%** (11%) | **86%** (34%) | **95%** (55%) | **79%** (33%) | **94%** (39%) | **84%** (29%) |
| Kaunas (54.6–55.45N 23.5–24.9E) | **3%** (4%) | **2%** (6%) | **23%** (5%) | **57%** (9%) | **49%** (12%) | **51%** (6%) | **73%** (10%) | **52%** (13%) |
| Central Poland, control (52–52.85N 19.5–20.9E) | **4%** (1%) | **10%** (3%) | **5%** (1%) | **17%** (2%) | **15%** (2%) | **16%** (1%) | **16%** (1%) | **18%** (1%) |
| Central Europe, control (48–52N 5–15E) | **1%** (0%) | **2%** (0%) | **2%** (0%) | **1%** (0%) | **2%** (0%) | **2%** (0%) | **1%** (0%) | **2%** (0%) |

Aircraft heard in the Gulf of Finland box: 17 Jan 1,354, 1 Feb 1,217, 16 May 2,065, 20 Jun 1,756, 15 Jul 1,799, 15 Aug 2,505, 15 Sep 2,343, 15 Oct 2,451.

- **East of Kaliningrad the two measures agree on the season:** position loss rose from 13–39% in Jan–Feb to 79–95% from
  June in the Kaliningrad, Suwałki–Ełk and Grodno boxes, as the crossing test found (verdict 45).
- **The degraded share misses it:** in the Suwałki–Ełk box on 15 Oct, 94% of aircraft heard sent no position and the
  daily tables read 0% degraded, because the few aircraft left with a fix were fine.
- **The controls stay low** (central Europe 1–2%); central Poland's 4–18% is the background of aircraft that never send
  ADS-B positions there, and it rose in summer, which may be traffic mix or a little spill-over.

## Does the Gulf of Finland's falling share mean less interference?

**No. It's aircraft dropping out of the count.** The year analysis found the Gulf of Finland box's degraded share
roughly halving from late July 2026 with traffic steady. The crossing test (verdicts 34–35; aircraft at 10,000 ft or
more, region widened to 52–61.5N 8–34E for these days, extracts in `data/trace_box_wide/`) shows aircraft losing their
positions entirely from August, above all in the east:

| Day | Eastern Gulf, seen (59.3–60.4N 26.5–29.5E) | Western Gulf, seen (59.3–60.0N 24.5–26.5E) | Sweden control, seen (58.4–59.2N 14–16E) | Eastern Gulf, ADS-B aircraft-hexes in the daily table |
|---|---|---|---|---|
| 17 Jan | 33% | 41% | 99% | 52 |
| 1 Feb | 25% | 40% | 98% | 34 |
| 16 May | 25% | 34% | 100% | 60 |
| 20 Jun | 37% | 38% | 100% | 73 |
| 15 Jul | 26% | 29% | 96% | 53 |
| 15 Aug | 11% | 20% | 97% | 60 |
| 15 Sep | 6% | 27% | 98% | 12 |
| 15 Oct | 6% | 26% | 97% | 25 |

- The eastern Gulf's few positioned aircraft were nearly all degraded (75–100%) on every day. When most of them stopped
  sending positions in September and October, the box lost its most degraded aircraft-hexes, and the whole Gulf's
  average fell. The western Gulf's degraded share stayed at 5–13% all year.
- Position loss in the Gulf of Finland was already high in winter (59–75% of crossings without positions for most of
  the way); the change from August is in the east.
- Part of the rise in MLAT-only aircraft is MLAT coverage growing: in the western Gulf, dark crossings fell from 11–14%
  (Jan–Feb) to 3–12% while MLAT-only crossings rose from 29–31% to 43–65%. The crossing test's "seen" share isn't
  affected by that, which is why it's the measure used here.

## What follows

1. **The per-hex degraded share can fall while interference spreads.** Wherever position loss is high, the share is
   measured on the few aircraft that keep a fix. Any trend in the share needs the position-loss measure beside it.
2. **A position-loss layer belongs on the map** next to the degraded share, with MLAT coverage shown so a blank isn't
   read as clean. That's a method change for the daily pipeline (count MLAT-only aircraft per hex and hour from the same
   pass); it needs a review first.
3. **Coverage drift has to be controlled for:** track the number of MLAT-capable hexes per day and keep control boxes
   (central Europe, central Poland) in every report.
