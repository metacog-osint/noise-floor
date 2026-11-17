"""tools/ops_tally.py: the log parser and the landing-time rows (no network)."""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import ops_tally as T  # noqa: E402


def test_compared():
    lines = [
        "=== cosmic2_daily 2026-11-17T11:34Z",
        "2026-11-16: 4222 cells scored, 52560 bins, flagged share 0.104",
        '2026-11-16: 2026-11-16.cosmic2.json already in cosmic2-data; not replaced. Compared with it: {"same_cells": '
        'true, "only_ours": 0, "only_theirs": 0, "max_score_diff": 0.0, "match": true}',
        '2026-11-17: x. Compared with it: {"same_cells": false, "only_ours": 2, "match": false}',
        '2026-11-15: x. Compared with it: {broken}',
    ]
    rows = T.compared(lines)
    assert [d for d, _ in rows] == ["2026-11-15", "2026-11-16", "2026-11-17"]
    assert rows[0][1]["match"] is None and rows[1][1]["match"] is True and rows[2][1]["match"] is False
    assert [d for d, _ in T.compared(lines, since="2026-11-16")] == ["2026-11-16", "2026-11-17"]


def test_landing_rows():
    up = {"2026-11-15": datetime(2026, 11, 16, 14, 5, tzinfo=timezone.utc),
          "2026-11-16": datetime(2026, 11, 17, 4, 35, tzinfo=timezone.utc),
          "2026-11-20": datetime(2026, 11, 21, 4, 30, tzinfo=timezone.utc)}
    rows = T.landing_rows(up, "2026-11-16", "2026-11-19")
    assert [(d, round(h, 2)) for d, _, h in rows] == [("2026-11-16", 4.58)]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
