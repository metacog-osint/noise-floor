"""tools/sentinel_catalog_check.py with a fake catalogue. Run as a plain script: python tests/test_sentinel_catalog_check.py"""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import sentinel_catalog_check as C  # noqa: E402

NOW = datetime(2026, 12, 1, 12, 0, 0, tzinfo=timezone.utc)


def name(unit, day, made="20261030T114245"):
    return f"{unit}_OPER_AUX_GNSSRD_POD__{made}_V202611{day:02d}T235942_202611{day + 1:02d}T235932"


A, B, C_, D, E = name("S1C", 1), name("S1C", 2), name("S2B", 3), name("S2B", 4), name("S3A", 5)
HELD = {A: "id-a", B: "id-b", C_: "id-c", D: "id-d", E: "id-e"}


def catalogue(extra_404=()):
    """A present (second page), B offline, C replaced by a newer product, D gone, E only found by its own lookup."""
    listing = {"S1C": [[{"Id": "id-b", "Name": B + ".TGZ", "Online": False}], [{"Id": "id-a", "Name": A + ".TGZ", "Online": True}]],
               "S2B": [[{"Id": "id-new", "Name": name("S2B", 3, "20261120T000000") + ".TGZ", "Online": True}]],
               "S3A": [[]]}

    def get(url):
        if "(id-" in url or "(id%2D" in url:
            cid = url.rsplit("(", 1)[1].rstrip(")").replace("%2D", "-")
            if cid == "id-e":
                return 200, {"Id": cid, "Name": E + ".TGZ", "Online": True}
            return 404, None
        if url.startswith("next:"):
            unit, page = url[5:].split(":")
            pages = listing[unit]
            page = int(page)
        else:
            unit = next(u for u in listing if u in url)
            pages, page = listing[unit], 0
        doc = {"value": pages[page]}
        if page + 1 < len(pages):
            doc["@odata.nextLink"] = f"next:{unit}:{page + 1}"
        return 200, doc
    return get


def tree(td, held=HELD):
    raw = Path(td) / "data/sentinel_gnss/raw"
    raw.mkdir(parents=True)
    lines = [json.dumps({"name": n, "catalogue_id": i}) for n, i in held.items()]
    (raw / "index.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return Path(td)


def test_classify_follows_pages_and_sorts_every_file():
    out = C.classify(HELD, catalogue(), pause=0)
    assert out == {"present": [A, E], "offline": [B], "replaced": [C_], "gone": [D]}, out


def test_newest_index_row_wins():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "i.jsonl"
        p.write_text(json.dumps({"name": A, "catalogue_id": "old"}) + "\n" + json.dumps({"name": A, "catalogue_id": "new"}) + "\n",
                     encoding="utf-8")
        assert C.held_files(p) == {A: "new"}


def test_report_alert_and_once_a_month():
    with tempfile.TemporaryDirectory() as td:
        root = tree(td)
        assert C.run(root, catalogue(), NOW) == 0
        doc = json.loads((root / "data/sentinel_gnss/catalog_check/2026-12.json").read_text(encoding="utf-8"))
        assert doc["counts"] == {"present": 2, "offline": 1, "replaced": 1, "gone": 1}
        assert doc["gone"] == [D]
        assert (root / "data/logs/SENTINEL_CATALOG_ALERT.txt").exists()

        def no_calls(url):
            raise AssertionError("the month's report exists, so nothing should be requested")
        assert C.run(root, no_calls, NOW) == 0


def test_clean_check_clears_the_alert():
    with tempfile.TemporaryDirectory() as td:
        root = tree(td, {A: "id-a"})
        flag = root / "data/logs/SENTINEL_CATALOG_ALERT.txt"
        flag.parent.mkdir(parents=True)
        flag.write_text("old", encoding="utf-8")
        assert C.run(root, catalogue(), NOW) == 0
        assert not flag.exists()


def test_failed_check_writes_nothing_and_retries():
    with tempfile.TemporaryDirectory() as td:
        root = tree(td)

        def down(url):
            raise C.CheckError("catalogue request failed: HTTP 503")
        assert C.run(root, down, NOW) == 1
        assert not (root / "data/sentinel_gnss/catalog_check/2026-12.json").exists()
        assert not (root / "data/logs/SENTINEL_CATALOG_ALERT.txt").exists()
        assert C.run(root, catalogue(), NOW) == 0


def test_dry_run_writes_nothing():
    with tempfile.TemporaryDirectory() as td:
        root = tree(td)
        assert C.run(root, catalogue(), NOW, force=True, dry_run=True) == 0
        assert not (root / "data/sentinel_gnss/catalog_check").exists()


def test_run_daily_calls_it_before_the_archive():
    cmd = Path(ROOT, "collectors", "run_daily.cmd").read_text(encoding="utf-8").splitlines()
    runs = [line for line in cmd if line.startswith(".venv\\Scripts\\python.exe")]
    assert "tools\\sentinel_catalog_check.py" in runs[-2], runs[-2]
    assert "tools\\pc_archive.py" in runs[-1], runs[-1]


if __name__ == "__main__":
    for k, f in sorted(globals().items()):
        if k.startswith("test_"):
            f()
            print(k, "ok")
