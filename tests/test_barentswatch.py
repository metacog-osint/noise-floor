"""Offline tests for collectors/barentswatch_ais.py: token, snapshot and SSE stream against a fake server. No network."""
import gzip
import io
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "collectors"))
import barentswatch_ais as B  # noqa: E402


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class Fake:
    def __init__(self):
        self.calls = []

    def __call__(self, url, data=None, headers=None, timeout=60):
        self.calls.append((url, data, headers))
        if url == B.TOKEN_URL:
            form = dict(x.split("=") for x in data.decode().split("&"))
            assert form["grant_type"] == "client_credentials" and form["scope"] == "ais" and form["client_id"] == "id1"
            return Resp(json.dumps({"access_token": "tok", "expires_in": 3600}).encode())
        assert headers["Authorization"] == "bearer tok", headers
        if url.endswith("/v1/latest/combined"):
            return Resp(json.dumps([{"mmsi": 257111020, "latitude": 70.1, "longitude": 25.2},
                                    {"mmsi": 273123456, "latitude": 69.9, "longitude": 33.0}]).encode())
        if url.endswith("/v1/sse/combined"):
            assert json.loads(data)["downsample"] is True and headers["Accept"] == "text/event-stream"
            return Resp(b": keepalive\n\ndata: {\"mmsi\": 1, \"latitude\": 70}\n\ndata: {\"mmsi\": 2, \"latitude\": 71}\n\n")
        raise AssertionError(url)


def main():
    tmp = tempfile.mkdtemp()
    B.OUT = tmp
    try:
        fake = Fake()
        c = B.Client("id1", "sec", opener=fake)
        n = B.snapshot(c, log=lambda m: None, now=datetime(2026, 10, 29, 6, 0, tzinfo=timezone.utc))
        assert n == 2
        snap = os.path.join(tmp, "2026-10-29", "latest_060000Z.json.gz")
        assert json.loads(gzip.open(snap).read())[0]["mmsi"] == 257111020      # stored unchanged
        tokens = [x for x in fake.calls if x[0] == B.TOKEN_URL]
        B.snapshot(c, log=lambda m: None, now=datetime(2026, 10, 29, 6, 10, tzinfo=timezone.utc))
        assert len([x for x in fake.calls if x[0] == B.TOKEN_URL]) == len(tokens) == 1      # token reused

        # stream: one connection delivers two messages and ends; then the STOP file ends the run
        clock = lambda: datetime(2026, 10, 29, 7, 30, tzinfo=timezone.utc)        # noqa: E731
        def sleep(_):
            open(os.path.join(tmp, "STOP"), "w").close()
        counts = B.stream(c, hours=1, log=lambda m: None, clock=clock, sleep=sleep)
        # the fake stream ends after two messages; the collector pauses before reconnecting, and the fake pause
        # creates the STOP file, so the run ends after one connection
        lines = gzip.open(os.path.join(tmp, "2026-10-29", "stream_07Z.jsonl.gz"), "rt").read().splitlines()
        assert lines[:2] == ['{"mmsi": 1, "latitude": 70}', '{"mmsi": 2, "latitude": 71}'], lines[:3]
        assert counts["messages"] >= 2 and json.load(open(os.path.join(tmp, "status.json")))["messages"] == counts["messages"]
        print("test_barentswatch: ok")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
