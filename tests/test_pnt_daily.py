"""Offline test for pipeline/pnt_daily.py: a synthetic adsb.lol day split into two tar parts.

Run:  python tests/test_pnt_daily.py   (or pytest)
"""
import gzip, io, json, os, shutil, sys, tarfile, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import pnt_daily as P  # noqa: E402

V2_GOOD = {"version": 2, "nac_p": 10, "nic": 8}
V2_BAD = {"version": 2, "nac_p": 0, "nic": 0}


def trace(icao, pts, kind="adsb_icao"):
    """pts: list of (t_seconds, lat, lon, alt, details_or_None)."""
    return {"icao": icao, "timestamp": 1760572800.0,
            "trace": [[t, la, lo, alt, 450.0, 90.0, 0, 0, det, kind, alt, None, None, None] for t, la, lo, alt, det in pts]}


def line(t0, n, lat, lon, det_first, step_s=60, dlon=0.0):
    return [(t0 + i * step_s, lat, lon + i * dlon, 35000, det_first if i == 0 else None) for i in range(n)]


def build_day(folder, day):
    traces = {
        "aaaaa1": trace("aaaaa1", line(0, 20, 55.0, 20.0, V2_GOOD)),                    # clean, Baltic hex
        "aaaaa2": trace("aaaaa2", line(0, 20, 55.0, 20.0, V2_BAD)),                     # jammed in the same hex
        "aaaaa3": trace("aaaaa3", line(0, 20, 55.0, 20.0, V2_GOOD)),                    # clean
        "~bbbbb": trace("~bbbbb", line(0, 20, 55.0, 20.0, V2_BAD)),                     # non-ICAO: ignored
        "ccccc1": trace("ccccc1", line(0, 20, 55.0, 20.0, V2_BAD), kind="mlat"),        # MLAT: ignored
        "ccccc2": trace("ccccc2", [(i * 60, 55.0, 20.0, "ground", V2_BAD if i == 0 else None) for i in range(20)]),  # ground
        "ccccc3": trace("ccccc3", line(0, 20, 55.0, 20.0, {"version": 0, "nac_p": 0, "nic": 0})),               # ADS-B v0
        "ddddd1": trace("ddddd1", line(0, 300, 40.0, -100.0, V2_BAD, step_s=60, dlon=0.02)),  # 5 h all bad: suspect
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


def test_day():
    import hashlib, pyarrow.parquet as pq
    tmp = tempfile.mkdtemp()
    try:
        raw = build_day(tmp, "2025-10-16")
        out = os.path.join(tmp, "out")
        s = P.run("2025-10-16", tmp, out, workers=2)
        assert s["input_sha256"] == hashlib.sha256(raw).hexdigest() and s["input_bytes"] == len(raw), "hash of the joined parts"
        assert s["files"] == 8 and s["non_icao"] == 1 and s["avionics_suspects"] == 1, s
        t = pq.read_table(os.path.join(out, "2025-10-16.parquet")).to_pylist()
        baltic = [r for r in t if abs(r["lat"] - 55.0) < 0.3]
        assert len(baltic) == 1, t
        b = baltic[0]
        assert (b["aircraft"], b["bad_nacp"], b["bad_nic"]) == (3, 1, 1), b   # MLAT, ground, v0, non-ICAO excluded
        assert b["score"] == 0.0, "GPSJam formula subtracts one bad aircraft"
        assert not [r for r in t if r["lat"] < 45], "avionics suspect must not appear in any hex"
        assert json.load(open(os.path.join(out, "2025-10-16.summary.json")))["method"]["h3_res"] == 4
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    test_day()
    print("PASS test_day")
