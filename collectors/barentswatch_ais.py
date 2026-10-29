#!/usr/bin/env python3
"""barentswatch_ais.py: collect Norway's open AIS (BarentsWatch live AIS API, Kystverket data) into daily files.

Coverage: the Norwegian economic zone, the fishery protection zone at Svalbard and the protection zone at Jan Mayen,
so the Norwegian coast to Finnmark and the western Barents Sea. The open data leave out fishing vessels under 15 m
and leisure craft under 45 m (developer.barentswatch.no, read 28 Oct 2026).

Access: free, but needs a BarentsWatch user and an API client (MyPage -> API clients; state the purpose). Tom creates
it and stores the two values as user environment variables BARENTSWATCH_CLIENT_ID and BARENTSWATCH_CLIENT_SECRET;
they never pass through Claude. Token: POST https://id.barentswatch.no/connect/token (client_credentials, scope ais).
API: https://live.ais.barentswatch.no/live (OpenAPI at /live/openapi/ais/openapi.json).

Terms (barentswatch.no "API terms and conditions", read 28 Oct 2026): NLOD unless an API says otherwise; credit
"Data delivered by BarentsWatch" and the data owner (Kystverket); "You cannot change the data content"; contact them
before high-traffic use. So this collector stores the messages exactly as delivered, privately (data/ is gitignored),
and nothing derived from them is published until BarentsWatch confirms that derived aggregates are fine (registry
row barentswatch-ais).

Usage
  python collectors/barentswatch_ais.py --dry-run              # credentials found? (values never printed)
  python collectors/barentswatch_ais.py snapshot               # latest position + static data per ship (last 24 h)
  python collectors/barentswatch_ais.py stream --hours 23.75   # live stream (SSE), downsampled, hourly files
Outputs
  data/ais/barentswatch/<day>/latest_<HHMMSS>Z.json.gz   snapshots (the API's JSON array, unchanged)
  data/ais/barentswatch/<day>/stream_<HH>Z.jsonl.gz      one SSE data line per message, unchanged
  data/ais/barentswatch/status.json                      last run: counts, errors, token expiry
Stop a stream early by creating data/ais/barentswatch/STOP.
"""
import argparse
import gzip
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "ais", "barentswatch")
TOKEN_URL = "https://id.barentswatch.no/connect/token"
API = "https://live.ais.barentswatch.no/live"
UA = "noise-floor-ais"
ENV_ID, ENV_SECRET = "BARENTSWATCH_CLIENT_ID", "BARENTSWATCH_CLIENT_SECRET"


def credential(name):
    """From the process environment, else the user environment in the registry (set with setx or SetEnvironmentVariable)."""
    v = os.environ.get(name)
    if v:
        return v
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return winreg.QueryValueEx(k, name)[0]
    except Exception:
        return None


def http(url, data=None, headers=None, timeout=60):
    """One HTTP request; returns the response object (the caller reads or streams it)."""
    h = {"User-Agent": UA, **(headers or {})}
    return urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=timeout)


class Client:
    def __init__(self, client_id, secret, opener=http, now=lambda: time.time()):
        self.client_id, self.secret, self.opener, self.now = client_id, secret, opener, now
        self.token, self.expires = None, 0.0

    def bearer(self):
        if self.token is None or self.now() > self.expires - 120:          # refresh two minutes early
            body = urllib.parse.urlencode({"client_id": self.client_id, "client_secret": self.secret,
                                           "scope": "ais", "grant_type": "client_credentials"}).encode()
            with self.opener(TOKEN_URL, body, {"Content-Type": "application/x-www-form-urlencoded"}) as r:
                tok = json.loads(r.read().decode("utf-8"))
            self.token, self.expires = tok["access_token"], self.now() + float(tok.get("expires_in", 3600))
        return {"Authorization": f"bearer {self.token}"}

    def post_json(self, path, payload, timeout=120):
        h = {**self.bearer(), "Content-Type": "application/json", "Accept": "application/json"}
        return self.opener(API + path, json.dumps(payload).encode(), h, timeout)


def _day_dir(t):
    d = os.path.join(OUT, t.strftime("%Y-%m-%d"))
    os.makedirs(d, exist_ok=True)
    return d


def snapshot(client, log=print, now=None):
    now = now or datetime.now(timezone.utc)
    with client.post_json("/v1/latest/combined", {"modelType": "Full", "modelFormat": "Json"}) as r:
        raw = r.read()
    rows = json.loads(raw.decode("utf-8"))
    path = os.path.join(_day_dir(now), f"latest_{now:%H%M%S}Z.json.gz")
    with gzip.open(path, "wb") as f:
        f.write(raw)                                                       # unchanged, as delivered
    try:
        shown = os.path.relpath(path, ROOT)
    except ValueError:                                                     # another drive (tests use a temp folder)
        shown = path
    log(f"snapshot: {len(rows)} ships -> {shown}")
    return len(rows)


def stream(client, hours, log=print, clock=lambda: datetime.now(timezone.utc), sleep=time.sleep):
    """SSE stream for `hours`, downsampled, written hourly; reconnects with backoff; stops on the STOP file."""
    stop_file, end = os.path.join(OUT, "STOP"), time.time() + hours * 3600
    counts, errors, backoff = {"messages": 0, "connections": 0}, [], 5
    while time.time() < end and not os.path.exists(stop_file):
        try:
            counts["connections"] += 1
            payload = {"modelType": "Simple", "modelFormat": "Json", "downsample": True}
            h = {**client.bearer(), "Content-Type": "application/json", "Accept": "text/event-stream"}
            with client.opener(API + "/v1/sse/combined", json.dumps(payload).encode(), h, 90) as r:
                backoff, fh, hour = 5, None, None
                try:
                    for line in r:
                        if time.time() >= end or os.path.exists(stop_file) or time.time() > client.expires - 120:
                            break                                          # time's up, stop asked, or token due
                        line = line.decode("utf-8", "replace").strip()
                        if not line.startswith("data:"):
                            continue
                        t = clock()
                        if t.strftime("%Y-%m-%dT%H") != hour:
                            if fh:
                                fh.close()
                            hour = t.strftime("%Y-%m-%dT%H")
                            fh = gzip.open(os.path.join(_day_dir(t), f"stream_{t:%H}Z.jsonl.gz"), "at", encoding="utf-8")
                        fh.write(line[5:].strip() + "\n")
                        counts["messages"] += 1
                finally:
                    if fh:
                        fh.close()
            if time.time() < end and not os.path.exists(stop_file):
                sleep(5)                                                   # the server closed the stream: pause, then reconnect
        except Exception as e:
            errors.append(f"{clock():%H:%M:%SZ} {type(e).__name__}: {str(e)[:160]}")
            log(f"stream: {errors[-1]}; retrying in {backoff} s")
            sleep(backoff)
            backoff = min(backoff * 2, 300)
    status = {"finished": clock().isoformat()[:19] + "Z", **counts, "errors": errors[-20:],
              "token_expires_utc": datetime.fromtimestamp(client.expires, timezone.utc).isoformat()[:19] + "Z"}
    os.makedirs(OUT, exist_ok=True)
    json.dump(status, open(os.path.join(OUT, "status.json"), "w", encoding="utf-8"), indent=1)
    log(f"stream: {counts['messages']} messages over {counts['connections']} connection(s), {len(errors)} error(s)")
    return counts


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("snapshot")
    s = sub.add_parser("stream")
    s.add_argument("--hours", type=float, default=1.0)
    a = ap.parse_args()
    cid, sec = credential(ENV_ID), credential(ENV_SECRET)
    if a.dry_run or not a.cmd:
        print(f"{ENV_ID}: {'found' if cid else 'NOT FOUND'}; {ENV_SECRET}: {'found' if sec else 'NOT FOUND'}")
        print(f"token: POST {TOKEN_URL} (client_credentials, scope ais); API: {API}")
        return
    if not (cid and sec):
        print(f"no {ENV_ID}/{ENV_SECRET} yet: skipped")
        return
    client = Client(cid, sec)
    if a.cmd == "snapshot":
        snapshot(client)
    else:
        stream(client, a.hours)


if __name__ == "__main__":
    sys.exit(main())
