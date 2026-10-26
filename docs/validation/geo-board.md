# GEO board: first check against published cases (26 Oct 2026)

**Lane:** geo-board (built 26 Oct 2026; not validated). **Code:** `tools/geo.py`, page `/geo`. **Data:** CelesTrak GP elements
for the active geosynchronous group and its catalogue records (USSPACECOM basic SSA data, used with citation), snapshot of
26 Oct 2026, 569 objects. **This is a sanity check, not a validation:** it compares what the board shows on its first day
with published reporting. A validation needs manoeuvre history (snapshots began on 26 Oct) and announced events to score
against.

## Bottom line

- **Positions agree with published slots to about 0.2°.** Eutelsat 7C at 7.0°E, GOES-18 at 137.0°W (NOAA's GOES-West slot),
  Astra 1KR at 19.0°E (inside the Astra 19.2°E cluster).
- **The close-pair list mixes three kinds of proximity.** Inspection behaviour (Luch-5X/Olymp-K 2 near Intelsat 39),
  servicing (MEV-2 docked to Intelsat 10-02) and plain slot-sharing by communications satellites (USA 283 near the APSTAR-6
  satellites; Cosmos 2526 near JCSAT-3A). The board can't tell them apart, which is why the page says it shows proximity,
  never intent.
- **Inspection-capable satellites show up as drifting**, as their published concepts of operation say they should: GSSAP 5
  and 6 (USA 324, USA 325), Shijian-17, Shijian-23 and the two Shiyan-12 satellites.
- **One error of mine, corrected here:** in a status message on 26 Oct I called USA 283 a US inspector satellite. Public
  catalogues list it as CBAS-SATCOM, a US military communications satellite. Its proximity to the APSTAR satellites at 134°E
  is most likely slot-sharing, not inspection.

## Cases

| Case | The board on 26 Oct | Published | Agreement |
|---|---|---|---|
| MEV-2 and Intelsat 10-02 | 0 km apart at 1.0°W | MEV-2 docked to Intelsat 10-02 on 12 Apr 2021 for about five years; undocking planned for 2026 ([Wikipedia](https://en.wikipedia.org/wiki/Intelsat_10-02), [TechCrunch](https://techcrunch.com/?p=2137247)) | Consistent: still docked in the 26 Oct elements. Whether undocking has been rescheduled is unverified |
| Luch-5X (Olymp-K 2) and Intelsat 39 | 52 km apart at 62.0°E; Luch-5X station-kept there (drift −0.008°/day) | Slingshot reported Luch-5X moving along the belt after its March 2023 launch and stopping near commercial satellites, closest measured about 16 km ([Breaking Defense, Oct 2023](https://breakingdefense.com/2023/10/second-russian-luch-olymp-satellite-now-trailing-western-systems-in-orbit/)). A French report says it has been near Intelsat 39 since 7 March ([Europe 1](https://www.europe1.fr/node/668397); the year couldn't be confirmed: the page refused automated access) | Consistent with the published behaviour; the Intelsat 39 dwell date is unverified |
| USA 283 and APSTAR-6C/6D/6E | about 40 km at 134.0°E | USA 283 is CBAS-SATCOM, a US military communications satellite (Boeing 702SP, launched 14 Apr 2018; [KeepTrack](https://keeptrack.space/satellite/43339), [Satcat](https://www.satcat.com/sats/43339)) | Proximity of communications satellites, most likely slot-sharing; not an inspection case |
| Cosmos 2526 and JCSAT-3A | 45 km at 128.0°E | Cosmos 2526 is Blagovest No. 12L, a Russian military communications satellite (launched 18 Apr 2018; [russianforces.org](https://russianforces.org/blog/2018/04/launch_of_cosmos-2526_-_blagov.shtml)) | Proximity of communications satellites; not an inspection case on this evidence |
| GSSAP 5 and 6 (USA 324, USA 325) | Drifting +0.68 and −0.65°/day | GSSAP satellites operate near GEO and drift above and below the belt to inspect objects ([Air & Space Forces Magazine](https://www.airandspaceforces.com/weapons/gssap/), [Wikipedia](https://en.wikipedia.org/wiki/Geosynchronous_Space_Situational_Awareness_Program)) | Consistent with the published concept of operations |
| GSSAP 7 and 8 (launched 12 Feb 2026) | Not in the snapshot | Launch reported ([Wikipedia](https://en.wikipedia.org/wiki/Geosynchronous_Space_Situational_Awareness_Program)) | Not in CelesTrak's geosynchronous group on 26 Oct; a gap in the public data, not in the board |

## Leads, not checked yet

- **The 127–128°E cluster:** Shijian-21 (128.2°E), Shijian-25 (127.2°E), Cosmos 2526 (128.1°E), Cosmos 2589 (127.7°E, drifting
  −0.044°/day, launched June 2025) and JCSAT-3A (128.0°E) sit within about 1° of each other. Shijian-25 has been reported
  docking with Shijian-21 for refuelling in 2025. Not verified here; worth a dated check against published tracking.
- **Drifting Chinese experimental satellites:** Shijian-17 (−1.50°/day), Shijian-23 (−0.86°/day) and Shiyan-12 01/02
  (+0.77 and +0.61°/day). The manoeuvre history the daily snapshots build will show where they stop.

## What this means for the board

- Positions and drift are trustworthy at the level the page claims (tens of km, a few hundredths of a degree a day).
- The close-pair list needs a label for what each object is. Next step: a curated, cited list of inspection-capable and
  servicing satellites (Olymp-K, GSSAP, Shijian and Shiyan experimental satellites, MEV), shown beside each pair, so slot-sharing
  communications satellites stop looking like inspections.
- Validation comes once there is history: score manoeuvre detection against announced relocations, and close approaches
  against published rendezvous, with the cases fixed in advance.
