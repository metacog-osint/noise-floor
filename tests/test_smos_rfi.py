"""Offline tests for tools/smos_rfi.py (SMOS browse reader and hot-look share). No network, no data/ files."""
import os
import struct
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import smos_rfi as S  # noqa: E402


def record(gid, lat, lon, entries):
    """One grid point: header, then (pol, value, flags) entries as 14-byte BT_Data."""
    b = struct.pack("<Ifffbb", gid, lat, lon, 0.0, 1, len(entries))
    for pol, val, extra in entries:
        b += struct.pack("<HfHHHH", pol | extra, val, 1000, 0, 0, 0)
    return b


def dbl(records):
    return struct.pack("<I", len(records)) + b"".join(records)


def test_fixed_records():
    buf = dbl([record(7, 70.0, -60.0, [(0, 250.0, 0), (1, 240.0, 0), (2, 1.0, 0), (3, 0.5, 0)]),
               record(8, 70.1, -60.0, [(0, 400.0, S.FLAG_RFI_POINT), (1, 260.0, 0), (2, 1.0, 0), (3, 0.5, 0)])])
    ids, lat, lon, x, y, fl = S.read_dbl(buf)
    assert list(ids) == [7, 8]
    assert np.allclose(x, [250.0, 400.0]) and np.allclose(y, [240.0, 260.0])
    assert list(fl) == [False, True]
    assert abs(lat[1] - 70.1) < 1e-4


def test_order_and_variable_length():
    """Entries out of order and a record with only two entries: the walker path must give the same answer."""
    buf = dbl([record(1, 60.0, 10.0, [(1, 230.0, 0), (0, 330.0, 0), (3, 0.0, 0), (2, 0.0, 0)]),
               record(2, 60.1, 10.0, [(0, 200.0, 0), (1, 190.0, 0)])])
    ids, lat, lon, x, y, fl = S.read_dbl(buf)
    assert list(ids) == [1, 2]
    assert np.allclose(x, [330.0, 200.0]) and np.allclose(y, [230.0, 190.0])
    try:
        S.read_dbl(buf + b"\x00")
        raise AssertionError("a trailing byte should be refused")
    except ValueError:
        pass


def test_reduce_counts_hot_looks():
    a = S.read_dbl(dbl([record(5, 0.0, 0.0, [(0, 330.0, 0), (1, 200.0, 0)]),
                        record(6, 1.0, 0.0, [(0, 200.0, 0), (1, 210.0, 0)])]))
    b = S.read_dbl(dbl([record(5, 0.0, 0.0, [(0, 200.0, 0), (1, 360.0, 0)]),
                        record(6, 1.0, 0.0, [(0, 310.0, 0), (1, float("nan"), 0)])]))     # Y missing: not a look
    r = S.reduce_points([a, b])
    i5, i6 = list(r["id"]).index(5), list(r["id"]).index(6)
    assert r["looks"][i5] == 2 and r["hot320"][i5] == 2 and r["hot350"][i5] == 1
    assert r["looks"][i6] == 1 and r["hot300"][i6] == 0 and abs(r["max_k"][i6] - 210.0) < 1e-3


def test_verdict_marks():
    base = {"auc_share_hot320": 0.85, "sites_heard_all_weeks": 9, "far_share_at_heard": 0.03}
    assert S.verdicts(base) == {"M1": "holds", "M2": "holds", "M3": "holds"}
    assert S.verdicts({**base, "auc_share_hot320": 0.7, "sites_heard_all_weeks": 5,
                       "far_share_at_heard": 0.10}) == {"M1": "weakened", "M2": "weakened", "M3": "weakened"}
    assert S.verdicts({**base, "auc_share_hot320": 0.6, "sites_heard_all_weeks": 4,
                       "far_share_at_heard": 0.2}) == {"M1": "fails", "M2": "fails", "M3": "fails"}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
