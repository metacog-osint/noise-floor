# Interference on every constellation and band: plan

Written 1 Nov 2026 (UTC) at Tom's request ("explore ways to identify and document observed interference of BeiDou,
GLONASS, QZSS, and the other GNSS freqs"). Step X1, the station tool for every signal, was built the same day
(`tools/station_bands.py`, results below); the first probe was run from scratch scripts before it. No watch areas appear here; area work stays in private config.

## Bottom line

- **Almost everything Noisefloor measures today is GPS L1.** The aircraft map, CYGNSS and the Sentinel L1 index all
  measure it, plus Galileo E1, which shares the same carrier. That says little about BeiDou, GLONASS, QZSS or the lower
  L-band (1164–1300 MHz).
- **Reference stations already record every signal they track.** One RINEX 3 file from an EPN or IGS station carries
  signal strength for GPS, GLONASS, Galileo, BeiDou and often QZSS, on two to five bands each. A drop seen on every
  satellite of one signal at once is the interference signature `tools/station_cn0.py` already uses for GPS L1. It
  extends to every signal.
- **Comparing bands shows what kind of interference it is.** The signals sit at known frequencies from 1176 to 1606 MHz,
  and GLONASS puts each satellite on its own channel. The drop on each signal, set against its frequency, sketches the
  interferer's spectrum. A narrowband L1 jammer, a multi-band jammer and broadband noise or equipment trouble each leave
  a different pattern.
- **A first probe worked** on the one local event the station test found (Vaiņode, Latvia, 17 May 2026).
  - Every band from 1176 to 1606 MHz fell together, on all four constellations: 1.3–3.2 dB-Hz by median.
  - A station 148 km away saw nothing on any signal it was tracking at the time.
  - That fits a broadband rise or equipment at the site, not a GPS L1 jammer.
- **From orbit (X3, 1 Nov):** on the Sentinel PODRIX receivers, Galileo E5a and GPS L2C pick out the regions where
  aircraft lose GPS better than L1 does (AUC 0.911 and 0.898), and drop 2.1–2.7 times as far as L1 on the same
  links. NISAR hears GPS and QZSS L2. COSMIC-2 may log GLONASS links (to probe).
- **QZSS can only be observed from East Asia and Oceania.** The IGS stations in Japan that were checked track it on
  L1, L1C, L1S, L2C and L5, but not BeiDou.

## The signals

Carrier frequencies from each system's interface control document. Signals on the same carrier share a jammer.

| Band | MHz | GPS | GLONASS | Galileo | BeiDou | QZSS | Others |
|---|---|---|---|---|---|---|---|
| Upper L | 1598.06–1605.38 | | G1 (FDMA, channel k = −7…+6: 1602 + 0.5625k) | | | | |
| | 1575.42 | L1 C/A, L1C | | E1 | B1C | L1 C/A, L1C, L1S | SBAS L1, NavIC L1 |
| | 1561.098 | | | | B1I | | |
| Lower L | 1278.75 | | | E6 | | L6 | |
| | 1268.52 | | | | B3I | | |
| | 1242.94–1248.63 | | G2 (FDMA: 1246 + 0.4375k) | | | | |
| | 1227.60 | L2 (P(Y), L2C) | | | | L2C | |
| | 1207.14 | | | E5b | B2b (and B2I) | | |
| | 1202.025 | | G3 (CDMA) | | | | |
| | 1191.795 | | | E5 (AltBOC, whole band) | | | |
| | 1176.45 | L5 | | E5a | B2a | L5 | SBAS L5, NavIC L5 |
| S | 2492.028 | | | | | | NavIC S |

What this means for detection:
- **A jammer on 1575.42 MHz hits GPS, Galileo, BeiDou (B1C) and QZSS at once.** BeiDou B1I sits 14 MHz below it, and
  GLONASS G1 23–30 MHz above. Whether those also drop tells how wide the jammer is.
- **The lower L-band holds the second civil frequency of every system.** The aircraft map can't see it. Military
  receivers and dual-frequency avionics depend on it.
- **Modulation matters on a shared carrier.** A narrowband jammer at the centre degrades BPSK signals (GPS C/A, BeiDou
  B1I) more than split-spectrum BOC signals (Galileo E1, GPS L1C, BeiDou B1C), whose power sits away from the centre
  (Betz 2001). Comparing C/A with E1 on the same receiver is a check on jammer bandwidth. Not yet tested here.

## What each sensor can hear

| Sensor | Constellations and bands | Where | Status |
|---|---|---|---|
| **Aircraft (ADS-B NIC/NACp)** | Position quality only. The message doesn't say which constellations the receiver used | Wherever aircraft fly | In use |
| **EPN and IGS reference stations** (RINEX 3, 30 s) | Whatever each receiver tracks. Checked: Vaiņode G/R/E/C on 19 signals; Riga adds QZSS, GLONASS G3 and SBAS (25 signals); two Japanese stations track G/R/E/J (QZSS on five signals) but not BeiDou | Fixed sites, line of sight only (`docs/validation/ground-stations.md` section 6) | GPS L1/L2/L5 and Galileo E1/E5a built; the rest is step X1 |
| **Sentinel-1C, 1D, 2C** (PODRIX) | GPS L1 C/A, L2 P(Y), L2C; Galileo E1, E5a | Near-global, regional footprint about 2,000 km | L1, E1 and L2 P(Y) built (step E of `docs/space-sensors-plan.md`); E5a and L2C checked in X3 (`docs/validation/sentinel-gnss-x3.md`) |
| **Sentinel-2B, 3A, 3B** (RUAG) | GPS L1, L2 P(Y) | Near-global | Built |
| **CYGNSS** | GPS L1 | ±38° latitude | In use |
| **NISAR** | 1219–1239 MHz (GPS and QZSS L2) and 1291–1296 MHz (the top of the Galileo E6 band) | Passes in a mode that hears the signal | In use (`nisar/README.md`) |
| **COSMIC-2** | GPS L1/L2; its receivers are reported to track GLONASS too (**unverified** for the files we read) | ±24° receiver latitude | Step C of the space-sensors plan; GLONASS links: step X5 |
| **HydroGNSS** | Reflected GPS/Galileo L1/E1 and L5/E5a | Near-polar | Waits on Tom's registration |
| **FY-3 GNOS** (Chinese weather satellites) | GPS and BeiDou occultation | Near-polar | Access through China's National Satellite Meteorological Centre; registration and terms **not checked** (step X5) |

## Telling interference from everything else

A signal can drop for reasons other than interference. Each check below uses the multi-signal data to rule one out.

1. **Common to every satellite on a signal.** One satellite fading is multipath, an obstruction or that satellite. Every
   satellite on a band at once (F ≥ 0.75 in the station rule) is the receiver's noise floor rising.
2. **The band pattern.**
   - Upper L only, or 1575.42 only: an L1 jammer. Many cheap jammers are L1 only.
   - Every band equally: broadband noise near the antenna, or equipment (antenna, cable, power).
   - Lower L more than upper L: a lower-band emitter, or ionospheric scintillation (next item).
3. **Ionospheric scintillation.** It weakens lower frequencies more (weak-scatter S4 scales about as f^−1.5; Yeh and Liu
   1982). It also hits many stations across hundreds of km and follows space weather. A lower-band-heavy drop seen at
   one station only, with neighbours quiet and Kp low, isn't scintillation.
4. **One constellation down on a shared carrier.** Interference can't pick GPS over Galileo at 1575.42 MHz, apart from
   the BPSK/BOC difference above. If only one system drops, the cause is that system: an outage, a health change or
   spoofing of that system alone. Broadcast health flags (in the navigation files we already fetch) and the operators'
   notices rule outages out:
   - GPS NANU (NAVCEN; refuses automated clients, so read by hand or through page watch);
   - Galileo NAGU (European GNSS Service Centre);
   - GLONASS notices (Information and Analysis Center, Roscosmos);
   - BeiDou notices (China Satellite Navigation Office);
   - QZSS NAQU (Cabinet Office, Japan).
5. **Equipment.** A whole-band drop at one station with nothing at its neighbours is most often equipment. The station
   log (EPN and IGS site logs list receiver, antenna and firmware changes) and a recurrence on the clock point to
   equipment.

**Baselines by constellation.** Each needs its own repeat, because the same sky position recurs at different intervals:
- GPS: about 247 s earlier each day (Agnew and Larson 2007; built).
- GLONASS: every 8 sidereal days.
- Galileo: every 10 sidereal days.
- BeiDou MEO: every 7 sidereal days.
- BeiDou GEO and IGSO, and QZSS: every sidereal day. A geostationary satellite never moves in the sky, so it gives the
  cleanest drop detector: a constant elevation and a daily baseline. This works only where those satellites are
  visible: roughly Asia and Oceania for QZSS, and Asia, Oceania and the Indian Ocean rim for BeiDou GEO/IGSO.

Where too few repeats are held, a pooled elevation-bin baseline (as built for Galileo) is the fallback.

## First probe: Vaiņode, 16–17 May 2026 (exploratory, 1 Nov 2026)

Scratch scripts read the held EPN files. For each signal, each satellite's C/N0 minus its own running median over
±30 min; then the median across satellites per epoch. This is not the built station method: there is no quiet-day
baseline.

**17 May, 00:09–00:18 UTC** (the short event in `docs/validation/ground-stations.md` section 5.3). Median drop in the
window, dB-Hz:

| MHz | Signal | Vaiņode | Riga (148 km) |
|---|---|---|---|
| 1176.45 | GPS L5 / Galileo E5a / BeiDou B2a | −1.9 / −2.2 / −2.2 | quiet |
| 1191.795 | Galileo E5 | −2.3 | quiet |
| 1207.14 | Galileo E5b / BeiDou B2b | −2.7 / −2.4 | quiet |
| 1227.60 | GPS L2C / L2 P(Y) | −2.4 / −2.2 | quiet |
| 1244.7–1248.6 | GLONASS G2, six satellites | −1.7 to −1.9 (one at 0.0) | quiet |
| 1268.52 | BeiDou B3I | −1.3 | quiet |
| 1278.75 | Galileo E6 | −1.6 | quiet |
| 1561.098 | BeiDou B1I | −2.5 | quiet |
| 1575.42 | GPS C/A / Galileo E1 / BeiDou B1C | −2.2 / −3.2 / −2.9 | quiet |
| 1598.1–1605.4 | GLONASS G1, eight satellites | −1.2 to −3.8 | quiet |

"Quiet" means Riga's lowest 5-minute value in 00:00–00:30 was 0.0 to −0.5 dB-Hz on every signal with data. Its 1st
percentile over the rest of the day is −0.2 to −0.8 on most signals; signals with only 2–3 satellites (GPS L1C,
GLONASS G3) reach −2.1 to −5.0.

What the probe shows:
- **Every constellation and every band fell together**, with the 1268–1279 MHz pair (B3I, E6) least. That is broadband
  across 1176–1606 MHz or equipment, not an L1 jammer. Station 148 km away quiet on all signals: local.
- **Galileo E1 and BeiDou B1C fell more than GPS C/A** on the same carrier. A narrowband jammer at the centre would do
  the opposite (Betz 2001). This also points to broadband noise.
- **Single GLONASS satellites scatter by ±1 dB-Hz,** so the channel ladder needs several minutes and several satellites
  per channel before it can resolve a spectrum.
- **The ±30-minute running median erases slow events.** The 16 May evening fall (hours long) reads near 0 dB-Hz in the
  same method, against 1–6.5 dB-Hz with the built station baselines. Step X1 must use quiet-day baselines.

Kp at the time was 1.7 (17 May, 00–03 UTC; 3.3–3.7 on the evening of 16 May; GFZ Potsdam, CC BY 4.0).

## X1 results: Vaiņode and Riga, 16–17 May 2026 (1 Nov 2026)

`tools/station_bands.py day` with five quiet baseline days per station (Vaiņode: 27 and 28 Apr, 1 and 4 May, 2 Jun;
Riga: 1, 4, 27, 29 and 30 May). **A development case, not a test:** the event was known before the tool was written.

**Agreement with the validated GPS and Galileo tool** (`station_cn0.py`, `docs/validation/ground-stations.md`):
- 17 May: GPS L1 C/A flagged 00:09–00:18Z (10 minutes), lowest −4.92 dB-Hz; GPS L5 flagged 103 minutes that day.
  Both as before.
- 16 May evening: lowest 5-minute values GPS L5 −5.65, Galileo E5a −6.52, GPS L2 P(Y) −2.7 dB-Hz, against 5.6, 6.5
  and 2.7 before.

**Median drop per signal**, dB-Hz (quiet-day baselines; for 16 May, the lowest 5-minute value from 20:00Z):

| MHz | Signal | Vaiņode 17 May 00:09–00:18 | Vaiņode 17 May 18:55–21:50 | Vaiņode 16 May evening (lowest) | Riga 17 May, both windows |
|---|---|---|---|---|---|
| 1176.45 | GPS L5 / Galileo E5a / BeiDou B2a | −5.5 / −5.4 / −5.2 | −3.0 / −2.8 / −2.8 | −5.7 / −6.5 / −6.8 | +0.3 to −0.1 |
| 1191.795 | Galileo E5 | −5.7 | −3.0 | −6.9 | +0.2 to +0.1 |
| 1207.14 | Galileo E5b / BeiDou B2b | −5.9 / −5.6 | −2.7 / −2.7 | −7.3 / −7.0 | +0.2 to 0.0 |
| 1227.60 | GPS L2C / L2 P(Y) | −6.3 / −5.1 | −2.9 / −1.3 | −5.6 / −2.7 | 0.0 to −0.1 |
| 1242.9–1248.6 | GLONASS G2 | −5.1 | −2.5 | −5.9 | +0.3 to 0.0 |
| 1268.52 | BeiDou B3I | −3.6 | −1.3 | −4.8 | +0.3 to −0.2 |
| 1278.75 | Galileo E6 | −4.2 | −1.8 | −4.8 | +0.1 to −0.1 |
| 1561.098 | BeiDou B1I | −4.0 | −0.5 | −2.2 | +0.3 to +0.2 |
| 1575.42 | GPS L1 C/A / Galileo E1 / BeiDou B1C | −4.7 / −4.9 / −4.7 | −1.0 / −0.9 / −0.6 | −2.0 / −2.7 / −2.4 | +0.2 to −0.1 |
| 1598.1–1605.4 | GLONASS G1 | −4.2 | −1.1 | −2.3 | 0.0 |

Riga's GPS signals were unscored at 00:09–00:18: three of its baseline days fall after the test day, and at the start of
a day their sidereal match lands on the day before (the day-edge limit in `docs/validation/ground-stations.md`
section 6).

What X1 adds to the GPS and Galileo tool:
- **Two patterns at one site.** At 00:09–00:18 on 17 May every system and band fell 3.6–6.3 dB-Hz. On both evenings
  the lower L-band (1176–1249 MHz) fell at least twice as far as the upper L-band (1559–1606 MHz), with the
  1268–1279 MHz pair in between.
- **Every GLONASS channel fell together** at 00:09–00:18 on 17 May: 3.3–4.8 dB-Hz on the eight G1 satellites and
  4.2–5.5 on the six G2 satellites, so whatever caused it covered both FDMA bands. On the evenings the channels spread
  more (G2 −1.3 to −3.6 on 17 May), but none stood out.
- **Riga, 148 km away, was quiet on every signal** in the same windows.
- Effects only: a lower-band emitter near the antenna, or the station's own antenna or receiver, would both fit. The
  station log and a recurrence check (ground-stations section 7, step 4) come next.

**Orbit checks (1 Nov):**
- BeiDou C01 and C03 come out at 140.0°E and 110.6°E, their GEO slots; QZS-3 (J07) at 127.1°E.
- GLONASS state vectors integrated 30 minutes forward match the next broadcast record to 2.2 m (median; R01, R09, R18).
- On 17 May no satellite of any system was tracked at Vaiņode while computed below the horizon.

## Build steps

Each step writes its checks into `docs/validation/` before results are read, as the other lanes do.

| # | Step |
|---|---|
| X1 | **Built 1 Nov:** `tools/station_bands.py` (`signals`, `day`; tests in `tests/test_station_bands.py`), beside `station_cn0.py`, whose rule and Baltic test are unchanged. It scores every signal-strength code in a RINEX 3/4 file with the same rule (D, F, 5-minute flags). Orbits: Keplerian for GPS, Galileo, QZSS and BeiDou (BDT and the BeiDou GEO rotation), RK4 integration of the GLONASS state vectors. Baselines per satellite: the sidereal sky match for GPS (246 s a day) and for QZSS and BeiDou GEO/IGSO (one sidereal day); own elevation-bin medians for GLONASS, Galileo and BeiDou MEO. Losses count only where the baseline days tracked that part of the sky. Unhealthy satellites are dropped (QZSS health is recorded only). Outputs per station-day: every signal's flags, and for each window and event a band signature and GLONASS channel ladder (`data/stations/<STATION>/<day>.bands.json`, `.png`). `station_cn0.fetch` now uses held files first and falls back to NASA CDDIS for IGS stations when BKG is unreachable. Results above |
| X2 | **A positive control with known frequencies and times.** Jammertest (Andøya, Norway) publishes its test plan with frequencies and times; a station inside its range would give a known-answer test across bands. Norway's national network terms are not checked (`docs/validation/ground-stations.md` section 7). Announced US tests near NOAA CORS stations are the open-data alternative (mostly L1) |
| X3 | **Done 1 Nov** (`docs/validation/sentinel-gnss-x3.md`; `tools/sentinel_bands.py`, tests in `tests/test_sentinel_bands.py`). Pre-registered at 14:06 UTC, run at 14:48 UTC on the 63 E3 days, PODRIX units. **Both checks hold:** Galileo E5a AUC 0.911, GPS L2C 0.898, against 0.863–0.872 on L1 and E1. **On the same links the lower bands drop 2.1–2.7 times as far as L1** (pooled −8.7 against −3.2 dB; Baltic −10.6 against −5.0 dB): *wideband* by the fixed readings, and steady across units and windows. Whether the emitters or the antennas favour the lower band is not separated. **The 60–160°E dip is a quarter as deep on L2C**, the only band no BeiDou signal shares. **After the fact (section 2.6):** over East Asia L2C and E5a slid 1.2–2.2 dB or more between Oct 2025 and Oct 2026 while other regions held; cause not established. `tools/sentinel_trend.py --signal l2c` builds box trends on L2C |
| X4 | **Exclusion feeds.** Broadcast health from the daily navigation files; the operators' notice pages (list above) through the page-watch collector, each with a registry row |
| X5 | **Probes.** Whether COSMIC-2 `podTc2` files include GLONASS links; whether FY-3 GNOS BeiDou data can be had without a paid or restricted account |
| X6 | **Stations that see QZSS and BeiDou GEO.** IGS daily files at NASA CDDIS on 27 Oct 2026 came from 451 stations, including 11 in Japan, 4 in South Korea, 4 in Taiwan, 2 in Hong Kong, 3 in the Philippines, 1 in Guam, 1 in Mongolia, 2 in China and 6 in Russia (BADG, KZN2, NVSK, SVTL, URAL, ZECK). National networks (Japan's GEONET, Geoscience Australia) add density; their terms are **not checked** |

## Limits

- **Line of sight.** A station hears a ground emitter only within tens of km, unless the emitter is high or airborne
  (`docs/validation/ground-stations.md` section 6). Stations near borders and coasts matter most.
- **Receivers differ.** Each station logs its own set of signals, and C/N0 estimators differ by make and signal. On
  16 May, Vaiņode's semi-codeless L2 P(Y) moved less than its L2C. Compare a signal with its own history at the same
  station, not across stations.
- **QZSS and BeiDou GEO/IGSO are regional.** European stations see QZSS rarely, if at all.
- **No attribution.** The band pattern describes the effect. It doesn't identify a source. Each detection is a lead.

## Decisions for Tom

| # | Decision | Recommendation |
|---|---|---|
| D1 | Build X1 now | **Decided 1 Nov (Tom: "Yes, build X1").** Built the same day |
| D2 | X3 (Sentinel E5a and L2C) | **Decided 1 Nov (Tom: "Yes, run X3").** Run the same day; both checks hold |
| D3 | National networks (GEONET, Geoscience Australia, Norway) | Read terms first; register only where they allow republishing derived results |
| D4 | Anything public | Later. A band-signature table per event, beside the existing station results, once X2 passes |

## Sources

- IS-GPS-200, IS-GPS-705, IS-GPS-800 (GPS L1 C/A and L2, L5, L1C): https://www.gps.gov/technical/icwg/
- GLONASS Interface Control Document, edition 5.1 (2008), Russian Institute of Space Device Engineering.
- Galileo Open Service Signal-in-Space ICD, European GNSS Service Centre: https://www.gsc-europa.eu/electronic-library/programme-reference-documents
- BeiDou ICDs (B1I, B3I, B1C, B2a, B2b), China Satellite Navigation Office: http://en.beidou.gov.cn/SYSTEMS/ICD/
- IS-QZSS-PNT and IS-QZSS-L6, Cabinet Office, Japan: https://qzss.go.jp/en/technical/ps-is-qzss/ps-is-qzss.html
- NavIC SPS ICD, ISRO: https://www.isro.gov.in/
- Betz, J. W. (2001). "Binary Offset Carrier Modulations for Radionavigation." *NAVIGATION* 48(4), 227–246.
- Yeh, K. C. and Liu, C. H. (1982). "Radio wave scintillations in the ionosphere." *Proc. IEEE* 70(4), 324–360.
- Agnew, D. C. and Larson, K. M. (2007). "Finding the repeat times of the GPS constellation." *GPS Solutions* 11, 71–76.
- IGS daily observation files: NASA CDDIS, https://cddis.nasa.gov/archive/gnss/data/daily/ (Earthdata login); EPN and IGS via BKG, https://igs.bkg.bund.de (CC BY 4.0 unless stated).
- Kp: GFZ Potsdam, https://kp.gfz.de (CC BY 4.0).
