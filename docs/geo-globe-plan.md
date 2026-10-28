# GEO globe: plan

Drafted 27 Oct 2026 after Tom approved every idea in the proposal. This plan decides the build order; anything marked
*to check* is not verified yet. The GEO board (`tools/geo.py`, the /geo page) stays; the globe becomes the tool at the
top of that page, with the board's tables below it as the text view.

## 1. Data

**Today.** `tools/geo.py snapshot` takes CelesTrak's "Active Geosynchronous" group (GP elements as OMM JSON, plus the
catalogue) once or twice a day into `<day>.geo.json` on the `pnt-data-YYYY-MM` release. The second run of a day
replaces the first, so element sets are lost. CelesTrak's documentation doesn't state the group's membership rules,
so inactive payloads, rocket bodies, debris and the graveyard orbit are outside what we can see today.

**Space-Track (Tom has an account).** The elements CelesTrak serves come from Space-Track, which also keeps every
element set ever published (`gp_history`). With it:

- **Backfill.** One `gp_history` pull per object list and date range recovers every element set, including the ones
  our second daily run overwrote, so no fix to the snapshot is needed. Target: 90 days at first, more if the files
  stay small (about 4 MB a month raw, 1 MB compressed, for all GEO objects: an estimate).
- **Daily.** One `gp` query for the whole GEO region (section 2) instead of CelesTrak's active list. That covers
  inactive payloads, rocket bodies, debris and the graveyard.
- **Limits.** Under 30 requests a minute and 300 an hour, as quoted from the Space-Track guidelines by the
  [spacetrack library's documentation](https://spacetrack.readthedocs.io/en/stable/usage.html). *To check* against
  space-track.org's own documentation and user agreement before the first automated run. The collector makes one
  daily query and a chunked one-off backfill, far under either limit.
- **Credentials.** `SPACETRACK_USER` and `SPACETRACK_PASSWORD`: GitHub secrets for the daily workflow and Windows
  user variables on this PC, set by Tom. Never printed or stored in the repo.
- **Licence.** Basic SSA data may be redistributed and used in published analysis with citation (terms re-read
  26 Oct 2026). Cite "Orbital data: USSPACECOM (space-track.org)". The source goes into `registry/sources.csv` first.

**Catalogue numbers.** The 5-digit catalogue ran out on 11 Jul 2026 ([CelesTrak](https://celestrak.org/)); new
objects are numbered 100000 and up and have no two-line element format. Everything here uses OMM JSON, which
carries them: the collector stores OMM records, and the viewer reads them with satellite.js `json2satrec`.

## 2. The region and who is in it

Our own definition, stated on the page, so arrivals and departures can be flagged:

- **Protected zone:** altitude 35,786 km ± 200 km and latitude within ±15°, the IADC geosynchronous protected region
  (IADC Space Debris Mitigation Guidelines; *to check* against the current revision).
- **Graveyard:** above the protected zone. The IADC end-of-life reorbit is a perigee raise of at least
  235 km + 1000·CR·A/m above GEO (*to check*, same source).
- **Membership events** between consecutive days: *arrived* (first seen in the zone), *left upward* (to the graveyard),
  *left downward*, *went quiet* (no new public elements for more than 7 days), *catalogue status changed*.

New objects and graveyard moves update automatically through these events: the viewer only draws what the data
holds, and the daily collector refreshes the data.

## 3. The viewer

Libraries: three.js and satellite.js 7.1.0 (both MIT), from the same CDNs the site already uses, with pinned versions.
Coastlines from Natural Earth (public domain) on a plain sphere. No build step. Touch rotate and zoom on phones. The
board's tables stay as the text and accessible view.

- **Positions.** SGP4/SDP4 from the OMM elements (satellite.js), in the Earth-fixed frame by default (station-kept
  satellites hang still, drifters slide along the belt, inclined orbits trace figure-eights). An inertial frame is a
  toggle. Accuracy: tens of kilometres, stated.
- **Scale.** At true scale the belt is a thin ring 6.6 Earth radii out, and 0.1° is 74 km, so co-located satellites
  are one dot. Two companions: zoom to a slot down to tens of kilometres, and a flat **belt strip** (longitude
  against latitude, zoomable) where picking inside a cluster works.
- **Select.** Click, shift-click, drag a box. Detail panel: name, catalogue number, launch designation, owner and
  country, type, launch date, longitude, drift, inclination, class, age of the elements, listed role with sources,
  nearest satellites, orbit-change history, membership events.
- **Search and filter.** Name, catalogue number, launch designation, owner code or country name, role; class, owner,
  type (payload, rocket body, debris), drift. Colour by class or owner.
- **Time.** A slider and playback over the past 1, 7, 30 or 90 days, drawn from the recorded element sets (each set
  propagated only until the next one), and the next 48 hours as a visibly different prediction. Trails for the
  selection or for everything.
- **Share and export.** View, selection and time in the link; selection as CSV.
- **Relative motion** of two selected satellites: separation over time, and their motion relative to each other along
  three axes (radial, along-track, cross-track), observed and predicted.
- **Look angles from a place.** Pick a city or click the globe: which satellites are above the horizon, at what
  elevation and bearing. The sun's direction and the predicted sun-outage windows from the Sun outages page.
- **Board overlays.** Close pairs as lines, orbit changes and membership events as markers.

## 4. Callouts

Automatic highlights of movements and positions worth an analyst's look, on by default, with a toggle and a filter
by rule. Each callout names its rule and the numbers behind it. They describe behaviour, never intent. Draft rules
(thresholds are frozen and written here before they are run on history):

| # | Callout | Draft rule |
|---|---|---|
| C1 | Close to another owner's satellite | Separation under 100 km at the common time, different owners; raised a level when one has a listed inspection or servicing role |
| C2 | Approaching | Separation to another owner's satellite falling on 3 or more consecutive days and now under 200 km |
| C3 | Parked beside another owner | Stopped drifting within 0.5° of another owner's station-kept satellite |
| C4 | Heading for an occupied slot | Drifting, slowing, and predicted to stop within 0.5° of another owner's satellite in the next 14 days |
| C5 | Listed-role object changed orbit | Any flagged orbit change, routine or not, by an object with a listed inspection or servicing role |
| C6 | Arrived | First seen in the protected zone |
| C7 | Retired to the graveyard | Left the zone upward (information only) |
| C8 | Went quiet | An active payload with no new public elements for more than 7 days |

**Validation before they go live.** With the Space-Track backfill, run the frozen rules over history and score them
against a list of published cases. The list is written, with sources, before the rules are run. Candidates to check:
reported approaches by Russia's Luch (Olymp-K) satellites to commercial satellites from 2015, and China's Shijian-21
moving a dead BeiDou satellite to the graveyard in January 2022. Also count callouts per week on quiet history, so
the default view isn't noise. Public elements can't resolve separations under about 50 km, and that stays stated.

## 5. Footprints

Three kinds, always labelled by kind:

- **Line of sight (computed).** Where the satellite is above a chosen elevation (0°, 5°, 10°). Exact geometry from
  its position.
- **Hypothetical beam (computed).** The analyst picks a band and an antenna size or a beamwidth
  (θ3dB ≈ 70·λ/D degrees) and clicks a boresight point; the viewer projects the −3 dB contour, and optionally −6 and
  −10 dB, onto the Earth from the satellite's true position, so slant-range stretching is right. Useful for asking
  where an uplink jammer would have to be. Labelled "hypothetical".
- **Published footprints (sourced).** Candidate sources, each checked and entered in `registry/sources.csv` with its
  licence before anything is drawn:
  - Operators' own coverage maps (Intelsat, SES, Eutelsat and others): usually copyrighted images. Expect link-out
    only.
  - SatBeams: a commercial footprint collection; copyrighted. Expect link-out or visual comparison only.
  - FCC filings for US-licensed satellites: public records, some with beam contour files. *To check*: format,
    coverage and reuse terms.
  - ITU filings: the Space Network List is free to view; the beam data (GIMS) comes with ITU's paid publications.
    *To check*.
  - Government satellites with published coverage (for example meteorological satellites). *To check*.

  Where the licence doesn't allow redrawing, the detail panel links to the operator's page instead.

## G1 done (27 Oct 2026)

`tools/geo_region.py` (tests: `tests/test_geo_region.py`). Daily: one gp query per daily run (`daily.yml`, step "GEO region
(Space-Track)"; skipped if the release's file for the day was fetched less than an hour before) writes
`<day>.geo-region.json` and adds the new element sets to `geo-elements-YYYY-MM.parquet`. Backfill run once on 27 Oct:
gp_history from 1 Jul 2026 for the 1,836 objects then near GEO, in 19 requests of 100 objects at under 5 a minute;
535,638 element sets (about 2.5 per object per day, 5–7 MB of parquet a month); the downloaded chunks and a manifest
of whose history is held stay in `data/geo/region/history/` on this PC (never fetched again). Region files replayed for
29 Jul – 27 Oct. Two changes after the first replay: 25 km / 0.25° hysteresis at the zone's edges (zone flips fell
from 68 to 30 in 90 days; the rest are real orbit changes), and "quiet" only for payloads on CelesTrak's active list
(97 events fell to 17: SJ-20, TJS-15, TJS-16, TJS-19, Shiyan 12 01 and 02, USA 270, Luch (Olymp) 2, MEV-1 and
others). Not yet done: rocket bodies and debris aren't drawn anywhere but the counts; G2 will need the element history
thinned (for example one set per object per 6 hours) before it goes to the browser.

## G2 done (28 Oct 2026)

`tools/geo_globe.py` (tests: `tests/test_geo_globe.py`) builds `site/data/geo/globe.json` (every object near GEO with its
latest elements, the active flag and owner names from `site_src/satcat_owners.json`, fetched from CelesTrak's owner
list on 27 Oct 2026) and `tracks-{1,7,30,90}d.json` at deploy (15 min, 1 h, 4 h and 12 h samples; 1.4–3.8 MB each).
`site_src/globe.js` (three.js 0.185.0 and satellite.js 7.1.0 from jsDelivr, pinned) draws the globe at the top of
/geo: search, filters, colour by where/type/active/owner, click, Shift-click and Shift-drag selection, the detail panel
(with the board's role, close pairs, orbit changes and arrivals), CSV, links that keep the state (`#g=`), the time
slider (recorded past, 48 h predicted), tracks for the selection or everything shown, the dashed 48 h prediction,
line-of-sight circles at 0/5/10° elevation, and the flat belt strip (height or latitude against longitude). Not done
yet: an inertial-frame toggle (left out: tracks are Earth-fixed), the sun's direction (G3).

## G5 done (28 Oct 2026)

- **Hypothetical beams** (detail panel, one selected satellite): band (UHF to Ka, up and down), dish diameter or beamwidth
  (θ3dB ≈ 70λ/D), presets (Earth cover 17.4°, regional 3°, spot 0.6°), −3 dB plus optional −6 and −10 dB contours from
  the main lobe G = Gm − 3(ψ/ψ½)² dB (the form ITU-R S.1528 gives after S.672), projected from the satellite's position,
  so slant stretch is right and contours break at the Earth's edge. "Click the Earth to aim" refuses points beyond the
  satellite's horizon. Beams travel in the link (`b:`). Checked: 0.6° at nadir lands 375 km across, 17.4° 10,956 km
  (the Earth's edge from GEO), Ku 12 GHz with a 2 m dish 0.87°.
- **Footprint files**: a KML or GeoJSON the analyst holds is drawn in their browser and never uploaded (fits SatBeams'
  internal-use KML licence).
- **Published footprints**: not drawn. Registry rows `satbeams` (exclude: proprietary; KML internal use only),
  `operator-coverage` (exclude), `fcc-space-filings` (later: public records, applicants' work, no reuse terms stated:
  Tom to decide after a format and access check) and `itu-space-filings` (later: GIMS beam data comes with the paid BR IFIC).
- "Fly to it" now parks the camera on the line from the Earth's centre through the satellite, so the Earth sits behind
  it and can be clicked to aim.

## 6. Build order

| Step | What | Needs |
|---|---|---|
| G1 | Space-Track collector: daily GEO-region pull, membership events, 90-day backfill; registry entry | Tom sets the two credentials |
| G2 | Globe and belt strip: positions, select, search, filter, detail panel, links, time slider, trails | Data from the current snapshots, then G1's history |
| G3 | Relative motion, close-approach chart, look angles, sun direction and outage windows, board overlays, CSV | G2 |
| G4 | Callouts: freeze the rules, write the published-case list, score on history, then switch on | G1 history |
| G5 | Footprints: line of sight and hypothetical beams, then the published-source licence review and whatever passes | G2 |

Each step is finished, checked on the live site and committed before the next.
