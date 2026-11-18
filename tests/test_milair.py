"""Military air lane (tools/milair.py, tools/milair_job.py, feed_v2.milair_items) on synthetic archive fixtures.
Run as a plain script: python tests/test_milair.py"""
import copy
import gzip
import io
import json
import os
import sys
import tarfile
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "doctrine", "kit", "python"))
import feed_v2  # noqa: E402
import milair as M  # noqa: E402
import milair_job  # noqa: E402
from tic_doctrine import lint  # noqa: E402

DAY = "2026-11-10"
DAY0 = datetime(2026, 11, 10, tzinfo=timezone.utc).timestamp()
GULF = (25.1, 51.3)          # over Qatar
LEVANT = (32.5, 34.8)
ROLES = M.load_roles()
PA = M.load_plane_alert()
REGIONS = M.load_regions()


def trace(icao, t=None, db=1, desc=None, points=(), ts=DAY0):
    """A readsb trace_full file: points are (seconds after ts, lat, lon, alt, source type)."""
    d = {"icao": icao, "timestamp": ts, "version": "readsb test", "trace": []}
    if db is not None:
        d["dbFlags"] = db
    if t:
        d["t"] = t
    if desc:
        d["desc"] = desc
    for s, la, lo, alt, src in points:
        d["trace"].append([s, la, lo, alt, 250.0, 90.0, 0, None, None, src, None, None, None, None])
    return d


def tar_of(traces):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for d in traces:
            raw = gzip.compress(json.dumps(d).encode())
            ti = tarfile.TarInfo(f"./traces/{d['icao'][-2:]}/trace_full_{d['icao']}.json")
            ti.size = len(raw)
            tf.addfile(ti, io.BytesIO(raw))
    return buf.getvalue()


def test_tables():
    assert M.role_of("K35R", "Boeing KC-135R", ROLES) == "tanker"
    assert M.role_of("K35R", "Boeing RC-135W", ROLES) == "isr"            # Rivet Joint filed on the KC-135 code
    assert M.role_of("A332", "Airbus A330-243-MRTT Phenix", ROLES) == "tanker"
    assert M.role_of("A332", "Airbus A330-243", ROLES) == "transport"
    assert M.role_of("C30J", "Lockheed KC-130J Hercules", ROLES) == "tanker"
    assert M.role_of("C30J", "Lockheed MC-130J Hercules", ROLES) == "transport"
    assert M.role_of("C130", "Lockheed EC-130H Hercules", ROLES) == "isr"
    assert M.role_of("B703", "E-8C J-STARS", ROLES) == "isr"
    assert M.role_of("B52", "", ROLES) == "bomber" and M.role_of("F16", "", ROLES) == "fighter"
    assert M.role_of("C17", "", ROLES) == "transport" and M.role_of("P8", "", ROLES) == "isr"
    assert M.role_of("", "", ROLES) == "unknown" and M.role_of("ZZZZ", "", ROLES) == "other"
    assert M.role_of("H60", "", ROLES) == "rotary" and M.role_of("TEX2", "", ROLES) == "trainer"
    # every listed type maps to a known role (load_roles raises otherwise) and the snapshot is well formed
    assert len(ROLES) > 150 and all(len(h) == 6 for h in PA) and len(PA) > 9000
    meta = json.load(open(os.path.join(ROOT, "registry", "plane_alert_mil.meta.json"), encoding="utf-8"))
    assert meta["licence"].startswith("ODbL") and meta["kept"] == len(PA)


def test_regions():
    """No two regions overlap: sample a grid over every box and check each point lands in one region only."""
    ids = [r["id"] for r in REGIONS]
    assert ids[0] == "gulf" and len(set(ids)) == len(ids)
    for r in REGIONS:
        for w, s, e, n in r["boxes"]:
            assert w < e and s < n, r["id"]
            for i in range(11):
                for j in range(11):
                    la, lo = s + (n - s) * (i + 0.5) / 11.5, w + (e - w) * (j + 0.5) / 11.5
                    hits = [x["id"] for x in REGIONS if any(bw <= lo < be and bs <= la < bn for bw, bs, be, bn in x["boxes"])]
                    assert hits == [r["id"]], (r["id"], la, lo, hits)
    assert REGIONS[M.region_of(*GULF, REGIONS)]["id"] == "gulf"
    assert REGIONS[M.region_of(*LEVANT, REGIONS)]["id"] == "levant"
    assert M.region_of(45.0, -100.0, REGIONS) is None


def fixture_traces():
    return [
        # tanker over the Gulf, ADS-B, hours 1 and 2
        trace("ae1001", "K35R", points=[(3700, *GULF, 25000, "adsb_icao"), (7300, *GULF, 25000, "adsb_icao")]),
        # tanker over the Gulf heard by MLAT only in hour 1; ADS-B over the Levant in hour 3
        trace("ae1002", "K35R", points=[(3800, *GULF, 24000, "mlat"), (11000, *LEVANT, 24000, "adsb_icao")]),
        # fighter on the ground only: not counted anywhere
        trace("ae1003", "F16", points=[(3600, *GULF, "ground", "adsb_icao")]),
        # a C-17 with a Mode S-only "position" (not usable) and one TIS-B position
        trace("ae1004", "C17", points=[(100, *GULF, 30000, "mode_s"), (200, *GULF, 30000, "tisb_icao")]),
        # not military: no flag, not listed
        trace("a00001", "B738", db=0, points=[(100, *GULF, 35000, "adsb_icao")]),
        # listed in plane-alert-db but not flagged by adsb.lol, no type in the trace: type from the snapshot
        trace(next(h for h, v in PA.items() if v[0] == "C17"), None, db=0, points=[(5000, *GULF, 28000, "adsb_icao")]),
        # positions outside the day are ignored
        trace("ae1005", "B52", points=[(-50, *GULF, 30000, "adsb_icao"), (90000, *GULF, 30000, "adsb_icao")]),
        # non-ICAO address
        trace("~ae1006", "K35R", points=[(100, *GULF, 30000, "adsb_icao")]),
    ]


def test_day_scan():
    raw = tar_of(fixture_traces())
    doc = M.run_day(DAY, [lambda: io.BytesIO(raw)], {"archive": "fixture", "parts": 1})
    c = doc["counts"]
    assert c["traces"] == 8 and c["military"] == 6, c          # ~ address and the airliner are out
    assert c["via"] == {"adsblol": 5, "plane-alert": 1}, c["via"]
    g = doc["regions"]["gulf"]
    assert g["distinct"]["tanker"] == 2 and g["distinct"]["transport"] == 2 and g["distinct"]["fighter"] == 0
    assert g["distinct"]["bomber"] == 0 and g["distinct"][M.ALL] == 4
    assert g["hours"]["tanker"][1] == 2 and g["hours"]["tanker"][2] == 1 and sum(g["hours"]["tanker"]) == 3
    assert g["mlat_only_hours"]["tanker"][1] == 1 and g["mlat_only_distinct"]["tanker"] == 1
    assert doc["regions"]["levant"]["distinct"]["tanker"] == 1 and doc["regions"]["levant"]["hours"]["tanker"][3] == 1
    assert doc["regions"][M.WORLD]["distinct"][M.ALL] == 4
    assert doc["source"]["bytes"] == len(raw) and len(doc["source"]["sha256"]) == 64
    text = json.dumps(doc)
    assert "ae1001" not in text and "ae1002" not in text, "no aircraft identifiers in the day file"
    assert doc["licence"] == "ODbL 1.0" and "lower bound" in doc["lower_bound"].lower()


def synthetic_docs(n_days, usual, today, role="tanker"):
    """Day docs with `usual` aircraft of `role` over the Gulf in hours 8-11 each day, and `today` on the last day."""
    base = M.aggregate([], REGIONS)
    docs = {}
    d_last = datetime(2026, 11, 10)
    for k in range(n_days, -1, -1):
        day = (d_last - timedelta(days=k)).strftime("%Y-%m-%d")
        regs = copy.deepcopy(base)
        n = today if k == 0 else usual
        for h in range(8, 12):
            regs["gulf"]["hours"][role][h] = n
            regs["gulf"]["hours"][M.ALL][h] = n
        regs["gulf"]["distinct"][role] = regs["gulf"]["distinct"][M.ALL] = n
        docs[day] = {"format": M.FORMAT, "day": day, "regions": regs, "made_at": f"{day}T06:00:00Z", "counts": {}}
    return docs


def test_reading_levels():
    r = M.reading(synthetic_docs(28, 4, 4), DAY)
    g = r["regions"]["gulf"]
    assert r["baseline_days"] == 28 and g["tanker"]["usual_aircraft_hours"] == 16 and g["tanker"]["level"] == "near"
    g = M.reading(synthetic_docs(28, 4, 13), DAY)["regions"]["gulf"]
    assert g["tanker"]["level"] == "above" and g["tanker"]["band"] == 3, g["tanker"]   # 52 / 16 = 3.25
    assert g["tanker"]["week_mean_distinct"] == round((6 * 4 + 13) / 7, 1)
    g = M.reading(synthetic_docs(28, 1, 2), DAY)["regions"]["gulf"]
    assert g["tanker"]["level"] == "near", "2x but under the floor of 3 tankers"
    g = M.reading(synthetic_docs(28, 4, 1), DAY)["regions"]["gulf"]
    assert g["tanker"]["level"] == "below"
    g = M.reading(synthetic_docs(28, 0, 5), DAY)["regions"]["gulf"]
    assert g["tanker"]["level"] == "above" and g["tanker"]["band"] == 4, "none usual: the ratio uses a floor of 1"
    r = M.reading(synthetic_docs(10, 4, 13), DAY)
    assert r["baseline_days"] == 10 and r["regions"]["gulf"]["tanker"]["level"] == "building"
    # same hours: a shift of the same aircraft to other hours keeps the aircraft-hours ratio at 1
    docs = synthetic_docs(28, 4, 4)
    h = docs[DAY]["regions"]["gulf"]["hours"]["tanker"]
    docs[DAY]["regions"]["gulf"]["hours"]["tanker"] = h[12:] + h[:12]
    assert M.reading(docs, DAY)["regions"]["gulf"]["tanker"]["ratio"] == 1.0
    # sparse: one aircraft-hour a day at a different hour each day is usual 1, not the 0 that per-hour medians give
    docs = synthetic_docs(28, 0, 0)
    for i, (day, d) in enumerate(sorted(docs.items())):
        d["regions"]["gulf"]["hours"]["tanker"][i % 24] = 1
        d["regions"]["gulf"]["distinct"]["tanker"] = 1
    g = M.reading(docs, DAY)["regions"]["gulf"]["tanker"]
    assert g["usual_aircraft_hours"] == 1 and g["ratio"] == 1.0 and g["level"] == "near", g


def test_weekends():
    """Workdays and weekends have their own usual levels, by the region's own weekend."""
    base = M.aggregate([], REGIONS)
    docs = {}
    last = datetime(2026, 11, 14)                     # a Saturday
    for k in range(28, -1, -1):
        d = last - timedelta(days=k)
        day = d.strftime("%Y-%m-%d")
        regs = copy.deepcopy(base)
        for rid, weekend in (("baltic", (5, 6)), ("gulf", (4, 5))):
            n = 3 if d.weekday() in weekend else 10
            for h in range(8, 12):
                regs[rid]["hours"][M.ALL][h] = regs[rid]["hours"]["transport"][h] = n
            regs[rid]["distinct"][M.ALL] = regs[rid]["distinct"]["transport"] = n
        docs[day] = {"format": M.FORMAT, "day": day, "regions": regs}
    sat = M.reading(docs, "2026-11-14")["regions"]
    assert sat["baltic"]["baseline"] == {"day_type": "weekend", "weekend": [5, 6], "days": 8, "min_days": 5}
    assert sat["baltic"][M.ALL]["level"] == "near" and sat["baltic"][M.ALL]["usual_aircraft_hours"] == 12
    assert sat["gulf"]["baseline"]["day_type"] == "weekend" and sat["gulf"][M.ALL]["level"] == "near"
    sun = M.reading(docs, "2026-11-08")["regions"]   # Sunday: weekend in the Baltic, a workday in the Gulf
    assert sun["baltic"]["baseline"]["day_type"] == "weekend" and sun["gulf"]["baseline"]["day_type"] == "workday"
    assert sun["gulf"][M.ALL]["usual_aircraft_hours"] == 40
    assert M.day_type("2026-11-13", (4, 5)) == "weekend" and M.day_type("2026-11-13") == "workday"


def test_site_and_feed():
    docs = synthetic_docs(28, 4, 13)
    with tempfile.TemporaryDirectory() as tmp:
        rel, site = os.path.join(tmp, "rel"), os.path.join(tmp, "site")
        os.makedirs(rel)
        for day, d in docs.items():
            with open(os.path.join(rel, f"{day}.milair.json"), "w", encoding="utf-8") as f:
                json.dump(d, f)
        r = M.site(rel, site)
        assert r["day"] == DAY and os.path.exists(os.path.join(site, "data", "milair", "history.json"))
        rd = json.load(open(os.path.join(site, "data", "milair", "reading.json"), encoding="utf-8"))
        board = {"freshness": {"aircraft_day": "2026-11-11"}}
        now = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
        feed = feed_v2.build(board, [], now=now, milair=rd)
        assert not feed_v2.check(feed), feed_v2.check(feed)
        items = [f for f in feed["features"] if f["properties"]["id"].startswith("noisefloor-milair-")]
        assert [f["properties"]["id"] for f in items] == [f"noisefloor-milair-gulf-{DAY}"], "only regions with aircraft"
        p, geom = items[0]["properties"], items[0]["geometry"]
        assert p["tier"] == "routine" and p["kind"] == "observation", "a measurement, never an alert"
        assert p["measure"] == {"name": "military_aircraft_hours", "value": 52, "expected": 16.0,
                                "unit": p["measure"]["unit"]} and "lower bound" in p["measure"]["unit"]
        assert p["measures"]["level"] == "above" and p["measures"]["by_role"]["tanker"]["band"] == 3
        assert p["baseline_ref"]["id"] == "noisefloor-milair-same-hours-28d"
        assert p["health"]["lane"] == "milair" and p["health"]["state"] == "fresh" and p["health"]["baseline_days"] == 20
        assert p["data_as_of"] == f"{DAY}T00:00:00Z" and "coverage_fraction" not in p
        assert "lower bound" in p["summary"] and "lower bound" in p["title"]
        assert "at least 3x its usual level" in p["summary"] and "tankers 13" in p["summary"]
        assert [s["id"] for s in p["sources"]] == ["adsblol-archive", "plane-alert-db"]
        assert "QA" in p["countries"], p["countries"]
        assert geom["type"] == "Polygon" and geom["coordinates"][0][0] == [47.5, 23.5]
        with open(os.path.join(tmp, "feed.geojson"), "w", encoding="utf-8") as f:
            json.dump(feed, f)
        rep = lint.lint_files([os.path.join(tmp, "feed.geojson")], os.path.join(ROOT, "doctrine"))
        assert lint.print_report(rep), "the kit's tradecraft linter must pass"
        # late and stale: health says so; past a week the items are withheld
        late = feed_v2.build(board, [], now=now + timedelta(days=3), milair=rd)
        lp = next(f["properties"] for f in late["features"] if f["properties"]["id"].startswith("noisefloor-milair-"))
        assert lp["health"]["state"] == "late"
        # coverage_fraction: the receiver network's on the item's own day, as the GNSS items carry it
        days = ([{"day": f"2026-10-{d:02d}", "hexes": 1000} for d in range(14, 32)]
                + [{"day": f"2026-11-{d:02d}", "hexes": 1000} for d in range(1, 10)]
                + [{"day": DAY, "hexes": 900}])
        cp = next(f["properties"] for f in feed_v2.build(board, days, now=now, milair=rd)["features"]
                  if f["properties"]["id"].startswith("noisefloor-milair-"))
        assert cp["coverage_fraction"] == 0.9, cp.get("coverage_fraction")
        gone = feed_v2.build(board, [], now=now + timedelta(days=9), milair=rd)
        assert not [f for f in gone["features"] if f["properties"]["id"].startswith("noisefloor-milair-")]
        # no reading file: no items, and the rest of the feed is untouched
        assert len(feed_v2.build(board, [], now=now)["features"]) == len(feed["features"]) - 1


def test_building_feed():
    rd = M.reading(synthetic_docs(5, 4, 4), DAY)
    rd["regions_meta"] = {x["id"]: {"name": x["name"], "boxes": x["boxes"], "watchfloor": x["watchfloor"]}
                          for x in REGIONS}
    feed = feed_v2.build({"freshness": {"aircraft_day": DAY}}, [], now=datetime(2026, 11, 11, tzinfo=timezone.utc),
                         milair=rd)
    assert not feed_v2.check(feed)
    p = next(f["properties"] for f in feed["features"] if f["properties"]["id"].startswith("noisefloor-milair-"))
    assert "baseline_ref" not in p and "expected" not in p["measure"] and "needs 12 earlier workdays" in p["summary"]


def test_job_days():
    t = datetime(2026, 11, 18).date()
    assert milair_job.days_from([], t) == ["2026-11-15", "2026-11-16", "2026-11-17"]
    assert milair_job.days_from(["2026-10-30:2026-11-01", "2026-11-05"], t) == [
        "2026-10-30", "2026-10-31", "2026-11-01", "2026-11-05"]
    assert milair_job.data_tag("2026-11-05") == "milair-data-2026"
    assert milair_job.upstream("2026-11-05") == ("adsblol/globe_history_2026", "v2026.11.05-planes-readsb-prod-0")


def test_live_probe():
    snap = {"ac": [{"hex": "ae1001", "t": "K35R", "lat": GULF[0], "lon": GULF[1], "alt_baro": 25000, "mlat": []},
                   {"hex": "ae1002", "t": "C17"},
                   {"hex": "ae1003", "t": "F16", "lat": GULF[0], "lon": GULF[1], "alt_baro": "ground"}]}
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "mil.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(snap, f)
        r = M.live(p, REGIONS, ROLES, PA)
    assert r["aircraft"] == 3 and r["with_position"] == 1 and r["no_position"] == 1 and r["regions"] == {"gulf": 1}


def main():
    test_tables()
    test_regions()
    test_day_scan()
    test_reading_levels()
    test_weekends()
    test_site_and_feed()
    test_building_feed()
    test_job_days()
    test_live_probe()
    print("test_milair: ok")


if __name__ == "__main__":
    main()
