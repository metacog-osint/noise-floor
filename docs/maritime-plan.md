# Maritime lane plan: vessels and their signals (South China Sea and Indian Ocean)

**Status: planned, 23 Oct 2026. Nothing is built yet.** This document is the working plan for any session that picks the lane
up. It records what was decided, what was assessed and parked (with the reason), the detectors, the data model, the
validation plan and the open decisions. Watch configuration (exact areas of interest, vessel watch lists) stays private,
as for every other lane: see `CLAUDE.local.md` for where it lives.

## 1. Bottom line

- **Worth building, narrowly.** The lane's value is combining signals that AIS-only trackers keep apart: AIS behaviour,
  ships seen by radar satellites while silent on AIS, RF emitters at sea, GNSS interference footprints and declared activity.
- **Two hard limits:**
  - Licence-clean ship positions are scarce in this region: no open global AIS feed exists, and satellite AIS is paid.
  - No free source sees a vessel's satellite communications (VSAT, Inmarsat, Iridium, Starlink).
- **Lead with one validated method, not a whole map:** dark ships and phantom tracks (radar-satellite detections matched
  against AIS) at one focus area, written up the way Phase 1 was, before widening.

## 2. Goals and non-goals

**Goals**
- Find and characterise interesting vessels and behaviour in a few focus areas:
  - dark ships and phantom tracks;
  - ship-to-ship transfers and identity laundering (shadow fleet);
  - coast guard and maritime militia pressure near contested features;
  - behaviour that risks undersea cables;
  - platforms carrying GNSS jammers or radars.
- Publish validated methods and licence-clean layers; keep everything else in the private watch.
- Build our own database of vessels, identities, observations, signals and behaviour events, with sources and confidence
  on every record.

**Non-goals**
- The content of private communications (voice or messages). We record metadata only (Section 11).
- Private craft, crew identities or anyone's personal life. State and commercial vessels only.
- Real-time targeting, or paid data on the free tier.

## 3. What we can observe

Licence status follows `registry/sources.csv`. Rows added on 23 Oct with "licence not yet read" must be checked before
they feed anything.

| Signal | Sources | Licence status | What it gives | Public or private |
|---|---|---|---|---|
| AIS positions and identity (VHF) | aisstream.io (volunteer-fed, free API) | No published terms: ask | Live coastal coverage; patchy mid-ocean | **Private** until terms are clear |
| | Global Fishing Watch | CC BY-NC | Best global picture, incl. encounters and loitering | Visual comparison only |
| | Government open AIS (Finland, Norway, Denmark, US) | Open | Home waters only; none in this region | Methods and testing only |
| | Satellite AIS (Spire, ORBCOMM, exactEarth) | Paid | Full ocean coverage | Out of scope |
| Ship detection by radar satellite | Sentinel-1 (Copernicus) | Free incl. commercial | Ships regardless of AIS; 6-day revisit restored in June 2026 with Sentinel-1C/1D. Open-ocean acquisitions in this region still to check against ESA's acquisition plans | Public (derived) |
| Ship detection, optical | Sentinel-2, Landsat 8/9 | Copernicus free; USGS public domain | Confirm radar detections in clear weather; vessel size and type | Public (derived) |
| Ship radars | Interference in Sentinel-1 (C-band, 5.3–5.5 GHz radars) and NISAR (L-band) images | As above (NISAR CC0) | Some naval air-search radars show up; research-grade | Private until validated |
| Lights and flares at night | VIIRS Boat Detection and VIIRS Nightfire (Earth Observation Group) | Free with registration; detections older than 45 days free; no formal licence found: ask | Lit fishing and militia fleets; platform and FPSO flares; burning ships | Public if the licence allows |
| GNSS interference at sea | Our ADS-B map (coastal coverage); AIS position anomalies; CYGNSS noise floor | Ours; CYGNSS CC0 | Jamming and spoofing footprints; jamming platforms | Public (ADS-B derived, ODbL) |
| HF communications (metadata only) | Public KiwiSDR receivers; YaDDNet volunteer DSC logs | KiwiSDR per-owner consent; YaDDNet terms unknown | DSC calls (MMSI, call type, distress and position reports); TDoA fixes of HF emitters, jammers and over-the-horizon radars; NAVTEX and weather fax | Private first |
| Weather and ocean state | ECMWF open data, NOAA GFS and WAVEWATCH III, Copernicus Marine, ERA5 (history) | Mostly open with attribution: to verify per source | Sea state, wind, currents, ducting | Public (context) |
| Declared activity and incidents | NGA broadcast warnings, UKMTO, JMIC, ReCAAP ISC, IMB PRC, China MSA warnings, India NAVAREA VIII | NGA and UKMTO verified; the rest unverified | Exercises, live-fire areas, incidents | Public where licensed; otherwise cite-only |
| Identity and sanctions | OFAC SDN (vessels with IMO numbers), UK sanctions list | US gov; OGL (to verify) | Sanctioned vessels, owners | Public |
| | OpenSanctions | Non-commercial | Merged lists | Excluded |
| | ITU ship-station list (MARS), IMO GISIS, Equasis | Permission or registration; restricted reuse | Call signs, owners, flags | Private lookup at most |
| Reference geography | Marine Regions (EEZs, boundaries), NGA World Port Index, GEBCO bathymetry, OSM coastline and submarine cables | CC BY 4.0 (to verify), US gov, GEBCO terms (to verify), ODbL | Boundaries, ports and anchorages, shoals, cable routes | Public |
| | TeleGeography Submarine Cable Map | Believed non-commercial: to verify | Cable routes | Visual only unless cleared |
| Analysis for validation | AMTI (CSIS), SeaLight (Stanford), Global Fishing Watch and C4ADS reports, HawkEye 360 public reports | Copyright | Known cases and labels | Cite-only |

## 4. What we can't observe (assessed 23 Oct and parked)

| Idea | Verdict | Why |
|---|---|---|
| VHF voice (channel 16 and 13: bridge to bridge, coast guard challenges) | Not remotely | Line of sight, about 20–40 NM. Needs our own coastal receivers (the feeder idea, Section 13 M7) |
| Per-vessel SATCOM | No | Encrypted or commercial. Commercial RF-geolocation constellations (HawkEye 360, Unseenlabs, Kleos) detect VHF push-to-talk and satellite-phone uplinks, at a price. We can still track SATCOM jamming and the GEO picture (SATCOM lanes) |
| Passive radar from ubiquitous signals (Starlink, DVB-T, GNSS) | Not remotely | A Chinese team's forward-scatter demonstration used Starlink downlinks and a ground receiver to detect a DJI Phantom 4 Pro drone (a stand-in for a stealth aircraft) off Guangdong. Media reports only; the paper hasn't been read, so its performance is unverified. Ships are large targets, but this needs receivers near the target area |
| Ship detection by spaceborne GNSS reflections (CYGNSS) | Not for ships | An oil platform has been seen in TechDemoSat-1 data; ship detection from orbit is still mostly simulation (resolution of a few km, unsuited antenna polarisation). CYGNSS stays useful for GNSS jamming over the sea |
| Weather radar and geostationary weather imagery as detectors | No | Coastal radars show ships only as unreliable clutter and few cover open water; geostationary pixels are 0.5–2 km. Ship tracks in low cloud fell by half or more after the 2020 sulphur rules and are rare in the tropics |
| An open global AIS feed (an "adsb.lol for ships") | Doesn't exist | MarineTraffic combines about 3,500 shore receivers (many volunteer-hosted, under its terms) with satellite AIS from exactEarth. Government open AIS covers home waters only |

Weather still matters as **context and prediction** (detectors D10, Section 6).

## 5. Detectors

Each detector produces events with a time, place, vessel(s), inputs, rule, confidence and source licence. All thresholds
below are starting points, to be fixed on known cases before any test (Section 10).

| ID | Detector | Rule (starting point) | Inputs |
|---|---|---|---|
| D1 | **Dark ship** | Radar-image detection (CFAR on Sentinel-1 GRD, length estimate from the image) with no AIS position within ±10 min and ±1 km of the acquisition | Sentinel-1, AIS |
| D2 | **Phantom track** | AIS position inside a radar image's footprint at acquisition time, with no detection where a ship of the reported length should show | Sentinel-1, AIS |
| D3 | **Ship-to-ship transfer** | Two vessels within about 500 m, both slower than 2 kn, for over 2 h, away from a port or anchorage | AIS; D1 detections pairing with AIS ships |
| D4 | **Loitering** | One vessel slower than 2 kn for over 6 h outside ports, anchorages and fishing grounds | AIS |
| D5 | **Going dark** | AIS gap of over 6 h starting and ending inside good coverage (judged from other vessels' reception there) | AIS, coverage baseline |
| D6 | **Identity change and text signals** | Change of MMSI, IMO, name, flag or call sign for the same hull (track continuity, size); destination-field messages such as "Chinese crew" or "no Israel link" in the Red Sea | AIS static data |
| D7 | **Spoofed track** | Implied speed above the vessel class's maximum, positions on land, circles or convergence on one point (the aircraft spoofing detectors applied at sea) | AIS, coastline |
| D8 | **Cable risk** | 1–3 kn in a near-straight line across a cable route for over 30 min, or an AIS track that stops over a cable | AIS, cable routes |
| D9 | **Pressure near features** | Closest approach under 500 m at over 10 kn relative speed (shadowing, blocking); clusters of state or militia-linked hulls around a contested feature against its usual level (swarming) | AIS, D1, reference lists |
| D10 | **Weather-implausible or sheltering** | A small vessel holding station in sea states its class can't work in (likely spoofed position); fleets sheltering before storms (expected, not suspicious) | AIS, waves and wind |
| D11 | **RF emitter at sea** | Interference in Sentinel-1 or NISAR images against that area's own baseline; GNSS degradation footprints at sea, fed to the radio-horizon localizer; CYGNSS noise-floor rises | Sentinel-1, NISAR, ADS-B, CYGNSS |
| D12 | **HF activity** | DSC calls (who called whom, positions when sent); TDoA fixes of persistent HF emitters | KiwiSDR, YaDDNet |
| D13 | **Missing traffic** | AIS traffic or night lights against the area's usual level (the maritime version of the map's "Fewer aircraft than usual" view) | AIS, VIIRS |

"Aggressive" and "benign" are **indicators for a person to review**, never an automatic verdict.

## 6. Prediction

- **Where could a dark vessel be now?** From its last fix, the class's speed range and the forecast currents and waves,
  compute a probability area, as search-and-rescue planning does. It tells us where to look in the next radar or optical pass.
- **What is the vessel physically able to do?** Sea state and wind limit small craft. That flags impossible tracks (D10)
  and explains expected absences, such as fleets in shelter during typhoons.
- **How far will RF travel?** Ducting forecasts (refractivity from weather models) explain detection ranges. The 2025 TDOA
  study of the Baltic reported reception beyond the radio horizon, likely through sea ducting.

## 7. Database

A private store first (SQLite or DuckDB on Tom's PC under `private/`, gitignored), with public outputs derived from
licence-clean inputs only.

| Table | Holds |
|---|---|
| `vessel` | One row per hull we believe in: best IMO, length, type, first and last seen |
| `identity` | Time-ranged identity claims for a vessel: MMSI, IMO, name, flag, call sign, with source |
| `observation` | Every sighting: time, position, source (AIS, radar image, optical, night lights, HF), quality, link to vessel if matched |
| `signal` | Emissions seen: AIS message type, radar interference (band, footprint), HF (DSC call, TDoA fix), GNSS interference exposure |
| `event` | Detector outputs (Section 5): type, time span, place, vessels, rule version, confidence |
| `assessment` | A person's review of an event: label, basis, grade (the five-field grading planned in Phase 6) |
| `source` | Registry id, licence and retrieval time for every row above |

Rules: every row names its source and licence; rule versions are stored with events so results can be re-run; watch
lists live in private config, never in tracked files.

## 8. Architecture

- **GitHub Actions (public, licence-clean):** Sentinel-1 and Sentinel-2 searches and ship detection over the focus
  areas, VIIRS products if licensed, declared warnings, weather context. Outputs go to release assets, as for the GNSS lane.
- **Tom's PC (private):** the AIS stream (a long-lived websocket, which Actions can't hold) and scheduled KiwiSDR sessions,
  writing to the private store. Same pattern as the NISAR lane.
- **Public site:** a separate **Sea** map page reusing the GNSS map's engine (pre-projected geometry, caching, events
  panel, "usual level" logic).
- **Private view:** behind Cloudflare Access, like the NISAR view. New services (D1, Workers cron, ntfy) still need Tom's OK.
- **Shared with existing lanes:** the GNSS map (coastal South China Sea and the Hormuz trend area), the NISAR lane (a
  private coastal watch area can be added), the radio-horizon localizer (jammers on ships), the declared lane.

## 9. Focus areas

Start with four, named here; exact boxes are private config.
1. **The Spratlys and Scarborough Shoal:** Second Thomas Shoal, Whitsun (Julian Felipe) Reef, Mischief Reef, Scarborough.
2. **Singapore Strait and the ship-to-ship transfer area off Johor.**
3. **Strait of Hormuz and the Gulf of Oman:** already on the GNSS trend; a spoofing hot spot; shadow-fleet traffic.
4. **Bab el-Mandeb and the southern Red Sea.**

**Sentinel-1 revisit, 25 Aug – 24 Oct 2026** (Planetary Computer catalogue; only Sentinel-1C and -1D appear):

| Area | Passes in 60 days | Note |
|---|---|---|
| Spratlys | 5 | One descending track, every 12 days |
| Scarborough Shoal | 10 | Two descending tracks |
| Singapore Strait and Johor | 19 | Only one track covers all the open water, every 12 days |
| Strait of Hormuz and Gulf of Oman | about 1 a day | Larger area, several tracks in both directions |
| Bab el-Mandeb | about 1 a day | Larger area, several tracks in both directions |

Radar coverage of the open South China Sea is sparse. Dark-ship counts at the Spratlys would rest on about one image every
12 days, so that area is better suited to case studies than to a daily layer.

Candidate fifth: the Taiwan Strait (cable incidents, exercises). The wider South China Sea and Indian Ocean follow once
one method is validated.

## 10. Validation

As in Phase 1: known cases first, rules fixed before scoring, held-out cases, baselines stated, failures kept on the record.

**Candidate known cases** (from memory or reporting; each is checked against its primary source before it's scored):
- Whitsun Reef militia gathering, March 2021 (Philippine government statements; AMTI and SeaLight analysis).
- Incidents at Second Thomas Shoal, 2023–2024 (Philippine Coast Guard and AFP statements).
- Undersea cable damage: Eagle S, Gulf of Finland, December 2024 (a Baltic case, useful to develop D8); Hong Tai 58, near
  Taiwan, February 2025.
- Ship-to-ship transfers off Johor (published shadow-fleet investigations).
- Gulf GNSS spoofing, June 2025, when ships' AIS positions jumped onto land.
- Red Sea AIS messaging since 2024 (destination-field declarations of crew or ownership).
- Fake AIS tracks of warships in the Black Sea, 2021 (a phantom-track case, D2).

**First flagship test:** D1 and D2 at the Singapore Strait and Johor area. Score against cases documented in published
reporting, report misses and false alarms, and compare against a baseline (for example, every radar detection flagged as
dark).

## 11. Licensing, law and communications

- **Registry first:** every source is recorded with its licence before it feeds anything; non-commercial sources are
  visual comparison only; AIS-derived records stay private unless the source allows publishing.
- **Receiving maritime radio (US):** the Wiretap Act allows intercepting radio "by any marine or aeronautical
  communications system", and from public stations and distress traffic (18 U.S.C. § 2511(2)(g)(ii)).
- **Publishing is narrower:** 47 U.S.C. § 605 bars divulging the content or existence of radio communications except as
  that chapter authorises. Get legal advice before publishing any communications content.
- **Receivers abroad:** they follow local law. Some countries criminalise using information from non-broadcast
  transmissions; the UK is believed to be one (not checked).
- **KiwiSDR:** scripted, scheduled use needs each owner's consent.
- **Our posture:** metadata only (signal type, time, approximate location, identifiers a ship already broadcasts); never the
  content of private communications; collection stays private until reviewed.

## 12. People and ethics

- State and commercial vessels only; no private craft and no crew identities.
- Illegal-fishing claims affect livelihoods: they need strong evidence and careful wording.
- Volunteer feeders in Southeast Asia could face local legal risk; that is part of any decision on M7.

## 13. Build sequence

| Step | What | Done when |
|---|---|---|
| M0 | Decisions and accounts (Section 14) | Accounts exist; aisstream answered or AIS kept private |
| M1 | Sentinel-1 search and ship detection for focus area 2, plus a private AIS sample there | Detections and AIS tracks for at least 30 days of passes |
| M2 | **Flagship:** D1 and D2, validated and written up | Validation section in `docs/validation/`, results on the Validation page |
| M3 | D3–D7 (transfers, loitering, going dark, identity, spoofing) | Each tested on known cases |
| M4 | Context: weather (D10, Section 6), declared warnings, sanctions, EEZs, ports, cables (D8) | Layers in the private view |
| M5 | RF and HF: Sentinel-1 and NISAR interference at sea, CYGNSS, DSC and TDoA (D11, D12) | Each with a known case |
| M6 | Public **Sea** map with licence-clean layers; private view for the rest | Live page; method card |
| M7 | Optional feeder kit (AIS, VHF and DSC on one Raspberry Pi) for partners | Tom's decision |

**Progress (23 Oct 2026).** M1 detection is built (`tools/ship_detect.py`), ahead of the M0 accounts. Microsoft's
Planetary Computer serves Sentinel-1 GRD anonymously, so no Copernicus account was needed.
- **Revisit:** over 60 days (29 Aug – 22 Oct 2026), focus area 2 had 19 Sentinel-1 passes, all from Sentinel-1D. Only one
  relative orbit covers all of the area's open water: descending, about 22:47 UTC (06:47 local), every 12 days. The other
  three tracks cover 12%, 56% and 60% of it.
- **Detection:** a two-parameter CFAR on VV at 20 m (k = 6), with a Natural Earth land mask buffered by 400 m plus an
  image-based mask. Minimum length is 30 m, and detections within 200 m are merged (sidelobes of bright ships). A full pass
  gives 2,100–3,500 detections over about 10,400 km² of sea, with a median length of 66–80 m.
- **Threshold sensitivity** on the newest pass: 5,403 detections at k = 5, 3,480 at k = 6, 2,125 at k = 8 and 1,659 at k = 10.
  The count flattens above k ≈ 8–10, so at k = 6 some of the low-contrast detections are probably clutter.
- **Fixed against moving:** across the four full passes, 382 detections recur within 60 m on 60% or more of passes. These
  are fixed structures, moorings and long-stay anchored ships. Another 1,770–3,200 per pass are movers.
- **Not done yet:**
  - AIS (needs Tom's aisstream key), so detection rate and false alarms aren't calibrated.
  - No Sentinel-2 cross-check.
  - Azimuth ghosts aren't removed.
  - Outputs stay private.

## 14. Open decisions for Tom

1. Go ahead now, or wait on the open question of pausing new lanes until NISAR passes a ground-truth test? (Recommendation:
   go ahead, with one validated method first.)
2. Accounts and requests only Tom can make: a Copernicus Data Space account (Sentinel-1 and -2 downloads, free with quotas);
   Earth Observation Group registration (night lights); an email to aisstream about their terms.
3. Which focus area first (recommendation: Singapore Strait and Johor).
4. Whether to pursue a volunteer feeder network (M7), with its people and legal risks.

## 15. Ideas log (23 Oct 2026 discussion)

- Start a vessel-focused RF and SATCOM map in the South China Sea and Indian Ocean: **accepted, narrowed** to focus areas
  and one flagship method.
- Use MarineTraffic-style volunteer AIS: **no open equivalent exists**; aisstream privately, and a feeder network as an option.
- Weather to detect vessels: **no as a detector, yes as context and prediction** (D10, Section 6).
- Baseline aberrations in ubiquitous signals: **yes, in the form we already use** (D11, D13); remote passive radar parked.
- Ship communications: **metadata and safety broadcasts via public HF receivers** (D12); VHF voice and SATCOM out of reach.
- Added during review: phantom tracks (D2), cable risk (D8), AIS text signals (D6), reference geography, optical
  confirmation, gas flares, identity history built in from the start.

## 16. Sources cited in this plan (retrieved 23 Oct 2026)

- MarineTraffic support, terrestrial vs satellite positions: https://support.marinetraffic.com/en/articles/14594297-how-was-the-vessel-s-position-received-terrestrial-or-satellite
- MarineTraffic and exactEarth partnership (AJOT): https://www.ajot.com/news/marinetraffic-partners-with-exactearth-to-deliver-most-comprehensive-vessel-tracking-yet
- Kystverket open AIS (NLOD): https://www.kystverket.no/en/sea-transport-and-ports/ais/access-to-ais-data/
- US Army Corps of Engineers, "AIS Data: An Overview of Free Sources" (2023): https://apps.dtic.mil/sti/html/trecms/AD1193822/index.html
- VIIRS Boat Detection (Earth Observation Group): https://payneinstitute.mines.edu/eog/viirs-boat-detection-vbd
- Sentinel-1D opening and Sentinel-1C/1D revisit (Copernicus Data Space): https://dataspace.copernicus.eu/node/3176
- Ship radars in Sentinel-1 interference (Naval News, Dec 2020): https://www.navalnews.com/naval-news/2020/12/hidden-threat-to-navies-how-freely-available-satellite-imagery-can-track-radars/
- Finding ship radars in SAR images (Memorial University): https://memorial.scholaris.ca/items/3c00fba4-1c2a-4a70-9679-c5d5252dce6b
- Starlink forward-scatter demonstration (media): https://interestingengineering.com/innovation/china-starlink-detect-stealth-fighters ; https://spacesecurity.wse.jhu.edu/?p=7170
- Space-based maritime surveillance survey, incl. GNSS-R ship detection: https://arxiv.org/pdf/2011.11304
- Ship tracks fading after IMO 2020 (NASA, via Seatrade): https://www.seatrade-maritime.com/regulations/nasa-shipping-s-ghostly-fingerprints-fading-since-imo-sulphur-cap
- YaDDNet and the YADD DSC decoder: https://swling.com/blog/2022/11/guest-post-monitoring-digital-selective-calling-dcs-with-yadd
- KiwiSDR TDoA open to the public: https://www.rtl-sdr.com/?p=23633
- 18 U.S.C. § 2511: https://www.law.cornell.edu/uscode/text/18/2511
- 47 U.S.C. § 605: https://www.govinfo.gov/content/pkg/USCODE-2023-title47/html/USCODE-2023-title47-chap5-subchapVI-sec605.htm
