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


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
            print("ok", k)
