"""Offline checks for the table method: geolocation, tier-0 QA parsing, tier-1 detection, screening.
Run: python tests/test_tables.py (from nisar/)."""
import io
import math
import os
import sys
import tempfile

import h5py
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from nisar_rfi import geoloc, pipeline, qa, tabdetect, tables  # noqa: E402

WE = 7.2921150e-5          # Earth rotation, rad/s
MU = 3.986004418e14


def synthetic_orbit(t0=6700.0, n=400, alt=747e3, inc_deg=98.4, raan_deg=40.0, u0_deg=20.0):
    """Circular sun-synchronous-like orbit, state vectors every second, ECEF."""
    a = geoloc.A + alt
    nn = math.sqrt(MU / a ** 3)
    i, om = math.radians(inc_deg), math.radians(raan_deg)
    p = np.array([math.cos(om), math.sin(om), 0.0])
    q = np.array([-math.sin(om) * math.cos(i), math.cos(om) * math.cos(i), math.sin(i)])
    t = t0 + np.arange(n, dtype=float)

    def ecef(tt):
        u = math.radians(u0_deg) + nn * (tt - t0)
        r = a * (np.cos(u)[:, None] * p + np.sin(u)[:, None] * q)
        th = WE * tt
        c, s = np.cos(th), np.sin(th)
        return np.column_stack([c * r[:, 0] + s * r[:, 1], -s * r[:, 0] + c * r[:, 1], r[:, 2]])

    pos = ecef(t)
    vel = (ecef(t + 0.01) - ecef(t - 0.01)) / 0.02
    return {"t": t, "pos": pos, "vel": vel, "units": "seconds since 2026-10-11T00:00:00"}


def test_geoloc_roundtrip():
    orb = synthetic_orbit()
    o = geoloc.Orbit(orb["t"], orb["pos"], orb["vel"])
    t0, r0 = 6900.0, 960e3
    lat, lon = geoloc.rdr2geo(o, t0, r0, look="Left")
    t1, r1 = geoloc.geo2rdr(o, float(lat), float(lon))
    assert abs(t1 - t0) < 1e-3 and abs(r1 - r0) < 1.0, (t1, r1)
    # left of track: for an ascending pass at mid-latitude the left side is west
    s, v = o.state(t0)
    slat, slon, _ = geoloc.ecef_to_llh(*s)
    assert lon < slon
    # height shifts the point across track by roughly h / tan(incidence)
    lat2, lon2 = geoloc.rdr2geo(o, t0, r0, h=1500.0, look="Left")
    shift = geoloc_km(float(lat), float(lon), float(lat2), float(lon2))
    assert 0.5 < shift < 5.0, shift


def geoloc_km(la1, lo1, la2, lo2):
    from nisar_rfi.geometry import km_between
    return km_between(la1, lo1, la2, lo2)


def synthetic_tables(orb, t0, r0):
    """Band A with an L2 emitter at (t0, r0), the 1233.125 MHz instrument tone everywhere, and a strip
    of degenerate blocks; band B with only its instrument tone."""
    t = np.arange(t0 - 20, t0 + 20, 0.25)
    r = np.linspace(890e3, 1050e3, 50)
    out = {}
    for band, (lo, hi), tone in (("A", (1217.0, 1240.98), 1233.125), ("B", (1290.5, 1296.49), 1296.002)):
        f = np.linspace(lo, hi, 1024) * 1e6
        for pol in ("HH", "HV"):
            hits = np.zeros((len(t), len(r), len(f)), np.float16)
            hits[:, :, np.abs(f / 1e6 - tone) < 0.03] = 0.9                       # instrument tone, everywhere
            hits[:, :, np.abs(f / 1e6 - tone - 0.1) < 0.02] = 0.55                # its sidelobe
            isr = np.full((len(t), len(r)), 0.5, np.float32)
            mean = np.full((len(t), len(r)), 1e4, np.float32)
            mean[:, :3] = 1e-3                                                     # degenerate strip ...
            isr[:, :3] = 1e12                                                      # ... with absurd ISR
            hits[:, :3, 100] = 1.0                                                 # and junk hits
            if band == "A":
                tt, rr = np.meshgrid(t, r, indexing="ij")
                g = np.exp(-((tt - t0) / 1.0) ** 2 - ((rr - r0) / 15e3) ** 2)
                blob = g > 0.2
                l2 = np.abs(f / 1e6 - 1227.6) < 0.15
                for k in np.nonzero(l2)[0]:
                    hits[:, :, k] = np.where(blob, 0.95, hits[:, :, k])
                isr = np.where(blob, 300.0 * g, isr).astype(np.float32)
            out[(band, pol)] = {"t": t, "r": r, "isr": isr, "mean": mean, "f": f, "hits": hits}
    return out


def test_tabdetect_finds_emitter_not_tones():
    orb = synthetic_orbit()
    o = geoloc.Orbit(orb["t"], orb["pos"], orb["vel"])
    t0, r0 = 6900.0, 975e3
    truth = geoloc.rdr2geo(o, t0, r0, look="Left")
    tab = synthetic_tables(orb, t0, r0)
    res = tabdetect.detect(tab, orb, "Left")
    assert len(res["A"]) == 1, res["A"]
    assert res.get("B", []) == [], res["B"]
    c = res["A"][0]
    err = geoloc_km(c["lat"], c["lon"], float(truth[0]), float(truth[1]))
    assert err < 3.0, err
    assert "GPS L2" in c["gnss_overlap"] and c["pols"] == ["HH", "HV"] and c["confidence"] == "HIGH"
    assert any(lo <= 1227.6 <= hi for lo, hi, _ in c["freq_runs_mhz"])
    assert not c["widespread"]
    d = dict(c, freq_runs_mhz=c["freq_runs_mhz"], gnss_overlap=c["gnss_overlap"])
    assert "L2 centre" in tabdetect.interpretation(d)


def test_tables_cache_roundtrip():
    orb = synthetic_orbit()
    tab = synthetic_tables(orb, 6900.0, 975e3)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "x.npz")
        tables.save_npz(p, tab, orb, {"look": "Left", "track": 157})
        tab2, orb2, meta = tables.load_npz(p)
    assert meta["look"] == "Left" and sorted(tab2) == sorted(tab)
    assert np.allclose(tab2[("A", "HV")]["isr"], tab[("A", "HV")]["isr"])
    assert orb2["units"].startswith("seconds since")


def test_rslc_name_and_score_kind():
    g = "NISAR_L2_PR_GCOV_032_157_A_015_2005_DHDH_A_20261011T015156_20261011T015229_P05023_N_F_J_001"
    assert tables.rslc_name(g) == g.replace("_L2_PR_GCOV_", "_L1_PR_RSLC_")
    assert qa.score_kind(g) == "max_isr"
    assert qa.score_kind("NISAR_L2_PR_GCOV_009_157_A_015_2005_DHDH_A_20260108T015200_20260108T015233_X05009_N_F_J_001") == "fraction"


def test_qa_read():
    buf = io.BytesIO()
    with h5py.File(buf, "w") as h:
        for f, vals in (("A", (1.77, 0.85)), ("B", (36.9, 27.8))):
            for pol, v in zip(("HH", "HV"), vals):
                h[f"/science/LSAR/RFI/data/frequency{f}/{pol}/rfiLikelihood"] = v
    q = qa.read_qa_bytes(buf.getvalue())
    assert q == {"AHH": 1.77, "AHV": 0.85, "BHH": 36.9, "BHV": 27.8}
    assert qa.band_score(q, "B") == 36.9 and qa.band_score(q, "C") is None


def test_screen_decision():
    cfg = {"screen": {"min_score": 10.0, "every": 3}}
    state = {}
    g = {"track": 109, "direction": "D", "frame": 60, "qa": {"AHH": 2.0, "BHV": 4.0}}
    assert pipeline.screen_decision(g, state, cfg) == (True, "rotation")        # first look at a frame
    state["stacks"]["109_D_060"]["since_tables"] = 0
    read, why = pipeline.screen_decision(g, state, cfg)
    assert not read and "below" in why
    state["stacks"]["109_D_060"]["since_tables"] = 2
    assert pipeline.screen_decision(g, state, cfg)[1] == "rotation"
    g["qa"]["AHV"] = 444.0
    assert pipeline.screen_decision(g, state, cfg)[0]
    assert pipeline.screen_decision(dict(g, qa=None), state, cfg) == (True, "no QA score")


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
            print("ok", k)
