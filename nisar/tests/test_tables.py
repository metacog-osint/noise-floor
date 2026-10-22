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
from nisar_rfi import bbdetect, geoloc, pipeline, qa, tabdetect, tables  # noqa: E402

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


def synthetic_power(orb, t0, r0, source=True, forest=True, seed=1):
    """signalMean maps for band A HH/HV: echo with texture, HV 8 dB under HH, a thermal noise floor;
    optionally a slant-polarized broadband source at (t0, r0) and a 'forest' patch with HV/HH of -3 dB
    but no extra power."""
    rng = np.random.default_rng(seed)
    t = np.arange(t0 - 20, t0 + 20, 0.25)
    r = np.linspace(890e3, 1050e3, 50)
    tt, rr = np.meshgrid(t, r, indexing="ij")
    echo = 10 ** ((60 + 4 * np.sin((rr - 890e3) / 40e3) + rng.normal(0, 1.5, tt.shape)) / 10)
    noise = 10 ** (48 / 10)
    hh = echo + noise
    hv = echo * 10 ** (-8 / 10) + noise
    if forest:
        patch = (np.abs(tt - (t0 - 12)) < 2) & (np.abs(rr - 930e3) < 12e3)
        hv = np.where(patch, echo * 10 ** (-3 / 10) + noise, hv)      # strong volume scattering, normal power
    if source:
        g = np.exp(-((tt - t0) / 1.2) ** 2 - ((rr - r0) / 18e3) ** 2)
        src = g * 10 ** (68 / 10)
        hh, hv = hh + 0.5 * src, hv + src                                # slant/vertical: more in V
    f = np.linspace(1217.0, 1240.98, 64) * 1e6
    out = {}
    for pol, m in (("HH", hh), ("HV", hv)):
        out[("A", pol)] = {"t": t, "r": r, "isr": np.full(m.shape, 0.5, np.float32), "mean": m.astype(np.float32),
                           "f": f, "hits": np.zeros(m.shape + (len(f),), np.float16)}
    return out


def test_broadband_finds_source_not_forest():
    orb = synthetic_orbit()
    o = geoloc.Orbit(orb["t"], orb["pos"], orb["vel"])
    t0, r0 = 6900.0, 990e3
    truth = [float(v) for v in geoloc.rdr2geo(o, t0, r0, look="Left")]
    res = bbdetect.detect(synthetic_power(orb, t0, r0), orb, "Left")
    alerting = [c for c in res["A"] if c["confidence"] != "LOW"]
    assert len(alerting) == 1, [(c["lat"], c["lon"], c["confidence"]) for c in res["A"]]
    c = alerting[0]
    assert geoloc_km(c["lat"], c["lon"], *truth) < 4.0, geoloc_km(c["lat"], c["lon"], *truth)
    assert c["peak_ratio_excess_db"] > 6 and c["peak_excess_power_db"] > 8 and c["confidence"] == "HIGH"
    quiet = bbdetect.detect(synthetic_power(orb, t0, r0, source=False), orb, "Left")
    assert not [c for c in quiet["A"] if c["confidence"] != "LOW"], quiet["A"]


def test_combine_methods():
    tone = {"A": [{"band": "A", "lat": 10.00, "lon": 10.00, "confidence": "MEDIUM", "method": "tables"}]}
    broad = {"A": [{"band": "A", "lat": 10.05, "lon": 10.05, "blocks": 30, "peak_ratio_excess_db": 12.0,
                    "peak_excess_power_db": 15.0, "peak_bb_z": 20.0, "confidence": "HIGH", "method": "broadband"},
                   {"band": "A", "lat": 11.5, "lon": 12.0, "blocks": 9, "peak_ratio_excess_db": 7.0,
                    "peak_excess_power_db": 9.0, "peak_bb_z": 9.0, "confidence": "HIGH", "method": "broadband"},
                   {"band": "A", "lat": 13.0, "lon": 15.0, "blocks": 3, "peak_ratio_excess_db": 3.0,
                    "peak_excess_power_db": 2.0, "peak_bb_z": 6.5, "confidence": "LOW", "method": "broadband"}]}
    out = pipeline.combine_methods(tone, broad)
    a = out["A"]
    assert len(a) == 2                                   # merged tone + separate broadband; LOW dropped
    merged = next(c for c in a if c.get("method") == "tables")
    assert merged["confidence"] == "HIGH" and merged["broadband"]["peak_ratio_excess_db"] == 12.0
    assert next(c for c in a if c.get("method") == "broadband")["lat"] == 11.5
    g = {"granule": "G", "start": "2026-10-01T00:00:00Z", "track": 1, "frame": 1, "direction": "A",
         "stack": "001_A_001", "mode": "20+5"}
    bbdet = pipeline.merge_table_bands({"A": [dict(c, outline=[[0, 0]], along_km=1, across_km=1, widespread=False,
                                                   freq_runs_mhz=[], gnss_overlap=[], pols=["HH", "HV"])
                                              for c in a if c["method"] == "broadband"]}, g, {})
    d = bbdet[0]
    assert "broadband" in d["band_text"] and "GPS L2" in d["gnss_overlap"] and d["freq_low_mhz"] < 1227.6 < d["freq_high_mhz"]
    assert "noise jammer" in d["interpretation"]


def test_token_days_left():
    import base64
    import json as _json
    import time
    body = base64.urlsafe_b64encode(_json.dumps({"exp": time.time() + 10 * 86400}).encode()).decode().rstrip("=")
    fake = f"eyJhbGciOiJub25lIn0.{body}.sig"
    d = pipeline.token_days_left(fake)
    assert 9.9 < d < 10.1, d
    assert pipeline.token_days_left("not-a-jwt") is None and pipeline.token_days_left("a.b.c") is None


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
            print("ok", k)
