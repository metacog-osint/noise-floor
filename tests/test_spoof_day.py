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


def test_airspeed_fast():
    """v0.5 --airspeed-fast: an aircraft spoofed for its whole visible flight (circling a point at 54 kt while its air data
    says 280 kt IAS) is never 'fast' by GNSS ground speed, so v0.4 doesn't test it; with air data it gets an episode."""
    pts = []
    for k in range(60):                                   # 15 min, a point every 15 s, on a 1 km circle round 56.0N 37.4E
        t = DAY0 + 3600 + 15 * k
        la, lo = S.destination(56.0, 37.4, (20 * k) % 360, 1.0)
        pts.append([t - DAY0, la, lo, 15000 + 250 * k, 54.0, (20 * k + 90) % 360, 0, 0, DET if k == 0 else None,
                    "adsb_icao", 15500 + 250 * k, None, 280, -0.4])
    d = {"icao": "ccc001", "timestamp": DAY0, "t": "T204", "trace": pts}
    A, M, cat = S.parse_trace(d)
    assert A[0][S.IAS] == 280 and len(A[0]) == 11
    off = S.analyse(A, M, cat)
    assert not off["fast"] and not off["episodes"], "v0.4: never fast by ground speed, never tested"
    on = S.analyse(A, M, cat, airspeed=True)
    assert on["fast"] and len(on["episodes"]) == 1, on["episodes"]
    assert all(on["flags"]["slow"][i] for i in on["episodes"][0])
    # a slow light aircraft with no air data stays untested either way
    light = [[p[0], p[1], p[2], p[3], p[4], p[5], 0, 0, ({"version": 2, "nac_p": 9, "nic": 8, "category": "A1"} if i == 0 else None),
              "adsb_icao", p[10], None, None, None] for i, p in enumerate(pts)]
    A2, M2, c2 = S.parse_trace({"icao": "ccc002", "timestamp": DAY0, "trace": light})
    assert not S.analyse(A2, M2, c2, airspeed=True)["fast"]


LIMA = (-12.040, -77.050)


def ring_points(t0, seconds, lat, lon, gs=109.0, alt=36000, step=2):
    """A receiver shown circling a ~1 km ring at a reported ground speed gs."""
    out = []
    for k in range(int(seconds // step) + 1):
        la, lo = S.destination(lat, lon, (k * 12) % 360, 1.0)
        out.append((t0 + k * step, la, lo, alt, gs, 0.0, alt + 1000))
    return out


def lima_flight(t0, seconds=60, gs=109.0, exc_gs=None):
    """30 min over Hungary, `seconds` shown at Lima (on a ring at gs, or moving at exc_gs), then on track again."""
    a = fly(t0, 30, 47.5, 19.0)
    t1 = t0 + 30 * 60 + 10
    if exc_gs:
        mid = [(t, la, lo, alt, exc_gs, trk, geo) for t, la, lo, alt, _, trk, geo in fly(t1, seconds / 60, *LIMA, gs=exc_gs)]
    else:
        mid = ring_points(t1, seconds, *LIMA, gs=gs)
    t2 = mid[-1][0] + 10
    c = fly(t2, 30, *S.destination(47.5, 19.0, 90.0, 450 / S.KT_PER_KMS * (t2 - t0)))
    return a + mid + c


def test_v06_slow_at_cruise():
    """v0.6 rule A: 109 kt at FL360 is slow; v0.5 lets it through and, after the jump there and back, calls the
    aircraft a duplicate address."""
    d = trace("bbb001", lima_flight(DAY0 + 3600))
    A, M, cat = S.parse_trace(d)
    old = S.analyse(A, M, cat, airspeed=True)
    assert not old["episodes"] and old["dup"], (old["episodes"], old["far"])
    new = S.analyse(A, M, cat, airspeed=True, v06=True)
    assert len(new["episodes"]) == 1 and not new["dup"]
    ep = new["episodes"][0]
    assert all(new["flags"]["slow"][i] for i in ep)
    assert all(S.km(A[i][S.LAT], A[i][S.LON], *LIMA) < 2 for i in ep)
    # a real jet at 160 kt is not slow at cruise; 140 kt at 20,000 ft isn't either (below the cruise floor)
    ok = fly(DAY0, 30, 47.5, 19.0) + fly(DAY0 + 1810, 10, 47.5, 21.0, gs=160) + fly(DAY0 + 2420, 10, 47.6, 21.5, gs=140, alt=20000)
    A2, M2, c2 = S.parse_trace(trace("bbb002", ok))
    assert not S.analyse(A2, M2, c2, airspeed=True, v06=True)["episodes"]


def test_v06_short_far_excursion():
    """v0.6 rule B: a 2-minute jump to Lima and back at normal speed is an excursion, not a duplicate address."""
    d = trace("bbb003", lima_flight(DAY0 + 3600, seconds=120, exc_gs=450))
    A, M, cat = S.parse_trace(d)
    old = S.analyse(A, M, cat, airspeed=True)
    assert old["dup"] and not old["episodes"]
    new = S.analyse(A, M, cat, airspeed=True, v06=True)
    assert new["far_excursions"] == 1 and not new["dup"]
    assert len(new["episodes"]) == 1 and all(new["flags"]["excursion"][i] for i in new["episodes"][0])
    # longer than 15 minutes: the rule doesn't apply
    d = trace("bbb004", lima_flight(DAY0 + 3600, seconds=20 * 60, exc_gs=450))
    A, M, cat = S.parse_trace(d)
    assert S.analyse(A, M, cat, airspeed=True, v06=True)["dup"]
    # two aircraft sharing an address, alternating all day: still a duplicate suspect
    a = fly(DAY0, 30, 50.0, 0.0, step=20)
    b = fly(DAY0 + 10, 30, 30.0, 30.0, step=20)
    A, M, cat = S.parse_trace(trace("bbb005", sorted(a + b)))
    r = S.analyse(A, M, cat, airspeed=True, v06=True)
    assert r["dup"] and not r["episodes"]


def mlat_rows(t0, minutes, lat, lon, gs_reported, gs_true=450.0, alt=36000, step=10):
    rows = []
    for k in range(int(minutes * 60 // step) + 1):
        la, lo = S.destination(lat, lon, 90.0, gs_true / S.KT_PER_KMS * k * step)
        rows.append([t0 + k * step - DAY0, la, lo, alt, gs_reported, 90.0, 0, 0, None, "mlat", None, None, None, None])
    return rows


def test_v06_mlat_speed():
    """v0.6 rule C: the false positions never reached the archive, only MLAT (moving at 450 kt) while the aircraft
    reported 109 kt: a speed episode located at the MLAT positions, with no spoofed-to point."""
    t0 = DAY0 + 3600
    a = fly(t0, 30, 47.5, 19.0)
    gap0 = t0 + 30 * 60 + 10
    c = fly(gap0 + 5 * 60, 30, *S.destination(47.5, 19.0, 90.0, 450 / S.KT_PER_KMS * (35 * 60 + 10)))
    d = trace("bbb006", a + c)
    lat0, lon0 = S.destination(47.5, 19.0, 90.0, 450 / S.KT_PER_KMS * (30 * 60 + 10))
    d["trace"] = sorted(d["trace"] + mlat_rows(gap0, 5, lat0, lon0, 109.0), key=lambda r: r[0])
    A, M, cat = S.parse_trace(d)
    assert len(M[0]) == 5 and M[0][4] == 109.0
    assert not S.analyse(A, M, cat, airspeed=True)["speed_episodes"]
    r = S.analyse(A, M, cat, airspeed=True, v06=True)
    assert len(r["speed_episodes"]) == 1 and not r["episodes"]
    rec = S.score_trace(json.dumps(d).encode(), DAY0, True, True)
    ep = [e for e in rec["episodes"] if e["kinds"] == ["speed"]]
    assert len(ep) == 1 and ep[0]["false_lat"] is None and ep[0]["reported_gs"] == 109.0 and ep[0]["vcells"]
    # MLAT agreeing with the reported speed: nothing
    d2 = trace("bbb007", a + c)
    d2["trace"] = sorted(d2["trace"] + mlat_rows(gap0, 5, lat0, lon0, 450.0), key=lambda r: r[0])
    A, M, cat = S.parse_trace(d2)
    assert not S.analyse(A, M, cat, airspeed=True, v06=True)["speed_episodes"]
    # a light aircraft is never tested
    d3 = trace("bbb008", a + c, det=dict(DET, category="A1"))
    d3["trace"] = sorted(d3["trace"] + mlat_rows(gap0, 5, lat0, lon0, 109.0), key=lambda r: r[0])
    A, M, cat = S.parse_trace(d3)
    assert not S.analyse(A, M, cat, airspeed=True, v06=True)["speed_episodes"]


def test_v06_day():
    """A whole day under --v06: the Lima ring becomes a slow episode shown at Lima, the MLAT-only one a speed episode
    with no spoofed-to point; tables and summary carry the new kind; the targets file puts the speed one in unplaced."""
    import pyarrow.parquet as pq
    import spoof_summary as SS
    tmp = tempfile.mkdtemp()
    try:
        raw, out = os.path.join(tmp, "raw"), os.path.join(tmp, "out")
        os.makedirs(raw)
        t0 = DAY0 + 3600
        a, gap0 = fly(t0, 30, 47.5, 19.0), t0 + 30 * 60 + 10
        c = fly(gap0 + 5 * 60, 30, *S.destination(47.5, 19.0, 90.0, 450 / S.KT_PER_KMS * (35 * 60 + 10)))
        sp = trace("bbb010", a + c)
        sp["trace"] = sorted(sp["trace"] + mlat_rows(gap0, 5, *S.destination(47.5, 19.0, 90.0, 450 / S.KT_PER_KMS * 1810), 109.0),
                             key=lambda r: r[0])
        traces = [trace("bbb009", lima_flight(t0)), sp] + [trace(f"bbb2{k:02d}", fly(t0 + k * 30, 50, 48.0 + 0.05 * k, 19.0)) for k in range(3)]
        build_day(raw, "2024-10-14", traces)
        s = S.run("2024-10-14", raw, out, 1, airspeed=True, v06=True)
        assert s["version"] == "0.6.1" and s["episodes"] == 2 and s["episodes_by_kind"].get("speed") == 1, s["episodes_by_kind"]
        t4 = pq.read_table(os.path.join(out, "2024-10-14.hex4.parquet")).to_pylist()
        assert sum(r["spoofed_speed"] for r in t4) >= 1
        p, d, pt = SS.write(out, "2024-10-14", os.path.join(out, "pub"))
        t = json.load(open(pt, encoding="utf-8"))
        assert len(t["clusters"]) == 1 and S.km(t["clusters"][0]["lat"], t["clusters"][0]["lon"], *LIMA) < 2
        assert t["left_out"]["no_false_position"] == 1
        assert [(u["reported_gs_kt"], u["episodes"], u["aircraft"]) for u in t["unplaced"]] == [(110, 1, 1)], t["unplaced"]
        assert t["unplaced"][0]["victim_cells"] and "bbb010" not in json.dumps(t)
        s5 = S.run("2024-10-14", raw, os.path.join(tmp, "v05"), 1, airspeed=True)
        assert s5["version"] == "0.5" and s5["episodes"] == 0, "v0.5 sees neither"
    finally:
        shutil.rmtree(tmp)


def test_v061_rule_a_for_a2():
    """v0.6.1 (docs/validation/spoofing-v061.md): rule A's floor for category A2. A turboprop at 25,500 ft making
    140 kt over the ground into a headwind is slow under v0.6 (floor 25,000 ft), not with rule A off for A2 (0) or with
    the A2 floor at 36,000 ft (v0.6.1, the default); a light jet doing 140 kt at 37,000 ft is still slow with the
    36,000 ft floor. Other categories are unchanged."""
    a2 = dict(DET, category="A2")

    def flight(alt):
        return fly(DAY0, 30, 47.5, 19.0, gs=280, alt=alt) + fly(DAY0 + 1810, 10, 47.5, 21.6, gs=140, alt=alt)

    def eps(pts, det, **kw):
        A, M, cat = S.parse_trace(trace("bbb020", pts, det=det, typ="B350"))
        return S.analyse(A, M, cat, airspeed=True, v06=True, **kw)["episodes"]

    assert S.SLOW_HI_A2_FT == 36000, "v0.6.1 default"
    assert not eps(flight(25500), a2), "v0.6.1 default: A2 at 25,500 ft, 140 kt, is not slow"
    assert len(eps(flight(37000), a2)) == 1, "v0.6.1 default: A2 at 37,000 ft, 140 kt, is slow"
    assert len(eps(flight(25500), a2, a2_hi_ft=25000)) == 1, "v0.6: A2 at 25,500 ft, 140 kt, is slow"
    assert not eps(flight(25500), a2, a2_hi_ft=0), "rule A off for A2"
    assert not eps(flight(25500), a2, a2_hi_ft=36000), "A2 below the 36,000 ft floor"
    assert len(eps(flight(37000), a2, a2_hi_ft=36000)) == 1, "A2 above the 36,000 ft floor"
    assert not eps(flight(37000), a2, a2_hi_ft=0)
    assert len(eps(flight(25500), DET, a2_hi_ft=0)) == 1, "A3 keeps rule A whatever the A2 setting"


def test_candidate():
    """Day cache candidates (docs/spoofing-light-plan.md): a clean airliner isn't one; slow, stationary or jumping
    positions at altitude make one; light aircraft never are."""
    def cand(pts, det=DET, mlat=()):
        A, M, cat = S.parse_trace(trace("bbb030", pts, det=det, mlat=mlat))
        return S.candidate(A, M, cat)
    assert not cand(fly(DAY0, 30, 47.5, 19.0))
    assert cand(fly(DAY0, 30, 47.5, 19.0) + fly(DAY0 + 1810, 5, 47.5, 21.6, gs=190, alt=30000)), "slow at altitude"
    assert cand(hold(DAY0, 3, 47.5, 19.0, gs=300)), "near-stationary at altitude"
    assert cand(fly(DAY0, 10, 47.5, 19.0) + fly(DAY0 + 610, 10, 40.0, 19.0)), "a jump"
    assert not cand(fly(DAY0, 30, 47.5, 19.0, gs=150, alt=8000)), "slow, but under 10,000 ft"
    assert not cand(fly(DAY0, 30, 47.5, 19.0, gs=90), det=dict(DET, category="A1")), "light aircraft"


def test_cache_rerun_and_shadow():
    """run --cache then rerun: the same outputs as the full run; a variant inside the envelope reproduces a full run
    with that setting; settings outside it are refused; the shadow file compares the two without identifiers."""
    import pyarrow.parquet as pq
    import spoof_shadow as SH
    tmp = tempfile.mkdtemp()
    try:
        raw, cache = os.path.join(tmp, "raw"), os.path.join(tmp, "cache")
        os.makedirs(raw)
        t0, a2 = DAY0 + 3600, dict(DET, category="A2")
        slow_a2 = fly(t0, 30, 47.5, 19.0, gs=280, alt=25500) + fly(t0 + 1810, 10, 47.5, 21.6, gs=140, alt=25500)
        traces = [trace("bbb009", lima_flight(t0)), trace("bbb040", slow_a2, det=a2, typ="B350")] +                  [trace(f"bbb2{k:02d}", fly(t0 + k * 30, 50, 48.0 + 0.05 * k, 19.0)) for k in range(4)]
        build_day(raw, "2024-10-14", traces)
        full = S.run("2024-10-14", raw, os.path.join(tmp, "full"), 1, airspeed=True, v06=True,
                     cache_dir=os.path.join(cache, "2024-10-14"))
        meta = json.load(open(os.path.join(cache, "2024-10-14", "meta.json")))
        assert meta["candidates"] == 2 and meta["aircraft"] == 6, meta     # the Lima flight and the slow A2
        re = S.rerun("2024-10-14", os.path.join(cache, "2024-10-14"), os.path.join(tmp, "re"), 1)

        def outs(d):
            ev = json.load(gzip.open(os.path.join(tmp, d, "2024-10-14.events.json.gz"), "rt"))
            t4 = pq.read_table(os.path.join(tmp, d, "2024-10-14.hex4.parquet")).to_pylist()
            return sorted(json.dumps(e, sort_keys=True) for e in ev), t4
        assert outs("full") == outs("re") and full["episodes"] == re["episodes"] == 1 and re["version"] == "0.6.1"
        v = S.rerun("2024-10-14", os.path.join(cache, "2024-10-14"), os.path.join(tmp, "v06"), 1,
                    {"SLOW_HI_A2_FT": 25000}, "v0.6")
        assert v["episodes"] == 2 and v["version"] == "0.6+v0.6" and v["rerun"]["overrides"] == {"SLOW_HI_A2_FT": 25000}
        S._set_overrides({"SLOW_HI_A2_FT": 36000})                       # rerun sets module constants: put back
        f06 = S.run("2024-10-14", raw, os.path.join(tmp, "f06"), 1, airspeed=True, v06=True, a2_hi_ft=25000)
        assert outs("v06") == outs("f06") and f06["episodes"] == 2
        for bad in ({"SLOW_KT": 250}, {"JUMP_KM": 5.0}, {"SAMPLE_S": 10.0}, {"FAST_KT": 200}, {"NOPE": 1}):
            try:
                S.check_overrides(bad)
                raise AssertionError(f"{bad} should be refused")
            except ValueError:
                pass
        S.check_overrides({"SLOW_HI_A2_FT": 0, "SLOW_KT": 120, "LOITER_S": 120})
        d = SH.diff("2024-10-14", os.path.join(tmp, "full"), os.path.join(tmp, "v06"), "v0.6", {"SLOW_HI_A2_FT": 25000})
        assert d["new"]["episodes"] == 1 and d["new"]["by_category"] == {"A2": 1} and d["gone"]["episodes"] == 0
        p = SH.write("2024-10-14", os.path.join(tmp, "full"), [d], os.path.join(tmp, "site"))
        txt = open(p, encoding="utf-8").read()
        assert "bbb0" not in txt and "bbb2" not in txt, "no aircraft identifiers"
        sc = SH.score([os.path.join(tmp, "site")])["v0.6"]
        assert sc["days"] == 1 and sc["episodes"] == {"default": 1, "variant": 2} and sc["new"]["episodes"] == 1
        assert SH.variants("2026-11-20") and not SH.variants("2027-01-01")      # the listed calibration variant's dates
    finally:
        S._set_overrides({"SLOW_HI_A2_FT": 36000})
        shutil.rmtree(tmp)


def make_cached_day(tmp, day="2024-10-14"):
    """A synthetic day with a Lima ring flight, a slow A2 and four clean aircraft: run with --cache. Returns
    (raw folder, cache root, summary of the full run)."""
    raw, cache = os.path.join(tmp, "raw"), os.path.join(tmp, "cache")
    os.makedirs(raw, exist_ok=True)
    t0, a2 = DAY0 + 3600, dict(DET, category="A2")
    slow_a2 = fly(t0, 30, 47.5, 19.0, gs=280, alt=25500) + fly(t0 + 1810, 10, 47.5, 21.6, gs=140, alt=25500)
    traces = [trace("bbb009", lima_flight(t0)), trace("bbb040", slow_a2, det=a2, typ="B350")] +              [trace(f"bbb2{k:02d}", fly(t0 + k * 30, 50, 48.0 + 0.05 * k, 19.0)) for k in range(4)]
    build_day(raw, day, traces)
    full = S.run(day, raw, os.path.join(tmp, "full"), 1, airspeed=True, v06=True, cache_dir=os.path.join(cache, day))
    return raw, cache, full


def test_cpu_time_and_cache_format_2():
    """Summaries carry cpu_seconds (main process plus pool workers); `cache-convert` writes a format-2 cache into a new
    root without touching the old one; rerun reads both formats and gives equal outputs (spoof_same)."""
    import hashlib
    import spoof_same
    tmp = tempfile.mkdtemp()
    try:
        raw, cache, full = make_cached_day(tmp)
        day = "2024-10-14"
        assert full["cpu_seconds"] >= 0 and full["seconds"] >= 0 and "seconds_read" in full, full
        old_dir, new_root = os.path.join(cache, day), os.path.join(tmp, "cache2")
        before = {n: hashlib.sha256(open(os.path.join(old_dir, n), "rb").read()).hexdigest() for n in os.listdir(old_dir)}
        m = S.convert_cache(old_dir, os.path.join(new_root, day))
        assert m["format"] == 2 and m["parsed_candidates"] == m["candidates"] == 2, m
        names = sorted(os.listdir(os.path.join(new_root, day)))
        assert "records.pkl.zst" in names and any(n.startswith("cand2-") for n in names) and "records.pkl.gz" not in names
        assert any(n.startswith("cand-") for n in names), "raw shards kept for spoof_compare"
        assert before == {n: hashlib.sha256(open(os.path.join(old_dir, n), "rb").read()).hexdigest()
                          for n in os.listdir(old_dir)}, "the old cache is untouched"
        for src, dst in ((old_dir, old_dir), (os.path.join(new_root, day), os.path.join(tmp, "elsewhere"))):
            try:
                S.convert_cache(src, dst)
                raise AssertionError("conversion onto itself, or of a format-2 cache, should be refused")
            except ValueError:
                pass
        r1 = S.rerun(day, old_dir, os.path.join(tmp, "re1"), 1)
        r2 = S.rerun(day, os.path.join(new_root, day), os.path.join(tmp, "re2"), 1)
        assert r1["cache_format"] == 1 and r2["cache_format"] == 2
        for r in (r1, r2):
            assert r["cpu_seconds"] >= 0 and set(r["seconds_parts"]) == {"records_load", "scoring", "shard_file_read"}, r
        rep = spoof_same.compare(os.path.join(tmp, "full"), os.path.join(tmp, "re2"), [day])
        assert rep["same"], rep
        assert spoof_same.compare(os.path.join(tmp, "re1"), os.path.join(tmp, "re2"), [day])["same"]
        v = S.rerun(day, os.path.join(new_root, day), os.path.join(tmp, "v06"), 1, {"SLOW_HI_A2_FT": 25000}, "v0.6")
        w = S.rerun(day, old_dir, os.path.join(tmp, "v06b"), 1, {"SLOW_HI_A2_FT": 25000}, "v0.6")
        assert v["episodes"] == w["episodes"] == 2
        assert spoof_same.compare(os.path.join(tmp, "v06"), os.path.join(tmp, "v06b"), [day])["same"]
        assert not spoof_same.compare(os.path.join(tmp, "v06"), os.path.join(tmp, "re2"), [day])["same"]
        # a build in progress blocks a second build of the same day, and a finished build replaces the folder whole
        os.mkdir(old_dir + ".building")
        try:
            S.run(day, raw, os.path.join(tmp, "full2"), 1, airspeed=True, v06=True, cache_dir=old_dir)
            raise AssertionError("a second build of the same day must stop")
        except RuntimeError as e:
            assert "another build" in str(e), e
        os.rmdir(old_dir + ".building")
        open(os.path.join(old_dir, "cand-12345.bin"), "wb").write(b"leftover")       # debris from an older build
        S.run(day, raw, os.path.join(tmp, "full3"), 1, airspeed=True, v06=True, cache_dir=old_dir)
        assert "cand-12345.bin" not in os.listdir(old_dir) and not [n for n in os.listdir(os.path.dirname(old_dir)) if "." in n]
        S._set_overrides({"SLOW_HI_A2_FT": 36000})                       # the 25000 rerun above set it
        assert S.rerun(day, old_dir, os.path.join(tmp, "re3"), 1)["episodes"] == 1
        stale = os.path.join(tmp, "stale")                     # a second build's shard left beside the first one's
        shutil.copytree(old_dir, os.path.join(stale, day))
        shard = sorted(n for n in os.listdir(old_dir) if n.startswith("cand-"))[0]
        shutil.copyfile(os.path.join(old_dir, shard), os.path.join(stale, day, "cand-99999.bin"))
        for fn in (lambda: S.rerun(day, os.path.join(stale, day), os.path.join(tmp, "o"), 1),
                   lambda: S.convert_cache(os.path.join(stale, day), os.path.join(tmp, "c2", day))):
            try:
                fn()
                raise AssertionError("a cache with stale shards must be refused")
            except RuntimeError as e:
                assert "stale or partial shards" in str(e), e
    finally:
        S._set_overrides({"SLOW_HI_A2_FT": 36000})
        shutil.rmtree(tmp)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
