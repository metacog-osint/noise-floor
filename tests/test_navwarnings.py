"""Offline tests for tools/navwarnings.py (parse an NGA smaps record; proximity and window). Run as a plain script."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import navwarnings as N  # noqa: E402

# HYDROARC 280/26 as the smaps endpoint returned it on 28 Oct 2026 (US government work)
REC = {"navArea": "XX", "msgSqncNumber": 280, "createdOn": "051820Z OCT 2026", "status": "CANCELED",
       "cancelledOn": "131600Z OCT 2026",
       "msgText": "051820Z OCT 26\nHYDROARC 280/26.\nBARENTS SEA.\nWHITE SEA.\nRUSSIA.\n1. MISSILE OPERATIONS 0400Z TO 1500Z DAILY\n"
                  "   10 THRU 13 OCT IN AREAS BOUND BY:\n   A. 73-48.00N 040-10.00E, 68-33.00N 044-42.00E,\n"
                  "      66-59.00N 044-24.00E, 66-54.00N 043-31.00E,\n      73-33.00N 037-31.00E.\n"
                  "   B. 67-42.00N 045-18.00E, 67-07.00N 045-42.00E,\n      67-07.00N 045-37.00E, 67-22.00N 044-55.00E.\n"
                  "2. CANCEL THIS MSG 131600Z OCT 26.\n"}


def test_parse():
    w = N.parse(REC)
    assert w["id"] == "HYDROARC 280/26", w["id"]                  # from the text, not the record's navArea
    assert w["issued"] == "2026-10-05T18:20Z" and w["cancel"] == "2026-10-13T16:00Z", (w["issued"], w["cancel"])
    assert w["activity"] == "MISSILE OPERATIONS", w["activity"]
    assert w["regions"] == ["BARENTS SEA", "WHITE SEA", "RUSSIA"], w["regions"]
    assert len(w["points"]) == 9 and w["points"][0] == [73.8, 40.1667], w["points"][:2]


def test_near():
    w = N.parse(REC)
    hit = N.near([w], 73.06, 53.72, 500, "2026-10-01T00:00Z", "2026-10-20T00:00Z")
    assert len(hit) == 1 and 430 <= hit[0]["km"] <= 445, hit         # Pankovo: about 437 km to the nearest vertex
    assert N.near([w], 73.06, 53.72, 400) == []                      # outside 400 km
    assert N.near([w], 73.06, 53.72, 500, "2026-10-14T00:00Z") == [] # cancelled before the window
    buoy = dict(w, activity="MOORING BUOY ADRIFT")
    assert N.near([buoy], 73.06, 53.72, 500) == [] and N.near([buoy], 73.06, 53.72, 500, military=False)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"test_navwarnings: ok ({len(tests)} tests)")


if __name__ == "__main__":
    main()
