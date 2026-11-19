"""pipeline/gnss_notams.py: archive rewrites, Q-line geometry, grouping of US copies, reading groups.
Run: python tests/test_gnss_notams.py (standard library only)."""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import gnss_notams as G  # noqa: E402

NOTE = G.SOURCE_FALLBACK


def notice(number, text, coords=None, radius=None, loc="URMG", fir="URRV", cls="INTL", issued="2026-11-17T08:00:00Z",
           end="2026-12-26T07:00:00Z", geometry=None):
    return {"matched_by": "q-code", "q_code": "QGWXX", "words": [], "refers_to": None,
            "notam": {"number": number, "type": "N", "affectedFir": fir, "icaoLocation": loc, "classification": cls,
                      "issued": issued, "effectiveStart": issued, "effectiveEnd": end, "text": text,
                      "coordinates": coords, "radius": radius},
            "geometry": geometry or {"type": "GeometryCollection", "geometries": [{"type": "Point", "coordinates": [0, 0]}]},
            "cancelled_by": None, "replaced_by": None, "ended_at": None}


def day_file(day, notices, written="2026-11-19T00:19:38Z", revised=None):
    return {"program": "launch", "dataset": "gnss-notams", "day": day, "source_note": NOTE, "rule": "gnss-1.0",
            "env": "prod", "lane_status": "ok", "written_at": written, "revised_at": revised, "n": len(notices),
            "notices": notices}


# Q line positions: degrees and minutes; 0,0 and junk are no position
assert G.q_position("4054N02919E") == (40.9, 29.3167)
assert G.q_position("3126S05759W") == (-31.4333, -57.9833)
assert G.q_position("0000N00000E") is None and G.q_position(None) is None and G.q_position("x") is None

# geometry from the Q line, never the NMS point at 0,0; text radius only without a Q line
w = G.where({"coordinates": "4323N04542E", "radius": "025"}, "GNSS FAILURE POSS WI AD AREA.")
assert w == {"lat": 43.3833, "lon": 45.7, "radius_nm": 25, "geo": "q"}, w
w = G.where({}, "NAV GPS (WSMRNM GPS 26-18) MAY NOT BE AVBL WI A 381NM RADIUS CENTERED AT 333921N1063127W (ONM147044)")
assert w["geo"] == "text" and w["radius_nm"] == 381 and abs(w["lat"] - 33.6558) < 1e-3 and w["lon"] < -106, w
w = G.where({}, "AN AREA DEFINED AS 98NM RADIUS OF 360000N0841900W SFC-FL400")
assert w["radius_nm"] == 98 and w["lat"] == 36.0 and abs(w["lon"] + 84.3167) < 1e-3, w
assert G.where({}, "GPS PRN 03 U/S") == {}

# reading groups, first that applies
assert G.kind("ZDV NAV GPS (WSMRNM GPS 26-18) (INCLUDING WAAS, GBAS, AND ADS-B) MAY NOT BE AVBL") == "test"
assert G.kind("GPS NAV NOTICE ADVISORY TO NAVSTAR USERS (NANU) 2026041") == "satellite"
assert G.kind("GPS NAV PRN 25 U/S") == "satellite"
assert G.kind("POSS GNSS FAILURE WI AD AREA.") == "interference"
assert G.kind("GNSS JAMMING AND SPOOFING OCCURRENCES CAN BE EXPECTED WITHIN FIR EPWW.") == "interference"
assert G.kind("SEVASTOPOL/BELBEK GBAS CH 22105 109.250 MHZ U/S.") == "equipment"

# copies to several US centres group once; the same words at two aerodromes stay two
t1 = "ZDV NAV GPS (WSMRNM GPS 26-18) (INCLUDING WAAS, GBAS, AND ADS-B) MAY NOT BE AVBL WI A 381NM RADIUS CENTERED AT 333921N1063127W FL400-UNL. DLY 0400 - 1200"
t2 = "ZLA NAV GPS (WSMRNM GPS 26-18) (INCLUDING WAAS, GBAS, AND ADS-B) MAY NOT BE AVBL WI A 381NM RADIUS CENTERED AT 333921N1063127W FL400-UNL."
assert G.group_key(t1) == G.group_key(t2)
assert G.group_key("NAV PRN 25 U/S") == G.group_key("GPS NAV PRN 25 U/S")
d = day_file("2026-11-18", [
    notice("10/113", t1, loc="ZDV", fir=None, cls="DOM"), notice("A4799/26", t2, loc="KZLA", fir="KZLA"),
    notice("G0066/26", "GNSS FAILURE POSS WI AD AREA.", "4323N04542E", "025"),
    notice("G0102/26", "GNSS FAILURE POSS WI AD AREA.", "6114N04642E", "025", loc="ULKK", fir="ULLL"),
    notice("G4334/13", "RNAV (GNSS) SID AND STAR PROCEDURES", "4054N02919E", "005", loc="LTFJ", fir="LTBB",
           issued="2015-01-07T07:12:00Z", end="PERM")])
s = G.site_day(d)
assert s["n"] == 5 and s["groups"] == 4, (s["n"], s["groups"])
assert [r["kind"] for r in s["notices"]] == ["test", "interference", "interference", "equipment"], s["notices"]
lead = s["notices"][0]
assert lead["number"] == "A4799/26" and lead["copies"] == [{"number": "10/113", "location": "ZDV"}], lead
assert lead["geo"] == "text" and lead["radius_nm"] == 381 and lead["test"] == "WSMRNM GPS 26-18"
assert s["notices"][3]["end"] == "PERM" and s["notices"][3]["geo"] == "q"
assert s["source_note"] == NOTE and "FAA data" not in s["kinds"].values()
assert s["counts"] == {"test": 1, "satellite": 0, "interference": 2, "equipment": 1, "other": 0}

# the archive: copies a new day, skips an unchanged one, copies again on a rewrite, keeps a day Launch dropped
with tempfile.TemporaryDirectory() as tmp:
    state = {"index": {"source_note": NOTE, "rule": "gnss-1.0", "days": [
        {"day": "2026-11-18", "written_at": "2026-11-19T00:19:38Z", "revised_at": None,
         "url": G.BASE + "2026-11-18.json"}]}, "2026-11-18": day_file("2026-11-18", [notice("G1/26", "GNSS FAILURE POSS")])}

    def fetch(url):
        key = "index" if url.endswith("index.json") else url.rsplit("/", 1)[1][:-5]
        return json.loads(json.dumps(state[key]))

    now = datetime(2026, 11, 19, 6, 0, tzinfo=timezone.utc)
    assert G.archive(tmp, fetch=fetch, now=now) == ["2026-11-18"]
    assert G.archive(tmp, fetch=fetch, now=now) == []
    state["index"]["days"][0]["revised_at"] = "2026-11-20T03:00:00Z"
    state["2026-11-18"] = day_file("2026-11-18", [notice("G1/26", "GNSS FAILURE POSS"), notice("G2/26", "GNSS LOSS")],
                                   revised="2026-11-20T03:00:00Z")
    assert G.archive(tmp, fetch=fetch, now=now) == ["2026-11-18"]
    idx = json.load(open(os.path.join(tmp, G.INDEX), encoding="utf-8"))
    assert idx["days"]["2026-11-18"]["n"] == 2 and idx["days"]["2026-11-18"]["copies"] == 2, idx
    assert idx["source_note"] == NOTE
    state["index"]["days"] = []                                 # Launch dropped the day (older than 14 days)
    assert G.archive(tmp, fetch=fetch, now=now) == []
    assert "2026-11-18" in json.load(open(os.path.join(tmp, G.INDEX), encoding="utf-8"))["days"]
    # a file that isn't what the schema promises is skipped, not archived
    state["index"]["days"] = [{"day": "2026-11-19", "written_at": "x", "url": G.BASE + "2026-11-19.json"}]
    state["2026-11-19"] = day_file("2026-11-20", [])
    assert G.archive(tmp, fetch=fetch, now=now) == []
    # the site step reads the archive
    out = os.path.join(tmp, "site")
    days = G.site(tmp, out)
    assert [x["day"] for x in days] == ["2026-11-18"] and days[0]["n"] == 2
    assert os.path.exists(os.path.join(out, "data", "notams", "2026-11-18.json"))

print("ok: gnss_notams archive, geometry, grouping and reading groups")
