"""Offline tests for tools/cosmic2_s4.py (COSMIC-2 limb S4) and tools/cosmic2_job.py (the GitHub day job).
No network, no data/ files."""
import io
import json
import math
import os
import sys
import tarfile
from datetime import datetime, timezone

import numpy as np
from scipy.io import netcdf_file

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cosmic2_job as J  # noqa: E402
import cosmic2_rfi as C2  # noqa: E402
import cosmic2_s4 as S  # noqa: E402

R_LEO = S.A_WGS + 550.0
DAY = "2026-11-13"
T0_GPS = S.day_start(DAY) - S.GPS_UNIX + S.LEAP          # GPS seconds at 00:00 UTC on DAY


def ecef(lat, lon, h):
    """Geodetic -> Earth-fixed km (WGS84), for checking geodetic()."""
    la, lo = math.radians(lat), math.radians(lon)
    n = S.A_WGS / math.sqrt(1 - S.E2 * math.sin(la) ** 2)
    return np.array([(n + h) * math.cos(la) * math.cos(lo), (n + h) * math.cos(la) * math.sin(lo),
                     (n * (1 - S.E2) + h) * math.sin(la)])


def elev_for(h):
    """Elevation (deg, negative) of a link from R_LEO on the equator whose tangent point is h km up."""
    return -math.degrees(math.acos((S.A_WGS + h) / R_LEO))


def link_geometry(elev_deg):
    """LEO on the equator at 0 deg E; the GPS satellite along the line at each elevation, in the equatorial plane."""
    e = np.radians(np.asarray(elev_deg, float))
    leo = np.tile([R_LEO, 0.0, 0.0], (len(e), 1))
    u = np.stack([np.sin(e), np.cos(e), np.zeros_like(e)], axis=1)
    return leo, leo + 26000.0 * u


def nc_link(start_gps, s4, elev, conid="G", prn=5, antenna=2, rfi=None):
    buf = io.BytesIO()
    f = netcdf_file(buf, "w")
    f.createDimension("time", len(s4))
    f.start_time = float(start_gps)
    f.antenna_id = int(antenna)
    f.prn_id = int(prn)
    f.conid = conid
    f.createVariable("time", "d", ("time",))[:] = np.arange(len(s4), dtype=float)
    f.createVariable("S4", "f", ("time",))[:] = s4
    f.createVariable("elevation", "d", ("time",))[:] = elev
    f.createVariable("RFI", "f", ("time",))[:] = np.zeros(len(s4)) if rfi is None else rfi
    leo, gps = link_geometry(elev)
    for i, ax in enumerate("xyz"):
        f.createVariable(f"{ax}_LEO", "d", ("time",))[:] = leo[:, i]
        f.createVariable(f"{ax}_GPS", "d", ("time",))[:] = gps[:, i]
    f.flush()
    data = buf.getvalue()
    f.close()
    return data


def name_for(sat=2, prn=5, antenna=2, con="G", hhmm="00.04", dur="0025"):
    return f"podTc2_C2E{sat}.2026.317.{hhmm}.{dur}.{con}{prn:02d}.{antenna:02d}_0001.0001_nc"


def test_geodetic_and_tangent_point():
    for lat, lon, h in ((0.0, 10.0, 300.0), (35.0, -60.0, 150.0), (-42.0, 120.0, 499.0), (60.0, 0.0, 0.0)):
        la, lo, hh = S.geodetic(ecef(lat, lon, h))
        assert abs(la - lat) < 1e-7 and abs(lo - lon) < 1e-7 and abs(hh - h) < 1e-5, (lat, lon, h, la, lo, hh)
    for h in (150.0, 300.0, 500.0):
        leo, gps = link_geometry([elev_for(h)])
        tp, between = S.tangent_point(leo, gps)
        la, lo, hh = S.geodetic(tp)
        assert between[0] and abs(hh[0] - h) < 1e-6 and abs(la[0]) < 1e-9, (h, hh, la)
    # a link above the horizon has its closest point behind the receiver: not between the two
    leo, gps = link_geometry([10.0])
    assert not S.tangent_point(leo, gps)[1][0]


def test_limb_samples_selects_gps_limb_seconds():
    el = np.r_[np.full(10, 5.0), np.full(10, elev_for(100.0)), np.full(10, elev_for(300.0)), np.full(10, elev_for(520.0))]
    s4 = np.r_[np.full(10, 0.2), np.full(10, 0.3), np.full(9, 0.4), -999.0, np.full(10, 0.5)]
    f = C2.open_link(nc_link(T0_GPS + 3600, s4, el))
    d, why = S.limb_samples(f, name_for())
    assert why == "ok"
    assert len(d["t"]) == 9 and np.allclose(d["s4"], 0.4)            # only the 300 km seconds with a valid S4
    assert np.all((d["h"] > 299.9) & (d["h"] < 300.1))
    assert list(d["since"]) == list(range(20, 29)) and d["key"][0] == 2 * 1000 + 2 * 100 + 5
    glo = C2.open_link(nc_link(T0_GPS, s4, el, conid="R"))
    assert S.limb_samples(glo, name_for(con="R"))[1] == "not GPS"
    up = C2.open_link(nc_link(T0_GPS, s4, np.full(40, 3.0)))
    assert S.limb_samples(up, name_for())[1] == "no limb samples"


def raw(t, s4, key=2205, since=None, rfi=None, lat=0.0, lon=0.0):
    t = np.asarray(t, np.int64)
    n = len(t)
    return {"t": t, "since": np.asarray(since if since is not None else t - t[0] + 1000, np.int64),
            "lat": np.full(n, lat), "lon": np.full(n, lon), "h": np.full(n, 300.0), "s4": np.asarray(s4, float),
            "rfi": np.zeros(n) if rfi is None else np.asarray(rfi, float), "key": np.full(n, key, np.int64)}


def cat(*parts):
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}


def test_windows_dedupe_skip_and_ten_second_values():
    base = int(T0_GPS) + 7200
    t = np.arange(base, base + 40)
    s4 = np.repeat([0.1, 0.2, 0.2, 0.3], 10)                      # two equal 10 s values in a row: still two values
    a = raw(t, s4)
    b = raw(t[:25], s4[:25])                                        # the same seconds again from a later dump
    w = S.windows(cat(a, b), skip_s=0)
    assert len(w["t"]) == 4 and list(np.round(w["s4"], 3)) == [0.1, 0.2, 0.2, 0.3]
    assert w["t"][0] == base + 4 + S.GPS_UNIX - S.LEAP              # placed at the window's middle second, in UTC
    # the first 60 s of a track are dropped; `since` is the larger of two copies of a second
    c = raw(t, s4, since=np.arange(40))
    assert len(S.windows(c)["t"]) == 0
    d = raw(t, s4, since=np.arange(40) + 45)                        # seconds 15.. of the file are 60+ s into the track
    assert len(S.windows(cat(c, d))["t"]) == 3
    # a gap longer than 10 s splits a run; two links never share a window; RFI flags the whole window
    g = raw(np.r_[t[:5], t[:5] + 30], np.full(10, 0.4))
    assert len(S.windows(g, skip_s=0)["t"]) == 2
    k = cat(raw(t[:10], np.full(10, 0.4)), raw(t[:10], np.full(10, 0.4), key=2306))
    assert len(S.windows(k, skip_s=0)["t"]) == 2
    r = raw(t[:10], np.full(10, 0.4), rfi=np.r_[np.zeros(9), 5e-4])
    assert S.windows(r, skip_s=0)["rfi"].tolist() == [True]


def values(n, s4, hour=5, lat=10.0, lon=30.0, link=1, rfi=False, spacing=10):
    t = S.day_start(DAY) + hour * 3600 + 60 + spacing * np.arange(n)
    return {"t": t, "lat": np.full(n, lat), "lon": np.full(n, lon), "h": np.full(n, 300.0),
            "s4": np.asarray(s4, float) * np.ones(n), "rfi": np.full(n, rfi), "link": np.full(n, link)}


def test_cell_hours():
    import h3
    few = values(9, 0.3, hour=2)
    many = cat(values(20, np.linspace(0.1, 2.0, 20), hour=5), values(5, 0.5, hour=5, link=2, rfi=True))
    other_day = values(3, 0.9, hour=30)
    out = S.cell_hours(cat(few, many, other_day), DAY)
    assert sorted(out) == [2, 5]
    (r2,), (r5,) = out[2], out[5]
    cell = h3.latlng_to_cell(10.0, 30.0, S.RES)
    assert r2[0] == cell and r2[3] == 9 and r2[5] is None and r2[6] == 0.3
    v = np.r_[np.linspace(0.1, 2.0, 20), np.full(5, 0.5)]
    assert r5[3] == 25 and r5[4] == 2 and r5[5] == round(float(np.percentile(v, 95)), 3) and r5[6] == 2.0
    assert r5[8] == 0.2                                             # 5 of 25 values with the RFI index raised
    la, lo = h3.cell_to_latlng(cell)
    tm = float(np.median(many["t"]))
    assert abs(r5[7] - round(((tm - S.day_start(DAY)) / 3600 + lo / 15) % 24, 1)) < 1e-9
    assert len(S.COLUMNS) == len(r5)


class FakeLimb(S.Limb):
    def __init__(self, parts, sats):
        super().__init__()
        self.parts = parts
        self.sats = sats


def test_build_day_file():
    t = np.arange(int(T0_GPS) + 3600 * 4, int(T0_GPS) + 3600 * 4 + 300)
    part = raw(t, np.repeat(np.linspace(0.1, 0.6, 30), 10), lat=-7.0, lon=-66.0)
    limb = FakeLimb([part], {"C2E2": 3, "C2E5": 1, "C2E1": 0})
    limb.reasons = {"ok": 4, "not GPS": 2}
    now = datetime(2026, 11, 14, 5, 7, 9, tzinfo=timezone.utc)
    doc = S.build(DAY, limb, {"url": "u"}, now=now)
    assert doc["feed"] == "cosmic2-limb-s4" and doc["day"] == DAY and doc["as_of"] == "2026-11-14T05:07:09Z"
    assert doc["measure"] == S.LABEL and "reads higher than a ground receiver's S4" in doc["measure"]
    assert doc["sources"] == ["cosmic2-ro"] and doc["credit"] and doc["licence"].startswith("CC BY 4.0")
    assert len(doc["hours"]) == 24 and doc["hours"][4]["hour"] == f"{DAY}T04:00Z"
    assert doc["counts"]["values"] == 30 and doc["counts"]["cell_hours"] >= 1 and doc["counts"]["hours_with_data"] == 1
    assert doc["satellites"] == ["C2E2", "C2E5"]
    assert any("C2E1" in p and "C2E3" in p for p in doc["problems"])
    assert any("23 UTC hour(s)" in p for p in doc["problems"])
    assert set(doc["column_notes"]) == set(doc["columns"])
    # the file never measures itself against ground S4 alert levels
    text = json.dumps({k: doc[k] for k in ("measure", "method", "column_notes", "credit", "licence")}).lower()
    for word in ("icao", "moderate", "severe", "threshold of 0.5", "0.8"):
        assert word not in text, word
    path = S.write(doc, out_dir=os.path.join(ROOT, "data", "test_tmp_s4"))
    assert path.endswith(f"{DAY}.cosmic2-limb-s4.json") and json.load(open(path, encoding="utf-8"))["day"] == DAY
    os.remove(path)
    os.rmdir(os.path.dirname(path))


def tar_of(files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files:
            ti = tarfile.TarInfo(f"podTc2_nrt_2026_317/{name}")
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    buf.seek(0)
    return buf


def test_one_pass_feeds_both_products():
    el = np.linspace(5.0, elev_for(140.0), 400)
    s4 = np.repeat(np.linspace(0.05, 0.5, 40), 10)
    rfi = np.where(np.arange(400) > 200, 2e-4, 0.0)
    files = [(name_for(prn=5), nc_link(T0_GPS + 600, s4, el, prn=5, rfi=rfi)),
             (name_for(prn=7, dur="0010"), nc_link(T0_GPS + 600, s4[:200], el[:200], prn=7, rfi=rfi[:200])),
             (name_for(prn=9, con="R"), nc_link(T0_GPS + 600, s4, el, prn=9, conid="R", rfi=rfi))]
    plain = C2.reduce_stream(tar_of(files))
    limb = S.Limb()
    both = C2.reduce_stream(tar_of(files), on_link=limb.add)
    for k in plain[0]:
        assert np.array_equal(plain[0][k], both[0][k]), k                  # the RFI reduction is unchanged
    assert plain[1] == both[1] and plain[2] == both[2]
    assert limb.reasons == {"ok": 2, "not GPS": 1} and limb.sats == {"C2E2": 2}
    w = limb.samples()
    r = limb.raw()
    for k in np.unique(r["key"]):
        secs = len(np.unique(r["t"][(r["key"] == k) & (r["since"] >= S.TRACK_SKIP_S)]))
        n = int((w["link"] == k).sum())
        assert secs > 0 and math.ceil(secs / 10) <= n <= math.ceil(secs / 10) + 1, (k, secs, n)   # one per 10 s block
        dt = np.diff(w["t"][w["link"] == k])
        assert np.all((dt >= 1) & (dt <= 10))


def test_job_days_gate_and_wait():
    from datetime import date
    assert J.days_from([], date(2026, 11, 15)) == ["2026-11-14"]
    assert J.days_from(["2026-10-30:2026-11-02", "2026-11-09"], date(2026, 11, 15)) == \
        ["2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02", "2026-11-09"]
    assert J.s4_tag("2026-11-14") == "swx-data-2026-11"
    assert J.asset_url("swx-data-2026-11", "x.json").endswith("/releases/download/swx-data-2026-11/x.json")

    class A:
        force = no_upload = s4_only = False
        wait_minutes, deadline_hour = 0, 13

    seen = []
    old = J.published, J.wait_for_ucar
    try:
        J.published = lambda tag, name, ua: seen.append((tag, name)) or True
        assert J.run_day("2026-11-14", A()) == "skipped"
        assert seen == [("swx-data-2026-11", "2026-11-14.cosmic2-limb-s4.json")]
        J.published = lambda *a: False
        J.wait_for_ucar = lambda *a, **k: (False, {})
        now = datetime(2026, 11, 15, 6, 0, tzinfo=timezone.utc)
        a = A()
        a.deadline_hour = 24                                        # never late: the next start looks again
        assert J.run_day("2026-11-14", a, now=now) == "waiting"
        a.deadline_hour = 0                                         # late: fail, so GitHub mails the owner
        try:
            J.run_day("2026-11-14", a, now=now)
            raise AssertionError("expected a failure past the deadline")
        except RuntimeError as e:
            assert "not posted" in str(e)
        assert J.run_day("2026-11-10", a, now=now) == "waiting"     # an older day being filled is never late
    finally:
        J.published, J.wait_for_ucar = old
    # waiting: polls until the archive answers, never past the budget
    answers = iter([(404, {}), (404, {}), (200, {"Content-Length": "5"})])
    old_status = J.http_status
    try:
        J.http_status = lambda url, ua, method="HEAD": next(answers)
        naps = []
        ok, hd = J.wait_for_ucar("u", "ua", wait_minutes=30, sleep=naps.append)
        assert ok and hd["Content-Length"] == "5" and naps == [J.POLL_S, J.POLL_S]
        J.http_status = lambda url, ua, method="HEAD": (404, {})
        ok, _ = J.wait_for_ucar("u", "ua", wait_minutes=0, sleep=naps.append)
        assert not ok
    finally:
        J.http_status = old_status


def test_job_run_day_end_to_end():
    """run_day with the download faked: the limb file is written, uploaded once, and the interference step runs."""
    el = np.linspace(5.0, elev_for(140.0), 400)
    s4 = np.repeat(np.linspace(0.05, 0.5, 40), 10)
    files = [(name_for(prn=5), nc_link(T0_GPS + 600, s4, el, prn=5)),
             (name_for(prn=7), nc_link(T0_GPS + 7200, s4, el, prn=7))]
    out_dir = os.path.join(ROOT, "data", "test_tmp_job")
    calls = []

    def fake_fetch(day, force=False, stream="nrt", on_link=None, on_retry=None):
        C2.reduce_stream(tar_of(files), on_link)
        return "table"

    class A:
        force = no_upload = False
        s4_only = False
        wait_minutes, deadline_hour = 0, 13

    old = (J.published, J.wait_for_ucar, J.upload, J.interference, C2.fetch, S.OUT)
    try:
        J.published = lambda *a: False
        J.wait_for_ucar = lambda *a, **k: (True, {"Content-Length": "123", "Last-Modified": "x"})
        J.upload = lambda tag, path, title, notes: calls.append(("upload", tag, os.path.basename(path)))
        J.interference = lambda day, no_upload, ua: calls.append(("interference", day)) or ("uploaded", None)
        C2.fetch = fake_fetch
        S.write.__defaults__ = (out_dir,)
        assert J.run_day(DAY, A(), now=datetime(2026, 11, 14, 5, 0, tzinfo=timezone.utc)) == "done"
    finally:
        J.published, J.wait_for_ucar, J.upload, J.interference, C2.fetch, _ = old
        S.write.__defaults__ = (S.OUT,)
    assert calls == [("upload", "swx-data-2026-11", f"{DAY}.cosmic2-limb-s4.json"), ("interference", DAY)]
    p = os.path.join(out_dir, f"{DAY}.cosmic2-limb-s4.json")
    doc = json.load(open(p, encoding="utf-8"))
    assert doc["counts"]["values"] > 0 and doc["source"]["bytes"] == 123
    assert sum(len(h["cells"]) for h in doc["hours"]) == doc["counts"]["cell_hours"] > 0
    os.remove(p)
    os.rmdir(out_dir)


def test_compare_rfi():
    a = {"judged_cells": 3, "cells": [["c1", 0.3, 40], ["c2", 0.25, 50]]}
    assert J.compare_rfi(a, json.loads(json.dumps(a)))["match"] is True
    b = {"judged_cells": 3, "cells": [["c1", 0.31, 40]]}
    r = J.compare_rfi(a, b)
    assert r["match"] is False and r["only_ours"] == 1 and r["max_score_diff"] == 0.01


def test_check_ground_rules():
    import cosmic2_s4_check as K
    assert all(K.keep_svid(s) for s in (1, 37, 38, 68, 71, 106, 146, 177, 181, 186))
    assert not any(K.keep_svid(s) for s in (None, 0, 69, 107, 120, 140, 141, 145, 178, 187, 191, 197, 198, 215))
    assert abs(K.s4_corrected(0.6, 0.36) - 0.48) < 1e-12 and K.s4_corrected(0.05, 0.06) == 0.0
    assert K.s4_corrected(0.7, None) == 0.7

    def rec(hh, mm, svid, s4, el=45.0, corr=0.05):
        return {"dt": f"2026-11-01 {hh:02d}:{mm:02d}:00", "svid": svid, "elevation": el, "totals4l1": s4,
                "corrections4l1": corr}
    recs = []
    for h, hi in ((1, 0), (2, 1), (3, 2)):
        recs += [rec(h, m % 60, 1 + m // 60, 0.1) for m in range(300)]
        recs += [rec(h, m, 5, 0.8) for m in range(hi)]
    recs += [rec(4, m, 3, 0.9) for m in range(50)]                     # too few satellite-minutes: unjudged
    recs += [rec(3, m, 187, 0.9) for m in range(30)] + [rec(1, m, 7, 0.9, el=20.0) for m in range(30)]  # dropped
    lab = K.hour_labels(recs)
    assert lab[1][0] == "quiet" and lab[2][0] == "unclear" and lab[3][0] == "disturbed" and lab[4][0] == "unjudged"
    assert lab[1][1] == 300 and lab[3][2] == 2


def test_check_scoring():
    import cosmic2_s4_check as K
    assert K.auc([2, 3], [0, 1]) == 1.0 and K.auc([1], [1]) == 0.5 and K.auc([], [1]) is None
    assert K.verdict("L1", 0.75) == "holds" and K.verdict("L1", 0.65) == "weakened" and K.verdict("L1", 0.5) == "fails"
    assert K.verdict("L3", 0.005) == "holds" and K.verdict("L3", 0.2) == "fails" and K.verdict("L2", None) == "not judged"
    assert K.in_night(20.0) and K.in_night(1.5) and not K.in_night(2.0) and not K.in_night(12.0)
    # a limb file with one cell near Tucuman in hour 3 and one far away
    import h3
    near = h3.latlng_to_cell(-24.0, -64.0, 1)
    far = h3.latlng_to_cell(10.0, 100.0, 1)
    la, lo = h3.cell_to_latlng(near)
    doc = {"columns": S.COLUMNS, "hours": [{"hour": h, "cells": []} for h in range(24)]}
    doc["hours"][3]["cells"] = [[near, la, lo, 20, 2, 0.9, 1.2, 23.0, 0.0], [far, 10.0, 100.0, 20, 2, 2.0, 2.5, 10.0, 1.0]]
    assert K.nearby(doc, 3, -23.727, -65.23, 1000.0) == (0.9, 1.2, 0.0)
    assert K.nearby(doc, 4, -23.727, -65.23, 1000.0) is None
    # perm_p: a perfect separation within each stratum is significant; shuffled values are not
    rng = np.random.default_rng(0)
    lab = np.tile([True, False], 100)
    vals = np.where(lab, 1.0, 0.0) + rng.normal(0, 0.1, 200)
    strata = np.repeat(np.arange(20), 10)
    a, p = K.perm_p(vals, lab, strata, n=200)
    assert a > 0.99 and p < 0.01
    a, p = K.perm_p(rng.normal(0, 1, 200), lab, strata, n=200)
    assert p > 0.01


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
