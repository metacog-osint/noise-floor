# Official GNSS interference notices: what can feed the events grader (26 Oct 2026)

**Why.** Events v1.0 (`docs/assessment/events.md`) sets `deliberate_suspected` (rule D1) only when an official notice
reports GNSS jamming or spoofing over an event. Notices that report interference without saying jamming or spoofing
count as corroboration (rule S2) only. The plan was to start with NGA's broadcast warnings and add NOTAMs later. This
note records what was checked on 26 Oct 2026, what went into the curated notices file, and what is left open.

## Bottom line

- **NGA's broadcast-warning API is frozen.** It has served the same 386 in-force warnings since at least 22 Oct 2026,
  the newest issued 10 May 2024, and its own `broadcast-warn/latest-warning` endpoint returns 2024-05-10T15:42Z. The
  only GNSS notice among them is a standing 2021 "GPS unreliable in vicinity Malta". It can't feed D1.
- **The official Baltic notices say "interference", not "jamming".** The Swedish-coordinated Baltic warning, the joint
  Estonia–Finland warning and the Finnish Notices to Mariners all describe GNSS interference or disruption and name no
  cause. Under the frozen rules they corroborate Baltic events but never set `deliberate_suspected`.
- **Two notices are now in the curated file** (`data/declared/notices.json`, private): BALTIC SEA NAV WARN 030/26 and
  the joint Estonia–Finland warning of 17 Jun 2025. Neither gives coordinates, so their positions are approximate
  circles along the named sea areas, flagged as drawn by us.
- **EASA's weekly table of affected FIRs is the one official source found that marks spoofing by area.** Whether a
  weekly FIR-wide spoofing mark should set `deliberate_suspected` is a decision for Tom, and it needs FIR boundaries
  from a licence-clean source. Recorded as a candidate (`easa-gnss-firs`, use `later`).

## Sources checked

| Source | What it gives | Wording | Placed by | Format | Fit |
|---|---|---|---|---|---|
| NGA MSI broadcast warnings | NAVAREA IV/XII, HYDROLANT/HYDROPAC/HYDROARC in force | (1 GNSS notice: "GPS unreliable", Malta, 2021) | coordinates | JSON API | Frozen at 10 May 2024; can't feed D1. The watch collector now reports it as an error |
| BALTICO navigational warnings (Swedish Maritime Administration) | Baltic warnings in force. BALTIC SEA NAV WARN 030/26, issued 12 Oct 2026 09:12 UTC, covers the southern, south-eastern, central and northern Baltic, the Gulfs of Finland and Riga and the Sea of Åland | "GNSS, AIS, RADAR AND DGPS INTERFERENCE OBSERVED IN AREA" | named sea areas | HTML, in force only | In the file (S2) |
| Joint Estonia–Finland navigation warning, 17 Jun 2025 | Gulf of Finland, both countries' territorial waters and EEZs; a danger zone in ENCs | "GNSS interference", "disruptions" | named waters (ENC zone not public) | news item | In the file (S2) |
| Finnish Notices to Mariners (Traficom) | *165/2026 (10 Jun 2026), *182/2026 (30 Jun 2026): GNSS and AIS interference in the Gulf of Finland, begun spring 2024, continuing | "interference" | named waters | PDF | Cited as evidence the joint warning still applies |
| Swedish Notices to Mariners (UFS 1131/2026) | A GNSS disturbance notice, not tied to an area, until further notice | "disturbance" | none | PDF | Can't be placed |
| EASA SIB 2022-02R4 (3 Jul 2026) and FIR tables | FIRs with interference reports in the last 7 and 30 days, with a spoofing column. 7-day table of 14 Oct 2026: spoofing marked for Ankara, Sofia, Yangon, Nicosia, Istanbul, Lahore, Cairo, Bangkok, Delhi, Damascus, Amman; reports without a spoofing mark for Bucharest, Warsaw, Tallinn, Vilnius, Tbilisi, Helsinki, Riga, Asmara, Kabul | defines jamming as intentional; spoofing column | FIR names | HTML tables, current only | Candidate for D1: Tom's decision |
| Traficom satellite-navigation interference statistics | Aggregated official picture of interference in Finland (page updated 8 May 2026) | — | Finland | web page | An observation source, not a notice: worth a look for a later corroboration lane |
| FAA NOTAM API, EUROCONTROL EAD | NOTAMs | varies; US GPS NOTAMs are mostly announced tests, already covered by FAA SPANS | coordinates | API or web, account needed | Later; needs an account Tom would hold |

## How the two notices were entered

- **BALTIC SEA NAV WARN 030/26:** in force from 12 Oct 2026 09:12 UTC (still listed on 26 Oct). Fourteen points along
  the named sub-areas with 70 km circles, kept mostly at sea (`"shape": "points"`), so aircraft effects far inland
  aren't counted as covered. Earlier warnings on the same subject aren't recorded, because the page lists only
  warnings in force.
- **Joint Estonia–Finland warning:** from 17 Jun 2025 11:02 UTC, no end date. Five points along the Finnish and
  Estonian waters of the Gulf of Finland, west of the Russian EEZ, with 50 km circles. It is assumed still in force on
  the strength of Finnish NtM *182/2026.

Both are class `interference`. Their effect on the register is in the method document's v1.0 results.

## Open

1. **EASA spoofing marks as a D1 driver** (Tom's decision). If yes: archive the weekly table from now on (it isn't
   archived anywhere we found), read EASA's copyright notice, and find FIR boundaries under a licence that allows
   reuse.
2. **NOTAMs** (later): the FAA NOTAM API needs a free key; GNSS NOTAMs outside the US could come through EUROCONTROL
   with an account. Both would need their terms read first.
3. **Baltic warning history:** BALTICO lists only warnings in force. Capturing the page daily would build a history,
   in the same way as the ESA archive.

Sources: [NGA MSI](https://msi.nga.mil/NavWarnings), [Swedish navigational warnings in force](https://navvarn.sjofartsverket.se/en/Navigationsvarningar/),
[Transpordiamet, 17 Jun 2025](https://transpordiamet.ee/en/news/eesti-ja-soome-hoiatavad-laevu-soome-lahes-sagenenud-gnss-hairete-eest),
[Traficom NtM 18/2026](https://traficom.fi/files/media/file/TM_2026_18_EN.pdf), [EASA GNSS outages and alterations](https://www.easa.europa.eu/en/domains/air-operations/global-navigation-satellite-system-outages-and-alterations),
[Traficom interference statistics](https://tieto.traficom.fi/en/statistics/satellite-navigation-service-interferences-finland).
