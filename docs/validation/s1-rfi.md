# Sentinel-1 RFI board: prototype and first validation (24 Oct 2026)

**Tool:** `tools/s1_rfi.py` (commands `search`, `fetch`, `sites`, `map`, `run`, `probe-asf`). **Tests:** `tests/test_s1_rfi.py`.
**Data:** the RFI annotation carried by Sentinel-1 Level-1 GRD products, read from Microsoft Planetary Computer. Only small
XML files are read, never the imagery. **Status:** prototype. Its outputs carry positions and stay private (`private/s1rfi/`).

## Bottom line

- **Access works without an account:**
  - Planetary Computer serves each GRD's `annotation/rfi/` files anonymously, at about 0.27 MB per product.
  - The ASF route also works up to the download itself: the search API needs no account, and the range-read code is
    written. ASF refuses the download until the Earthdata account accepts the ASF Sentinel EULA once, and only the
    owner can do that.
- **The annotation is there on all current platforms:**
  - S1C and S1D (IPF 004.03), and S1A (IPF 004.03 in 2026; 003.51/003.52 in 2022) carry full per-burst reports.
  - Products from Nov–Dec 2021 (S1A and S1B, IPF 003.40) carry the file, but with no burst-level detection.
- **Check B (quiet control): passed.** Gibson Desert, Western Australia: 56 products, 22 passes, 3,276 bursts, none flagged, no sites.
- **Check A (sites line up with published radar locations): failed in all three test areas.**
  - Rostov-on-Don and the Negev each have a site within 30 km of the published point (16 km and 25 km). But the
    published point itself scores low against the rest of each area: percentile 0.41 and 0.25, against the 0.90 required.
  - Pogonovo/Liski (Voronezh oblast) is quiet: 2.9% of bursts flagged, no sites.
  - The closest result came from the secondary window. Rostov-on-Don in Apr–Jul 2022, nearer in time to the
    published case, has a site 11 km from the radome and a percentile of 0.83. That still misses the pre-stated 0.90.
- **What the annotation shows well is region-scale RFI.** The Gulf calibration area (Eastern Province, Bahrain, Qatar) is
  saturated: 82% of bursts flagged and every pass hit. Rostov-on-Don and the Negev are busy, with 21% and 35% flagged. The
  control is silent.
- **Localization is coarse:**
  - RFI usually sits in one subswath per pass, about 85 km across track, for 2–3 bursts along track (40–60 km).
  - The crossings of several geometries narrow that to site cores of roughly 10–50 km.
  - That is too coarse to confirm a single published radar site in a busy area.
- **Verdict:** the board can say where C-band RFI is and isn't, region by region and pass by pass. It can't yet locate an
  emitter. Treat its sites as leads, and keep them private.

## 1. Access: what was checked (23–24 Oct 2026)

| Route | Result |
|---|---|
| **ASF search API** (`api.daac.asf.alaska.edu/services/search/param`) | Works without auth. It finds S1C and S1D SLC and GRD products by box and date |
| **ASF download, range reads into the SAFE zip** | Refused with HTTP 403 `EULA Acceptance Failure`, using a valid Earthdata bearer token. Earthdata Login lists the app to approve. `python tools/s1_rfi.py probe-asf <scene>` reports this, and will list the zip's `annotation/rfi/` entries once the EULA is accepted. Not verified end to end |
| **Copernicus Data Space** | Catalogue search is anonymous. Downloading a product, or even a single file node such as `manifest.safe`, returns HTTP 401 without a token, so it needs an account. Not used |
| **Microsoft Planetary Computer**, `sentinel-1-grd` | Works anonymously. The SAS token comes from the public token endpoint, and blob listing and reads are allowed. Each item's folder holds `manifest.safe`, `annotation/rfi/rfi-iw-{vv,vh}.xml` and the main annotation `annotation/iw-{vv,vh}.xml`. The STAC asset table lists the RFI files under the key `schema-product-*`, which is a cataloguing quirk, so the tool lists the folder rather than trusting asset keys |

**Which products carry the RFI folder.** GRD was confirmed directly, on every one of about 800 products read.

SLC was not checked directly, because the only anonymous source has no SLC. SAR-MPC-0540 describes SLC RFI annotation
per subswath and polarization (§2.2.1, §2.2.3).

**Volume per GRD product:**
- `manifest.safe`: ~25 kB.
- Two RFI files: 11–55 kB each.
- The last 170 kB of one main annotation, read with an HTTP range request. That tail holds the geolocation grid and
  the swath merge table.

In total that is about 0.27 MB, against roughly 1 GB for the imagery. The ~800 products read here cached to 227 MB
under `data/s1rfi/cache/` (gitignored).

## 2. What the annotation says

Field definitions come from the Sentinel-1 Product Specification, S1-RS-MDA-52-7441, issue 3.17.1 (30 Jul 2026),
Tables 6-112 to 6-119. How to use them is from SAR-MPC-0540, "Sentinel-1: Using the RFI annotations", v1.1 (31 May 2023).
Both are on [SentiWiki](https://sentiwiki.copernicus.eu/web/s1-documents).

- **The processor (IPF 3.40+) works in three steps** (SAR-MPC-0540 §2.2):
  1. Pre-screen the noise pulses for RFI. This needs noise measurements, so it runs in IW/EW only.
  2. Optionally run data-based detection.
  3. Mitigate.
- **Activation.** The main annotation's `rfiMitigationPerformed` (`Never`, `BasedOnNoiseMeas`, `Always`) sets how
  detection is activated. The one 2026 product whose main annotation was read in full uses `BasedOnNoiseMeas`. The
  tool reads only the end of the main annotation, so it doesn't record this flag per product.
- **From IPF 3.51,** a pre-screen hit in one burst switches detection on for every burst of that polarization (§2.2.2).

| Element | Meaning (PS table) |
|---|---|
| `rfiMitigationApplied` | `None`, `Time`, `Frequency` or `TimeFrequency` (6-112). Under `BasedOnNoiseMeas`, anything but `None` means RFI was pre-screened in the product |
| `rfiDetectionFromNoiseReport` | One per noise sequence and swath (6-114): `noiseSensingTime`, `rfiDetected`, `maxKLDivergence`, `maxFisherZ`, and `maxRfiPsd` (the largest PSD in an RFI bin; zero if none was found) |
| `rfiBurstReport` | One per TOPS burst and swath (6-116). `azimuthTime` is the zero-Doppler time of the burst's **first line**. `inBandOutBandPowerRatio` is the ratio of in-band to out-of-band power |
| `timeDomainRfiReport` | `percentageAffectedLines`: % of level-0 lines with RFI. `avgPercentageAffectedSamples` / `maxPercentageAffectedSamples`: samples hit per line (6-117) |
| `frequencyDomainRfiBurstReport` | `isolatedRfiReport` (line-by-line tones): % lines hit and the max % of bandwidth hit in one line. `percentageBlocksPersistentRfi` and `maxPercentageBWAffectedPersistentRfi`: from the mean PSD of each processing block (6-118, 6-119) |

**Caveats from SAR-MPC-0540 itself** (Appendix B, §4.1):
- The pre-screen can miss RFI, because it sees only a few noise echoes.
- It can also fire on RFI present only in the noise pulses.
- Very bright targets, and land/water transitions, can trigger false time-domain detections, notably in the
  cross-pol channel.
- Spurious tones can trigger frequency-domain detection over calm sea in cross-pol.
- Interference can also come from another C-band SAR imaging the same area (Fig. 32).

## 3. Method (frozen before the test areas were run)

1. **Search** Planetary Computer for IW GRD products over the area and window. **Fetch** the manifest (IPF version),
   both RFI files, and the tail of one main annotation.
2. **Geolocate each burst report** to a quadrilateral:
   - Along track: from `azimuthTime` to `azimuthTime` plus the burst spacing (median 2.76 s).
   - Across track: the subswath's pixel bounds, from `swathMerging`.
   - Positions come from bilinear interpolation of the product's geolocation grid, extrapolated linearly for bursts
     that start before the slice.
   - A check against the manifest footprints agrees to within one burst length (≤ 18 km at the slice ends). Subswath
     order is right for both directions (IW1 is near range).
   - Adjacent slices repeat their seam bursts; those are de-duplicated.
3. **Flag** a burst when `percentageAffectedLines` is at least 10%, or `percentageBlocksPersistentRfi` at least 1%, in
   either polarization.
4. **Back-project onto a 0.05° grid:**
   - Per pass and cell, take the largest affected-lines percentage among the covering bursts.
   - Average per geometry (relative orbit plus direction).
   - The **score** is the median of those geometry means over the geometries covering the cell.
   - One emitter leaves a stripe on each pass. Only where the stripes from most geometries cross does the median stay high.
5. **Sites.** Peaks are picked greedily, one per 30 km. A peak counts only if all of these hold:
   - score ≥ 10;
   - flagged on ≥ 3 passes from ≥ 2 geometries, and on ≥ 30% of covering passes;
   - ≥ 4 covering passes;
   - it stands at least 5 points above, *and* at least 1.25 times, the median of the 30–90 km ring around it.

   The ratio rule was added after the Gulf calibration: a region lit everywhere should report no discrete sites rather
   than tile into them.
6. **Outputs (private):**
   - `private/s1rfi/<area>/sites.json`: first and last seen, passes, geometries, max affected lines, max affected
     bandwidth, max noise RFI PSD, polarizations, extent.
   - `bursts.jsonl` and `grid.npz`.
   - A quicklook PNG and a KML.

## 4. Pre-stated check

Written at 04:35 UTC on 24 Oct 2026 (23:35 CDT on 23 Oct), before any test-area or control product was searched. Only the
calibration area had been run. The full text is kept with the private outputs.

- **Check A (location).** For each test area with a published reference location, the area passes if:
  1. a site lies within 30 km of the location; **and**
  2. the location's own score is in the top 10% of the area's covered cells.

  The lane passes Check A if at least one of the three test areas passes. The chance rate is also reported: the share of
  covered cells within 30 km of any site.
- **Check B (control).** No sites, and fewer than 5% of bursts flagged.
- **Secondary.** Rostov-on-Don, 1 Apr – 15 Jul 2022, with the same rules, reported separately.

**Reference locations,** all from Bellingcat (Ollie Ballinger, ["Radar Interference Tracker"](https://www.bellingcat.com/resources/2022/02/11/radar-interference-tracker-a-new-open-source-tool-to-locate-active-military-radar-systems/), 11 Feb 2022):

| Test area | Reference |
|---|---|
| Rostov-on-Don | The RNIIRS radome, 47.3544°N 39.7834°E; interference in Jun–Jul 2021 |
| Voronezh oblast | The map point near Pogonovo and Liski, 51.4980°N 39.1684°E; interference on 29 Sep and 13 Nov 2021 |
| Negev | The "Dimona Radar Facility" pin, 30.9685°N 35.0971°E |

The article also reports the Dammam Patriot battery but gives no coordinates, so that area served only as calibration.

## 5. Results (window 20 Jul – 20 Oct 2026 unless stated; all S1C and S1D, IPF 004.03)

| Area (role) | Products / passes | Passes with RFI | Bursts flagged | Sites | Chance rate (30 km) | Reference: nearest site, score percentile | Verdict |
|---|---|---|---|---|---|---|---|
| Eastern Province / Bahrain / Qatar (calibration) | 184 / 77 | 77 | 82.1% | 0 (48 peaks below the prominence rules) | – | – | Saturated |
| Rostov-on-Don (test) | 186 / 93 | 90 | 21.4% | 7 | 0.62 | 16.0 km; 0.41 | **Fail** |
| Voronezh oblast (test) | 167 / 92 | 63 | 2.9% | 0 | 0 | none; 0.68 | **Fail** (quiet) |
| Negev (test) | 118 / 61 | 58 | 34.7% | 10 | 0.74 | 25.1 km; 0.25 | **Fail** |
| Gibson Desert (control) | 56 / 22 | 0 | 0.0% | 0 | 0 | – | **Pass** |
| Rostov-on-Don, Apr–Jul 2022 (secondary; S1A, IPF 003.51/003.52) | 84 / 43 | 21 | 13.9% | 6 | 0.58 | 11.3 km; 0.83 | Fail (closest) |

**Reading the table:**
- In Rostov-on-Don and the Negev, 62% and 74% of covered cells lie within 30 km of some site. So a site within 30 km of
  the reference is close to what chance gives, which is why the pre-stated rule also asks for the reference cell to score
  high.
- Every site was flagged by all of the geometries covering its peak. But at most peaks only 2–4 geometries cover the
  cell, so the crossing constraint is often weak.

## 6. Diagnostics (after the check; they don't change the verdict)

- **RFI is confined in range.**
  - On a pass with RFI over the area, it usually appears in one subswath: 32 of 45 flagged passes at Rostov-on-Don, and
    21 of 44 in the Negev. The rest show it in two.
  - It runs for 2–3 consecutive bursts along track (median; 90th percentile 4–8).
  - So a burst report constrains an emitter to about one subswath (~85 km) by 40–60 km per pass. The Bellingcat
    method instead reads the narrow azimuth stripe in the focused image, which this annotation can't resolve.
- **The cross-pol channel dominates the flags in the busy areas.**
  - VH is flagged on 56% of bursts in the Negev, against 4.8% in VV. At Rostov-on-Don it is 32.8% against 9.4%.
  - Five of the ten Negev sites, and three of the six 2022 Rostov-on-Don sites, are VH-only. Six of those eight show
    little frequency-domain support (affected bandwidth ≤ 8%).
  - This fits the cross-pol false-detection modes in SAR-MPC-0540 Appendix B. It doesn't prove them.
- **A VV-only variant (exploratory, not pre-stated) doesn't rescue Check A.**
  - Rostov-on-Don: 3 sites, the nearest 11 km from the radome, at percentile 0.56.
  - Negev: 3 sites, the nearest 55 km away.
  - The control stays silent.
  - Any VV-only rule needs its own fresh test.
- **Ghost sites.**
  - The offline test shows the score can also peak where the stripes of most, but not all, geometries overlap: about
    one subswath away from the true crossing.
  - Sites where every covering geometry agrees are the stronger leads.

## 7. Limits and caveats

- **Four years apart.** The published cases date from 2021 to early 2022, and the main window is 2026. A radar may have
  moved, changed band or been switched off. A miss doesn't show the method is blind, and a hit four years on would have
  been weak evidence anyway.
- **Dimona.** Public sources describe the Dimona site's radar as a US X-band AN/TPY-2 ([Wikipedia](https://en.wikipedia.org/wiki/Dimona_Radar_Facility); not verified here). X-band is outside Sentinel-1's 5.405 GHz band. Bellingcat reports C-band interference there without naming the emitter, so it isn't clean ground truth.
- **Saturated regions** (the Gulf) give no discrete sites by design. The board can only say "RFI everywhere".
- **Bursts with no burst-level report count as zero.** These are bursts where the processor ran no detection in that
  polarization (`rfiMitigationApplied=None`). Because the pre-screen can miss RFI, that biases scores low where RFI is
  intermittent.
- **Older products.** Products made before burst-level mitigation was switched on carry only the noise pre-screen. The
  tool reads it (`noise_detected`, `maxRfiPsd`) but doesn't score it.
  - IPF 003.40, from 4 Nov 2021; the Dec 2021 products checked here have `rfiMitigationApplied=None` throughout.
  - Mitigation was in place from 23 Mar 2022, according to an ESA STEP forum reply
    ([thread](https://forum.step.esa.int/t/rfi-annotations-of-sentinel-1-grd-slc-products/34941)). That date hasn't
    been checked against ESA release notes.
- **Not an attribution.** A flag means the processor saw interference in its band. It doesn't say what or whose the
  emitter is, and another C-band SAR can cause it too.

## 8. Next

- **A same-time known emitter,** such as a C-band radar whose position and on-air dates are published for the same
  weeks, to measure position error directly. Re-run Check A unchanged on it before tuning anything.
- **The ASF route,** if the account owner accepts the ASF Sentinel EULA on the Earthdata account (one approval in a browser). It gives SLC
  products and per-subswath RFI files. `probe-asf` then confirms the folder in SLC zips by range reads.
- **Per-burst along-track weighting** (the affected-lines profile within a run), and use of the noise pre-screen, to
  sharpen positions. Both need a fresh test.

## Run

```sh
python tools/s1_rfi.py run --area <name>                         # search, fetch, sites, map for one configured area
python tools/s1_rfi.py run --area all
python tools/s1_rfi.py search --area <name> --start 2026-07-20 --end 2026-10-20
python tools/s1_rfi.py probe-asf <ASF scene name>                # needs EARTHDATA_TOKEN and the accepted EULA
python tests/test_s1_rfi.py
```

The areas live in a private config, `private/watch/s1rfi.json` (gitignored). Its keys are:

- `defaults` (`source`, `start`, `end`);
- optional `detect` and `sites` overrides;
- `areas`: per name, `role`, `label`, `bbox` [W, S, E, N], an optional `start`/`end`, and `reference_sites`
  (`name`, `lat`, `lon`, `source`).

## Data and licences

| Data | Licence and use |
|---|---|
| Copernicus Sentinel-1 L1 GRD annotations (via Microsoft Planetary Computer) | Free for any use, including commercial, with attribution: "Contains modified Copernicus Sentinel data 2026" (and 2022 for the secondary window). Ingested (annotations only) |
| Natural Earth (basemap lines in the quicklooks) | Public domain |
| Bellingcat, Wikipedia | Cited only |
