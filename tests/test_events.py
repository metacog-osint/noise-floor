"""Offline tests for tools/events.py (Events and grading lane): fusion, each grade rule, the planned-test overlap and
the NATURAL rules, on small synthetic inputs. Run as a plain script: python tests/test_events.py"""
import argparse
import contextlib
import io
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import h3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import events as E  # noqa: E402

DAY = "2026-03-10"
C0 = h3.latlng_to_cell(55.0, 20.0, 2)
RING1 = sorted(h3.grid_ring(C0, 1))
RING2 = sorted(h3.grid_ring(C0, 2))


def ll(cell):
    return h3.cell_to_latlng(cell)


def anomaly(cell, h0, h1, m="jam", tier="notable", at=None):
    lat, lon = at or ll(cell)
    return {"m": m, "tier": tier, "h0": h0, "h1": h1, "regions": 1, "rh": h1 - h0 + 1, "peak": 20.0, "excess": 15.0,
            "lat": lat, "lon": lon, "cells": [cell]}


def burst(cell, t0, t1, at=None):
    lat, lon = at or ll(cell)
    return {"t0": t0, "t1": t1, "peak": 9, "regions": 1, "lat": lat, "lon": lon, "cells": [cell]}


def from_file(anomalies=(), bursts=(), sbas=(), day=DAY):
    return E.observations_from_events_file(day, {"day": day, "anomalies": list(anomalies), "bursts": list(bursts),
                                                 "sbas": list(sbas)}, "test")


def kp_series(storm=None, day=DAY):
    """Kp 1.0 everywhere for three days around `day`, except {'HH': kp} slots on `day`."""
    start = datetime.fromisoformat(day).replace(tzinfo=timezone.utc) - timedelta(days=1)
    rows = []
    for k in range(24):
        s = start + timedelta(hours=3 * k)
        v = (storm or {}).get(s.strftime("%H")) if s.date().isoformat() == day else None
        rows.append((s, v if v is not None else 1.0, "def"))
    return E.Kp(rows)


def run(observations, kp="quiet"):
    k = kp_series() if kp == "quiet" else kp
    return E.build_day(DAY, observations + E.kp_observations(DAY, k), k)


def effects(events):
    return [e for e in events if e["grades"]["signal_type"][0] == "EFFECT"]


def field(e, name):
    return e["grades"][name][0]


def rule(e, name):
    return e["grades"][name][1]


def faa(lat, lon, w0="10:00", w1="12:00", radius_nm=100, tid="TEST GPS 26-01", day=DAY, windows=None):
    return {"id": tid, "place": "Test Range", "centre": [lat, lon], "radii_nm": {"50FT AGL": radius_nm // 2, "FL400": radius_nm},
            "windows": windows or [[f"{day}T{w0}Z", f"{day}T{w1}Z"]], "notice_url": "https://example.invalid/notice"}


# ---------------------------------------------------------------- fusion
def test_fusion_adjacent_regions_and_hours():
    assert len(effects(run(from_file(bursts=[burst(C0, "10:00Z", "10:05Z"), burst(RING1[0], "10:30Z", "10:35Z")])))) == 1
    # two rings apart: not adjacent
    assert len(effects(run(from_file(bursts=[burst(C0, "10:00Z", "10:05Z"), burst(RING2[0], "10:30Z", "10:35Z")])))) == 2
    # adjacent regions but 115 min apart
    assert len(effects(run(from_file(bursts=[burst(C0, "10:00Z", "10:05Z"), burst(RING1[0], "12:01Z", "12:05Z")])))) == 2
    # hours 14-15 and 16 are adjacent; 14-15 and 17 are not (hour 16 empty between them)
    assert len(effects(run(from_file(anomalies=[anomaly(C0, 14, 15), anomaly(RING1[0], 16, 16)])))) == 1
    assert len(effects(run(from_file(anomalies=[anomaly(C0, 14, 15), anomaly(RING1[0], 17, 17)])))) == 2
    # different measures and kinds in one place and hour fuse into one event
    ev = effects(run(from_file(anomalies=[anomaly(C0, 10, 10, "jam"), anomaly(C0, 10, 10, "acc")],
                               bursts=[burst(C0, "10:20Z", "10:30Z")])))
    assert len(ev) == 1 and len(ev[0]["members"]) == 3 and ev[0]["effect_measure"] == "both"


def test_fusion_distance_cap():
    far = h3.latlng_to_cell(55.0, 45.0, 2)                    # ~1,600 km east of C0
    path = list(h3.grid_path_cells(C0, far))
    obs = [E.obs(DAY, "adsb_level", "EFFECT", "adsb", 0, 1439, "day", *ll(c), [c], measure="gross",
                 detail={"jam_hexes": 3, "hexes_5plus": 9, "share": 20.0}, key=c) for c in path]
    groups = E.fuse(obs)
    assert len(groups) >= 2, len(groups)
    assert sum(len(g) for g in groups) == len(path)
    for g in groups:
        pts = [(obs[i]["lat"], obs[i]["lon"]) for i in g]
        assert all(E.km(a, b) <= E.MAX_EVENT_KM for a in pts for b in pts)


def test_sbas_fusion():
    ev = run(from_file(sbas=[{"area": "WAAS (CONUS)", "start": 3, "end": 4, "state": "outage"},
                             {"area": "WAAS (CONUS)", "start": 5, "end": 5, "state": "degraded"},
                             {"area": "EGNOS (Europe)", "start": 5, "end": 5, "state": "outage"}]))
    assert sorted(len(e["members"]) for e in effects(ev)) == [1, 2]


# ---------------------------------------------------------------- support
def test_support_rules():
    base = from_file(anomalies=[anomaly(C0, 10, 10, "jam"), anomaly(C0, 10, 10, "acc")], bursts=[burst(C0, "10:20Z", "10:30Z")])
    e = effects(run(list(base)))[0]
    assert field(e, "support") == "Single-source, unverified" and rule(e, "support") == "S1", e["grades"]["support"]
    lat, lon = ll(C0)
    e = effects(run(list(base) + E.faa_observations(DAY, [faa(lat, lon)])))[0]
    assert field(e, "support") == "Partially corroborated" and rule(e, "support") == "S2"
    E.SOURCES["testsensor"] = ("synthetic second sensor family", True)
    try:
        other = E.obs(DAY, "test_rfi", "EFFECT", "testsensor", 600, 659, "hour", lat, lon, [C0], measure="gross", key="x")
        e = effects(run(list(base) + [other]))[0]
        assert field(e, "support") == "Multiple sources" and rule(e, "support") == "S3"
        # a second sensor family that doesn't agree in space (two rings away) does not corroborate
        far = E.obs(DAY, "test_rfi", "EFFECT", "testsensor", 600, 659, "hour", *ll(RING2[0]), [RING2[0]], measure="gross", key="y")
        assert [field(e, "support") for e in effects(run(list(base) + [far]))] == ["Single-source, unverified"] * 2
    finally:
        del E.SOURCES["testsensor"]


# ---------------------------------------------------------------- planned test
def test_planned_overlap():
    lat, lon = ll(C0)
    tests = E.faa_observations(DAY, [faa(lat, lon)])          # 10:00-12:00Z, 100 nm (185 km)
    ev = run(from_file(bursts=[burst(C0, "10:30Z", "10:40Z")]) + tests)
    e = effects(ev)[0]
    assert field(e, "verdict") == "planned" and rule(e, "verdict") == "P1"
    assert field(e, "attribution_status") == "candidate" and "TEST GPS 26-01" in e["grades"]["attribution_status"][2]
    assert tests[0]["id"] in e["members"] and "candidate: announced test TEST GPS 26-01" in e["label"]
    assert not [x for x in ev if field(x, "signal_type") == "WARNING"]      # the notice attached, not left alone
    # outside the radius (~400 km away): open; the notice stands alone as a WARNING event, planned by rule P2
    away = h3.latlng_to_cell(55.0, 26.5, 2)
    ev = run(from_file(bursts=[burst(away, "10:30Z", "10:40Z")]) + tests)
    assert [field(e, "verdict") for e in effects(ev)] == ["open"]
    w = [x for x in ev if field(x, "signal_type") == "WARNING"]
    assert len(w) == 1 and field(w[0], "verdict") == "planned" and rule(w[0], "verdict") == "P2"
    assert field(w[0], "attribution_status") == "none" and field(w[0], "support") == "Single-source, unverified"
    # outside the window
    assert [field(e, "verdict") for e in effects(run(from_file(bursts=[burst(C0, "13:00Z", "13:10Z")]) + tests))] == ["open"]
    # partly inside: one burst within 50 nm, the fused neighbour beyond it -> open, hint test_partial
    tight = E.faa_observations(DAY, [faa(lat, lon, radius_nm=50)])
    ev = effects(run(from_file(bursts=[burst(C0, "10:30Z", "10:40Z"), burst(RING1[0], "10:35Z", "10:45Z")]) + tight))
    assert len(ev) == 1 and field(ev[0], "verdict") == "open" and ev[0]["open_hint"] == "test_partial"
    assert ev[0]["exclusions"]["planned_test"][0] == "partial"
    # a window across midnight is clipped to the day
    o = E.faa_observations(DAY, [faa(lat, lon, windows=[["2026-03-09T22:00Z", "2026-03-10T02:00Z"]])])
    assert o[0]["detail"]["windows"] == [[0, 120]]
    assert E.faa_observations("2026-03-11", [faa(lat, lon, windows=[["2026-03-09T22:00Z", "2026-03-10T02:00Z"]])]) == []


# ---------------------------------------------------------------- NATURAL
def test_kp_helpers():
    kp = kp_series({"09": 6.0, "12": 7.0})
    assert E.kp_max(kp, DAY, 15 * 60, 15 * 60 + 59) == 7.0                 # 15Z: the 12-15Z slot is within 3 h
    assert E.kp_max(kp, DAY, 17 * 60, 17 * 60 + 59) == 7.0                 # 17Z - 3 h = 14Z: reaches the 12-15Z slot
    assert E.kp_max(kp, DAY, 19 * 60, 19 * 60 + 59) == 1.0                 # 19Z - 3 h = 16Z: doesn't
    assert E.kp_max(kp, DAY, 6 * 60, 6 * 60 + 59) == 6.0                   # 06:59Z + 3 h reaches the 09-12Z slot
    assert E.kp_max(kp, "2026-03-20", 0, 59) is None                        # outside the series
    nat = E.kp_observations(DAY, kp)
    assert len(nat) == 1 and (nat[0]["t0"], nat[0]["t1"]) == (540, 899) and nat[0]["detail"]["kp_max"] == 7.0


def test_natural_rules():
    hi = h3.latlng_to_cell(60.0, -100.0, 2)                                  # geomagnetic latitude ~68
    lo = h3.latlng_to_cell(20.0, 80.0, 2)                                    # geomagnetic latitude ~12
    assert E.mlat(*ll(hi)) > 60 and abs(E.mlat(*ll(lo))) < 25
    storm6 = kp_series({"09": 6.0})
    ev = run(from_file(anomalies=[anomaly(hi, 10, 10, "acc")]), storm6)
    e = effects(ev)[0]
    assert field(e, "verdict") == "benign_natural" and rule(e, "verdict") == "N2"
    nat = [x for x in ev if field(x, "signal_type") == "NATURAL"]
    assert len(nat) == 1 and field(nat[0], "verdict") == "benign_natural" and rule(nat[0], "verdict") == "N0"
    assert nat[0]["members"][0] in e["context"]                              # the storm is linked as context
    # worse-than-93 m loss is not explained by a storm, even a severe one
    e = effects(run(from_file(anomalies=[anomaly(hi, 10, 10, "jam")]), kp_series({"09": 8.667})))[0]
    assert field(e, "verdict") == "open" and e["open_hint"] == "storm_partial"
    # low geomagnetic latitude: Kp 6 is not enough, Kp 8.3 is
    e = effects(run(from_file(anomalies=[anomaly(lo, 10, 10, "acc")]), storm6))[0]
    assert field(e, "verdict") == "open" and e["exclusions"]["space_weather"][0] == "storm_partial"
    e = effects(run(from_file(anomalies=[anomaly(lo, 10, 10, "acc")]), kp_series({"09": 8.333})))[0]
    assert field(e, "verdict") == "benign_natural"
    # quiet Kp: nothing natural about it
    e = effects(run(from_file(anomalies=[anomaly(hi, 10, 10, "acc")])))[0]
    assert field(e, "verdict") == "open" and e["exclusions"]["space_weather"][0] == "not_indicated"
    # no Kp at all: the check says so and the verdict stays open
    e = effects(E.build_day(DAY, from_file(anomalies=[anomaly(hi, 10, 10, "acc")]), None))[0]
    assert field(e, "verdict") == "open" and e["exclusions"]["space_weather"][0] == "unknown"


def test_sbas_rules():
    run_ = {"area": "WAAS (Canada)", "start": 10, "end": 11, "state": "outage"}
    e = effects(run(from_file(sbas=[run_]), kp_series({"09": 6.0})))[0]
    assert field(e, "verdict") == "benign_natural" and rule(e, "verdict") == "N1"
    e = effects(run(from_file(sbas=[run_])))[0]
    assert field(e, "verdict") == "open" and e["open_hint"] == "sbas_service"
    e = effects(run(from_file(sbas=[dict(run_, area="GAGAN (India)")])))[0]
    assert field(e, "verdict") == "open" and e["open_hint"] == "sbas_equipage"
    # a flag that is only partly at storm time is not natural, however strong the storm (N2 is for located effects)
    part = [{"area": "WAAS (CONUS)", "start": 2, "end": 4, "state": "outage"}, {"area": "WAAS (CONUS)", "start": 5, "end": 9, "state": "degraded"}]
    e = effects(run(from_file(sbas=part), kp_series({"12": 8.667})))[0]
    assert len(e["members"]) == 2 and field(e, "verdict") == "open" and e["open_hint"] == "storm_partial", e["exclusions"]
    # a 10 m-only effect next to a storm-time SBAS flag, below the Kp latitude gate: natural by N1 (SBAS context)
    mid = h3.latlng_to_cell(40.0, -100.0, 2)
    assert abs(E.mlat(*ll(mid))) < 50
    obs = from_file(anomalies=[anomaly(mid, 12, 12, "acc")], sbas=[dict(run_, area="WAAS (CONUS)")])
    ev = effects(run(obs, kp_series({"09": 5.333})))
    a = [e for e in ev if e["cells"]][0]
    assert field(a, "verdict") == "benign_natural" and rule(a, "verdict") == "N1"
    assert [o["id"] for o in obs if o["kind"] == "adsb_sbas"][0] in a["context"]


def test_verdict_precedence_and_invariants():
    hi = h3.latlng_to_cell(60.0, -100.0, 2)
    lat, lon = ll(hi)
    obs = from_file(anomalies=[anomaly(hi, 10, 10, "acc")]) + E.faa_observations(DAY, [faa(lat, lon)])
    e = effects(run(obs, kp_series({"09": 6.0})))[0]
    assert field(e, "verdict") == "planned"                                  # a matched notice outranks the storm
    assert e["exclusions"]["space_weather"][0] == "benign_natural"           # but both checks are recorded
    ev = run(from_file(anomalies=[anomaly(C0, 3, 4), anomaly(hi, 10, 10, "acc")], bursts=[burst(C0, "05:00Z", "05:09Z")],
                       sbas=[{"area": "EGNOS (Europe)", "start": 1, "end": 1, "state": "outage"}]), kp_series({"09": 6.0}))
    for e in ev:
        assert field(e, "attribution_status") != "attributed"
        assert field(e, "localization_error_km") is None and rule(e, "localization_error_km") == "L0"
        assert field(e, "signal_type") in E.SIGNAL and field(e, "support") in E.SUPPORT and field(e, "verdict") in E.VERDICT
        assert field(e, "verdict") != "deliberate_suspected"                 # no interference-warning input yet
        for name, g in e["grades"].items():
            assert len(g) == 4 and g[1] and g[2], (name, g)                  # value, rule, reason, basis
    # ids are deterministic
    a = [e["id"] for e in run(from_file(bursts=[burst(C0, "10:00Z", "10:05Z")]))]
    b = [e["id"] for e in run(from_file(bursts=[burst(C0, "10:00Z", "10:05Z")]))]
    assert a == b and a[0].startswith("EV-20260310-")


# ---------------------------------------------------------------- level check
def test_level_observations():
    kids = sorted(h3.cell_to_children(C0, 4))
    other = sorted(h3.cell_to_children(RING2[0], 4))
    rows = []
    for c in kids[:3]:                                  # 3 hexes at score 100 x (3 - 1) / 10 = 20: one observation
        la, lo = h3.cell_to_latlng(c)
        rows.append({"h3": c, "lat": la, "lon": lo, "aircraft": 10, "bad_nacp": 9, "bad_nacp_live": 3})
    la, lo = h3.cell_to_latlng(kids[3])
    rows.append({"h3": kids[3], "lat": la, "lon": lo, "aircraft": 4, "bad_nacp": 4, "bad_nacp_live": 4})   # < 5 aircraft
    for c in other[:2]:                                 # only 2 hexes in this region: none
        la, lo = h3.cell_to_latlng(c)
        rows.append({"h3": c, "lat": la, "lon": lo, "aircraft": 10, "bad_nacp": 3, "bad_nacp_live": None})
    out = E.level_observations(DAY, rows)
    assert len(out) == 1 and out[0]["cells"] == [C0] and out[0]["detail"]["jam_hexes"] == 3
    assert out[0]["detail"]["hexes_5plus"] == 3 and (out[0]["t0"], out[0]["t1"]) == (0, 1439)
    # score uses live counts: 10 aircraft, 1 live bad -> 0, even with many raw bad (post-exposure) reports
    rows = [dict(r, bad_nacp_live=1) for r in rows[:3]]
    assert E.level_observations(DAY, rows) == []


# ---------------------------------------------------------------- register round trip
def test_register_roundtrip():
    tmp = tempfile.mkdtemp()
    old = E.REGISTER
    try:
        E.REGISTER = os.path.join(tmp, "register.sqlite")
        db = E.connect()
        nxt = "2026-03-11"
        far = h3.latlng_to_cell(30.0, 40.0, 2)
        for day in (DAY, nxt):
            # the same region at jamming scale on both days, plus an unrelated 10 m anomaly far away each day
            lvl = E.obs(day, "adsb_level", "EFFECT", "adsb", 0, 1439, "day", *ll(C0), [C0], measure="gross",
                        detail={"jam_hexes": 4, "hexes_5plus": 9, "share": 30.0}, key=C0)
            obs = [lvl] + E.observations_from_events_file(day, {"anomalies": [anomaly(far, 10, 11, "acc")], "bursts": [],
                                                                "sbas": []}, "test")
            kp = kp_series(day=day)
            obs += E.kp_observations(day, kp)
            E.write_day(db, day, obs, E.build_day(day, obs, kp), {"events_src": "test", "kp": "max 1.0"})
        E.episodes(db)
        db.commit()
        rows = db.execute("SELECT id, episode_id, episode_days, episode_index FROM events WHERE regions=1 AND "
                          "effect_measure='gross' ORDER BY day").fetchall()
        assert len(rows) == 2 and rows[0][1] == rows[1][1] and rows[0][2] == 2 and [r[3] for r in rows] == [1, 2], rows
        assert db.execute("SELECT COUNT(*) FROM events WHERE effect_measure='capable' AND episode_id IS NULL").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM grades").fetchone()[0] == 20
        assert db.execute("SELECT COUNT(*) FROM exclusions WHERE cause='receiver_fault'").fetchone()[0] == 4
        # rebuilding a day replaces its rows
        obs = E.observations_from_events_file(DAY, {"anomalies": [], "bursts": [burst(C0, "01:00Z", "01:05Z")], "sbas": []}, "t")
        E.write_day(db, DAY, obs, E.build_day(DAY, obs, kp_series()), {})
        assert db.execute("SELECT COUNT(*) FROM events WHERE day=?", (DAY,)).fetchone()[0] == 1
        db.commit()
        db.close()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            E.cmd_show(argparse.Namespace(day=nxt, event=None, limit=5, full=True))
            E.cmd_stats(argparse.Namespace())
        out = buf.getvalue()
        assert "rule S1" in out and "verdict" in out and "register: 3 events" in out, out[:2000]
    finally:
        E.REGISTER = old
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"test_events: ok ({len(tests)} tests)")


if __name__ == "__main__":
    main()
