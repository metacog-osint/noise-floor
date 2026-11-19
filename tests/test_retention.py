"""Retention archives (18 Nov 2026): FAA GPS test history, sun-alert history, `.v<n>` copies of
reruns. A fake in-memory release stands in for the GitHub CLI. Run as a plain script: python tests/test_retention.py"""
import fnmatch, gzip, json, os, shutil, sys, tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in ("tools", "pipeline"):
    sys.path.insert(0, os.path.join(ROOT, d))
import release_archive as R  # noqa: E402
import faa_gps_tests as F  # noqa: E402
import sun_alerts as SA  # noqa: E402
import daily_job as J  # noqa: E402
import fetch_release_files as FR  # noqa: E402

RELEASES = {}     # tag -> {name: bytes}


def fake_gh(*args):
    a = list(args)
    if a[:2] == ["release", "download"]:
        tag, pat, out = a[2], a[a.index("-p") + 1], a[a.index("-D") + 1]
        with open(os.path.join(out, pat), "wb") as f:
            f.write(RELEASES[tag][pat])
    elif a[:2] == ["release", "upload"]:
        tag = a[2]
        for p in (x for x in a[3:] if os.path.exists(x)):
            name = os.path.basename(p)
            assert "--clobber" in a or name not in RELEASES[tag], "would overwrite " + name
            with open(p, "rb") as f:
                RELEASES[tag][name] = f.read()
    elif a[:2] == ["release", "create"]:
        RELEASES.setdefault(a[2], {})
    return ""


def fake_assets(tag, repo=None):
    return None if tag not in RELEASES else {n: len(b) for n, b in RELEASES[tag].items()}


R.gh, R.release_assets = fake_gh, fake_assets


def lines(tag, prefix):
    out = []
    for n in sorted(RELEASES[tag]):
        if n.startswith(prefix):
            b = RELEASES[tag][n]
            b = gzip.decompress(b) if n.endswith(".gz") else b
            out += [json.loads(x) for x in b.decode().splitlines()]
    return out


def test_faa_history():
    RELEASES["declared-data"] = {"faa_gps_tests.json": b"{}"}
    store = {"tests": {}}
    for i in range(227):
        base = "T%d GPS 25-%d" % (i, i)
        store["tests"][base] = {"base": base, "id": base, "nid": i, "radii_nm": [{"nm": 50}]}
    t1 = datetime(2026, 11, 18, 5, 40, tzinfo=timezone.utc)
    assert F.archive_history(store, now=t1) == 227                        # first run: every stored record
    assert F.archive_history(store, now=t1.replace(minute=41)) == 0       # nothing new: no asset
    first = {n: b for n, b in RELEASES["declared-data"].items() if "history" in n}
    assert len(first) == 1 and next(iter(first)).startswith("faa_gps_tests.history-2026-11-")
    # a REV replaces the stored record: the old one stays in the history, the new one is appended
    store["tests"]["T5 GPS 25-5"] = {"base": "T5 GPS 25-5", "id": "T5 GPS 25-5 REV 1", "nid": 999, "radii_nm": [{"nm": 80}]}
    store["tests"]["T300 GPS 25-300"] = {"base": "T300 GPS 25-300", "id": "x", "nid": 300}
    t2 = datetime(2026, 12, 2, 5, 40, tzinfo=timezone.utc)                # a new month: new asset name, old one untouched
    assert F.archive_history(store, now=t2) == 2
    hist = {n: b for n, b in RELEASES["declared-data"].items() if "history" in n}
    assert len(hist) == 2 and all(hist[n] == b for n, b in first.items()), "closed history asset was rewritten"
    recs = [x["record"] for x in lines("declared-data", "faa_gps_tests.history-")]
    t5 = [r for r in recs if r["base"] == "T5 GPS 25-5"]
    assert [r["radii_nm"][0]["nm"] for r in t5] == [50, 80] and len(recs) == 229
    assert RELEASES["declared-data"]["faa_gps_tests.json"] == b"{}"       # the live asset is not touched here
    # a failure is loud (annotation), and does not raise into the step that uploads the live store
    R.release_assets = lambda *a, **k: None
    try:
        assert F.archive_history(store, now=t2) == -1
    finally:
        R.release_assets = fake_assets


def test_sun_history():
    RELEASES.pop("sun-alerts-2026", None)
    a1 = {"id": "sun-l-burst-2026-11-17T07:00:00Z", "kind": "l-burst", "t": "2026-11-17T07:00:00Z", "text": "x"}
    a2 = {"id": "sun-bright-sun-2026-11-17T12:00:00Z", "kind": "bright-sun", "t": "2026-11-17T12:00:00Z", "text": "1.30x"}
    t1 = datetime(2026, 11, 18, 6, 0, 5, tzinfo=timezone.utc)
    assert SA.archive_alerts({"alerts": [a1, a2]}, now=t1) == 2           # creates the release
    assert SA.archive_alerts({"alerts": [a1, a2]}, now=t1.replace(second=9)) == 0
    a2b = dict(a2, text="1.34x")                                          # same id, changed content: kept as a new version
    a3 = {"id": "sun-l-burst-2026-11-18T01:00:00Z", "kind": "l-burst", "t": "2026-11-18T01:00:00Z", "text": "y"}
    snap = dict(RELEASES["sun-alerts-2026"])
    assert SA.archive_alerts({"alerts": [a3, a2b]}, now=t1.replace(hour=9)) == 2
    assert all(RELEASES["sun-alerts-2026"][n] == b for n, b in snap.items())          # earlier assets untouched
    got = [x["record"] for x in lines("sun-alerts-2026", "sun-alerts-history-2026-")]
    assert [r["id"] for r in got].count(a2["id"]) == 2 and a1 in got and a3 in got    # a1 has left the 7-day view but is kept
    assert all(n.endswith(".jsonl") for n in RELEASES["sun-alerts-2026"])


def test_keep_old_versions():
    tag = "pnt-data-2026-11"
    RELEASES[tag] = {"2026-11-10.anomalies.json": b'{"v":1}', "2026-11-10.hourly.parquet": b"P"}
    J.REPO = "o/r"
    J.gh = fake_gh
    J.assets = lambda repo, t: fake_assets(t)

    def dl(repo, t, name, folder, size=None):
        os.makedirs(folder, exist_ok=True)
        p = os.path.join(folder, name)
        with open(p, "wb") as f:
            f.write(RELEASES[t][name])
        return p
    J.download = dl
    tmp = tempfile.mkdtemp()
    try:
        new = os.path.join(tmp, "2026-11-10.anomalies.json")
        with open(new, "wb") as f:
            f.write(b'{"v":2}')
        pq = os.path.join(tmp, "2026-11-10.hourly.parquet")
        with open(pq, "wb") as f:
            f.write(b"Q")
        assert J.keep_old_versions(tag, [new, pq]) == ["2026-11-10.anomalies.v1.json"]      # parquet is not copied
        assert RELEASES[tag]["2026-11-10.anomalies.v1.json"] == b'{"v":1}'
        fake_gh("release", "upload", tag, new, "--clobber")                                  # the overwrite itself
        assert J.keep_old_versions(tag, [new]) == []                                         # identical rerun: no copy
        with open(new, "wb") as f:
            f.write(b'{"v":3}')
        assert J.keep_old_versions(tag, [new]) == ["2026-11-10.anomalies.v2.json"]
        assert RELEASES[tag]["2026-11-10.anomalies.v1.json"] == b'{"v":1}' and RELEASES[tag]["2026-11-10.anomalies.v2.json"] == b'{"v":2}'
        assert J.keep_old_versions(tag, [os.path.join(tmp, "2026-11-11.bursts.json")]) == []  # a first run keeps nothing
        assert not any(FR.FILES.match(n) for n in RELEASES[tag] if ".v" in n)                # readers ignore the copies
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for k, f in sorted(globals().items()):
        if k.startswith("test_"):
            f()
            print(k, "ok")
