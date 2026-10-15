# EMSO tracker (working name)

This is an open-source picture of where the electromagnetic spectrum is being contested and what that does to positioning, navigation and timing (PNT) and to satellite communications. It is built only from sources whose licences allow it, and every source is recorded in a licence registry before it is used. The project belongs to The Intelligence Company.

**Status (Oct 2026):**

- **Phase 1 is built and validated:** the PNT processor and its analysis, tested on 20 days. Key findings:
  - It finds the known Baltic, Black Sea and Caucasus hotspots.
  - It reconstructs the 13–17 Oct 2025 EGNOS outage from aircraft data alone, to within an hour.
  - It separates geomagnetic storms (10 m accuracy loss) from jamming-scale loss.
  - It recovers both bursts of the 22 Sep 2026 Bay Area GPS loss.
  - It tags aircraft whose avionics stay latched after crossing a jammed area.
- **It doesn't run daily yet.** That is Phase 2.

## What it measures

From each aircraft's own ADS-B position-quality reports, it computes the share of aircraft in each H3 hex whose GNSS accuracy was degraded, per day, hour and minute, at two thresholds:

- **93 m (NACp < 8):** jamming-scale loss
- **10 m (NACp < 10):** only for aircraft that showed 10 m capability that day; storms and SBAS outages show here

It is an **effect** measure, not attribution. Read [`docs/method-card.md`](docs/method-card.md) for what it can and can't tell you.

## Layout

| Path | What |
|---|---|
| `pipeline/pnt_daily.py` | One adsb.lol day to per-hex daily, hourly and per-minute degradation (about 1 to 1.5 min per worldwide day) |
| `pipeline/pnt_analysis.py` | SBAS service flag, same-hour baselines and anomaly events, minute-burst events |
| `pipeline/run_days.py` | Process date ranges, skipping days already done |
| `collectors/` | Community collectors (Bluesky, RSS/Atom). The account and feed lists are private and not in this repo. |
| `registry/sources.csv` | Licence registry: every source, its licence, and what it may be used for. Checked by `tools/check_registry.py`. |
| `docs/` | Design, method card and validation reports with figures |
| `tools/` | Validation scripts and repository checks |
| `tests/` | Offline tests (synthetic data, no network) |

## Data and licences

| Source | Licence | How it is used |
|---|---|---|
| ADS-B traces | [adsb.lol](https://www.adsb.lol/) globe_history, ODbL 1.0 | Ingested. Derived hex data is published under ODbL, with attribution on every map. |
| Kp index | GFZ Potsdam, CC BY 4.0 | Ingested |
| Basemaps | Natural Earth, public domain | Ingested |
| GPSJam, Stanford RFI, OpenSky, Cloudflare Radar and other sources not licensed for commercial use | — | Visual comparison only. Never ingested. |

## Run locally

```bash
pip install -r requirements.txt            # h3, orjson, pyarrow (add requirements-dev.txt for figures)
python pipeline/pnt_daily.py 2025-10-16 --raw <folder with the day's adsb.lol tar or split parts>
python pipeline/pnt_analysis.py 2025-10-16
for t in tests/test_*.py; do python "$t"; done
```

## Not in this repository, by design

Watch configuration (areas of interest, keywords, followed accounts, alert history) and private notes stay out of the repo. A pre-commit hook and CI check block a private term list.

## Licence

**Code:** no licence has been chosen yet, so all rights are reserved for now. **Data outputs:** ODbL 1.0, as derived from adsb.lol.
