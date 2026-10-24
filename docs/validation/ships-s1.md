# Sentinel-1 ship detection checked against Sentinel-2 (24 Oct 2026)

**Tools:** `tools/ship_detect.py` (the detector) and `tools/s2_check.py` (this check). **Tests:** `tests/test_s2_check.py`.
**Area:** Singapore Strait and Johor (maritime plan focus area 2; the exact box is private configuration).
**Data:** Sentinel-1 GRD and Sentinel-2 L2A from Microsoft Planetary Computer (anonymous). Only windows over the area were read.
**Status:** first validation, with no AIS yet. The rule was fixed before scoring. Per-detection results, chips and positions stay private.

## Bottom line

- **No simultaneous optical image exists.** Sentinel-2 passes at about 03:05–03:22 UTC; Sentinel-1 passes at about 11:16–11:24
  or 22:39–22:47 UTC. The closest pairs are 4.3–8 hours apart, so moving ships can't be matched one to one. Precision
  here is measured as the share of detections that an optical object confirms, after removing chance coincidences (q).
  That is a **lower bound**: a real ship that sailed away counts against it.
- **The original detector (two-parameter CFAR, k = 6) is dominated by false alarms in low-wind sea.**
  - q is 0.13 on the dawn pass of 22 Oct (95% CI 0.09–0.18) and 0.19–0.31 on two evening passes.
  - By eye, about 69% of the scorable 22 Oct detections are low-contrast blobs in patchy sea clutter (population-weighted
    from 90 chips). About 29% look real: confirmed, or a compact or bright target that has moved.
- **Three false-alarm types account for most of the excess.** On a full pass at k = 6:
  - Low-contrast blobs (peak under 10 dB above the local sea mean): 23–50% of detections. They're rarely confirmed.
  - Land leaks (reclamation, islands and coast missing from Natural Earth 10 m): 7–21%.
  - Azimuth ghosts (faint copies of very bright targets 4.3–6.3 km along track): 4–6%. They're confirmed at chance level (0 of
    74 within 150 m, over five pairs).
- **Raising k helps, but a contrast floor helps more.** k = 6 with a 10 dB contrast floor, ghosts dropped and an S2 land mask
  ("recommended" below) gives:
  - q 0.49, 0.42 and 0.51 on the three development pairs, against 0.13, 0.31 and 0.19 for the original detector;
  - q 0.23 and 0.45 on two **held-out** pairs (pre-registered), against 0.09 and 0.17 for the original detector, and 0.21 and
    0.42 at k = 10;
  - so the gain over the original is clear out of sample, and the gain over plain k = 10 is small (within noise). The
    recommended setting keeps more large ships than k = 10, though.
- **Recall for large ships is moderate, with wide uncertainty.** For vessels of 100 m or more that S2 shows without a wake
  (stationary or slow), 21 of 30 had an S1 detection within 500 m (7 of 30 within 150 m), 4.3–8 h apart. Corrected for
  chance, that is about 0.5–0.8.
  - Under way vessels (with a wake) were found at chance level, as expected.
  - The recommended setting found 19 of 30.
- **Fixed structures confirm well where the sky is clean:**
  - S1 detections at recurring sites: 23 of 27 confirmed within 150 m on 3 Sep, and 10 of 13 on the held-out 3 Sep pair.
  - Unconfirmed recurring sites are mostly islands and coast, buoys or beacons too small for S2, and a few edge artefacts.

## 1. Method

### Pairs

| Pair | Sentinel-1 | Sentinel-2 | Gap | Role |
|---|---|---|---|---|
| P1 | 22 Oct 2026 22:47 UTC, descending, full area | S2B 23 Oct 03:08, relative orbit 75 | +4.3 h | development |
| P2 | 3 Sep 11:24, ascending, about 56% of the area | S2A 3 Sep 03:22, relative orbit 118 | −8.1 h | development |
| P3 | 29 Aug 11:16, ascending, about 60% | S2C 29 Aug 03:05, relative orbit 75 | −8.2 h | development |
| P5 | 16 Sep 22:47, descending, full | S2C 18 Sep 03:05, relative orbit 75 | +28.3 h | held out |
| P6 | 4 Sep 22:47, descending, full | S2B 3 Sep 03:05, relative orbit 75 | −43.7 h | held out |

Pairs came from the catalogue (dates, catalogue cloud cover and footprints) before any pixel was read. The S2 orbit-75 images
cover only part of the area. Clouds limited P1 to 410 scorable detections at k = 6 (of 3,480), P2 to 650 (of 1,562) and P3 to 122.
A fourth candidate pair (S1 5 Oct, S2 6 Oct) turned out to have no overlap, which I hadn't checked; it's recorded as inconclusive.

### Optical reference (Sentinel-2 L2A)

- **Bands:** B08 (near infrared, 10 m) for objects, and the scene classification layer (SCL, 20 m) for water, land and cloud.
- **Objects:** connected B08 pixels inside water that exceed the mean of a ring of water pixels (250–500 m) by 5 standard
  deviations and by at least 0.02 reflectance, and cover at least 3 pixels.
- **Not counted:**
  - objects within 100 m of land;
  - cloud (SCL cloud, cloud shadow and cirrus classes), grown by 200 m;
  - hazy water, where the robust standard deviation of B08 in 500 m blocks is above 1.6 times the scene's clean-water level.
- **SCL calls anchored ships "cloud".** A ship-sized cloud blob counts as cloud only if real cloud (a large blob, cloud shadow or
  cirrus) lies within about 500 m.
- **How good the reference is**, checked by eye:
  - 30 random objects per scene. Most were vessels or small craft on 23 Oct and 3 Sep (orbit 118). On 29 Aug most were small
    cumulus clouds, which SCL doesn't flag.
  - Objects of 100 m or more: 10 of 28 were vessels on 23 Oct (15 were clouds), and 44 of 60 on 3 Sep (7 clouds, 9 other).
  - Clouds in the reference don't bias precision: they're unrelated to S1 detections, so the chance control (below) absorbs
    them. For recall, every large object was labelled by eye first.

### Pre-stated rule (summary)

Written before scoring (a private note with the full text and a change log):
- **Scorable:** an S1 detection is scorable when at least 90% of S2 pixels within 300 m are clear and at least half of those
  within 50 m are water.
- **Confirmed:** an optical object lies within **150 m** (tight) or **500 m** (loose). Anchored ships swing on their cable:
  the hull's centre can move roughly 150–370 m between images hours apart (physical reasoning, not measured).
- **Chance control:** the same detections moved 3 km to each of 8 compass points. Moved points must also be scorable water in
  both images. The chance-corrected confirmation is q = (m − c) / (1 − c), where m is the confirmed share and c the control share.
- **Strata:** S1 length, fixed (within 60 m of a site recurring in 60% or more of full passes) or other, ghost candidates,
  within 100 m of S2 land.

**Changes after the rule was written**, all logged with reasons:
1. The optical reference first failed its own check (cloud wisps). The cloud and haze rules above were added before any S1
   scoring.
2. The by-eye sample then showed that SCL labels anchored ships as cloud, and that the first cloud rule masked anchorages.
   This change was made **after** the first P1 score, so it is post hoc. The first result stays on record: P1 at k = 6 had
   q = 0.11 (0.07–0.15), and fixed sites confirmed 3 of 15.
3. Coast rejection was added before P2 and P3 were scored.
4. The detector changes were chosen on P1–P3, then tested on P5 and P6 with a prediction written beforehand.

## 2. Precision and CFAR threshold

Chance-corrected confirmation q at 500 m (95% CI on m carried through). n is scorable detections. Detections are for the full pass.

| Detector | P1 detections, n, q | P2 detections, n, q | P3 detections, n, q |
|---|---|---|---|
| k = 5 | 5,403, 780, 0.07 | 2,112, 864, 0.25 | 1,924, 336, 0.09 |
| k = 6 (original) | 3,480, 410, 0.13 (0.09–0.18) | 1,562, 650, 0.31 (0.25–0.37) | 932, 122, 0.19 (0.09–0.30) |
| k = 8 | 2,125, 176, 0.27 | 1,123, 521, 0.34 | 546, 59, 0.41 |
| k = 10 | 1,659, 119, 0.35 (0.25–0.46) | 928, 454, 0.34 | 443, 50, 0.44 |
| k = 6, contrast ≥ 10 dB | 1,729, 79, 0.47 | 1,285, 490, 0.40 | 532, 46, 0.51 |
| **Recommended** (k = 6, ≥ 10 dB, ghosts dropped, S2 land mask) | 1,459, 77, 0.49 (0.35–0.61) | 990, 480, 0.42 (0.35–0.49) | 413, 46, 0.51 (0.32–0.68) |

- The k = 5, 6, 8 and 10 counts on 22 Oct reproduce the earlier run exactly (5,403, 3,480, 2,125 and 1,659).
- q rises with k on every pass. A real stationary target shouldn't depend on k, so the extra detections at low k are mostly clutter.
- At 150 m, q is lower on the 8-hour pairs (P2 0.12 at k = 6), as anchored ships swing or leave. On the 4.3-hour pair it's
  about the same as at 500 m (P1 0.13).
- The chance share at 500 m is high in the dense traffic of P2 (c = 0.35), which is why the 150 m figures are also reported.

**By S1 length** (P1, k = 6, not fixed): q is 0.10 for 30–59 m (n 265), 0.15 for 60–99 m (96), 0.17 for 100–199 m (25),
and 0.25 for 200 m or more (4). On P3, detections of 200 m or more reach q = 0.62 (n 28). S1 "length" isn't a reliable size
for clutter: a diffuse clutter patch measures 100–170 m.

**Held-out test (pre-registered).** The prediction was that the recommended setting beats the original by at least 0.10 in q,
and beats k = 10.

| Detector | P5 n, q | P6 n, q |
|---|---|---|
| k = 6 (original) | 183, 0.09 | 260, 0.17 |
| k = 10 | 72, 0.21 | 88, 0.42 |
| Recommended | 61, 0.23 | 80, 0.45 |

The prediction held on both pairs. The margin over k = 10 (+0.01, +0.03) is within noise. The recommended setting keeps more
detections of 200 m or more than k = 10 (29 against 24, and 49 against 42).

**Density check.** Per km² of the same clear water:
- On P1, S1 at k = 6 had twice as many detections as S2 had objects: 410 against 203, and 99 of those S2 objects are craft
  under 30 m. That is consistent with clutter.
- On P2 (busy strait, 8 h gap), S1 had fewer: 639 against 1,035.
- On P3, the S2 count is inflated by cumulus, so it isn't usable.

## 3. What the false alarms look like

From the 90-chip sample on P1 (30 per length stratum, random seed fixed in advance), labelled by eye:

| Label | Count | Notes |
|---|---|---|
| Confirmed by S2 | 13 | Mostly small craft in fields of boats, plus one large ship and one structure |
| Compact point target, nothing in S2 | 9 | Small craft that moved, or below S2's limit |
| Bright ship signature, nothing in S2 | 5 | Ships that sailed in the 4.3 h gap; one anchorage group whose ships had shifted |
| Low-contrast blob in patchy sea | 61 | Bright wind patches next to calm water; wind rows; nothing in S2 |
| Valid-data edge | 1 | A recurring "fixed site" on the edge of the image data |
| Ghost candidate | 1 | Faint, smeared, along track of a bright target |

- **Low-contrast blobs:** 55 of the 66 sampled detections with peak ratio under 10 were clutter. Among detections at or above
  it, 16 of 24 looked real. The 22 Oct pass (06:47 local, dawn) shows strongly patchy backscatter at sub-km scale. A Gaussian
  two-parameter CFAR underestimates heavy-tailed, non-uniform sea clutter (a known limit; see Crisp 2004).
- **Land leaks:** the airport and port reclamation, oil terminals, mangrove and beach coast, and small islands, none of them in
  Natural Earth 10 m land or minor islands. On 3 Sep they were 65 of 1,562 detections inside S2's clear view. Across a full
  pass, 7–21% of detections sit on land as mapped from S2. Recurring sites include 51 of 382 on S2 land.
- **Azimuth ghosts:**
  - Seen first in S1 alone: across all 19 passes, faint detections cluster 4.5–6 km along track of very bright targets
    (bearing about 192° descending, 348° ascending).
  - That matches the expected azimuth-ambiguity offset λ·R·PRF/(2V), about 4.7–5.7 km for IW. The PRF and slant range were
    taken as typical values, not read from the product annotation (unverified).
  - S2 confirms none of them within 150 m (0 of 74).

## 4. Recall for large vessels

S2 objects of 100 m or more in water S1 could see were labelled by eye from chips (S2 near-infrared, true colour, and S1 with
its detections). Labels: vessel without wake, vessel with wake, cloud, islet, other.

| Pair (gap) | Vessels without wake | With an S1 detection within 500 m (150 m) | Chance share at 500 m | Corrected |
|---|---|---|---|---|
| P1 (4.3 h) | 6 | 5 (2) | 0.14 | 0.81 (0.35–0.97) |
| P2 (8.1 h) | 24 | 16 (5) | 0.35 | 0.48 (0.17–0.72) |

- Vessels with a wake: 1 of 4 and 4 of 17 within 500 m, both at chance level.
- Islets and structures: 6 of 6 detected.
- With the recommended setting: 3 of 6 on P1 and 16 of 24 on P2. Two P1 matches are lost in heavy clutter.
- "No wake" doesn't prove a ship stayed for 4–8 hours, so these are lower bounds on recall for stationary ships.
- The sample is small. The 16.5-minute stationarity test from two S2 passes (3 Sep) only covered the main traffic lane,
  where most large ships were under way (stationary share 0.27 for objects of 200 m or more, n 33). It wasn't used for recall.

## 5. Detector changes (all optional; the original is the default)

`tools/ship_detect.py` now has:
- `--min-contrast DB`: drops detections whose peak is less than DB above the ring's sea mean. 10 is recommended.
- `--ghosts keep|flag|drop`: azimuth-ghost candidates. A candidate needs a detection at least 20 dB brighter 4.3–6.3 km along
  track and within 200 m across; the along-track direction comes from the image's ground control points.
- `--landmask FILE`: an extra land mask, applied after the CFAR test (built with `tools/s2_check.py watermask` from S2 SCL on
  dates not used for scoring).
- `--out DIR`.
- `--scene ID` now processes the whole acquisition that frame belongs to, not just the one frame.

With no new flags, the 22 Oct pass still gives 3,480 detections. Recommended:
`--min-contrast 10 --ghosts drop --landmask <file>`.

## 6. Limits

- No AIS: precision is a lower bound, and the share of unconfirmed detections that are real ships that moved isn't known.
- No simultaneous optical image. The development pairs are 4.3–8.2 h apart; the held-out pairs 28–44 h.
- The optical reference misses small craft, buoys and thin beacons, and is contaminated by small cumulus that SCL doesn't flag.
- One area, five pairs, and few scorable large ships (30 for recall). Clouds removed most of the pairs' overlap.
- The contrast floor was chosen in-sample. It passed one held-out test, but its edge over k = 10 isn't established.
- GRD amplitude isn't radiometrically calibrated in this tool (fine for relative tests).

## 7. Next steps

- AIS for the area, to separate "moved" from "false" and to measure recall properly (maritime plan D1/D2).
- A clutter-aware CFAR (K-distribution or log-domain) in place of the contrast floor, tested on held-out passes.
- A shadow or shape test to drop cumulus from the optical reference, and more clear S2 pairs over the coming dry season.

## Sources

- Copernicus Sentinel data legal notice (free, including commercial use, with attribution). It is linked from each Planetary
  Computer `sentinel-2-l2a` item (checked 24 Oct 2026): https://sentinel.esa.int/documents/247904/690755/Sentinel_Data_Legal_Notice
- Planetary Computer Sentinel-2 L2A dataset: https://planetarycomputer.microsoft.com/dataset/sentinel-2-l2a
- Sentinel-2 L2A scene classification classes (Sen2Cor; ESA Level-2A product documentation). The class meanings were used as
  documented by ESA; the document wasn't re-read for this note.
- D. J. Crisp, "The State-of-the-Art in Ship Detection in Synthetic Aperture Radar Imagery", DSTO-RR-0272 (2004), on CFAR
  detectors and sea-clutter models.
- Azimuth ambiguities in SAR: the standard offset λ·R·PRF/(2V). The values for Sentinel-1 IW are approximate and unverified here.

Contains modified Copernicus Sentinel data 2026.
