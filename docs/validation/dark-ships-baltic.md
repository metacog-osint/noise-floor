# Dark ships and phantom tracks in Finnish waters (maritime M2): pre-registration

**Written 26 Oct 2026 at about 18:00 UTC, before any matching code existed and before the held-out data was read.**
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

---

## Results

(Not yet scored.)
