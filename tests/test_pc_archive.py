"""tools/pc_archive.py: the PC's daily copy into the private archive. A local DirStore stands in for GitHub.
Run as a plain script: python tests/test_pc_archive.py"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import pc_archive as P  # noqa: E402
import tic_archive as ta  # noqa: E402

T0 = datetime(2026, 11, 19, 12, 0, 0, tzinfo=timezone.utc)


def make_tree(root):
    files = {
        "private/nisar/state/state.json": '{"detections": [{"tier": "LOW"}]}',
        "private/nisar/black-sea/state/state.json": '{"detections": []}',
        "private/nisar/state/cache/GRANULE.npz": "x" * 100,
        "private/nisar/black-sea/state/cache/G2.npz": "y" * 100,
        "private/nisar/cache/cmr.json": "z",
        "private/nisar/out/detections.geojson": "{}",
        "data/raw/bluesky/2026-11-19.json": "[]",
        "data/raw/feeds/a.xml": "<rss/>",
        "data/raw/watch/p.html": "<html/>",
        "data/community/bluesky/digest.md": "#",
        "data/watch/alerts.jsonl": "{}\n",
        "data/declared/navwarn/archive.jsonl": "{}\n",
        "data/ais/aisstream/2026-11-19.parquet": "PAR1",
        "data/vessels/sanctioned.json": "[]",
        "data/sentinel_gnss/e1.csv": "a,b",
        "private/sentinel/area/trend.json": "{}",
        "private/watch/maritime.json": "{}",
    }
    for rel, text in files.items():
        p = Path(root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def latest_paths(store, lane):
    tags = store.tags(f"noisefloor-{lane}-")
    names = sorted(n for t in tags for n in store.assets(t) if n.endswith(".files.json"))
    doc = json.loads((store.root / tags[-1] / names[-1]).read_text(encoding="utf-8"))
    return [f["path"] for f in doc["files"]]


def test_both_lanes_archived_caches_left_out():
    with tempfile.TemporaryDirectory() as td:
        make_tree(td)
        store = ta.DirStore(Path(td) / "store")
        assert P.run(list(P.LANES), Path(td), store, now=T0) == 0
        nisar = latest_paths(store, "nisar")
        assert "nisar/state/state.json" in nisar and "nisar/black-sea/state/state.json" in nisar
        assert "nisar/out/detections.geojson" in nisar
        assert not any(p.endswith(".npz") or "/cache/" in p for p in nisar), nisar
        coll = latest_paths(store, "collectors")
        for want in ("raw-bluesky/2026-11-19.json", "watch/alerts.jsonl", "navwarn/archive.jsonl",
                     "ais/aisstream/2026-11-19.parquet", "sentinel-private/area/trend.json",
                     "watch-config/maritime.json"):
            assert want in coll, want
        assert not (Path(td) / "data/logs/ARCHIVE_FAILED.txt").exists()


def test_pruned_rows_survive_in_earlier_snapshot():
    with tempfile.TemporaryDirectory() as td:
        make_tree(td)
        store = ta.DirStore(Path(td) / "store")
        P.run(["nisar"], Path(td), store, now=T0)
        state = Path(td) / "private/nisar/state/state.json"
        state.write_text('{"detections": []}', encoding="utf-8")       # the prune removed the LOW row
        P.run(["nisar"], Path(td), store, now=T0 + timedelta(days=1))
        tag = store.tags("noisefloor-nisar-")[0]
        snaps = sorted(n for n in store.assets(tag) if n.endswith(".files.json"))
        assert len(snaps) == 2
        out = Path(td) / "restored"
        ta.Archive(store, "noisefloor", "nisar").restore(out, snaps[0])
        assert "LOW" in (out / "nisar/state/state.json").read_text(encoding="utf-8")


def test_missing_folder_archives_the_rest_then_fails_loudly():
    with tempfile.TemporaryDirectory() as td:
        make_tree(td)
        import shutil
        shutil.rmtree(Path(td) / "data/ais")
        store = ta.DirStore(Path(td) / "store")
        assert P.run(list(P.LANES), Path(td), store, now=T0) == 1
        flag = Path(td) / "data/logs/ARCHIVE_FAILED.txt"
        assert flag.exists() and "data/ais" in flag.read_text(encoding="utf-8")
        assert "watch/alerts.jsonl" in latest_paths(store, "collectors")
        (Path(td) / "data/ais").mkdir()
        (Path(td) / "data/ais/x.parquet").write_text("PAR1", encoding="utf-8")
        assert P.run(list(P.LANES), Path(td), store, now=T0 + timedelta(hours=1)) == 0
        assert not flag.exists()


def test_upload_failure_returns_1():
    class Broken(ta.DirStore):
        def upload(self, tag, paths):
            raise ta.ArchiveError("network down")
    with tempfile.TemporaryDirectory() as td:
        make_tree(td)
        store = Broken(Path(td) / "store")
        P.ta.time.sleep = lambda s: None
        assert P.run(["nisar"], Path(td), store, now=T0) == 1
        assert (Path(td) / "data/logs/ARCHIVE_FAILED.txt").exists()


def test_run_daily_calls_archive_last():
    cmd = Path(ROOT, "collectors", "run_daily.cmd").read_text(encoding="utf-8").splitlines()
    runs = [i for i, line in enumerate(cmd) if line.startswith(".venv\\Scripts\\python.exe")]
    assert "tools\\pc_archive.py" in cmd[runs[-1]], cmd[runs[-1]]


if __name__ == "__main__":
    for k, f in sorted(globals().items()):
        if k.startswith("test_"):
            f()
            print(k, "ok")
