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

## 2. Results

Not run yet.
