# NISAR L-band lane: validation (21 Oct 2026)

**Lane:** `nisar/` (see `nisar/README.md`). **Data:** NISAR GCOV and RSLC products from ASF DAAC: BETA (Oct 2025 – Jan 2026) and PROVISIONAL (17 Jun 2026 onward). **Known answer:** the jammer about 50 km SW of Shiraz, Iran (27.32°N 52.87°E), from GPS World, "Converging on the jammer" (Sean Gorman, 18 May 2026). The article places it from independent signals intelligence, on at 8 and 20 Jan 2026 and off at 27 Dec 2025, on track 157 ascending, frame 15.

**The published location is internally inconsistent (found 22 Oct 2026).** The article gives both "27.32°N, 52.87°E" and "roughly 50 km southwest of Shiraz", but that coordinate is 257 km south of Shiraz city (29.61°N 52.54°E), near the Gulf coast. One of the two is wrong, and the article doesn't say which. Everything below was scored against the coordinate. A re-score against the other reading is in section 1. Until the author confirms the position, this is a weaker known answer than it looked.

Detections outside the published case stay in the private outputs until the method is validated.

## Bottom line

- **The image method fails the known answer** on the published BETA dates.
  - 56 detections at 30 sites over 6 passes.
  - None within 50 km of the jammer; 21 on the date it was off.
  - It is kept only for BETA products and treated as unvalidated.
- **The table method works mechanically.** It reads the RSLC processor's own RFI tables. On 40 PROVISIONAL passes of the area (18 Jun – 19 Oct 2026, three geometries):
  - every pass was read;
  - 32 passes were downloaded, 2.9 GB in all (median 88 MB);
  - positions agree with the catalogue footprints;
  - strong detections repeat from pass to pass within 9–24 km, and one site agrees across ascending and descending geometries.
- **The known answer isn't confirmed on PROVISIONAL data.**
  - The published site was inside the swath on all 40 passes.
  - No HIGH or MEDIUM detection fell within 50 km of it; the nearest candidate is a LOW 30 km away.
  - Either the jammer was off or had moved after January, or the method misses it. These data can't separate the two.
  - So the table method is **plausible but not validated against ground truth**. Its outputs stay private.
- **Broadband detector (section 5) passes its first positive control.** In an area with documented L1/L2/L5 jamming, where the tone method saw nothing at the L2 centre, it detects on 12 of 13 covering passes. It stays near zero in forested regions without reported jamming.
- **Next:** a surveyed emitter or an announced GPS interference test (NOTAM with place, time and band) to measure position accuracy.

## 1. Image method on BETA products: failed

**Run:** `nisar/validation/shiraz.json` covered six GCOV granules: track 157 ascending, frames 15–16, on 27 Dec, 8 Jan and 20 Jan. All were 20+5 MHz HH+HV.

| Check | Result | Verdict |
|---|---|---|
| A site at the jammer on 8 and 20 Jan | Nearest detection 50.8 km away (20 Jan); none within 50 km on either date | **Fail** |
| Nothing at the jammer on 27 Dec | 21 detections elsewhere in the frames on that date | **Fail** (false alarms) |
| Overall | 56 detections at 30 sites over 6 passes | Not usable as built |
| Re-score against "about 50 km SW of Shiraz" (22 Oct 2026) | The passes reach 30.05°N, so they cover it. Detections fall 16–26 km from Shiraz city and from a point 50 km SW of it on **all three** dates, including 27 Dec, when the jammer was reported off | **No pass either:** a persistent source near Shiraz, not the reported on/off pattern |

**What the processor itself says.** BETA products ran ST-EVD detection with mitigation disabled, and report the fraction of blocks flagged per channel:

| Date | Band A (HH / HV) | Band B (HH / HV) |
|---|---|---|
| 27 Dec 2025 (off) | 0.04% / 0.02% | 9.9% / 38.3% |
| 8 Jan 2026 (on) | 0.05% / 0.10% | 28.1% / 60.9% |
| 20 Jan 2026 (on) | 0.05% / 0.10% | 11.4% / 42.7% |

(Frame 15. Frame 16 shows the same pattern at lower levels.) On this frame the processor flags band B (1291–1296 MHz) far more than band A (1219–1239 MHz, which contains GPS L2), and band B rises on 8 Jan but falls back on 20 Jan, though the jammer was reported on both dates. Any re-tuning of the image method should start from that rather than assume a band-A signature.

**BETA RSLCs carry no per-block RFI tables,** because those are written only by tone-rank, so the table method can't run on the published dates.

## 2. Processor RFI tables in PROVISIONAL products

PROVISIONAL products run **tone-rank** detection and mitigation. These checks come from probing GCOV and RSLC granules on 21 Oct 2026, in two regions.

- **The QA `rfiLikelihood` is the maximum interference-to-signal ratio over blocks,** not a 0–1 fraction (isce3 `nisar/workflows/focus.py`, `rfi_likelihood = np.max(isr)`).
  - Values range from about 1 to 10^18 across a 30-day sample of 428 granules.
  - The extreme values come from blocks whose signal estimate is near zero.
  - So it works as a coarse screen, not a detector.
- **The RSLC tables are present and complete.** Each pass carries per-block ISR, signal mean and a 1024-bin pulse-hit share over the sub-band (band A 1217.0–1241.0 MHz, band B 1290.5–1296.5 MHz). They are stored contiguous and uncompressed.
- **Geolocation is consistent with the catalogue.** Table corners turned into ground positions from the product's orbit land within a few hundredths of a degree of the CMR footprint polygons.
- **Two tones appear in every pass checked:** 1233.125 MHz (band A) and 1296.002 MHz (band B), hit in roughly 30–90% of blocks in most channels, in both regions. They are treated as the radar's own and excluded (±0.15 MHz; they leak into bins about 0.1 MHz either side).
- **Interference is confined in range.** On the strongest Shiraz-frame detection, the strongest azimuth row was hot in 14 of 53 range blocks (about 55–90 km of a ~160 km slant-range span). One pass gives a position estimate, not just a bearing.

## 3. Table method on PROVISIONAL products, Shiraz area

**Run:** `nisar/validation/shiraz_provisional.json`, table method, terrain height 1,500 m. The 40 GCOV/RSLC pairs are tracks 56 and 157 ascending (01:43–01:52Z) and track 107 descending (15:12Z), all 20+5 MHz. All 40 had the table read: 32 downloaded and 8 from earlier probes.

| Check | Result | Verdict |
|---|---|---|
| Published site inside the swath | 40 of 40 passes (orbit geometry, site at 1,500 m) | Covered |
| Detection at the published site | No HIGH/MEDIUM within 50 km; nearest LOW 30 km (5 blocks, HV only, 53% of pulses, 1.4 dB) | **Not confirmed** |
| Detections overall | 94 at 46 sites: 20 HIGH, 34 MEDIUM, 40 LOW. 92 in band A (all with energy in the GPS L2 main lobe), 2 in band B | Many candidates; see the rule change below |
| Repeatability, strongest site | 10 HIGH/MEDIUM detections, all within 24 km of the site centroid | Consistent |
| Cross-geometry agreement | A site with the same three-tone signature, seen from track 107 (twice) and track 157: three detections within 9 km of the centroid | Consistent |
| Read cost | Median 88 MB per pass; about 20–30 s per pass with four reads in flight (estimated from progress) | As designed |

**Rule change from this run.** Small single-polarization clusters were noise-like: 40 detections with under 10 blocks, a median 56% of pulses hit and a median ISR of −1.9 dB. MEDIUM now needs 10 blocks, or both polarizations with at least 70% of pulses hit; the rest are LOW and below the default alert floor. The counts above use the new rule.

**Unresolved.** The strongest site carries a single tone at **1226.0 MHz** (ISR 28–32 dB, about 20% of the frame).
- It appears on every descending pass of track 107 (15:12Z) and on none of the 20 ascending passes (01:43–01:52Z) over the same area.
- The descending granules also carry a different code in their names (`DHDH_M` against `DHDH_A`).
- It is either an emitter that is on only in the afternoon or evening, or a mode-specific artifact. Checking `_M_` passes elsewhere for the same tone would tell them apart.

**Not covered here.** These data can't test the alert logic: the run was a seeded baseline, so alerts were held.

## 4. Regional run with a documented L2 jamming area as the control

A 30-day run over a private watch area (429 passes, 22 Sep – 21 Oct 2026) included an area where published work reports GNSS jamming on L1, L2 and L5. Locations stay private.

- **Cost and run time:**
  - 335 passes read their tables and 93 were screened out.
  - 25.5 GB downloaded (median 89 MB per read).
  - About 1 h 35 min, or ~3–4 minutes a day in daily use.
- **At the control area:**
  - Emitters were detected on every pass that covered it (13 of 13), 11–56 km from the reference points.
  - Mostly in band B (1290.8–1291.8 MHz).
  - In band A only as tones at 1221.5–1225.3 MHz on a few passes.
  - **Nothing at the GPS L2 centre frequency.**
- **Elsewhere in the area:** narrowband sites at the L2 centre (1227.2–1228.5 MHz) repeated on 5–9 passes from 2–4 geometries, within 5–23 km. That is good evidence that the method finds real ground emitters; it says nothing about who operates them.
- **Reading (hypothesis, not verified):**
  - Tone-rank flags loud **narrowband tones** in each block's spectrum.
  - A broadband noise jammer raises the signal estimate without standing out as tones, so the table method may **under-detect barrage jamming** while catching CW and narrowband emitters well.
  - A complementary detector on `signalMean` anomalies (power above what the same ground gives on other passes) is the next step.
- **Alert volume:** if this run had been live, 142 sites would have raised a first-time alert. The first live run of any area must be a seeded baseline, as the pipeline already does.

## 5. Broadband detector on the processor's signal power

**Why.** At the control area of section 4 the tone method found nothing at the L2 centre. Tone-rank flags loud narrowband tones, while a noise jammer raises the whole spectrum. That raised level shows up in the tables' per-block `signalMean`, the processor's estimate of the background power, not as tones.

**Method** (`nisar/nisar_rfi/bbdetect.py`):

- **Signature.** Natural echo comes back much weaker in the cross-polarized channel (HV) than in HH, and thermal noise is similar in both. An outside transmitter isn't tied to the radar's transmit polarization, so a vertical or slant-polarized source lifts HV about as much as HH.
- **Score.** Per pass and band, learn the frame's own relationship between HH power and the HV/HH ratio (median and robust spread per 1 dB HH bin). Then score each block's excess ratio and its z-score against that relationship.
- **Gates.**
  - MEDIUM needs 4 blocks, a ratio excess of at least 4 dB, excess HV power at least 5 dB over the frame, and HV within 1 dB of HH at the peak.
  - HIGH needs 8 blocks, 6 dB and 8 dB.
  - The last gate is physical: vegetation at L-band stays near −5 dB or below, so a ratio near or above 0 dB points to an outside source.
- **Position.** The centroid of the excess HV power, from the orbit.
- **Merging.** A broadband candidate within 20 km of a tone candidate in the same band becomes evidence on that detection. Other broadband candidates become their own detections; LOW ones are dropped.

**Results, regional 30-day set (335 passes read):**

| Check | Result |
|---|---|
| Control area (documented L1/L2/L5 jamming) | MEDIUM/HIGH within 40 km on **12 of 13** covering passes; in band A (which contains GPS L2) on 9 passes. The tone method had nothing at the L2 centre there |
| Candidates | 761 in all; 263 MEDIUM/HIGH (141 HIGH). Runs in about 30 s over the cached set |
| Geographic contrast | MEDIUM/HIGH detections concentrate where jamming is documented. Neighbouring, heavily forested regions with no reported jamming, the land cover most likely to cause cross-pol false alarms, gave 1–4 detections each over 37–83 passes |
| Absolute-ratio gate | Removed 8 of 271 MEDIUM/HIGH candidates; the control result is unchanged |
| Repeat sites | The strongest broadband site in the set lies in the control area: 9 passes, 5 geometries, both bands, ratio excess up to 16.5 dB |

**Shiraz case area (40 PROVISIONAL passes):**
- Again nothing within 40 km of the published site.
- Broadband candidates fall within a few km of several tone sites, so the two detectors agree independently.
- The single 1226.0 MHz tone of section 3 shows no broadband excess, which fits a pure tone.

**Combined pipeline** (both detectors, merged):

| Area | Detections | Tone only | Tone + broadband | Broadband only |
|---|---|---|---|---|
| Regional set | 738 | 491 | 68 | 179 |
| Shiraz area | 101 | 83 | 11 | 7 |

**Verdict.** The broadband detector finds the documented jamming that the tone method missed, on nearly every covering pass. It stays quiet in forested regions without reported jamming. That is the first positive control the lane has passed.

**Still not shown:**
- the published Shiraz jammer, by either detector;
- the accuracy of positions against a surveyed emitter;
- behaviour on horizontally polarized emitters, which raise HH more than HV and are under-detected by design.

## Reproduce

```sh
cd nisar
python -m nisar_rfi run --config validation/shiraz.json --start 2025-12-20 --end 2026-01-21              # image method, BETA
python -m nisar_rfi run --config validation/shiraz_provisional.json --start 2026-06-17 --end 2026-10-21 --seed   # table method
python -m nisar_rfi tables NISAR_L2_PR_GCOV_032_157_A_015_2005_DHDH_A_20261011T015156_20261011T015229_P05023_N_F_J_001
```

Outputs go to `private/nisar/validation-shiraz*/` (gitignored).

## Sources

- GPS World, [Converging on the jammer: dual-satellite GPS interference localization from space](https://www.gpsworld.com/converging-on-the-jammer-dual-satellite-gps-interference-localization-from-space/) (18 May 2026)
- ASF, [NISAR provisional known issues](https://nisar-docs.asf.alaska.edu/provisional-known-issues/) (RFI filter; updated 30 Jul 2026) and [frequencies and polarizations](https://nisar-docs.asf.alaska.edu/frequencies-polarization)
- isce3 (`python/packages/isce3/signal/rfi_tone_rank.py`, `python/packages/nisar/workflows/focus.py`), github.com/isce-framework/isce3, read 21 Oct 2026
