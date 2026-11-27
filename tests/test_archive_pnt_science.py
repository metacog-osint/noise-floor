"""Private archive lanes for the PNT, declared and space-weather day files and the feed history log.

daily.yml (lanes pnt and declared), cosmic2.yml (limbs4), ground-roti.yml (roti) and deploy-site.yml (feedlog) each
end with a step that puts what the run wrote into the private archive (tools/tic_archive.py,
metacog-osint/tic-archive). The tests check that:
  - each step runs last, also after a failure, with the archive token and nothing else, inside the job's time limit;
  - the archived folders are the ones the jobs write: the folder constants are read from the job modules' source
    (no import, so no science dependencies are needed), and the raw inputs the jobs read stay out;
  - the workflow's own put commands, run against a local DirStore, restore every file byte for byte, and a file a
    later run replaces stays restorable from the snapshot that held it (GhStore replaced; any subprocess call fails);
  - each step's bash, under -eo pipefail with a stand-in for the archive tool, archives nothing when the run made
    nothing, fails without the token, and tries every lane even when one fails.

Run as a plain script: python tests/test_archive_pnt_science.py"""
from __future__ import annotations

import ast
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
import pc_archive  # noqa: E402
import tic_archive as ta  # noqa: E402

PROGRAM = "noisefloor"
FIRST, SECOND = "20261127T060000Z", "20261128T060000Z"
WORKFLOWS = {
    # workflow: (job, archive step, {lane: [--src values]}, {lane: [--exclude values]})
    "daily.yml": ("process", "Private archive (this run's PNT and declared files, to tic-archive)",
                  {"pnt": ["data/pnt"], "declared": ["data/declared"]}, {"pnt": [], "declared": []}),
    "cosmic2.yml": ("day", "Private archive (day files made this run, to tic-archive)",
                    {"limbs4": ["swx=data/swx", "cosmic2=data/cosmic2/daily"]}, {"limbs4": ["swx/raw/*"]}),
    "ground-roti.yml": ("day", "Private archive (day files made this run, to tic-archive)",
                        {"roti": ["data/swx"]}, {"roti": ["raw/*"]}),
    "deploy-site.yml": ("deploy", "Private archive (feed history log, to tic-archive)",
                        {"feedlog": ["$RUNNER_TEMP/feed-history"]}, {"feedlog": []}),
}


def text_of(wf: str) -> str:
    return (ROOT / ".github" / "workflows" / wf).read_text(encoding="utf-8")


def job_text(wf: str, job: str) -> str:
    t = text_of(wf)
    m = re.search(r"(?m)^  " + re.escape(job) + r":\n(.*?)(?=^  \S|\Z)", t.split("\njobs:\n", 1)[1], re.S)
    return m.group(1)


def steps(wf: str, job: str) -> dict[str, str]:
    """The job's steps by name (unnamed steps by their action or command)."""
    out = {}
    for chunk in re.split(r"(?m)^      - ", job_text(wf, job).split("\n    steps:\n", 1)[1])[1:]:
        m = re.match(r"name: (.+)|if: (.+)\n\s+uses: (\S+)|uses: (\S+)|run: (.+)", chunk)
        key = next(g for g in m.groups() if g) if m else chunk[:40]
        out[key.strip()] = chunk
    return out


def archive_calls(text: str, cmd: str) -> list[list[str]]:
    """Every `python[3] tools/tic_archive.py <cmd> ...` in a step, as argv after the script name."""
    flat = text.replace("\\\n", " ")
    return [[m.group(1), *shlex.split(m.group(2))]
            for m in re.finditer(r"python3? tools/tic_archive\.py (" + cmd + r")\b([^;|&\n]*)", flat)]


def arg(argv: list[str], flag: str) -> list[str]:
    return [argv[i + 1] for i, t in enumerate(argv) if t == flag]


def puts(wf: str) -> list[list[str]]:
    job, name, _, _ = WORKFLOWS[wf]
    return archive_calls(steps(wf, job)[name], "put")


def tree(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def module_paths(rel: str) -> dict[str, str]:
    """Top-level NAME = os.path.join(...) constants of a module, as posix paths relative to the repo root, read
    from its source (ROOT is the repo root; a name defined earlier in the module may start the join)."""
    tree_ = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    names = {"ROOT": ""}
    for node in tree_.body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
            continue
        v = node.value
        if not (isinstance(v, ast.Call) and ast.unparse(v.func) == "os.path.join"):
            continue
        parts = []
        for a in v.args:
            if isinstance(a, ast.Name) and a.id in names:
                parts.append(names[a.id])
            elif isinstance(a, ast.Constant) and isinstance(a.value, str):
                parts.append(a.value)
            elif isinstance(a, ast.Attribute):          # G.OUT: another module's constant
                parts.append(f"<{ast.unparse(a)}>")
            else:
                break
        else:
            names[node.targets[0].id] = "/".join(p for p in parts if p)
    return names


def run_archive(argv: list[str], cwd: Path, store: Path, stamp: str = FIRST) -> int:
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


class TestSteps(unittest.TestCase):
    def test_each_workflow_puts_its_lanes_from_its_folders(self):
        for wf, (_, _, srcs, excludes) in WORKFLOWS.items():
            calls = puts(wf)
            self.assertEqual([arg(c, "--lane")[0] for c in calls], list(srcs), wf)
            for c in calls:
                lane = arg(c, "--lane")[0]
                self.assertEqual(arg(c, "--program"), [PROGRAM], wf)
                self.assertEqual(arg(c, "--src"), srcs[lane], wf)
                self.assertEqual(arg(c, "--exclude"), excludes[lane], wf)
                # Public files: archived as they are, so they match the public copies by hash.
                self.assertFalse([t for t in c if t.startswith(("--redact", "--include"))], wf)

    def test_last_after_a_failure_with_only_the_archive_token(self):
        for wf, (job, name, _, _) in WORKFLOWS.items():
            names = list(steps(wf, job))
            self.assertEqual(names[-1], name, wf)
            text = steps(wf, job)[name]
            self.assertRegex(text, r"if: \$\{\{ !cancelled\(\)", wf)
            self.assertIn("GH_TOKEN: ${{ secrets.TIC_ARCHIVE_TOKEN }}", text)
            self.assertNotIn("github.token", text)
            self.assertNotIn("|| true", text)
            self.assertNotIn("continue-on-error", text)
            self.assertIn('[ -z "$GH_TOKEN" ]', text)
            # The archive token reaches the archive step alone; the job's other steps keep the repository token.
            self.assertEqual(text_of(wf).count("secrets.TIC_ARCHIVE_TOKEN"), 1, wf)

    def test_bounded_in_time_inside_the_job(self):
        for wf, (job, _, _, _) in WORKFLOWS.items():
            jt = job_text(wf, job)
            (limit,) = re.findall(r"(?m)^    timeout-minutes: (\d+)\s*$", jt)
            st = steps(wf, job)
            own = {n: int(m) for n, s in st.items() for m in re.findall(r"(?m)^        timeout-minutes: (\d+)\s*$", s)}
            # Every step that may run long has its own limit, so it fails (not a cancelled job) and the archive
            # step still runs; the limits leave room for the setup steps.
            if wf != "deploy-site.yml":
                for n in st:
                    if n.startswith(("actions/", "pip install")):
                        continue
                    self.assertIn(n, own, f"{wf}: step {n!r} has no timeout-minutes")
                self.assertLessEqual(sum(own.values()) + 5, int(limit), wf)
            self.assertLessEqual(own[WORKFLOWS[wf][1]], 15, wf)

    def test_lane_names_are_unique_and_no_name_extends_another(self):
        lanes = [arg(c, "--lane")[0] for wf in WORKFLOWS for c in puts(wf)] + list(pc_archive.LANES) + ["milair"]
        self.assertEqual(len(lanes), len(set(lanes)), lanes)
        for a in lanes:
            for b in lanes:
                if a != b:
                    self.assertFalse(b.startswith(a + "-"), (a, b))     # tic_archive lists a lane by its prefix


class TestFoldersAreWhereTheJobsWrite(unittest.TestCase):
    def test_pnt_day_files(self):
        a, d = module_paths("pipeline/pnt_analysis.py"), module_paths("pipeline/daily_job.py")
        self.assertEqual((a["DAILY"], a["OUT"]), ("data/pnt/daily", "data/pnt/analysis"))
        self.assertEqual(d["SITE"], "data/pnt/site")          # map, hotspots, coverage and spoofing files
        src = (ROOT / "pipeline" / "daily_job.py").read_text(encoding="utf-8")
        self.assertIn("DAILY, ANALYSIS = A.DAILY, A.OUT", src)
        # The raw adsb.lol archive and the spoofing work folder are outside the lane.
        self.assertFalse(d["WORK"].startswith("data/pnt"))
        self.assertFalse(d["SPOOF"].startswith("data/pnt"))
        # Every upload in daily_job.py sends files from those three folders (or the .v<n> copies kept beside them).
        for line in re.findall(r'gh\("release", "upload".*', src):
            self.assertRegex(line, r"files|outputs\(day\)|SITE|dst", line)

    def test_declared_files(self):
        self.assertEqual(module_paths("pipeline/faa_gps_tests.py")["STORE"], "data/declared/faa_gps_tests.json")
        self.assertEqual(module_paths("pipeline/gnss_notams.py")["DIR"], "data/declared/gnss-notams")
        self.assertIn("gh release upload declared-data data/declared/faa_gps_tests.json",
                      steps("daily.yml", "process")["Announced GPS tests"])

    def test_space_weather_day_files_and_not_their_inputs(self):
        self.assertEqual(module_paths("tools/cosmic2_s4.py")["OUT"], "data/swx")
        self.assertEqual(module_paths("tools/ground_roti.py")["OUT"], "data/swx")
        self.assertEqual(module_paths("tools/cosmic2_daily.py")["OUT"], "data/cosmic2/daily")
        self.assertEqual(module_paths("tools/cosmic2_rfi.py")["DAYS_DIR"], "data/cosmic2/days")     # UCAR files
        self.assertEqual(module_paths("tools/station_cn0.py")["RAW"], "data/stations/raw")          # RINEX
        self.assertIn('os.path.join(out_dir, "raw")', (ROOT / "tools" / "cosmic2_s4.py").read_text(encoding="utf-8"))

    def test_feed_history_folder(self):
        st = steps("deploy-site.yml", "deploy")
        for name in ("Log the feed's changes (release feed-history)", "Save the feed history (release feed-history)"):
            self.assertIn('"$RUNNER_TEMP/feed-history"', st[name])
        self.assertIn("steps.feedhistory.outcome == 'success'", st[WORKFLOWS["deploy-site.yml"][1]])


# A run's files, by workflow: (path relative to the run folder, archived?)
RUN_FILES = {
    "daily.yml": [("data/pnt/daily/2026-11-20.parquet", True), ("data/pnt/daily/2026-11-20.hourly.parquet", True),
                  ("data/pnt/daily/2026-11-19.minute.parquet", True), ("data/pnt/analysis/2026-11-20.sbas.json", True),
                  ("data/pnt/site/2026-11-20.map.json", True), ("data/pnt/site/2026-11-20.spoof.json", True),
                  ("data/declared/faa_gps_tests.json", True), ("data/declared/gnss-notams/index.json", True),
                  ("data/raw/daily_job/2026-11-20/part.tar", False)],
    "cosmic2.yml": [("data/swx/2026-11-20.cosmic2-limb-s4.json", True), ("data/cosmic2/daily/2026-11-20.cosmic2.json", True),
                    ("data/swx/raw/2026-11-20.parquet", False), ("data/cosmic2/days/2026-324/link.nc", False)],
    "ground-roti.yml": [("data/swx/2026-11-20.ground-roti.json", True), ("data/stations/raw/2026/324/x.crx.gz", False)],
    "deploy-site.yml": [("feed-history/state.json", True), ("feed-history/log/2026/11/20.jsonl", True)],
}


def archived_name(wf: str, rel: str) -> str:
    """Where a run file sits in its lane's snapshot (the named sources put their files under name/)."""
    for c in puts(wf):
        for src in arg(c, "--src"):
            name, _, path = src.rpartition("=")
            path = path.replace("$RUNNER_TEMP/", "")
            if rel.startswith(path + "/"):
                rest = rel[len(path) + 1:]
                return arg(c, "--lane")[0], (f"{name}/{rest}" if name else rest)
    return None, None


class TestRoundTrip(unittest.TestCase):
    def test_every_run_file_restores_byte_for_byte_and_inputs_stay_out(self):
        for wf, files in RUN_FILES.items():
            with tempfile.TemporaryDirectory() as td:
                td = Path(td)
                run, store, runner_temp = td / "run", td / "store", td / "run"
                for i, (rel, _) in enumerate(files):
                    p = run / rel
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(f"{wf} {rel} {i}\n".encode() * 50)
                for c in puts(wf):
                    argv = [t.replace("$RUNNER_TEMP", str(runner_temp)) for t in c]
                    self.assertEqual(run_archive(argv, run, store), 0, wf)
                got = {}
                for lane in WORKFLOWS[wf][2]:
                    dest = td / "restored" / lane
                    self.assertEqual(run_archive(["restore", "--program", PROGRAM, "--lane", lane,
                                                  "--dest", str(dest)], run, store), 0)
                    got.update({(lane, k): v for k, v in tree(dest).items()})
                want = {}
                for rel, kept in files:
                    lane, name = archived_name(wf, rel)
                    if kept:
                        want[(lane, name)] = hashlib.sha256((run / rel).read_bytes()).hexdigest()
                    else:
                        self.assertNotIn((lane, name), got, f"{wf}: an input reached the archive: {rel}")
                self.assertEqual(got, want, wf)

    def test_a_replaced_day_file_stays_restorable(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            run, store = td / "run", td / "store"
            day = run / "data/swx/2026-11-20.ground-roti.json"
            day.parent.mkdir(parents=True)
            day.write_text('{"stations": 17}', encoding="utf-8")
            (put,) = puts("ground-roti.yml")
            self.assertEqual(run_archive(put, run, store, FIRST), 0)
            day.write_text('{"stations": 16}', encoding="utf-8")       # the two-day refresh remakes the day
            self.assertEqual(run_archive(put, run, store, SECOND), 0)
            (tag,) = [p.name for p in store.iterdir()]
            first = next(n.name for n in (store / tag).iterdir() if n.name.startswith(FIRST) and n.name.endswith(".files.json"))
            self.assertEqual(run_archive(["restore", "--program", PROGRAM, "--lane", "roti", "--dest", str(td / "a"),
                                          "--snapshot", first], run, store), 0)
            self.assertEqual(run_archive(["restore", "--program", PROGRAM, "--lane", "roti", "--dest", str(td / "b")],
                                         run, store), 0)
            self.assertEqual((td / "a/2026-11-20.ground-roti.json").read_text(), '{"stations": 17}')
            self.assertEqual((td / "b/2026-11-20.ground-roti.json").read_text(), '{"stations": 16}')


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
    body = []
    for line in text.split("run: |\n", 1)[1].split("\n"):
        if line.strip() and not line.startswith(" " * 10):
            break
        body.append(line[10:])
    return "\n".join(body) + "\n"


@unittest.skipUnless(BASH, "needs bash, as the runner has")
class TestArchiveStepShell(unittest.TestCase):
    """Each archive step's script under bash -eo pipefail, with python replaced by a stand-in that records the call
    and fails the lanes named in FAIL."""

    def case(self, wf: str, files: list[str], token: str, fail: str = "") -> tuple[int, list[str], str]:
        job, name, _, _ = WORKFLOWS[wf]
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            for f in files:
                (td / f).parent.mkdir(parents=True, exist_ok=True)
                (td / f).write_text("{}", encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME")}
            env.update(GH_TOKEN=token, CALLS=(td / "calls.txt").as_posix(), FAIL=fail, RUNNER_TEMP=td.as_posix())
            stub = ('python() { echo "$*" >> "$CALLS"; case " $* " in *" --lane $FAIL "*) [ -n "$FAIL" ] && return 1;; '
                    'esac; return 0; }\npython3() { python "$@"; }\n')
            r = subprocess.run([BASH, "--noprofile", "--norc", "-eo", "pipefail", "-c",
                                stub + run_script(steps(wf, job)[name])],
                               cwd=td, env=env, capture_output=True, text=True, timeout=60)
            calls = (td / "calls.txt").read_text().splitlines() if (td / "calls.txt").exists() else []
            lanes = [arg(shlex.split(c), "--lane")[0] for c in calls if c.startswith("tools/tic_archive.py put")]
            return r.returncode, lanes, r.stdout + r.stderr

    def test_a_run_that_made_nothing_archives_nothing_and_passes(self):
        for wf, files in (("daily.yml", []), ("daily.yml", ["data/raw/daily_job/x.tar"]),
                          ("cosmic2.yml", ["data/swx/raw/2026-11-20.parquet", "data/cosmic2/days/a.nc"]),
                          ("ground-roti.yml", ["data/stations/raw/x.gz"])):
            for token in ("t", ""):
                rc, lanes, out = self.case(wf, files, token)
                self.assertEqual((rc, lanes), (0, []), (wf, files, token))
                self.assertIn("nothing was archived", out)

    def test_files_without_the_token_fail_loudly(self):
        for wf, files in (("daily.yml", ["data/pnt/daily/a.parquet"]), ("cosmic2.yml", ["data/swx/a.json"]),
                          ("ground-roti.yml", ["data/swx/a.json"]), ("deploy-site.yml", [])):
            rc, lanes, out = self.case(wf, files, "")
            self.assertEqual((rc, lanes), (1, []), wf)
            self.assertIn("::error::secret TIC_ARCHIVE_TOKEN is not set", out)

    def test_each_lane_with_files_is_put(self):
        self.assertEqual(self.case("daily.yml", ["data/pnt/site/a.map.json", "data/declared/f.json"], "t")[:2],
                         (0, ["pnt", "declared"]))
        self.assertEqual(self.case("daily.yml", ["data/declared/f.json"], "t")[:2], (0, ["declared"]))
        self.assertEqual(self.case("daily.yml", ["data/pnt/daily/a.parquet"], "t")[:2], (0, ["pnt"]))
        self.assertEqual(self.case("cosmic2.yml", ["data/cosmic2/daily/a.cosmic2.json"], "t")[:2], (0, ["limbs4"]))
        self.assertEqual(self.case("ground-roti.yml", ["data/swx/a.ground-roti.json"], "t")[:2], (0, ["roti"]))
        self.assertEqual(self.case("deploy-site.yml", [], "t")[:2], (0, ["feedlog"]))

    def test_a_failed_lane_does_not_stop_the_other_and_fails_the_step(self):
        files = ["data/pnt/site/a.map.json", "data/declared/f.json"]
        for fail in ("pnt", "declared"):
            rc, lanes, out = self.case("daily.yml", files, "t", fail=fail)
            self.assertEqual((rc, lanes), (1, ["pnt", "declared"]), fail)
            self.assertIn("::error::a lane did not reach the private archive", out)
        for wf, files, lane in (("cosmic2.yml", ["data/swx/a.json"], "limbs4"),
                                ("ground-roti.yml", ["data/swx/a.json"], "roti"), ("deploy-site.yml", [], "feedlog")):
            self.assertNotEqual(self.case(wf, files, "t", fail=lane)[0], 0, wf)


if __name__ == "__main__":
    unittest.main()
