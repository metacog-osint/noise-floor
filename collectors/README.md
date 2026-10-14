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
