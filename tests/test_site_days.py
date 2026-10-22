"""Offline test for tools/site_days.py: daily map files join the committed days without overriding them."""
import json, os, shutil, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import site_days as S  # noqa: E402

COLS = ["h3", "aircraft", "bad_live", "bad_raw", "capable", "capable_bad10"]


def day_file(day, cells):
    return {"day": day, "licence": "ODbL 1.0; derived from adsb.lol", "cols": COLS, "cells": cells}


def write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def main():
    tmp = tempfile.mkdtemp()
    try:
        gnss, src = os.path.join(tmp, "gnss"), os.path.join(tmp, "dl")
        os.makedirs(gnss); os.makedirs(src)
        S.GNSS = gnss
        write(os.path.join(gnss, "2025-10-14.json"), day_file("2025-10-14", [["a", 10, 5, 5, 8, 1]]))
        write(os.path.join(gnss, "days.json"), [{"day": "2025-10-14", "note": "EGNOS outage", "hexes": 1, "jam_hexes": 1, "kb": 1}])
        # 5 aircraft, 2 bad -> 100*(2-1)/5 = 20% (jamming scale); 5 aircraft, 1 bad -> 0%; 4 aircraft -> not counted
        write(os.path.join(src, "2026-10-21.map.json"), day_file("2026-10-21", [["b", 5, 2, 2, 4, 0], ["c", 5, 1, 1, 4, 0], ["d", 4, 4, 4, 4, 4]]))
        write(os.path.join(src, "2026-10-20.map.json"), day_file("2026-10-20", [["b", 9, 0, 0, 9, 0]]))
        write(os.path.join(src, "2025-10-14.map.json"), day_file("2025-10-14", []))     # must not replace the committed day
        write(os.path.join(src, "notes.txt"), {})
        sys.argv = ["site_days.py", src]
        S.main()
        idx = json.load(open(os.path.join(gnss, "days.json")))
        assert [d["day"] for d in idx] == ["2025-10-14", "2026-10-20", "2026-10-21"], idx
        assert idx[0] == {"day": "2025-10-14", "note": "EGNOS outage", "hexes": 1, "jam_hexes": 1, "kb": 1}, idx[0]
        assert idx[2]["daily"] is True and idx[2]["hexes"] == 2 and idx[2]["jam_hexes"] == 1, idx[2]
        assert idx[1]["jam_hexes"] == 0 and idx[1]["note"] == "", idx[1]
        assert json.load(open(os.path.join(gnss, "2025-10-14.json")))["cells"] == [["a", 10, 5, 5, 8, 1]]
        assert os.path.exists(os.path.join(gnss, "2026-10-21.json")) and not os.path.exists(os.path.join(gnss, "notes.txt"))
        print("test_site_days: ok")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
