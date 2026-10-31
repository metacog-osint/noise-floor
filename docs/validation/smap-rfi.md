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

## 4. Next

- **A fresh known answer with current positions.** Lists of L-band radars with positions and dates from the same weeks
  would do. Any rule built on the isolated-source list needs its own new test.
- **What a public layer could carry.** A weekly map of flagged share is honest as it stands: "the 1400–1427 MHz band is
  busy here". It is not evidence of GPS interference, and isolated sources would be leads only.
