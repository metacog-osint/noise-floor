"""Private archive lane for the military air day files (milair.yml, lane milair of tools/tic_archive.py).

Every day file a milair.yml run writes lands in the private archive (metacog-osint/tic-archive) and restores byte
for byte, and a day file that a forced remake replaces on the public release stays restorable from the snapshot
that held it. The test makes a real offline run of tools/milair_job.py in a temporary folder (synthetic archive
parts, the public upload replaced by a stand-in), then runs the workflow's own tic_archive.py command, read from
milair.yml, against a local DirStore. Nothing reaches GitHub: GhStore is replaced and any subprocess call during an
archive command fails the test. The step's own bash runs with stand-ins for the archive tool.

Run as a plain script: python tests/test_archive_milair.py"""
from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import milair as M  # noqa: E402
import milair_job  # noqa: E402
import tic_archive as ta  # noqa: E402
from test_milair import fixture_traces, tar_of  # noqa: E402

WF = (ROOT / ".github" / "workflows" / "milair.yml").read_text(encoding="utf-8")
PROGRAM, LANE, SRC = "noisefloor", "milair", "data/milair"
FIRST, SECOND = "20261127T050000Z", "20261128T050000Z"
DAYS = ["2026-11-09", "2026-11-10"]


def steps() -> dict[str, str]:
    """The workflow's steps by name (unnamed steps by their action or command)."""
    out = {}
    for chunk in re.split(r"(?m)^      - ", WF.split("\n    steps:\n", 1)[1])[1:]:
        m = re.match(r"name: (.+)|uses: (\S+)|run: (.+)", chunk)
        out[(m.group(1) or m.group(2) or m.group(3)).strip()] = chunk
    return out


STEPS = steps()
DAY_STEP = "Military air day files"
ARCHIVE_STEP = "Private archive (day files made this run, to tic-archive)"


def archive_calls(text: str, cmd: str) -> list[list[str]]:
    """Every `python tools/tic_archive.py <cmd> ...` in a step, as argv after the script name."""
    flat = text.replace("\\\n", " ")
    return [[m.group(1), *shlex.split(m.group(2))]
            for m in re.finditer(r"python tools/tic_archive\.py (" + cmd + r")\b([^;|&\n]*)", flat)]


def arg(argv: list[str], flag: str) -> list[str]:
    return [argv[i + 1] for i, t in enumerate(argv) if t == flag]


def tree(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def minutes(text: str) -> int:
    (m,) = re.findall(r"(?m)^        timeout-minutes: (\d+)\s*$", text)
    return int(m)


def run_archive(argv: list[str], cwd: Path, store: Path, stamp: str = FIRST) -> int:
    """One tic_archive.py command as the workflow gives it, in cwd, against a DirStore at store."""
    def no_subprocess(*a, **k):
        raise AssertionError("an archive command tried to run a subprocess (gh): nothing may leave the test")

    old = os.getcwd()
    os.chdir(cwd)
    try:
        with mock.patch.object(ta, "GhStore", lambda *a, **k: ta.DirStore(store)), \
                mock.patch.object(ta, "utc_stamp", lambda now=None: stamp), \
                mock.patch.object(subprocess, "run", no_subprocess):
            return ta.main(argv)
    finally:
        os.chdir(old)


def job_run(root: Path, days: list[str], force: bool = False, traces=None) -> list[str]:
    """tools/milair_job.py's run() as the workflow starts it, in a copy rooted at root: synthetic archive parts,
    the release reads and the public upload replaced. Returns the days it uploaded."""
    raw = tar_of(traces or fixture_traces())
    uploaded = []
    with mock.patch.object(M, "ROOT", str(root)), \
            mock.patch.object(milair_job, "release_assets", lambda repo, tag: {}), \
            mock.patch.object(milair_job, "archive_parts", lambda day: [f"https://example.invalid/{day}.tar"]), \
            mock.patch.object(M, "url_opener", lambda url: (lambda: __import__("io").BytesIO(raw))), \
            mock.patch.object(milair_job, "upload", lambda day, path: uploaded.append(day)):
        made, _, _, failed = milair_job.run(days, force=force)
    assert not failed, failed
    assert made == uploaded == days, (made, uploaded)
    return made


class TestWorkflowStep(unittest.TestCase):
    def test_one_put_of_the_day_folder(self):
        (call,) = archive_calls(STEPS[ARCHIVE_STEP], "put")
        self.assertEqual(arg(call, "--program"), [PROGRAM])
        self.assertEqual(arg(call, "--lane"), [LANE])
        self.assertEqual(arg(call, "--src"), [SRC])
        # The day files are public already (ODbL): archived as they are, so they match the public copy by hash.
        self.assertFalse([t for t in call if t.startswith(("--redact", "--exclude", "--include"))])
        self.assertEqual([c for n, s in STEPS.items() if n != ARCHIVE_STEP for c in archive_calls(s, "put")], [])

    def test_the_folder_is_where_the_job_writes(self):
        with mock.patch.object(milair_job, "release_assets", lambda repo, tag: {}), \
                mock.patch.object(milair_job, "archive_parts", lambda day: []), \
                tempfile.TemporaryDirectory() as td, mock.patch.object(M, "ROOT", td):
            milair_job.run(DAYS)                       # nothing posted: only the folder is made
            self.assertTrue((Path(td) / SRC).is_dir())
        self.assertEqual(Path(M.ROOT).resolve(), ROOT)

    def test_after_the_day_step_and_loud_on_failure(self):
        names = list(STEPS)
        self.assertEqual(names[-1], ARCHIVE_STEP)
        self.assertGreater(names.index(ARCHIVE_STEP), names.index(DAY_STEP))
        text = STEPS[ARCHIVE_STEP]
        self.assertIn("if: ${{ !cancelled() }}", text)          # also after a failed day: what it made is kept
        self.assertIn("GH_TOKEN: ${{ secrets.TIC_ARCHIVE_TOKEN }}", text)
        self.assertNotIn("github.token", text)
        self.assertNotIn("|| true", text)
        self.assertNotIn("continue-on-error", text)
        self.assertEqual(text.count("exit 1"), 1)              # token missing
        # The day step keeps the repository token; the archive token reaches only the archive step.
        self.assertIn("GH_TOKEN: ${{ github.token }}", STEPS[DAY_STEP])
        self.assertEqual(WF.count("secrets.TIC_ARCHIVE_TOKEN"), 1)

    def test_bounded_in_time_inside_the_job(self):
        (job,) = re.findall(r"(?m)^    timeout-minutes: (\d+)\s*$", WF)
        day, archive = minutes(STEPS[DAY_STEP]), minutes(STEPS[ARCHIVE_STEP])
        # The day step times out (a failure, not a cancel) with room left for the archive step and the setup steps.
        self.assertLessEqual(day + archive + 10, int(job))
        self.assertLessEqual(archive, 10)


class TestEveryDayFileIsArchived(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="nf-milair-lane-"))
        cls.run_root, cls.store = cls.work / "run", cls.work / "store"
        cls.run_root.mkdir()
        job_run(cls.run_root, DAYS)
        (cls.put,) = archive_calls(STEPS[ARCHIVE_STEP], "put")
        cls.first = tree(cls.run_root / SRC)
        cls.rc = run_archive(cls.put, cls.run_root, cls.store, FIRST)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def snapshot(self, stamp: str) -> str:
        (name,) = [p.name for tag in self.store.iterdir() for p in tag.iterdir()
                   if p.name.startswith(stamp) and p.name.endswith(".files.json")]
        return name

    def restore(self, dest: Path, snapshot: str | None = None) -> dict[str, str]:
        cmd = ["restore", "--program", PROGRAM, "--lane", LANE, "--dest", str(dest)]
        if snapshot:
            cmd += ["--snapshot", snapshot]
        self.assertEqual(run_archive(cmd, self.run_root, self.store), 0)
        return tree(dest)

    def test_the_run_wrote_the_day_files(self):
        self.assertEqual(sorted(self.first), [f"{d}.milair.json" for d in DAYS])

    def test_the_put_succeeded_into_this_months_release(self):
        self.assertEqual(self.rc, 0)
        self.assertEqual([p.name for p in self.store.iterdir()], [f"{PROGRAM}-{LANE}-2026-11"])

    def test_every_day_file_restores_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as td:
            got = self.restore(Path(td), self.snapshot(FIRST))
        self.assertEqual(got, self.first)

    def test_a_forced_remake_keeps_the_earlier_version(self):
        day = DAYS[-1]
        path = self.run_root / SRC / f"{day}.milair.json"
        old = path.read_bytes()
        try:
            # The next run remakes one day with --force: different bytes, the same public name (--clobber there).
            fresh = self.work / "run2"
            fresh.mkdir()
            job_run(fresh, [day], force=True, traces=fixture_traces()[:2])
            self.assertNotEqual((fresh / SRC / path.name).read_bytes(), old)
            self.assertEqual(run_archive(self.put, fresh, self.store, SECOND), 0)
            with tempfile.TemporaryDirectory() as td:
                now = self.restore(Path(td) / "now")                         # the newest snapshot
                then = self.restore(Path(td) / "then", self.snapshot(FIRST))
            self.assertEqual(now, tree(fresh / SRC))
            self.assertEqual(then[path.name], hashlib.sha256(old).hexdigest())
            self.assertNotEqual(now[path.name], then[path.name])
        finally:
            shutil.rmtree(self.work / "run2", ignore_errors=True)


def find_bash() -> str | None:
    """Git's bash on Windows (System32's bash.exe is WSL), the PATH's elsewhere."""
    if os.name == "nt":
        for p in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe"):
            if os.path.exists(p):
                return p
        return None
    return shutil.which("bash")


BASH = find_bash()


def run_script(text: str) -> str:
    """The `run: |` block of a step, as the runner gets it."""
    body = []
    for line in text.split("run: |\n", 1)[1].split("\n"):
        if line.strip() and not line.startswith(" " * 10):
            break
        body.append(line[10:])
    return "\n".join(body) + "\n"


@unittest.skipUnless(BASH, "needs bash, as the runner has")
class TestArchiveStepShell(unittest.TestCase):
    """The archive step's script under bash -eo pipefail, as Actions runs it, with python replaced by a stand-in
    that records the call and exits with PUT_RC."""

    def case(self, files: list[str], token: str, put_rc: int = 0) -> tuple[int, list[str], str]:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            for f in files:
                (td / f).parent.mkdir(parents=True, exist_ok=True)
                (td / f).write_text("{}", encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME")}
            env.update(GH_TOKEN=token, CALLS=(td / "calls.txt").as_posix(), PUT_RC=str(put_rc))
            stub = 'python() { echo "$*" >> "$CALLS"; return "$PUT_RC"; }\n'
            r = subprocess.run([BASH, "--noprofile", "--norc", "-eo", "pipefail", "-c",
                                stub + run_script(STEPS[ARCHIVE_STEP])],
                               cwd=td, env=env, capture_output=True, text=True, timeout=60)
            calls = (td / "calls.txt").read_text().splitlines() if (td / "calls.txt").exists() else []
            return r.returncode, calls, r.stdout + r.stderr

    def test_no_day_file_archives_nothing_and_passes(self):
        for files in ([], ["data/milair/.keep"], ["data/other/x.milair.json"]):
            rc, calls, out = self.case(files, "token")
            self.assertEqual((rc, calls), (0, []), files)
            self.assertIn("nothing was archived", out)

    def test_no_day_file_and_no_token_still_passes(self):
        self.assertEqual(self.case([], "")[:2], (0, []))

    def test_day_files_without_the_token_fail_loudly(self):
        rc, calls, out = self.case(["data/milair/2026-11-10.milair.json"], "")
        self.assertEqual((rc, calls), (1, []))
        self.assertIn("::error::secret TIC_ARCHIVE_TOKEN is not set", out)

    def test_day_files_are_put_once(self):
        rc, calls, _ = self.case(["data/milair/2026-11-09.milair.json", "data/milair/2026-11-10.milair.json"], "t")
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [f"tools/tic_archive.py put --program {PROGRAM} --lane {LANE} --src {SRC}"])

    def test_a_failed_put_fails_the_step(self):
        rc, calls, _ = self.case(["data/milair/2026-11-10.milair.json"], "t", put_rc=1)
        self.assertNotEqual(rc, 0)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
