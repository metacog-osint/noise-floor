# Noisefloor method (doctrine summary)

The full method is in `docs/` (DESIGN.md, the validation write-ups and the plain-language guide). This page states it in
the terms of The Intelligence Company's doctrine kit (`doctrine/kit/`).

## What it measures
The share of aircraft in each H3 cell whose ADS-B reports show position error worse than 93 m (severe GPS error), from
the adsb.lol daily archive (ODbL). Supporting measures: aircraft heard by multilateration but sending no position,
ADS-B spoofing episodes, the CYGNSS reflectometry noise floor, Sentinel-1 interference flags, and declared notices.

## Baselines
Each region and named area is compared with its own previous 30 days (rolling). The validated reference days in
`docs/validation/` are the fixed reference. JP 2-01.3 warns that a steady adversary signal can come to look normal, so
long-running regions are counted and shown separately rather than absorbed into the baseline.

## Anomaly versus warning
Everything Noisefloor publishes today is a measurement (kind observation; tier routine or anomaly). A region that newly
reaches jamming scale is an anomaly. Warnings, which are judged and carry likelihood and confidence, come only through
the warning problems in `indicators.json`, once their rules are scored.

## Independent lines of evidence
For confidence, each sensing method is one line: aircraft position quality, aircraft heard without a position, spoofing
detection, satellite reflectometry, satellite radar interference flags, and declared notices. Two reports through the
same method count once.

## Gaps and no data
adsb.lol has known gaps (no archive for 31 Dec 2025 or 6 May 2026; 7 May covers about 6 hours). A missing day or source
turns its layer grey ("no data"), never quiet. A fall in the severe share is read with position loss beside it, because
jammed aircraft can stop reporting position (assumption NF-AS-3, strained).

## Human review
None for daily items (fully automated, rule-based); sampled for the validation sets.

## Feed
`site/data/feed.geojson` (contract `tic-feed/2`), built at deploy by `tools/feed_v2.py` from the status board.

## Change log
- 2026-10-30: doctrine kit 0.1.0 adopted; contract v2 feed added.
