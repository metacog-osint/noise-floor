"""Offline test for tools/radar_spokes.py: synthetic sweeps, sun position, bearing intersections.

Runs as a plain script (CI: `python tests/test_radar_spokes.py`). Needs numpy; skips cleanly without it."""
import math
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))


def synthetic_sweep(rng, np, spokes=(), rain=None, nrays=360, nbins=720, rscale=0.25, noise_zc=-48.0):
    """TH-like sweep: speckle noise (30% of gates just above the noise threshold), optional interference
    spokes (constant received power -> Z = level + 20 log10 r) and an optional rain area."""
    r = (np.arange(nbins) + 0.5) * rscale
    lr = 20 * np.log10(r)
    z = np.full((nrays, nbins), np.nan, "f4")
    speck = rng.random((nrays, nbins)) < 0.3
    z[speck] = (noise_zc + rng.exponential(1.5, speck.sum()) + np.broadcast_to(lr, z.shape)[speck])
    for az, level in spokes:
        a = int(az)
        hit = rng.random(nbins) < 0.9
        z[a, hit] = level + lr[hit] + rng.normal(0, 1.0, hit.sum())
    if rain:
        a0, a1, r0, r1, dbz = rain
        g0, g1 = int(r0 / rscale), int(r1 / rscale)
        z[a0:a1, g0:g1] = dbz + rng.normal(0, 4, (a1 - a0, g1 - g0))
    # near-range clutter
    z[:, : int(30 / rscale)] = rng.normal(25, 10, (nrays, int(30 / rscale)))
    t0 = datetime(2026, 10, 23, 2, 0, 0, tzinfo=timezone.utc)
    return dict(radar="test:aaa", provider="test", lat=54.0, lon=10.0, height=100.0, elangle=0.5,
                start=t0, end=t0.replace(second=30), az=(np.arange(nrays) + 0.5) * 360.0 / nrays, r_km=r, z=z,
                beamwidth=1.0, fmi_emitter=None, radconst=70.0, nez=float("nan"))


def main():
    try:
        import numpy as np
    except ImportError:
        print("test_radar_spokes: numpy not installed, skipped")
        return 0
    import radar_spokes as R

    rng = np.random.default_rng(42)

    # 1. clear air: two spokes (weak and moderate), found at the right azimuths, nothing else
    sw = synthetic_sweep(rng, np, spokes=[(100, -44.0), (250, -35.0)])
    row, sp = R.detect_sweep(sw)
    azs = sorted(s["az"] for s in sp)
    assert len(sp) == 2, sp
    assert abs(azs[0] - 100.5) <= 1.0 and abs(azs[1] - 250.5) <= 1.0, azs
    lev = {round(s["az"]): s["level_zc"] for s in sp}
    assert abs(lev[100] + 44.0) < 1.0 and abs(lev[250] + 35.0) < 1.0, lev
    assert all(not s["sun"] and not s["precip"] for s in sp)
    assert all(15 <= s["slope"] <= 25 for s in sp), [s["slope"] for s in sp]   # the 20 log r signature
    assert row["n_spokes"] == 2 and abs(row["nf_zc"] - (-48)) < 2, row

    # 2. a rain area (30 dBZ, 40 rays wide) alone gives no detection
    sw = synthetic_sweep(rng, np, rain=(150, 190, 40, 160, 30.0))
    row, sp = R.detect_sweep(sw)
    assert len(sp) == 0, sp

    # 3. a strong spoke crossing rain at 40-100 km is still found from its clear 100-180 km part, and is not
    #    flagged "precip" (the wet share is counted only where the ray holds its level)
    sw = synthetic_sweep(rng, np, spokes=[(170, -20.0)], rain=(150, 190, 40, 100, 30.0))
    row, sp = R.detect_sweep(sw)
    hits = [s for s in sp if abs(s["az"] - 170.5) <= 1.0]
    assert len(sp) == 1 and hits and not hits[0]["precip"], sp

    # 4. circular grouping across north
    m = np.zeros(360, bool)
    m[[358, 359, 0, 1, 50]] = True
    groups = sorted(sorted(int(i) for i in g) for g in R._groups(m))
    assert groups == [[0, 1, 358, 359], [50]], groups

    # 5. sun position: elevation at local solar noon ~ 90 - lat + declination (23 Oct: dec about -11.4 deg)
    # (solar noon at 10 E is about 11:04 UTC on 23 Oct: 12:00 - 40 min for longitude - ~16 min equation of time)
    best = max((R.sun_azel(54.0, 10.0, datetime(2026, 10, 23, 10 + m_ // 60, m_ % 60, tzinfo=timezone.utc))
                for m_ in range(30, 100)), key=lambda x: x[1])
    assert abs(best[0] - 180) < 1.0 and abs(best[1] - (90 - 54 - 11.4)) < 0.5, best
    # refraction lifts the apparent sun by about 0.5 deg at the horizon
    az, el = R.sun_azel(54.0, 10.0, datetime(2026, 10, 23, 5, 58, tzinfo=timezone.utc))
    assert 95 < az < 120 and -1.5 < el < 0.0, (az, el)

    # 6. bearing intersection recovers a known point
    lat_e, lon_e = 52.5, 9.0
    _, b1 = R.gc_dist_brg(53.6, 6.75, lat_e, lon_e)
    _, b2 = R.gc_dist_brg(52.46, 9.69, lat_e, lon_e)
    x = R.bearing_intersection(53.6, 6.75, b1, 52.46, 9.69, b2)
    assert x is not None
    d, _ = R.gc_dist_brg(x[0], x[1], lat_e, lon_e)
    assert d < 0.1 and x[4] > 15, x
    # bearings pointing apart only meet on the far side of the Earth (dropped later by fix_max_km)
    x = R.bearing_intersection(53.0, 7.0, 270.0, 53.0, 9.0, 90.0)
    assert x is None or min(x[2], x[3]) > 5000, x

    # 7. source clustering: 40 detections near 100.3 deg in 50 sweeps -> one persistent source
    spokes = [dict(az=str(100.3 + rng.normal(0, 0.3)), t=f"2026-10-23T{h:02d}:{m_:02d}:00Z", z100="0", pr_dbm="-110",
                   excess_db="4", width="1", slope="20", wet="0") for h in range(10) for m_ in (0, 15, 30, 45)]
    src = R.find_sources(spokes, 50)
    assert len(src) == 1 and abs(src[0]["az"] - 100.3) < 0.3 and src[0]["persist_class"] == "persistent", src

    print("test_radar_spokes: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
