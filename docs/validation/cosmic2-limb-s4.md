# COSMIC-2 limb S4 (pre-registration, 15 Nov 2026)

**What it measures:** limb S4 measured along radio-occultation paths, which reads higher than a ground receiver's S4.
The ray from a GPS satellite to a COSMIC-2 receiver below the receiver's horizon crosses the ionosphere edge-on, over
thousands of kilometres, so its S4 is not a ground receiver's S4 and is never read against the alert levels used for
ground S4.

**Tools:** `tools/cosmic2_s4.py` (method), `tools/cosmic2_job.py` (the daily job that runs on GitHub,
`.github/workflows/cosmic2.yml`), `tools/cosmic2_s4_check.py` (this check). Tests: `tests/test_cosmic2_s4.py`.
**Sources:** `cosmic2-ro` (UCAR CDAAC, CC BY 4.0) and, as ground truth, `ingv-eswua-scint` (INGV eSWua, CC BY 4.0).
**Product:** `<day>.cosmic2-limb-s4.json` on the `swx-data-YYYY-MM` releases, one per UTC day, due by 14:00 UTC the
next day, so the board and COP have a same-morning picture.

## 1. What the files hold (measured 13-15 Nov 2026, on the tuning day 13 Nov)

- **S4 in `podTc2`.** UCAR's format page lists `S4` ("S4 scintillation index", unitless, fill −999) beside the RFI
  index the interference layer reads. UCAR's TGRS Space Weather Provisional Data Release 1 (30 Mar 2020, section 3):
  the receiver computes S4 on board for each GNSS satellite its navigation (POD) antennas track, every 10 s, from 50 Hz
  (GPS) signal-to-noise ratio, as the square root of (⟨P²⟩ − ⟨P⟩²)/⟨P⟩²; `podTc2` holds an unmodified copy. So it is
  total S4, with no noise correction. The release notes "occasional" spurious high values "at beginning of a GNSS
  track", with no quality flags. **Not verified:** the format page does not name the signal; we take `S4` to be GPS
  L1 C/A, the signal the release's L1 S4 refers to.
- **One value per 10 s.** The 1 Hz `S4` series holds each value for 10 samples (53,000 runs of equal values in 400
  files: about 98% are 10 long). So one sample here is one 10 s value, not one second.
- **Overlapping files.** A track is written again, from its start, in each later dump: 400 files held 170 distinct
  links, and every shared second carried the same S4 (123,091 of 123,091).
- **Geometry.** Our tangent heights (closest point of the straight receiver-GPS line to the Earth's centre, height
  above the WGS84 ellipsoid) match UCAR's own `occheight` to within 0.01 km on 25,282 below-horizon samples.
- **Track start.** On 13 Nov, limb seconds in the first 30 s of a track had a higher median S4 (0.12–0.17 against
  0.07–0.10 later), but they were 0.04% of limb seconds. Dropping the first 60 s costs 2.4% of values.
- **Satellites.** On 13 Nov only C2E2, C2E5 and C2E6 delivered links (as on 19 Oct, when three of six did); the day
  file says so in `problems`.
- **Grid.** At H3 res 2 (about 300 km) only 16% of cell-hours reached 10 values; at res 1 (about 840 km) 66% did, and
  5° bins 44%.
- **GLONASS** links (`conid` R) are in the same archive and are left out.

## 2. Frozen method (version 1.0)

`tools/cosmic2_s4.py` as committed with this document:

1. Links: GPS only (`conid` G). Seconds with a valid S4 (not −999, 0–9999) and the link below the receiver's horizon
   (`elevation` < 0).
2. Place: the ray's tangent point, from `x/y/z_LEO` (at reception) and `x/y/z_GPS` (at transmission), straight-line
   geometry. Keep tangent points 150–500 km above the WGS84 ellipsoid.
3. Seconds are made unique per link (receiver, antenna, PRN). Seconds within 60 s of the start of their file's track
   are dropped.
4. One value per 10 s window: a run of seconds of one link with the same S4, at most 10 s long, with no gap over 10 s,
   placed at its middle second. A window is RFI-flagged if UCAR's RFI index reached 1e-4 in any of its seconds.
5. Grid: H3 res 1, because the place along the ray is uncertain by up to about 2,000 km either side of the tangent
   point (the F region at 250–450 km, straight-line geometry), and because res 2 leaves most cell-hours below the
   10-value minimum. Across the line of sight the place is good to tens of km. H3 is the grid of every Noisefloor map
   layer.
6. Per cell and UTC hour: `n` (10 s values), `links`, `p95` (95th percentile, numpy's linear interpolation, only from
   10 values), `max`, `lst` (mean local solar time at the cell centre, at the cell-hour's median time) and `rfi` (share
   of the values that were RFI-flagged). UCAR's Cal/Val team found that interference can raise on-board S4 and that the
   RFI index does not always catch it, so `rfi` is a pointer, not a correction.

## 3. Ground truth: eSWua receivers

- **Stations** (eSWua codes; the view is `ws<code>`): Lagos `lag0p`, Nairobi `nai0p`, Malindi `mal0p`, Tucumán
  `tuc0p`, São Paulo `sao0p`, Saba `sab0p`, KL University `klu0p`, Dhaka `dha0p`, Hanoi `han0p`, Kenting `ken0p`.
  Positions from eSWua's station table.
- **Records:** one per satellite and minute. Kept: elevation 30° or more, and eSWua satellite ids (`svid`) of GPS
  (1–37), GLONASS (38–68), Galileo (71–106), BeiDou from C06 (146–177) and QZSS J01–J06 (181–186). Dropped: SBAS
  (120–140, 198–215), ids with no PRN in eSWua's satellite table (69–70, 107–119, 178–180, 188–190, and any other),
  geostationary QZSS Q07 (187), and, for the same reason (a still pierce point, open to steady multipath), BeiDou
  C01–C05 (141–145) and NavIC (191–197), whose satellites are all geostationary or inclined geosynchronous.
- **S4:** the noise-corrected L1 value, √max(`totals4l1`² − `corrections4l1`², 0); `totals4l1` alone where the
  correction is missing.
- **Receiver-hour** (UTC): judged when it has at least 300 kept satellite-minutes. **Disturbed:** at least 2
  satellite-minutes with S4 of 0.5 or more. **Quiet:** none. One such minute: unclear, left out. These levels apply to
  the ground receivers' own S4 only; nothing here sets a level for limb S4.
- eSWua's `dt` is taken as UTC. The receivers time-tag in GPS time (18 s ahead), which moves no record across an hour
  boundary except those at hh:59:42 and later; that is accepted.

## 4. Pairing

- For each judged receiver-hour, the limb cells of the same UTC hour that have a `p95` and whose centre lies within
  **1,000 km** of the station (great circle, R = 6,371 km). The receiver-hour's limb value **L** is the largest such
  `p95`. Receiver-hours with no such cell are not paired; their count is reported.
- Why 1,000 km: a ground receiver's pierce points at 350 km for elevation 30° or more lie within about 550 km of it,
  and a res-1 cell's centre is up to about 480 km from its edge. 600 km and 1,500 km are reported beside it, without
  marks.
- Station-hour local solar time is UTC plus the station's longitude / 15.

## 5. Checks on held-out days

**Days:** every day from 16 Oct to 12 Nov 2026 except the tuning and scratch days 7, 9 and 10 Nov: 25 days. 13 and
14 Nov are not used. A day whose limb file is missing, or a station-day with no eSWua records, is skipped and reported,
not replaced. The limb files are the published `swx-data-2026-10` and `swx-data-2026-11` assets, made by the frozen
method with `cosmic2.yml` (`s4_only`) after this document is committed.

| # | Check | Holds if | Fails if |
|---|---|---|---|
| L1 | Pooled AUC of L, disturbed against quiet receiver-hours (all hours) | ≥ 0.70 | < 0.60 |
| L2 | The same, only receiver-hours at station local solar time 19:00–02:00 (needs 20 disturbed and 20 quiet pairs, else not judged) | ≥ 0.60 | < 0.55 |
| L3 | Chance test: labels shuffled 2,000 times within station × local-solar-hour strata (keeps place and time of day, breaks the day-to-day pairing); one-sided p of L1's AUC | p ≤ 0.01 | p > 0.05 |

Between the two marks the result is "weakened". The layer counts as validated only if L1, L2 and L3 all hold.

Reported without marks: the median L in disturbed and in quiet receiver-hours with a 95% interval (bootstrap over
station-days, 2,000 draws, seed 1); each station's own AUC where it has 5 or more disturbed pairs; the AUC with the
largest `max` in place of `p95`; L1 at 600 km and 1,500 km; and the share of paired cell-hours with `rfi` above 0.5.

**Seeds:** L3 uses numpy's default generator with seed 1.

## 6. Results on the held-out days (run 15 Nov 2026, 03:50 UTC)

Sections 1–5 were committed in 488706e before any held-out day was made. The 25 limb files came from the workflow run
of 15 Nov 2026 at 03:29 UTC (`cosmic2.yml`, `s4_only`, commit 0735348, which only fixed a log line in the job). Command:
`python tools/cosmic2_s4_check.py check 2026-10-16:2026-11-06 2026-11-08 2026-11-11:2026-11-12`.

**All three checks hold, so the layer is validated.**

| # | Check | Result | Verdict |
|---|---|---|---|
| L1 | Pooled AUC, disturbed against quiet receiver-hours | 0.834 (140 disturbed, 2,832 quiet) | holds |
| L2 | The same, at station local solar time 19:00–02:00 | 0.763 (130 disturbed, 633 quiet) | holds |
| L3 | Chance test, labels shuffled within station × local-solar-hour | p = 0.0005 (none of 2,000 shuffles reached 0.834) | holds |

**Counts.** 5,029 judged receiver-hours; 2,972 paired with a limb cell within 1,000 km in the same hour; 2,057 had none.
Skipped station-days (no eSWua records): Hanoi on all 25 days; Lagos 24–27 Oct; Nairobi 30–31 Oct and 8 Nov. No limb
file was missing. Every limb file lists one problem: only C2E2, C2E5 and C2E6 delivered `podTc2` data (the interference
layer's tables show the same three satellites).

**Reported without marks:**
- Median L: disturbed 0.516 (95% interval 0.444–0.609), quiet 0.131 (0.128–0.136). These are limb values; they say
  nothing about ground S4 levels.
- AUC with the largest `max` in place of `p95`: 0.833.
- L1 at 600 km: 0.821 (1,413 pairs); at 1,500 km: 0.834 (3,735 pairs).
- Averaged over paired receiver-hours, the share of their nearby cells with `rfi` above 0.5: 0.375.
- Each station's own AUC (5 or more disturbed pairs):

| Station | AUC | Disturbed | Quiet |
|---|---|---|---|
| Lagos | 0.951 | 6 | 339 |
| Nairobi | 0.906 | 17 | 296 |
| Malindi | 0.894 | 17 | 311 |
| Tucumán | 0.910 | 28 | 317 |
| São Paulo | 0.772 | 28 | 270 |
| Saba | 0.811 | 16 | 289 |
| KL University | 0.745 | 20 | 318 |
| Dhaka | 0.838 | 5 | 341 |

Kenting had fewer than 5 disturbed pairs; Hanoi had no records.

**Exploratory, not pre-registered** (run after the results above, because UCAR's Cal/Val team found that interference
can raise on-board S4): with only cells whose `rfi` is 0.5 or less, L1's AUC is 0.808 (2,087 pairs, 110 disturbed) and
the night-only AUC 0.720; with only cells with no RFI-flagged value, 0.763 (1,317 pairs, 59 disturbed) and 0.694. The
separation does not rest on RFI-flagged cells, though it is weaker without them; whether scintillation itself raises
UCAR's RFI index was not tested.

**Tuning days against the unfrozen scratch results** (not part of the test): the published files place the 7 Nov
South American peak at 03:00–04:00 UTC (1.21 near 4°S 56°W, 1.00 near 8°S 63°W) and the 9 Nov Horn of Africa values
at 16:00–17:00 UTC (0.47 near 12°N 46°E), one hour earlier than the scratch notes; the 10 Nov peaks over Africa are at
20:00–22:00 UTC (up to 1.33 near 8°N 18°E), as in the scratch. The time conversion was checked against a file's own
start time (GPS 00:01:31 = 00:01:13 UTC).

**What this shows and what it does not.** Limb S4 is higher where and when low-latitude ground receivers see
scintillation, beyond what the time of day explains (L2, L3), on 25 days in Oct–Nov 2026 with three satellites. It is a
regional indicator placed at a nominal tangent point, not an estimate of the S4 a ground receiver would measure, and
its values are not on the same scale. One season and eight stations; no mid- or high-latitude test.

**Interference file from the same pass.** On 7, 9, 10 and 13 Nov the job's `<day>.cosmic2.json` matched the file this
PC had published, cell for cell (score difference 0.0). The job filled 11 and 12 Nov, which the PC had missed.

## 7. What waits on review

Adding the layer to the public map or to the `tic-feed/2` feed, after this validation, as for every earlier layer.
