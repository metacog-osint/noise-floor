"""Offline tests for tools/cosmic2_daily.py's upload step: a day already in cosmic2-data (made by GitHub's
tools/cosmic2_job.py) is kept and compared, never replaced, unless --replace or --resummarise. No network, no data/."""
import contextlib
import io
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cosmic2_daily as D  # noqa: E402
import cosmic2_job as J  # noqa: E402

DAY = "2026-11-15"
OURS = {"day": DAY, "judged_cells": 4222, "raised_cells": 2, "satellites": ["C2E2"],
        "cells": [["c1", 0.3, 40], ["c2", 0.25, 50]]}


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _run(published, theirs=None, replace=False, fail_download=False):
    """write() with summarise, the release and gh faked. Returns (gh calls, printed text)."""
    calls = []
    old = (D.summarise, D.OUT, D.gh, J.published, D.urllib.request.urlopen)
    tmp = tempfile.mkdtemp()

    def urlopen(req, timeout=None):
        if fail_download:
            raise OSError("boom")
        return _Resp(json.dumps(theirs).encode())

    D.summarise = lambda day: dict(OURS)
    D.OUT = tmp
    D.gh = lambda *a, check=True: calls.append(a) or type("R", (), {"returncode": 0})()
    J.published = lambda tag, name, ua: published
    D.urllib.request.urlopen = urlopen
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            path = D.write(DAY, no_upload=False, replace=replace)
        assert os.path.exists(path)
    finally:
        D.summarise, D.OUT, D.gh, J.published, D.urllib.request.urlopen = old
    return calls, out.getvalue()


def _uploads(calls):
    return [c for c in calls if c[:2] == ("release", "upload")]


def test_new_day_is_uploaded():
    calls, text = _run(published=False)
    assert len(_uploads(calls)) == 1 and "--clobber" in _uploads(calls)[0]
    assert "uploaded to release cosmic2-data" in text and "Compared with it" not in text


def test_day_in_release_is_kept_and_compared():
    calls, text = _run(published=True, theirs=json.loads(json.dumps(OURS)))
    assert _uploads(calls) == [] and calls == []
    line = next(x for x in text.splitlines() if "Compared with it: " in x)
    assert line.startswith(f"{DAY}: {DAY}.cosmic2.json already in cosmic2-data; not replaced.")
    assert json.loads(line.split("Compared with it: ", 1)[1])["match"] is True


def test_difference_is_logged_not_uploaded():
    theirs = {"judged_cells": 4222, "cells": [["c1", 0.31, 40]]}
    calls, text = _run(published=True, theirs=theirs)
    cmp = json.loads(text.split("Compared with it: ", 1)[1].splitlines()[0])
    assert _uploads(calls) == [] and cmp["match"] is False and cmp["only_ours"] == 1


def test_unreadable_copy_is_still_kept():
    calls, text = _run(published=True, fail_download=True)
    cmp = json.loads(text.split("Compared with it: ", 1)[1].splitlines()[0])
    assert _uploads(calls) == [] and cmp["match"] is None and "boom" in cmp["error"]


def test_replace_uploads_over_it():
    calls, text = _run(published=True, theirs=OURS, replace=True)
    assert len(_uploads(calls)) == 1 and "Compared with it" not in text


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
