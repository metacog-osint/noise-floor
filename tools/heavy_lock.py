#!/usr/bin/env python3
"""heavy_lock.py: a machine-wide lock for heavy local jobs, so two of them never run at once on a shared PC.

On 16 Nov 2026 one cached rerun day took 935 s against about 250 s for its neighbours, because other jobs were running.
A heavy job (a variant score, a multi-day spoof_day run or rerun, a cache build, any long job that needs the cores or
the disk) takes this lock first and waits, with a clear message, while another one holds it.

    import heavy_lock
    with heavy_lock.hold("score-variant V1"):
        ...                                   # the heavy part

    python tools/heavy_lock.py status                       # who holds it, since when, whether it is alive
    python tools/heavy_lock.py run --label "my job" -- python some_job.py --args
    python tools/heavy_lock.py clear-stale                  # remove a lock whose holder has died

The lock is one small JSON file, created atomically (O_EXCL), in a folder that is the same for every project on the
machine and that is worked out at run time: $TIC_HEAVY_LOCK_DIR, else %LOCALAPPDATA%\\tic-heavy (Windows) or
$XDG_STATE_HOME/tic-heavy (default ~/.local/state/tic-heavy), so nothing personal is written into any repo.

Stale locks: the file holds the holder's PID and the process start time. A waiter that finds the PID gone, or the PID
now belonging to a different process (a start time that differs), removes the file and takes the lock. A holder that is
alive but hung is never removed by a waiter; stop that process, or run `release --force`.

Children: acquiring sets TIC_HEAVY_LOCK_TOKEN in the environment. A child process that calls hold() (for example a
heavy tool started by a heavy tool) sees its parent's token on the lock and doesn't wait for itself.

Other projects' heavy jobs can adopt it by wrapping the command (`python <noise-floor>/tools/heavy_lock.py run -- ...`)
or by copying this one file (standard library only) and calling hold() at the top of the job's main().
"""
import argparse
import atexit
import contextlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

TOKEN_ENV = "TIC_HEAVY_LOCK_TOKEN"
LOCK_NAME = "heavy.lock"


def lock_dir():
    d = os.environ.get("TIC_HEAVY_LOCK_DIR")
    if d:
        return d
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    else:
        base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "tic-heavy")


def lock_path():
    return os.path.join(lock_dir(), LOCK_NAME)


# ---------- processes ----------

def _win_open(pid):
    import ctypes
    k = ctypes.windll.kernel32
    k.OpenProcess.restype = ctypes.c_void_p
    return k, k.OpenProcess(0x1000, False, int(pid))        # PROCESS_QUERY_LIMITED_INFORMATION


def pid_alive(pid):
    """True if a process with this PID exists now."""
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k, h = _win_open(pid)
        if not h:
            return False                     # access denied also means it exists, but a lock holder is ours: not seen
        try:
            code = wintypes.DWORD()
            k.GetExitCodeProcess(ctypes.c_void_p(h), ctypes.byref(code))
            return code.value == 259         # STILL_ACTIVE
        finally:
            k.CloseHandle(ctypes.c_void_p(h))
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def proc_start(pid):
    """An opaque start-time stamp of a process (to tell a reused PID from the holder), or None if it can't be read."""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            k, h = _win_open(pid)
            if not h:
                return None
            try:
                c, e, kt, ut = (wintypes.FILETIME() for _ in range(4))
                if not k.GetProcessTimes(ctypes.c_void_p(h), ctypes.byref(c), ctypes.byref(e), ctypes.byref(kt),
                                         ctypes.byref(ut)):
                    return None
                return (c.dwHighDateTime << 32) | c.dwLowDateTime
            finally:
                k.CloseHandle(ctypes.c_void_p(h))
        with open(f"/proc/{int(pid)}/stat", "rb") as f:
            return int(f.read().rsplit(b")", 1)[1].split()[19])
    except Exception:
        return None


# ---------- the lock file ----------

def read_lock():
    """The lock's contents, or None if there is none (or it is unreadable: a half-written file counts as held)."""
    try:
        with open(lock_path(), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception:
        return {"pid": None, "label": "(unreadable lock file)", "token": None, "unreadable": True}


def is_stale(info):
    """The holder is gone, or its PID now belongs to another process."""
    if info is None:
        return False
    if info.get("unreadable"):
        try:
            return time.time() - os.path.getmtime(lock_path()) > 30      # a writer takes milliseconds
        except OSError:
            return False
    pid = info.get("pid")
    if not pid_alive(pid):
        return True
    start = info.get("pid_start")
    now = proc_start(pid)
    return start is not None and now is not None and start != now


def _remove_if(token):
    """Remove the lock file if it still holds this token (a waiter that races another one removes only what it read)."""
    info = read_lock()
    if info is not None and info.get("token") == token:
        with contextlib.suppress(FileNotFoundError):
            os.remove(lock_path())
        return True
    return False


def describe(info):
    if not info:
        return "no heavy job holds the lock"
    started = info.get("started")
    since = ""
    if started:
        secs = max(0, int(time.time() - datetime.fromisoformat(started).timestamp()))
        since = f", running {secs // 3600}h {secs % 3600 // 60:02d}m since {started}"
    return f"'{info.get('label')}' (pid {info.get('pid')}, {info.get('cmd', '')[:80]}){since}"


class Held:
    def __init__(self, token, owned):
        self.token, self.owned = token, owned

    def release(self):
        if self.owned:
            _remove_if(self.token)
            self.owned = False
            if os.environ.get(TOKEN_ENV) == self.token:
                del os.environ[TOKEN_ENV]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


def acquire(label, wait=True, poll=5.0, timeout=None, notify=None, every=60.0):
    """Take the lock. wait: block until it is free (message every `every` seconds), else raise BlockingIOError.
    timeout: seconds to wait at most (then TimeoutError). Returns a Held (also a context manager)."""
    notify = notify or (lambda m: print(m, file=sys.stderr, flush=True))
    mine = os.environ.get(TOKEN_ENV)
    cur = read_lock()
    if mine and cur and cur.get("token") == mine:
        return Held(mine, False)                          # a child of the holder: already covered
    os.makedirs(lock_dir(), exist_ok=True)
    token = uuid.uuid4().hex
    t0, last = time.time(), 0.0
    while True:
        info = {"pid": os.getpid(), "pid_start": proc_start(os.getpid()), "label": label, "token": token,
                "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "cmd": " ".join(sys.argv)[:200]}
        try:
            fd = os.open(lock_path(), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            cur = read_lock()
            if cur is None:
                continue                                  # released between our attempt and the read
            if is_stale(cur):
                notify(f"heavy_lock: removing a stale lock, {describe(cur)}: that process is gone")
                _remove_if(cur.get("token"))
                continue
            if not wait:
                raise BlockingIOError(f"another heavy job holds the lock: {describe(cur)}")
            if timeout is not None and time.time() - t0 > timeout:
                raise TimeoutError(f"gave up after {timeout:.0f} s waiting for: {describe(cur)}")
            if time.time() - last >= every:
                notify(f"heavy_lock: waiting for another heavy job, {describe(cur)}. '{label}' starts when it ends "
                       f"(waited {int(time.time() - t0)} s).")
                last = time.time()
            time.sleep(poll)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(info, f)
        os.environ[TOKEN_ENV] = token
        if time.time() - t0 > 1:
            notify(f"heavy_lock: '{label}' got the lock after {int(time.time() - t0)} s")
        held = Held(token, True)
        atexit.register(held.release)                     # also on an exception or sys.exit
        return held


def hold(label, **kw):
    """Context manager: `with hold("job"): ...` (see acquire for the keywords)."""
    return acquire(label, **kw)


def status():
    info = read_lock()
    return {"path": lock_path(), "held": info is not None, "stale": is_stale(info), "holder": info}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("clear-stale")
    rel = sub.add_parser("release", help="remove the lock whoever holds it (only with --force)")
    rel.add_argument("--force", action="store_true")
    run = sub.add_parser("run", help="run a command while holding the lock")
    run.add_argument("--label", default=None)
    run.add_argument("--timeout", type=float, default=None, help="give up waiting after this many seconds")
    run.add_argument("argv", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    if a.cmd == "status":
        s = status()
        print(json.dumps(s, indent=1))
        print(describe(s["holder"]) + (" [STALE: holder gone]" if s["stale"] else ""))
    elif a.cmd == "clear-stale":
        info = read_lock()
        if info is not None and is_stale(info):
            _remove_if(info.get("token"))
            print("removed:", describe(info))
        else:
            print("nothing stale:", describe(info))
    elif a.cmd == "release":
        if not a.force:
            sys.exit("release removes another job's lock: pass --force if its process is hung or gone")
        with contextlib.suppress(FileNotFoundError):
            os.remove(lock_path())
        print("lock removed")
    else:
        argv = a.argv[1:] if a.argv[:1] == ["--"] else a.argv
        if not argv:
            sys.exit("usage: heavy_lock.py run [--label L] -- command ...")
        with hold(a.label or " ".join(argv)[:60], timeout=a.timeout):
            sys.exit(subprocess.call(argv))


if __name__ == "__main__":
    main()
