"""Offline tests for tools/ais_detect.py on synthetic tracks (no network, no collected data). Plain script, as CI runs
it: needs numpy, scipy, pyproj, h3 and pyarrow (requirements.txt plus nisar/requirements.txt, both installed in CI)."""
import math, os, sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import ais_detect as A  # noqa: E402

T0 = 1_792_800_000


def track(mmsi, t, lat, lon, sog, cog=None, heading=None, nav=0):
    n = len(t)
    return {"mmsi": np.full(n, mmsi, np.int64), "time": np.asarray(t, np.int64), "lat": np.asarray(lat, float),
            "lon": np.asarray(lon, float), "sog": np.broadcast_to(np.asarray(sog, float), (n,)).copy(),
            "cog": np.full(n, 90.0) if cog is None else np.asarray(cog, float),
            "heading": np.full(n, 90, np.int16) if heading is None else np.asarray(heading, np.int16),
            "navStat": np.full(n, nav, np.int8), "posAcc": np.zeros(n, bool), "raim": np.zeros(n, bool),
            "rx_ms": np.asarray(t, np.int64) * 1000}


def join(*tracks):
    L = {k: np.concatenate([t[k] for t in tracks]) for k in tracks[0]}
    o = np.lexsort((L["time"], L["mmsi"]))
    return {k: v[o] for k, v in L.items()}


def meta_of(types):
    return {m: {"mmsi": m, "type": t, "imo": 9603972, "name": f"V{m}", "hist": {}} for m, t in types.items()}


def straight(mmsi, n=60, dt=10, kn=10.0, lat0=60.0, lon0=25.0, sog=None):
    t = T0 + np.arange(n) * dt
    dlon = kn * KN_DEG_LON * dt * np.arange(n)
    return track(mmsi, t, np.full(n, lat0), lon0 + dlon, kn if sog is None else sog)


KN_DEG_LON = 1.852 / 3600 / (111.32 * math.cos(math.radians(60)))   # degrees of longitude per knot-second at 60N


def test_basics():
    assert A.imo_valid(9603972) and A.imo_valid(9074729)
    assert not A.imo_valid(9603973) and not A.imo_valid(536491800) and not A.imo_valid(0)
    assert A.mmsi_kind(111230001) == "sar_aircraft" and A.mmsi_kind(230123000) == "ship"
    assert A.mmsi_kind(992301234) == "aton" and A.mmsi_kind(970123456) == "sart_mob_epirb"
    assert A.vessel_class(80)[0] == "tanker" and A.speed_limit_kn(80) == 30.0 and A.speed_limit_kn(None) == 67.5
    assert A.dest_class("CHINESE CREW") == "statement"
    assert A.dest_class("FIHEL") == "locode" and A.dest_class("FI HEL>SE STO") == "locode"
    assert A.dest_class("HELSINKI") == "place" and A.dest_class("HELSINKI PILOT CH 71") == "service"
    assert A.dest_class("") == "empty" and A.dest_class("FOR ORDERS") == "generic"
    k = A.pos_key(np.array([60.1234, 60.1235]), np.array([24.5678, 24.5678]), 4)
    assert k[0] != k[1]


def test_walk_track():
    tr = straight(1, n=40)
    lat, lon, t = tr["lat"].copy(), tr["lon"].copy(), tr["time"]
    lat[10] += 0.2                                          # one bad report, about 22 km north
    sus, exc = A.walk_track(t, lat, lon, 37.5)
    assert [e["kind"] for e in exc] == ["spike"] and sus.sum() == 1 and sus[10]
    lat2 = tr["lat"].copy(); lat2[20:25] += 0.5             # a 5-report excursion that returns
    sus, exc = A.walk_track(t, lat2, lon, 37.5)
    assert [e["kind"] for e in exc] == ["excursion"] and sus.sum() == 5
    lat3 = tr["lat"].copy(); lat3[15:] += 2.0               # displaced for good
    sus, exc = A.walk_track(t, lat3, lon, 37.5)
    assert exc[0]["kind"] == "jump" and exc[0]["i0"] == 15


def test_speed_and_reported_speed():
    a = straight(230000001, kn=12)
    b = straight(230000002, kn=12, lat0=60.2)
    b["lat"][30:] += 3.0                                    # jumps 330 km and stays
    c = straight(230000003, kn=12, lat0=60.4, sog=80.0)     # reports 80 kn
    L = join(a, b, c)
    meta = meta_of({230000001: 70, 230000002: 70, 230000003: 70})
    stats = {}
    ev, sus, per = A.d7_speed(L, meta, stats)
    assert len(ev) == 1 and ev[0]["mmsi"] == [230000002] and ev[0]["numbers"]["first_jump_km"] > 300
    ev2, flag = A.d7_reported_speed(L, meta)
    assert [e["mmsi"] for e in ev2] == [[230000003]] and flag.sum() == 60


def test_rendezvous_and_loiter():
    n = 70
    t = T0 + np.arange(n) * 60
    a = track(230000011, t, np.full(n, 59.5), np.full(n, 22.0), 0.5)
    b = track(230000012, t, np.full(n, 59.5015), np.full(n, 22.0), 0.3)    # about 170 m north
    c = track(230000013, t, np.full(n, 59.6), np.full(n, 22.0), 0.4)       # 11 km away
    L = join(a, b, c)
    meta = meta_of({230000011: 80, 230000012: 80, 230000013: 70})
    sus = np.zeros(len(L["mmsi"]), bool)
    c7 = A.h3_cells(L["lat"], L["lon"], 7)
    ev = A.d3_rendezvous(L, meta, sus, c7, set(), 0.5)
    assert len(ev) == 1 and ev[0]["mmsi"] == [230000011, 230000012] and ev[0]["context"]["setting"] == "open water"
    assert 100 < ev[0]["numbers"]["median_sep_m"] < 250 and ev[0]["numbers"]["hours"] >= 1.0
    lo = A.d4_loiter(L, meta, sus, c7, set(), 1.0)
    assert len(lo) == 3
    lo_zone = A.d4_loiter(L, meta, sus, c7, set(c7.tolist()), 1.0)
    assert all(e["context"]["setting"] == "port or anchorage zone" for e in lo_zone)


def test_going_dark():
    n = 120
    t = T0 + np.arange(n) * 60
    others = [track(230000020 + i, t, np.full(n, 59.9 + 0.001 * i), np.full(n, 24.0), 0.0) for i in range(4)]
    keep = (np.arange(n) < 30) | (np.arange(n) > 100)                       # silent for 70 min
    v = track(230000030, t[keep], np.full(keep.sum(), 59.905), np.full(keep.sum(), 24.0), 0.0)
    w = track(230000031, t[keep], np.full(keep.sum(), 62.5), np.full(keep.sum(), 19.0), 0.0)  # nobody else there
    sparse = np.isin(np.arange(n), [5, 60, 110])                              # edge of coverage: heard now and then
    x = track(230000032, t[sparse], np.full(3, 59.903), np.full(3, 24.0), 0.0)
    L = join(*others, v, w, x)
    meta = meta_of({m: 70 for m in np.unique(L["mmsi"]).tolist()})
    c5 = A.h3_cells(L["lat"], L["lon"], 5)
    ev, st = A.d5_dark(L, meta, c5, 0.5, int(t[0]), int(t[-1]))
    assert st == {"gaps_over_threshold": 4, "gaps_irregular_reception": 2}, st
    assert [e["mmsi"] for e in ev] == [[230000030]]
    assert ev[0]["numbers"]["gap_h"] > 1.1 and ev[0]["context"]["stationary_both_ends"]


def test_circles():
    n = 120
    t = T0 + np.arange(n) * 15
    r_deg_lat = 0.3 / 111.32
    def circ(m, phase):
        ang = np.radians(np.arange(n) * 12 + phase)   # 12 degrees per 15 s: 4 turns in 30 min
        return track(m, t, 60.0 + r_deg_lat * np.cos(ang), 26.0 + r_deg_lat * np.sin(ang) / math.cos(math.radians(60)), 8.0)
    L = join(circ(230000041, 0), circ(230000042, 90), straight(230000043, n=n, dt=15, lat0=60.3))
    meta = meta_of({230000041: 70, 230000042: 80, 230000043: 70})
    ev = A.d7_circles(L, meta, np.zeros(len(L["mmsi"]), bool))
    assert len(ev) == 1 and ev[0]["mmsi"] == [230000041, 230000042] and "spoofing" in ev[0]["context"]["reading"]
    # one vessel circling alone with its heading following the course: a real manoeuvre
    one = circ(230000044, 0)
    one["cog"] = (np.arange(n) * 12 + 90.0) % 360
    one["heading"] = one["cog"].astype(np.int16)
    ev = A.d7_circles(join(one), meta, np.zeros(n, bool))
    assert len(ev) == 1 and "real manoeuvre" in ev[0]["context"]["reading"], ev
    one["heading"] = np.full(n, 90, np.int16)                                # course detached from heading
    ev = A.d7_circles(join(one), meta, np.zeros(n, bool))
    assert "check for spoofing" in ev[0]["context"]["reading"], ev


def test_identity():
    meta = {230000051: {"mmsi": 230000051, "type": 70, "imo": 9603972, "name": "B",
                        "hist": {"name": {"A": [1000, 2000, 3, {"mqtt"}], "B": [3000, 4000, 2, {"mqtt"}]},
                                 "imo": {9603972: [1000, 4000, 5, {"mqtt"}]}}},
            230000052: {"mmsi": 230000052, "type": 80, "imo": 9603972, "name": "C",
                        "hist": {"imo": {9603972: [1000, 4000, 5, {"rest"}]}, "destination": {"NO LINK TO ISRAEL": [1, 2, 1, {"mqtt"}]}}},
            230000053: {"mmsi": 230000053, "type": 80, "imo": 9603973, "name": "D", "hist": {"imo": {9603973: [1, 2, 1, {"mqtt"}]}}}}
    L = straight(230000051)
    ev, st = A.d6_identity(meta, L)
    rules = sorted(e["rule"] for e in ev)
    assert rules == ["D6-destination-text", "D6-identity-change", "D6-imo-invalid", "D6-imo-shared"], rules
    assert st["imo_field"] == {"valid": 2, "bad_check_digit": 1}


def main():
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)


if __name__ == "__main__":
    main()
