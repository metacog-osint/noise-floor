# Spoofing, made lighter: plan and procedure (16 Nov 2026)

**Why.** Finding spoofing every day is already cheap: the daily job on GitHub downloads the 3.7 GB adsb.lol archive,
runs the jamming analysis and the spoofing detector, and publishes, in about 5 minutes on a free runner. Testing a change
to the detector is not. The v0.6.1 step (`validation/spoofing-v061.md`, 15 Nov 2026) took 36 day-runs from the raw
archives (4–14 minutes each on 7 cores, about 3.5 hours), two Lima comparisons of 17 minutes each that reread the raw
traces, and 314 GB of raw archives kept on disk for 103 days. Each run reads about 77 million positions to find about
30,000 false ones, and every variant starts again from the raw archive. This plan cuts that cost without changing the
detector's method or weakening the checks that keep false alarms down.

Four parts. Parts 1, 2 and 4 are in `tools/spoof_day.py`, `tools/spoof_shadow.py` and `pipeline/daily_job.py`. Part 3 is
on the site, in `tools/spoof_site.py` (with the spoofing pages).

## 1. Shadow variants in the daily run

A candidate change is listed in `tools/spoof_shadow.json` (name, the detector constants it sets, from and until dates,
why, and the document that registers it). On each day it is due, the daily job:

1. runs `spoof_day.py run --cache` as usual (the published files are the default's, unchanged);
2. reruns each due variant from that day's cache (`spoof_day.py rerun --set ... --label NAME`), which re-scores only the
   cache's candidate aircraft;
3. compares each variant with the default (`spoof_shadow.py diff`) and uploads `<day>.spoof-shadow.json` beside the
   day's spoofing files.

The shadow file holds aggregates only, no aircraft identifiers: for the default and each variant, active and total
aircraft-hours by region group, episodes by class, kind and region group, control-box episodes, MLAT-tested and
MLAT-confirmed episodes; and what changed (episodes gone and new by class, region group and emitter category, and
MLAT-confirmed episodes lost). A failure in any of this is logged and skipped; the day publishes anyway.

To score a variant after some days:

```
gh release download pnt-data-2026-11 -R metacog-osint/noise-floor -p "*.spoof-shadow.json" -D shadow/
python tools/spoof_shadow.py score shadow/ --name NAME
```

`score` pools the days and applies the standing checks against the default on the same days: H1 (controls active share
≤ 0.01%), H2 (Middle East and Baltic ≥ 0.2% and ≥ 20× H1), H3 (MLAT-confirmed share ≥ 75%), H6 (control-box episodes
≤ 1.5× the default) and H8 (MLAT-confirmed episodes ≥ 98% of the default). Live days carry the controls, so false alarms
are measured as they happen, not only on the 12 historical days.

The first listed variant is v0.6 (`SLOW_HI_A2_FT` 25,000 ft), from 15 Nov to 15 Dec 2026. It changes nothing on the
site. It is a calibration: its differences from v0.6.1 are known (`validation/spoofing-v061.md`), so the daily shadow
files show the mechanism working and what it costs on GitHub.

## 2. The day cache

`spoof_day.py run DAY --cache DIR` also writes `DIR/DAY/`:

- `records.pkl.gz`: the finished records of every aircraft that is not a candidate;
- `cand-*.bin`: the raw trace files of the candidates, as read from the archive;
- `meta.json`: the archive's file names, size and SHA-256, counts, and the envelope below.

`spoof_day.py rerun DAY --cache DIR --out OUT [--set NAME=VALUE ...] [--label NAME]` re-scores the candidates with the
variant's settings, reuses every other record, and writes the same files as a full run (tables, events, summary). The
summary's version gains `+NAME` and a `rerun` block listing the settings.

**Candidates** (`candidate()`): aircraft of a category that can be tested (A2–A5, or none) with any ADS-B or MLAT position
at or above 10,000 ft under 200 kt, any 90 s at or above 10,000 ft within 6 km, or any jump of 10 km or more at an
implied 800 kt or more. An aircraft outside all of these can't hold a flagged position under any setting inside the
**envelope**, so its record is the same whatever the variant:

| Constant | Allowed in a rerun |
|---|---|
| `SLOW_KT`, `SLOW_HI_KT`, `SPEED_GS_KT` | ≤ 200 kt |
| `HIGH_ALT_FT`, `HIGH_ALT_A2_FT`, `SLOW_HI_FT`, `SPEED_FT` | ≥ 10,000 ft |
| `SLOW_HI_A2_FT` | 0 (off) or ≥ 10,000 ft |
| `LOITER_KM` | ≤ 6 km |
| `LOITER_S` | ≥ 90 s |
| `JUMP_KM`, `JUMP_KT` | ≥ 10 km, ≥ 800 kt |
| Episode, victim, class, replay and MLAT-check constants | any value |

A rerun refuses anything outside the envelope, and any constant that changes every aircraft's record (sampling,
resolutions, the fast-aircraft tests, NACp, kinematics, geometric altitude, the envelope itself). Those still need a
fresh run from the raw archive.

**Exactness test (15 Nov 2026), 20 Apr 2025** (52,233 trace files, 40,477 aircraft):
- 1,990 aircraft (4.9%) are candidates. The cache is 116 MB, against 2.4 GB of archive. Writing it added 7 s to the
  full run (331 s against 324 s on 7 workers).
- A rerun with no change took 56 s and reproduced the full run exactly: the same 371 episodes, field for field, and
  identical res-4, res-2 and daily tables.
- A rerun set to v0.6 (`--set SLOW_HI_A2_FT=25000`) reproduced the 15 Nov v0.6 full run of that day: the same 372
  episodes and identical tables. One summary list differed: the supporting indicator `geo_sat_trusted_res2_top`, at
  its 20th place, among regions tied at 4 aircraft. Records are now sorted before aggregation, so ties break the same
  way in every run.
- `tests/test_spoof_day.py` (`test_cache_rerun_and_shadow`) checks the same on a synthetic day, including the refusals.

**All 18 test days (16 Nov 2026).** The 12 held-out days and 7–12 Nov 2026 are cached in `data/spoof_cache/`
(local; 2.9 GB in all, 70–230 MB a day).
- **Exactness.** Each day's full run with `--cache` reproduced the 15 Nov v0.6.1 run from the raw archive
  (`data/spoofing_v061b`) on all 18 days: the same 8,844 episodes field for field, and identical res-4, res-2 and daily
  tables. The summaries differed only in the order of tied entries in two top-20 lists (`geo_sat_trusted_res2_top` on
  every day, `victim_res2_top` on three).
- **V1 rescored from the caches** (`rerun --set SLOW_HI_A2_FT=0 --label V1` on all 18 days) reproduced the 15 Nov V1
  run (`data/spoofing_v061a`): identical episodes and tables on every day, so H1–H8 are unchanged (H1 0.0023% of 15.2
  million control aircraft-hours, H2 0.397% and 0.904%, H3 568 of 618, H4 22 of 67, H5 Beirut, Beirut, Amman, H6 122,
  H7 0 of 12, H8 568). Lima (`tools/spoof_compare.py --cache-root`): P1 12 of 14 and P2 47 of 56, and all 56 flights
  have the same placed, counted and placeable values. Five unmatched flights' reasons now read "aircraft not in the
  archive (or not a cache candidate)", as expected.
- **One cache was faulty, and was fixed.** 2025-05-10 first scored 783 episodes instead of 431. Its folder held a
  second, partial set of candidate shards (1,666 traces, all duplicates of the 2,038 real ones), left by a second run
  of the same day writing into the same folder when the build was restarted. A rerun reads every shard, so those
  aircraft were scored twice. With the stale shards moved aside, the day reproduces exactly, under V1 and under the
  default. Guards follow: a rerun will refuse a cache whose shards don't hold exactly the candidates in `meta.json`,
  and a cache build will no longer share a folder with another run.
- **Time.** End to end the V1 rescore took 2 h 46 min (18 reruns 9,433 s, held-out score 154 s, Lima 391 s), but the
  PC was running other heavy jobs throughout, and the faulty day alone took 2,300 s. Reran on its own after the fix,
  that day took 137 s against 1,038 s for its full run. Wall time on a shared PC is not a cost figure. Measured again
  the same day with CPU time and one command (`tools/spoof_variant.py`, "Proof and timing" below): 929 s for all 18
  days from the format-2 caches, 1,489 s of CPU.
- **On GitHub.** A variant's held-out score now runs on GitHub Actions instead of the PC
  (`.github/workflows/spoof-variant.yml`, Run workflow with `set` and `label`). The caches and the H6 baseline's
  events hold ICAO addresses, so they are in a private release, uploaded with `tools/spoof_cache_release.py` and read
  with a read-only token; only aggregate scores leave the job. The Lima check stays on the PC.
- **Raw archives.** 102 of the 103 day archives in `data/raw/trace_box/` are still published by adsb.lol with the
  same file names and sizes, so they could be downloaded again (the 103rd is an unfinished local download).

**Held-out days:** each of the 12 held-out days and 7–12 Nov 2026 is cached once from the raw archive
(`data/spoof_cache/`, local). After that, a variant's held-out score is 18 reruns and `tools/spoof_heldout.py` on their
output, with no raw archive. `tools/spoof_compare.py --cache-root` reads the Lima flights' traces from the caches
(candidates only; a flight whose aircraft is not a candidate had no slow, near-stationary or jumping position at
altitude, so it can't be placed or counted anyway). Whether to delete the raw archives once the caches exist is Tom's
decision; the caches can't rebuild a day for settings outside the envelope.

**Scoring a variant in one command (16 Nov 2026).** `python tools/spoof_variant.py --set NAME=VALUE ... --label L --out DIR
--baseline DIR [--reference DIR] [--outside DIR --at=LAT,LON]` takes the heavy-job lock, reruns the days from the caches
(`--cache`, default `data/spoof_cache`; `--days`, default the 18 test days), then scores the held-out days (H1–H6 from
`spoof_heldout.py`; H7, the A2 rule-A control-box episodes of v0.6's review still present, from
`<baseline>/new_controls.json`; H8, MLAT-confirmed episodes at least 98% of the baseline's), the outside list at the place
(P1, P2; `spoof_compare.py --cache-root --v06`) and, with `--reference`, checks the output against an earlier one with
`tools/spoof_same.py` (events as sorted JSON, the three parquet tables sorted on every column, the summary minus timing
and provenance keys, and the `*_top` lists classed same, tie-order, tie-at-cut or differs; exit 1 on a real difference).
One report JSON (`<out>/variant_report.json`) holds, per day, wall, CPU and read seconds, candidates, aircraft and
episodes, the totals, and every score; it has counts only, never an ICAO address or the outside folder's path, which is
always an argument. Summaries of `run` and `rerun` now carry `cpu_seconds` (the main process plus every pool worker);
compare that, not wall time, on this shared PC. A rerun's summary adds `seconds_parts` (`records_load`, `scoring`,
`shard_file_read`) and `cache_format`. `rerun` and `cache-convert` refuse a day whose shards hold a different number of
candidate traces than `meta.json` says: the 2025-05-10 cache held shards of two overlapping builds, and its V1 rescore
gave 783 episodes and 51,597 aircraft against 431 and 49,931 in the raw run (a difference `spoof_same.py` finds at once).
`run --cache` now builds in `<cache>.building`, made exclusively (a second build of the same day stops with a message), and
moves the finished folder into place whole.

**Where a cached rerun spends its time, and the format-2 cache.** For 20 Feb 2024 (V1, 1,608 candidates, one pass, other
jobs running): loading the 41,257 records from `records.pkl.gz` takes about 5 s (0.45 s gunzip, 4.2 s unpickle); scoring
the candidates takes about 31 s of CPU spread over the workers, of which gunzip, JSON parsing and `parse_trace` are 37%;
`aggregate()` over all records takes about 22 s in the main process and writing the tables and summary more, which a cache
can't shorten: after the reruns of 16 Nov it is about half of the 18-day rerun time (390–405 s of 790–910 s).
`python tools/spoof_day.py cache-convert DAY... --cache OLD_ROOT --to NEW_ROOT` writes format-2 caches into a new root
(the old one is only read; it refuses to write over it): `records.pkl.zst` (the same pickle, zstd) and `cand2-*.bin` (each
candidate parsed once by `parse_trace` and pickled, zstd, so a worker skips gunzip, JSON parsing and `parse_trace`), plus
a copy of the raw `cand-*.bin` shards that `spoof_compare.py --cache-root` still reads. `rerun` reads either format. Size:
2.9 GB for the 18 old caches, 4.6 GB for the new root. Converting took 861 s. A one-day A/B on 20 Feb 2024 (warm files):
CPU 69.4 and 70.0 s against 58.9 and 59.2 s, wall 47–48 s against 42–44 s.

**Proof and timing, 18 days, V1** (`--set SLOW_HI_A2_FT=0 --label V1`, one command each, on the PC with other jobs
running: a Norway AIS collector, two Cordon history jobs, an NSF measurement, a check run; the first run also had a
COP event backfill). Reruns from the format-2 caches equal reruns from the format-1 caches on all 18 days: no real
difference in events, tables or summaries; tie order in a `*_top` list differs on 3 days between formats (and on 2 to 18
days between any two runs: `victim_res2_top` is built from sets of strings, whose order changes with the process's hash
seed; `sorted()` there would make runs identical). Every run equals the raw V1 run (`data/spoofing_v061a`) on all 18 days.

| 18 days, 7 workers | Format 1, run 1 | Format 1, run 2 | Format 2 |
|---|---|---|---|
| Reruns, wall | 1,469 s | 910 s | 792 s |
| Reruns, CPU | 2,302 s | 1,966 s | 1,489 s |
| Of it records load / scoring / shard reading (wall) | 212 / 661 / 435 s | 146 / 375 / 162 s | 59 / 329 / 181 s |
| Aggregation and writing (wall) | 596 s | 389 s | 405 s |
| Held-out score, outside score, reference check | 25 / 82 / 20 s | 23 / 77 / 16 s | 24 / 78 / 17 s |
| Whole command | 1,625 s | 1,043 s | 929 s |

Run 2 against the format-2 run is the like-for-like pair (the same load): CPU −24%, wall −13%, reading −25%. Scores of
all three: H1 0.0023% of 15.2 million control aircraft-hours, H2 0.397% and 0.904%, H3 568 of 618, H4 22 of 67, H5 Beirut,
Beirut, Amman, H6 122 (baseline 134), H7 0 of 12, H8 568 (at least 557); Lima P1 12 of 14, P2 47 of 56 — the 15 Nov V1
scores. The next saving is not in the cache format but in `aggregate()`: a stored partial aggregate of the non-candidate
records would remove most of the 400 s, but the geo-outlier columns depend on every aircraft in a hex-hour, so it needs
its own exactness test.

**Heavy-job lock** (`tools/heavy_lock.py`). Heavy local jobs take one machine-wide lock and wait, with a message every
minute naming the holder, while another holds it: `spoof_variant.py`, and `spoof_day.py run`, `rerun` and `cache-convert`
for more than one day (`--no-lock` skips it). The lock is a file made with O_EXCL in `$TIC_HEAVY_LOCK_DIR`, else
`%LOCALAPPDATA%\tic-heavy` (`$XDG_STATE_HOME/tic-heavy` elsewhere); it holds the holder's PID and start time, and a waiter
removes a lock whose process has gone or whose PID now belongs to another process; a live holder is never removed
(`heavy_lock.py status`, `clear-stale`, `release --force`). A child of the holder sees `TIC_HEAVY_LOCK_TOKEN` and doesn't wait
for its parent. Another project's heavy job adopts it by running under `python tools/heavy_lock.py run --label NAME -- COMMAND`
or by copying that one file (standard library only) and wrapping its main in `with heavy_lock.hold("NAME"):`. A job that
doesn't adopt it still competes: on 15–16 Nov the cached V1 rescore took 9,978 s while other jobs ran, 2025-05-10 alone 2,300 s.

## 3. A daily spoofing indicator by place

The places that spoofers send aircraft to are stable from day to day: Beirut, Amman, Lima, the Romanian ring. The
spoofing pages follow them from day to day already (`tools/spoof_site.py track()`, from the published
`<day>.spoof-targets.json`). Each followed place now also gets its own **usual level**: the median number of aircraft
shown there a day over up to 30 earlier days with a targets file (0 on days it wasn't used), once 7 such days exist. The
newest day reads **above** (at least twice usual and 3 or more aircraft over it), **below** (half or less and 3 or more
under it) or **near**. The total over all places gets the same reading. A place used on no earlier day is "new" and is
left to the new-places list.

- Trends page: one line above the places table (the total against its usual level, and the places above theirs), and an
  "Against usual" column.
- Board (`board.json` → spoofing → `place_levels`) and the COP feed: each place above its usual level is an
  observation, tier anomaly, placed where that day's aircraft really were (`noisefloor-spoof-above-<day>-<n>`).

**Regions (16 Nov 2026).** The same reading for the regions where aircraft really were: each H3 res-2 region's
aircraft-hours in active spoofing episodes (`share2`) against its median on up to 30 earlier days with regional shares
(0 when it had none), with the same above and below rule (`tools/spoof_site.py region_levels()`), except that from
16 Nov 2026 above needs 5 or more spoofed aircraft-hours over usual (the region floor below). On the map it is a
bold dashed outline, in the new Spoofing view (Measure → Spoofing, `m=spf`), which turns off the GPS-error colours,
keys the regions, lists where each region's aircraft were shown (`sent2`), pools 7 days on request (`share2_7`) and
ranks the regions in the table under the map. The board's `region_levels` gives the Today page one sentence, and up to
five regions above their usual level go to the COP feed (`noisefloor-spoof-region-above-<day>-<n>`, tier anomaly). On
14 Nov 2026, with 7 earlier days, 13 regions read above (largest rises near Tver, Doha and Tallinn), and all regions
together read near usual (487 spoofed aircraft-hours against 442).

**Region floor (pre-registered 16 Nov 2026, before any scoring).** On 15 Nov 2026 the three regions read above stood
on 9, 6 and 3 spoofed aircraft-hours, against usual levels of 1, 2.5 and 0. Tom agreed (16 Nov 2026) that a region
should read **above** only when it is at least twice its usual level **and 5 or more** spoofed aircraft-hours over it
(was 3). The **below** rule, the places' rule (section 3 above) and the all-regions total keep 3. The test, written
before it is run:

- Data: every published `<day>.spoof.json` with `share2` that has at least 7 earlier such days. On 16 Nov 2026 that is
  14 and 15 Nov only, so the first scoring is a description, not a verdict. The test is run again on the first day with
  30 earlier days of `share2`, about 7 Dec 2026, and its result is written here.
- Measures, for the old rule (3) and the new one (5): above readings per day; above readings whose region centre lies
  in a quiet control box (`tools/spoof_day.py REGIONS`, kind "control"); above readings in the validation's spoofing
  groups (Middle East, Baltic and W Russia, Black Sea); for each reading the new rule drops, its rise (spoofed
  aircraft-hours minus usual) and whether the region reads above again (under the old rule) on the next day.
- P1 (noise): the new rule gives no more control-box readings than the old one.
- P2 (signal kept): the new rule keeps at least half of the old rule's readings in the spoofing groups.
- P3 (persistence, at the 30-day run only): readings the new rule drops are above again the next day less often than
  readings it keeps.
- Decision: the new rule goes live now. If P2 or P3 fails at the 30-day run, the result goes to Tom with the old rule
  as the alternative; nothing is changed back without his call.

First scoring (16 Nov 2026, after the commit above; 9 published days with `share2`, 7-15 Nov, so levels on 14 and 15
Nov only). Above readings: 16 under the old rule, 7 under the new one (14 Nov 13 → 6; 15 Nov 3 → 1). Control boxes: 0
and 0 (P1 holds). Spoofing groups: 5 and 5, none dropped (P2 holds). The 9 dropped readings all rose by 3 to 4
spoofed aircraft-hours, all outside the validation's boxes: central Turkey (twice), the Syrian desert east of Damascus,
Istanbul, east of Moscow, the Oman coast, the UAE interior and two regions of central India. Persistence, from the one
pair of days: 1 of 7 dropped readings and 1 of 6 kept ones were above again the next day, so P3 can't be judged yet.
Below and near readings were the same under both rules on both days, as they must be.

**Verdict (16 Nov 2026, evening).** The `share2` backfill (backfill.yml `spoofing_only`, run 43919624652, 7 Oct-6 Nov
redone as v0.6.1) gave 40 published days with `share2`, 7 Oct-15 Nov, so 33 days have at least 7 earlier ones (14 Oct-
15 Nov) and 15 Nov has the full 30: this is the 30-day run. Each day's usual level is the median of up to 30 earlier
days, so the October days rest on fewer. Scored with the same code as above (`spoof_site.region_levels()`, old rule
`min_over=3` against new `min_over=5`) on the files as published.
- Above readings: 451 under the old rule, 282 under the new one (169 dropped; every dropped reading rose by 3 to 4.5
  spoofed aircraft-hours, in regions of 11 to 7,326 aircraft-hours). Below and near readings were the same under both
  rules on every day.
- **P1 (noise): holds.** Control-box readings 39 → 16. The 16 left are in two boxes: us_west 9 (6 of them in the region
  centred near 35.5° N, 106.2° W in New Mexico, 5-10 aircraft-hours against a usual of 0) and c_europe 7 (4 near
  49.5° N, 14.1° E, 2 near 50.1° N, 9.9° E, 1 near 50.5° N, 5.7° E; 5-11 against usual 0-2). Whether these are announced tests or detector
  noise is not checked here.
- **P2 (signal kept): holds.** Readings in the spoofing groups 160 → 122 (76% kept; the test needs 50%). Of the 169
  dropped: 89 elsewhere, 23 control, 19 South Asia, 14 Middle East, 13 Black Sea, 11 Baltic and W Russia.
- **P3 (persistence): holds.** Dropped readings were above again the next day (old rule) 44 times in 166, 27%; kept
  readings 111 in 280, 40%. (Not pre-registered, for scale only: Fisher's exact test, odds ratio 0.55, p = 0.005.)
- The 14-15 Nov figures in the first scoring changed because those days now have up to 30 earlier days, not 7
  (14 Nov 16 → 11, 15 Nov 5 → 2).
- Decision: the new rule (`REGION_MIN_OVER = 5`) stays, as pre-registered. The 7 Dec recheck is no longer needed for
  the verdict; run then, it is an out-of-sample check on the 21 days after this one.

This needs no new processing: it reads the files the daily run already publishes. It answers the analyst's question
(is spoofing happening, where, and more than usual?) in one line. The detector stays as the engine underneath. Like the
new-places list, it compares a place with its own normal, and is not a warning.

## 4. A lighter test procedure

From now on, a change to the spoofing detector goes through these steps:

1. **Batch small fixes.** Collect fixes that touch the same rule into one step, not one pre-registration each.
2. **Pre-register one variant** unless the evidence leaves two genuinely open. The pass marks are the standing H1–H6 and
   H8 (and any check specific to the change), fixed before any run, as before.
3. **If the change is inside the envelope:** score it on the cached held-out days (18 reruns, no raw archive) and, at
   the same time, list it in `tools/spoof_shadow.json` for 14 or more daily days. Adoption needs both to pass.
4. **If it is outside the envelope** (a new rule, a fast-aircraft or sampling change): a fresh run from the raw archives
   is still needed on the held-out days, so make the case for it in the pre-registration. If the new rule is
   expected to recur, widen the envelope in the same step, rebuild the caches once, and use them after that.
5. **Lima-type outside checks** stay reported, not gating, and run from the caches.

Expected cost of an envelope change: 18 reruns of a few minutes each, plus a scoring command over files the daily run
already published, against about 3.5 hours of PC time and the raw archives on disk.
