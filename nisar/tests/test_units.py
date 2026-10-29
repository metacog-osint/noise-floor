"""Small offline checks. Run: python -m pytest tests -q   (or python tests/test_units.py)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from nisar_rfi import bands, cmr, geometry as geo, places  # noqa: E402

# Shaped like a CMR umm_json item for a Baltic GCOV granule (19 Oct 2026, track 109 D, frame 60);
# field names and values as returned by CMR, trimmed to what the parser reads.
UMM_ITEM = {
    "meta": {"concept-id": "G4381537306-ASF"},
    "umm": {
        "GranuleUR": "NISAR_L2_PR_GCOV_033_109_D_060_2005_DHDH_A_20261019T182312_20261019T182348_P05023_N_F_J_001",
        "TemporalExtent": {"RangeDateTime": {"BeginningDateTime": "2026-10-19T18:23:12.000000Z",
                                             "EndingDateTime": "2026-10-19T18:23:48.999342Z"}},
        "SpatialExtent": {"HorizontalSpatialDomain": {"Geometry": {"GPolygons": [{"Boundary": {"Points": [
            {"Longitude": 15.86998, "Latitude": 57.65354}, {"Longitude": 14.227, "Latitude": 55.58533},
            {"Longitude": 17.78673, "Latitude": 54.65017}, {"Longitude": 19.58353, "Latitude": 56.66976},
            {"Longitude": 15.86998, "Latitude": 57.65354}]}}]}}},
        "AdditionalAttributes": [
            {"Name": "ASCENDING_DESCENDING", "Values": ["DESCENDING"]},
            {"Name": "FRAME_NUMBER", "Values": ["60"]}, {"Name": "TRACK_NUMBER", "Values": ["109"]},
            {"Name": "FREQUENCIES", "Values": ["A", "B"]}, {"Name": "STACK_ID", "Values": ["109_D_060"]},
            {"Name": "RANGE_BANDWIDTH_CONCAT", "Values": ["20+5"]}, {"Name": "FULL_FRAME", "Values": ["TRUE"]},
            {"Name": "FREQUENCY_A_POLARIZATION_CONCAT", "Values": ["HH+HV"]},
        ],
        "RelatedUrls": [
            {"URL": "https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L2_GCOV_PROVISIONAL_V1/X/X.h5", "Type": "GET DATA"},
            {"URL": "s3://sds-n-cumulus-prod-nisar-products/X/X.h5", "Type": "GET DATA VIA DIRECT ACCESS"},
            {"URL": "https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L2_GCOV_PROVISIONAL_V1/X/X.rc.yaml", "Type": "EXTENDED METADATA"},
            {"URL": "https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L2_GCOV_PROVISIONAL_V1/X/X_QA_SUMMARY.csv", "Type": "VIEW RELATED INFORMATION"},
        ],
    },
}


def test_cmr_parse():
    g = cmr.parse(UMM_ITEM)
    assert g["track"] == 109 and g["frame"] == 60 and g["direction"] == "D"
    assert g["stack"] == "109_D_060" and g["mode"] == "20+5" and g["frequencies"] == ["A", "B"]
    assert g["start"] == "2026-10-19T18:23:12Z"
    assert g["links"]["data"].endswith(".h5") and g["links"]["data"].startswith("https://")
    assert g["links"]["runconfig"].endswith(".rc.yaml")
    assert len(g["footprint"]) == 5 and g["full_frame"]


def test_bands():
    assert bands.band_edges("20+5", "A") == (1219.0, 1239.0)
    assert bands.gnss_in(1219, 1239) == ["GPS L2"]
    assert "GPS L2" not in bands.gnss_in(*bands.band_edges("20+5", "B"))
    assert "GLONASS G2" in bands.gnss_in(*bands.band_edges("40+5", "A"))
    assert "jammer" in bands.interpretation(["A"], "20+5")


def test_geometry():
    d = geo.ground_track_heading(55, "D")
    a = geo.ground_track_heading(55, "A")
    assert 190 < d < 205 and 335 < a < 350          # SSW descending, NNW ascending at Baltic latitudes
    r = geo.line_intersection(54.6, 19.7, 107, 54.6, 19.8, 73)
    assert r and r[2] > 30


def test_places():
    where, iso = places.describe(54.71, 20.51)
    assert iso == "RU" and "Kaliningrad" in where


def test_site_signature():
    from nisar_rfi import sites

    def tone(lo, hi):
        return {"freq_runs_mhz": [[lo, hi, 0.8]], "band_text": f"{lo}-{hi} MHz", "method": "tables", "bands": ["A"], "band": "A"}
    assert sites.signature(tone(1227.0, 1228.2)) == "L2"
    assert sites.signature(tone(1220.9, 1221.4)) == "other"
    assert sites.signature({"band_text": "band A broadband (1219-1239 MHz)", "method": "broadband", "bands": ["A"]}) == "L2"
    assert sites.signature({"band_text": "band B broadband (1291-1296 MHz)", "method": "broadband", "bands": ["B"]}) == "other"
    assert sites.signature({"band_text": "A", "method": "tables", "bands": ["A"]}) == "other"    # no frequency detail

    # The Pankovo case (28 Oct 2026): an L2 fix 9 km from an older radar-like site and 20 km from an L2 site joins the
    # L2 site, instead of the nearest one.
    state = {"sites": {}, "detections": [], "processed": {}}
    cfg = {"sites": {"site_prefix": "NZ"}}

    def det(i, lat, lon, lo, hi):
        d = tone(lo, hi)
        d.update(id=f"d{i}", lat=lat, lon=lon, peak_z=5.0)
        return d
    sites.update(state, {"track": 51, "direction": "D", "start": "2026-06-29T17:44:38Z"}, [det(1, 73.25, 53.76, 1221.0, 1221.4)], cfg)
    sites.update(state, {"track": 112, "direction": "A", "start": "2026-10-07T23:10:54Z"}, [det(2, 73.01, 53.72, 1227.1, 1228.2)], cfg)
    sites.update(state, {"track": 51, "direction": "D", "start": "2026-10-15T17:44:35Z"}, [det(3, 73.185, 53.567, 1227.0, 1228.2)], cfg)
    assert state["sites"]["NZ-0001"]["sig"] == "other" and state["sites"]["NZ-0001"]["detections"] == ["d1"], state["sites"]
    assert state["sites"]["NZ-0002"]["sig"] == "L2" and state["sites"]["NZ-0002"]["detections"] == ["d2", "d3"], state["sites"]


def test_site_late_pass():
    """A pass older than a site's latest coverage (a retried failure) re-derives the site from its time-ordered
    record, raises no RETURNED or QUIET event, and prune keeps the newest coverage, not the last appended."""
    from datetime import datetime, timezone
    from nisar_rfi import sites
    state = {"sites": {}, "detections": [], "processed": {}}
    cfg = {"sites": {"site_prefix": "T", "quiet_after": 2}}
    box = [[19.0, 54.0], [21.0, 54.0], [21.0, 56.0], [19.0, 56.0], [19.0, 54.0]]

    def g(day, track=1):
        return {"track": track, "direction": "A", "start": f"2026-{day}T12:00:00Z", "footprint": box}

    def det(i):
        return {"id": f"d{i}", "lat": 55.0, "lon": 20.0, "peak_z": 5.0, "bands": ["A"], "method": "tables"}

    def kinds(ev):
        return [e["kind"] for e in ev]
    assert kinds(sites.update(state, g("10-01"), [det(1)], cfg)) == ["NEW"]
    sites.update(state, g("10-10"), [], cfg)
    assert kinds(sites.update(state, g("10-20"), [], cfg)) == ["QUIET"]
    s = state["sites"]["T-0001"]
    # late detection between the two clean passes: active again (one clean pass since), but no RETURNED alert
    assert kinds(sites.update(state, g("10-15", 2), [det(2)], cfg)) == []
    assert (s["status"], s["clean_streak"], s["last_seen"][:10]) == ("ACTIVE", 1, "2026-10-15"), s
    # late detection before the first: first_seen moves back; late clean pass: no QUIET event, order kept
    sites.update(state, g("08-01", 3), [det(3)], cfg)
    assert kinds(sites.update(state, g("09-01", 4), [], cfg)) == []
    assert s["first_seen"][:10] == "2026-08-01" and s["status"] == "ACTIVE"
    assert [cv["start"][:10] for cv in s["coverage"]] == ["2026-08-01", "2026-09-01", "2026-10-01", "2026-10-10",
                                                           "2026-10-15", "2026-10-20"]
    # back in order: the next clean pass makes it QUIET with an event, as before
    assert kinds(sites.update(state, g("10-30"), [], cfg)) == ["QUIET"]
    # prune keeps the newest 60 by time even if an old entry was appended last
    s["coverage"] = [{"pass": f"p{i}", "start": f"2026-10-{1 + i % 28:02d}T{i % 24:02d}:00:00Z", "active": False}
                     for i in range(70)] + [{"pass": "old", "start": "2026-08-15T00:00:00Z", "active": True}]
    sites.prune(state, 400, datetime(2026, 10, 31, tzinfo=timezone.utc))
    assert len(s["coverage"]) == 60 and all(cv["pass"] != "old" for cv in s["coverage"])


def test_mode_hearing():
    """A 5 MHz VV pass (tables span 1218.5-1224.5 MHz) can't hear the L2 centre or broadband power; 20+5 tables span
    1215-1263 MHz, so they hear 1247 MHz; unchecked modes count as able to hear. Clean passes in a mode that can't
    hear a site don't make it QUIET; older records get their modes back from the processed-pass log."""
    from nisar_rfi import sites
    l2, low, mid, broad = [("tone", 1227.0, 1228.2)], [("tone", 1221.0, 1221.0)], [("tone", 1247.2, 1247.3)], [("broad", 1219.0, 1239.0)]
    assert not bands.hears(["5"], l2) and bands.hears(["5"], low) and not bands.hears(["5"], broad)
    assert bands.hears(["20+5"], mid) and bands.hears(["20+5"], broad) and bands.hears(["5", "20+5"], l2)
    assert bands.hears(["40+5"], l2) and bands.hears([], l2) and bands.hears(["5"], [])
    d = {"band": "A", "mode": "20+5", "freq_runs_mhz": [[1227.1, 1228.2, 0.6]], "broadband": {"confidence": "HIGH"},
         "band_b": {"method": "broadband", "freq_runs_mhz": []}}
    assert bands.signal_needs(d) == [("tone", 1227.1, 1228.2), ("broad", 1219.0, 1239.0), ("broad", 1291.0, 1296.0)]

    state = {"sites": {}, "detections": [], "processed": {}}
    cfg = {"sites": {"site_prefix": "M", "quiet_after": 2}}
    box = [[52.0, 72.0], [56.0, 72.0], [56.0, 74.0], [52.0, 74.0], [52.0, 72.0]]

    def g(day, mode):
        return {"track": 1, "direction": "A", "start": f"2026-10-{day}T12:00:00Z", "footprint": box, "mode": mode}
    det = {"id": "d1", "lat": 73.0, "lon": 54.0, "peak_z": 5.0, "bands": ["A"], "method": "tables", **d}
    assert [e["kind"] for e in sites.update(state, g("07", "20+5"), [det], cfg)] == ["NEW"]
    s = state["sites"]["M-0001"]
    assert [e["kind"] for e in sites.update(state, g("08", "5"), [], cfg)] == []
    assert [e["kind"] for e in sites.update(state, g("09", "5"), [], cfg)] == []
    assert (s["status"], s["clean_streak"]) == ("ACTIVE", 0) and s["coverage"][-1]["modes"] == ["5"], s
    sites.update(state, g("10", "20+5"), [], cfg)
    assert [e["kind"] for e in sites.update(state, g("11", "20+5"), [], cfg)] == ["QUIET"]

    # an older record: no modes or needs stored; the processed log has the frames
    for cv in s["coverage"]:
        cv.pop("modes")
    s.pop("needs")
    state["detections"] = [det]
    state["processed"] = {f"G{day}": {"status": "ok", "track": 1, "direction": "A", "start": f"2026-10-{day}T12:00:00Z",
                                      "footprint": box, "mode": m} for day, m in (("07", "20+5"), ("08", "5"), ("09", "5"))}
    assert sites.fill_modes(state, 2) == 1
    assert [cv.get("modes") for cv in s["coverage"]] == [["20+5"], ["5"], ["5"], [], []], s["coverage"]
    assert s["status"] == "QUIET" and s["needs"], s          # the two 20+5 clean passes (modes unknown now) still count


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
            print("ok", k)
