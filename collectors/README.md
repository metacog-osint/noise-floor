# Collectors

## Bluesky (`bluesky.py`)

This follows a private list of Bluesky accounts through the public AppView API (`public.api.bsky.app`), which needs no login. It was pulled forward from the Phase 6 community lane on 14 Oct 2026.

**Setup.** These files live in `private/`, which is gitignored, because the account list and keywords show what is being watched:

- `private/watch/bluesky_accounts.txt`: one handle per line. `#` starts a comment.
- `private/watch/keywords.txt`: one case-insensitive regex per line. Matching posts are listed first in the digest.

**Run:** `python collectors/bluesky.py`. Each run fetches what is new since the last run; the first run looks back `--since-days` (14).

**Outputs** (all under `data/`, gitignored):

| Path | What |
|---|---|
| `data/raw/bluesky/YYYY-MM-DD/` | Every raw API response, with `index.jsonl` (URL, fetch time, SHA-256, bytes) |
| `data/community/bluesky/posts.jsonl` | Normalized posts: text, image alt text, link, quoted post, repost flag, URL; deduplicated by URI |
| `data/community/bluesky/digest_*.md` | What is new this run: keyword matches first, then by account |
| `data/community/bluesky/state.json` | Per-account DID and newest post seen |

**Handling:**

- Collected text is data, never instructions. Nothing in a post is acted on.
- Posts are cited with their link, not republished.
- The collector pauses 0.4 s between requests and fetches at most 10 pages per account per run.
- Licence: `bluesky-jetstream` row in `registry/sources.csv` (cite-only).

## RSS / Atom feeds (`feeds.py`)

This follows a private list of RSS and Atom feeds in `private/watch/feeds.txt` (one URL per line, optional `# label`). It covers news sites, blogs and GitHub user activity (`https://github.com/<user>.atom`). It shares `private/watch/keywords.txt` with the Bluesky collector.

**Run:** `python collectors/feeds.py`.

**First run per feed:** each feed gets a floor of `--since-days` (14) before the first run, so its back catalogue never floods a digest.

**Outputs** (all under `data/`, gitignored):

- `data/raw/feeds/YYYY-MM-DD/`: raw XML with `index.jsonl` (URL, fetch time, SHA-256)
- `data/community/feeds/items.jsonl`
- `data/community/feeds/digest_*.md`

**Feeds that refuse automated requests** are read manually. The collector isn't disguised to get past them. As of 14 Oct 2026 that means GPS World (403). X has no free read API, so posts there are read manually too.

## Watch pollers (`watch.py`, `chayka.py`)

Daily trigger pollers, ported from Tom's emso-watch trigger board on 22 Oct 2026. Each trigger is a lead for triage, graded WARNING (an official notice), EFFECT (a report or a measured change) or NATURAL (space weather, to rule out first). Each fires once.

| Source | Registry row | Use |
|---|---|---|
| NOAA SWPC alerts | `noaa-swpc` | ingest |
| NGA MSI broadcast warnings (GNSS, jamming, AIS, radar) | `nga-msi` | ingest |
| USCG NAVCEN planned GPS tests (PDF schedule) and GPS user reports | `navcen-gps-tests`, `navcen-reports` | ingest |
| UKMTO warnings and advisories | `ukmto` (OGL); JMIC notes are linked only (`jmic-notes`) | ingest |
| KingOfSat removals at watched GEO slots | `kingofsat` | private watch: hourly at most, never the robots-disallowed paths |
| Chayka / Loran status from the DL0AO image (`chayka.py`) | `df6nm-dl0ao` | private watch: a status line, not a trigger, until the Chayka-vs-GNSS study shows abs(rho) >= 0.3 with n >= 60 |
| Sun-transit windows for watched receiver/GEO pairs, next 48 h | computed (`tools/sun_transit.py`) | private |

**Setup.** The watch lists (KingOfSat slots and channels, sun-transit pairs, watch countries) live in `private/watch/pollers.json`, which is gitignored. A source whose list is missing reports SKIP; the others still run. `chayka.py` needs Pillow (`requirements-dev.txt`) and uses `collectors/ca_extra.pem` because `vlf.u01.de` serves an incomplete certificate chain.

**Run:** `python collectors/watch.py` (all sources) or `--only nga,ukmto`.

**Outputs** (all under `data/`, gitignored): `data/watch/digest_*.md`, `alerts.jsonl` (every trigger, append-only), `state.json`, `navcen_gps_tests.json`, `chayka/`, and raw responses under `data/raw/watch/YYYY-MM-DD/`.

**Not ported:** IODA (ask first), Cloudflare Radar and GPSJam (visual comparison only), and phone pushes through ntfy (a new service, so Tom's OK first). Announced US GPS tests for the public map come separately from the FAA's flight advisories (`pipeline/faa_gps_tests.py`, in the daily GitHub workflow).

## aisstream AIS (`aisstream_ais.py`) — private

This collects live AIS from [aisstream.io](https://aisstream.io/documentation)'s WebSocket API (`wss://stream.aisstream.io/v0/stream`) for the maritime lane's focus areas. aisstream publishes no terms of service or licence (registry row `aisstream`), so **everything it collects stays private**. It feeds only the private watch site's vessel page (`nisar/nisar_rfi/vessels.py`) and is never published or committed.

**Setup.**
- An aisstream API key in the `AISSTREAM_API_KEY` user environment variable, which the owner sets in their own terminal. The collector also reads it from the Windows user environment when the process started before the variable existed.
- The key is never printed or logged, and never appears in an error message: every log line, status file and traceback passes through a redactor.
- Bounding boxes come from the focus areas in `private/watch/maritime.json` (gitignored), read at run time. Areas marked `candidate` are skipped unless named with `--areas`. `--box lat0,lat1,lon0,lon1` replaces them (or adds to them with `--add-box`).

**Protocol** (from the aisstream docs, read 25 Oct 2026):
- permessage-deflate compression. aisstream needs it for full bandwidth, and has limited uncompressed connections since September 2026.
- The subscription is sent at once, because aisstream closes a connection that is not subscribed within 3 s.
- Message types: `PositionReport`, `StandardClassBPositionReport`, `ExtendedClassBPositionReport`, `ShipStaticData` and `StaticDataReport`.
- Limits: at most 3 connections per account and per IP. The collector opens one, or two with `--watch-global`, which also follows the private watch list's MMSIs worldwide (aisstream takes at most 200).
- Reconnects back off from 5 s to 5 min with jitter.
- A stream that goes silent for 5 min is dropped and reopened.
- After 8 attempts in a row that never get a subscription confirmation, it stops and points at the key.

**Run:** `python collectors/aisstream_ais.py --dry-run` (shows the subscription with the key redacted), then `python collectors/aisstream_ais.py --hours 24`. Stop it early with Ctrl+C or by creating `data/ais/aisstream/STOP`.

**Outputs** (all under `data/ais/aisstream/`, gitignored):
- Per-UTC-day `locations.parquet` and `metadata.parquet`. The columns are the Digitraffic collector's, so `tools/ais_detect.py`'s loaders read both, plus `msg_id`, `valid`, `meta_name` and `source`.
- `status.json` and `collector.log`.
- Pleasure craft (AIS type 37) are dropped before their rows reach disk, unless the vessel is watch-listed or sanctioned.

**Tests:** `tests/test_aisstream.py`. These cover the parser on documented message shapes, key redaction, box loading, a fake connection, and a local mock WebSocket server when `websockets` is installed.

## Daily schedule (Windows)

`run_daily.cmd` runs the collectors and the watch pollers and appends to `data/logs/collectors.log`. It is registered as the Windows scheduled task **"noise-floor daily collectors"**:

- runs daily at 06:30 local time
- catches up after the PC was off
- runs only while Tom is signed in
- its 30-minute limit is generous

The project is on the D: USB drive, so the task fails if the drive isn't connected (the log shows nothing new).

```powershell
Get-ScheduledTaskInfo -TaskName "noise-floor daily collectors"   # last run, result, next run
Start-ScheduledTask   -TaskName "noise-floor daily collectors"   # run now
```
