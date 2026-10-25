"""Offline tests for collectors/aisstream_ais.py: the parser on synthetic messages in aisstream's documented shapes,
key redaction (the key must never reach a log, status file, exception text or data file), box loading from a temporary
config, the collection loop on a fake connection, and the output read back by tools/ais_detect.py. Plain script, as CI
runs it (requirements.txt + nisar/requirements.txt; no network). `websockets` is imported lazily: when it is
installed, a last test replays messages from a local mock server (127.0.0.1 only); otherwise that test is skipped."""
import io, json, os, shutil, sys, tempfile, threading, time, urllib.parse
from contextlib import redirect_stderr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "collectors"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import aisstream_ais as S  # noqa: E402

KEY = "k3yTEST0123456789abcdefFAKE"          # a fake key; it must never appear in any output
RX = 1_792_892_400_000                       # 2026-10-25 01:40:00 UTC, in ms


def pos_msg(mmsi=273123456, lat=59.9, lon=29.1, ts=55, meta_time=True, lower=False, mt="PositionReport"):
    body = {"MessageID": 1 if mt == "PositionReport" else 18, "RepeatIndicator": 0, "UserID": mmsi, "Valid": True,
            "Sog": 11.3, "PositionAccuracy": True, "Longitude": lon, "Latitude": lat, "Cog": 87.5, "TrueHeading": 90,
            "Timestamp": ts, "Raim": False, "CommunicationState": 0}
    if mt == "PositionReport":
        body.update({"NavigationalStatus": 0, "RateOfTurn": -2, "SpecialManoeuvreIndicator": 0, "Spare": 0})
    md = {"MMSI": mmsi, "ShipName": "TEST VESSEL@@@ "}
    md.update({"latitude": lat, "longitude": lon} if lower else {"Latitude": lat, "Longitude": lon})
    if meta_time:
        md["time_utc"] = "2026-10-25 01:40:02.123456789 +0000 UTC"
    return {"MessageType": mt, "MetaData": md, "Message": {mt: body}}


def static_msg(mmsi=273123456, typ=80, imo=9074729, name="TEST TANKER"):
    return {"MessageType": "ShipStaticData", "MetaData": {"MMSI": mmsi, "ShipName": name},
            "Message": {"ShipStaticData": {
                "MessageID": 5, "RepeatIndicator": 0, "UserID": mmsi, "Valid": True, "AisVersion": 1, "ImoNumber": imo,
                "CallSign": "UBCD7  ", "Name": name + "@@@@", "Type": typ, "Dimension": {"A": 200, "B": 44, "C": 20, "D": 22},
                "FixType": 1, "Eta": {"Month": 10, "Day": 27, "Hour": 14, "Minute": 30}, "MaximumStaticDraught": 12.4,
                "Destination": "PRIMORSK@@@", "Dte": False, "Spare": False}}}


def test_parser():
    r = S.parse_message(pos_msg(), RX)
    assert r["kind"] == "position" and r["meta"] is None
    row = dict(zip(S.LOC_KEYS, r["loc"]))
    # time_utc 01:40:02, report second 55 -> the previous minute's :55 = 01:39:55
    assert row["time"] == 1_792_892_395, row["time"]
    assert row["mmsi"] == 273123456 and row["lat"] == 59.9 and row["lon"] == 29.1 and row["sog"] == 11.3
    assert row["navStat"] == 0 and row["rot"] == -2 and row["posAcc"] is True and row["raim"] is False
    assert row["msg_id"] == 1 and row["source"] == "aisstream" and row["meta_name"] == "TEST VESSEL" and row["rx_ms"] == RX
    # no time_utc: our receive time is the base; lower-case MetaData keys are accepted as a position fallback
    m = pos_msg(ts=60, meta_time=False, lower=True)
    del m["Message"]["PositionReport"]["Latitude"]
    row = dict(zip(S.LOC_KEYS, S.parse_message(m, RX)["loc"]))
    assert row["time"] == RX // 1000 and row["lat"] == 59.9
    # class B: no navigational status or rate of turn
    row = dict(zip(S.LOC_KEYS, S.parse_message(pos_msg(mt="StandardClassBPositionReport"), RX)["loc"]))
    assert row["msg_id"] == 18 and row["navStat"] is None and row["rot"] is None
    # ship static data: draught in tenths, ETA packed as Digitraffic does, padding stripped
    r = S.parse_message(static_msg(), RX)
    assert r["kind"] == "static" and r["type"] == 80 and r["imo"] == 9074729 and r["loc"] is None
    meta = dict(zip(S.META_KEYS, r["meta"]))
    assert meta["name"] == "TEST TANKER" and meta["callSign"] == "UBCD7" and meta["destination"] == "PRIMORSK"
    assert meta["draught"] == 124 and meta["eta"] == (10 << 16 | 27 << 11 | 14 << 6 | 30) and meta["type"] == 80
    assert (meta["refA"], meta["refB"], meta["refC"], meta["refD"]) == (200, 44, 20, 22) and meta["posType"] == 1
    assert meta["src"] == "ws" and meta["msg_id"] == 5 and meta["timestamp"] == RX      # no time_utc: receive time
    # extended class B: a position and an identity in one message
    ext = {"MessageType": "ExtendedClassBPositionReport", "MetaData": {"MMSI": 412000111},
           "Message": {"ExtendedClassBPositionReport": {"MessageID": 19, "UserID": 412000111, "Valid": True, "Sog": 3.1,
                                                        "Longitude": 115.5, "Latitude": 9.9, "Cog": 10.0, "TrueHeading": 511,
                                                        "Timestamp": 7, "Name": "MIN SHA YU 01", "Type": 30,
                                                        "Dimension": {"A": 20, "B": 10, "C": 3, "D": 3}, "FixType": 1,
                                                        "Raim": False, "Dte": True, "AssignedMode": False}}}
    r = S.parse_message(ext, RX)
    assert r["kind"] == "position+static" and r["type"] == 30
    assert dict(zip(S.LOC_KEYS, r["loc"]))["heading"] == 511 and dict(zip(S.META_KEYS, r["meta"]))["name"] == "MIN SHA YU 01"
    # static data report: part A (name) and part B (type, call sign, dimensions)
    a = {"MessageType": "StaticDataReport", "MetaData": {"MMSI": 412000222}, "Message": {"StaticDataReport": {
        "MessageID": 24, "UserID": 412000222, "Valid": True, "PartNumber": False, "ReportA": {"Valid": True, "Name": "HAI XUN 1"},
        "ReportB": {"Valid": False}}}}
    b = {"MessageType": "StaticDataReport", "MetaData": {"MMSI": 412000222}, "Message": {"StaticDataReport": {
        "MessageID": 24, "UserID": 412000222, "Valid": True, "PartNumber": True, "ReportA": {"Valid": False},
        "ReportB": {"Valid": True, "ShipType": 55, "CallSign": "BXYZ", "Dimension": {"A": 50, "B": 10, "C": 5, "D": 5},
                    "FixType": 1, "VendorIDName": "ABC", "VenderIDModel": 1, "VenderIDSerial": 2, "Spare": 0}}}}
    ma = dict(zip(S.META_KEYS, S.parse_message(a, RX)["meta"]))
    rb = S.parse_message(b, RX)
    mb = dict(zip(S.META_KEYS, rb["meta"]))
    assert ma["name"] == "HAI XUN 1" and ma["type"] is None and mb["type"] == 55 and mb["callSign"] == "BXYZ" and rb["type"] == 55
    # other message kinds
    assert S.parse_message({"MessageType": "SubscriptionConfirmation", "Message": {"CompressionEnabled": True}}, RX) == \
        {"kind": "confirm", "compression": True}
    assert S.parse_message({"error": "Api Key Is Not Valid"}, RX)["kind"] == "error"
    assert S.parse_message({"MessageType": "BaseStationReport", "Message": {"BaseStationReport": {}}}, RX)["kind"] == "other"
    assert S.parse_message({"MessageType": "PositionReport", "Message": {}}, RX)["kind"] == "bad"
    assert S.parse_message({"MessageType": "PositionReport", "MetaData": {}, "Message": {"PositionReport": {"UserID": 0}}}, RX)["kind"] == "bad"
    assert S.decode_frame(json.dumps(pos_msg()).encode("utf-8"))["MessageType"] == "PositionReport"


def test_times():
    assert S.meta_time_s({"time_utc": "2026-10-25 01:40:02.5 +0000 UTC"}) == 1_792_892_402.5
    assert S.meta_time_s({"time_utc": "2026-10-25T03:40:02+02:00"}) == 1_792_892_402
    assert S.meta_time_s({"time_utc": "2026-10-25T01:40:02Z"}) == 1_792_892_402
    assert S.meta_time_s({}) is None and S.meta_time_s({"time_utc": "garbage"}) is None
    b = 1_792_892_402                                       # :02 of a minute
    assert S.position_time(b, 1) == b - 1 and S.position_time(b, 4) == b + 2   # 2 s of clock slack allowed
    assert S.position_time(b, 30) == b - 32 and S.position_time(b, 60) == b and S.position_time(b, None) == b
    assert S.pack_eta({"Month": 0, "Day": 0, "Hour": 24, "Minute": 60}) == (24 << 6 | 60) and S.pack_eta(None) is None


def test_boxes():
    tmp = tempfile.mkdtemp()
    try:
        cfg = os.path.join(tmp, "maritime.json")
        json.dump({"focus_areas": [{"id": "a", "box": [1, 2, 103, 104]}, {"id": "b", "box": [10, 12, 114, 116]},
                                   {"id": "c", "box": [22, 26, 118, 122], "candidate": True}],
                   "vessel_watch": {"vessels": [{"mmsi": 273000001, "imo": "IMO 9074729", "reason": "test"}, {"imo": 9603972}]}},
                  open(cfg, "w"))
        assert S.load_boxes(cfg) == [("a", [1.0, 2.0, 103.0, 104.0]), ("b", [10.0, 12.0, 114.0, 116.0])]
        assert [a for a, _ in S.load_boxes(cfg, ["c", "a"])] == ["a", "c"]          # named candidates are included
        try:
            S.load_boxes(cfg, ["zz"]); raise AssertionError("unknown area accepted")
        except ValueError:
            pass
        assert S.load_boxes(os.path.join(tmp, "missing.json")) == []
        assert S.load_watch_ids(cfg) == ({273000001}, {9074729, 9603972})
        assert S.parse_box("1.5, 2, 103,104.5") == [1.5, 2.0, 103.0, 104.5]
        for bad in ("1,2,3", "95,96,1,2", "1,1,3,4", "a,b,c,d"):
            try:
                S.parse_box(bad); raise AssertionError(f"bad box accepted: {bad}")
            except ValueError:
                pass
        assert S.corners([2, 1, 103, 104]) == [[[1, 103], [2, 104]]]
        assert S.corners([50, 60, 170, -170]) == [[[50, 170], [60, 180.0]], [[50, -180.0], [60, -170]]]   # antimeridian
        sub = json.loads(S.subscription(KEY, [[1, 2, 103, 104]], S.TYPES, mmsi=list(range(1, 300))))
        assert sub["APIKey"] == KEY and sub["BoundingBoxes"] == [[[1, 103], [2, 104]]]
        assert len(sub["FiltersShipMMSI"]) == 200 and sub["FiltersShipMMSI"][0] == "000000001"
        assert sub["FilterMessageTypes"] == S.TYPES
        assert KEY not in S.describe_subscription(S.subscription(KEY, [[1, 2, 103, 104]]))
        # sanctions file layouts the collector exempts from the private-craft drop
        sp = os.path.join(tmp, "s.json")
        json.dump({"vessels": [{"imo": 9074729, "mmsi": [273000009]}, {"imo": "IMO9603972"}]}, open(sp, "w"))
        assert S.load_sanctioned_ids(sp) == ({273000009}, {9074729, 9603972})
        json.dump({"9074729": {"name": "X"}}, open(sp, "w"))
        assert S.load_sanctioned_ids(sp) == (set(), {9074729})
        assert S.load_sanctioned_ids(os.path.join(tmp, "none.json")) == (set(), set())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_redaction():
    tmp = tempfile.mkdtemp()
    old = S.LOG_PATH
    try:
        assert S.get_api_key({S.KEY_ENV: "  " + KEY + " "}) == KEY
        S.REDACT.add(KEY)
        S.LOG_PATH = os.path.join(tmp, "log.txt")
        err = io.StringIO()
        with redirect_stderr(err):
            S.log("sending", json.dumps({"APIKey": KEY}), "bare", KEY)
            try:
                raise RuntimeError(f"server said: bad key {KEY} in {{\"APIKey\": \"{KEY}\"}}")
            except RuntimeError as e:
                S.log("failed:", S.err_text(e))
                S._excepthook(type(e), e, e.__traceback__)
            S.log("url form", "https://x/?k=" + urllib.parse.quote(KEY))
        text = open(S.LOG_PATH, encoding="utf-8").read() + err.getvalue()
        assert KEY not in text and "[REDACTED]" in text, text
        assert "Traceback" in err.getvalue()          # the excepthook still shows where it failed
    finally:
        S.LOG_PATH = old
        shutil.rmtree(tmp, ignore_errors=True)


class FakeWS:
    """Stands in for a websockets client connection: replays frames, then times out like recv(timeout=...)."""

    def __init__(self, frames, fail_send=False):
        self.frames, self.sent, self.closed, self.fail_send = list(frames), [], False, fail_send

    def send(self, m):
        if self.fail_send:
            raise ConnectionError(f"refused while sending {m}")      # an error text that echoes the subscription
        self.sent.append(m)

    def recv(self, timeout=None):
        if self.frames:
            return self.frames.pop(0)
        time.sleep(min(timeout or 0, 0.05))
        raise TimeoutError

    def close(self):
        self.closed = True


def run_fake(out, cfg, frames, hours=0.0004, fail_send=False):
    conns = []

    def connect(url):
        ws = FakeWS(frames if not conns else [], fail_send=fail_send)
        conns.append(ws)
        return ws
    args = S.argparse.Namespace(out=out, hours=hours, flush_min=5, watch_config=cfg,
                                sanctioned=os.path.join(out, "none.json"), url="ws://fake")
    S.REDACT.add(KEY)
    c = S.Collector(args, KEY, [S.Stream("focus", [[1, 2, 103, 104]], S.TYPES)], connect=connect)
    err = io.StringIO()
    with redirect_stderr(err):
        rc = c.run()
    return c, conns, rc, err.getvalue()


def test_collector_fake_connection():
    import pyarrow.parquet as pq
    tmp = tempfile.mkdtemp()
    old = S.LOG_PATH
    try:
        cfg = os.path.join(tmp, "maritime.json")
        json.dump({"focus_areas": [], "vessel_watch": {"vessels": [{"mmsi": 538000777}]}}, open(cfg, "w"))
        out = os.path.join(tmp, "ais")
        S.LOG_PATH = os.path.join(out, "collector.log")
        os.makedirs(out)
        yacht = 235000037
        frames = [json.dumps({"MessageType": "SubscriptionConfirmation", "Message": {"CompressionEnabled": True}}).encode(),
                  json.dumps(pos_msg(yacht)).encode(),                         # before its static data: dropped at compaction
                  json.dumps(static_msg(yacht, typ=37, imo=0, name="PRIVATE YACHT")).encode(),
                  json.dumps(pos_msg(yacht)).encode(),                         # after: dropped before disk
                  json.dumps(static_msg(538000777, typ=37, imo=0, name="WATCHED YACHT")).encode(),   # watch list: kept
                  json.dumps(pos_msg(538000777)).encode(),
                  json.dumps(static_msg()).encode(), json.dumps(pos_msg()).encode(), json.dumps(pos_msg(lat=59.95)).encode(),
                  b"not json", json.dumps({"MessageType": "AidsToNavigationReport", "Message": {}}).encode()]
        c, conns, rc, err = run_fake(out, cfg, frames)
        assert rc == 0 and len(conns) == 1 and conns[0].closed
        sub = json.loads(conns[0].sent[0])
        assert sub["APIKey"] == KEY and sub["BoundingBoxes"] == [[[1, 103], [2, 104]]]
        assert c.counts["confirm"] == 1 and c.counts["bad"] == 1 and c.counts["other"] == 1
        assert c.counts["dropped_private"] >= 1 and yacht in c.private and 538000777 not in c.private
        day = sorted(d for d in os.listdir(out) if d[:2] == "20")[0]          # today's UTC receive day
        loc = pq.read_table(os.path.join(out, day, "locations.parquet"))
        meta = pq.read_table(os.path.join(out, day, "metadata.parquet"))
        assert yacht not in loc["mmsi"].to_pylist() and yacht not in meta["mmsi"].to_pylist()
        assert sorted(set(loc["mmsi"].to_pylist())) == [273123456, 538000777] and loc.num_rows == 3
        assert not [p for p in os.listdir(os.path.join(out, day)) if p.startswith("locations-")]      # parts merged
        st = json.load(open(os.path.join(out, "status.json")))
        assert st["running"] is False and st["streams"][0]["confirmed"] is False and st["counts"]["position"] == 4   # 1 dropped at flush
        # the key is in no file the collector wrote, and not on stderr
        for dp, _, fs in os.walk(out):
            for f in fs:
                assert KEY.encode() not in open(os.path.join(dp, f), "rb").read(), f
        assert KEY not in err
        # tools/ais_detect.py reads the same columns
        import ais_detect as A
        A.AIS_DIR = out
        L, stats, _ = A.load_locations([day])
        assert stats["rows"] == 3 and set(L["mmsi"].tolist()) == {273123456, 538000777}
        M = A.load_metadata([day])
        assert M[273123456]["imo"] == 9074729 and M[273123456]["type"] == 80 and M[273123456]["draught"] == 124

        # a failing send whose error text echoes the subscription: retried, and the key is redacted everywhere
        out2 = os.path.join(tmp, "ais2")
        os.makedirs(out2)
        S.LOG_PATH = os.path.join(out2, "collector.log")
        c, conns, rc, err = run_fake(out2, cfg, [], hours=0.0003, fail_send=True)
        assert conns and "connect failed" in err and "[REDACTED]" in err and KEY not in err
        assert KEY not in open(S.LOG_PATH, encoding="utf-8").read()

        # compaction drops a pleasure craft's rows written before its static data arrived
        out3 = os.path.join(tmp, "ais3")
        rows = [S.parse_message(pos_msg(yacht), RX)["loc"], S.parse_message(pos_msg(), RX)["loc"]]
        S.write_part(out3, "2026-10-25", "locations", rows, S.LOC_KEYS, S.LOC_SCHEMA)
        S.write_part(out3, "2026-10-25", "metadata", [S.parse_message(static_msg(yacht, typ=37, imo=0), RX)["meta"]],
                     S.META_KEYS, S.META_SCHEMA)
        drop = S.day_private_mmsi(out3, "2026-10-25")
        assert drop == {yacht} and S.day_private_mmsi(out3, "2026-10-25", exempt_mmsi={yacht}) == set()
        assert S.compact(out3, "2026-10-25", "locations", S.LOC_SCHEMA, drop) == 1
        assert S.compact(out3, "2026-10-25", "metadata", S.META_SCHEMA, drop) == 0
        assert pq.read_table(os.path.join(out3, "2026-10-25", "locations.parquet"))["mmsi"].to_pylist() == [273123456]
    finally:
        S.LOG_PATH = old
        shutil.rmtree(tmp, ignore_errors=True)


def test_watchdogs():
    """No confirmation and no data -> retry; confirmed but silent -> reconnect; repeated failures -> give up."""
    tmp = tempfile.mkdtemp()
    old = (S.LOG_PATH, S.CONFIRM_S, S.MAX_UNCONFIRMED)
    try:
        cfg = os.path.join(tmp, "maritime.json")
        json.dump({"focus_areas": []}, open(cfg, "w"))
        S.LOG_PATH = None
        S.CONFIRM_S = 0.3
        out = os.path.join(tmp, "a")
        os.makedirs(out)
        c, conns, rc, err = run_fake(out, cfg, [], hours=0.0003)
        assert "no subscription confirmation within 0.3 s" in err and c.streams[0].unconfirmed == 1, err
        S.MAX_UNCONFIRMED = 1
        out = os.path.join(tmp, "b")
        os.makedirs(out)
        c, conns, rc, err = run_fake(out, cfg, [], hours=0.003)
        assert rc == 2 and "giving up" in err and c.fatal, err
        assert json.load(open(os.path.join(out, "status.json")))["fatal"]
        S.CONFIRM_S, S.MAX_UNCONFIRMED = old[1], old[2]
        out = os.path.join(tmp, "c")
        os.makedirs(out)
        conf = json.dumps({"MessageType": "SubscriptionConfirmation", "Message": {"CompressionEnabled": True}}).encode()
        args = S.argparse.Namespace(out=out, hours=0.0003, flush_min=5, watch_config=cfg, sanctioned="none", url="x")
        st = S.Stream("focus", [[1, 2, 103, 104]], S.TYPES, stale_s=0.3)
        c = S.Collector(args, KEY, [st], connect=lambda url: FakeWS([conf]))
        e = io.StringIO()
        with redirect_stderr(e):
            assert c.run() == 0
        assert "no messages for 0.3 s; dropped the connection" in e.getvalue() and st.ever_confirmed, e.getvalue()
    finally:
        S.LOG_PATH, S.CONFIRM_S, S.MAX_UNCONFIRMED = old
        shutil.rmtree(tmp, ignore_errors=True)


def test_mock_server():
    """End to end through a real WebSocket on 127.0.0.1 (needs `websockets`; skipped without it)."""
    try:
        from websockets.sync.server import serve
    except ImportError:
        print("skip test_mock_server: websockets not installed")
        return
    import pyarrow.parquet as pq
    got = {}

    def handler(ws):
        t0 = time.time()
        sub = json.loads(ws.recv(timeout=3))          # aisstream: subscribe within 3 s or the connection closes
        got["sub"], got["delay"] = sub, time.time() - t0
        got["deflate"] = any("deflate" in type(e).__name__.lower() for e in ws.protocol.extensions)
        if sub.get("APIKey") != KEY:
            ws.close(1008, f"invalid key {sub.get('APIKey')}")       # echoes the key, as a careless server might
            return
        ws.send(json.dumps({"MessageType": "SubscriptionConfirmation", "Message": {"CompressionEnabled": got["deflate"]}}).encode())
        for m in (static_msg(), pos_msg(), pos_msg(lat=59.91), pos_msg(mt="StandardClassBPositionReport", mmsi=412000333)):
            ws.send(json.dumps(m).encode("utf-8"))            # binary frames of UTF-8 JSON, as documented
        try:
            for _ in ws:
                pass
        except Exception:
            pass

    tmp = tempfile.mkdtemp()
    old_env = os.environ.get(S.KEY_ENV)
    try:
        cfg = os.path.join(tmp, "maritime.json")
        json.dump({"focus_areas": [{"id": "x", "box": [59, 61, 28, 31]}]}, open(cfg, "w"))
        with serve(handler, "127.0.0.1", 0, compression="deflate") as server:
            port = server.socket.getsockname()[1]
            th = threading.Thread(target=server.serve_forever, daemon=True)
            th.start()
            out = os.path.join(tmp, "ais")
            os.environ[S.KEY_ENV] = KEY
            err = io.StringIO()
            with redirect_stderr(err):
                rc = S.main(["--url", f"ws://127.0.0.1:{port}", "--hours", "0.0008", "--out", out, "--watch-config", cfg])
            # wrong key: the server closes with a reason that contains the (wrong) key; the log must redact it
            out_bad = os.path.join(tmp, "bad")
            os.environ[S.KEY_ENV] = "wrongKEY987654321zz"
            err_bad = io.StringIO()
            with redirect_stderr(err_bad):
                S.main(["--url", f"ws://127.0.0.1:{port}", "--hours", "0.0004", "--out", out_bad, "--watch-config", cfg])
            server.shutdown()
        assert rc == 0, err.getvalue()
        assert got["deflate"] and got["delay"] < 3, got
        assert got["sub"]["BoundingBoxes"] == [[[59.0, 28.0], [61.0, 31.0]]] and got["sub"]["FilterMessageTypes"] == S.TYPES
        day = sorted(d for d in os.listdir(out) if d[:2] == "20")[0]
        loc = pq.read_table(os.path.join(out, day, "locations.parquet"))
        assert loc.num_rows == 3 and set(loc["source"].to_pylist()) == {"aisstream"}
        assert sorted(set(loc["msg_id"].to_pylist())) == [1, 18]
        st = json.load(open(os.path.join(out, "status.json")))
        assert st["streams"][0]["compression"] is True and st["counts"]["static"] == 1, st
        logs = err.getvalue() + open(os.path.join(out, "collector.log"), encoding="utf-8").read()
        assert "subscription confirmed; compression on" in logs and KEY not in logs
        bad_logs = err_bad.getvalue() + open(os.path.join(out_bad, "collector.log"), encoding="utf-8").read()
        assert "wrongKEY987654321zz" not in bad_logs and "connection closed" in bad_logs, bad_logs
        for d in (out, out_bad):
            for dp, _, fs in os.walk(d):
                for f in fs:
                    data = open(os.path.join(dp, f), "rb").read()
                    assert KEY.encode() not in data and b"wrongKEY987654321zz" not in data, f
    finally:
        if old_env is None:
            os.environ.pop(S.KEY_ENV, None)
        else:
            os.environ[S.KEY_ENV] = old_env
        S.LOG_PATH = None
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)


if __name__ == "__main__":
    main()
