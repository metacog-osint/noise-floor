#!/usr/bin/env python3
"""digitraffic_ais.py: collect Finland's open AIS stream (Digitraffic, Fintraffic) into per-UTC-day Parquet files.

Source: Digitraffic Marine, MQTT over WebSocket at wss://meri.digitraffic.fi:443/mqtt (registry id `digitraffic-ais`,
CC BY 4.0, "Source: Fintraffic / digitraffic.fi, license CC 4.0 BY"). No account is needed. Docs:
https://www.digitraffic.fi/en/marine-traffic/ and https://www.digitraffic.fi/en/support/instructions/ (checked 24 Oct 2026).

What it subscribes to (one connection, QoS 0):
  vessels-v2/+/location   position reports: time (epoch s), lat, lon, sog, cog, heading, navStat, rot, posAcc, raim
  vessels-v2/+/metadata   static and voyage data: timestamp (epoch ms), name, callSign, imo, type, destination,
                          draught, eta, posType, refA-refD
  vessels-v2/status       the feed's own heartbeat ("updated", epoch s)
At start, and once per new UTC day, it also fetches one REST snapshot of the vessel register
(GET /api/ais/v1/vessels, gzip, Digitraffic-User header) so vessels that stay silent on metadata still have identities.
The REST locations endpoint returns only each vessel's latest position (no history), so it is not used.

Politeness: the client identifies itself as "noise-floor" (MQTT client id "noise-floor; <uuid>" as in Digitraffic's
Python example, and a Digitraffic-User header on the WebSocket handshake and REST call; no personal data). One
connection; reconnects back off from 10 s to 5 min (Digitraffic allows 5 MQTT connections a minute per IP without
the header).

Outputs (root data/ is gitignored), by receive day in UTC:
  data/ais/digitraffic/YYYY-MM-DD/locations-HHMMSS-PID.parquet   one part per flush (every --flush-min minutes)
  data/ais/digitraffic/YYYY-MM-DD/metadata-HHMMSS-PID.parquet
  data/ais/digitraffic/YYYY-MM-DD/locations.parquet          parts merged ("compacted") at day end and at exit
  data/ais/digitraffic/YYYY-MM-DD/metadata.parquet
  data/ais/digitraffic/status.json                           PID, counts, last message and flush times (UTC)
Columns: see LOC_SCHEMA and META_SCHEMA below. rx_ms is our receive time (epoch ms, UTC); src is mqtt or rest.

Stopping cleanly: --hours N, Ctrl+C, or create the file data/ais/digitraffic/STOP (deleted on exit). Every exit path
flushes and compacts. Log lines go to stderr and to data/ais/digitraffic/collector.log (--log). Needs paho-mqtt (>= 2.0)
and pyarrow.

Usage
  python collectors/digitraffic_ais.py --hours 12
  python collectors/digitraffic_ais.py --compact-only          # merge leftover parts (e.g. after a crash)
"""
import argparse
import glob
import gzip
import json
import os
import signal
import sys
import time
import urllib.request
import uuid
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "ais", "digitraffic")
HOST, PORT, WS_PATH = "meri.digitraffic.fi", 443, "/mqtt"
REST_VESSELS = "https://meri.digitraffic.fi/api/ais/v1/vessels"
USER = "noise-floor"
TOPICS = [("vessels-v2/+/location", 0), ("vessels-v2/+/metadata", 0), ("vessels-v2/status", 0)]
STALE_S = 180          # no message for this long while connected: drop and reconnect (normal rate is ~30 a second)

LOC_SCHEMA = pa.schema([
    ("mmsi", pa.int32()), ("time", pa.int64()), ("lat", pa.float64()), ("lon", pa.float64()),
    ("sog", pa.float32()), ("cog", pa.float32()), ("heading", pa.int16()), ("navStat", pa.int8()),
    ("rot", pa.int16()), ("posAcc", pa.bool_()), ("raim", pa.bool_()), ("rx_ms", pa.int64()),
])
META_SCHEMA = pa.schema([
    ("mmsi", pa.int32()), ("timestamp", pa.int64()), ("name", pa.string()), ("callSign", pa.string()),
    ("imo", pa.int32()), ("type", pa.int16()), ("destination", pa.string()), ("draught", pa.int16()),
    ("eta", pa.int32()), ("posType", pa.int8()), ("refA", pa.int16()), ("refB", pa.int16()),
    ("refC", pa.int16()), ("refD", pa.int16()), ("rx_ms", pa.int64()), ("src", pa.string()),
])
LOC_KEYS = [f.name for f in LOC_SCHEMA]
META_KEYS = [f.name for f in META_SCHEMA]


def utcnow():
    return datetime.now(timezone.utc)


def iso(ms=None):
    t = utcnow() if ms is None else datetime.fromtimestamp(ms / 1000, timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def day_of(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


LOG_PATH = None              # set from --log; lines also go to stderr


def log(*a):
    line = " ".join([iso()] + [str(x) for x in a])
    try:
        print(line, file=sys.stderr, flush=True)
    except Exception:               # no console (e.g. started hidden): the log file still gets the line
        pass
    if LOG_PATH:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def _int(v, lo, hi):
    """An int inside the column's range, else None (keeps one bad field from losing a row)."""
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    return v if lo <= v <= hi else None


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _bool(v):
    return None if v is None else bool(v)


def _str(v):
    return None if v is None else str(v)


def loc_row(mmsi, d, rx):
    return (mmsi, _int(d.get("time"), 0, 2**62), _num(d.get("lat")), _num(d.get("lon")), _num(d.get("sog")),
            _num(d.get("cog")), _int(d.get("heading"), -32768, 32767), _int(d.get("navStat"), -128, 127),
            _int(d.get("rot"), -32768, 32767), _bool(d.get("posAcc")), _bool(d.get("raim")), rx)


def meta_row(mmsi, d, rx, src):
    g = d.get
    return (mmsi, _int(g("timestamp"), 0, 2**62), _str(g("name")), _str(g("callSign")), _int(g("imo"), -2**31, 2**31 - 1),
            _int(g("type", g("shipType")), -32768, 32767), _str(g("destination")), _int(g("draught"), -32768, 32767),
            _int(g("eta"), -2**31, 2**31 - 1), _int(g("posType"), -128, 127),
            _int(g("refA", g("referencePointA")), -32768, 32767), _int(g("refB", g("referencePointB")), -32768, 32767),
            _int(g("refC", g("referencePointC")), -32768, 32767), _int(g("refD", g("referencePointD")), -32768, 32767),
            rx, src)


def write_part(day, kind, rows, keys, schema):
    """Write one flush's rows as a new Parquet part (atomic rename), so a crash never corrupts earlier data."""
    if not rows:
        return
    d = os.path.join(OUT, day)
    os.makedirs(d, exist_ok=True)
    cols = list(zip(*rows))
    table = pa.table({k: pa.array(c, type=schema.field(k).type) for k, c in zip(keys, cols)}, schema=schema)
    stamp = utcnow().strftime("%H%M%S") + f"-{os.getpid()}"
    path = os.path.join(d, f"{kind}-{stamp}.parquet")
    n = 0
    while os.path.exists(path):
        n += 1
        path = os.path.join(d, f"{kind}-{stamp}-{n}.parquet")
    tmp = path + ".tmp"
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, path)


def compact(day, kind, schema):
    """Merge a day's parts (and any earlier merged file) into <day>/<kind>.parquet, then delete the parts."""
    d = os.path.join(OUT, day)
    parts = sorted(glob.glob(os.path.join(d, f"{kind}-*.parquet")))
    if not parts:
        return 0
    merged = os.path.join(d, f"{kind}.parquet")
    srcs = ([merged] if os.path.exists(merged) else []) + parts
    tables = []
    for p in srcs:
        try:
            tables.append(pq.read_table(p).cast(schema))
        except Exception as e:  # a damaged part is kept aside, never silently dropped
            log(f"compact: cannot read {os.path.basename(p)} ({e}); renamed to .bad")
            os.replace(p, p + ".bad")
            if p in parts:
                parts.remove(p)
    if not tables:
        return 0
    t = pa.concat_tables(tables)
    sort = [("mmsi", "ascending"), ("time" if kind == "locations" else "rx_ms", "ascending")]
    t = t.sort_by(sort)
    tmp = merged + ".tmp"
    pq.write_table(t, tmp, compression="zstd", row_group_size=500_000)
    os.replace(tmp, merged)
    for p in parts:
        os.remove(p)
    return t.num_rows


def fetch_vessels_snapshot():
    """One REST call for the vessel register; returns metadata rows (src='rest')."""
    req = urllib.request.Request(REST_VESSELS, headers={"Digitraffic-User": USER, "Accept-Encoding": "gzip",
                                                        "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
    rx = int(time.time() * 1000)
    rows = []
    for v in json.loads(body):
        m = _int(v.get("mmsi"), 0, 2**31 - 1)
        if m is not None:
            rows.append(meta_row(m, v, rx, "rest"))
    return rows


class Collector:
    def __init__(self, args):
        import paho.mqtt.client as mqtt
        self.mqtt = mqtt
        self.args = args
        self.loc, self.meta = {}, {}          # day -> rows
        self.counts = {"location": 0, "metadata": 0, "status": 0, "bad": 0, "connects": 0, "flushes": 0}
        self.last_msg = 0.0
        self.last_status_updated = None
        self.connected = False
        self.connected_since = 0.0
        self.backoff, self.next_try = 10, 0.0
        self.stop = False
        self.started = utcnow()
        self.days_seen = set()
        self.snapshot_days = set()
        cid = f"{USER}; {uuid.uuid4()}"
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid, transport="websockets",
                                  clean_session=True)
        self.client.ws_set_options(path=WS_PATH, headers={"Digitraffic-User": USER})
        self.client.tls_set()
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

    # MQTT callbacks (all run in this thread, inside client.loop())
    def on_connect(self, client, userdata, flags, rc, props=None):
        if rc.is_failure:
            log(f"connect refused: {rc}")
            self.connected = False
            return
        self.connected = True
        self.connected_since = self.last_msg = time.time()
        client.subscribe(TOPICS)
        log("connected; subscribed", ", ".join(t for t, _ in TOPICS))

    def on_disconnect(self, client, userdata, flags, rc, props=None):
        if self.connected and not self.stop:
            self.retry_later(f"disconnected: {rc}")
        self.connected = False

    def retry_later(self, why):
        """Mark the connection down and schedule the next attempt with exponential backoff (10 s to 5 min)."""
        self.connected = False
        self.next_try = time.time() + self.backoff
        log(f"{why}; next attempt in {self.backoff} s")
        self.backoff = min(self.backoff * 2, 300)

    def on_message(self, client, userdata, msg):
        self.last_msg = time.time()
        rx = int(self.last_msg * 1000)
        parts = msg.topic.split("/")
        kind = parts[-1]
        try:
            d = json.loads(msg.payload)
            if kind == "location":
                row = loc_row(int(parts[1]), d, rx)
                self.loc.setdefault(day_of(rx), []).append(row)
                self.counts["location"] += 1
            elif kind == "metadata":
                row = meta_row(int(parts[1]), d, rx, "mqtt")
                self.meta.setdefault(day_of(rx), []).append(row)
                self.counts["metadata"] += 1
            elif kind == "status":
                self.counts["status"] += 1
                self.last_status_updated = d.get("updated")
        except Exception:
            self.counts["bad"] += 1

    # housekeeping
    def snapshot(self):
        day = utcnow().strftime("%Y-%m-%d")
        if day in self.snapshot_days or self.args.no_snapshot:
            return
        self.snapshot_days.add(day)
        try:
            rows = fetch_vessels_snapshot()
            self.meta.setdefault(day, []).extend(rows)
            log(f"REST vessel snapshot: {len(rows)} vessels")
        except Exception as e:
            log(f"REST vessel snapshot failed: {e}")

    def flush(self, final=False):
        today = utcnow().strftime("%Y-%m-%d")
        for day in sorted(set(self.loc) | set(self.meta)):
            for kind, buf, keys, schema in (("locations", self.loc, LOC_KEYS, LOC_SCHEMA),
                                            ("metadata", self.meta, META_KEYS, META_SCHEMA)):
                try:
                    write_part(day, kind, buf.get(day, []), keys, schema)
                    buf.pop(day, None)
                except Exception as e:          # keep the rows in memory and try again next flush
                    log(f"write failed for {day} {kind}: {e}")
            self.days_seen.add(day)
        self.counts["flushes"] += 1
        for day in sorted(self.days_seen):
            if day < today or final:
                try:
                    n = compact(day, "locations", LOC_SCHEMA)
                    compact(day, "metadata", META_SCHEMA)
                except Exception as e:          # parts stay on disk; --compact-only can finish later
                    log(f"compaction failed for {day}: {e}")
                    continue
                if n:
                    log(f"compacted {day}: {n} location rows")
                if day < today:
                    self.days_seen.discard(day)
        self.write_status(final)

    def write_status(self, final=False):
        st = {"pid": os.getpid(), "started_utc": self.started.strftime("%Y-%m-%dT%H:%M:%SZ"), "now_utc": iso(),
              "running": not final, "connected": self.connected, "counts": self.counts,
              "last_message_utc": iso(self.last_msg * 1000) if self.last_msg else None,
              "feed_status_updated_utc": iso(self.last_status_updated * 1000) if self.last_status_updated else None,
              "source": "Fintraffic / digitraffic.fi, license CC 4.0 BY"}
        os.makedirs(OUT, exist_ok=True)
        tmp = os.path.join(OUT, "status.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, indent=1)
        os.replace(tmp, os.path.join(OUT, "status.json"))

    def run(self):
        a = self.args
        deadline = time.time() + a.hours * 3600 if a.hours else None
        stopfile = os.path.join(OUT, "STOP")
        os.makedirs(OUT, exist_ok=True)
        if os.path.exists(stopfile):
            os.remove(stopfile)
        next_flush = time.time() + a.flush_min * 60
        self.snapshot()
        self.write_status()
        log(f"start: pid {os.getpid()}, hours {a.hours or 'unlimited'}, flush every {a.flush_min} min -> {OUT}")
        while not self.stop:
            now = time.time()
            if deadline and now >= deadline:
                log("time limit reached")
                break
            if os.path.exists(stopfile):
                log("STOP file found")
                break
            if not self.connected and now >= self.next_try:
                try:
                    if self.counts["connects"]:
                        log("reconnecting")
                    self.counts["connects"] += 1
                    self.client.connect(HOST, PORT, keepalive=60)
                    # CONNACK arrives in loop(); give it a window before counting this as a failure
                    t0 = time.time()
                    while not self.connected and time.time() - t0 < 20 and not self.stop:
                        self.client.loop(timeout=1.0)
                    if not self.connected:
                        raise RuntimeError("no CONNACK within 20 s")
                except Exception as e:
                    try:
                        self.client.disconnect()
                    except Exception:
                        pass
                    self.retry_later(f"connect failed: {e}")
            if self.connected:
                rc = self.client.loop(timeout=1.0)
                if rc != self.mqtt.MQTT_ERR_SUCCESS:
                    if self.connected:
                        self.retry_later(f"loop error {rc}")
                elif time.time() - self.last_msg > STALE_S:
                    try:
                        self.client.disconnect()
                    except Exception:
                        pass
                    self.retry_later(f"no messages for {STALE_S} s; dropped the connection")
                elif self.backoff > 10 and time.time() - self.connected_since > 120:
                    self.backoff = 10          # stable again: reset the backoff
            else:
                time.sleep(1.0)
            if time.time() >= next_flush:
                self.flush()
                self.snapshot()        # no-op unless a new UTC day has started
                next_flush = time.time() + a.flush_min * 60
                log(f"flush: {self.counts['location']} locations, {self.counts['metadata']} metadata so far; "
                    f"connected={self.connected}")
        self.stop = True
        try:
            self.client.disconnect()
            self.client.loop(timeout=1.0)       # let the DISCONNECT go out
        except Exception:
            pass
        self.connected = False
        self.flush(final=True)
        if os.path.exists(stopfile):
            os.remove(stopfile)
        log(f"stopped: {self.counts}")


def main():
    global LOG_PATH, OUT
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--hours", type=float, default=0, help="stop after N hours (default: run until stopped)")
    ap.add_argument("--flush-min", type=float, default=5, help="minutes between flushes to disk (default 5)")
    ap.add_argument("--no-snapshot", action="store_true", help="skip the REST vessel-register snapshot")
    ap.add_argument("--compact-only", action="store_true", help="merge leftover parts for every day, then exit")
    ap.add_argument("--log", default=None,
                    help="append log lines to this file as well as stderr (default <out>/collector.log; '' for none)")
    ap.add_argument("--out", default=OUT, help="output folder (default data/ais/digitraffic)")
    args = ap.parse_args()
    OUT = os.path.abspath(args.out)
    if args.log is None:
        args.log = os.path.join(OUT, "collector.log")
    if args.log:
        os.makedirs(os.path.dirname(os.path.abspath(args.log)), exist_ok=True)
        LOG_PATH = args.log
    if args.compact_only:
        for d in sorted(glob.glob(os.path.join(OUT, "????-??-??"))):
            day = os.path.basename(d)
            n = compact(day, "locations", LOC_SCHEMA)
            compact(day, "metadata", META_SCHEMA)
            print(day, n)
        return
    c = Collector(args)

    def handler(signum, frame):
        log(f"signal {signum}: stopping")
        c.stop = True
    for s in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, s):
            signal.signal(getattr(signal, s), handler)
    c.run()


if __name__ == "__main__":
    main()
