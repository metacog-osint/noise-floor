# Dark ships and phantom tracks in Finnish waters (maritime M2): pre-registration

**Written 26 Oct 2026, committed 17:57 UTC (8b1554c), before any matching code existed and before the held-out data was read.**
Nothing in the "Frozen" and "Checks" sections changes after scoring. Results go below the line at the end.

**Lane:** maritime, step M2 (detectors D1 "dark ship" and D2 "phantom track", `docs/maritime-plan.md` section 5).
**Why here:** the plan's flagship area (Singapore Strait) has no licence-clean AIS. Finland's Digitraffic AIS (CC BY 4.0,
`collectors/digitraffic_ais.py`) does, so the first D1/D2 test runs in Finnish waters. The Sentinel-1 detector itself was
checked against Sentinel-2 at Singapore (`docs/validation/ships-s1.md`); that check had no simultaneous reference. AIS
at the radar's acquisition time is one.

## What is being tested

- **D1, dark ship:** a radar detection with no AIS position within ±10 min and ±1 km of the acquisition.
- **D2, phantom track:** an AIS position inside the radar image at acquisition time with no detection where a ship of
  the reported length should show.

D1 can't be scored for precision directly: no source says which ships were really dark. What can be tested is (a) whether
the detector finds the large ships AIS says are there, which D2 depends on, and (b) whether large detections without AIS
are rare enough that each one is worth a person's look, rather than clutter that swamps the list.

## Data

- **Development (may be read to build and debug the matcher):** Sentinel-1C passes of 24 Oct 2026 at 04:57 UTC
  (descending) and 16:12 UTC (ascending) over the Archipelago Sea and western Gulf of Finland, with the 24 Oct AIS
  capture (03:31–17:45 UTC).
- **Held-out (not read by any matching code before scoring):** the Sentinel-1C pass of 26 Oct 2026 at 04:41 UTC
  (descending; three IW frames, about 22–28°E, 58.7–62.2°N) with the AIS capture of 25 Oct 19:51 – 26 Oct 19:51 UTC.
  These AIS files are also the held-out set of the AIS spoofing test (`docs/validation/ais-baltic.md`); that test reads
  them first, for its own checks, and nothing from it feeds this one.
- **Extension (if a longer AIS capture runs):** every Sentinel-1 pass over the capture's coverage during the first
  seven days of the next AIS capture of at least seven days, up to 30 frames, scored with the same frozen rules and
  reported separately.

## Frozen

- **Detector:** `tools/ship_detect.py` as of this commit, with the setting recommended by the Sentinel-2 check: k = 6,
  `--min-contrast 10`, `--ghosts drop`, 20 m pixels, the default Natural Earth 10 m land mask with its 400 m buffer. No
  Sentinel-2 land mask: late-October Sentinel-2 over Finland is mostly cloud, and choosing scenes by cloud would be a
  choice made after seeing data.
- **Sea area scored:** pixels inside the scene's valid data, off the land mask, and at least 1.5 km from it (islands,
  skerries and harbours make the coast the main clutter source).
- **AIS at acquisition:** for each MMSI, its position linearly interpolated to the acquisition time from reports within
  ±10 min on both sides (or the single nearest report within ±2 min). A vessel with reports in the scene but none within
  ±10 min is "position unknown": never counted for D2, and a detection within 1 km of its last report isn't dark.
  Positions flagged by the AIS spoofing tests (`ais_detect.py` ais-0.1) are treated as unknown.
- **Length:** AIS dimensions refA + refB, when both are present and the sum is 5–400 m.
- **Matching:** one to one, nearest pairs first, within 1 km. The 1 km allows for the radar's along-track shift of moving
  ships (a few hundred metres at typical speeds).
- **Fixed sites:** a detection within 100 m of a site that `ship_detect.py persist` finds in at least 60% of the
  development and held-out passes (buoys, beacons, turbines) is a fixed structure, not a ship.

**Amendment 1 (26 Oct 2026, committed 17:59 UTC (ba70c1f), before any held-out data was read and before the matcher
existed).** Four gaps in the text above, closed here:

- **Scored area:** also restricted to the AIS detector's named regions "Gulf of Finland 22.5-27E", "Gulf of Finland east
  of 27E" and "Archipelago Sea and Aland" (`ais_detect.REGIONS`, first match, so Narva Bay is excluded), where Finnish
  shore stations hear vessels across the water. Detections and vessels elsewhere are reported, not scored.
- **Processing:** each region is read in tiles of 1° longitude by 0.7° latitude with 0.04° of padding, and points are
  scored only in a tile's core. Tiling only splits the work: the CFAR ring is 620 m, well inside the padding.
- **Fixed sites:** decided in the matcher (`tools/dark_match.py`), not by `ship_detect.py persist`, which reads another
  output folder: a detection is a fixed structure if at least two passes cover its point and at least 60% of those have
  a detection within 100 m of it.
- **Spoofing flags and unknown positions:** a vessel is "position unknown" at acquisition if it has reports within
  ±30 min but no position by the interpolation rule; if `ais_detect.py` lists it among spoofing victims (any reading)
  with a flagged span (first to last flagged report, ±10 min) covering the acquisition; or if the interpolation segment
  implies more than 60 kn.

## Checks

| # | Check | Pass if |
|---|---|---|
| H1 | Recall for large ships (D2's base) | Of AIS vessels 100 m or longer with a known position in the scored sea area, at least 85% have a matched detection |
| H2 | Position agreement | The median distance between matched AIS positions and detections, for vessels 100 m or longer, is 500 m or less |
| H3 | Large dark detections are rare | Detections with an estimated length of 50 m or more, not at a fixed site, with no AIS match: at most 10% of all detections of 50 m or more |

**Verdict rule.** D1/D2 validated (regional: Finnish waters, ships of 100 m or more) if H1, H2 and H3 pass. Partly
validated if H1 and H2 pass and H3 fails (the detector finds ships, but unmatched large targets are too common to be read
as dark ships without review). Not validated if H1 or H2 fails. If the held-out pass holds fewer than 20 AIS vessels of
100 m or more in the scored area, the result is reported as "too few ships" and the verdict waits for the extension.

**Reported, not scored:** recall for 50–100 m vessels; phantom candidates (D2) listed with length, speed and distance to
land; every large dark detection as an image chip, reviewed by eye in fixed categories (vessel-like, clutter, structure,
unclear); detections near the Finnish–Russian maritime border counted apart, because naval vessels there often don't
transmit, which is a legitimate reason for a dark ship, not evidence of wrongdoing. Ships near the scene edge and in ice
(none expected in October) are counted apart.

## Limits stated in advance

- One held-out pass is a small sample. The extension exists for that reason.
- AIS reception from Finnish shore stations weakens far offshore and near Estonia; a vessel the network doesn't hear is
  "unknown", not dark, only if it was heard within ±10 min. A vessel never heard looks dark to this test.
- Small craft (under about 15 m) don't have to carry AIS and are rarely resolved at 20 m pixels; this test says nothing
  about them.
- Positions and identities of individual vessels stay private. Only counts and the verdict are published.

## Development notes (24 Oct passes; not the held-out test)

The matcher (`tools/dark_match.py`) was built and run on the two development passes only (Sentinel-1C, 24 Oct 2026,
04:57 UTC descending and 16:12 UTC ascending, with the 24 Oct AIS capture). The held-out pass hasn't been read.

| | Variant A (as pre-registered) | Variant B (amendment 2) |
|---|---|---|
| Detections in the scored area | 5,831 | 85 |
| AIS vessels scored (known position) | 59 | 45 |
| H1: ships of 100 m or more matched | 36 of 37 (97%) | 34 of 34 (100%) |
| H2: median position gap, matched ships of 100 m or more | 404 m | 404 m |
| H3: large detections (50 m or more) with no AIS match | 3,524 of 3,576 (98.5%) | 36 of 81 (44%) |
| 50–100 m ships matched (reported) | 11 of 12 | 11 of 11 |

- **The detector finds the ships AIS says are there.** Both variants pass H1 and H2 on the development passes. The
  ~400 m median gap is the along-track shift of moving ships in radar images, as expected.
- **Variant A is swamped by land.** 2,625 of the 2,911 detections on the first pass were in the Archipelago Sea: skerries
  and islets that the Natural Earth 10 m coastline doesn't contain. The Finnish and Estonian coasts of the Gulf of
  Finland show the same.
- **Variant B removes most of it, not all.** With OpenStreetMap land added, 40 detections stay unmatched, 36 of them 50 m
  or more. None lies within 2 km of any AIS vessel, so they aren't shifted images of moving ships. About a third lie
  2–8 km straight along the satellite track from a large ship, which fits azimuth ghosts (the Sentinel-2 check found
  ghosts 4.3–6.3 km along track); the detector's ghost filter, tuned at Singapore, misses them here. The rest lie
  across track and are unexplained so far (uncharted rocks, navigation marks, aquaculture, or vessels without AIS).

**Amendment 2 (26 Oct 2026, before any held-out data was read).** Variant B is added: identical to variant A except that
OpenStreetMap land polygons (`osm-land-polygons` in the registry, ODbL; `data/ref/osm/baltic_land.json`, cut from the
26 Oct 2026 download) are passed to `ship_detect.detect_array` as its extra land mask (rasterised at 20 m, all pixels
touched; the detector then drops detections on or within 40 m of that land and removes it from the sea area). Variant A
stays the pre-registered primary. Both will be scored on the held-out pass with the same checks and verdict rule, and
both reported.

**Amendment 3 (26 Oct 2026, committed before the held-out pass was read).** Two rules, both from the development
findings above, applied to variant A and variant B alike (`dark_match.py score --amend3`):

- **Fixed-object map.** Every Sentinel-1 pass over the scored regions from 10 to 23 Oct 2026 (39 passes, development
  period only, no AIS) is run through the same detector (`dark_match.py clutter`). A place where a detection falls
  within 100 m in at least half of the passes whose scoring area covers it, with at least 4 covering passes, is a fixed
  object (rocks and islets missing from the coastlines, beacons, buoys, aquaculture). Detections there count neither as
  ships nor as dark ships. A vessel anchored at one spot through most of those passes would also be removed: stated, not
  corrected.
- **Ghost rule.** An unmatched detection lying 3.5–7.5 km from a matched detection, or from a known AIS vessel of 50 m or
  more, along the satellite track (the pass's along-track bearing from the image geometry) and within 800 m across it,
  is an azimuth ghost, not a dark ship.

H1–H3 and the verdict rule are unchanged. The held-out pass is scored for variant A as pre-registered, and for both
variants with amendments 2 and 3; all are reported.

**Not scored yet, on purpose.** On the development passes both variants would come out "partly validated" (H3 fails). A
ghost rule that uses AIS-positioned ships, and a fixed-site map from more passes, would be decided and written here as
amendment 3 before the held-out pass is read. Until then the held-out pass stays unread.

---

## Results

**Scored 27 Oct 2026** (`dark_match.py run` on the held-out pass from 00:06 UTC, outputs written 00:14 and 00:19 UTC,
after amendment 3 was committed at 22:19 UTC on 26 Oct; `dark_match.py score --set heldout`). One pass: Sentinel-1C,
26 Oct 2026 04:41 UTC, descending, three IW frames, with the 25–26 Oct AIS capture.

| | A, as pre-registered | B (amendment 2) | B with amendment 3 | A with amendment 3 |
|---|---|---|---|---|
| Detections in the scored area | 857 | 86 | 86 | pending |
| AIS vessels scored (known position) | 94 | 83 | 83 | |
| H1: ships of 100 m or more matched (≥ 85%) | 75 of 75 (100%): **pass** | 75 of 75: **pass** | 75 of 75: **pass** | |
| H2: median position gap, matched ships of 100 m or more (≤ 500 m) | 105 m: **pass** | 105 m: **pass** | 105 m: **pass** | |
| H3: large detections with no AIS match (≤ 10%) | 591 of 678 (87%): **fail** | 3 of 86 (3.5%): **pass** | 1 of 84 (1.2%): **pass** | |
| Verdict (rule above) | **partly validated** | **validated (regional)** | **validated (regional)** | |

A with amendment 3 waits for its own fixed-object map (`dark_match.py clutter --variant A`, running); it will be added
here, and it can't change the verdicts above.

**Reported, not scored.**

- 50–100 m ships matched: 6 of 6 in every variant. Phantom candidates (AIS ships of 50 m or more with no detection): 0.
- Large dark detections east of 27°E (counted apart: naval vessels near the Finnish–Russian border often don't
  transmit): 15 in variant A, 0 in B.
- Variant B's three large dark detections, reviewed by eye on 20 m image chips (private): one faint point in open water,
  estimated 92 m at 11.0 dB contrast, just over the 10 dB floor (**unclear**); and two points that amendment 3's
  fixed-object map, built from 39 earlier passes without AIS, marks as fixed objects (**structure**: an offshore light or
  beacon fits; one also lies about 3.7 km along track from an AIS ship, so a ghost was the first guess by eye). Variant A's
  591 are mostly islets and skerries outside the Natural Earth coastline, as on the development passes; not reviewed one
  by one.
- Amendment 3 flagged 2 fixed-object detections and 1 ghost in variant B.

**What this shows.**

- **The detector finds the large ships AIS reports.** All 75 ships of 100 m or more, and all 6 of 50–100 m, were
  matched within 1 km, with a 105 m median gap (smaller than on the development passes, about 400 m; fewer of these ships
  were moving fast across track). D2's base holds on this pass.
- **With a proper coastline, large unmatched targets are rare.** The pre-registered variant fails H3 only because Natural
  Earth's coastline misses the skerries; with OpenStreetMap land (amendment 2, decided on development data) 3 of 86 large
  detections are unmatched, and 1 after amendment 3. A list that short can be reviewed by a person each time, which is
  what H3 asks.
- **Limits.** One pass, 75 large ships, Finnish waters, October (no ice). The pre-registered primary is "partly
  validated"; the "validated" verdicts rest on amendments made before the held-out read, on development data. The
  extension (Sentinel-1 passes in the first seven days of the 7-day AIS capture that began at 00:06 UTC on 27 Oct 2026,
  up to 30 frames, same frozen rules) will be scored and reported separately.
