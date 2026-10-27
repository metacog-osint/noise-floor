"""Offline test for tools/site_days.py: daily map files join the committed days without overriding them."""
import json, os, shutil, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import site_days as S  # noqa: E402

COLS = ["h3", "aircraft", "bad_live", "bad_raw", "capable", "capable_bad10"]


def day_file(day, cells):
    return {"day": day, "licence": "ODbL 1.0; derived from adsb.lol", "cols": COLS, "cells": cells}


def write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def test_feed(tmp):
    import xml.etree.ElementTree as ET
    evd = os.path.join(tmp, "feed_events")
    os.makedirs(evd)
    write(os.path.join(tmp, "feed_places.json"), {"places": [["Kaliningrad", 54.7, 20.5, 2, 0], ["Tiny <Town>", 0, 0, 9, 0]]})
    idx = [{"day": f"2026-09-{d:02d}", "note": "", "hexes": 1000, "jam_hexes": 100 + d} for d in range(1, 31)]
    idx.append({"day": "2026-10-01", "note": "R&D <note>", "hexes": 1000, "jam_hexes": 400, "daily": True})
    write(os.path.join(evd, "2026-10-01.json"), {"day": "2026-10-01", "anomalies": [
        {"m": "jam", "tier": "major", "peak": 61.2, "lat": 54.9, "lon": 20.1, "h0": 2, "h1": 4, "excess": 40.4, "hs": 0.7, "test": "X <1>"},
        {"m": "acc", "tier": "major", "peak": 30, "lat": 1, "lon": 1, "h0": 0, "h1": 1, "excess": 20},
        {"m": "jam", "tier": "minor", "peak": 9, "lat": 1, "lon": 1, "h0": 0, "h1": 1, "excess": 5}],
        "bursts": [{}, {}], "tests": [{"id": "X <1>"}]})
    p = os.path.join(tmp, "feed.xml")
    none = os.path.join(tmp, "no_alerts.json")
    assert S.write_feed(idx, evd, p, os.path.join(tmp, "feed_places.json"), n=30, alerts_path=none) == 30
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.parse(p).getroot()                                       # well-formed despite <, & in notes and test ids
    es = root.findall("a:entry", ns)
    assert len(es) == 30 and es[0].find("a:updated", ns).text == "2026-10-01T23:59:59Z"
    assert es[0].find("a:title", ns).text == "1 Oct 2026: 400 cells with severe GPS error (30-day median 116), 1 major event", es[0].find("a:title", ns).text
    html = es[0].find("a:content", ns).text
    assert "near Kaliningrad" in html and "70% of the degraded aircraft were A350s or A380s" in html and "fits announced test X &lt;1&gt;" in html, html
    assert "R&amp;D &lt;note&gt;" in html and "2 minute-level bursts." in html and "1 announced US GPS tests." in html, html
    assert html.count("<li>") == 1, html                                # only the major/notable jamming-scale event
    assert es[-1].find("a:id", ns).text.endswith("gnss-day-2026-09-02")
    assert "No event file for this day." in es[1].find("a:content", ns).text
    assert "not reviewed by a person" in html and "validated days" in es[1].find("a:content", ns).text
    # sun-outage alerts join the feed in time order, with their own ids
    al = os.path.join(tmp, "alerts.json")
    write(al, {"alerts": [{"id": "sun-l-burst-2026-10-01T09:00:00Z", "kind": "l-burst", "level": "obs", "t": "2026-10-01T09:00:00Z", "text": "Burst <1>"},
                          {"id": "sun-report-2026-10-02T09:00:00Z", "kind": "report", "level": "obs", "t": "2026-10-02T09:00:00Z", "text": "R", "link": "https://x.test/a?b=1&c=2"}]})
    assert S.write_feed(idx, evd, p, os.path.join(tmp, "feed_places.json"), n=30, alerts_path=al) == 32
    es = ET.parse(p).getroot().findall("a:entry", ns)
    assert [e.find("a:updated", ns).text for e in es[:3]] == ["2026-10-02T09:00:00Z", "2026-10-01T23:59:59Z", "2026-10-01T09:00:00Z"]
    assert es[0].find("a:link", ns).get("href") == "https://x.test/a?b=1&c=2" and "Burst &lt;1&gt;" in es[2].find("a:content", ns).text


def main():
    tmp = tempfile.mkdtemp()
    try:
        gnss, src = os.path.join(tmp, "gnss"), os.path.join(tmp, "dl")
        os.makedirs(gnss); os.makedirs(src)
        S.GNSS, S.EVENTS = gnss, os.path.join(tmp, "events")
        S.FEED, S.PLACES = os.path.join(tmp, "feed.xml"), os.path.join(tmp, "places.json")    # never the repo's site/
        write(os.path.join(gnss, "2025-10-14.json"), day_file("2025-10-14", [["a", 10, 5, 5, 8, 1]]))
        write(os.path.join(gnss, "days.json"), [{"day": "2025-10-14", "note": "EGNOS outage", "hexes": 1, "jam_hexes": 1, "kb": 1}])
        # 5 aircraft, 2 bad -> 100*(2-1)/5 = 20% (jamming scale); 5 aircraft, 1 bad -> 0%; 4 aircraft -> not counted
        write(os.path.join(src, "2026-10-21.map.json"), day_file("2026-10-21", [["b", 5, 2, 2, 4, 0], ["c", 5, 1, 1, 4, 0], ["d", 4, 4, 4, 4, 4]]))
        write(os.path.join(src, "2026-10-20.map.json"), day_file("2026-10-20", [["b", 9, 0, 0, 9, 0]]))
        write(os.path.join(src, "2025-10-14.map.json"), day_file("2025-10-14", []))     # must not replace the committed day
        write(os.path.join(src, "notes.txt"), {})
        sys.argv = ["site_days.py", src]
        S.main()
        idx = json.load(open(os.path.join(gnss, "days.json")))
        assert [d["day"] for d in idx] == ["2025-10-14", "2026-10-20", "2026-10-21"], idx
        assert idx[0] == {"day": "2025-10-14", "note": "EGNOS outage", "hexes": 1, "jam_hexes": 1, "kb": 1}, idx[0]
        assert idx[2]["daily"] is True and idx[2]["hexes"] == 2 and idx[2]["jam_hexes"] == 1 and idx[2]["acc_hexes"] == 0, idx[2]
        # acc: 5+ capable aircraft and >= 50% of them below 10 m after the one-aircraft subtraction
        assert S.stats(day_file("x", [["e", 9, 0, 0, 6, 4], ["f", 9, 0, 0, 6, 3], ["g", 9, 0, 0, 4, 4]]))["acc_hexes"] == 1
        assert idx[1]["jam_hexes"] == 0 and idx[1]["note"] == "", idx[1]
        assert json.load(open(os.path.join(gnss, "2025-10-14.json")))["cells"] == [["a", 10, 5, 5, 8, 1]]
        assert os.path.exists(os.path.join(gnss, "2026-10-21.json")) and not os.path.exists(os.path.join(gnss, "notes.txt"))
        assert not os.path.exists(os.path.join(tmp, "events"))          # no analysis files given: no event files

        # event files: anomaly and burst events carry their regions; SBAS hours merge into runs
        an = {"baseline_days": ["d"] * 14, "events": [
            {"measure": "gross", "tier": "major", "start_hour": 3, "end_hour": 5, "regions": 2, "region_hours": 4,
             "peak_share": 40.0, "peak_excess": 35.0, "lat": 59.1, "lon": 28.1, "cells": ["r1", "r2"]},
            {"measure": "capable_10m", "tier": "minor", "start_hour": 7, "end_hour": 7, "regions": 1, "region_hours": 1,
             "peak_share": 20.0, "peak_excess": 9.0, "lat": 10.0, "lon": 78.0}]}
        bu = {"events": [{"start": "13:11Z", "end": "13:19Z", "peak_aircraft": 15, "lat": 57.9, "lon": 19.2, "detections": 3,
                          "regions": 2, "basis": "prior 14 days, same 15-min slot", "cells": ["r3"]}]}
        sb = {"areas": {"EGNOS (Europe)": {"hours": [None, {"hour": 1, "state": "outage"}, {"hour": 2, "state": "outage"},
                                                     {"hour": 3, "state": "ok"}, {"hour": 4, "state": "degraded"}]},
                        "WAAS (CONUS)": {"hours": [{"hour": 0, "state": "ok"}]}}}
        for k, v in (("anomalies", an), ("bursts", bu), ("sbas", sb)):
            write(os.path.join(src, f"2026-10-21.{k}.json"), v)
        assert S.write_events("2026-10-21", src, os.path.join(tmp, "events"))
        ev = json.load(open(os.path.join(tmp, "events", "2026-10-21.json")))
        assert ev["baseline_days"] == 14 and ev["burst_basis"].startswith("prior 14"), ev
        assert ev["anomalies"][0] == {"m": "jam", "tier": "major", "h0": 3, "h1": 5, "regions": 2, "rh": 4, "peak": 40.0,
                                      "excess": 35.0, "lat": 59.1, "lon": 28.1, "cells": ["r1", "r2"], "hs": None}, ev["anomalies"][0]
        assert ev["anomalies"][1]["m"] == "acc" and ev["anomalies"][1]["cells"] == []
        assert ev["bursts"] == [{"t0": "13:11Z", "t1": "13:19Z", "peak": 15, "regions": 2, "lat": 57.9, "lon": 19.2, "cells": ["r3"], "hs": None}]
        assert ev["sbas"] == [{"area": "EGNOS (Europe)", "start": 1, "end": 2, "state": "outage"},
                              {"area": "EGNOS (Europe)", "start": 4, "end": 4, "state": "degraded"}], ev["sbas"]
        assert not S.write_events("2026-10-20", src, os.path.join(tmp, "events"))   # analysis files missing

        # trend: one series per area over the days that have a hotspot file; a missing area is a gap
        write(os.path.join(src, "2026-10-20.hotspots.json"), {"regions": {"A": {"share": 10.0, "aircraft_hexes": 100, "box": [1, 2, 3, 4]}}})
        write(os.path.join(src, "2026-10-21.hotspots.json"), {"regions": {"A": {"share": 12.5, "aircraft_hexes": 80, "box": [1, 2, 3, 4]},
                                                                          "B": {"share": None, "aircraft_hexes": 0, "box": [5, 6, 7, 8]}}})
        tp = os.path.join(tmp, "trend.json")
        assert S.write_trend(["2026-10-19", "2026-10-21", "2026-10-20"], src, tp) == 2
        tr = json.load(open(tp))
        assert tr["days"] == ["2026-10-20", "2026-10-21"], tr
        assert tr["regions"]["A"] == {"box": [1, 2, 3, 4], "share": [10.0, 12.5], "aircraft_hexes": [100, 80]}, tr
        assert tr["regions"]["B"]["share"] == [None, None] and tr["regions"]["B"]["box"] == [5, 6, 7, 8], tr
        assert S.write_trend(["2026-10-19"], src, os.path.join(tmp, "none.json")) == 0 and not os.path.exists(os.path.join(tmp, "none.json"))
        # a missing calendar day becomes a gap, not a joined line
        write(os.path.join(src, "2026-10-18.hotspots.json"), {"regions": {"A": {"share": 8.0, "aircraft_hexes": 90, "box": [1, 2, 3, 4]}}})
        assert S.write_trend(["2026-10-18", "2026-10-20"], src, tp) == 2
        tr = json.load(open(tp))
        assert tr["days"] == ["2026-10-18", "2026-10-19", "2026-10-20"] and tr["regions"]["A"]["share"] == [8.0, None, 10.0], tr
        # announced tests: an event inside a test's window and widest radius is tagged; others aren't
        tests = {"tests": {"WSMRNM GPS 25-16": {"id": "WSMRNM GPS 25-16", "place": "White Sands Missile Range, NM",
                                                "centre": [33.64, -106.57], "radii_nm": {"FL400": 363, "FL250": 328},
                                                "windows": [["2025-10-22T03:00Z", "2025-10-22T11:00Z"]], "notice_url": "u"}}}
        write(os.path.join(tmp, "faa_gps_tests.json"), tests)
        evd = os.path.join(tmp, "ev2")
        os.makedirs(evd)
        write(os.path.join(evd, "2025-10-22.json"), {"day": "2025-10-22", "anomalies": [
            {"m": "acc", "h0": 3, "h1": 5, "lat": 33.0, "lon": -106.0},          # inside, in window
            {"m": "jam", "h0": 3, "h1": 5, "lat": 55.6, "lon": 17.9},            # far away
            {"m": "acc", "h0": 13, "h1": 14, "lat": 33.0, "lon": -106.0}],       # outside the window
            "bursts": [{"t0": "10:50Z", "t1": "11:10Z", "lat": 34.0, "lon": -107.0}]})
        write(os.path.join(evd, "2025-10-25.json"), {"day": "2025-10-25", "anomalies": [], "bursts": []})
        assert S.annotate_all(evd, os.path.join(tmp, "faa_gps_tests.json")) == (2, 2)
        ev = json.load(open(os.path.join(evd, "2025-10-22.json")))
        assert [a.get("test") for a in ev["anomalies"]] == ["WSMRNM GPS 25-16", None, None], ev["anomalies"]
        assert ev["bursts"][0]["test"] == "WSMRNM GPS 25-16" and ev["tests"][0]["place"].startswith("White Sands"), ev
        assert json.load(open(os.path.join(evd, "2025-10-25.json")))["tests"] == []
        test_feed(tmp)
        print("test_site_days: ok")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
