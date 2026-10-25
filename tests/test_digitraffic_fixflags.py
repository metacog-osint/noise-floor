"""collectors/digitraffic_ais.py: REST locations -> fixflags rows, the poll timer, and the flush/compact round trip."""
import os, shutil, sys, tempfile, types

import pyarrow.parquet as pq

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "collectors"))
import digitraffic_ais as D  # noqa: E402


def feature(mmsi, ts, lon=28.0, lat=60.1, **extra):
    p = {"mmsi": mmsi, "sog": 8.2, "cog": 90.0, "navStat": 0, "posAcc": True, "raim": False, "timestamp": ts,
         "timestampExternal": 1792907081661, **extra}
    return {"mmsi": mmsi, "type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": p}


def main():
    g = {"features": [feature(538000001, 63), feature(273000002, 62), feature(265000003, 41),
                      feature(230000004, 60), feature(230000005, 99),                   # out of range: kept, field None
                      {"mmsi": None, "geometry": {"coordinates": [1, 2]}, "properties": {}},
                      {"mmsi": 230000006, "geometry": None, "properties": {}}]}
    rows = D.fix_rows(g, 1000)
    assert [r[0] for r in rows] == [538000001, 273000002, 265000003, 230000004, 230000005], rows
    assert [r[1] for r in rows] == [63, 62, 41, 60, None] and rows[0][3:5] == (60.1, 28.0) and rows[0][-1] == 1000
    assert D.fix_rows(None, 1) == []

    tmp = tempfile.mkdtemp()
    old_out, old_fetch = D.OUT, D.fetch_locations
    try:
        D.OUT = tmp
        calls = []
        D.fetch_locations = lambda: calls.append(1) or D.fix_rows(g, int(__import__("time").time() * 1000))
        c = D.Collector(types.SimpleNamespace(rest_min=10, no_snapshot=True, hours=0, flush_min=5))
        c.rest_poll(); c.rest_poll()                       # the second call is inside the 10-minute window
        assert len(calls) == 1 and c.counts["rest_polls"] == 1 and c.counts["fix_lost_reports"] == 2, c.counts
        c.next_rest = 0; c.rest_poll()
        assert len(calls) == 2
        c.flush(final=True)
        day = os.listdir(tmp)
        day = [d for d in day if len(d) == 10][0]
        t = pq.read_table(os.path.join(tmp, day, "fixflags.parquet"))
        assert t.num_rows == 10 and t.schema.names == D.FIX_KEYS, (t.num_rows, t.schema.names)
        assert sorted(set(t.column("utc_second").to_pylist()) - {None}) == [41, 60, 62, 63]
        assert not [f for f in os.listdir(os.path.join(tmp, day)) if f.startswith("fixflags-")]   # parts merged
        off = D.Collector(types.SimpleNamespace(rest_min=0, no_snapshot=True, hours=0, flush_min=5))
        off.rest_poll()
        assert len(calls) == 2                             # --rest-min 0 turns polling off
    finally:
        D.OUT, D.fetch_locations = old_out, old_fetch
        shutil.rmtree(tmp)
    print("test_digitraffic_fixflags: ok")


if __name__ == "__main__":
    main()
