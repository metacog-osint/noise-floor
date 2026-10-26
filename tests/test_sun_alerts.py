"""tools/sun_alerts.py: alerts from predicted sun-outage windows and synthetic NOAA data, with and without numpy."""
import os, sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import sun_alerts as A  # noqa: E402

TARGETS = {"slots": [{"lon": 13.0, "name": "Hot Bird 13E"}, {"lon": 52.5, "name": "Yahsat 1A 52.5E"}],
           "cities": [{"name": "Tehran", "lat": 35.69, "lon": 51.39, "tz": "Asia/Tehran"},
                      {"name": "Sydney", "lat": -33.87, "lon": 151.21, "tz": "Australia/Sydney"}]}
NOW = datetime(2026, 10, 9, 18, 0, tzinfo=timezone.utc)


def flux_file():
    rows = []
    for d in range(1, 31):                       # 30 quiet days at 500 sfu, then a bright 8 Oct at 700 sfu
        v = 700 if d == 8 else 500
        rows.append({"time_tag": f"2026-10-{d:02d}T12:00:00" if d <= 9 else f"2026-09-{d:02d}T12:00:00",
                     "common_name": "Test", "details": [{"frequency": 15400, "flux": v}]})
    return rows


def main():
    # Hot Bird from Tehran on 8 Oct 2026: 11:11-11:20 UTC (see tools/sun_transit.py)
    events = [
        {"type": "RBR", "frequency": "15400", "particulars1": "800", "begin_datetime": "2026-10-08T11:14:00", "max_datetime": "2026-10-08T11:15:00"},
        {"type": "RBR", "frequency": "15400", "particulars1": "800", "begin_datetime": "2026-10-08T16:00:00", "max_datetime": "2026-10-08T16:01:00"},
        {"type": "RBR", "frequency": "1415", "particulars1": "2400", "begin_datetime": "2026-10-07T07:00:00", "max_datetime": "2026-10-07T07:02:00"},
        {"type": "RBR", "frequency": "1415", "particulars1": "300", "begin_datetime": "2026-10-07T08:00:00", "max_datetime": "2026-10-07T08:01:00"},
        {"type": "XRA", "frequency": "1-8A", "particulars1": "M1.0", "begin_datetime": "2026-10-07T08:00:00"},
    ]
    reports = {"reports": [
        {"time_utc": "2026-10-08T11:16:00Z", "lat": 35.69, "lon": 51.39, "satellite_lon": 13.0, "source_name": "test", "summary": "Inside."},
        {"time_utc": "2026-10-08T15:00:00Z", "lat": 35.69, "lon": 51.39, "satellite_lon": 13.0, "source_name": "test", "summary": "Outside."},
    ]}
    res = A.make_alerts(TARGETS, flux_file(), events, reports, now=NOW)
    kinds = [a["kind"] for a in res["alerts"]]
    assert kinds.count("burst-in-window") == 1, kinds          # the 16:00 burst is outside every window
    assert kinds.count("l-burst") == 1, kinds                  # 300 sfu is below the 1000 sfu line
    assert kinds.count("bright-sun") == 1, kinds               # 8 Oct only, and only if that day had windows
    assert kinds.count("report") == 2, kinds
    rep = {a["text"][-60:]: a["level"] for a in res["alerts"] if a["kind"] == "report"}
    assert sorted(rep.values()) == ["both", "obs"], rep         # inside = both, outside = observed only
    assert all(a["id"].startswith("sun-") for a in res["alerts"]) and res["pairs"] == 2, res["pairs"]   # Sydney sees neither slot
    burst = [a for a in res["alerts"] if a["kind"] == "burst-in-window"][0]
    assert "Hot Bird 13E from Tehran" in burst["text"], burst["text"]
    # the same windows without numpy
    if A.np is not None:
        pairs = A.pairs_from(TARGETS)
        t0 = datetime(2026, 10, 7, tzinfo=timezone.utc)
        w_np = [(a, b, p["city"], p["slot"]) for a, b, p in A.windows(pairs, t0, 3)]
        saved, A.np = A.np, None
        try:
            w_py = [(a, b, p["city"], p["slot"]) for a, b, p in A.windows(pairs, t0, 3)]
        finally:
            A.np = saved
        assert w_np == w_py and w_np, (len(w_np), len(w_py))
    print("test_sun_alerts: ok")


if __name__ == "__main__":
    main()
