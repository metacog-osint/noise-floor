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

## Daily schedule (Windows)

`run_daily.cmd` runs both collectors and appends to `data/logs/collectors.log`. It is registered as the Windows scheduled task **"noise-floor daily collectors"**:

- runs daily at 06:30 local time
- catches up after the PC was off
- runs only while Tom is signed in
- its 30-minute limit is generous

The project is on the D: USB drive, so the task fails if the drive isn't connected (the log shows nothing new).

```powershell
Get-ScheduledTaskInfo -TaskName "noise-floor daily collectors"   # last run, result, next run
Start-ScheduledTask   -TaskName "noise-floor daily collectors"   # run now
```
