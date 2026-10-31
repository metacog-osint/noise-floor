"""Offline tests for tools/sentinel_gnss.py (Sentinel navigation receivers, step E1). No network, no data/ files."""
import datetime as dt
import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import sentinel_gnss as M  # noqa: E402

DAY = dt.date(2026, 10, 24)


def test_sigv4_matches_aws_example():
    # AWS S3 documentation, "Signature Calculations for the Authorization Header", example GET Object with a Range header
    hdrs, cpath, cq = M.sigv4("GET", "examplebucket.s3.amazonaws.com", "/test.txt", {}, "AKIAIOSFODNN7EXAMPLE",
                              "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "us-east-1", amz_date="20130524T000000Z",
                              extra={"Range": "bytes=0-9"})
    assert cpath == "/test.txt" and cq == ""
    auth = hdrs["Authorization"]
    assert "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date" in auth, auth
    assert auth.endswith("Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"), auth
    assert hdrs["x-amz-date"] == "20130524T000000Z" and "host" not in hdrs


def test_sigv4_encodes_path_and_query():
    _, cpath, cq = M.sigv4("GET", "h", "/eodata/a b/c.TGZ", {"prefix": "x/y z", "list-type": 2}, "A", "S", "default")
    assert cpath == "/eodata/a%20b/c.TGZ"
    assert cq == "list-type=2&prefix=x%2Fy%20z"


def hl(content, label):
    return content.ljust(60) + label


GPS_TYPES = "C1C L1C S1C C1W L1W S1W C2W L2W S2W C2L L2L S2L".split()
GAL_TYPES = "C1C L1C S1C C5Q L5Q S5Q".split()


def obs_line(sat, values, types):
    out = sat
    for ty in types:
        v = values.get(ty)
        out += (f"{v:14.3f}  " if v is not None else " " * 16)
    return out.rstrip()


def epoch(y, mo, d, hh, mm, ss, flag, ns):
    return f"> {y:4d} {mo:2d} {d:2d} {hh:2d} {mm:2d}{ss:11.7f}  {flag:1d}{ns:3d}       0.001545689119"


def rinex_text():
    lines = [hl("     3.03           O                   M", "RINEX VERSION / TYPE"),
             hl("SEN-2C", "MARKER NAME"),
             hl("L801                PODRIX", "REC # / TYPE / VERS"),
             hl(f"E    6 {' '.join(GAL_TYPES)}", "SYS / # / OBS TYPES"),
             hl(f"G   12 {' '.join(GPS_TYPES)}", "SYS / # / OBS TYPES"),
             hl("  2026    10    24     0     0    0.0000000     GPS", "TIME OF FIRST OBS"),
             hl("", "END OF HEADER")]
    lines += [epoch(2026, 10, 24, 0, 0, 0.0, 0, 2),
              obs_line("E02", {"C1C": 23220452.558, "S1C": 52.932, "S5Q": 53.131}, GAL_TYPES),
              obs_line("G01", {"C1C": 24103403.229, "S1C": 43.408, "S1W": 30.1, "S2W": 29.5, "S2L": 46.779}, GPS_TYPES)]
    # an event record (flag 4) with two comment lines: skipped
    lines += [epoch(2026, 10, 24, 0, 0, 5.0, 4, 2), hl("A COMMENT", "COMMENT"), hl("ANOTHER", "COMMENT")]
    lines += [epoch(2026, 10, 24, 0, 0, 10.0, 0, 2),
              obs_line("G01", {"C1C": 24103000.0, "S1C": 42.0}, GPS_TYPES),
              obs_line("G05", {"C1C": 21000000.0}, GPS_TYPES)]           # no signal strength: no row
    lines += [epoch(2026, 10, 25, 0, 0, 0.0, 0, 1),
              obs_line("E07", {"S1C": 40.742}, GAL_TYPES)]
    return lines


def test_parse_rinex():
    hdr, t, sat, vals = M.parse_rinex(rinex_text(), DAY)
    assert hdr["receiver"] == "PODRIX" and hdr["marker"] == "SEN-2C" and hdr["time_system"] == "GPS"
    assert hdr["types"]["G"] == GPS_TYPES and hdr["types"]["E"] == GAL_TYPES
    assert list(t) == [0.0, 0.0, 10.0, 86400.0], t
    assert list(sat) == ["E02", "G01", "G01", "E07"], sat
    assert math.isclose(vals["s1c"][0], 52.932, abs_tol=1e-3) and math.isclose(vals["s5q"][0], 53.131, abs_tol=1e-3)
    assert np.isnan(vals["s1w"][0]) and np.isnan(vals["s2l"][0])
    assert math.isclose(vals["s2l"][1], 46.779, abs_tol=1e-3) and math.isclose(vals["s1w"][1], 30.1, abs_tol=1e-3)
    assert math.isclose(vals["s1c"][2], 42.0) and np.isnan(vals["s2w"][2])
    assert all(v.dtype == np.float32 for v in vals.values())


def test_parse_rejects_other_time_systems():
    lines = rinex_text()
    lines[5] = hl("  2026    10    24     0     0    0.0000000     UTC", "TIME OF FIRST OBS")
    try:
        M.parse_rinex(lines, DAY)
    except ValueError as ex:
        assert "UTC" in str(ex)
    else:
        raise AssertionError("UTC time system accepted")


def name(unit, created, start, stop):
    return f"{unit}_OPER_AUX_GNSSRD_POD__{created}_V{start}_{stop}"


def test_choose_products():
    rows = [
        {"Name": name("S2C", "20261030T120621", "20261023T235942", "20261024T235932")},   # the day
        {"Name": name("S2C", "20261031T090000", "20261023T235942", "20261024T235932")},   # reprocessed: newer wins
        {"Name": name("S2C", "20261031T120000", "20261024T235942", "20261025T235932")},   # next day: 18 s overlap
        {"Name": name("S1A", "20260706T113036", "20260629T235946", "20260630T192456")},   # unit not asked for
        {"Name": name("S3A", "20261030T121059", "20261024T230000", "20261024T233000")},   # 30 min: too short
        {"Name": "S2C_OPER_AUX_PROQUA_xxx"},
    ]
    got = M.choose(rows, DAY, ["S2C", "S3A"])
    assert list(got) == ["S2C"], got
    assert got["S2C"]["Name"].startswith("S2C_OPER_AUX_GNSSRD_POD__20261031T090000")
    assert got["S2C"]["_cover_s"] > 86000
    partial = M.choose([{"Name": name("S1A", "20260706T113036", "20260629T235946", "20260630T192456")}],
                       dt.date(2026, 6, 30), ["S1A"])
    assert 19 * 3600 < partial["S1A"]["_cover_s"] < 20 * 3600


def test_day_filter_and_days_arg():
    f = M.day_filter(DAY, ["S1C", "S2C", "S2B"])
    assert "Collection/Name eq 'SENTINEL-1' or Collection/Name eq 'SENTINEL-2'" in f
    assert "gt 2026-10-23T00:00:00.000Z" in f and "lt 2026-10-25T00:00:00.000Z" in f
    assert M.days_arg(["2026-10-22..2026-10-24", "2026-10-30"]) == [
        dt.date(2026, 10, 22), dt.date(2026, 10, 23), dt.date(2026, 10, 24), dt.date(2026, 10, 30)]


def test_spans_needed():
    today = dt.date(2026, 10, 31)
    cap = dt.date(2026, 10, 29)
    assert M.spans_needed(None, DAY, today) == [(M.HISTORY_START, cap)]
    early = dt.date(2025, 1, 10)
    assert M.spans_needed(None, early, today) == [(dt.date(2025, 1, 8), cap)]
    held = {"from": "2025-03-01", "to": "2026-10-29"}
    assert M.spans_needed(held, DAY, today) == []                          # covered
    assert M.spans_needed(held, dt.date(2026, 10, 28), today) == []        # nothing newer to hold yet
    assert M.spans_needed(held, dt.date(2026, 10, 28), dt.date(2026, 11, 3)) == [(dt.date(2026, 10, 29),
                                                                                  dt.date(2026, 11, 1))]
    assert M.spans_needed(held, early, today) == [(dt.date(2025, 1, 8), dt.date(2025, 3, 1))]


def test_gmst_matches_sgp4():
    from sgp4.propagation import gstime
    for jd in (2451545.0, 2461337.25, 2461338.6789):
        assert abs(float(M.gmst(jd)) - gstime(jd)) < 1e-9


def test_geodetic():
    lat, lon, alt = M.geodetic(np.array([[6378137.0, 0.0, 0.0], [0.0, 0.0, 6356752.314245 + 1000.0]]))
    assert abs(lat[0]) < 1e-9 and abs(lon[0]) < 1e-9 and abs(alt[0]) < 1e-6
    assert abs(lat[1] - 90.0) < 1e-6 and abs(alt[1] - 1.0) < 1e-6


def test_frames_and_look():
    # circular equatorial orbit, eastward: at t=0 the spacecraft is on +x moving +y, so up=+x, forward=+y, right=-z
    r, w = 7.0e6, 2 * math.pi / 6000.0
    t = np.arange(-30, 31) * 10.0
    pos = np.stack([r * np.cos(w * t), r * np.sin(w * t), np.zeros_like(t)], axis=1)
    up, fwd, right = M.frames(pos)
    i = 30
    assert np.allclose(up[i], [1, 0, 0]) and np.allclose(fwd[i], [0, 1, 0], atol=1e-9)
    assert np.allclose(right[i], [0, 0, -1], atol=1e-9)
    vel = np.stack([-r * w * np.sin(w * t), r * w * np.cos(w * t), np.zeros_like(t)], axis=1)
    up2, fwd2, right2 = M.frames(pos[[0, i, -1]], vel[[0, i, -1]])          # velocities: no neighbours needed
    assert np.allclose(fwd2[1], [0, 1, 0], atol=1e-12) and np.allclose(right2[1], [0, 0, -1], atol=1e-12)
    p = np.repeat(pos[i:i + 1], 4, axis=0)
    targets = np.array([[r + 2e7, 0, 0],            # straight up
                        [r, 2e7, 0],                # ahead, on the horizon
                        [r, 0, -2e7],               # to the right (south), on the horizon
                        [r - 3e6, 0, 0]])           # below
    el, az = M.look(p, up[[i] * 4], fwd[[i] * 4], right[[i] * 4], targets)
    assert abs(el[0] - 90) < 1e-6
    assert abs(el[1]) < 1e-6 and (az[1] < 1e-6 or az[1] > 360 - 1e-6)
    assert abs(el[2]) < 1e-6 and abs(az[2] - 90) < 1e-6
    assert abs(el[3] + 90) < 1e-6


def test_spacecraft_ecef_from_elements():
    # a Sentinel-2-like sun-synchronous orbit: 14.308 rev/day, 98.57 deg
    s = {"epoch": "2026-10-24T06:00:00.000000", "n": 14.308, "e": 0.0001, "i": 98.57, "raan": 0.0, "argp": 90.0,
         "M": 0.0, "bstar": 1e-5}
    t0 = dt.datetime(2026, 10, 24, tzinfo=dt.timezone.utc).timestamp()
    t = t0 + np.array([0.0, 6 * 3600.0, 6 * 3600.0 + 10.0, 80 * 3600.0])
    xyz, vel, age = M.spacecraft_ecef([s], t)
    assert np.allclose(age, [6, 0, 10 / 3600.0, 74])
    lat, lon, alt = M.geodetic(xyz)
    assert np.all((alt[:3] > 770) & (alt[:3] < 830)), alt               # ~789 km at the equator, more near the poles
    assert np.all(np.isnan(xyz[3])) and np.all(np.isnan(vel[3]))       # 74 h from the only set: no position
    step = (xyz[2] - xyz[1]) / 10.0
    assert 6800 < np.linalg.norm(step) < 7600, step                      # Earth-fixed speed, m/s
    assert np.allclose(step, (vel[1] + vel[2]) / 2.0, atol=1.0), (step, vel[1:3])   # velocity is Earth-fixed too
    near = M.spacecraft_ecef([s, {**s, "epoch": "2026-10-24T12:00:00.000000"}], t[:1] + 11 * 3600.0)[2]
    assert abs(near[0] - 1.0) < 1e-9                                     # the nearer set is used


def test_grid_offset():
    assert M.grid_offset(np.arange(0, 86400, 10.0)) == 0.0
    assert M.grid_offset(np.arange(4, 86400, 10.0)) == 4.0             # Sentinel-2B's grid
    assert M.grid_offset(np.arange(0, 86400, 1.0)) == 0.0              # Sentinel-3's 1 s files
    assert M.grid_offset(np.r_[np.arange(4, 8000, 10.0), [0.0, 30.0]]) == 4.0


def test_gnss_positions():
    eph = {"G01": [{"crs": 0.0, "dn": 0.0, "m0": 0.0, "cuc": 0.0, "e": 0.01, "cus": 0.0, "sqrta": 5153.7, "toe": 518400.0,
                    "cic": 0.0, "om0": 0.0, "cis": 0.0, "i0": 0.96, "crc": 0.0, "w": 0.0, "omd": 0.0, "idot": 0.0,
                    "week": 2390.0, "health": 0.0}],
           "G02": [{"crs": 0.0, "dn": 0.0, "m0": 0.0, "cuc": 0.0, "e": 0.01, "cus": 0.0, "sqrta": 5153.7, "toe": 518400.0,
                    "cic": 0.0, "om0": 0.0, "cis": 0.0, "i0": 0.96, "crc": 0.0, "w": 0.0, "omd": 0.0, "idot": 0.0,
                    "week": 2390.0, "health": 1.0}]}                      # unhealthy: no position
    toe = 2390 * 604800.0 + 518400.0
    out = M.gnss_positions(eph, ["G01", "G01", "G02", "G09"], np.array([toe, toe + 3 * 3600.0, toe, toe]))
    r = np.linalg.norm(out[0])
    assert 2.62e7 < r < 2.68e7, r
    assert np.all(np.isnan(out[1])) and np.all(np.isnan(out[2])) and np.all(np.isnan(out[3]))


if __name__ == "__main__":
    for name_, fn in list(globals().items()):
        if name_.startswith("test_") and callable(fn):
            fn()
            print("ok", name_)
