#!/usr/bin/env python3
"""Download the site's files from this repo's pnt-data-* and declared-data releases, fetching only what changed.

  python3 tools/fetch_release_files.py DIR     # uses GH_TOKEN or GITHUB_TOKEN for the asset listing

The asset listing goes through the REST API (a few calls per release). The files themselves come from their
plain download links, which don't count against the API rate limit. DIR/manifest.json remembers each file's
size and update time, so a cached DIR only gets new or changed files, and files no longer in any release are
removed. Standard library only (the deploy job runs it without installing anything).
"""
import concurrent.futures
import json
import os
import re
import sys
import time
import urllib.request

FILES = re.compile(r"^(\d{4}-\d{2}-\d{2}\.(map|anomalies|bursts|sbas|hotspots)\.json|faa_gps_tests\.json)$")
TAGS = ("pnt-data-", "declared-data")     # daily outputs; declared events (announced GPS tests)
NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')


def api_pages(url, token):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "noise-floor"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    while url:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
            data, link = json.load(r), r.headers.get("Link") or ""
        yield from data
        m = NEXT.search(link)
        url = m.group(1) if m else None


def fetch(url, dest, size):
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "noise-floor"})
            with urllib.request.urlopen(req, timeout=120) as r, open(dest + ".part", "wb") as f:
                f.write(r.read())
            if os.path.getsize(dest + ".part") != size:
                raise IOError(f"{os.path.basename(dest)}: size {os.path.getsize(dest + '.part')}, release says {size}")
            os.replace(dest + ".part", dest)
            return
        except Exception:
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    out = sys.argv[1]
    repo = os.environ.get("GITHUB_REPOSITORY", "metacog-osint/noise-floor")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    os.makedirs(out, exist_ok=True)
    mpath = os.path.join(out, "manifest.json")
    manifest = {}
    if os.path.exists(mpath):
        with open(mpath, encoding="utf-8") as f:
            manifest = json.load(f)
    want = {}
    for rel in api_pages(f"https://api.github.com/repos/{repo}/releases?per_page=100", token):
        if not rel["tag_name"].startswith(TAGS):
            continue
        for a in api_pages(f"https://api.github.com/repos/{repo}/releases/{rel['id']}/assets?per_page=100", token):
            if FILES.match(a["name"]):
                want[a["name"]] = [a["size"], a["updated_at"], a["browser_download_url"]]
    todo = [n for n, w in want.items() if manifest.get(n) != w[:2] or not os.path.exists(os.path.join(out, n))]
    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda n: fetch(want[n][2], os.path.join(out, n), want[n][0]), todo))
    gone = [n for n in manifest if n not in want]
    for n in gone:
        if os.path.exists(os.path.join(out, n)):
            os.remove(os.path.join(out, n))
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump({n: w[:2] for n, w in want.items()}, f)
    print(f"release files: {len(want)}; downloaded {len(todo)}; removed {len(gone)}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"changed={'true' if todo or gone else 'false'}\n")


if __name__ == "__main__":
    main()
