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

**All 18 test days** (the 12 held-out days and 7–12 Nov 2026) are being cached from the raw archives (started 15 Nov 2026, 18:53 CST; `data/spoof_cache/build_all.sh`, local). Still to do once they are: check each day's full-run output against the 15 Nov v0.6.1 V2 output (`data/spoofing_v061b`), rerun V1 (`--set SLOW_HI_A2_FT=0`) from the caches and score it with `tools/spoof_heldout.py` and `tools/spoof_compare.py --cache-root` against the 15 Nov results, and record the time it takes.

**Held-out days:** each of the 12 held-out days and 7–12 Nov 2026 is cached once from the raw archive
(`data/spoof_cache/`, local). After that, a variant's held-out score is 18 reruns and `tools/spoof_heldout.py` on their
output, with no raw archive. `tools/spoof_compare.py --cache-root` reads the Lima flights' traces from the caches
(candidates only; a flight whose aircraft is not a candidate had no slow, near-stationary or jumping position at
altitude, so it can't be placed or counted anyway). Whether to delete the raw archives once the caches exist is Tom's
decision; the caches can't rebuild a day for settings outside the envelope.

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
