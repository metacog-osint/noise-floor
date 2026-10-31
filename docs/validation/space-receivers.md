# GNSS receivers in orbit: Sentinel-6A and COSMIC-2 (pre-registration, 31 Oct 2026)

**Lanes:** steps P and C of `docs/space-sensors-plan.md`.
**Tools:**
- `tools/s6_rfi.py` (Sentinel-6A), `tools/cosmic2_rfi.py` (COSMIC-2);
- `tools/rx_rfi.py`, the shared signal-strength index;
- tests `tests/test_rx_rfi.py` and `tests/test_cosmic2_rfi.py`.

**Reference:** the aircraft map's H3 res-4 daily tables, aggregated to res 2 (about 300 km across). The pairing rules
are the CYGNSS lane's: 20+ aircraft in a cell; "jammed" at a GPSJam-style share of 10% or more, "clean" below 2%.

## 1. What each lane measures

**Sentinel-6A** (66° inclination, about 1,340 km altitude):
- Source: PO.DAAC's hourly RINEX from the TriG receiver's RO-POD antenna, at 1 Hz.
- Each link's GPS L1 C/A signal strength (V/V, converted to dB) is compared with the median for its 5° elevation bin
  over the same day.
- The epoch index is the median of those residuals over the epoch's links (at least four, at 10° elevation or more).
- An epoch counts as "down" when the index is −2 dB or lower.

**COSMIC-2** (24° inclination, about 550 km):
- Source: UCAR's own per-antenna RFI index (`podTc2`, threshold 1e-4) for each of the two navigation antennas.
- One antenna looks forward along the track, the other backward.

**Both lanes:**
- **Bins:** 10 s bins per receiver give a flagged share.
- **Back-projection:** each H3 res-2 cell is scored by the correlation, across bins, between "this bin's satellite
  could see the cell" (within a radius R of the sub-satellite point) and the bin's flagged share.
- **Why a correlation:** the offline test shows the plain flagged share drifts toward the edge of coverage.
- **COSMIC-2 latitude limit:** for an emitter poleward of COSMIC-2's orbit, latitude trades off against detection
  range; longitude holds.

## 2. Tuning on the six CYGNSS in-sample days

Days: 2 Jan, 24 Feb, 9, 10 and 16 May, and 19 Oct 2026.

**Sentinel-6A.** Twelve settings were tried: thresholds of 1, 1.5, 2 and 3 dB, each with radii of 2,000, 3,000 and
3,800 km. The pooled AUC ran from 0.676 to 0.957. The chosen setting, 2 dB at 3,800 km (the horizon), gave:

| Measure | In-sample |
|---|---|
| Paired cell-days | 5,123 (151 jammed, 4,839 clean) |
| Pooled AUC | 0.957 |
| Lowest leave-one-region-out AUC | 0.948 |
| Clean cells' 95th-percentile score (the frozen control threshold T) | 0.2409 |
| Control-box cell-days at or above T | 0.0% (1,776 cell-days) |
| Spearman with CYGNSS (res-2 median excess), shared cells | 0.477 (21,753) |

**Regions (in-sample):**
- Eastern Europe, Baltic to Black Sea: 116 jammed cell-days, own AUC 0.966.
- Gulf: 26 cell-days, own AUC 0.963.
- Myanmar: 6 cell-days, own AUC 0.748.
- Western Siberia: 2 cell-days.
- India–Pakistan border: 1 cell-day.

**COSMIC-2.** Section 4 is written once its last two tuning days are in.

## 3. Sentinel-6A: frozen method and checks on held-out days

Written and committed before any held-out Sentinel-6A day was fetched.

- **Days:** the CYGNSS held-out days (`docs/validation/cygnss.md` §8.1). That is every 19th day from 1 Oct 2025:
  2025-10-01, 10-20, 11-08, 11-27, 12-16; 2026-01-04, 01-23, 02-11, 03-02, 03-21, 04-09, 04-28, 05-17, 06-05, 06-24,
  07-13, 08-01, 08-20, 09-08, 09-27, 10-16. A day without files, or without geometry, is skipped and reported, not
  replaced.
- **Method:** `tools/s6_rfi.py` and `tools/rx_rfi.py` as committed with this document:
  - signal S1C; 5° bins; 10° mask; four links;
  - "down" at −2 dB; 10 s bins;
  - R = 3,800 km; res 2; a cell is judged from 30 bins (`MIN_VIS`).

| # | Check | In-sample | Holds if | Fails if |
|---|---|---|---|---|
| S1 | Pooled AUC, jammed vs clean cell-days | 0.957 | ≥ 0.85 | < 0.75 |
| S2 | Leave-one-region-out AUC (every judged region; `cygnss_checks.region_heldout` rules) | 0.948 | every value ≥ 0.80 | any value < 0.70 |
| S3 | Control-box cell-days at or above T = 0.2409 | 0.0% | ≤ 5% | > 15% |
| S4 | Spearman with CYGNSS on shared cells | 0.477 | ≥ 0.30 | < 0.15 |

Between the two marks the result is "weakened". Each region's own AUC is reported too, without a mark.

## 4. COSMIC-2: frozen method and checks

Written and committed on 31 Oct 2026, before any held-out COSMIC-2 day was fetched.

**Tuning on the six days.**
- Radii of 1,500, 2,000 and 2,500 km were tried, each with and without the fore/aft split. Pooled AUC ran from 0.881 to 0.966; the split helped at every radius.
- **Chosen:** 2,500 km with the split (each antenna sees only the cells on its own side of the satellite).
- **Why not the best AUC:** 1,500 km scores higher (0.966), but judges only 36 jammed cell-days, because it doesn't reach the Levant or the northern Gulf. 2,500 km judges 77.

| Measure (2,500 km, split) | In-sample |
|---|---|
| Paired cell-days | 3,926 (77 jammed, 3,764 clean) |
| Pooled AUC | 0.922 |
| Lowest leave-one-region-out AUC | 0.895 |
| Clean cells' 95th-percentile score (frozen control threshold T) | 0.23 |
| Control-box cell-days at or above T | 0.0% (1,776) |
| Spearman with CYGNSS, shared cells | 0.305 (21,753) |

**Regions (in-sample):**
- Eastern Mediterranean and Black Sea edge: 44 cell-days, own AUC 0.871.
- Gulf: 26 cell-days, own AUC 0.999.
- Myanmar: 6 cell-days, own AUC 0.979.
- India–Pakistan border: 1 cell-day.

**Satellites delivering data:**
- Five of six on 2 Jan (C2E1, 2, 4, 5, 6).
- Four from 24 Feb to 16 May (C2E2, 4, 5, 6).
- Three on 19 Oct (C2E2, 5, 6).
- C2E3 delivered nothing on any tuning day.

**Frozen method:** `tools/cosmic2_rfi.py` as committed with this section:
- UCAR's threshold 1e-4; 10 s bins;
- radius 2,500 km with the fore/aft split;
- res 2, cells within 60° latitude, judged from 30 bins.

**Days:** the same 21 held-out days as section 3. A day without a `podTc2` archive is skipped and reported.

| # | Check | In-sample | Holds if | Fails if |
|---|---|---|---|---|
| C1 | Pooled AUC, jammed vs clean cell-days | 0.922 | ≥ 0.85 | < 0.75 |
| C2 | Leave-one-region-out AUC (every judged region) | 0.895 | every value ≥ 0.80 | any value < 0.70 |
| C3 | Control-box cell-days at or above T = 0.23 | 0.0% | ≤ 5% | > 15% |
| C4 | Spearman with CYGNSS on shared cells | 0.305 | ≥ 0.20 | < 0.10 |
| C5 | Change: mean score of Persian Gulf box cells on the spring held-out days (2 Mar, 21 Mar, 9 Apr, 28 Apr, 17 May 2026) minus the mean on the winter ones (1 Oct 2025 to 11 Feb 2026, eight days) | not measurable in-sample | ≥ +0.05 | < 0 |

Between the marks the result is "weakened". Check C5 is also run on Sentinel-6A, as a report without a mark, because
its checks were frozen before C5 was written.

## 5. Results

### 5.1 Sentinel-6A on the 21 held-out days (run 31 Oct 2026): all four checks hold

All 21 days had files and geometry. BKG refused connections that afternoon, so broadcast navigation came from the
fallback in `tools/sentinel_gnss.fetch_nav`; the method is otherwise as frozen in section 3.

| # | Check | Held-out | In-sample | Verdict |
|---|---|---|---|---|
| S1 | Pooled AUC (407 jammed, 16,874 clean cell-days) | **0.956** | 0.957 | **holds** (≥ 0.85) |
| S2 | Lowest leave-one-region-out AUC | **0.918** | 0.948 | **holds** (≥ 0.80) |
| S3 | Control-box cell-days at or above T = 0.2409 (6,216) | **0.0%** | 0.0% | **holds** (≤ 5%) |
| S4 | Spearman with CYGNSS, shared cells (76,369) | **0.504** | 0.477 | **holds** (≥ 0.30) |

**Regions (held-out),** with each region's own AUC and the AUC with it left out:

| Region | Jammed cell-days | Days | Own AUC | AUC without it |
|---|---|---|---|---|
| Eastern Europe, Baltic to Black Sea | 348 | 21 | 0.967 | 0.918 |
| Gulf | 33 | 7 | 0.946 | 0.962 |
| Myanmar | 19 | 15 | 0.798 | 0.968 |
| Red Sea | 2 | 2 | 0.750 | 0.957 |
| India–Pakistan border | 2 | 2 | 0.984 | 0.959 |
| Western Siberia | 2 | 2 | 0.956 | 0.956 |
| Off Libya | 1 | 1 | 0.920 | 0.956 |

**What this shows.**
- Sentinel-6A's own receiver separates aircraft-jammed regions from clean ones, day by day, as well as CYGNSS does.
- It reaches 66°N, so it covers the Baltic, which CYGNSS and COSMIC-2 can't see.

**Change in the Gulf** (the measure frozen later as COSMIC-2's C5; reported here without a mark, 31 Oct).
- **Winter vs spring:** mean score of the Persian Gulf box's 8 cells was 0.207 on the eight winter held-out days and
  0.201 on the five spring days, a difference of **−0.006**.
- **Day by day:** winter days ran 0.151–0.308, spring days 0.140–0.307.
- **Reading:** Sentinel-6A rates the Gulf as raised all year. It doesn't show the spring 2026 surge that the aircraft
  (0.5% to 39–53%) and CYGNSS recorded. It places a region, but on this evidence it doesn't track change there.

**What it doesn't show.**
- The score is smooth over the 3,800 km radius, so it places interference by region, not by site.
- It doesn't track the Gulf's spring change (above).
- Eastern Europe dominates the jammed cells (348 of 407). Leaving it out still gives 0.918.
- Myanmar is weaker (own AUC 0.80).
- A map layer needs Tom's yes (plan step P, as for the other lanes).
