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


# ---------------------------------------------------------------- CYGNSS (second sensor family)
ME = h3.latlng_to_cell(26.0, 52.0, 2)          # inside the CYGNSS band (|lat| <= ~38)


def cyg_row(lat, lon, n=40, med=2.0, dropout=None, cell=None):
    c = cell or h3.latlng_to_cell(lat, lon, 3)
    la, lo = h3.cell_to_latlng(c)
    return {"h3": c, "lat": la, "lon": lo, "n": n, "passes": 4, "med_db": med, "p90_db": None if med is None else med + 0.5,
            "frac1": 0.8, "land": 1.0, "dropout": dropout}


def cyg_disk(lat, lon, k, med, n=40):
    """Rows for every res-3 cell within k rings of the point, all with the same median excess."""
    return [cyg_row(0, 0, n=n, med=med, cell=c) for c in sorted(h3.grid_disk(h3.latlng_to_cell(lat, lon, 3), k))]


def run_cyg(adsb_obs, rows, kp="quiet"):
    k = kp_series() if kp == "quiet" else kp
    obs = adsb_obs + E.cygnss_observations(DAY, rows, "test") + E.kp_observations(DAY, k)
    return E.build_day(DAY, obs, k, E.cygnss_field(rows)), obs


def test_cygnss_observations():
    rows = [cyg_row(25, 55, n=20, med=1.0),            # exactly at both thresholds: noise
            cyg_row(25, 57, n=19, med=3.0),            # too few DDMs
            cyg_row(25, 59, n=40, med=0.99),           # below 1 dB
            cyg_row(25, 61, n=5, med=None, dropout=0.5),   # dropout at the threshold
            cyg_row(25, 63, n=40, med=0.2, dropout=0.49)]
    out = E.cygnss_observations(DAY, rows)
    assert [o["kind"] for o in out] == ["cygnss_noise", "cygnss_dropout"], [o["kind"] for o in out]
    o = out[0]
    assert o["family"] == "cygnss" and o["sensor"] and o["signal_type"] == "EFFECT" and o["measure"] == "rf"
    assert o["cells"] == [h3.cell_to_parent(rows[0]["h3"], 2)] and (o["t0"], o["t1"], o["time_res"]) == (0, 1439, "day")
    f = E.cygnss_field(rows)                           # judged cells only (20+ DDMs)
    assert sum(len(v) for v in f.values()) == 3


def test_cygnss_multiple_sources():
    lat, lon = ll(ME)
    gross = from_file(anomalies=[anomaly(ME, 10, 11, "jam")])
    # a raised neighbourhood: every res-3 cell within ~2 rings at +2 dB
    ev, obs = run_cyg(list(gross), cyg_disk(lat, lon, 2, 2.0))
    e = [x for x in effects(ev) if x["effect_measure"] == "gross"][0]
    assert field(e, "support") == "Multiple sources" and rule(e, "support") == "S3", e["grades"]["support"]
    basis = set(e["grades"]["support"][3])
    assert all(o["detail"]["n"] >= E.CYG_MIN_DDM for o in obs if o["id"] in basis and o["family"] == "cygnss")
    assert field(e, "verdict") == "open"               # two sensors agreeing is support, not a verdict
    # one raised cell in a quiet neighbourhood: linked and fused, but the field median is below 1 dB -> no S3
    rows = cyg_disk(lat, lon, 3, 0.0)
    rows[[r["h3"] for r in rows].index(h3.latlng_to_cell(lat, lon, 3))]["med_db"] = 3.0
    ev, obs = run_cyg(list(gross), rows)
    e = [x for x in effects(ev) if x["effect_measure"] == "gross"][0]
    raised = [o["id"] for o in obs if o["kind"] == "cygnss_noise"]
    assert raised and raised[0] in e["members"] and field(e, "support") == "Single-source, unverified"
    assert "no pair agrees" in e["grades"]["support"][2]
    # a 10 m-only ADS-B observation never makes Multiple sources with CYGNSS (it pairs at the chance rate)
    ev, _ = run_cyg(from_file(anomalies=[anomaly(ME, 10, 11, "acc")]), cyg_disk(lat, lon, 2, 2.0))
    assert "Multiple sources" not in [field(x, "support") for x in effects(ev)]


def test_cygnss_fusion_distance():
    lat, lon = ll(ME)
    gross = from_file(anomalies=[anomaly(ME, 10, 11, "jam")])
    near_ = [cyg_row(lat + 250 / 111.2, lon)]          # ~250 km north: links (300 km rule), and its field is raised
    ev, _ = run_cyg(list(gross), near_)
    assert len(effects(ev)) == 1 and field(effects(ev)[0], "support") == "Multiple sources"
    far_ = [cyg_row(lat + 420 / 111.2, lon)]           # ~420 km: no link, two events, no S3
    ev, _ = run_cyg(list(gross), far_)
    assert len(effects(ev)) == 2 and all(field(x, "support") == "Single-source, unverified" for x in effects(ev))
    # a CYGNSS cell between two separate ADS-B events attaches to one of them; it never bridges the two
    import math
    east = h3.latlng_to_cell(lat, lon + 560 / (111.2 * math.cos(math.radians(lat))), 2)   # not adjacent, under the cap
    two = from_file(anomalies=[anomaly(ME, 10, 11, "jam"), anomaly(east, 10, 11, "jam")])
    k = 111.2 * math.cos(math.radians(lat))
    mid = [cyg_row(lat, lon + 150 / k), cyg_row(lat, lon + 400 / k)]   # a chain: A - cell - cell - B
    ev, _ = run_cyg(list(two), mid)
    gross_events = [x for x in effects(ev) if x["effect_measure"] == "gross"]
    assert len(gross_events) == 2, [x["members"] for x in effects(ev)]
    # dropouts are placed by the spacecraft: they never fuse with ADS-B and never count toward support
    drop = [cyg_row(lat, lon, n=5, med=None, dropout=0.9)]
    ev, _ = run_cyg(list(gross), drop)
    assert len(effects(ev)) == 2
    d = [x for x in effects(ev) if x["effect_measure"] == "dropout"][0]
    assert field(d, "support") == "Single-source, unverified" and "don't count" in d["grades"]["support"][2]
    # CYGNSS alone is one sensor family; storms never excuse an RF observation
    ev, _ = run_cyg([], cyg_disk(lat, lon, 1, 2.0), kp_series({"09": 8.667}))
    e = effects(ev)[0]
    assert field(e, "support") == "Single-source, unverified" and field(e, "verdict") == "open" and e["effect_measure"] == "rf"
    assert e["exclusions"]["space_weather"][0] == "not_applicable" and e["open_hint"] is None


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


# ---------------------------------------------------------------- v1.0: FL250 radius, notices (D1), scintillation (N3)
def test_faa_radius_fl250():
    lat, lon = ll(C0)
    t = faa(lat, lon)
    t["radii_nm"] = {"50FT AGL": 30, "FL250": 50, "FL400": 100}
    o = E.faa_observations(DAY, [t])[0]
    assert o["detail"]["radius_km"] == 92.6 and o["detail"]["radius_ring"] == "FL250", o["detail"]
    assert E.faa_observations(DAY, [faa(lat, lon)])[0]["detail"]["radius_ring"] == "widest"   # no FL250 ring
    # a burst ~150 km out: inside the FL400 ring (185 km), outside the FL250 ring (93 km) -> not planned
    at = (lat, lon + 2.35)
    d = E.km(at, (lat, lon))
    assert 100 < d < 180, d
    ev = effects(run(from_file(bursts=[burst(h3.latlng_to_cell(*at, 2), "10:30Z", "10:40Z", at=at)]) + [o]))
    assert [field(e, "verdict") for e in ev] == ["open"]
    t["radii_nm"] = {"FL400": 100}                                            # widest ring: planned
    ev = effects(run(from_file(bursts=[burst(h3.latlng_to_cell(*at, 2), "10:30Z", "10:40Z", at=at)])
                     + E.faa_observations(DAY, [t])))
    assert [field(e, "verdict") for e in ev] == ["planned"]


def test_notice_parsing():
    assert E.notice_class("GPS JAMMING REPORTED IN AREA") == "jamming"
    assert E.notice_class("GNSS SPOOFING HAS BEEN REPORTED") == "jamming"
    assert E.notice_class("GPS UNRELIABLE IN VICINITY MALTA") == "interference"
    assert E.notice_class("GPS JAMMING EXERCISE 0600Z TO 1800Z") == "test"     # test wording wins
    assert E.notice_class("GPS SIGNALS MAY BE UNRELIABLE DUE TO TESTING") == "test"
    assert E.notice_class("LATEST GPS INTERFERENCE REPORTS") == "interference"  # LATEST is not TEST
    assert E.notice_class("JAMMING OF RADIO COMMUNICATIONS") == "other"        # no GNSS word
    assert E.notice_class("DERELICT VESSEL") == "other"
    assert E.notice_positions("IN VICINITY MALTA (35-53N 014-27E).") == [(35.8833, 14.45)]
    assert E.notice_positions("A. 19-23.0N 092-03.1W. B. 59-30-15N 024-10-00E") == [(19.3833, -92.0517), (59.5042, 24.1667)]
    assert E.notice_positions("12-75N 010-00E") == []                           # minutes must be < 60
    assert E.notice_radius_km("WITHIN 25 NM OF 35-53N 014-27E") == 46.3
    assert E.notice_radius_km("A 10 MILE RADIUS OF") == 18.5
    assert E.notice_radius_km("WITHIN 40 KM OF") == 40.0 and E.notice_radius_km("AREA BOUND BY") is None
    sq = [(54.0, 19.0), (54.0, 21.0), (56.0, 21.0), (56.0, 19.0)]
    assert E.in_polygon(55.0, 20.0, sq) and not E.in_polygon(57.0, 20.0, sq)


def notice(text, nid="NOTICE 1/26", valid_from="2026-03-01T00:00Z", valid_to=None, **kw):
    return {"id": nid, "source": nid, "url": "https://example.invalid/n", "issued_utc": valid_from,
            "valid_from_utc": valid_from, "valid_to_utc": valid_to, "text": text, **kw}


def notice_obs(*items, day=DAY):
    tmp = tempfile.mkdtemp()
    try:
        p = os.path.join(tmp, "notices.json")
        with open(p, "w", encoding="utf-8") as f:
            import json
            json.dump({"notices": list(items)}, f)
        return E.notice_observations(day, E.load_notices(p))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_notice_rules():
    lat, lon = ll(C0)
    pos = f"{int(lat):02d}-{round((lat % 1) * 60):02d}N {int(lon):03d}-{round((lon % 1) * 60):02d}E"
    jam = notice_obs(notice(f"BALTIC SEA. GPS JAMMING REPORTED WITHIN 50 NM OF {pos}."))
    assert len(jam) == 1 and jam[0]["detail"]["class"] == "jamming" and jam[0]["detail"]["radius_km"] == 92.6
    assert (jam[0]["t0"], jam[0]["t1"]) == (0, 1439)                       # in force all day
    ev = run(from_file(bursts=[burst(C0, "10:30Z", "10:40Z")]) + jam)
    e = effects(ev)[0]
    assert field(e, "verdict") == "deliberate_suspected" and rule(e, "verdict") == "D1", e["grades"]["verdict"]
    assert field(e, "support") == "Partially corroborated" and rule(e, "support") == "S2"
    assert field(e, "attribution_status") == "none"                           # D1 names no source
    assert e["exclusions"]["notice"][:2] == ("jamming_reported", "D1") and jam[0]["id"] in e["members"]
    assert not [x for x in ev if field(x, "signal_type") == "WARNING"]
    # an interference notice corroborates but doesn't make the verdict
    intf = notice_obs(notice(f"GPS UNRELIABLE IN VICINITY ({pos})."))
    assert intf[0]["detail"]["radius_km"] == E.NOTICE_POINT_KM and not intf[0]["detail"]["radius_stated"]
    e = effects(run(from_file(bursts=[burst(C0, "10:30Z", "10:40Z")]) + intf))[0]
    assert field(e, "verdict") == "open" and e["open_hint"] == "notice_interference" and rule(e, "support") == "S2"
    assert e["exclusions"]["notice"][:2] == ("interference_reported", "D-")
    # test notices, unplaced notices and notices out of force make no observation
    assert notice_obs(notice(f"GPS JAMMING EXERCISE WITHIN 50 NM OF {pos}")) == []
    assert notice_obs(notice("GPS JAMMING REPORTED IN THE EASTERN BALTIC")) == []
    assert notice_obs(notice(f"GPS JAMMING WITHIN 50 NM OF {pos}", valid_to="2026-03-09T12:00Z")) == []
    assert notice_obs(notice(f"GPS JAMMING WITHIN 50 NM OF {pos}", valid_from="2026-03-11T00:00Z")) == []
    part = notice_obs(notice(f"GPS JAMMING WITHIN 50 NM OF {pos}", valid_from="2026-03-10T12:00Z"))
    assert (part[0]["t0"], part[0]["t1"]) == (720, 1439)
    assert field(effects(run(from_file(bursts=[burst(C0, "10:30Z", "10:40Z")]) + part))[0], "verdict") == "open"
    # out of place: no attachment, and an unmatched notice makes no event of its own
    away = h3.latlng_to_cell(55.0, 26.5, 2)
    ev = run(from_file(bursts=[burst(away, "10:30Z", "10:40Z")]) + jam)
    assert [field(e, "verdict") for e in effects(ev)] == ["open"] and not [x for x in ev if jam[0]["id"] in x["members"]]
    # polygon: inside counts with no radius
    poly = notice_obs(notice("GPS JAMMING IN AREA BOUND BY 54-00N 019-00E, 54-00N 021-30E, 56-30N 021-30E, 56-30N 019-00E."))
    assert poly[0]["detail"]["polygon"] and poly[0]["detail"]["radius_km"] is None
    assert field(effects(run(from_file(bursts=[burst(C0, "10:30Z", "10:40Z")]) + poly))[0], "verdict") == "deliberate_suspected"
    # "shape": "points": circles around each point, not a polygon (a burst at the centre of a 3-point line is covered
    # by the polygon test only if it falls inside the triangle; here it sits on the first point)
    line = notice_obs(notice("GPS JAMMING ALONG THE GULF", points=[[lat, lon], [lat + 0.5, lon + 3.0], [lat - 0.4, lon + 6.0]],
                             radius_km=30, shape="points"))
    assert not line[0]["detail"]["polygon"] and line[0]["detail"]["radius_km"] == 30
    assert field(effects(run(from_file(bursts=[burst(C0, "10:30Z", "10:40Z")]) + line))[0], "verdict") == "deliberate_suspected"
    # a matched announced test outranks D1; the notice check records it
    tests = E.faa_observations(DAY, [faa(lat, lon)])
    e = effects(run(from_file(bursts=[burst(C0, "10:30Z", "10:40Z")]) + tests + jam))[0]
    assert field(e, "verdict") == "planned" and e["exclusions"]["notice"][2]["outranked_by"] == "P1"
    # a CYGNSS-only event never reaches D1 (timed to the day only)
    rows = [cyg_row(lat, lon, med=3.0)]
    ev = E.build_day(DAY, E.cygnss_observations(DAY, rows) + jam, kp_series(), E.cygnss_field(rows))
    assert all(field(x, "verdict") != "deliberate_suspected" for x in ev)


def test_easa_d1():
    """v1.1: an EASA 7-day table with spoofing in every FIR of a stand-in area makes a week-long notice; an effect inside
    the outline that week is deliberate_suspected (D1), one outside or another week is not."""
    import json
    lat, lon = ll(C0)
    tmp = tempfile.mkdtemp()
    try:
        easa, fir = os.path.join(tmp, "easa"), os.path.join(tmp, "fir.json")
        os.makedirs(easa)
        box = [[lat - 1.5, lon - 2.5], [lat - 1.5, lon + 2.5], [lat + 1.5, lon + 2.5], [lat + 1.5, lon - 2.5]]
        json.dump({"areas": {"AAA": {"name": "Test land", "firs": ["XXXX"], "rings": [box]},
                             "TWO": {"name": "Split land", "firs": ["YYYY", "ZZZZ"], "rings": [box]}}}, open(fir, "w"))
        table = {"days": 7, "date": "2026-03-12", "firs": [
            {"icao": "XXXX", "name": "Test", "spoofing": True, "reported": False},
            {"icao": "YYYY", "name": "Half", "spoofing": True, "reported": True},
            {"icao": "ZZZZ", "name": "Other half", "spoofing": False, "reported": True}]}
        for name in ("a.json", "b.json"):                                        # the same table in two copies counts once
            json.dump({"url": "https://example.invalid/easa", "tables": [table, dict(table, days=30)]},
                      open(os.path.join(easa, name), "w"))
        ns = E.load_easa_notices(easa, fir)
        assert [n["id"] for n in ns] == ["EASA-2026-03-12-AAA"]                  # TWO needs both of its FIRs marked
        n = ns[0]
        assert (n["valid_from_utc"], n["valid_to_utc"]) == ("2026-03-06T00:00Z", "2026-03-12T23:59Z")
        assert n["class"] == "jamming" and n["easa"]["reported"] is False
        obs = E.notice_observations(DAY, ns)
        assert len(obs) == 1 and obs[0]["detail"]["rings"] == [box] and (obs[0]["t0"], obs[0]["t1"]) == (0, 1439)
        e = effects(run(from_file(bursts=[burst(C0, "10:30Z", "10:40Z")]) + obs))[0]
        assert field(e, "verdict") == "deliberate_suspected" and rule(e, "verdict") == "D1"
        assert "EASA" in e["grades"]["verdict"][1 + 1] and e["exclusions"]["notice"][2]["notices"][0]["easa"]["area"] == "AAA"
        away = h3.latlng_to_cell(lat, lon + 8.0, 2)
        assert field(effects(run(from_file(bursts=[burst(away, "10:30Z", "10:40Z")]) + obs))[0], "verdict") == "open"
        assert E.notice_observations("2026-03-13", ns) == [] and E.notice_observations("2026-03-05", ns) == []
        rows = [cyg_row(lat, lon, med=3.0)]                                       # CYGNSS only: timed to the day
        ev = E.build_day(DAY, E.cygnss_observations(DAY, rows) + obs, kp_series(), E.cygnss_field(rows))
        e = effects(ev)[0]
        assert field(e, "verdict") == "open" and e["open_hint"] == "notice_untimed" and "EASA" in e["grades"]["verdict"][2]
        assert E.load_easa_notices(os.path.join(tmp, "none"), fir) == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def ism_dir(s4=0.6, sp=0.1, hour="2026031010", cells=((55.0, 20.0), (55.0, 22.5), (40.0, 0.0))):
    """A tiny nowcast archive: a three-cell grid and one hour with the given S4 and sigma-phi in the first cell."""
    import gzip
    tmp = tempfile.mkdtemp()
    os.makedirs(os.path.join(tmp, "ism", hour[:4], hour[4:6]))
    with open(os.path.join(tmp, "ism", "grid.csv"), "w", encoding="utf-8") as f:
        f.write("lon,lat\n" + "".join(f"{lo},{la}\n" for la, lo in cells))
    rows = [f"{int(s4 * 1000)},5,{int(sp * 1000)},5,20,2"] + ["50,5,40,5,20,2"] * (len(cells) - 1)
    with gzip.open(os.path.join(tmp, "ism", hour[:4], hour[4:6], f"ism_{hour[:8]}T{hour[8:]}Z.csv.gz"), "wt") as f:
        f.write("s4,s4_err,sigma_phi,sigma_phi_err,tec,tec_err\n" + "\n".join(rows) + "\n")
    return tmp


def run_ism(observations, tmp):
    k = kp_series()
    return E.build_day(DAY, observations + E.kp_observations(DAY, k), k, None, E.load_ism(tmp))


def test_scintillation_n3():
    tmp = ism_dir()
    try:
        ism = E.load_ism(tmp)
        assert len(ism.hours) == 1 and len(ism.cells) == 3
        assert ism.near(DAY, 600, 659, [(55.0, 20.0)])["s4"] == 0.6           # 10:00-10:59Z overlaps the 10Z hour
        assert ism.near(DAY, 840, 900, [(55.0, 20.0)]) is None                 # 14Z: more than 1 h away
        assert ism.near(DAY, 600, 659, [(40.0, 40.0)]) is None                 # no cell within 300 km
        e = effects(run_ism(from_file(anomalies=[anomaly(C0, 10, 10, "acc")]), tmp))[0]
        assert field(e, "verdict") == "benign_natural" and rule(e, "verdict") == "N3", e["grades"]["verdict"]
        assert e["exclusions"]["scintillation"][:2] == ("moderate", "N3")
        # 93 m loss is never excused by scintillation: recorded, verdict stays open
        e = effects(run_ism(from_file(anomalies=[anomaly(C0, 10, 10, "jam")]), tmp))[0]
        assert field(e, "verdict") == "open" and e["exclusions"]["scintillation"][:2] == ("moderate", "N3-")
        # no archived hour near the event: no record
        e = effects(run_ism(from_file(anomalies=[anomaly(C0, 15, 15, "acc")]), tmp))[0]
        assert field(e, "verdict") == "open" and "scintillation" not in e["exclusions"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    tmp = ism_dir(s4=0.3, sp=0.45)                                             # sigma-phi alone reaches moderate
    try:
        e = effects(run_ism(from_file(anomalies=[anomaly(C0, 10, 10, "acc")]), tmp))[0]
        assert rule(e, "verdict") == "N3"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    tmp = ism_dir(s4=0.3, sp=0.2)
    try:
        e = effects(run_ism(from_file(anomalies=[anomaly(C0, 10, 10, "acc")]), tmp))[0]
        assert field(e, "verdict") == "open" and e["exclusions"]["scintillation"][0] == "below_moderate"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert E.load_ism(os.path.join(tempfile.gettempdir(), "no-such-ism-archive")) is None


def test_publish_monthly():
    import json
    tmp = tempfile.mkdtemp()
    old = E.REGISTER
    try:
        E.REGISTER = os.path.join(tmp, "register.sqlite")
        db = E.connect()
        for day in (DAY, "2026-04-02"):
            obs = from_file(bursts=[burst(C0, "10:30Z", "10:40Z")], day=day)
            E.write_day(db, day, obs, E.build_day(day, obs, kp_series(day=day)), {"events_src": "test"})
        db.execute("INSERT OR REPLACE INTO meta VALUES ('version', ?)", (E.VERSION,))
        db.commit()
        db.close()
        out = os.path.join(tmp, "monthly.json")
        with contextlib.redirect_stdout(io.StringIO()):
            E.cmd_publish(argparse.Namespace(out=out))
        d = json.load(open(out, encoding="utf-8"))
        assert d["version"] == E.VERSION and [m["month"] for m in d["months"]] == ["2026-03", "2026-04"]
        m = d["months"][0]
        assert m["days"] == 1 and m["events"] == 1 and m["effect_verdict"]["open"] == 1 and m["signal_type"]["EFFECT"] == 1
        text = json.dumps(d)
        assert '"lat"' not in text and C0 not in text and "OB-" not in text and "EV-" not in text   # aggregates only
        assert any("European Space Agency" in x for x in d["sources"])
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
