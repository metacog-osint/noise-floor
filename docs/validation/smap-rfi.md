# SMAP radiometer RFI: pre-registered known-answer check (30 Oct 2026)

**Tool:** `tools/smap_rfi.py`. **Data:** NASA SMAP L1C half-orbit brightness temperatures, SPL1CTB v006 (36 km EASE-Grid
2.0), 11–17 Oct 2026: 27–31 half-orbits a day, 5.9–7.6% of looks flagged worldwide. **Plan:** `docs/space-sensors-plan.md`, steps R0–R3.

## 1. Pre-registration

Written and committed before the share map or any radar comparison was computed. Only the daily fetch totals above had
been seen.

**What is read.** In each cell's 16-bit quality word for each look (fore or aft) and polarization (H or V), the
`flag_meanings` attribute names bit 2 `RFI_detection` and bit 15 `RFI_clean`. On one half-orbit (20 Oct), bits 3 and
15 were set only where bit 2 was set. Readings:
- bit 2 = "RFI detected";
- bit 15 = "RFI left after mitigation".

The 0/1 sense is inferred from the data. The product specification has not been read.

**Measure.** Per cell, over the seven days:
- `share`: looks with bit 2 set ÷ all looks;
- `resid_share`: the same for bit 15;
- `contrast`: share minus the median share of the cells 100–300 km away.

**Known answer.**
- Long-range air-surveillance radar sites from the FAA site file (March 2010) as redistributed by open-air-data/atc-radar
  (ODbL; contents DbCL). These are rows typed ARSR or FPS, plus en-route Mode S sites (`ENR-MDS`), which sit with
  long-range primary radars.
- These radars transmit in 1215–1400 MHz. SMAP listens at 1400–1427 MHz.
- **Premise (unverified):** their out-of-band emission reaches SMAP's band. A miss tests the premise as much as the
  method.

**Comparison.**
- Land cells within 40 km of a site ("near") against land cells farther than 150 km from every site ("far").
- Both groups lie inside the sites' own bounding box, widened by 1 degree.

**Pass marks, on `share`:**

| AUC, near vs far | Verdict |
|---|---|
| ≥ 0.70 | holds |
| 0.60–0.70 | weak |
| < 0.60 | fails |

`contrast` and `resid_share` are reported beside it, without a pass mark.

**What it would show.** Holding means SMAP's flags pick out a known class of L-band emitter. It would not show that
SMAP can see GPS jammers: they transmit at 1176–1610 MHz, mostly outside SMAP's band.

## 2. Result (run 31 Oct 2026): fails

Seven days, 11–17 Oct 2026, 388,676 cells (108,711 on land). The site file gives 31 long-range sites: 108 cells lie
near them, and 2,673 far cells sit in the same box.

| Measure | AUC, near vs far | Near median | Far median | Verdict |
|---|---|---|---|---|
| `share` (pre-registered) | **0.502** | 0.067 | 0.071 | **fails** (< 0.60) |
| `contrast` | 0.563 | 0.027 | 0.004 | no pass mark |
| `resid_share` | 0.533 | 0.000 | 0.000 | no pass mark |

SMAP's flags don't pick out the 2010 long-range radar sites in the United States. This test can't tell which of
three explanations holds:
- these radars' out-of-band emission doesn't reach 1400–1427 MHz (the premise);
- the 2010 positions are stale;
- 36 km cells are too coarse for this comparison.

## 3. Diagnostics (after the check; they don't change the verdict)

**Flagged share by region.** Median share of looks with RFI detected, on land cells:

| Region | Median share | Share of cells > 0.5 |
|---|---|---|
| Western Russia | 0.750 | 0.933 |
| China, Korea, Japan | 0.679 | 0.706 |
| Europe | 0.643 | 0.679 |
| Middle East | 0.429 | 0.368 |
| Contiguous US | 0.050 | 0.036 |
| Africa, Australia, South America | 0.000 | 0.005–0.008 |

**Saturation.** Europe, western Russia and East Asia are saturated: most looks there carry an RFI flag. Like
Sentinel-1 over the Gulf, the flags can say only that the band is busy across a region.

**Isolated sources in quiet regions.** Some cells are flagged on every look while the 100–300 km ring around them is
quiet:
- Labrador, Cape Breton Island and Vancouver Island (CA);
- near Las Palmas and north of Vigo (ES);
- near São Paulo (BR), Lagos (NG) and Ho (GH);
- near Mataram and Surakarta (ID), Sri Jayawardenepura Kotte (LK), and Comayagua (HN);
- north of Irvine and north of Prescott (US).

These are single emitters in or spilling into the protected band. They have not been identified, and whether any is a
radar is not checked.

## 5. Second known answer: North Warning System long-range radars (pre-registration, 31 Oct 2026)

Written and committed before either test week was fetched.

**Where the idea came from.** Section 3 found always-flagged cells in quiet regions, two of them in Labrador and on Cape
Breton Island. Labrador hosts long-range radars of the North Warning System (NWS). The test below is therefore not
blind to that diagnostic. To limit the bias:
- it takes every active NWS long-range site from one published list, not the cells already noticed;
- it runs on two weeks nobody has looked at;
- Cape Breton is not an NWS site and isn't in the list.

**Sites.**
- The 14 active long-range radars (AN/FPS-117) in Wikipedia's "North Warning System" station table, with the coordinates
  given there (read 31 Oct 2026).
- Lady Franklin Point (PIN-3) is excluded: the same table says it has been out of commission since Nov 2020.
- The AN/FPS-117 transmits in 1215–1400 MHz, just below SMAP's 1400–1427 MHz. Premise (unverified): its out-of-band
  emission reaches SMAP's band.

| Site | Place | Lat | Lon |
|---|---|---|---|
| POW-M | Point Barrow, AK | 71.3272 | −156.6361 |
| POW-2 | Oliktok, AK | 70.4983 | −149.8894 |
| BAR-M | Barter Island, AK | 70.1303 | −143.6392 |
| LIZ-1 | Cape Lisburne, AK | 68.8700 | −166.1500 |
| BAR-2 | Shingle Point, YT | 68.9228 | −137.2606 |
| PIN-M | Cape Parry, NT | 70.1714 | −124.7250 |
| CAM-M | Cambridge Bay, NU | 69.1161 | −105.1189 |
| CAM-3 | Shepherd Bay, NU | 68.7928 | −93.4403 |
| FOX-M | Hall Beach, NU | 68.7608 | −81.2264 |
| FOX-3 | Dewar Lakes, NU | 68.6506 | −71.2328 |
| DYE-M | Cape Dyer, NU | 66.6644 | −61.3558 |
| BAF-3 | Brevoort Island, NU | 63.3400 | −64.1581 |
| LAB-2 | Saglek, NL | 58.4886 | −62.5856 |
| LAB-6 | Cartwright, NL | 53.5511 | −56.8300 |

**Data.** Two weeks of SMAP L1C (SPL1CTB v006), each scored on its own:
- 1–7 Oct 2026;
- 20–26 Oct 2026 (after the 18–19 Oct gap).

The measures are as in section 1 (`share`, `contrast`, `resid_share`), with tool and thresholds unchanged.

**Comparison.**
- "Near": every cell (land or water) within 40 km of a site.
- "Far": every cell farther than 150 km from all 14 sites, inside the sites' bounding box widened by 2 degrees
  (about 51.5–73.3°N, 168.2–54.8°W).
- Cells near the excluded PIN-3 count in neither group.
- Near and far cell-weeks from the two weeks are pooled.

| # | Check | Holds if | Fails if |
|---|---|---|---|
| N1 | AUC of `share`, near vs far (pooled) | ≥ 0.80 | < 0.65 |
| N2 | Sites "heard" (nearest cell's share ≥ 0.5) in both weeks, out of 14 | ≥ 8 | ≤ 4 |
| N3 | Far cells with share ≥ 0.5 (pooled) | ≤ 5% | > 15% |

Between the marks the result is "weakened". `contrast` and `resid_share` AUCs are reported without marks.

### 5.1 Result (run 31 Oct 2026): all three checks hold

The two weeks had 30–38 half-orbits a day, with 6.2–8.1% of looks flagged worldwide. The comparison pooled 82 near
cell-weeks and 20,200 far ones.

| # | Check | Result | Verdict |
|---|---|---|---|
| N1 | AUC of `share`, near vs far | **0.988** (median share 0.795 near, 0.021 far) | **holds** (≥ 0.80) |
| N2 | Sites heard in both weeks | **10 of 14** | **holds** (≥ 8) |
| N3 | Far cells with share ≥ 0.5 | **1.2%** | **holds** (≤ 5%) |

Without marks: AUC of `contrast` 0.992 (median 0.75 near, 0.00 far); AUC of `resid_share` 0.965.

**Per site** (share of the nearest cell within 40 km, week of 1–7 Oct / week of 20–26 Oct):

| Heard | Sites |
|---|---|
| Yes | Barter Island 0.91 / 0.83; Cape Lisburne 0.77 / 0.94; Cape Parry 1.00 / 0.98; Cambridge Bay 0.62 / 0.71; Shepherd Bay 0.59 / 0.67; Hall Beach 0.77 / 0.77; Cape Dyer 0.90 / 0.97; Brevoort Island 1.00 / 1.00; Saglek 0.94 / 0.97; Cartwright 1.00 / 0.85 |
| No | Dewar Lakes 0.32 / 0.13 (cell 15 km away); Point Barrow, Oliktok, Shingle Point (no cell within 40 km) |

**Diagnostics (after the check; they don't change the verdict).**
- **Why three sites had no cell.** At 70°N the 36 km EASE-Grid 2.0 cells stretch to about 90 km north–south, so the
  nearest cell centre can sit more than 40 km from a coastal site. Their nearest cells, 41–45 km away, read:
  - Point Barrow 0.70 / 0.75;
  - Shingle Point 0.61 / 0.75;
  - Oliktok 0.47 / 0.43.
- **Dewar Lakes** reads low in both weeks, even though a cell sits 15 km away. Whether its radar was off, or why it
  differs, is not known.

**What this shows.**
- SMAP's RFI flags pick out the North Warning System's long-range L-band radars clearly, in two unseen weeks, against
  a quiet Arctic background.
- With section 2's failure, this says SMAP can find L-band radars where the background is quiet. In crowded regions
  (Europe, East Asia, and the US test of section 2) the flags saturate, or don't stand out.

**What it doesn't show.**
- It doesn't show that SMAP sees GPS jammers.
- It doesn't locate an emitter finer than SMAP's 36–90 km cells.
- It isn't blind: the idea came from the diagnostics in section 3, though the site list is complete and the weeks
  were unseen.

## 6. Next

- **A fresh known answer with current positions.** Lists of L-band radars with positions and dates from the same weeks
  would do. Any rule built on the isolated-source list needs its own new test.
- **What a public layer could carry.** A weekly map of flagged share is honest as it stands: "the 1400–1427 MHz band is
  busy here". It is not evidence of GPS interference, and isolated sources would be leads only.
