"""Offline tests for collectors/watch.py and collectors/chayka.py: no network, no private config.

Every source is mocked with responses shaped like the live ones (checked 14 and 22 Oct 2026). Names, slots and
channels here are neutral test values, not the private watch lists.
Run: python tests/test_pollers.py
"""
import csv, io, json, os, shutil, sys, tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "collectors"))
import watch as W  # noqa: E402

try:   # Chayka needs numpy and pillow: in this PC's .venv, not in CI's requirements.txt install
    import numpy as np
    from PIL import Image
    import chayka as C
except ImportError as _e:
    np = Image = C = None
    NO_CHAYKA = str(_e)

NOW = datetime(2026, 10, 7, 7, 0, tzinfo=timezone.utc)

NAVCEN_TEXT = """USCG NAVCEN 2026 GPS TESTING
SCHEDULE
LAST UPDATE 9/28/26
1
GPS Coordinates Range
@
50ft
Range
@
10,000ft
End DateStart DateLocationGPS#Test Name
32-06-58N 106-08-55W92NM120NM01 Oct14 SepTesttown, TX GPS 26-02RANGEA
33-07-14N 106-07-56W180NM226NM29 Sep28 SepPinon, NMGPS 26-46RANGEB
32-36-24N 114-12-05W131 NM191 NM09 Oct06 OctYuma, AZGPS 26-02RANGE_C
"""

REPORTS_HTML = """<html><body><table class="table table-striped" id="gps_pr_table"><thead><tr>
<th scope="col" id="index">Index</th><!---<th>Disruption Date/Time</th>---><th>Disruption Date</th><th>Location</th>
<th class="typeCol">Type</th><th>Description</th><th>Cause</th><th>Closed Date</th></tr></thead><tbody>
{rows}</tbody></table></body></html>"""
REPORT_ROW = """<tr><td id="{i}">{i}</td><!---<td>{d}<br>15:45:00 CET</td>---><td class="occDate">{d}</td><!---<td>10/13/2026</td>--->
<td>{loc}</td><td class="typeCol">Marine</td><td class="col_text_break">USER: Loss of GPS <br>NAVCEN: {nav}</td>
<td>{cause}</td><td>{closed}</td></tr>"""


def reports_page(extra=None, cause2=""):
    rows = [REPORT_ROW.format(i=2, d="10/05/2026", loc="Test Harbor", nav="Under review." if not cause2 else "Reviewed.",
                              cause=cause2, closed="10/08/2026" if cause2 else ""),
            REPORT_ROW.format(i=1, d="01/02/2026", loc="Old Port", nav="Reviewed.", cause="User Equipment", closed="01/09/2026")]
    if extra:
        rows.insert(0, extra)
    return REPORTS_HTML.format(rows="".join(rows))


def kos_page(rows):
    return "<table>" + "".join(rows) + "</table>"


def chayka_image(h=700, dropout_rows=6, anthorn_on=True, seed=1):
    """Synthetic DL0AO image: noise background, steady bright pulses on 'on' tracks."""
    rng = np.random.default_rng(seed)
    a = rng.integers(0, 25, size=(h, C.BAND * len(C.TRACKS), 3)).astype(np.uint8)
    on = {C.TRACK_IDS.index("Slonim 8000X"): dropout_rows, C.TRACK_IDS.index("Kotelnikovo 5990M"): 0}
    if anthorn_on:
        on.update({C.TRACK_IDS.index("Anthorn 6731M"): 0, C.TRACK_IDS.index("Anthorn 6731Y"): 0})
    for i, off_top in on.items():
        a[off_top:, i * C.BAND + 12: i * C.BAND + 15, :] = 200
    buf = io.BytesIO()
    Image.fromarray(a).save(buf, format="PNG")
    return buf.getvalue()


class Fake:
    """Canned responses by URL; records every request. Unknown URLs fail, so nothing reaches the network."""

    def __init__(self):
        self.calls, self.scenario = [], {"ukmto_new": False, "kos_new": False, "report_new": False}

    def __call__(self, url, headers, timeout):
        assert headers.get("User-Agent", "").startswith("noise-floor"), headers
        self.calls.append(url)
        s, d = self.scenario, NOW.date().isoformat()
        if "swpc.noaa.gov" in url:
            return json.dumps([
                {"product_id": "K06A", "issue_datetime": (NOW - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S.000"),
                 "message": "Space Weather Message Code: ALTK06\r\nSerial Number: 1\r\n\r\nALERT: Geomagnetic K-index of 6\r\n"},
                {"product_id": "K05W", "issue_datetime": (NOW - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S.000"),
                 "message": "Space Weather Message Code: WATA50\r\nWATCH: Geomagnetic Storm Category G1 Predicted\r\n"},
                {"product_id": "K04A", "issue_datetime": (NOW - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S.000"),
                 "message": "ALERT: Geomagnetic K-index of 4\r\n"}]).encode()
        if "msi.nga.mil" in url:                       # the smaps endpoint, one request per navArea
            if "navArea=4&" in url:
                return json.dumps({"smaps": [
                    {"msgSqncNumber": 1, "subRegion": "11", "createdOn": "051133Z OCT 2026",
                     "msgText": "051133Z OCT 26\nNAVAREA IV 1/26.\nGPS SIGNALS\nUNRELIABLE IN AREA"},
                    {"msgSqncNumber": 2, "createdOn": "051200Z OCT 2026", "msgText": "051200Z OCT 26\nNAVAREA IV 2/26.\nDERELICT VESSEL"},
                ]}).encode()
            if "navArea=12&" in url:
                return json.dumps({"smaps": [
                    {"msgSqncNumber": 3, "createdOn": "051300Z OCT 2026",
                     "msgText": "051300Z OCT 26\nNAVAREA XII 3/26.\nBARRIER MARKED WITH WHITE LIGHTS AND RADAR REFLECTORS"},
                ]}).encode()
            return json.dumps({"smaps": [], "fake_area": url.split("navArea=")[1].split("&")[0]}).encode()   # bodies differ per area, as real ones do
        if url == W.NAVCEN_TESTS:
            return b"%PDF-test"   # pdf_text is replaced in the end-to-end test
        if url == W.NAVCEN_REPORTS:
            extra = REPORT_ROW.format(i=3, d="10/06/2026", loc="New Bay", nav="", cause="", closed="") if s["report_new"] else None
            return reports_page(extra, cause2="Unknown Interference" if s["report_new"] else "").encode()
        if "sccd.royalnavy.mod.uk/api/ukmto/products-count/" in url:   # shapes as returned live, 14 Oct 2026
            return json.dumps([{"id": "m-now", "name": W.MONTHS[NOW.month - 1], "productItemCount": 2},
                               {"id": "m-next", "name": W.MONTHS[NOW.month % 12], "productItemCount": 0}]).encode()
        if "sccd.royalnavy.mod.uk/api/ukmto/products/" in url:
            if "m-now" not in url:
                return b"null"                                         # an empty month comes back as JSON null
            items = [{"id": "p-079", "reference": "JMIC Update 079", "issueDate": f"{d}T08:00:00Z", "location": "Red Sea",
                      "pdfUrl": "https://www.ukmto.org/-/media/ukmto/products/update-079-jmic-advisory-note.pdf"}]
            if s["ukmto_new"]:
                items.insert(0, {"id": "p-081", "reference": "JMIC Update 081", "issueDate": f"{d}T09:00:00Z",
                                 "location": "Red Sea",
                                 "pdfUrl": "https://www.ukmto.org/-/media/ukmto/products/update-081-jmic-advisory-note.pdf"})
            return json.dumps(items).encode()
        if url.startswith(W.KOS):
            path = url[len(W.KOS):]
            assert not any(x in path for x in W.KOS_DISALLOWED), url
            if path == "/removed":
                rows = ['<tr><td>19.2°E</td><td>Testsat 1A</td><td>11034.00</td></tr>',
                        '<tr><td>Old Channel</td><td>x</td><td>x</td><td>x</td><td>1</td><td>2026-01-01</td></tr>']
                if s["kos_new"]:
                    rows += ['<tr><td>19.2°E</td><td>Testsat 1A</td><td>10971.20 MHz H</td></tr>',
                             f'<tr><td>Test Channel News</td><td>X</td><td>News</td><td>-</td><td>101</td><td>{d}</td></tr>',
                             '<tr><td>99.0°E</td><td>Elsewhere 1</td><td>12000.00</td></tr>',
                             f'<tr><td>Other Channel</td><td>X</td><td>News</td><td>-</td><td>7</td><td>{d}</td></tr>']
                return kos_page(rows).encode()
            if path == "/new":
                return kos_page(['<tr><td>26.0°E</td><td>Testsat 2</td><td>11900.00</td></tr>',
                                 f'<tr><td>Test Channel News</td><td>X</td><td>News</td><td>-</td><td>5</td><td>{d}</td></tr>']).encode()
        raise AssertionError(f"unexpected request {url}")


def tmp_config(d):
    p = os.path.join(d, "pollers.json")
    json.dump({"kingofsat": {"slots": ["19.2E"], "watch": ["Test Channel"]},
               "sun_transit": {"dish_m": 0.9, "freq_ghz": 11.7, "pairs": [
                   {"receiver": "Tehran", "country": "IR", "lat": 35.6892, "lon": 51.389, "satellite": "Yahsat 1A", "slot": 52.5}]}},
              open(p, "w", encoding="utf-8"))
    return p


def chayka_fetcher(img_bytes, top):
    def f(url, dest):
        open(dest, "wb").write(img_bytes)
        return top, True
    return f


# ---------------- unit tests ----------------
def test_dtg_and_keywords():
    assert W.dtg_iso("101133Z MAY 2024") == "2024-05-10T11:33Z"
    assert W.MSI_KEYWORDS.search("GPS SIGNALS UNRELIABLE") and W.MSI_KEYWORDS.search("RADAR TRIALS IN AREA")
    assert not W.MSI_KEYWORDS.search("LIGHTS AND RADAR REFLECTORS"), "radar reflectors on buoys aren't radar activity"


def test_nga_frozen_feed_is_an_error():
    class Old(Fake):
        def __call__(self, url, headers, timeout):
            if "msi.nga.mil" in url:
                return json.dumps({"smaps": [{"msgSqncNumber": 517, "createdOn": "101542Z MAY 2024",
                                              "msgText": "101542Z MAY 24\nNAVAREA IV 517/24.\nGPS UNRELIABLE"}]}).encode()
            return super().__call__(url, headers, timeout)
    ctx = W.Ctx(NOW, {"health": {}}, None, tempfile.gettempdir(), tempfile.gettempdir(), opener=Old())
    try:
        W.src_nga(ctx)
        raise AssertionError("a feed whose newest warning is 2024 must not pass as OK")
    except ValueError as e:
        assert "frozen" in str(e) and "2024-05-10T15:42Z" in str(e), e


def test_navcen_tests_parse():
    upd, tests = W.navcen_tests_parse(NAVCEN_TEXT)
    assert upd.isoformat() == "2026-09-28" and len(tests) == 3, tests
    a = tests[0]
    assert (a["name"], a["gps"], a["location"], a["start"], a["end"]) == ("RANGEA", "GPS 26-02", "Testtown, TX", "2026-09-14", "2026-10-01"), a
    assert (a["lat"], a["lon"], a["range_nm_50ft"], a["range_nm_10000ft"]) == (32.11611, -106.14861, 92.0, 120.0), a
    assert tests[1]["location"] == "Pinon, NM" and tests[1]["gps"] == "GPS 26-46", "no space before GPS#"
    assert tests[2]["name"] == "RANGE_C" and tests[2]["range_nm_50ft"] == 131.0, "space before NM"
    # schedule updated in December: January dates belong to the next year; a window can cross the new year
    _, t2 = W.navcen_tests_parse("LAST UPDATE 12/20/26\n32-06-58N 106-08-55W10NM20NM05 Jan28 DecX, NMGPS 27-01ABC\n"
                                 "32-06-58N 106-08-55W10NM20NM15 Jan10 JanY, NMGPS 27-02DEF\n")
    assert (t2[0]["start"], t2[0]["end"]) == ("2026-12-28", "2027-01-05") and t2[1]["start"] == "2027-01-10", t2
    try:
        W.navcen_tests_parse("no date here")
        raise AssertionError("missing LAST UPDATE should fail loudly")
    except ValueError:
        pass


def test_navcen_reports_parse():
    reps = W.navcen_reports_parse(reports_page())
    assert [r["index"] for r in reps] == [2, 1]
    r = reps[0]
    assert (r["date"], r["location"], r["type"], r["user"], r["navcen"], r["cause"], r["closed"]) == \
        ("2026-10-05", "Test Harbor", "Marine", "Loss of GPS", "Under review.", "", ""), r
    assert "CET" not in json.dumps(reps), "commented-out cells are dropped"


def test_kos_parse_and_robots_guard():
    rows = W.kos_parse(kos_page(['<tr><td>13.0°E</td><td>Sat</td><td>10971.20 MHz H</td></tr>',
                                 '<tr><td>Chan</td><td>X</td><td>News</td><td>-</td><td>1</td><td>2026-10-07</td></tr>']))
    assert rows == [{"pos": "13.0E", "sat": "Sat", "freq": "10971.20 H", "name": "Chan", "date": "2026-10-07"}], rows
    ctx = W.Ctx(NOW, {"health": {}}, None, tempfile.gettempdir(), tempfile.gettempdir(), opener=Fake())
    for p in ("/channelhistory.php?cl=1", "/tp.php?tp=1", "/find.php?q=x", "/detail-x.php"):
        try:
            W.kos_get(ctx, p)
            raise AssertionError(f"{p} should be refused")
        except ValueError:
            pass


def test_sun_transit_matches_advisory():
    ws = W.sun_windows([{"receiver": "Tehran", "country": "IR", "lat": 35.6892, "lon": 51.389, "satellite": "Yahsat 1A",
                         "slot": 52.5}], datetime(2026, 10, 1, tzinfo=timezone.utc), hours=24 * 20)
    days = [w["peak"].strftime("%m-%d %H:%M") for w in ws]
    assert days[0].startswith("10-05 08:1") and days[-1].startswith("10-10 08:1") and len(days) == 6, days  # advisory: 5-10 Oct, ~08:17Z


def test_chayka_scoring_and_flags():
    if C is None:
        print(f"SKIP test_chayka_scoring_and_flags: {NO_CHAYKA}")
        return
    d = tempfile.mkdtemp()
    try:
        top = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)
        st = C.run(d, now=top, fetcher=chayka_fetcher(chayka_image(), top))
        assert st["receiver_ok"] is True and st["rows_logged_total"] == 700 and st["new_rows"] == 700, st
        s = st["stations"]
        assert s["Slonim 8000X"]["flag"].startswith("DROPOUT") and s["Slonim 8000X"]["same_hour_baseline_pct"] >= 95, s["Slonim 8000X"]
        assert s["Kotelnikovo 5990M"]["on_now"] and s["Kotelnikovo 5990M"]["flag"] is None
        assert not s["Bryansk 8000M"]["on_now"] and s["Bryansk 8000M"]["on_pct_24h"] == 0
        assert len(os.listdir(os.path.join(d, "archive"))) == 1
        # the next run an hour later logs only the 12 newer rows
        st2 = C.run(d, now=top + timedelta(hours=1), fetcher=chayka_fetcher(chayka_image(), top + timedelta(hours=1)))
        assert st2["new_rows"] == 12 and st2["rows_logged_total"] == 712, (st2["new_rows"], st2["rows_logged_total"])
        # receiver control: Anthorn and most Chayka tracks dark together -> fault suspected, no flags
        rows = list(csv.DictReader(open(os.path.join(d, "chayka_rows.csv"), encoding="utf-8")))
        for r in rows[-3:]:
            r["Anthorn 6731M"] = r["Anthorn 6731Y"] = "0"
        assert C.control_on(rows) is False and C.receiver_ok(rows) is False
        assert all(v["flag"] is None for v in C.summarize(rows, top + timedelta(hours=1)).values())
        # Anthorn dark but the Chayka tracks on: Anthorn's own problem, the receiver is fine
        for r in rows[-3:]:
            r.update({C.TRACK_IDS[i]: "1" for i in C.WATCH_IDX})
        assert C.control_on(rows) is False and C.receiver_ok(rows) is True
    finally:
        shutil.rmtree(d)


# ---------------- end to end ----------------
def test_end_to_end():
    tmp = tempfile.mkdtemp()
    real_pdf_text = W.pdf_text
    W.pdf_text = lambda body: NAVCEN_TEXT
    try:
        out, raw, cfg = os.path.join(tmp, "out"), os.path.join(tmp, "raw"), tmp_config(tmp)
        fake = Fake()
        img = chayka_image() if C else None
        keys = {k for k, _, _ in W.SOURCES} - (set() if C else {"chayka"})

        def go(now):
            return W.run(only=keys, config=cfg, out=out, raw=raw, now=now, opener=fake,
                         chayka_fetcher=chayka_fetcher(img, now - timedelta(minutes=10)) if C else None)

        r1 = go(NOW)
        alerts = [json.loads(l) for l in open(os.path.join(out, "alerts.jsonl"), encoding="utf-8")]
        srcs = {a["source"] for a in alerts}
        assert srcs == {"NOAA SWPC", "NGA MSI", "USCG NAVCEN", "USCG NAVCEN reports"}, srcs
        assert len([a for a in alerts if a["source"] == "NOAA SWPC"]) == 1, "alerts only, not watches or old messages"
        nga = [a for a in alerts if a["source"] == "NGA MSI"]
        assert len(nga) == 1 and nga[0]["event_time"] == "2026-10-05T11:33Z", nga
        assert nga[0]["title"].startswith("NAVAREA IV 1/2026 (subregion 11): GPS SIGNALS"), nga
        tests = [a for a in alerts if a["source"] == "USCG NAVCEN"]
        assert len(tests) == 1 and "RANGE_C" in tests[0]["title"], "tests already over when first seen aren't listed"
        rep = [a for a in alerts if a["source"] == "USCG NAVCEN reports"]
        assert len(rep) == 1 and rep[0]["title"].startswith("Report 2,"), "first run lists only recent reports"
        # baselined: UKMTO's existing product, the old NAVCEN report, two finished tests (KingOfSat: nothing recent)
        assert r1["baselined"] == 4, r1
        h = json.load(open(os.path.join(out, "state.json"), encoding="utf-8"))["health"]
        assert all(v["status"] == "OK" for v in h.values()), h
        page = open(os.path.join(ROOT, out, r1["digest"]) if not os.path.isabs(r1["digest"]) else r1["digest"], encoding="utf-8").read()
        want = ["## New triggers", "## Planned GPS tests", "| RANGE_C (GPS 26-02) | Yuma, AZ | 2026-10-06 to 2026-10-09",
                "## Sun transit, next 48 h", "Yahsat 1A", "## Source health", "Open Government Licence"]
        if C:
            want += ["## Chayka (DL0AO): status, not a trigger", "DROPOUT"]
        for s in want:
            assert s in page, s
        assert len(h) == len(keys), (h, keys)
        assert json.load(open(os.path.join(out, "navcen_gps_tests.json"), encoding="utf-8"))["tests"][0]["name"] == "RANGEA"

        # second run, two hours later, nothing new: dedupe; unchanged bodies are indexed, not stored again
        r2 = go(NOW + timedelta(hours=2))
        assert r2["new_triggers"] == 0, r2
        idx = [json.loads(l) for l in open(os.path.join(raw, NOW.strftime("%Y-%m-%d"), "index.jsonl"), encoding="utf-8")]
        assert any(x.get("unchanged") for x in idx)
        stored = [f for f in os.listdir(os.path.join(raw, NOW.strftime("%Y-%m-%d"))) if f != "index.jsonl"]
        assert len(stored) == len({x["sha256"] for x in idx}), "each distinct body stored once"

        # third run: new UKMTO product, KingOfSat removal, NAVCEN report and an update to an earlier one
        fake.scenario.update(ukmto_new=True, kos_new=True, report_new=True)
        r3 = go(NOW + timedelta(hours=4))
        new = [json.loads(l) for l in open(os.path.join(out, "alerts.jsonl"), encoding="utf-8")][len(alerts):]
        kos = [a for a in new if a["source"] == "KingOfSat"]
        assert len(kos) == 1 and kos[0]["title"].startswith("WATCHED · 19.2E") and "26.0E" in kos[0]["detail"], kos
        uk = [a for a in new if a["source"] == "UKMTO"]
        assert len(uk) == 1 and "081" in uk[0]["title"] and uk[0]["url"].endswith(".pdf") and "JMIC" in uk[0]["detail"], uk
        rep = sorted(a["title"] for a in new if a["source"] == "USCG NAVCEN reports")
        assert len(rep) == 2 and rep[0].startswith("Report 2 updated") and rep[1].startswith("Report 3,"), rep
        assert r3["new_triggers"] == 4, r3

        # a seen id is remembered beyond 14 days (emso-watch pruned at 14 d, so in-force warnings re-fired)
        r4 = go(NOW + timedelta(days=20))
        assert r4["new_triggers"] == 0, r4

        # courtesy throttles: an immediate rerun doesn't refetch UKMTO, KingOfSat or the Chayka image
        n = len(fake.calls)
        go(NOW + timedelta(days=20, minutes=5))
        later = fake.calls[n:]
        assert not any("ukmto" in u or u.startswith(W.KOS) for u in later), later
    finally:
        W.pdf_text = real_pdf_text
        shutil.rmtree(tmp)


def test_missing_config_skips_only_those_sources():
    tmp = tempfile.mkdtemp()
    real_pdf_text = W.pdf_text
    W.pdf_text = lambda body: NAVCEN_TEXT
    try:
        out = os.path.join(tmp, "out")
        W.run(config=os.path.join(tmp, "absent.json"), out=out, raw=os.path.join(tmp, "raw"), now=NOW, opener=Fake(),
              only={"nga", "kingofsat", "sun-transit"})
        h = json.load(open(os.path.join(out, "state.json"), encoding="utf-8"))["health"]
        assert h["NGA MSI"]["status"] == "OK" and h["KingOfSat"]["status"] == "SKIP" and h["Sun transit"]["status"] == "SKIP", h
    finally:
        W.pdf_text = real_pdf_text
        shutil.rmtree(tmp)


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS {name}")
            except Exception as e:
                fails += 1; print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    sys.exit(1 if fails else 0)
