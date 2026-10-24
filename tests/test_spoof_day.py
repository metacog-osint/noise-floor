"""Offline tests for tools/spoof_day.py: synthetic aircraft tracks, and a tiny synthetic adsb.lol day.

Run:  python tests/test_spoof_day.py   (or pytest)
"""
import gzip, io, json, os, shutil, sys, tarfile, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import spoof_day as S  # noqa: E402

DAY0 = 1728864000.0   # 2024-10-14T00:00:00Z
DET = {"version": 2, "nac_p": 9, "nic": 8, "category": "A3"}


def fly(t0, minutes, lat, lon, trk=90.0, gs=450.0, alt=35000, step=10, geo_off=1000):
    """Points every `step` s on a great circle: (t, lat, lon, alt, gs, trk, geo)."""
    out = []
    for k in range(int(minutes * 60 // step) + 1):
        la, lo = S.destination(lat, lon, trk, gs / S.KT_PER_KMS * k * step)
        out.append((t0 + k * step, la, lo, alt, gs, trk, alt + geo_off))
    return out


def hold(t0, minutes, lat, lon, gs=0.7, alt=35000, step=15, geo_off=-3150):
    """A receiver held at a fixed point (the spoofed-to position): ground speed near zero."""
    return [(t0 + k * step, lat, lon, alt, gs, 0.0, alt + geo_off) for k in range(int(minutes * 60 // step) + 1)]


def trace(icao, pts, det=DET, mlat=(), typ="A320"):
    """adsb.lol trace_full dict. pts as from fly()/hold(); mlat: (t, lat, lon, alt)."""
    rows = [[t - DAY0, la, lo, alt, gs, trk, 0, 0, det if i == 0 else None, "adsb_icao", geo, None, None, None]
            for i, (t, la, lo, alt, gs, trk, geo) in enumerate(pts)]
    rows += [[t - DAY0, la, lo, alt, None, None, 0, 0, None, "mlat", None, None, None, None] for t, la, lo, alt in mlat]
    rows.sort(key=lambda r: r[0])
    return {"icao": icao, "timestamp": DAY0, "t": typ, "trace": rows}


def analyse(d):
    A, M, cat = S.parse_trace(d)
    return A, M, S.analyse(A, M, cat)


def spoofed_flight(t0=DAY0 + 3600, lat=30.0, lon=30.0):
    """20 min on track, 10 min held at a point ~250 km away, then on track again (dead-reckoned) for 20 min."""
    a = fly(t0, 20, lat, lon)
    la, lo = S.destination(lat, lon, 90.0, 450 / S.KT_PER_KMS * 30 * 60)
    b = hold(t0 + 20 * 60 + 15, 10, lat + 2.0, lon + 1.0)
    c = fly(t0 + 30 * 60 + 30, 20, *S.destination(lat, lon, 90.0, 450 / S.KT_PER_KMS * (30 * 60 + 30)))
    return a + b + c, (la, lo)


def test_clean_flight():
    A, M, r = analyse(trace("aaa001", fly(DAY0 + 3600, 60, 50.0, 5.0)))
    assert r["fast"] and not r["episodes"] and all(r["trusted"]) and r["jumps"] == 0, r["episodes"]


def test_fixed_point_spoof():
    pts, _ = spoofed_flight()
    A, M, r = analyse(trace("aaa002", pts))
    assert len(r["episodes"]) == 1, r["episodes"]
    ep = r["episodes"][0]
    assert all(r["flags"]["slow"][i] and r["flags"]["loiter"][i] for i in ep)
    assert len(ep) == 41 and r["jumps"] == 2
    vt, before, after, how = S.victim_track(A, r["trusted"], ep, M)
    assert how == "between" and before[S.LON] < after[S.LON] and abs(before[S.LAT] - 30.0) < 0.2, (how, before, after)
    assert any(r["flags"]["geo_step"]) and any(r["flags"]["geo_sat"])


def test_replay_info():
    """v0.4: positions re-sent ~20 min late retrace the aircraft's own track (replay); a fixed-point hold doesn't."""
    t0 = DAY0 + 3600
    track = fly(t0, 60, 50.0, 5.0)
    stale = [(p[0] + 20 * 60 + 5, *p[1:]) for p in track[:30]]          # the first 5 min re-sent 20 min later
    pts = sorted(track + stale, key=lambda p: p[0])
    A, M, r = analyse(trace("aaa009", pts))
    grid = S.replay_grid(A, r["trusted"])
    ep = [i for i, p in enumerate(A) if any(abs(p[0] - s[0]) < 0.01 and abs(p[1] - s[1]) < 1e-9 for s in stale)]
    share, lag, iqr = S.replay_info(A, grid, ep)
    assert share > 0.9 and abs(lag - 1205) < 30 and iqr <= S.REPLAY_IQR_S, (share, lag, iqr)
    pts2, _ = spoofed_flight()
    A2, M2, r2 = analyse(trace("aaa010", pts2))
    share2, _, _ = S.replay_info(A2, S.replay_grid(A2, r2["trusted"]), r2["episodes"][0])
    assert share2 == 0.0, share2


def test_realistic_excursion():
    """Positions shifted 100 km north for 10 min at normal speed, then back: an excursion, not slow."""
    t0 = DAY0 + 7200
    a = fly(t0, 30, 40.0, 20.0)
    mid = [(t, la + 0.9, lo, alt, gs, trk, geo) for t, la, lo, alt, gs, trk, geo in fly(t0 + 30 * 60 + 10, 10, *S.destination(40.0, 20.0, 90.0, 450 / S.KT_PER_KMS * (30 * 60 + 10)))]
    c = fly(t0 + 40 * 60 + 20, 30, *S.destination(40.0, 20.0, 90.0, 450 / S.KT_PER_KMS * (40 * 60 + 20)))
    A, M, r = analyse(trace("aaa003", a + mid + c))
    assert len(r["episodes"]) == 1, r["episodes"]
    ep = r["episodes"][0]
    assert all(r["flags"]["excursion"][i] for i in ep) and not any(r["flags"]["slow"]) and len(ep) == len(mid)


def test_light_aircraft_not_tested():
    """Light aircraft (category A1) can fly slowly at 12,000 ft: never slow / loiter."""
    det = dict(DET, category="A1")
    pts = fly(DAY0, 30, 46.0, 7.0, gs=260, alt=12000) + fly(DAY0 + 1810, 20, 46.0, 9.0, gs=80, alt=12000)
    A, M, r = analyse(trace("aaa004", pts, det=det, typ="PC21"))
    assert not r["fast"] and not r["episodes"]


def test_a2_floor():
    """Category A2 (business jets, turboprops, commuters): slow / loiter only from 18,000 ft (skydiving and training
    flights fly slowly lower down); larger categories from 10,000 ft."""
    det = dict(DET, category="A2")
    fast_leg = fly(DAY0, 20, 33.0, -112.0, gs=300, alt=24000)
    low = fast_leg + hold(DAY0 + 1215, 6, 33.5, -112.0, gs=85, alt=13000, geo_off=500)
    A, M, r = analyse(trace("aaa009", low, det=det, typ="SH36"))
    assert r["fast"] and not r["episodes"], r["episodes"]
    high = fast_leg + hold(DAY0 + 1215, 6, 33.5, -112.0, gs=85, alt=21000, geo_off=500)
    A, M, r = analyse(trace("aaa010", high, det=det, typ="BE40"))
    assert len(r["episodes"]) == 1
    A, M, r = analyse(trace("aaa011", low, det=dict(DET, category="A3")))
    assert len(r["episodes"]) == 1, "A3 keeps the 10,000 ft floor"


def test_duplicate_address():
    """Two aircraft sharing an address 3,000 km apart, alternating: duplicate suspect, no episodes."""
    a = fly(DAY0, 30, 50.0, 0.0, step=20)
    b = fly(DAY0 + 10, 30, 30.0, 30.0, step=20)
    A, M, r = analyse(trace("aaa005", sorted(a + b)))
    assert r["dup"] and r["far"] >= 2


def test_loiter_needs_continuous_coverage():
    """The same airway point seen 5 h apart (coverage gap) is not a loiter."""
    a = fly(DAY0, 3, 24.0, 54.0)
    b = fly(DAY0 + 5 * 3600, 3, 24.0, 54.0)
    A, M, r = analyse(trace("aaa006", a + b))
    assert not any(r["flags"]["loiter"]) and not r["episodes"]


def test_one_way_jump_unresolved():
    """A jump with no return can't say which side is true: counted, not an episode."""
    a = fly(DAY0, 30, 35.0, 30.0)
    b = fly(DAY0 + 30 * 60 + 20, 30, 37.0, 33.0)
    A, M, r = analyse(trace("aaa007", a + b))
    assert r["jumps"] == 1 and len(r["unresolved"]) == 1 and not r["episodes"]


def test_mlat_confirms():
    pts, _ = spoofed_flight()
    t0 = DAY0 + 3600 + 20 * 60 + 15
    truth = [(t0 + k * 15, *S.destination(30.0, 30.0, 90.0, 450 / S.KT_PER_KMS * (20 * 60 + 15 + k * 15)), 35000) for k in range(10)]
    A, M, r = analyse(trace("aaa008", pts, mlat=truth))
    on_false = [x for x in r["mlat"] if r["false"][x[0]]]
    assert len(on_false) >= 8 and all(x[1] > 100 for x in on_false), on_false[:3]


def test_classify():
    """active: another aircraft spoofed nearby; post: an earlier episode far away; isolated: neither."""
    def ep(t0, lat, lon, h):
        return {"t0": t0, "t1": t0 + 300, "ref": [lat, lon], "vcells": [(S.cell(lat, lon, S.RES), h)]}
    a = {"icao": "a", "episodes": [ep(DAY0, 33.0, 33.0, 0)]}
    b = {"icao": "b", "episodes": [ep(DAY0 + 600, 33.0, 33.0, 1)]}
    c = {"icao": "c", "episodes": [ep(DAY0, 55.0, 30.0, 0), ep(DAY0 + 7200, 48.0, 5.0, 2)]}
    d = {"icao": "d", "episodes": [ep(DAY0, 40.0, -100.0, 5)]}
    e = {"icao": "e", "episodes": [dict(ep(DAY0, 40.0, -90.0, 5), vcells=[])]}
    S.classify([a, b, c, d, e])
    got = [x["class"] for r in (a, b, c, d, e) for x in r["episodes"]]
    assert got == ["active", "active", "isolated", "post", "isolated", "unlocated"], got


def build_day(folder, day, traces):
    stem = os.path.join(folder, f"v{day.replace('-', '.')}-planes-readsb-prod-0.tar")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for d in traces:
            raw = gzip.compress(json.dumps(d).encode())
            ti = tarfile.TarInfo(f"./traces/{d['icao'][-2:]}/trace_full_{d['icao']}.json")
            ti.size = len(raw)
            tf.addfile(ti, io.BytesIO(raw))
    data = buf.getvalue()
    half = len(data) // 2
    open(stem + ".aa", "wb").write(data[:half])
    open(stem + ".ab", "wb").write(data[half:])


def test_day():
    import pyarrow.parquet as pq
    tmp = tempfile.mkdtemp()
    try:
        raw, out = os.path.join(tmp, "raw"), os.path.join(tmp, "out")
        os.makedirs(raw)
        pts, _ = spoofed_flight()
        traces = [trace("bbb001", pts)] + [trace(f"bbb1{k:02d}", fly(DAY0 + 3600 + k * 30, 50, 30.0 + 0.05 * k, 30.0)) for k in range(5)]
        build_day(raw, "2024-10-14", traces)
        s = S.run("2024-10-14", raw, out, 1)
        assert s["aircraft"] == 6 and s["episodes"] == 1 and s["aircraft_with_episodes"] == 1, s
        t4 = pq.read_table(os.path.join(out, "2024-10-14.hex4.parquet")).to_pylist()
        assert sum(r["spoofed"] for r in t4) >= 1 and sum(r["false_pos"] for r in t4) == 1
        held = S.h3.latlng_to_cell(32.0, 31.0, S.RES)
        assert [r["false_pos"] for r in t4 if r["h3"] == held] == [1], "false position counted where it was shown"
        assert all(r["spoofed"] <= r["aircraft"] for r in t4)
        t2 = pq.read_table(os.path.join(out, "2024-10-14.hex2.parquet")).to_pylist()
        assert max(r["spoofed"] for r in t2) == 1
        ev = json.load(gzip.open(os.path.join(out, "2024-10-14.events.json.gz"), "rt"))
        assert len(ev) == 1 and ev[0]["kinds"] == ["loiter", "slow"] and ev[0]["victim_how"] == "between", ev
        assert ev[0]["class"] == "isolated" and sum(r["spoofed_isolated"] for r in t4) >= 1, "one aircraft alone: isolated"
        assert ev[0]["start"].startswith("2024-10-14T01:20")
        assert s["spoofed_to_res6_top"][0][3] == 1
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
