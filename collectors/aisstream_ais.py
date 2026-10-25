#!/usr/bin/env python3
"""aisstream_ais.py: collect AIS from aisstream.io's WebSocket API into per-UTC-day Parquet files. PRIVATE DATA.

aisstream.io publishes no terms of service or licence (registry row `aisstream`, checked 23 Oct 2026), so everything this
collector writes stays private: it feeds the private watch site only and is never published or committed.

Source and protocol (https://aisstream.io/documentation, read 25 Oct 2026; field names from the generated models,
https://github.com/aisstream/ais-message-models type-definition.yaml):
  - Connect to wss://stream.aisstream.io/v0/stream with permessage-deflate. aisstream needs compression to serve full
    bandwidth, and from September 2026 uncompressed connections are bandwidth-limited. The SubscriptionConfirmation
    says whether compression was negotiated (Message.CompressionEnabled); the collector logs it.
  - Send one JSON subscription within 3 s of connecting: APIKey, BoundingBoxes [[[lat, lon], [lat, lon]], ...],
    optional FiltersShipMMSI (at most 200 nine-character strings) and FilterMessageTypes. Invalid subscriptions get
    no reply and the connection is closed.
  - Limits: 3 subscribed connections per account, 3 open connections per IP, at most one subscription update per
    second per connection. A slow reader loses messages (no replay). No SLA: reconnect with backoff and jitter.
  - Direct browser connections are not permitted: this script is the server-side client.
  - Frames are binary, UTF-8 JSON: {"MessageType": ..., "MetaData": {...}, "Message": {<MessageType>: {...}}}.

Message types subscribed (FilterMessageTypes): PositionReport (class A, msgs 1-3), StandardClassBPositionReport (18),
ExtendedClassBPositionReport (19), ShipStaticData (class A static and voyage, 5), StaticDataReport (class B static, 24).

The API key comes from the AISSTREAM_API_KEY environment variable, or on Windows from the user environment
(HKCU\\Environment) when the process started before the variable was set. The key is never printed, logged, written or
put in an exception message: every log line and error text passes through a redactor first.

Bounding boxes default to the focus areas in private/watch/maritime.json, read at run time (boxes there are
[lat0, lat1, lon0, lon1]; entries marked "candidate" are skipped unless named with --areas). --box adds or replaces
boxes. Watch configuration never goes into tracked files.

Outputs (root data/ is gitignored), by receive day in UTC, with the Digitraffic collector's column names where they
overlap, so tools/ais_detect.py's loaders read both:
  data/ais/aisstream/YYYY-MM-DD/locations-HHMMSS-PID.parquet   one part per flush (every --flush-min minutes)
  data/ais/aisstream/YYYY-MM-DD/metadata-HHMMSS-PID.parquet
  data/ais/aisstream/YYYY-MM-DD/locations.parquet              parts merged at day end and at exit
  data/ais/aisstream/YYYY-MM-DD/metadata.parquet
  data/ais/aisstream/status.json                               PID, streams, counts, last message (UTC); no key
  data/ais/aisstream/private_craft.json                        MMSIs seen as pleasure craft (dropped, see below)
Locations add msg_id (AIS message number), valid, meta_name (aisstream's MetaData ShipName) and source ("aisstream").
Metadata adds msg_id and source; src is "ws". draught is in tenths of a metre and eta is packed as Digitraffic does
(month << 16 | day << 11 | hour << 6 | minute), so both sources mean the same thing in the same column.
time is the position's epoch second: aisstream's MetaData time_utc when present (else our receive time), moved back to
the report's own UTC second (the AIS Timestamp field, 0-59).

No private craft (maritime plan Section 12): MMSIs whose static data says AIS type 37 (pleasure craft) are dropped
before their rows reach disk, and compaction drops any of their rows written before the type arrived. Vessels on the
private watch list or in data/vessels/sanctioned.json are exempt. Nothing about crews is collected.

Stopping cleanly: --hours N, Ctrl+C, or create data/ais/aisstream/STOP (deleted on exit). Every exit path flushes and
compacts. Log lines go to stderr and to data/ais/aisstream/collector.log. Needs `websockets` (>= 13) and pyarrow.

Usage
  python collectors/aisstream_ais.py --dry-run                 # show the subscription (key redacted) and exit
  python collectors/aisstream_ais.py --hours 24
  python collectors/aisstream_ais.py --areas <area-id> --hours 2      # ids from the private config
  python collectors/aisstream_ais.py --watch-global --hours 24 # plus a second connection: watch-list MMSIs worldwide
  python collectors/aisstream_ais.py --compact-only            # merge leftover parts (e.g. after a crash)
"""
import argparse
import glob
import json
import logging
import os
import random
import re
import signal
import sys
import threading
import time
import traceback
import urllib.parse
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "ais", "aisstream")
WATCH_CONFIG = os.path.join(ROOT, "private", "watch", "maritime.json")
SANCTIONED = os.path.join(ROOT, "data", "vessels", "sanctioned.json")
URL = "wss://stream.aisstream.io/v0/stream"
KEY_ENV = "AISSTREAM_API_KEY"
SOURCE = "aisstream"
TYPES = ["PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport", "ShipStaticData",
         "StaticDataReport"]
MAX_MMSI = 200                 # aisstream: at most 200 MMSI filters per subscription
STALE_S = 300                  # focus boxes: no message for this long while subscribed -> reconnect
STALE_WATCH_S = 6 * 3600       # MMSI-filtered stream: watched vessels can be out of coverage for hours
CONFIRM_S = 20                 # no SubscriptionConfirmation (and no data) this long after subscribing -> retry
MAX_UNCONFIRMED = 8            # consecutive attempts never confirmed in this run -> give up (bad key or boxes)
PRIVATE_TYPES = {37}           # AIS ship type 37: pleasure craft (ITU-R M.1371 Table 53)
PRIVATE_KEEP_DAYS = 180        # forget a private-craft MMSI after this long unseen (MMSIs get reassigned)

LOC_SCHEMA = pa.schema([
    ("mmsi", pa.int32()), ("time", pa.int64()), ("lat", pa.float64()), ("lon", pa.float64()),
    ("sog", pa.float32()), ("cog", pa.float32()), ("heading", pa.int16()), ("navStat", pa.int8()),
    ("rot", pa.int16()), ("posAcc", pa.bool_()), ("raim", pa.bool_()), ("rx_ms", pa.int64()),
    ("msg_id", pa.int8()), ("valid", pa.bool_()), ("meta_name", pa.string()), ("source", pa.string()),
])
META_SCHEMA = pa.schema([
    ("mmsi", pa.int32()), ("timestamp", pa.int64()), ("name", pa.string()), ("callSign", pa.string()),
    ("imo", pa.int32()), ("type", pa.int16()), ("destination", pa.string()), ("draught", pa.int16()),
    ("eta", pa.int32()), ("posType", pa.int8()), ("refA", pa.int16()), ("refB", pa.int16()),
    ("refC", pa.int16()), ("refD", pa.int16()), ("rx_ms", pa.int64()), ("src", pa.string()),
    ("msg_id", pa.int8()), ("source", pa.string()),
])
LOC_KEYS = [f.name for f in LOC_SCHEMA]
META_KEYS = [f.name for f in META_SCHEMA]
MSG_IDS = {"PositionReport": 1, "StandardClassBPositionReport": 18, "ExtendedClassBPositionReport": 19,
           "ShipStaticData": 5, "StaticDataReport": 24}


# ----------------------------------------------------------------------------------------------- secrets
class Redactor:
    """Replaces every registered secret (raw, JSON-escaped and URL-encoded forms) with [REDACTED]."""

    def __init__(self):
        self.forms = []

    def add(self, secret):
        if not secret or len(secret) < 4:
            return
        for f in (secret, json.dumps(secret)[1:-1], urllib.parse.quote(secret, safe=""),
                  urllib.parse.quote_plus(secret)):
            if f and f not in self.forms:
                self.forms.append(f)
        self.forms.sort(key=len, reverse=True)

    def __call__(self, text):
        text = str(text)
        for f in self.forms:
            text = text.replace(f, "[REDACTED]")
        return text


REDACT = Redactor()


def err_text(e):
    """An exception as one redacted line: type and message, never the payload we sent."""
    return REDACT(f"{type(e).__name__}: {e}")


def get_api_key(environ=None):
    """The aisstream key from the process environment, else (Windows) the user environment in the registry."""
    environ = os.environ if environ is None else environ
    k = (environ.get(KEY_ENV) or "").strip()
    if k:
        return k
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as h:
                v, _ = winreg.QueryValueEx(h, KEY_ENV)
            return str(v).strip() or None
        except OSError:
            return None
    return None


def _excepthook(tp, val, tb):
    sys.stderr.write(REDACT("".join(traceback.format_exception(tp, val, tb))))


def _thread_excepthook(a):
    sys.stderr.write(REDACT("".join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback))))


class _RedactFilter(logging.Filter):
    def filter(self, record):
        record.msg = REDACT(record.getMessage())
        record.args = ()
        return True


def install_redaction():
    """Uncaught exceptions (main and threads) and the websockets library's own log lines go through the redactor."""
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    lg = logging.getLogger("websockets")
    lg.setLevel(logging.WARNING)            # DEBUG would log frames, including the subscription
    lg.propagate = False
    if not any(isinstance(h, logging.StreamHandler) and getattr(h, "_nf", False) for h in lg.handlers):
        h = logging.StreamHandler(sys.stderr)
        h._nf = True
        h.addFilter(_RedactFilter())
        h.setFormatter(logging.Formatter("%(asctime)s websockets %(levelname)s %(message)s"))
        lg.addHandler(h)


# ----------------------------------------------------------------------------------------------- basics
def utcnow():
    return datetime.now(timezone.utc)


def iso(ms=None):
    t = utcnow() if ms is None else datetime.fromtimestamp(ms / 1000, timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def day_of(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


LOG_PATH = None


def log(*a):
    line = REDACT(" ".join([iso()] + [str(x) for x in a]))
    try:
        print(line, file=sys.stderr, flush=True)
    except Exception:
        pass
    if LOG_PATH:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def _int(v, lo, hi):
    if isinstance(v, bool):
        v = int(v)
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    return v if lo <= v <= hi else None


def _num(v):
    if isinstance(v, bool):
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _bool(v):
    return None if v is None else bool(v)


def _text(v):
    """AIS six-bit text: trailing '@' padding and spaces removed; empty -> None."""
    if v is None:
        return None
    s = str(v).replace("\x00", "").rstrip(" @").strip()
    return s or None


# ----------------------------------------------------------------------------------------------- boxes
def parse_box(s):
    """'lat0,lat1,lon0,lon1' (the order maritime.json uses) -> [lat0, lat1, lon0, lon1], validated."""
    try:
        v = [float(x) for x in str(s).replace(" ", "").split(",")]
    except ValueError:
        raise ValueError(f"box {s!r}: expected lat0,lat1,lon0,lon1")
    return check_box(v)


def check_box(v):
    if len(v) != 4:
        raise ValueError(f"box {v!r}: expected 4 numbers lat0,lat1,lon0,lon1")
    la0, la1, lo0, lo1 = (float(x) for x in v)
    if not (-90 <= la0 <= 90 and -90 <= la1 <= 90 and -180 <= lo0 <= 180 and -180 <= lo1 <= 180):
        raise ValueError(f"box {v!r}: latitude must be within +-90 and longitude within +-180")
    if la0 == la1 or lo0 == lo1:
        raise ValueError(f"box {v!r}: zero width or height")
    return [la0, la1, lo0, lo1]


def corners(b):
    """[lat0, lat1, lon0, lon1] -> aisstream corner pairs. A box with lon0 > lon1 crosses the antimeridian and is split
    in two (the docs don't say how aisstream treats such a box)."""
    la0, la1, lo0, lo1 = b
    s, n = min(la0, la1), max(la0, la1)
    if lo0 > lo1:
        return [[[s, lo0], [n, 180.0]], [[s, -180.0], [n, lo1]]]
    return [[[s, lo0], [n, lo1]]]


def load_watch_config(path=WATCH_CONFIG):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_boxes(path=WATCH_CONFIG, areas=None):
    """Focus-area boxes from the private maritime config: [(id, [lat0, lat1, lon0, lon1]), ...]. With areas given,
    exactly those ids (candidates included); otherwise every area not marked candidate."""
    cfg = load_watch_config(path)
    want = set(areas or [])
    out, seen = [], set()
    for a in cfg.get("focus_areas", []):
        aid = a.get("id") or f"area{len(out) + 1}"
        if want and aid not in want:
            continue
        if not want and a.get("candidate"):
            continue
        out.append((aid, check_box(a["box"])))
        seen.add(aid)
    missing = want - seen
    if missing:
        raise ValueError(f"unknown area id(s) in {os.path.basename(path)}: {', '.join(sorted(missing))}")
    return out


def _imo(v):
    """An IMO number from 9074729, "9074729" or "IMO 9074729"; None if not a 7-digit number."""
    return _int(str(v).upper().replace("IMO", "").strip() if v is not None else None, 1_000_000, 9_999_999)


def load_watch_ids(path=WATCH_CONFIG):
    """(MMSIs, IMOs) on the private vessel watch list."""
    mm, im = set(), set()
    for v in (load_watch_config(path).get("vessel_watch") or {}).get("vessels", []):
        if not isinstance(v, dict):
            continue
        m = _int(v.get("mmsi"), 1, 999_999_999)
        i = _imo(v.get("imo"))
        if m:
            mm.add(m)
        if i:
            im.add(i)
    return mm, im


def load_sanctioned_ids(path=SANCTIONED):
    """(MMSIs, IMOs) from data/vessels/sanctioned.json (tools/sanctions.py: by_imo and by_mmsi; other layouts such as
    a list of records, a 'vessels' list or a dict keyed by IMO are read too). Missing or unreadable file -> empty."""
    mm, im = set(), set()
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return mm, im
    if isinstance(d, dict) and ("by_imo" in d or "by_mmsi" in d):        # tools/sanctions.py's layout
        recs = [dict(v, imo=v.get("imo", k)) if isinstance(v, dict) else {"imo": k}
                for k, v in (d.get("by_imo") or {}).items()]
        mm |= {m for m in (_int(k, 1, 999_999_999) for k in (d.get("by_mmsi") or {})) if m}
    else:
        recs = d.get("vessels", d) if isinstance(d, dict) else d
        if isinstance(recs, dict):
            recs = [dict(v, imo=v.get("imo", k)) if isinstance(v, dict) else {"imo": k} for k, v in recs.items()]
    for r in recs if isinstance(recs, list) else []:
        if not isinstance(r, dict):
            continue
        for m in (r.get("mmsi") if isinstance(r.get("mmsi"), list) else [r.get("mmsi")]):
            m = _int(m, 1, 999_999_999)
            if m:
                mm.add(m)
        for i in (r.get("imo") if isinstance(r.get("imo"), list) else [r.get("imo")]):
            i = _imo(i)
            if i:
                im.add(i)
    return mm, im


def subscription(key, boxes, types=TYPES, mmsi=None):
    """The JSON subscription message (contains the key: never log it; use describe_subscription)."""
    msg = {"APIKey": key, "BoundingBoxes": [c for b in boxes for c in corners(b)]}
    if mmsi:
        msg["FiltersShipMMSI"] = [f"{int(m):09d}" for m in sorted(mmsi)][:MAX_MMSI]
    if types:
        msg["FilterMessageTypes"] = list(types)
    return json.dumps(msg)


def describe_subscription(sub_json):
    d = json.loads(sub_json)
    d["APIKey"] = "[REDACTED]"
    return REDACT(json.dumps(d))


# ----------------------------------------------------------------------------------------------- parsing
_TIME_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2}):(\d{2})(\.\d+)?")
_OFF_RE = re.compile(r"([+-])(\d{2}):?(\d{2})")


def meta_time_s(md):
    """aisstream MetaData time (time_utc, e.g. '2026-10-25 01:02:03.123456789 +0000 UTC') as epoch seconds, or None.
    The current docs' example shows no time field; older messages carry time_utc (unverified for today's feed)."""
    v = None
    for k in ("time_utc", "TimeUtc", "TimeUTC", "time"):
        if md.get(k):
            v = str(md[k])
            break
    if not v:
        return None
    m = _TIME_RE.search(v)
    if not m:
        return None
    try:
        t = datetime.strptime(f"{m.group(1)} {m.group(2)}:{m.group(3)}:{m.group(4)}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    s = t.replace(tzinfo=timezone.utc).timestamp() + (float(m.group(5)) if m.group(5) else 0.0)
    off = _OFF_RE.search(v[m.end():])
    if off and not v[m.end():].strip().upper().startswith("Z"):
        sign = 1 if off.group(1) == "+" else -1
        s -= sign * (int(off.group(2)) * 3600 + int(off.group(3)) * 60)
    return s


def position_time(base_s, ts_sec):
    """Epoch second of a position: the latest time at or just before base_s whose second equals the report's UTC
    second (0-59); base_s itself when the report's second is not available (60-63)."""
    b = int(base_s)
    ts = _int(ts_sec, 0, 59)
    if ts is None:
        return b
    t = b - b % 60 + ts
    if t > b + 2:          # the report's second belongs to the previous minute (2 s of clock slack)
        t -= 60
    return t


def pack_eta(eta):
    """aisstream Eta {Month, Day, Hour, Minute} -> Digitraffic's packed integer (month<<16 | day<<11 | hour<<6 | min)."""
    if not isinstance(eta, dict):
        return None
    mo, d, h, mi = (_int(eta.get(k), 0, 63) for k in ("Month", "Day", "Hour", "Minute"))
    if None in (mo, d, h, mi):
        return None
    return (mo & 0xF) << 16 | (d & 0x1F) << 11 | (h & 0x1F) << 6 | (mi & 0x3F)


def _dims(dim):
    dim = dim if isinstance(dim, dict) else {}
    return tuple(_int(dim.get(k), 0, 32767) for k in ("A", "B", "C", "D"))


def _meta_row(mmsi, ts_ms, rx, msg_id, name=None, call=None, imo=None, typ=None, dest=None, draught=None, eta=None,
              fix=None, dims=(None, None, None, None)):
    return (mmsi, ts_ms, name, call, imo, typ, dest, draught, eta, fix, dims[0], dims[1], dims[2], dims[3], rx, "ws",
            msg_id, SOURCE)


def _loc_row(mmsi, t, body, md, rx, msg_id, nav=None, rot=None):
    lat = _num(body.get("Latitude"))
    lon = _num(body.get("Longitude"))
    if lat is None:
        lat = _num(md.get("Latitude", md.get("latitude")))
    if lon is None:
        lon = _num(md.get("Longitude", md.get("longitude")))
    return (mmsi, t, lat, lon, _num(body.get("Sog")), _num(body.get("Cog")), _int(body.get("TrueHeading"), -32768, 32767),
            nav, rot, _bool(body.get("PositionAccuracy")), _bool(body.get("Raim")), rx, msg_id,
            _bool(body.get("Valid")), _text(md.get("ShipName")), SOURCE)


def parse_message(obj, rx_ms):
    """One decoded aisstream message -> dict(kind=..., loc=row|None, meta=row|None, ...).

    kind: 'position', 'static', 'position+static', 'confirm' (with compression), 'error' (with text), 'other'
    (a type we don't store), 'bad' (malformed)."""
    if not isinstance(obj, dict):
        return {"kind": "bad"}
    mt = obj.get("MessageType")
    if mt == "SubscriptionConfirmation":
        return {"kind": "confirm", "compression": (obj.get("Message") or {}).get("CompressionEnabled")}
    if mt is None and ("error" in obj or "Error" in obj):
        return {"kind": "error", "text": str(obj.get("error", obj.get("Error")))[:300]}
    if mt not in MSG_IDS:
        return {"kind": "other", "type": str(mt)[:60]}
    body = (obj.get("Message") or {}).get(mt)
    md = obj.get("MetaData") or {}
    if not isinstance(body, dict) or not isinstance(md, dict):
        return {"kind": "bad"}
    mmsi = _int(body.get("UserID"), 1, 999_999_999) or _int(md.get("MMSI"), 1, 999_999_999)
    if mmsi is None:
        return {"kind": "bad"}
    base = meta_time_s(md)
    base = rx_ms / 1000 if base is None else base
    ts_ms = int(base * 1000)
    msg_id = _int(body.get("MessageID"), 0, 127) or MSG_IDS[mt]
    if mt == "PositionReport":
        t = position_time(base, body.get("Timestamp"))
        row = _loc_row(mmsi, t, body, md, rx_ms, msg_id, nav=_int(body.get("NavigationalStatus"), -128, 127),
                       rot=_int(body.get("RateOfTurn"), -32768, 32767))
        return {"kind": "position", "mmsi": mmsi, "loc": row, "meta": None}
    if mt == "StandardClassBPositionReport":
        t = position_time(base, body.get("Timestamp"))
        return {"kind": "position", "mmsi": mmsi, "loc": _loc_row(mmsi, t, body, md, rx_ms, msg_id), "meta": None}
    if mt == "ExtendedClassBPositionReport":
        t = position_time(base, body.get("Timestamp"))
        typ = _int(body.get("Type"), 0, 255)
        meta = _meta_row(mmsi, ts_ms, rx_ms, msg_id, name=_text(body.get("Name")), typ=typ or None,
                         fix=_int(body.get("FixType"), -128, 127), dims=_dims(body.get("Dimension")))
        return {"kind": "position+static", "mmsi": mmsi, "type": typ or None, "loc": _loc_row(mmsi, t, body, md, rx_ms, msg_id),
                "meta": meta}
    if mt == "ShipStaticData":
        typ = _int(body.get("Type"), 0, 255)
        imo = _int(body.get("ImoNumber"), 1, 2**31 - 1)
        dr = _num(body.get("MaximumStaticDraught"))
        meta = _meta_row(mmsi, ts_ms, rx_ms, msg_id, name=_text(body.get("Name")), call=_text(body.get("CallSign")),
                         imo=imo, typ=typ or None, dest=_text(body.get("Destination")),
                         draught=_int(round(dr * 10), 0, 32767) if dr is not None else None,
                         eta=pack_eta(body.get("Eta")), fix=_int(body.get("FixType"), -128, 127),
                         dims=_dims(body.get("Dimension")))
        return {"kind": "static", "mmsi": mmsi, "type": typ or None, "imo": imo, "loc": None, "meta": meta}
    # StaticDataReport (msg 24): part A carries the name, part B the type, call sign and dimensions
    if body.get("PartNumber"):
        rb = body.get("ReportB") or {}
        if rb.get("Valid") is False:
            return {"kind": "other", "type": "StaticDataReport-B-invalid"}
        typ = _int(rb.get("ShipType"), 0, 255)
        meta = _meta_row(mmsi, ts_ms, rx_ms, msg_id, call=_text(rb.get("CallSign")), typ=typ or None,
                         fix=_int(rb.get("FixType"), -128, 127), dims=_dims(rb.get("Dimension")))
        return {"kind": "static", "mmsi": mmsi, "type": typ or None, "loc": None, "meta": meta}
    ra = body.get("ReportA") or {}
    if ra.get("Valid") is False:
        return {"kind": "other", "type": "StaticDataReport-A-invalid"}
    return {"kind": "static", "mmsi": mmsi, "loc": None, "meta": _meta_row(mmsi, ts_ms, rx_ms, msg_id, name=_text(ra.get("Name")))}


def decode_frame(frame):
    """A WebSocket frame (bytes or str) -> JSON object."""
    if isinstance(frame, (bytes, bytearray, memoryview)):
        frame = bytes(frame).decode("utf-8")
    return json.loads(frame)


# ----------------------------------------------------------------------------------------------- disk
def write_part(out, day, kind, rows, keys, schema):
    """One flush's rows as a new Parquet part (atomic rename), so a crash never corrupts earlier data."""
    if not rows:
        return
    d = os.path.join(out, day)
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


def compact(out, day, kind, schema, drop_mmsi=frozenset()):
    """Merge a day's parts (and any earlier merged file) into <day>/<kind>.parquet, dropping rows of drop_mmsi
    (private craft), then delete the parts. Returns the merged row count."""
    import pyarrow.compute as pc
    d = os.path.join(out, day)
    parts = sorted(glob.glob(os.path.join(d, f"{kind}-*.parquet")))
    merged = os.path.join(d, f"{kind}.parquet")
    if not parts and not (drop_mmsi and os.path.exists(merged)):
        return 0
    srcs = ([merged] if os.path.exists(merged) else []) + parts
    tables = []
    for p in srcs:
        try:
            tables.append(pq.read_table(p).cast(schema))
        except Exception as e:  # a damaged part is kept aside, never silently dropped
            log(f"compact: cannot read {os.path.basename(p)} ({err_text(e)}); renamed to .bad")
            os.replace(p, p + ".bad")
            if p in parts:
                parts.remove(p)
    if not tables:
        return 0
    t = pa.concat_tables(tables)
    if drop_mmsi:
        t = t.filter(pc.invert(pc.is_in(t["mmsi"], value_set=pa.array(sorted(drop_mmsi), pa.int32()))))
    t = t.sort_by([("mmsi", "ascending"), ("time" if kind == "locations" else "rx_ms", "ascending")])
    tmp = merged + ".tmp"
    pq.write_table(t, tmp, compression="zstd", row_group_size=500_000)
    os.replace(tmp, merged)
    for p in parts:
        os.remove(p)
    return t.num_rows


def day_private_mmsi(out, day, exempt_mmsi=frozenset(), exempt_imo=frozenset()):
    """MMSIs whose static data on this day says pleasure craft, minus exempt vessels."""
    import pyarrow.compute as pc
    found, imo_of = set(), {}
    for p in glob.glob(os.path.join(out, day, "metadata*.parquet")):
        try:
            t = pq.read_table(p, columns=["mmsi", "type", "imo"])
        except Exception:
            continue
        for m, ty, im in zip(t["mmsi"].to_pylist(), t["type"].to_pylist(), t["imo"].to_pylist()):
            if im:
                imo_of[m] = im
            if ty in PRIVATE_TYPES:
                found.add(m)
    return {m for m in found if m not in exempt_mmsi and imo_of.get(m) not in exempt_imo}


# ----------------------------------------------------------------------------------------------- collector
class Stream:
    """One aisstream connection and its subscription."""

    def __init__(self, name, boxes, types, mmsi=None, stale_s=STALE_S):
        self.name, self.boxes, self.types, self.mmsi, self.stale_s = name, boxes, types, mmsi, stale_s
        self.ws = None
        self.confirmed = False
        self.ever_confirmed = False
        self.compression = None
        self.subscribed_at = 0.0
        self.connected_since = 0.0
        self.last_msg = 0.0
        self.backoff, self.next_try = 5.0, 0.0
        self.connects = 0
        self.unconfirmed = 0           # consecutive attempts never confirmed (only counts before the first success)

    def info(self):
        return {"name": self.name, "boxes": len(self.boxes), "types": self.types, "mmsi_filters": len(self.mmsi or []),
                "connected": self.ws is not None, "confirmed": self.confirmed, "compression": self.compression,
                "connects": self.connects, "last_message_utc": iso(self.last_msg * 1000) if self.last_msg else None}


class Collector:
    def __init__(self, args, key, streams, connect=None):
        self.args, self.streams = args, streams
        self._key = key                       # private: never logged, never in status
        self.out = args.out
        self.connect_fn = connect
        self.loc, self.meta = {}, {}          # day -> rows
        self.counts = {"position": 0, "static": 0, "confirm": 0, "error": 0, "other": 0, "bad": 0,
                       "dropped_private": 0, "flushes": 0}
        self.stop = False
        self.fatal = None
        self.started = utcnow()
        self.days_seen = set()
        self.exempt_mmsi, self.exempt_imo = set(), set()
        self.exempt_day = None
        self.private = self._load_private()   # mmsi -> last seen day (pleasure craft; dropped)

    # private-craft bookkeeping
    def _private_path(self):
        return os.path.join(self.out, "private_craft.json")

    def _load_private(self):
        try:
            with open(self._private_path(), encoding="utf-8") as f:
                d = json.load(f)
            return {int(k): v for k, v in d.get("mmsi", {}).items()}
        except (OSError, ValueError, AttributeError):
            return {}

    def _save_private(self):
        cut = datetime.fromtimestamp(time.time() - PRIVATE_KEEP_DAYS * 86400, timezone.utc).strftime("%Y-%m-%d")
        self.private = {m: d for m, d in self.private.items() if d >= cut}
        os.makedirs(self.out, exist_ok=True)
        tmp = self._private_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"_about": "MMSIs whose static data said AIS type 37 (pleasure craft); their rows are dropped. "
                                 "Private, gitignored.", "mmsi": {str(m): d for m, d in sorted(self.private.items())}}, f)
        os.replace(tmp, self._private_path())

    def refresh_exempt(self):
        day = utcnow().strftime("%Y-%m-%d")
        if day == self.exempt_day:
            return
        self.exempt_day = day
        wm, wi = load_watch_ids(self.args.watch_config)
        sm, si = load_sanctioned_ids(self.args.sanctioned)
        self.exempt_mmsi, self.exempt_imo = wm | sm, wi | si
        for m in list(self.private):
            if m in self.exempt_mmsi:
                del self.private[m]

    def note_type(self, res):
        typ, m = res.get("type"), res["mmsi"]
        if typ in PRIVATE_TYPES and m not in self.exempt_mmsi and res.get("imo") not in self.exempt_imo:
            self.private[m] = utcnow().strftime("%Y-%m-%d")
        elif typ is not None and typ not in PRIVATE_TYPES and m in self.private:
            del self.private[m]            # the MMSI now belongs to something else

    def handle(self, s, frame):
        rx = int(time.time() * 1000)
        s.last_msg = rx / 1000
        try:
            res = parse_message(decode_frame(frame), rx)
        except Exception:
            self.counts["bad"] += 1
            return
        k = res["kind"]
        if k == "confirm":
            self.counts["confirm"] += 1
            s.confirmed = s.ever_confirmed = True
            s.unconfirmed = 0
            s.compression = res.get("compression")
            log(f"{s.name}: subscription confirmed; compression {'on' if s.compression else 'OFF (bandwidth limits apply)'}")
            return
        if k == "error":
            self.counts["error"] += 1
            log(f"{s.name}: server error: {REDACT(res.get('text'))}")
            return
        if k in ("other", "bad"):
            self.counts[k] += 1
            return
        if not s.confirmed:                     # data flowing means the subscription was accepted
            s.confirmed = s.ever_confirmed = True
            s.unconfirmed = 0
        if "type" in res:
            self.note_type(res)
        if res["mmsi"] in self.private:
            self.counts["dropped_private"] += 1
            return
        day = day_of(rx)
        if res.get("loc"):
            self.loc.setdefault(day, []).append(res["loc"])
            self.counts["position"] += 1
        if res.get("meta"):
            self.meta.setdefault(day, []).append(res["meta"])
            self.counts["static"] += 1

    # connection management
    def _connect(self, url):
        if self.connect_fn:
            return self.connect_fn(url)
        from websockets.sync.client import connect
        return connect(url, compression="deflate", open_timeout=20, ping_interval=20, ping_timeout=30,
                       close_timeout=5, max_size=2 ** 22, max_queue=4096, user_agent_header="noise-floor")

    def retry_later(self, s, why):
        self.close(s)
        if not s.ever_confirmed:
            s.unconfirmed += 1
            if s.unconfirmed >= MAX_UNCONFIRMED:
                self.fatal = (f"{s.name}: {s.unconfirmed} attempts in a row without a confirmed subscription; "
                              "check the API key, the boxes and the connection limits (3 per account and per IP)")
        wait = s.backoff * random.uniform(0.75, 1.25)
        s.next_try = time.time() + wait
        log(f"{s.name}: {REDACT(why)}; next attempt in {wait:.0f} s")
        s.backoff = min(s.backoff * 2, 300.0)

    def close(self, s):
        if s.ws is not None:
            try:
                s.ws.close()
            except Exception:
                pass
        s.ws = None
        s.confirmed = False

    def open(self, s):
        s.connects += 1
        if s.connects > 1:
            log(f"{s.name}: reconnecting")
        try:
            s.ws = self._connect(self.args.url)
            # aisstream closes a connection that is not subscribed within 3 s: send at once
            s.ws.send(subscription(self._key, s.boxes, s.types, s.mmsi))
        except Exception as e:
            self.retry_later(s, f"connect failed: {err_text(e)}")
            return
        s.subscribed_at = s.connected_since = s.last_msg = time.time()
        log(f"{s.name}: connected; subscribed to {len(s.boxes)} box(es)"
            + (f", {len(s.mmsi)} MMSI filter(s)" if s.mmsi else ""))

    def pump(self, s, timeout):
        """Read what is waiting on one stream (block up to timeout for the first frame). Returns frames read."""
        n = 0
        t_end = time.time() + 0.5
        while s.ws is not None and n < 20000:
            try:
                frame = s.ws.recv(timeout=timeout if n == 0 else 0)
            except TimeoutError:
                break
            except Exception as e:                       # closed by the server or the network (code and reason in e)
                self.retry_later(s, f"connection closed ({err_text(e)})")
                break
            self.handle(s, frame)
            n += 1
            if time.time() > t_end:
                break
        return n

    def watchdog(self, s):
        now = time.time()
        if s.ws is None:
            return
        if not s.confirmed and now - s.subscribed_at > CONFIRM_S:
            self.retry_later(s, f"no subscription confirmation within {CONFIRM_S} s (invalid key or subscription?)")
        elif s.confirmed and now - s.last_msg > s.stale_s:
            self.retry_later(s, f"no messages for {s.stale_s} s; dropped the connection")
        elif s.backoff > 5 and s.confirmed and now - s.connected_since > 120:
            s.backoff = 5.0

    # flushing
    def flush(self, final=False):
        today = utcnow().strftime("%Y-%m-%d")
        for day in sorted(set(self.loc) | set(self.meta)):
            for kind, buf, keys, schema in (("locations", self.loc, LOC_KEYS, LOC_SCHEMA),
                                            ("metadata", self.meta, META_KEYS, META_SCHEMA)):
                rows = [r for r in buf.get(day, []) if r[0] not in self.private]
                self.counts["dropped_private"] += len(buf.get(day, [])) - len(rows)
                try:
                    write_part(self.out, day, kind, rows, keys, schema)
                    buf.pop(day, None)
                except Exception as e:          # keep the rows in memory and try again next flush
                    log(f"write failed for {day} {kind}: {err_text(e)}")
            self.days_seen.add(day)
        self.counts["flushes"] += 1
        for day in sorted(self.days_seen):
            if day < today or final:
                try:
                    drop = day_private_mmsi(self.out, day, self.exempt_mmsi, self.exempt_imo)
                    drop |= {m for m in self.private if m not in self.exempt_mmsi}
                    n = compact(self.out, day, "locations", LOC_SCHEMA, drop)
                    compact(self.out, day, "metadata", META_SCHEMA, drop)
                except Exception as e:
                    log(f"compaction failed for {day}: {err_text(e)}")
                    continue
                if n:
                    log(f"compacted {day}: {n} location rows")
                if day < today:
                    self.days_seen.discard(day)
        try:
            self._save_private()
        except OSError as e:
            log(f"private-craft list not saved: {err_text(e)}")
        self.write_status(final)

    def write_status(self, final=False):
        st = {"pid": os.getpid(), "started_utc": self.started.strftime("%Y-%m-%dT%H:%M:%SZ"), "now_utc": iso(),
              "running": not final, "streams": [s.info() for s in self.streams], "counts": self.counts,
              "private_craft_known": len(self.private), "fatal": self.fatal,
              "source": "aisstream.io (PRIVATE: no published terms; never publish)"}
        os.makedirs(self.out, exist_ok=True)
        tmp = os.path.join(self.out, "status.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(REDACT(json.dumps(st, indent=1)))
        os.replace(tmp, os.path.join(self.out, "status.json"))

    def run(self):
        a = self.args
        deadline = time.time() + a.hours * 3600 if a.hours else None
        stopfile = os.path.join(self.out, "STOP")
        os.makedirs(self.out, exist_ok=True)
        if os.path.exists(stopfile):
            os.remove(stopfile)
        next_flush = time.time() + a.flush_min * 60
        self.refresh_exempt()
        self.write_status()
        log(f"start: pid {os.getpid()}, hours {a.hours or 'unlimited'}, flush every {a.flush_min} min, "
            f"{len(self.streams)} stream(s) -> {self.out}")
        try:
            while not self.stop:
                now = time.time()
                if deadline and now >= deadline:
                    log("time limit reached")
                    break
                if os.path.exists(stopfile):
                    log("STOP file found")
                    break
                if self.fatal:
                    log(f"giving up: {self.fatal}")
                    break
                live = 0
                for s in self.streams:
                    if s.ws is None and time.time() >= s.next_try:
                        self.open(s)
                    if s.ws is not None:
                        live += 1
                got = 0
                for s in self.streams:
                    if s.ws is not None:
                        got += self.pump(s, 1.0 if live == 1 else 0)
                    self.watchdog(s)
                if live == 0 or (live > 1 and got == 0):
                    time.sleep(0.5 if live == 0 else 0.05)
                if time.time() >= next_flush:
                    self.refresh_exempt()
                    self.flush()
                    next_flush = time.time() + a.flush_min * 60
                    log(f"flush: {self.counts['position']} positions, {self.counts['static']} static so far; "
                        f"connected={[s.ws is not None for s in self.streams]}")
        finally:
            self.stop = True
            for s in self.streams:
                self.close(s)
            self.flush(final=True)
            if os.path.exists(stopfile):
                os.remove(stopfile)
            log(f"stopped: {self.counts}")
        return 2 if self.fatal else 0


def build_streams(args):
    boxes = []
    if args.box and not args.add_box:
        boxes = [("box", parse_box(b)) for b in args.box]
    else:
        if args.global_:
            boxes = [("world", [-90.0, 90.0, -180.0, 180.0])]
        else:
            boxes = load_boxes(args.watch_config, args.areas.split(",") if args.areas else None)
        boxes += [("box", parse_box(b)) for b in (args.box or [])]
    if not boxes:
        raise SystemExit("no bounding boxes: add focus areas to the private maritime config, or pass --box")
    types = args.types.split(",") if args.types else TYPES
    bad = [t for t in types if t not in MSG_IDS]
    if bad:
        raise SystemExit(f"unsupported message type(s): {', '.join(bad)} (stored types: {', '.join(MSG_IDS)})")
    streams = [Stream("focus", [b for _, b in boxes], types)]
    if args.watch_global:
        mm, _ = load_watch_ids(args.watch_config)
        if not mm:
            log("--watch-global: the watch list has no MMSIs (IMO-only entries can't be filtered); skipped")
        else:
            if len(mm) > MAX_MMSI:
                log(f"--watch-global: {len(mm)} MMSIs on the watch list; aisstream takes {MAX_MMSI}, the rest are skipped")
            streams.append(Stream("watch", [[-90.0, 90.0, -180.0, 180.0]], types, mmsi=sorted(mm)[:MAX_MMSI],
                                  stale_s=STALE_WATCH_S))
    return streams, [aid for aid, _ in boxes]


def main(argv=None):
    global LOG_PATH
    install_redaction()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--hours", type=float, default=0, help="stop after N hours (default: run until stopped)")
    ap.add_argument("--flush-min", type=float, default=5, help="minutes between flushes to disk (default 5)")
    ap.add_argument("--areas", help="comma-separated focus-area ids from the private config (default: all but candidates)")
    ap.add_argument("--box", action="append", help="lat0,lat1,lon0,lon1 (repeatable); replaces the config boxes "
                                                   "unless --add-box is given")
    ap.add_argument("--add-box", action="store_true", help="add the --box boxes to the config boxes")
    ap.add_argument("--global", dest="global_", action="store_true",
                    help="the whole world instead of the focus areas (large: check disk space)")
    ap.add_argument("--watch-global", action="store_true",
                    help="a second connection: the watch list's MMSIs anywhere in the world")
    ap.add_argument("--types", help=f"comma-separated message types (default: {','.join(TYPES)})")
    ap.add_argument("--watch-config", default=WATCH_CONFIG, help="private maritime config (focus areas, watch list)")
    ap.add_argument("--sanctioned", default=SANCTIONED, help="sanctioned-vessel list (exempt from the private-craft drop)")
    ap.add_argument("--url", default=URL, help=argparse.SUPPRESS)          # tests: a local mock server
    ap.add_argument("--dry-run", action="store_true", help="print the subscription (key redacted) and exit")
    ap.add_argument("--compact-only", action="store_true", help="merge leftover parts for every day, then exit")
    ap.add_argument("--log", default=None, help="log file as well as stderr (default <out>/collector.log; '' for none)")
    ap.add_argument("--out", default=OUT, help="output folder (default data/ais/aisstream)")
    args = ap.parse_args(argv)
    args.out = os.path.abspath(args.out)
    if args.log is None:
        args.log = os.path.join(args.out, "collector.log")
    if args.log:
        os.makedirs(os.path.dirname(os.path.abspath(args.log)), exist_ok=True)
        LOG_PATH = args.log
    if args.compact_only:
        wm, wi = load_watch_ids(args.watch_config)
        sm, si = load_sanctioned_ids(args.sanctioned)
        for d in sorted(glob.glob(os.path.join(args.out, "????-??-??"))):
            day = os.path.basename(d)
            drop = day_private_mmsi(args.out, day, wm | sm, wi | si)
            n = compact(args.out, day, "locations", LOC_SCHEMA, drop)
            compact(args.out, day, "metadata", META_SCHEMA, drop)
            print(day, n)
        return 0
    streams, area_ids = build_streams(args)
    key = get_api_key()
    if key:
        REDACT.add(key)
    if args.dry_run:
        print(f"areas: {', '.join(area_ids)}")
        for s in streams:
            print(f"{s.name}: {describe_subscription(subscription('x' * 8, s.boxes, s.types, s.mmsi))}")
        print(f"API key: {'found' if key else 'NOT FOUND'} ({KEY_ENV})")
        return 0
    if not key:
        log(f"no API key: set the {KEY_ENV} user environment variable (see the private aisstream handoff note)")
        return 3
    c = Collector(args, key, streams)

    def handler(signum, frame):
        log(f"signal {signum}: stopping")
        c.stop = True
    for sname in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, sname):
            signal.signal(getattr(signal, sname), handler)
    return c.run()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as e:            # last line of defence: nothing unredacted reaches the console
        sys.stderr.write(REDACT("".join(traceback.format_exception(type(e), e, e.__traceback__))))
        sys.exit(1)
