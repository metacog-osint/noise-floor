# Ground ROTI (pre-registration, 15 Nov 2026)

**What it measures:** ROTI, a measured TEC fluctuation index at fixed stations. ROTI is the standard deviation, over
5 minutes, of the rate of change of slant TEC along each station-satellite path (Pi, Mannucci, Lindqwister and Ho 1997,
"Monitoring of global ionospheric irregularities using the worldwide GPS network", GRL 24(18), 2283-2286). It is a proxy
for ionospheric irregularities. It is not a scintillation index: it is never an S4 value, it is never read against the
alert levels used for S4, and this document sets no alert level for ROTI either.

**Tools:** `tools/ground_roti.py` (method), `tools/ground_roti_job.py` (the daily job that runs on GitHub,
`.github/workflows/ground-roti.yml`), `tools/ground_roti_check.py` (this check). Tests: `tests/test_ground_roti.py`.
**Sources:** `cors-igs` (IGS station data via the BKG GNSS Data Center; IGS terms: open, attribution required) and, as
ground truth, `ingv-eswua-scint` (INGV eSWua, CC BY 4.0).
**Product:** `<day>.ground-roti.json` on the `swx-data-YYYY-MM` releases, beside the COSMIC-2 limb S4 files, one per
UTC day, due by 14:00 UTC the next day.
**Purpose:** like the limb S4 layer, to fill in low-latitude irregularity activity where no scintillation receiver sits.

## 1. Frozen method (version 1.0)

`tools/ground_roti.py` as committed with this document. The choices below were made on the engineering days 13 Nov 2026
(every station but Djibouti) and 14 Nov 2026 (Djibouti), from the files' own properties only: no eSWua record was read
alongside any ROTI value before this document was committed.

1. **Stations** (IGS names; positions from the files' `APPROX POSITION XYZ`). Where no scintillation receiver sits:
   Cape Verde `CPVG00CPV`, Gabon `NKLG00GAB`, Ascension Island `ASCG00SHN`, Djibouti `DJIG00DJI`, Seychelles
   `SEY200SYC`, Madagascar `VOIM00MDG` and Diego Garcia `DGAR00GBR`. Ghana `ACRG00GHA` is in that belt too, but sits
   418 km from the Lagos receiver, so it is also a validation partner. Added for the validation, each the open IGS
   station nearest an eSWua receiver: Malindi `MAL200KEN`, Eldoret `MOIU00KEN`, Salta `UNSA00ARG`, Cachoeira Paulista
   `CHPG00BRA`, Saba `SABY00BES`, Gadanki `GDKG00IND`, Shillong `SHLG00IND`, Tainan `NCKU00TWN` and Hanoi `HUMG00VNM`.
   17 stations, all published.
2. **Files:** each station's daily 30 s RINEX 3/4 observation file (`..._01D_30S_MO.crx.gz`) from
   `igs.bkg.bund.de/root_ftp/IGS/obs/YYYY/DDD/` (anonymous), and the IGS merged broadcast navigation file
   (`BRDC00IGS_R`, with BKG's other merged files as fallbacks) for orbits. Compact RINEX 3.1 files (RNX2CRX 4.2.0) are
   read as compact RINEX 3.0, the newest version the `hatanaka` 2.8.1 decoder accepts. On `MAL200KEN`, 13 Nov, that gave
   2,880 epochs, and G02's code difference C2W − C1C stayed within −6 to +10 m. **Not verified:** what else changed in 3.1. The
   day file notes every station read this way.
3. **Signals.** GPS: L1 C/A carrier (`L1C`) with L2. For each satellite the L2 signal is whichever of L2C (`2L`, `2X`,
   `2S`) or semi-codeless P(Y) (`2W`) has the most epochs with both its phase and its code; ties go to that order.
   Galileo: E1 (`1C`, `1X`, `1B`) with E5a (`5Q`, `5X`, `5I`), picked the same way. GLONASS, BeiDou and QZSS are left
   out.
4. **Elevation:** at least 30 deg (the eSWua mask in section 2; it also limits multipath), from the broadcast
   ephemeris, satellites broadcast as healthy only (`tools/station_cn0.py` `sky`).
5. **ROT.** Slant TEC from the geometry-free carrier phase, (λ1φ1 − λ2φ2) / (40.308×10¹⁶ (1/f2² − 1/f1²)) TECU
   (0.1051 m per TECU for GPS L1/L2, 0.1288 m for Galileo E1/E5a). ROT at epoch k is (TEC(k) − TEC(k−1)) / 0.5 min, in
   TECU/min. It is formed only when epochs k−1 and k are consecutive (30 s apart) and both hold both phases and both
   codes.
6. **Cycle slips.** No ROT at epoch k where the loss-of-lock indicator (bit 0) is set on either carrier, or where the
   Melbourne-Wübbena combination (Melbourne 1985; Wübbena 1985) changes by more than **2 wide-lane cycles** from k−1.
   Why 2: on the engineering days, at 30 deg or more, the epoch-to-epoch change had a median of 0.04-0.27 cycles and a
   99th percentile of 0.21-1.30 cycles across the 17 stations, and exceeded 2 cycles at 0-0.22% of epoch pairs. Inside
   a strong irregularity (Saba, G14, 03:15 UTC on 13 Nov) it reached 0.96 cycles, and true slips were 85 and 220 cycles.
   A 1-cycle mark would have dropped 1-3% of good data at some stations and much of the data inside irregularities.
   Known limit: a slip by the same number of cycles on both carriers leaves the Melbourne-Wübbena combination unchanged
   and adds 0.51 TECU per cycle to one ROT value. Bit 1 of the loss-of-lock indicator (half-cycle ambiguity) is not used.
   Each refused epoch above 30 deg counts as an arc break.
7. **ROTI:** the population standard deviation of ROT, √(⟨ROT²⟩ − ⟨ROT⟩²), in fixed 5-minute windows of GPS time (10
   epochs), from at least 8 ROT values. A window's middle is at least 2 minutes from its edges, so the 18 s GPS-UTC
   offset moves no window into another UTC hour.
8. **Pierce points:** thin shell at 350 km, spherical Earth (6,371 km), at the middle ROT epoch of each window. At 30
   deg they lie within about 550 km of the station.
9. **Per station and UTC hour** (pooled over GPS and Galileo satellites): `n` (5-minute ROTI values), `sats`, `p95`
   (95th percentile, numpy's linear interpolation, only from 20 values), `max`, `max_lat`/`max_lon` (the pierce point of
   the largest value), `lst` (the station's mean local solar time at the middle of the hour, UTC + longitude / 15) and
   `breaks` (arc breaks above 30 deg). Station latitude and longitude are on every row.
10. **The day file** also carries `as_of`, the registry id (`cors-igs`), credit lines, the licence (CC BY 4.0), the
    station list (receiver, antenna, file, BKG listing time), `missing` (stations not posted when it was made),
    `failed` (stations whose file could not be read) and `problems`.

**Measured on the engineering days, for reference** (not part of the test): quiet-hour `p95` was 0.03-0.17 TECU/min;
`n` was 72-156 per station-hour. Raised hours on 13 Nov: Salta 00-03 UTC (`p95` 1.8-4.5 TECU/min), Cape Verde 20-03 UTC
(0.9-2.4), Ghana 22-01 UTC (0.4-1.9), Ascension 20-01 UTC (0.26-1.3), Gabon 00-01 UTC (0.48-0.53); Djibouti 18-20 UTC on 14 Nov
(0.25-0.98). Each station-day took 2-5 s to compute on this PC.

**Posting at BKG** (listing times of day D's file, hours after the end of day D, sampled on 10 days from 16 Oct to 14
Nov 2026): within an hour on most days, Ghana, Gabon, Djibouti (missing on 13 Nov), Madagascar, Salta, Cachoeira
Paulista, Saba, Gadanki and Hanoi; Cape Verde 8-56 h until 11 Nov, then within an hour; about 1.6 or 9 h, Seychelles, Diego Garcia,
Shillong; about 9 h, Malindi, Eldoret, Tainan; Ascension about 57 h, except 33 h on 13 Nov and 9 h on 14 Nov. On 13
Nov the 9 h batch came at 12:45 UTC. A listing time can be later than the first posting if BKG replaced the file.

## 2. Ground truth: eSWua receivers

The same rules as `docs/validation/cosmic2-limb-s4.md` section 3, restated:

- **Receivers** (eSWua codes; the view is `ws<code>`): Lagos `lag0p`, Nairobi `nai0p`, Malindi `mal0p`, Tucumán
  `tuc0p`, São Paulo `sao0p`, Saba `sab0p`, KL University `klu0p`, Dhaka `dha0p`, Hanoi `han0p`, Kenting `ken0p`.
  Positions from eSWua's station table.
- **Records:** one per satellite and minute. Kept: elevation 30° or more, and eSWua satellite ids (`svid`) of GPS
  (1–37), GLONASS (38–68), Galileo (71–106), BeiDou from C06 (146–177) and QZSS J01–J06 (181–186). Dropped: SBAS,
  ids with no PRN in eSWua's satellite table, geostationary QZSS Q07, BeiDou C01–C05 and NavIC.
- **S4:** the noise-corrected L1 value, √max(`totals4l1`² − `corrections4l1`², 0); `totals4l1` alone where the
  correction is missing.
- **Receiver-hour** (UTC): judged when it has at least 300 kept satellite-minutes. **Disturbed:** at least 2
  satellite-minutes with S4 of 0.5 or more. **Quiet:** none. One such minute: unclear, left out. These levels apply to
  the ground receivers' own S4 only; nothing here sets a level for ROTI.
- eSWua's `dt` is taken as UTC (the receivers time-tag in GPS time, 18 s ahead; accepted, as in the limb check).
- The code is the limb check's own (`tools/cosmic2_s4_check.py` `hour_labels`), not a copy.

## 3. Pairing

Each eSWua receiver is paired with one IGS station, fixed in advance (`STATIONS` in `tools/ground_roti.py`):

| eSWua receiver | IGS station | Distance |
|---|---|---|
| Malindi `mal0p` | Malindi `MAL200KEN` | 0 km |
| Saba `sab0p` | Saba `SABY00BES` | 4 km |
| Hanoi `han0p` | Hanoi `HUMG00VNM` | 11 km |
| Tucumán `tuc0p` | Salta `UNSA00ARG` | 113 km |
| Kenting `ken0p` | Tainan `NCKU00TWN` | 137 km |
| São Paulo `sao0p` | Cachoeira Paulista `CHPG00BRA` | 196 km |
| Nairobi `nai0p` | Eldoret `MOIU00KEN` | 243 km |
| Dhaka `dha0p` | Shillong `SHLG00IND` | 258 km |
| KL University `klu0p` | Gadanki `GDKG00IND` | 366 km |
| Lagos `lag0p` | Accra `ACRG00GHA` | 418 km |

- Every pair is within 418 km, so the two see much the same sky (each one's pierce points at 30 deg or more lie within
  about 550 km of it). Local solar time differs by at most 15 minutes (Lagos-Accra, 3.6 deg of longitude); geographic
  latitude by at most 3.0 deg (KL University-Gadanki). Magnetic latitude was not computed; near the crests of the
  equatorial anomaly 3 deg can matter.
- For each judged receiver-hour, **R** is the partner station's `p95` in the same UTC hour of the same day. A
  receiver-hour whose partner has no `p95` that hour (no file, too few values) is not paired; the count is reported.
- Receiver-hour local solar time is UTC (middle of the hour) plus the receiver's longitude / 15.
- **Far pairs** (reported without marks): each station with no receiver within 500 km is paired with every receiver
  500-2,000 km away whose longitude is within 15 deg (local time within an hour). That gives Gabon-Lagos (992 km),
  Djibouti-Nairobi (1,574 km) and Djibouti-Malindi (1,641 km). This asks whether a station's ROTI says anything about
  a receiver that far away; it does not test the measure itself.

## 4. Checks

| # | Check | Holds if | Fails if |
|---|---|---|---|
| R1 | Pooled AUC of R, disturbed against quiet receiver-hours (all hours) | ≥ 0.80 | < 0.70 |
| R2 | The same, only receiver-hours at receiver local solar time 19:00–02:00 (needs 20 disturbed and 20 quiet pairs, else not judged) | ≥ 0.70 | < 0.60 |
| R3 | Chance test: labels shuffled 2,000 times within receiver × local-solar-hour strata (keeps place and time of day, breaks the day-to-day pairing); one-sided p of R1's AUC | p ≤ 0.01 | p > 0.05 |

Between the two marks the result is "weakened". The layer counts as validated only if R1, R2 and R3 all hold. The marks
are higher than the limb S4 check's (0.70 and 0.60) because these are direct measurements at or near the receivers, not
a regional value at a nominal place.

Reported without marks: the median R in disturbed and in quiet receiver-hours with a 95% interval (bootstrap over
receiver-days, 2,000 draws, seed 1); each pair's own AUC where it has 5 or more disturbed pairs; the AUC with the
station-hour `max` in place of `p95`; the AUC of `breaks`; R1 for the pairs within 250 km only; and the far pairs'
pooled AUC.

**Seeds:** R3 uses numpy's default generator with seed 1 (the limb check's `perm_p`).

## 5. Held-out days

**Days:** the limb S4 check's 25 days: every day from 16 Oct to 12 Nov 2026 except 7, 9 and 10 Nov. 13 and 14 Nov
(the engineering days) are not used; nor are 7, 9 and 10 Nov. A day whose ROTI file is missing, a station missing from
a day file, or a receiver-day with no eSWua records is skipped and reported, not replaced.

**Ground truth files:** the eSWua records for the 25 days were fetched for the limb check on 15 Nov 2026 (250 files,
10 receivers × 25 days) and are read from that cache, not fetched again.

**ROTI files:** the published `swx-data-2026-10` and `swx-data-2026-11` assets, made by the frozen method with
`ground-roti.yml` after this document is committed. Command:
`python tools/ground_roti_check.py check 2026-10-16:2026-11-06 2026-11-08 2026-11-11:2026-11-12 --ground <cache>`.

## 6. Results on the held-out days (run 15 Nov 2026, 19:29 UTC)

Sections 1–5 were committed in 366c39e (15 Nov 2026, 18:20 UTC) before any held-out day was made, and reached `main`
unchanged in 7d28456 (`tools/ground_roti.py`, `tools/ground_roti_check.py` and this document are byte for byte the
same in both). The 30 day files for 16 Oct – 14 Nov came from workflow run 43746680913 (`ground-roti.yml`,
`workflow_dispatch`, commit 7d28456; started 18:25 UTC, finished 19:18 UTC; the files' `as_of` runs from 18:27 to
19:18 UTC). The check ran at commit e906fb1, which changed only the collectors. Command:
`python tools/ground_roti_check.py check 2026-10-16:2026-11-06 2026-11-08 2026-11-11:2026-11-12 --ground data/eswua`.

**All three checks hold, so the layer is validated.**

| # | Check | Result | Verdict |
|---|---|---|---|
| R1 | Pooled AUC of R, disturbed against quiet receiver-hours | 0.887 (312 disturbed, 4,686 quiet) | holds |
| R2 | The same, at receiver local solar time 19:00–02:00 | 0.871 (294 disturbed, 1,134 quiet) | holds |
| R3 | Chance test, labels shuffled within receiver × local-solar-hour | p = 0.0005 (none of 2,000 shuffles reached 0.887) | holds |

**Counts.** 5,005 judged receiver-hours; 4,998 paired with the partner station's `p95` in the same hour; 7 unpaired.
Skipped receiver-days, 33 in all: no eSWua records for Hanoi on all 25 days, Lagos 24–27 Oct, and Nairobi 30–31 Oct and
8 Nov; one partner station missing from its day file, Shillong `SHLG00IND` on 26 Oct (so Dhaka that day). No day file
was missing. Stations missing from the held-out day files (not posted at BKG when the file was made): Seychelles
`SEY200SYC` 16–24 Oct, Shillong 26 Oct; every other day file has all 17 stations. No station failed to read. Malindi
`MAL200KEN` was read as compact RINEX 3.1 from 20 Oct on, and each of those files says so. On the days outside the test,
Shillong is missing on 9 Nov and Djibouti on 13 Nov.

**Reported without marks:**
- Median R: disturbed 0.893 TECU/min (95% interval 0.732–1.103), quiet 0.083 (0.079–0.088). These are ROTI values;
  they say nothing about S4 levels.
- AUC with the station-hour `max` in place of `p95`: 0.911.
- AUC of `breaks` (arc breaks above 30 deg): 0.749. Arc breaks rise in disturbed hours too, so slips and loss of lock
  carry part of the same signal.
- R1 for the pairs within 250 km only: 0.914 (3,406 pairs).
- Far pairs (Gabon–Lagos, Djibouti–Nairobi, Djibouti–Malindi): AUC 0.919 (1,526 pairs, 71 disturbed, none unpaired).
- Each pair's own AUC (5 or more disturbed pairs):

| eSWua receiver / IGS station | Distance | AUC | Disturbed | Quiet |
|---|---|---|---|---|
| Lagos / Accra `ACRG00GHA` | 418 km | 0.925 | 11 | 465 |
| Malindi / Malindi `MAL200KEN` | 0 km | 0.968 | 31 | 560 |
| Nairobi / Eldoret `MOIU00KEN` | 243 km | 0.946 | 29 | 423 |
| Tucumán / Salta `UNSA00ARG` | 113 km | 0.987 | 62 | 517 |
| São Paulo / Cachoeira Paulista `CHPG00BRA` | 196 km | 0.929 | 69 | 530 |
| Saba / Saba `SABY00BES` | 4 km | 0.873 | 42 | 551 |
| KL University / Gadanki `GDKG00IND` | 366 km | 0.845 | 36 | 504 |
| Dhaka / Shillong `SHLG00IND` | 258 km | 0.651 | 14 | 562 |
| Kenting / Tainan `NCKU00TWN` | 137 km | 0.887 | 18 | 574 |

Hanoi / Hanoi `HUMG00VNM` (11 km) had no eSWua records, so that pair was not tested. Dhaka / Shillong is the weakest
pair; Shillong sits about 2 deg north of Dhaka, and section 3 notes that magnetic latitude was not computed. Why that
pair is weaker was not tested.

**First day, for reference** (16 Oct 2026, 16 stations, 384 station-hours, all with a `p95`; median `p95` 0.086
TECU/min, median `n` 118.5): the largest hourly `p95` per station was Gabon 3.91 TECU/min at 19 UTC, Salta 3.13 at
03 UTC, Malindi 3.04 at 19 UTC, Eldoret 2.76 at 19 UTC, Djibouti 1.91 at 18 UTC, Accra 1.59 at 19 UTC, Cape Verde 1.23
at 21 UTC and Gadanki 1.01 at 17 UTC; Diego Garcia, Madagascar, Ascension, Hanoi, Tainan and Shillong stayed at or
below 0.16.

**What this shows and what it does not.** On 25 days in Oct–Nov 2026, a station's hourly ROTI `p95` is higher in the
hours when a scintillation receiver within 418 km sees L1 S4 of 0.5 or more, beyond what place and time of day explain
(R2, R3), and more so for the closer pairs. ROTI is a proxy for irregularities measured at fixed stations: it ranks
disturbed hours well, but it is not an estimate of the S4 a receiver there would measure, it is never read against S4
alert levels, and this test sets no ROTI level that means scintillation. The belt stations with no receiver nearby
(Cape Verde, Ascension, Seychelles, Madagascar, Diego Garcia) are covered by the method, not by this test; the far
pairs suggest that station ROTI tracks receivers 1,000–1,600 km away in the same longitudes, but they test the sky,
not the measure. One season (Oct–Nov 2026), nine tested pairs, low latitudes only (about 27°S to 26°N); no mid- or
high-latitude test, and no test of L-band scintillation other than L1.

## 7. What waits on review

- Adding the layer to the public map or to the `tic-feed/2` feed, after this validation, as for every earlier layer.
- The tic-dispatch schedule for `ground-roti.yml` (starts at :30 past 09–13, 16 and 22 UTC), prepared in the hub but not
  pushed, and the Worker deploy that would carry it. Until then the job runs on GitHub's own cron only.
