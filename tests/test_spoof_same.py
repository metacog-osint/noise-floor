"""Offline tests for tools/spoof_same.py on small synthetic output folders (no spoof_day run needed).

Run:  python tests/test_spoof_same.py   (or pytest)
"""
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
import spoof_same as SS  # noqa: E402

DAY = "2026-01-02"


def write_out(folder, events=None, rows=None, summary=None):
    os.makedirs(folder, exist_ok=True)
    events = events if events is not None else [{"icao": "aaa001", "start": "2026-01-02T01:00:00Z", "alt": 36000, "kinds": ["slow"]},
                                                {"icao": "aaa002", "start": "2026-01-02T02:00:00Z", "alt": 25000.5, "kinds": ["loiter"]}]
    with gzip.open(os.path.join(folder, f"{DAY}.events.json.gz"), "wt", encoding="utf-8") as f:
        json.dump(events, f)
    rows = rows if rows is not None else [("8a2a1", 1, 3, 1.5), ("8a2a2", 2, 4, float("nan")), ("8a2a3", 0, 9, 2.0)]
    for t in SS.TABLES:
        pq.write_table(pa.table({"h3": [r[0] for r in rows], "hour": pa.array([r[1] for r in rows], pa.int8()),
                                 "aircraft": pa.array([r[2] for r in rows], pa.int32()),
                                 "x": pa.array([r[3] for r in rows], pa.float64())}),
                       os.path.join(folder, f"{DAY}.{t}.parquet"), compression="zstd")
    s = {"day": DAY, "version": "0.6.1", "seconds": 10.0, "seconds_read": 5.0, "cpu_seconds": 40.0, "workers": 7,
         "method": {"A": 1}, "episodes": 2, "aircraft": 100,
         "victim_res2_top": [["c1", 5], ["c2", 3], ["c3", 3]],
         "spoofed_to_res6_top": [["h", 1.0, 2.0, 4], ["i", 1.0, 2.0, 2]]}
    s.update(summary or {})
    with open(os.path.join(folder, f"{DAY}.summary.json"), "w", encoding="utf-8") as f:
        json.dump(s, f)


def test_same_ignores_order_timing_and_nan():
    tmp = tempfile.mkdtemp()
    try:
        a, b = os.path.join(tmp, "a"), os.path.join(tmp, "b")
        write_out(a)
        ev = [{"icao": "aaa002", "kinds": ["loiter"], "alt": 25000.5, "start": "2026-01-02T02:00:00Z"},      # other order, other key order
              {"alt": 36000, "icao": "aaa001", "start": "2026-01-02T01:00:00Z", "kinds": ["slow"]}]
        write_out(b, events=ev, rows=[("8a2a3", 0, 9, 2.0), ("8a2a1", 1, 3, 1.5), ("8a2a2", 2, 4, float("nan"))],
                  summary={"version": "0.6.1+V1", "seconds": 99.0, "seconds_read": 1.0, "cpu_seconds": 3.0, "workers": 1,
                           "method": {"A": 2}, "rerun": {"label": "V1"}, "cache_format": 2, "seconds_parts": {"scoring": 1}})
        rep = SS.compare(a, b)
        assert rep["same"] and rep["days"][DAY]["events"] == "same" and rep["days"][DAY]["hex4"] == "same", rep
        assert rep["days"][DAY]["seconds_a"] == 10.0 and rep["days"][DAY]["cpu_seconds_b"] == 3.0
    finally:
        shutil.rmtree(tmp)


def test_real_differences_are_found():
    tmp = tempfile.mkdtemp()
    try:
        a = os.path.join(tmp, "a")
        write_out(a)
        cases = {
            "events": dict(events=[{"icao": "aaa001", "start": "2026-01-02T01:00:00Z", "alt": 36000, "kinds": ["slow"]}]),
            "event field": dict(events=[{"icao": "aaa001", "start": "2026-01-02T01:00:00Z", "alt": 36000, "kinds": ["slow"]},
                                        {"icao": "aaa002", "start": "2026-01-02T02:00:00Z", "alt": 25000.5, "kinds": ["slow"]}]),
            "table value": dict(rows=[("8a2a1", 1, 3, 1.5), ("8a2a2", 2, 5, float("nan")), ("8a2a3", 0, 9, 2.0)]),
            "table rows": dict(rows=[("8a2a1", 1, 3, 1.5)]),
            "summary value": dict(summary={"episodes": 3}),
            "top list": dict(summary={"victim_res2_top": [["c9", 5], ["c2", 3], ["c3", 3]]}),
        }
        for name, kw in cases.items():
            b = os.path.join(tmp, "b-" + name.replace(" ", "-"))
            write_out(b, **kw)
            rep = SS.compare(a, b)
            assert not rep["same"] and rep["real_differences"] == [DAY], (name, rep)
        os.remove(os.path.join(tmp, "b-events", f"{DAY}.hex2.parquet"))
        assert SS.compare(a, os.path.join(tmp, "b-events"))["days"][DAY]["missing"]["b"] == [f"{DAY}.hex2.parquet"]
        assert not SS.compare(a, os.path.join(tmp, "nowhere"))["same"]
    finally:
        shutil.rmtree(tmp)


def test_top_list_classes():
    top = lambda *e: [list(x) for x in e]
    a = top(("c1", 5), ("c2", 3), ("c3", 3))
    assert SS.top_compare(a, top(("c1", 5), ("c2", 3), ("c3", 3))) == "same"
    assert SS.top_compare(a, top(("c1", 5), ("c3", 3), ("c2", 3))) == "tie-order"
    assert SS.top_compare(a, top(("c3", 3), ("c1", 5), ("c2", 3))) == "differs", "a lower count ranked first is not a tie"
    # cut at 3 entries: the entries tied at the cut count differ, everything above it agrees
    assert SS.top_compare(top(("c1", 5), ("c2", 3), ("c3", 3)), top(("c1", 5), ("c2", 3), ("c4", 3))) == "tie-at-cut"
    assert SS.top_compare(top(("c1", 5), ("c2", 3), ("c3", 3)), top(("c9", 5), ("c2", 3), ("c3", 3))) == "differs"
    assert SS.top_compare(top(("c1", 5), ("c2", 3)), top(("c1", 5), ("c2", 4))) == "differs"
    assert SS.top_compare([["h", 1.0, 2.0, 4]], [["h", 1.0, 2.0, 4]]) == "same", "count last in six-column entries"


def test_ties_are_reported_but_do_not_fail():
    tmp = tempfile.mkdtemp()
    try:
        a, b = os.path.join(tmp, "a"), os.path.join(tmp, "b")
        write_out(a)
        write_out(b, summary={"victim_res2_top": [["c1", 5], ["c3", 3], ["c2", 3]]})
        rep = SS.compare(a, b)
        assert rep["same"] and rep["tie_days"] == [DAY] and rep["days"][DAY]["ties"] == {"victim_res2_top": "tie-order"}, rep
        write_out(b, summary={"victim_res2_top": [["c1", 5], ["c2", 3], ["c4", 3]]})
        rep = SS.compare(a, b)
        assert rep["same"] and rep["days"][DAY]["ties"] == {"victim_res2_top": "tie-at-cut"}
    finally:
        shutil.rmtree(tmp)


def test_exit_status():
    tmp = tempfile.mkdtemp()
    try:
        a, b, c = (os.path.join(tmp, n) for n in "abc")
        write_out(a); write_out(b); write_out(c, summary={"aircraft": 101})
        script = os.path.join(ROOT, "tools", "spoof_same.py")
        ok = subprocess.run([sys.executable, script, a, b, "--quiet"], capture_output=True, text=True)
        bad = subprocess.run([sys.executable, script, a, c, "--quiet", "--json", os.path.join(tmp, "r.json")],
                             capture_output=True, text=True)
        assert ok.returncode == 0 and "no real difference" in ok.stdout, ok.stdout
        assert bad.returncode == 1 and "REAL DIFFERENCE" in bad.stdout, bad.stdout
        assert json.load(open(os.path.join(tmp, "r.json")))["real_differences"] == [DAY]
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
