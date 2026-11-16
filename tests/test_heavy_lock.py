"""Offline tests for tools/heavy_lock.py: one holder at a time, stale locks by PID, children of the holder, the CLI.

Run:  python tests/test_heavy_lock.py   (or pytest)
"""
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import heavy_lock as HL  # noqa: E402

TMP = tempfile.mkdtemp()
os.environ["TIC_HEAVY_LOCK_DIR"] = os.path.join(TMP, "lock")
os.environ.pop(HL.TOKEN_ENV, None)
MSGS = []


def quiet(m):
    MSGS.append(m)


def dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_default_path_is_computed_not_hard_coded():
    keep = os.environ.pop("TIC_HEAVY_LOCK_DIR")
    try:
        d = HL.lock_dir()
        assert d.endswith("tic-heavy") and "metac" not in d.lower(), d
    finally:
        os.environ["TIC_HEAVY_LOCK_DIR"] = keep


def test_one_holder_at_a_time():
    assert HL.status()["held"] is False
    a = HL.acquire("first", notify=quiet)
    try:
        s = HL.status()
        assert s["held"] and s["holder"]["pid"] == os.getpid() and s["holder"]["label"] == "first" and not s["stale"]
        os.environ.pop(HL.TOKEN_ENV)                       # as another process would see it
        try:
            HL.acquire("second", wait=False, notify=quiet)
            raise AssertionError("second holder got the lock")
        except BlockingIOError as e:
            assert "first" in str(e)
        t = time.time()
        try:
            HL.acquire("third", timeout=0.3, poll=0.1, every=0.0, notify=quiet)
            raise AssertionError("third holder got the lock")
        except TimeoutError:
            pass
        assert time.time() - t < 5 and any("waiting for another heavy job" in m and "first" in m for m in MSGS), MSGS
        os.environ[HL.TOKEN_ENV] = a.token
    finally:
        a.release()
    assert HL.status()["held"] is False and HL.TOKEN_ENV not in os.environ
    with HL.hold("again", notify=quiet):
        assert HL.status()["holder"]["label"] == "again"
    assert HL.status()["held"] is False


def test_child_of_the_holder_does_not_wait():
    with HL.hold("parent", notify=quiet):
        out = subprocess.run([sys.executable, "-c",
                              "import sys; sys.path.insert(0, %r); import heavy_lock as H; "
                              "h = H.acquire('child', wait=False); print(h.owned)" % os.path.join(ROOT, "tools")],
                             capture_output=True, text=True, env=dict(os.environ))
        assert out.returncode == 0 and out.stdout.strip() == "False", (out.stdout, out.stderr)
        assert HL.status()["holder"]["label"] == "parent"


def test_stale_lock_is_taken_over():
    os.makedirs(HL.lock_dir(), exist_ok=True)
    pid = dead_pid()
    with open(HL.lock_path(), "w") as f:
        json.dump({"pid": pid, "pid_start": 1, "label": "crashed", "token": "x", "started": "2026-11-16T00:00:00+00:00"}, f)
    assert HL.status()["stale"]
    del MSGS[:]
    with HL.hold("after the crash", wait=False, notify=quiet) as h:
        assert h.owned and HL.status()["holder"]["label"] == "after the crash"
    assert any("stale" in m and "crashed" in m for m in MSGS), MSGS


def test_reused_pid_is_stale_a_live_holder_is_not():
    os.makedirs(HL.lock_dir(), exist_ok=True)
    mine = HL.proc_start(os.getpid())
    with open(HL.lock_path(), "w") as f:                    # this PID is alive; the start time says another process
        json.dump({"pid": os.getpid(), "pid_start": (mine + 7) if mine is not None else None, "label": "old", "token": "y"}, f)
    if mine is not None:
        assert HL.status()["stale"], "same PID, different start time: the PID was reused"
    with open(HL.lock_path(), "w") as f:
        json.dump({"pid": os.getpid(), "pid_start": mine, "label": "live", "token": "z"}, f)
    assert not HL.status()["stale"]
    os.remove(HL.lock_path())


def test_cli_run_holds_the_lock_and_returns_the_exit_status():
    script = os.path.join(ROOT, "tools", "heavy_lock.py")
    probe = ("import sys; sys.path.insert(0, %r); import heavy_lock as H; "
             "s = H.status(); sys.exit(3 if s['held'] and s['holder']['label'] == 'probe job' else 9)" % os.path.join(ROOT, "tools"))
    env = {k: v for k, v in os.environ.items() if k != HL.TOKEN_ENV}
    r = subprocess.run([sys.executable, script, "run", "--label", "probe job", "--", sys.executable, "-c", probe], env=env,
                       capture_output=True, text=True)
    assert r.returncode == 3, (r.returncode, r.stderr)
    assert HL.status()["held"] is False, "released after the command"
    r = subprocess.run([sys.executable, script, "status"], env=env, capture_output=True, text=True)
    assert r.returncode == 0 and "no heavy job holds the lock" in r.stdout, r.stdout


if __name__ == "__main__":
    import shutil
    try:
        for name, fn in list(globals().items()):
            if name.startswith("test_") and callable(fn):
                fn()
                print("PASS", name)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
