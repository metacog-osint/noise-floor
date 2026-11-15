"""Tests for tools/spoof_summary.py's spoofed-to clusters (<day>.spoof-targets.json). Run as a plain script."""
import gzip
import json
import math
import os
import random
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import spoof_summary as SS  # noqa: E402


def on_ring(lat, lon, r_km, brg):
    """The point r_km from (lat, lon) on bearing brg (degrees), on a sphere."""
    R = 6371.0
    p1, l1, b, d = math.radians(lat), math.radians(lon), math.radians(brg), r_km / R
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), math.degrees(l2)


def episode(icao, lat, lon, cls="active", start="2026-11-12T04:00:00Z", end="2026-11-12T04:05:00Z", cells=(), kinds=("slow",)):
    return {"icao": icao, "type": "A320", "cat": "A3", "class": cls, "start": start, "end": end, "false_lat": round(lat, 4),
            "false_lon": round(lon, 4), "alt": 36000, "kinds": list(kinds), "clean_share": 1.0, "mlat_dis": 0,
            "victim_cells": list(cells)}


def ring(lat, lon, n, r_km=1.0, prefix="r", **kw):
    return [episode(f"{prefix}{k:03d}", *on_ring(lat, lon, r_km, 360.0 * k / n), **kw) for k in range(n)]


def test_ring_is_one_cluster():
    """A ring of about 1 km radius (points 0.6-1.9 km from its centre) is one cluster, wherever it sits on the H3 grid."""
    rnd = random.Random(7)
    for _ in range(60):
        lat, lon = rnd.uniform(-60, 70), rnd.uniform(-180, 180)
        ev = [episode(f"a{k}", *on_ring(lat, lon, rnd.uniform(0.6, 1.9), rnd.uniform(0, 360))) for k in range(15)]
        groups = SS.targets(ev)
        assert len(groups) == 1 and len(groups[0]) == 15, (lat, lon, [len(g) for g in groups])


def test_lima_like_day():
    import h3
    hu, sk = h3.latlng_to_cell(47.5, 21.5, 4), h3.latlng_to_cell(48.7, 21.3, 4)
    lima = ring(-12.040, -77.050, 12, cells=[hu])
    lima[0]["victim_cells"] = [hu, sk]
    lima[1]["victim_cells"] = []                              # unlocated
    lima[1]["class"] = "unlocated"
    lima.append(episode("r000", *on_ring(-12.040, -77.050, 1.0, 10), start="2026-11-12T20:00:00Z",
                        end="2026-11-12T20:01:00Z", cells=[sk], kinds=("loiter",)))   # same aircraft again
    other = ring(47.959, 23.276, 4, prefix="o", cells=[hu])     # the second, smaller ring in Romania
    far = [episode("z1", 60.12, 31.38, cls="post"), episode("z2", 60.12 + 0.2, 31.38)]   # ~22 km apart: two clusters
    replay = [episode("q1", 29.2, -82.9, cls="replay")]
    ev = lima + other + far + replay
    d = SS.target_summary("2026-11-12", ev, {"version": "0.5"})
    assert d["episodes"] == len(ev) and d["clustered"] == len(ev) - 1 and d["left_out"]["replay"] == 1
    cl = d["clusters"]
    assert [c["episodes"] for c in cl] == [13, 4, 1, 1], [c["episodes"] for c in cl]
    top = cl[0]
    assert SS.km(top["lat"], top["lon"], -12.040, -77.050) < 0.3, (top["lat"], top["lon"])
    assert 0.8 <= top["r50_km"] <= 1.1 and top["r90_km"] <= 1.1
    assert top["aircraft"] == 12 and top["located"] == 12
    assert top["classes"] == {"active": 12, "unlocated": 1}
    assert top["kinds"] == {"loiter": 1, "slow": 12}
    assert top["first"] == "2026-11-12T04:00:00Z" and top["last"] == "2026-11-12T20:01:00Z"
    # true-position cells: [cell, episodes, distinct aircraft]; both sk episodes are aircraft r000
    assert top["victim_cells"] == [[hu, 11, 11], [sk, 2, 1]], top["victim_cells"]
    assert top["alt_ft"] == [36000, 36000] and top["clean"] == 13
    assert SS.km(cl[1]["lat"], cl[1]["lon"], 47.959, 23.276) < 0.3
    # aggregates only: no addresses, types or exact times of single episodes beyond first/last
    text = json.dumps(d)
    for e in ev:
        assert e["icao"] not in text
    assert "A320" not in text


def test_deterministic():
    rnd = random.Random(3)
    ev = (ring(-12.04, -77.05, 9) + ring(55.98, 37.42, 7, r_km=2.0, prefix="m")
          + [episode(f"s{k}", rnd.uniform(50, 60), rnd.uniform(15, 35)) for k in range(80)])
    a = SS.target_summary("d", ev)
    rnd.shuffle(ev)
    b = SS.target_summary("d", ev)
    assert a == b


def test_write_keeps_old_fields():
    """<day>.spoof.json keeps every field it had and gains targets_file; the companion file is written beside it."""
    tmp = tempfile.mkdtemp()
    try:
        ev = ring(-12.04, -77.05, 5)
        with gzip.open(os.path.join(tmp, "2026-11-12.events.json.gz"), "wt", encoding="utf-8") as f:
            json.dump(ev, f)
        with open(os.path.join(tmp, "2026-11-12.summary.json"), "w", encoding="utf-8") as f:
            json.dump({"version": "0.5", "episodes": 5, "episodes_by_class": {"active": 5},
                       "spoofed_to_res6_top": [["c", -12.04, -77.05, 5]]}, f)
        p, d, pt = SS.write(tmp, "2026-11-12", os.path.join(tmp, "out"))
        old = {"day", "version", "licence", "active", "episodes", "classes", "aircraft_with_episodes", "cells",
               "victim_res2_top", "spoofed_to_top", "method"}
        assert old <= set(d) and d["targets_file"] == "2026-11-12.spoof-targets.json"
        assert os.path.basename(pt) == d["targets_file"]
        t = json.load(open(pt, encoding="utf-8"))
        assert t["clusters"][0]["episodes"] == 5 and t["version"] == "0.5"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_empty_day():
    d = SS.target_summary("d", [])
    assert d["clusters"] == [] and d["episodes"] == 0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
