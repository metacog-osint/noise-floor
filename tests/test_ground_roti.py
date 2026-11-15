"""Offline tests for tools/ground_roti.py (ROTI, a measured TEC fluctuation index at fixed stations), the day job
tools/ground_roti_job.py and the check tools/ground_roti_check.py. Synthetic data only: no network, no hatanaka, no
data/ files. Run as a plain script: python tests/test_ground_roti.py"""
import gzip
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cosmic2_job as J  # noqa: E402
import ground_roti as R  # noqa: E402
import ground_roti_check as K  # noqa: E402
import ground_roti_job as GJ  # noqa: E402

DAY = "2026-11-13"
F1, F2 = R.SIGNALS["G"][0], R.SIGNALS["G"][2]


def synth_sat(tec, rho=None, f1=F1, f2=F2, a1="1C", a2="2L"):
    """Carrier phases (cycles) and codes (m) for a slant TEC series (TECU) and a range; MW is then exactly 0."""
    k = np.arange(R.NEP, dtype=float)
    rho = 2.2e7 + 300.0 * k if rho is None else rho
    i1, i2 = 40.308e16 * tec / f1 ** 2, 40.308e16 * tec / f2 ** 2
    return {"L" + a1: (rho - i1) / (R.C / f1), "L" + a2: (rho - i2) / (R.C / f2),
            "C" + a1: rho + i1, "C" + a2: rho + i2}


def test_label_and_scale():
    assert R.LABEL == "ROTI, a measured TEC fluctuation index at fixed stations"
    assert abs(R.stec_scale(F1, F2) - 0.10507) < 2e-4                      # metres of L1-L2 per TECU
    fe1, fe5 = R.SIGNALS["E"][0], R.SIGNALS["E"][2]
    assert abs(R.stec_scale(fe1, fe5) - 0.12883) < 2e-4


def test_parse_obs_float64_lli_and_grid():
    def field(v, lli=" "):
        return f"{v:14.3f}{lli} " if v is not None else " " * 16
    hdr = [
        "     4.02           OBSERVATION DATA    M                   RINEX VERSION / TYPE",
        "TEST00XXX                                                   MARKER NAME",
        "  6378137.0000        0.0000        0.0000                  APPROX POSITION XYZ",
        "G    4 C1C L1C C2L L2L                                      SYS / # / OBS TYPES",
        "E    4 C1X L1X C5X L5X                                      SYS / # / OBS TYPES",
        "                                                            END OF HEADER"]
    body = [
        "> 2026 11 13 00 00  0.0000000  0  2",
        "G05" + field(22000000.123) + field(115612345.678) + field(22000003.5) + field(90087654.321, "1"),
        "E11" + field(23000000.0) + field(120000000.5) + field(None) + field(89000000.25),
        "> 2026 11 13 00 00 15.0000000  0  1",                                 # off the 30 s grid: ignored
        "G05" + field(1.0) + field(2.0) + field(3.0) + field(4.0),
        "> 2026 11 13 00 00 30.0000000  4  1",                                 # event record: skipped
        "COMMENT LINE",
        "> 2026 11 13 00 01  0.0000000  0  1",
        "G05" + field(22000300.0) + field(115613922.0) + field(22000303.0) + field(90088883.0)]
    h, vals, lli, present = R.parse_obs("\n".join(hdr + body), DAY)
    assert h["version"] == "4.02" and h["marker"] == "TEST00XXX"
    assert present[0] and present[2] and present.sum() == 2
    assert vals["G05"]["L1C"].dtype == np.float64
    assert vals["G05"]["L1C"][0] == 115612345.678                         # float64 keeps the millicycles
    assert lli["G05"]["L2L"][0] == 1 and "L1C" not in lli["G05"]
    assert np.isnan(vals["E11"].get("C5X", np.full(R.NEP, np.nan))[0]) and vals["E11"]["L5X"][0] == 89000000.25
    assert vals["G05"]["C1C"][2] == 22000300.0 and np.isnan(vals["G05"]["C1C"][1])


def test_rinex_text_plain_gzip():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "BRDC00IGS_R_20263170000_01D_MN.rnx.gz")
        with gzip.open(p, "wb") as f:
            f.write(b"hello")
        assert R.rinex_text(p) == ("hello", None)


def test_rot_slips_lli_gaps_and_mask():
    k = np.arange(R.NEP, dtype=float)
    tec = 20.0 + 0.01 * k                                                  # 0.01 TECU per 30 s = 0.02 TECU/min
    obs = synth_sat(tec)
    el = np.full(R.NEP, 60.0)
    rot, brk, sig = R.rot_series(obs, {}, "G", el)
    assert sig == "G:L1C+L2L"
    assert np.isnan(rot[0]) and np.allclose(rot[1:], 0.02, atol=1e-6)
    assert not brk.any()
    # an L1 slip of 5 cycles at epoch 100: MW jumps 5 wide-lane cycles -> no ROT there, ROT fine after it
    obs2 = {c: v.copy() for c, v in obs.items()}
    obs2["L1C"][100:] += 5
    rot2, brk2, _ = R.rot_series(obs2, {}, "G", el)
    assert np.isnan(rot2[100]) and brk2[100] and brk2.sum() == 1
    assert np.allclose(rot2[101:], 0.02, atol=1e-6)
    # a slip on both carriers by the same number of cycles is invisible to MW (documented limit): ROT spikes
    obs3 = {c: v.copy() for c, v in obs.items()}
    obs3["L1C"][200:] += 1
    obs3["L2L"][200:] += 1
    rot3, brk3, _ = R.rot_series(obs3, {}, "G", el)
    assert not brk3.any() and abs(rot3[200] - 0.02 - (R.C / F1 - R.C / F2) / R.stec_scale(F1, F2) / 0.5) < 1e-6
    # loss-of-lock indicator bit 0 at epoch 300; bit 1 alone (half-cycle) is not a break
    lli = {"L2L": np.zeros(R.NEP, np.int8)}
    lli["L2L"][300] = 1
    lli["L2L"][301] = 2
    rot4, brk4, _ = R.rot_series(obs, lli, "G", el)
    assert np.isnan(rot4[300]) and brk4[300] and np.isfinite(rot4[301])
    # gap at epoch 400: no ROT at 400 or 401 (no consecutive pair), and not counted as a break
    obs5 = {c: v.copy() for c, v in obs.items()}
    obs5["C2L"][400] = np.nan
    rot5, brk5, _ = R.rot_series(obs5, {}, "G", el)
    assert np.isnan(rot5[400]) and np.isnan(rot5[401]) and np.isfinite(rot5[402]) and not brk5.any()
    # below the mask
    el2 = el.copy()
    el2[500:510] = 29.9
    rot6, _, _ = R.rot_series(obs, {}, "G", el2)
    assert np.isnan(rot6[500:510]).all() and np.isfinite(rot6[510])
    # the band-2 signal with more epochs wins; ties go to the preference order
    obs7 = dict(obs)
    obs7.update({"L2W": obs["L2L"].copy(), "C2W": obs["C2L"].copy()})
    assert R.pick(obs7, R.SIGNALS["G"][3]) == "2L"
    obs7["L2L"] = obs7["L2L"].copy()
    obs7["L2L"][:10] = np.nan
    assert R.pick(obs7, R.SIGNALS["G"][3]) == "2W"


def test_roti_windows():
    rot = np.full(R.NEP, np.nan)
    rot[10:20] = np.tile([1.0, -1.0], 5)                                   # window 1: std 1
    rot[20:28] = 3.0                                                        # window 2: 8 values, std 0
    rot[30:37] = np.arange(7.0)                                             # window 3: 7 values, not enough
    out, cnt = R.roti_windows(rot)
    assert out.shape == (288,) and abs(out[1] - 1.0) < 1e-12 and out[2] == 0.0
    assert np.isnan(out[3]) and cnt[3] == 7 and np.isnan(out[0])


def test_pierce():
    la, lo = R.pierce(10.0, 20.0, 0.0, 90.0)
    assert abs(la - 10.0) < 1e-9 and abs(lo - 20.0) < 1e-9
    la, lo = R.pierce(0.0, 0.0, 0.0, 30.0)                                  # due north at 30 deg
    psi = 60.0 - math.degrees(math.asin(6371.0 / 6721.0 * math.cos(math.radians(30))))
    assert abs(la - psi) < 1e-9 and abs(lo) < 1e-9 and 4.7 < la < 4.9      # about 535 km north
    la, lo = R.pierce(0.0, 179.9, 90.0, 30.0)                               # due east across the date line
    assert lo < -170


def test_station_day_and_hour_rows():
    rng = np.random.default_rng(1)
    k = np.arange(R.NEP, dtype=float)
    vals, sky = {}, {}
    for i, sat in enumerate(["G01", "G02", "E03"]):
        tec = 15.0 + np.cumsum(rng.normal(0, 0.02 if i else 0.2, R.NEP))   # G01 fluctuates ten times more
        if sat[0] == "E":
            vals[sat] = synth_sat(tec, f1=R.SIGNALS["E"][0], f2=R.SIGNALS["E"][2], a1="1C", a2="5Q")
        else:
            vals[sat] = synth_sat(tec)
        sky[sat] = (np.full(R.NEP, 45.0), np.where(k < 1440, 50.0, 10.0))  # up for the first 12 hours
    rows, nbrk, used = R.station_day(vals, {}, sky, 5.0, -1.0)
    assert used == {"G01": "G:L1C+L2L", "G02": "G:L1C+L2L", "E03": "E:L1C+L5Q"}
    assert len(rows) == 3 * 144 - 0 and not nbrk.any()                      # window 0 has 9 ROT values: enough
    hours = R.hour_rows("TEST00XXX", rows, nbrk, 5.0, -1.0)
    assert set(hours) == set(range(12))
    r = hours[3]
    assert R.COLUMNS == ["station", "lat", "lon", "n", "sats", "p95", "max", "max_lat", "max_lon", "lst", "breaks"]
    assert r[0] == "TEST00XXX" and r[3] == 36 and r[4] == 3 and r[5] is not None
    g01 = [v for w, s, v, _, _ in rows if s == "G01" and w // 12 == 3]
    assert r[6] == round(max(g01), 3) and abs(r[9] - ((3.5 - 1 / 15) % 24)) < 0.01
    assert abs(r[7] - R.pierce(5.0, -1.0, 45.0, 50.0)[0]) < 0.01
    few = R.hour_rows("TEST00XXX", rows[:10], nbrk, 5.0, -1.0)
    assert few[0][3] == 10 and few[0][5] is None                            # p95 needs 20 values


def test_build_day_file():
    rows = [(w, "G01", 0.05 + 0.001 * w, 5.0, 0.0) for w in range(288)]
    hrs = R.hour_rows("ACRG00GHA", rows, np.zeros(R.NEP, int), 5.6, -0.2)
    info = {"id": "ACRG00GHA", "place": "Ghana", "lat": 5.6, "lon": -0.2, "file": "ACRG.crx.gz", "windows": 288,
            "satellites": 1, "partner": "lag0p", "note": "compact RINEX 3.1 read as 3.0"}
    doc = R.build(DAY, {"ACRG00GHA": (hrs, info)}, ["CPVG00CPV"], {"NKLG00GAB": "SourceError: bad"},
                  "BRDC00IGS_R_20263170000_01D_MN.rnx.gz", now=datetime(2026, 11, 14, 9, 30, tzinfo=timezone.utc),
                  posted={"ACRG.crx.gz": "2026-11-14 00:05"})
    assert doc["feed"] == "ground-roti" and doc["version"] == R.VERSION and doc["as_of"] == "2026-11-14T09:30:00Z"
    assert doc["measure"] == R.LABEL and "not an S4 value" in doc["not_s4"] and doc["units"] == "TECU/min"
    assert doc["sources"] == ["cors-igs"] and doc["licence"].startswith("CC BY 4.0")
    assert doc["missing"] == ["CPVG00CPV"] and doc["failed"] == {"NKLG00GAB": "SourceError: bad"}
    assert len(doc["hours"]) == 24 and doc["hours"][5]["stations"][0][0] == "ACRG00GHA"
    assert doc["counts"] == {"stations": 1, "station_hours": 24, "with_p95": 0, "values": 288}
    assert doc["stations"][0]["posted"] == "2026-11-14 00:05 UTC"
    assert any("not posted" in p and "CPVG00CPV" in p for p in doc["problems"])
    assert any(p.startswith("NKLG00GAB") for p in doc["problems"]) and any("3.1" in p for p in doc["problems"])


def test_station_table():
    assert len(R.STATIONS) == 17 and all(len(s) == 9 for s in R.STATIONS)
    for s in ("CPVG00CPV", "ACRG00GHA", "NKLG00GAB", "ASCG00SHN", "DJIG00DJI", "SEY200SYC", "VOIM00MDG", "DGAR00GBR"):
        assert s in R.STATIONS
    assert len(K.PARTNERS) == 10 and K.PARTNERS["mal0p"] == "MAL200KEN"
    import cosmic2_s4_check as G
    for code, sta in K.PARTNERS.items():                                   # every pair within 500 km
        assert R.km(*G.STATIONS[code][1:3], *R.STATIONS[sta][1:3]) < 500
    assert sorted(K.far_pairs()) == [("DJIG00DJI", "mal0p"), ("DJIG00DJI", "nai0p"), ("NKLG00GAB", "lag0p")]


def bkg_html(names):
    return "".join(f'<tr><td><a href="{n}">{n}</a></td><td align="right">2026-11-14 09:05  </td></tr>' for n in names)


def test_listing_parse():
    import urllib.request
    html = bkg_html(["ACRG00GHA_R_20263170000_01D_30S_MO.crx.gz", "BRDC00IGS_R_20263170000_01D_MN.rnx.gz"])

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return html.encode()
    real = urllib.request.urlopen
    urllib.request.urlopen = lambda *a, **k: Resp()
    try:
        lst = R.bkg_listing(DAY)
    finally:
        urllib.request.urlopen = real
    assert lst["ACRG00GHA_R_20263170000_01D_30S_MO.crx.gz"] == "2026-11-14 09:05"
    assert R.obs_file(lst, "ACRG00GHA", DAY) == "ACRG00GHA_R_20263170000_01D_30S_MO.crx.gz"
    assert R.obs_file(lst, "CPVG00CPV", DAY) is None
    assert R.nav_file(lst, DAY) == "BRDC00IGS_R_20263170000_01D_MN.rnx.gz"


def args(**kw):
    a = dict(force=False, no_upload=False, wait_minutes=30, publish_hour=9, deadline_hour=13, refresh_days=2)
    a.update(kw)
    return SimpleNamespace(**a)


def test_job_decide():
    a = args()
    full = {f"S{i}": "f" for i in range(17)}
    some = {"S1": "f"}
    assert GJ.decide({"missing": []}, full, 17, True, 10, a, 0) == "skip"
    assert GJ.decide({"missing": ["S1"]}, some, 17, True, 10, a, 0) == "refresh"
    assert GJ.decide({"missing": ["S2"]}, some, 17, True, 10, a, 0) == "skip"
    assert GJ.decide({"missing": ["S1"]}, some, 17, False, 10, a, 3) == "skip"   # too old to refresh
    assert GJ.decide(None, {}, 17, True, 5, a, 0) == "waiting"
    assert GJ.decide(None, {}, 17, True, 13, a, 0) == "late"
    assert GJ.decide(None, {}, 17, False, 13, a, 4) == "waiting"
    assert GJ.decide(None, full, 17, True, 2, a, 0) == "publish"
    assert GJ.decide(None, some, 17, True, 8, a, 0) == "waiting"
    assert GJ.decide(None, some, 17, True, 9, a, 0) == "wait"
    assert GJ.decide(None, some, 17, False, 2, a, 5) == "publish"
    assert GJ.decide({"missing": []}, full, 17, True, 10, args(force=True), 0) == "publish"
    from datetime import date
    assert GJ.default_days(date(2026, 11, 15), 2) == ["2026-11-12", "2026-11-13", "2026-11-14"]


def test_job_run_day():
    calls = []
    saved = (GJ.published_doc, R.available, R.make_day, J.upload)
    state = {"doc": None, "have": {"ACRG00GHA": "f"}}

    def fake_make(day, stations, log=print):
        doc = {"counts": {"stations": len(state["have"]), "station_hours": 24, "with_p95": 20},
               "missing": [s for s in stations if s not in state["have"]], "failed": {}, "problems": []}
        calls.append(("make", day))
        return doc, os.path.join(tempfile.gettempdir(), f"{day}.ground-roti.json")
    GJ.published_doc = lambda tag, name: state["doc"]
    R.available = lambda day, stations: (dict(state["have"]), "nav", {})
    R.make_day = fake_make
    J.upload = lambda tag, path, title, notes: calls.append(("upload", tag, os.path.basename(path)))
    try:
        now = datetime(2026, 11, 14, 3, 0, tzinfo=timezone.utc)
        # newest day, an old (backfill) day, and the sleep loop: use a fixed clock through decide's `hour`
        assert GJ.run_day("2026-10-20", args(), now) == "published"
        assert calls[-1] == ("upload", "swx-data-2026-10", "2026-10-20.ground-roti.json")
        state["doc"] = {"missing": []}
        assert GJ.run_day("2026-10-20", args(), now) == "skipped"
        state["doc"] = {"missing": ["ACRG00GHA"]}
        assert GJ.run_day("2026-11-13", args(), now) == "refreshed"
        state["doc"] = None
        slept = []

        def fake_sleep(s):
            slept.append(s)
            state["have"] = {s: "f" for s in R.STATIONS}
        assert GJ.run_day("2026-11-13", args(publish_hour=0), now, sleep=fake_sleep) == "published"
        assert slept == [GJ.POLL_S]
        state["have"] = {}
        assert GJ.run_day("2026-11-13", args(deadline_hour=24), now) == "waiting"
        try:
            GJ.run_day("2026-11-13", args(deadline_hour=0), now)
            raise AssertionError("expected a failure past the deadline")
        except RuntimeError as e:
            assert "past 00:00 UTC" in str(e)
    finally:
        GJ.published_doc, R.available, R.make_day, J.upload = saved


def test_check_pairs_and_scores():
    import cosmic2_s4_check as G
    days = [f"2026-10-{d:02d}" for d in range(16, 26)]
    rng = np.random.default_rng(3)
    truth = {}

    def ground(code, day):
        recs = []
        for h in range(24):
            hot = (h in (20, 21, 22)) and rng.random() < 0.5
            truth[(code, day, h)] = hot
            for m in range(310):
                s4 = 0.7 if hot and m < 3 else 0.1
                recs.append({"dt": f"{day} {h:02d}:{m % 60:02d}:00", "svid": 1 + m % 30, "elevation": 45.0,
                             "totals4l1": s4, "corrections4l1": 0.0})
        return recs
    cache = {}

    def ground_c(code, day):
        if (code, day) not in cache:
            cache[(code, day)] = ground(code, day)
        return cache[(code, day)]

    def roti(day):
        hours = []
        for h in range(24):
            rows = []
            for code, sta in K.PARTNERS.items():
                ground_c(code, day)
                v = 1.0 if truth.get((code, day, h)) else 0.05 + 0.01 * rng.random()
                rows.append([sta, 0.0, 0.0, 100, 10, v, v * 2, 0.0, 0.0, 0.0, 0])
            for sta in ("NKLG00GAB", "DJIG00DJI"):
                rows.append([sta, 0.0, 0.0, 100, 10, 0.05, 0.1, 0.0, 0.0, 0.0, 0])
            hours.append({"stations": rows})
        return {"hours": hours, "stations": [{"id": s} for s in R.STATIONS]}
    res = K.check(days, ground_c, roti)
    assert res["R1_auc"] == 1.0 and res["R1"] == "holds" and res["R3"] == "holds" and res["validated"] in (True, False)
    assert res["unpaired"] == 0 and res["disturbed"] > 20
    assert res["far_pairs"]["pairs"] > 0 and res["far_pairs"]["links"]
    assert G.in_night(20.5) and K.verdict("R1", 0.75) == "weakened" and K.verdict("R3", 0.2) == "fails"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
