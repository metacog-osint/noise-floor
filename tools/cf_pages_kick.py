#!/usr/bin/env python3
"""Push a stuck Cloudflare Pages Git build through by retrying the newest queued deployment.

Since 15 Oct 2026 the site project's Git builds sit in "queued" and never start, while a retry of
the queued deployment deploys at once. Run this after pushing site changes until the cause is fixed.

  python tools/cf_pages_kick.py [project]        # default project: noise-floor

Needs CLOUDFLARE_API_TOKEN (Pages Edit) in the environment, or in the Windows user environment.
The token is never printed.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "https://api.cloudflare.com/client/v4"


def token():
    tok = os.environ.get("CLOUDFLARE_API_TOKEN")
    if not tok and os.name == "nt":
        tok = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "[Environment]::GetEnvironmentVariable('CLOUDFLARE_API_TOKEN','User')"],
                             capture_output=True, text=True).stdout.strip()
    if not tok:
        sys.exit("CLOUDFLARE_API_TOKEN is not set")
    return tok


def call(tok, method, path):
    req = urllib.request.Request(API + path, method=method, data=b"{}" if method == "POST" else None,
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.load(e)


def main():
    proj = sys.argv[1] if len(sys.argv) > 1 else "noise-floor"
    tok = token()
    aid = call(tok, "GET", "/accounts")["result"][0]["id"]
    newest = call(tok, "GET", f"/accounts/{aid}/pages/projects/{proj}/deployments?per_page=1")["result"][0]
    stage = newest.get("latest_stage") or {}
    commit = ((newest.get("deployment_trigger") or {}).get("metadata") or {}).get("commit_hash", "")[:7]
    if stage.get("name") == "deploy" and stage.get("status") == "success":
        print(f"{proj}: newest deployment ({commit}) is already live")
        return
    r = call(tok, "POST", f"/accounts/{aid}/pages/projects/{proj}/deployments/{newest['id']}/retry")
    if not r.get("success"):
        sys.exit(f"retry failed: {r.get('errors')}")
    new_id = r["result"]["id"]
    print(f"{proj}: retrying {commit} as {new_id[:8]}")
    for _ in range(30):
        time.sleep(10)
        st = (call(tok, "GET", f"/accounts/{aid}/pages/projects/{proj}/deployments/{new_id}")["result"].get("latest_stage") or {})
        print(f"  {st.get('name')} {st.get('status')}")
        if st.get("status") == "failure":
            sys.exit(1)
        if st.get("name") == "deploy" and st.get("status") == "success":
            return
    sys.exit("still not deployed after 5 minutes")


if __name__ == "__main__":
    main()
