"""Offline test for pipeline/pnt_daily.py (v1.1): a synthetic adsb.lol day split into two tar parts.

Run:  python tests/test_pnt_daily.py   (or pytest)
"""
import gzip, io, json, os, shutil, sys, tarfile, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import pnt_daily as P  # noqa: E402

DAY0 = 1760572800.0   # 2025-10-16T00:00:00Z
GOOD = {"version": 2, "nac_p": 10, "nic": 8}
BAD = {"version": 2, "nac_p": 0, "nic": 0}
FINE_BAD = {"version": 2, "nac_p": 9, "nic": 8}   # worse than 10 m, better than 93 m


def trace(icao, pts, kind="adsb_icao", typ="A320"):
    """pts: list of (t_seconds_after_day0, lat, lon, alt, details_or_None)."""
    return {"icao": icao, "timestamp": DAY0, "t": typ,
            "trace": [[t, la, lo, alt, 450.0, 90.0, 0, 0, det, kind, alt, None, None, None] for t, la, lo, alt, det in pts]}


def stay(t0, minutes, lat, lon, det, alt=35000):
    """One report a minute at a fixed point (circling inside one hex)."""
    return [(t0 + i * 60, lat, lon, alt, det if i == 0 else None) for i in range(minutes)]


def build_day(folder, day):
    q = (50.0, 10.0)      # quiet hex (central Europe)
    j = (59.3, 28.0)      # jammed hex (Estonia-Russia border)
    b = (55.0, 20.0)      # Baltic hex used for the threshold checks
    traces = {
        # Baltic hex, 20 min: 2 clean, 1 jammed, 1 fine-degraded; plus aircraft that must be ignored
        "aaaaa1": trace("aaaaa1", stay(0, 20, *b, GOOD)),
        "aaaaa2": trace("aaaaa2", stay(0, 20, *b, BAD)),
        "aaaaa3": trace("aaaaa3", stay(0, 20, *b, GOOD)),
        "aaaaa4": trace("aaaaa4", stay(0, 20, *b, FINE_BAD)),                               # NACp 9 all day: not capable
        "aaaaa5": trace("aaaaa5", stay(0, 10, *b, GOOD) + stay(600, 30, *b, FINE_BAD)),     # capable, then drops to 9
        "~bbbbb": trace("~bbbbb", stay(0, 20, *b, BAD)),                                    # non-ICAO
        "ccccc1": trace("ccccc1", stay(0, 20, *b, BAD), kind="mlat"),                       # MLAT
        "ccccc2": trace("ccccc2", stay(0, 20, *b, BAD, alt="ground")),                      # ground
        "ccccc3": trace("ccccc3", stay(0, 20, *b, {"version": 0, "nac_p": 0, "nic": 0})),   # ADS-B v0
        "ccccc4": trace("ccccc4", stay(86400, 20, *b, BAD)),                                # next UTC day
        # Quiet hex, 4 h: three clean peers and one faulty-avionics aircraft -> dropped as suspect
        "qqqqq1": trace("qqqqq1", stay(0, 240, *q, GOOD)),
        "qqqqq2": trace("qqqqq2", stay(0, 240, *q, GOOD)),
        "qqqqq3": trace("qqqqq3", stay(0, 240, *q, GOOD)),
        "qqqqq9": trace("qqqqq9", stay(0, 240, *q, BAD), typ="C42"),
        # Jammed hex, 4 h: everyone bad, including a long flight -> kept (v1 would have dropped it)
        "jjjjj1": trace("jjjjj1", stay(0, 240, *j, BAD)),
        "jjjjj2": trace("jjjjj2", stay(0, 240, *j, BAD)),
        "jjjjj3": trace("jjjjj3", stay(0, 240, *j, BAD)),
        "jjjjj9": trace("jjjjj9", stay(0, 240, *j, BAD)),
        # Lone faulty aircraft with no peers: kept, and the GPSJam formula keeps its hex at score 0
        "ddddd1": trace("ddddd1", stay(0, 300, 40.0, -100.0, BAD)),
    }
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        hm = tarfile.TarInfo("./heatmap/00.bin.ttf"); hm.size = 3
        tf.addfile(hm, io.BytesIO(b"xyz"))
        for icao, d in traces.items():
            data = gzip.compress(json.dumps(d).encode())
            ti = tarfile.TarInfo(f"./traces/{icao[-2:]}/trace_full_{icao}.json"); ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    raw = buf.getvalue()
    stem = f"v{day.replace('-', '.')}-planes-readsb-prod-0.tar"
    half = len(raw) // 2 + 7  # split mid-member, like GitHub release parts
    open(os.path.join(folder, stem + ".aa"), "wb").write(raw[:half])
    open(os.path.join(folder, stem + ".ab"), "wb").write(raw[half:])
    open(os.path.join(folder, stem), "wb").write(raw[: len(raw) // 3])  # truncated whole copy: must be ignored
    return raw


def near(rows, lat, lon):
    return [r for r in rows if abs(r["lat"] - lat) < 0.3 and abs(r["lon"] - lon) < 0.3]


def test_day():
    import hashlib, pyarrow.parquet as pq
    tmp = tempfile.mkdtemp()
    try:
        raw = build_day(tmp, "2025-10-16")
        out = os.path.join(tmp, "out")
        s = P.run("2025-10-16", tmp, out, workers=2)
        assert s["input_sha256"] == hashlib.sha256(raw).hexdigest() and s["input_bytes"] == len(raw), "hash of the joined parts"
        assert s["files"] == 19 and s["non_icao"] == 1, s
        assert s["avionics_suspects"] == 1 and s["avionics_suspect_centroids"][0][3] == "C42", s["avionics_suspect_centroids"]
        d = pq.read_table(os.path.join(out, "2025-10-16.parquet")).to_pylist()
        (b,) = near(d, 55.0, 20.0)
        assert (b["aircraft"], b["bad_nacp"], b["bad_nic"], b["bad_acc10"]) == (5, 1, 1, 3), b
        assert b["score"] == 0.0 and b["score_acc10"] == 40.0, "GPSJam formula subtracts one bad aircraft"
        assert (b["capable"], b["cap_bad_acc10"]) == (3, 1), ("capable = reported NACp >= 10 at least once", b)
        (q,) = near(d, 50.0, 10.0)
        assert (q["aircraft"], q["bad_nacp"]) == (3, 0), ("faulty avionics dropped", q)
        (jm,) = near(d, 59.3, 28.0)
        assert (jm["aircraft"], jm["bad_nacp"], jm["score"]) == (4, 4, 75.0), ("jammed long flight kept", jm)
        (lone,) = near(d, 40.0, -100.0)
        assert (lone["aircraft"], lone["bad_nacp"], lone["score"]) == (1, 1, 0.0), lone
        h = pq.read_table(os.path.join(out, "2025-10-16.hourly.parquet")).to_pylist()
        jh = sorted(r["hour"] for r in h if r["h3"] == jm["h3"])
        assert jh == [0, 1, 2, 3] and all(r["bad_nacp"] == 4 for r in h if r["h3"] == jm["h3"]), jh
        assert max(r["hour"] for r in h) == 4 and min(r["hour"] for r in h) == 0, "300-min lone flight spans hours 0-4"
        assert json.load(open(os.path.join(out, "2025-10-16.summary.json")))["method_version"] == "1.1"
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    test_day()
    print("PASS test_day")
