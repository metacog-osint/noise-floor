"""tools/position_loss.py: per hex-hour flags from a synthetic trace, and the aggregation."""
import gzip, json, os, sys
from datetime import datetime, timezone

import h3

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import position_loss as L  # noqa: E402


def trace(icao, pts, ts):
    # readsb trace point: [t offset, lat, lon, alt, gs, track, flags, vrate, details, type, ...]
    return gzip.compress(json.dumps({"icao": icao, "timestamp": ts, "trace": [
        [t, la, lo, alt, 450, 90, 0, 0, None, typ] for t, la, lo, alt, typ in pts]}).encode())


def main():
    day0 = int(datetime(2026, 9, 15, tzinfo=timezone.utc).timestamp())
    a, b = (54.0, 22.5), (52.4, 20.0)       # Suwalki-Elk and central Poland
    ha, hb = (h3.str_to_int(h3.latlng_to_cell(*p, 4)) for p in (a, b))
    t1 = trace("4ca123", [(3600, *a, 35000, "mlat"), (3700, *a, 35000, "mlat"),           # 01Z in A: MLAT only
                          (7300, *b, 36000, "adsb_icao"), (7400, *b, 36000, "mlat"),      # 02Z in B: both
                          (7500, *b, 5000, "mlat"),                                        # below 10,000 ft: ignored
                          (90000, *b, 36000, "adsb_icao")], day0)                          # next day: ignored
    t2 = trace("4ca456", [(3650, *a, 34000, "adsb_icao"), (3660, *a, 34000, "other")], day0)
    t3 = trace("~abc123", [(3650, *a, 34000, "mlat")], day0)                               # non-ICAO: skipped
    assert L.trace_cells(t1, day0) == {(ha, 1): 2, (hb, 2): 3}, L.trace_cells(t1, day0)
    assert L.trace_cells(t2, day0) == {(ha, 1): 1} and L.trace_cells(t3, day0) is None
    hh, dd, n = L.work(([t1, t2, t3], day0, L.MIN_ALT))
    assert n == 2
    assert hh[(ha, 1)] == [2, 1, 1, 1] and hh[(hb, 2)] == [1, 1, 0, 1], hh      # heard, adsb, mlat_only, mlat_any
    assert dd[ha] == [2, 1, 1, 1] and dd[hb] == [1, 1, 0, 1], dd
    print("test_position_loss: ok")


if __name__ == "__main__":
    main()
