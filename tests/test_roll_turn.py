"""tools/roll_turn.py: ISA density, expected turn rate, pair building, runs and episode tags on synthetic traces."""
import math, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import roll_turn as R  # noqa: E402

DAY0 = 1792022400.0      # 2026-10-15T00:00:00Z


def pt(t, track, roll, ias=250, alt=35000, kind="adsb_icao", nacp=10):
    # readsb trace point: [t, lat, lon, alt, gs, track, flags, vrate, details, type, geom_alt, geom_rate, ias, roll]
    return [t, 55.0, 20.0, alt, 450.0, track, 0, 0, {"nac_p": nacp, "version": 2}, kind, alt, 0, ias, roll]


def main():
    assert abs(R.density_ratio(0) - 1.0) < 1e-3 and 0.30 < R.density_ratio(35000) < 0.32 and R.density_ratio(45000) < 0.2
    w = R.expected_rate(25.0, 250, 35000)
    assert 1.05 < w < 1.2, w                                      # about 1.1 deg/s for an airliner at FL350
    assert R.expected_rate(0.0, 250, 35000) == 0.0 and R.expected_rate(-25.0, 250, 35000) == -w
    assert R.wrap(350 - 10) == -20 and R.wrap(10 - 350) == 20

    # a coordinated turn: the track follows the bank -> residuals ~0, no run
    turn = [pt(10 * i, (90 + w * 10 * i) % 360, 25.0) for i in range(30)]
    p = R.trace_pairs({"icao": "abc123", "timestamp": DAY0, "trace": turn}, DAY0)
    assert len(p) == 29 and max(abs(x[3]) for x in p) < 1e-6 and R.runs_of(p) == []
    # banked for 2 min but the GNSS track stays straight (a false track) -> a run
    fake = [pt(10 * i, 90.0, 25.0) for i in range(13)]
    p = R.trace_pairs({"icao": "abc123", "timestamp": DAY0, "trace": fake}, DAY0)
    assert all(abs(x[3]) >= 1.0 for x in p) and R.runs_of(p) == [0], (p[:2], R.runs_of(p))
    # two mismatches only: not a run; gaps over 40 s break runs and pairs
    short = [pt(10 * i, 90.0, 25.0 if i in (1, 2) else 0.0) for i in range(6)]
    assert R.runs_of(R.trace_pairs({"icao": "x", "timestamp": DAY0, "trace": short}, DAY0)) == []
    gap = [pt(0, 90, 0.0), pt(10, 90, 0.0), pt(70, 90, 0.0), pt(80, 90, 0.0)]
    assert len(R.trace_pairs({"icao": "x", "timestamp": DAY0, "trace": gap}, DAY0)) == 2
    # filters: MLAT points, below 10,000 ft, slow IAS, steep roll, points under 8 s apart
    skip = [pt(0, 90, 0.0), pt(10, 90, 0.0, kind="mlat"), pt(20, 90, 0.0, alt=8000), pt(30, 90, 0.0), pt(40, 90, 0.0, ias=120),
            pt(50, 90, 50.0), pt(53, 90, 0.0), pt(60, 90, 0.0)]
    p = R.trace_pairs({"icao": "x", "timestamp": DAY0, "trace": skip}, DAY0)
    assert [round(x[0] - DAY0) for x in p] == [60], p            # only 50 -> 60 qualifies (53 is under 8 s after 50)
    # NACp tracked for the jammed-not-spoofed check
    p = R.trace_pairs({"icao": "x", "timestamp": DAY0, "trace": [pt(0, 90, 0.0, nacp=0), pt(10, 90, 0.0, nacp=0)]}, DAY0)
    assert p[0][4] is True
    # episode tags
    win = [(DAY0 + 100, DAY0 + 200, "isolated"), (DAY0 + 150, DAY0 + 300, "active")]
    assert R.tag_of(DAY0 + 120, win) == "other" and R.tag_of(DAY0 + 160, win) == "active" and R.tag_of(DAY0 + 400, win) == "none"
    # worker aggregation: one aircraft, one hour, run counted once
    import gzip, json
    raw = gzip.compress(json.dumps({"icao": "abc123", "timestamp": DAY0, "trace": fake}).encode())
    rows, n_ac, n_pairs = R.work(([raw], DAY0, {}))
    assert n_ac == 1 and n_pairs == 12 and len(rows) == 1 and rows[0][:6] == ("abc123", 0, "none", 12, 12, 1), rows
    assert rows[0][9] == 0.0                                       # every point at 55N 20E: held at a point
    assert R.spread_km([55.0, 55.1, 55.2], [20.0, 20.0, 20.0], 55.1, 20.0) > 10 and R.spread_km([], [], 0, 0) is None
    print("test_roll_turn: ok")


if __name__ == "__main__":
    main()
