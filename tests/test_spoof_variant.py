"""Offline test for tools/spoof_variant.py: the whole variant score on one synthetic cached day (reruns, the outside
score, the reference check, the report), with the heavy-job lock redirected to a temporary folder.

Run:  python tests/test_spoof_variant.py   (or pytest)
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import heavy_lock  # noqa: E402
import spoof_day as S  # noqa: E402
import spoof_variant as V  # noqa: E402
import test_spoof_day as T  # noqa: E402

DAY = "2024-10-14"


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_main(argv):
    old = sys.argv
    sys.argv = ["spoof_variant.py"] + argv
    try:
        V.main()
    except SystemExit as e:
        return e.code
    finally:
        sys.argv = old
    return None


def test_expand_and_defaults():
    assert V.expand(["2026-11-07:2026-11-09", "2026-11-08", "2025-01-01"]) == ["2026-11-07", "2026-11-08", "2026-11-09", "2025-01-01"]
    assert len(V.TEST_DAYS) == 18 and V.TEST_DAYS[:12] == V.H.DAYS and V.TEST_DAYS[-1] == "2026-11-12"
    assert V.parse_sets(["SLOW_HI_A2_FT=0", "LOITER_KM=4.5"]) == {"SLOW_HI_A2_FT": 0, "LOITER_KM": 4.5}
    src = open(os.path.join(ROOT, "tools", "spoof_variant.py"), encoding="utf-8").read()
    import re
    assert not re.search(r"[A-Za-z]:[\\/]", src), "no drive path in the tool: the outside folder is only ever an argument"


def test_variant_end_to_end():
    tmp = tempfile.mkdtemp()
    os.environ["TIC_HEAVY_LOCK_DIR"] = os.path.join(tmp, "lock")
    try:
        raw, cache, full = T.make_cached_day(tmp, DAY)
        # an outside list: the Lima ring flight, shown at Lima for 60 s from 01:00 + 30 min + 10 s
        t1 = T.DAY0 + 3600 + 30 * 60 + 10
        outside = os.path.join(tmp, "outside")
        os.makedirs(outside)
        feat = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [T.LIMA[1], T.LIMA[0]]},
                "properties": {"icao24": "bbb009", "segment": "during", "timestamp_during_min": iso(t1),
                               "timestamp_during_max": iso(t1 + 60)}}
        json.dump({"type": "FeatureCollection", "features": [feat]}, open(os.path.join(outside, f"spoof_{DAY}.json"), "w"))
        # an earlier output of the same variant, to check against
        ref = os.path.join(tmp, "ref")
        S.rerun(DAY, os.path.join(cache, DAY), ref, 1, {"SLOW_HI_A2_FT": 0}, "V1")
        out = os.path.join(tmp, "out")
        args = ["--set", "SLOW_HI_A2_FT=0", "--label", "V1", "--cache", cache, "--out", out, "--days", DAY, "--workers", "1",
                "--reference", ref, "--outside", outside, f"--at={T.LIMA[0]},{T.LIMA[1]}", "--lima-days", DAY]
        assert run_main(args) == 0
        rep = json.load(open(os.path.join(out, "variant_report.json")))
        assert rep["label"] == "V1" and rep["overrides"] == {"SLOW_HI_A2_FT": 0} and rep["days"] == [DAY]
        row = rep["per_day"][0]
        assert row["day"] == DAY and row["cpu_seconds"] >= 0 and row["candidates"] == 2 and row["aircraft"] == 6, row
        assert row["episodes"] == 1 and row["version"] == "0.6.1-a2-0+V1", row           # the slow A2 is off under V1
        assert set(row["parts"]) == {"records_load", "scoring", "shard_file_read"}
        t = rep["totals"]
        assert t["days"] == 1 and t["cpu_seconds"] >= 0 and t["candidates"] == 2 and t["episodes"] == 1 and t["wall_seconds"] >= 0, t
        assert rep["reference"]["same"] and rep["reference"]["real_differences"] == [], rep["reference"]
        li = rep["lima"]
        assert li["P1"]["placed"] == li["P1"]["placeable"] == 1 and li["P1"]["pass"] and li["P2"]["pass"], li
        assert "heldout" not in rep, "the synthetic day is not a held-out day"
        assert rep["checks"] == {"P1": True, "P2": True}, rep["checks"]
        txt = json.dumps(rep)
        assert "bbb0" not in txt and outside.replace("\\", "/") not in txt.replace("\\", "/"), "no ICAO address, no outside path"
        assert heavy_lock.status()["held"] is False, "lock released"
        # a different variant is a real difference against that reference: exit status 1
        out2 = os.path.join(tmp, "out2")
        S._set_overrides({"SLOW_HI_A2_FT": 36000})
        assert run_main(["--set", "SLOW_HI_A2_FT=25000", "--label", "V0", "--cache", cache, "--out", out2, "--days", DAY,
                         "--workers", "1", "--reference", ref]) == 1
        assert not json.load(open(os.path.join(out2, "variant_report.json")))["reference"]["same"]
        # settings outside the cache envelope are refused before anything runs
        try:
            run_main(["--set", "SLOW_KT=250", "--label", "bad", "--cache", cache, "--out", os.path.join(tmp, "o3"), "--days", DAY])
            raise AssertionError("outside the envelope should be refused")
        except ValueError:
            pass
    finally:
        S._set_overrides({"SLOW_HI_A2_FT": 36000})
        os.environ.pop("TIC_HEAVY_LOCK_DIR", None)
        shutil.rmtree(tmp)


def test_heldout_extras():
    """H7 and H8 from folders of synthetic episodes and summaries."""
    tmp = tempfile.mkdtemp()
    try:
        import gzip
        base, out = os.path.join(tmp, "base"), os.path.join(tmp, "out")
        for d in (base, out):
            os.makedirs(d)
        box = {"victim_cells": [], "class": "isolated"}
        ep = {"icao": "aaa001", "start": "2025-01-01T01:00:00Z", "end": "2025-01-01T01:10:00Z", **box}
        for folder, conf, evs in ((base, 100, [ep]), (out, 99, []), ):
            json.dump({"episodes_mlat_confirmed": conf}, open(os.path.join(folder, "2025-01-01.summary.json"), "w"))
            with gzip.open(os.path.join(folder, "2025-01-01.events.json.gz"), "wt") as f:
                json.dump(evs, f)
        lst = [{"day": "2025-01-01", "icao": "aaa001", "cat": "A2", "kinds": ["slow"], "start": ep["start"], "end": ep["end"]},
               {"day": "2025-01-01", "icao": "aaa002", "cat": "A3", "kinds": ["slow"], "start": ep["start"], "end": ep["end"]}]
        json.dump(lst, open(os.path.join(base, "new_controls.json"), "w"))
        r = V.h7_h8(out, base, ["2025-01-01"], None, 99)
        assert r["H8"] == {"confirmed": 99, "baseline": 100, "min": 98, "pass": True}, r
        assert r["H7"] == {"still_present": 0, "of": 1, "pass": True}, r
        assert V.h7_h8(base, base, ["2025-01-01"], None, 97)["H8"]["pass"] is False
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
