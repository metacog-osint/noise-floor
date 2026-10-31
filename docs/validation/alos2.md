# ALOS-2 PALSAR-2 ScanSAR: known-answer test against long-range radars (pre-registration, 31 Oct 2026)

**Tool:** `tools/alos2_rfi.py` (JAXA's open ScanSAR Level 2.2 archive on AWS, bucket `jaxaalos2`; HH and HV read at the
200 m overview). **Plan:** `docs/space-sensors-plan.md`, "Not pursued now" (ALOS-2), developed on Tom's 30 Oct request.

Everything in sections 1–3 was written and committed before any scene covering a radar site, or any control scene, was
scored. One scene had been scored before: a quiet Chukotka scene from 4 Aug 2014, used to build the tool.

## 1. Why this test

- **Same sites as SMAP.** The North Warning System's long-range radars (AN/FPS-117) are the known answer that SMAP's
  flags passed (`docs/validation/smap-rfi.md` §5: 14 sites, AUC 0.988).
- **In-band for ALOS-2.** The FPS-117 transmits across 1215–1400 MHz, which contains PALSAR-2's band around 1257.5 MHz.
  ALOS-2 should therefore receive these radars directly, not through spill-over.
- **Unverified premise:** that the radars' frequency hopping puts energy inside PALSAR-2's band during an acquisition.
- **What the signature should look like.** A radar's pulses are not polarized, so they add about as much power to HV as
  to HH. Natural surfaces return HV 5–12 dB below HH. A rotating radar is heard in bursts as its beam sweeps past, so the
  signature is narrow bright bands across the swath, spaced along the track.

## 2. Measure (frozen)

- For each scene, HH and HV are read at overview level 3 (about 200 m). Each valid pixel gets HV − HH (dB).
- Pixels are binned into lines across the swath, one pixel wide, along the flight direction (the footprint's first edge,
  as the tool already does).
- Each line's median HV − HH is computed from 50 pixels or more.
- **Local excess of a line:** its median minus the median of the line medians within ±25 lines (about ±5 km along
  track), itself excluded. A line is "raised" at a local excess of 3 dB or more.
- **Scene flagged:** 2 or more raised lines.
- **Scene score:** the largest local excess among its lines.

## 3. Scenes and checks (frozen)

**Sites.**
- The 14 active NWS long-range radars, with the coordinates in `docs/validation/smap-rfi.md` §5.
- Lady Franklin Point (PIN-3), out of commission since Nov 2020, is a site for the control exclusion only.

**Period.** Scenes acquired from 1 Oct 2025 to 30 Sep 2026, as named in the bucket (`-YYMMDD`).

**Site scenes.**
- A scene's footprint (its JSON geometry) contains a site at least 20 km inside its edge.
- Per site, the first 6 such scenes in date order (all of them if fewer). A scene covering two sites is counted once.

**Control scenes.**
- The footprint's centre lies inside the box 51.5–73.3°N, 168.2–54.8°W (the sites' box widened by 2°).
- No site, PIN-3 included, lies within 300 km of the footprint.
- Ordered by scene name; every k-th is taken so that the count matches the number of site scenes (all, if fewer).

**Selection.**
- Candidate scenes come from the bucket listing of 31 Oct 2026, filtered to frame numbers 1000–1550 and 2050–2600
  (high northern latitudes, ascending and descending), then by footprint.
- If a scene can't be read, it's skipped and reported, not replaced.

| # | Check | Holds if | Fails if |
|---|---|---|---|
| A1 | Share of site scenes flagged vs share of control scenes flagged | site ≥ 0.50 and control ≤ 0.20, Fisher's exact test p < 0.01 | site share ≤ control share |
| A2 | AUC of the scene score, site vs control | ≥ 0.75 | < 0.60 |

Between the marks the result is "weakened". Also reported, without marks:
- per-site results;
- whether a site lies within ±10 km along track of a raised line (position);
- the scene-median measure the tool already gives (lines 3 dB above the scene median).

## 4. Result (run 31 Oct 2026): fails

**Selection.**
- 948 candidate scenes in the period and frame ranges; 8 crossed the antimeridian and were skipped.
- The open archive is thin over the Canadian Arctic: 1–3 scenes for most sites, and none over Cape Lisburne or
  Cartwright. The rule gave 32 site scenes covering 12 of the 14 sites:
  - Point Barrow 2, Oliktok 6, Barter Island 6, Shingle Point 6;
  - Cape Parry 3, Cambridge Bay 1, Shepherd Bay 1, Hall Beach 3, Dewar Lakes 2, Cape Dyer 2, Brevoort Island 1,
    Saglek 2.
- 32 control scenes were taken from 148 available.
- All 64 scenes were scored, with no read errors.

| # | Check | Result | Verdict |
|---|---|---|---|
| A1 | Scenes flagged | site **0 of 32**, control **0 of 32** (Fisher p = 1.0) | **fails** (site share ≤ control share) |
| A2 | AUC of the scene score | **0.503** (median largest local excess: 0.85 dB at sites, 0.91 dB in controls) | **fails** (< 0.60) |

**Diagnostics (after the check; they don't change the verdict).**
- **Lines far above the scene median** (the tool's earlier measure): 10 of 32 site scenes against 6 of 32 controls. Not
  a meaningful difference.
- **Largest local excess** (cut 3 dB):
  - site scenes: at most 2.93 dB (90th percentile 2.28 dB);
  - controls: at most 3.19 dB (90th percentile 3.15 dB). Single lines in a few controls passed 3 dB, but no scene had
    the two raised lines that flag it.
- **What the images show:** the HV − HH image of the Saglek scene (1 Jan 2026) shows terrain and sea texture and no
  streaks across the swath.

**What this shows.** The open Level 2.2 products don't show the North Warning System radars, although SMAP flags the
same sites strongly. This test can't tell which of these is the reason:
- JAXA's processing filters the radars' signal out before Level 2.2;
- the radars weren't transmitting inside PALSAR-2's band during these acquisitions;
- interference covering only part of a line doesn't move the line's median.

**Next, if ALOS-2 is taken further.**
- Products made before any filtering (Level 1.1, JAXA G-Portal account), or per-line high percentiles instead of
  medians. Either needs a new pre-registered test.
- Until then ALOS-2 stays a probe, not a source for the map.
