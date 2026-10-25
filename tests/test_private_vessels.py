"""Offline tests for nisar/nisar_rfi/vessels.py (the private vessel page) on synthetic AIS from both collectors'
schemas, a temporary watch config, a sanctions file in tools/sanctions.py's layout, and a NISAR state file. Plain
script, as CI runs it (requirements.txt + nisar/requirements.txt; no network). Checks categories, the sanctions
matches (IMO decides; MMSI only without a valid IMO; names never add a ship), the "near" emitter join, private-craft
exclusion, reporting statistics net of collection gaps, GNSS indicators, and that hostile AIS text cannot break out of
the page's data block."""
import json, os, shutil, sys, tempfile

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nisar"))
sys.path.insert(0, os.path.join(ROOT, "collectors"))
from nisar_rfi import vessels as V  # noqa: E402
import aisstream_ais as S  # noqa: E402
import digitraffic_ais as DT  # noqa: E402

DAY = "2026-10-20"
T0 = 1_792_454_400            # 2026-10-20 00:00:00 UTC


def write(d, day, kind, rows, schema):
    os.makedirs(os.path.join(d, day), exist_ok=True)
    keys = [f.name for f in schema]
    cols = list(zip(*rows))
    pq.write_table(pa.table({k: pa.array(c, type=schema.field(k).type) for k, c in zip(keys, cols)}, schema=schema),
                   os.path.join(d, day, f"{kind}.parquet"))


def a_loc(m, t, lat, lon, sog=10.0, msg=1, pos_acc=True, raim=False):
    return (m, t, lat, lon, sog, 90.0, 90, 0 if msg == 1 else None, 0, pos_acc, raim, t * 1000, msg, True, None, "aisstream")


def a_meta(m, name=None, imo=None, typ=None, call=None, dest=None, draught=None, eta=None, refs=(None,) * 4, msg=5):
    return (m, T0 * 1000, name, call, imo, typ, dest, draught, eta, 1, *refs, T0 * 1000, "ws", msg, "aisstream")


def d_loc(m, t, lat, lon, sog=8.0):
    return (m, t, lat, lon, sog, 45.0, 45, 0, 0, False, False, t * 1000)


def d_meta(m, name, imo, typ):
    return (m, T0 * 1000, name, "CALL", imo, typ, "FIHEL", 50, 0, 1, 50, 10, 5, 5, T0 * 1000, "mqtt")


def test_rules():
    flags = ("RU", "CN", "IR", "KP")
    cats, basis = V.classify(412000001, {"type": 30, "name": "MIN SHA YU 01"}, "CN", {}, {}, None, flags)
    assert cats == ["state_flag_of_interest"]                  # fishing types count on the private page
    cats, basis = V.classify(230000002, {"type": 70, "name": "FINNISH COAST GUARD 1"}, "FI", {}, {}, "mmsi", flags)
    assert cats == ["sanctioned", "law_enforcement"] and "unconfirmed" in basis["sanctioned"]
    assert V.classify(230000002, {"type": 70, "name": "X"}, "FI", {}, {}, "name", flags)[0] == []   # names never add
    assert V.classify(230000003, {"type": 70, "imo": 9074729}, "FI", {}, {9074729: {}}, None, flags)[0] == ["watch_list"]
    assert V.excluded(235000037, {"type": 37}, False) and not V.excluded(235000037, {"type": 37}, True)
    assert V.excluded(235000036, {"type": 36}, False) and not V.excluded(235000036, {"type": 36, "imo": 9074729}, False)
    assert V.excluded(992351234, {}, False) and not V.excluded(273000001, {}, False)       # aid to navigation: out
    assert V.ais_class_of({1, 5}) == "A" and V.ais_class_of({18, 24}) == "B" and V.ais_class_of(set()) is None
    import numpy as np
    dets = [{"id": "x", "t": f"{DAY}T01:00:00Z", "lat": 1.0, "lon": 104.0}]
    near = V.emitters_near(np.array([T0 + 600, T0 + 7200]), np.array([1.1, 1.0]), np.array([104.0, 104.0]), dets)
    assert len(near) == 1 and near[0]["km"] == 0.0 and near[0]["dt_h"] == 1.0
    assert V.emitters_near(np.array([T0 - 600]), np.array([1.0]), np.array([104.0]), dets) == []    # the day before


def test_build():
    tmp = tempfile.mkdtemp()
    try:
        dirs = {"aisstream": os.path.join(tmp, "aisstream"), "digitraffic": os.path.join(tmp, "digitraffic")}
        tanker, navy, cg, yacht, jumpy, plain, watched, sail, mm_only, name_only = (
            273100001, 230100002, 412100003, 235100004, 538100005, 244100006, 636100007, 412100008, 667100009, 244100010)
        A, M = [], []
        for i in range(60):                                   # every 60 s for an hour; most vessels then go quiet
            t = T0 + i * 60
            A.append(a_loc(tanker, t, 1.20 + i * 0.001, 103.80 + i * 0.001))
            A.append(a_loc(cg, t, 9.70, 115.80 + i * 0.0005, msg=18))
            A.append(a_loc(yacht, t, 1.25, 103.85))
            A.append(a_loc(sail, t, 9.0, 115.0))
            A.append(a_loc(mm_only, t, 25.0, 57.0))
            A.append(a_loc(name_only, t, 25.1, 57.1))
            # reported positions that jump 2 degrees away and back every 10 minutes
            A.append(a_loc(jumpy, t, 1.40 + (2.0 if i % 10 == 5 else 0.0), 104.0))
        for i in range(190):                                  # one vessel keeps reporting: the collector was up
            A.append(a_loc(plain, T0 + i * 60, 1.30, 103.90 + i * 0.0005))
        for i in range(10):
            A.append(a_loc(tanker, T0 + 3 * 3600 + i * 60, 1.30, 103.90, pos_acc=False, raim=True))
        A.append(a_loc(tanker, T0 + 3 * 3600 + 30, 1.30, 103.90))                # a time of its own
        A.append(a_loc(tanker, T0 + 3 * 3600 + 540, 1.30, 103.90))               # exact duplicate of a row above
        M += [a_meta(tanker, "SHADOW ONE", 9074729, 80, "UBCD7", "FOR ORDERS", 124, 10 << 16 | 27 << 11 | 14 << 6 | 30, (200, 44, 20, 22)),
              a_meta(tanker, "SHADOW 1", 9074729, 80),             # a name change inside the window
              a_meta(cg, "CHINA COAST GUARD 5901", None, None, msg=24),
              a_meta(yacht, "PRIVATE YACHT", None, 37),
              a_meta(plain, "PLAIN CARGO", 9603972, 70),
              a_meta(sail, "SAIL TRAINING", None, 36),
              a_meta(jumpy, "JUMPY", 9074729, 70),
              a_meta(mm_only, "MMSI ONLY", None, 80),
              a_meta(name_only, "LISTED NAME", None, 80)]
        write(dirs["aisstream"], DAY, "locations", A, S.LOC_SCHEMA)
        write(dirs["aisstream"], DAY, "metadata", M, S.META_SCHEMA)
        D = [d_loc(navy, T0 + i * 120, 60.10, 24.90 + i * 0.001) for i in range(30)]
        D += [d_loc(watched, T0 + i * 300, 59.5, 22.0) for i in range(5)]
        write(dirs["digitraffic"], DAY, "locations", D, DT.LOC_SCHEMA)
        write(dirs["digitraffic"], DAY, "metadata", [d_meta(navy, "</script><script>alert(1)</script>", None, 35),
                                                    d_meta(watched, "WATCHED", 9603972, 80)], DT.META_SCHEMA)
        wp = os.path.join(tmp, "maritime.json")
        json.dump({"vessel_watch": {"vessels": [{"mmsi": watched, "reason": "test reason", "source": "test source"},
                                                {"imo": "IMO 9300001", "name": "Never Seen", "reason": "dark"}]}}, open(wp, "w"))
        sp = os.path.join(tmp, "sanctioned.json")
        lst = lambda lst_, prog: {"list": lst_, "programme": prog, "date": "2025-01-10", "url": "https://example.org/x",
                                  "id": "1", "name": "N", "flag": None}
        json.dump({"generated": "2026-10-25T00:00:00Z",
                   "sources": [{"id": "ofac", "list": "OFAC SDN", "attribution": "OFAC SDN List", "published": "2026-10-24"}],
                   "by_imo": {"9074729": {"imo": 9074729, "names": ["SHADOW ONE"], "flags": [], "mmsi": [], "callsigns": [],
                                          "listings": [lst("OFAC SDN", "RUSSIA-EO14024")]},
                              "9300002": {"imo": 9300002, "names": ["LISTED NAME"], "flags": [], "mmsi": [str(mm_only)],
                                          "callsigns": [], "listings": [lst("UK Sanctions List", "Russia")]}},
                   "no_imo": [], "by_mmsi": {str(mm_only): [9300002]}}, open(sp, "w"))
        st = os.path.join(tmp, "state")
        os.makedirs(st)
        json.dump({"detections": [
            {"id": "d1", "site": "S-1", "start": f"{DAY}T00:30:00Z", "lat": 1.40, "lon": 103.80, "confidence": "MEDIUM",
             "band_text": "1227 MHz (GPS L2)", "where": "test"},                     # ~16 km from the tanker's track
            {"id": "d2", "site": "S-2", "start": f"{DAY}T00:30:00Z", "lat": 3.0, "lon": 106.0, "confidence": "HIGH"},  # far
            {"id": "d3", "site": "S-3", "start": "2026-10-21T00:30:00Z", "lat": 1.21, "lon": 103.81},    # other day
            {"id": "d4", "site": "S-4", "start": f"{DAY}T00:40:00Z", "lat": 1.21, "lon": 103.81, "ignored": True}]},
            open(os.path.join(st, "state.json"), "w"))
        logs = []
        data = V.build_data(days=[DAY], cfg={"state_dir": st}, dirs=dirs, watch_path=wp, sanctions_path=sp,
                            use_land=False, log=logs.append)
        by = {v["mmsi"]: v for v in data["vessels"]}
        assert yacht not in by and sail not in by and plain not in by and name_only not in by, sorted(by)
        traffic = [r[0] for r in data["traffic"]["rows"]]
        assert yacht not in traffic and sail not in traffic and plain in traffic and name_only in traffic
        t = by[tanker]
        assert t["categories"] == ["sanctioned", "state_flag_of_interest"], t["categories"]
        assert t["listings"] == [{"list": "OFAC SDN", "programme": "RUSSIA-EO14024", "date": "2025-01-10",
                                  "url": "https://example.org/x", "match": "imo"}], t["listings"]
        assert t["flag"] == "RU" and t["ais_class"] == "A" and t["signals"]["ais_class"] == "A" and t["imo"] == 9074729
        sg = t["signals"]
        assert sg["imo_check_digit_ok"] is True and sg["draught"] == 12.4 and sg["eta"] == "10-27 14:30 UTC"
        assert sg["dimensions"] == {"length_m": 244, "beam_m": 42} and sg["destination"] == "FOR ORDERS"
        assert sg["pos_fix_device"] == "GPS" and t["identities"]["names"][0][1] == 1
        r = t["reporting"]
        assert r["positions"] == 71 and r["median_interval_s"] == 60.0 and r["gaps_over_1h"] == 1, r
        assert 2.0 < r["longest_gap_h"] < 2.05 and r["spoofed_positions"] == 0 and r["first_seen"] == f"{DAY}T00:00:00Z"
        assert abs(r["pos_accuracy_high_share"] - 61 / 71) < 0.01 and abs(r["raim_share"] - 10 / 71) < 0.01
        assert t["last"]["t"] == f"{DAY}T03:09:00Z" and t["last"]["nav_status"] == "under way using engine"
        assert t["last"]["sog"] == 10.0 and len(t["track"]) <= 20 and t["track"][0] == [T0, 1.2, 103.8]
        assert [e["id"] for e in t["emitters_near"]] == ["d1"] and 10 < t["emitters_near"][0]["km"] < 30
        assert t["emitters_near"][0]["vessel_t"].startswith(DAY) and t["seen"] and t["sources"] == ["aisstream"]
        assert by[navy]["categories"] == ["military"] and by[navy]["sources"] == ["digitraffic"] and by[navy]["flag"] == "FI"
        assert by[cg]["categories"] == ["law_enforcement", "state_flag_of_interest"] and by[cg]["ais_class"] == "B"
        assert by[cg]["category_basis"]["law_enforcement"] == "name pattern (check)"
        mo = by[mm_only]
        assert mo["categories"] == ["sanctioned"] and mo["listings"][0]["match"] == "mmsi" and "unconfirmed" in mo["category_basis"]["sanctioned"]
        j = by[jumpy]
        assert "gnss_victim" in j["categories"] and "sanctioned" in j["categories"] and j["reporting"]["spoofed_positions"] >= 5
        assert all(abs(p[1] - 1.40) < 0.01 for p in j["track"]) and len(j["suspect_positions"]) == j["reporting"]["spoofed_positions"]
        w = by[watched]
        assert w["categories"] == ["watch_list"] and w["private_notes"] == [{"reason": "test reason", "source": "test source"}]
        unseen = [v for v in data["vessels"] if v["mmsi"] is None]
        assert len(unseen) == 1 and unseen[0]["imo"] == 9300001 and unseen[0]["seen"] is False and unseen[0]["name"] == "NEVER SEEN"
        assert data["counts"]["sanctioned"] == 3 and data["counts"]["with_emitters_near"] >= 1 and data["sanctions_loaded"]
        assert data["sanctions_sources"] == ["OFAC SDN List, list dated 2026-10-24"]
        assert [d["id"] for d in data["detections"]] == ["d1", "d2"] and data["vessels"][0]["categories"][0] == "sanctioned"
        assert not data["collection_gaps"]["aisstream"]          # one vessel kept reporting through the tanker's gap
        # every record carries the public tab's keys
        keys = {"mmsi", "imo", "name", "callsign", "flag", "ais_type", "ais_type_label", "ais_class", "categories", "listings",
                "last", "track", "reporting", "signals"}
        assert all(keys <= set(v) for v in data["vessels"])
        # the page: data inline, and a hostile vessel name cannot close the script element
        out = os.path.join(tmp, "page.html")
        V.write_page(data, out)
        html = open(out, encoding="utf-8").read()
        assert html.lower().count("</script") == 2 and "<\\/SCRIPT><SCRIPT>ALERT(1)<\\/SCRIPT>" in html   # names are upper-cased
        assert "/*__DATA__*/" not in html and '"vessels":[' in html
        # no sanctions file: the join is a no-op and the page says so
        data2 = V.build_data(days=[DAY], cfg=None, dirs=dirs, watch_path=wp, sanctions_path=os.path.join(tmp, "none.json"),
                             use_land=False, log=logs.append)
        assert not data2["sanctions_loaded"] and data2["counts"]["sanctioned"] == 0 and not data2["detections"]
        # the view hook's builder writes into a folder
        dest = os.path.join(tmp, "view")
        old = V.AIS_DIRS
        try:
            V.AIS_DIRS = dirs
            info = V.build(None, dest, days=[DAY], watch_path=wp, sanctions_path=sp, use_land=False, log=logs.append)
        finally:
            V.AIS_DIRS = old
        assert info["vessels"] == len(data["vessels"]) and os.path.exists(os.path.join(dest, "vessels.html"))
        assert json.load(open(os.path.join(dest, "vessels.json")))["days"] == [DAY]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)


if __name__ == "__main__":
    main()
