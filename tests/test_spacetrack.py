"""Offline tests for tools/spacetrack.py (Sentinel's Space-Track client). Run as a plain script: python tests/test_spacetrack.py"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import spacetrack as S  # noqa: E402


def test_elset_row():
    g = {"NORAD_CAT_ID": "46984", "EPOCH": "2026-10-24T03:12:45.123456", "MEAN_MOTION": "12.80930000",
         "ECCENTRICITY": "0.0007", "INCLINATION": "66.04", "RA_OF_ASC_NODE": "101.5", "ARG_OF_PERICENTER": "270.1",
         "MEAN_ANOMALY": "89.9", "BSTAR": "", "MEAN_MOTION_DOT": "-0.0000001", "MEAN_MOTION_DDOT": "0",
         "ELEMENT_SET_NO": "999", "REV_AT_EPOCH": "x"}
    r = S.elset_row(g)
    assert r["norad"] == 46984 and r["epoch"] == g["EPOCH"] and abs(r["n"] - 12.8093) < 1e-9
    assert r["bstar"] is None and r["elset"] == 999 and r["rev"] is None   # empty and bad fields read as missing


def test_history_path():
    p = S.history_path([46984, "39086"], "2026-10-23", "2026-10-25")
    assert p.startswith("class/gp_history/NORAD_CAT_ID/46984,39086/EPOCH/2026-10-23--2026-10-25/")
    assert p.endswith("/format/json") and "/predicates/" + ",".join(S.ELSET) + "/" in p


def test_no_gp_query():
    """Noisefloor makes no gp (current catalogue) query: Orbit does, on the shared account (18 Nov 2026)."""
    src = open(os.path.join(ROOT, "tools", "spacetrack.py"), encoding="utf-8").read()
    assert "class/gp/" not in src


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"test_spacetrack: ok ({len(tests)} tests)")
