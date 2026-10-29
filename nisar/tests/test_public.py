"""Offline checks for the public export (nisar_rfi/public.py): the gate, private fields, skipped areas.

Run: python tests/test_public.py (from nisar/). No network.
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from nisar_rfi import public  # noqa: E402


def det(i, start, track=54, direction="A", conf="MEDIUM", widespread=False, lat=73.05, lon=53.65):
    return {"id": f"d{i}", "start": start, "track": track, "direction": direction, "confidence": conf,
            "widespread": widespread, "ignored": None, "lat": lat, "lon": lon, "band": "A", "bands": ["A"],
            "band_text": "1227.0-1228.2 MHz (GPS L2)", "freq_runs_mhz": [[1227.0, 1228.2, 0.8]], "peak_hit": 0.8,
            "blocks": 100, "pols": ["HH", "HV"], "method": "tables", "granule": f"G{i}",
            # private or noisy fields that must not leave
            "interpretation": "Consistent with a GNSS jammer", "url": "https://cmr.example/x", "rfi_likelihood": {"AHH": 3},
            "site": "X"}


def site(sid, det_ids, coverage, lat=73.05, lon=53.65, **extra):
    return {"id": sid, "lat": lat, "lon": lon, "weight": 10.0, "first_seen": coverage[0]["start"],
            "last_seen": coverage[-1]["start"], "detections": det_ids, "coverage": coverage, "bands_seen": ["A"],
            "geometries": [], "status": "ACTIVE", "clean_streak": 0, "fix": None, "where": "near a place",
            "country": "RU", "baseline": True, **extra}


def cov(start, track=54, direction="A", active=True, modes=None):
    c = {"pass": f"{track:03d}{direction}{start[:13]}", "start": start, "active": active}
    if modes is not None:
        c["modes"] = modes
    return c


def write_state(folder, sites, dets, processed_starts):
    os.makedirs(folder, exist_ok=True)
    state = {"sites": {s["id"]: s for s in sites}, "detections": dets,
             "processed": {f"P{i}": {"start": t, "status": "ok"} for i, t in enumerate(processed_starts)}}
    json.dump(state, open(os.path.join(folder, "state.json"), "w"))


def main():
    work = tempfile.mkdtemp(prefix="nisar_public_")
    try:
        t1, t2, t3 = "2026-10-07T23:10:54Z", "2026-10-15T22:38:28Z", "2026-10-17T22:55:00Z"
        t4 = "2026-10-18T18:00:00Z"                     # a 5 MHz VV pass: it can't hear a tone at the L2 centre
        dets = [
            det(1, t1, track=112), det(2, t2, track=54),                               # A: two passes -> in
            det(3, t2, track=54, lat=70.0, lon=50.0), det(4, t2, track=54, lat=70.01, lon=50.0),  # B: one pass, two frames
            det(5, t1, lat=71.0, lon=51.0), det(6, t2, conf="LOW", lat=71.0, lon=51.0),  # C: one MEDIUM + one LOW
            det(7, t1, conf="HIGH", widespread=True, lat=72.6, lon=52.9),
            det(8, t2, conf="HIGH", widespread=True, lat=72.6, lon=52.9),
            det(9, t3, conf="HIGH", widespread=True, lat=72.6, lon=52.9),               # D: frame-wide flags only
            det(10, t1, lat=74.0, lon=55.0), det(11, t3, lat=74.0, lon=55.0),           # E: ignored site
        ]
        sites = [
            site("NZ-0001", ["d1", "d2"], [cov(t1, 112), cov(t2), cov(t3, 83, active=False),
                                           cov(t4, 51, active=False, modes=["5"])]),
            site("NZ-0002", ["d3", "d4"], [cov(t2)], lat=70.0, lon=50.0),
            site("NZ-0003", ["d5", "d6"], [cov(t1), cov(t2)], lat=71.0, lon=51.0),
            site("NZ-0004", ["d7", "d8", "d9"], [cov(t1), cov(t2), cov(t3)], lat=72.6, lon=52.9),
            site("NZ-0005", ["d10", "d11"], [cov(t1), cov(t3)], lat=74.0, lon=55.0, ignored="known site"),
        ]
        pub = os.path.join(work, "pub")
        write_state(pub, sites, dets, ["2026-06-17T17:44:38Z", t1, t2, t3])
        priv = os.path.join(work, "priv")
        write_state(priv, sites[:1], dets[:2], [t1, t2])
        cfgs = [
            {"state_dir": pub, "aoi": {"name": "Area one", "public_name": "Public area", "bbox": [51, 70.8, 57.5, 74.2]}},
            {"state_dir": priv, "aoi": {"name": "Private box", "bbox": [1, 2, 3, 4]}, "public": False},
            {"state_dir": os.path.join(work, "missing"), "aoi": {"name": "No state yet", "bbox": [0, 0, 1, 1]}},
        ]
        doc = public.build(cfgs, now=datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc))

        ids = [s["id"] for s in doc["sites"]]
        assert ids == ["NZ-0001"], ids                      # B, C, D, E fail the gate; the private area is skipped
        s = doc["sites"][0]
        assert s["passes_seen"] == 2 and s["geometries"] == ["112A", "54A"], s
        assert s["first_seen"] == t1 and s["last_seen"] == t2, s
        assert s["coverage"] == [[t1, 1], [t2, 1], [t3, 0]], s["coverage"]
        assert s["coverage_unheard"] == [t4], s["coverage_unheard"]
        assert s["coverage_from"] == t1, s["coverage_from"]
        assert len(s["detections"]) == 2 and s["detections"][0]["granule"] == "G1", s["detections"]
        assert s["spread_km"] == 0.0, s["spread_km"]
        # the label follows the site's mean position, not the stored first-detection text
        assert s["where"] != "near a place" and s["country"] == "RU", (s["where"], s["country"])
        text = json.dumps(doc)
        for private in ("interpretation", "rfi_likelihood", "cmr.example", "clean_streak", "baseline", "status",
                        "Private box", "Consistent with a GNSS jammer"):
            assert private not in text, f"private field leaked: {private}"
        assert [a["name"] for a in doc["areas"]] == ["Public area"], doc["areas"]
        assert doc["areas"][0]["since"] == "2026-06-17" and doc["areas"][0]["passes"] == 4, doc["areas"]
        assert doc["licence"] == public.LICENCE and doc["day"] == "2026-10-28"

        # aircraft cross-check from a local day file (no network): one judged cell at jamming scale near NZ-0001 on t1
        import h3
        adir = os.path.join(work, "adsb")
        os.makedirs(adir)
        near, far = h3.latlng_to_cell(73.05, 53.65, 4), h3.latlng_to_cell(60.0, 20.0, 4)
        json.dump({"cols": ["h3", "aircraft", "bad_live", "bad_raw", "capable", "capable_bad10"],
                   "cells": [[near, 10, 3, 3, 10, 3], [far, 50, 40, 40, 50, 40]]},
                  open(os.path.join(adir, t1[:10] + ".map.json"), "w"))
        json.dump({"cols": ["h3", "aircraft", "bad_live", "bad_raw", "capable", "capable_bad10"],
                   "cells": [[near, 4, 4, 4, 4, 4]]},                 # under 5 aircraft: not judged
                  open(os.path.join(adir, t2[:10] + ".map.json"), "w"))
        doc2 = public.build(cfgs[:1], now=datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc),
                            adsb=public.Adsb(adir, fetch=False))
        covs = doc2["sites"][0]["coverage"]
        assert covs == [[t1, 1, [1, 1]], [t2, 1, None], [t3, 0, None]], covs    # (3-1)/10 = 20% -> jamming scale
        assert "ODbL" in doc2["licence_adsb"] and "licence_adsb" not in doc

        path = public.write(doc, os.path.join(work, "out"))
        assert os.path.basename(path) == "2026-10-28.nisar.json"
        assert json.load(open(path, encoding="utf-8"))["sites"][0]["id"] == "NZ-0001"
        print("public export: gate, private fields, skipped areas OK")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
