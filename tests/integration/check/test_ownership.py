"""Test processes are found by their run folder and stopped when that run ends."""

import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from unittest.mock import Mock

import pytest

from slopmeister.check import cli, jobs, ownership, scheduler

ROOT = Path(__file__).resolve().parents[3]
SLEEPER = (
    "import signal, sys, time\nfrom pathlib import Path\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "Path(sys.argv[1]).touch()\ntime.sleep(60)\n"
)
ENDED_OWNER = {"pid": 999_999_999, "identity": "1:1"}
LIVE_OWNER = {"pid": os.getpid(), "identity": ownership.identity(os.getpid())}
JOB = """
import os, signal, subprocess, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, {root!r})
from slopmeister.check import jobs
ready = Path({ready!r})
env = os.environ
if {nested!r}:
    env = jobs._environment(Path(tempfile.mkdtemp(prefix='htr.', dir={nested!r})))
helper = subprocess.Popen(
    [sys.executable, '-c', {sleeper!r}, str(ready)], env=env, start_new_session=True
)
while not ready.exists(): time.sleep(.01)
Path({pid_file!r}).write_text(str(helper.pid))
if {outcome!r} == 'failure': raise SystemExit(7)
if {outcome!r} == 'killed': os.kill(os.getpid(), signal.SIGKILL)
if {outcome!r} == 'timeout': time.sleep(60)
"""


def sleeper(tmp_path, name, root=None, *args, key=ownership.ROOT_VARIABLE):
    ready = tmp_path / f"{name}.ready"
    env = {key: value for key, value in os.environ.items() if key != ownership.ROOT_VARIABLE}
    if root is not None:
        env[key] = str(root)
    process = subprocess.Popen(
        [sys.executable, "-c", SLEEPER, str(ready), *args], env=env, start_new_session=True
    )
    deadline = time.monotonic() + 5
    while not ready.exists():
        assert process.poll() is None and time.monotonic() < deadline
        time.sleep(0.01)
    return process


def kill(*processes):
    for process in processes:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        process.wait(timeout=5)


def kill_pid(path):
    if path.exists():
        with contextlib.suppress(ProcessLookupError):
            os.kill(int(path.read_text()), signal.SIGKILL)


def owned_folder(root, name, owner):
    folder = root / name
    folder.mkdir(mode=0o700)
    (folder / "owner.json").write_text(json.dumps(owner))
    return folder


def run_job(tmp_path, outcome, nested=""):
    pid_file = tmp_path / f"{outcome}.pid"
    code = JOB.format(
        root=str(ROOT),
        ready=str(tmp_path / f"{outcome}.ready"),
        nested=nested,
        sleeper=SLEEPER,
        pid_file=str(pid_file),
        outcome=outcome,
    )
    settings = scheduler.Settings(1, tmp_path, tmp_path / "logs")
    result = scheduler.run_checks([jobs.Check(outcome, (sys.executable, "-c", code))], settings)
    return result["results"][0], pid_file


@pytest.mark.parametrize(
    ("outcome", "expected"),
    (("pass", 0), ("failure", 7), ("killed", -signal.SIGKILL), ("timeout", jobs.EXIT_TIMEOUT)),
)
def test_job_end_stops_detached_sigterm_ignoring_helper(
    tmp_path, run_root, monkeypatch, outcome, expected
):
    """Escaping bug: a helper in its own session that ignores SIGTERM outlived its job."""
    monkeypatch.setattr(jobs, "CHECK_TIMEOUT", 3)
    unrelated = sleeper(tmp_path, "unrelated")
    pid_file = tmp_path / f"{outcome}.pid"
    try:
        row, pid_file = run_job(tmp_path, outcome)
        assert row["returncode"] == expected
        assert ownership.identity(int(pid_file.read_text())) is None
        assert not Path(row["owner"]["root"]).exists()
        assert unrelated.poll() is None
    finally:
        kill_pid(pid_file)
        kill(unrelated)


def test_outer_job_end_stops_a_nested_gates_helper(tmp_path, run_root):
    """Escaping bug: a gate run inside a test replaced the marker and hid its jobs."""
    pid_file = tmp_path / "pass.pid"
    try:
        row, pid_file = run_job(tmp_path, "pass", nested=str(run_root))
        assert row["returncode"] == 0
        assert ownership.identity(int(pid_file.read_text())) is None
    finally:
        kill_pid(pid_file)


def test_clean_spares_a_live_gates_run_and_unrelated_processes(tmp_path, run_root):
    """Escaping bug: the start cleanup killed a running test or trusted a spoofed argument."""
    live = owned_folder(run_root, "htr.live", LIVE_OWNER)
    ended = owned_folder(run_root, "htr.ended", ENDED_OWNER)
    running = sleeper(tmp_path, "running", live)
    leftover = sleeper(tmp_path, "leftover", ended, key="TMPDIR")
    spoof = sleeper(tmp_path, "spoof", None, f"{ownership.ROOT_VARIABLE}={ended}")
    unrelated = sleeper(tmp_path, "unrelated")
    try:
        assert ownership.clean() == (1, 1)
        assert leftover.wait(timeout=5) == -signal.SIGKILL
        assert all(p.poll() is None for p in (running, spoof, unrelated))
        assert live.exists() and not ended.exists()
    finally:
        kill(running, leftover, spoof, unrelated)


def test_clean_keeps_foreign_live_and_symlinked_folders(tmp_path, run_root):
    """Escaping bug: deletion trusted a name, ignored a live gate or followed a link."""
    foreign = run_root / "htr.foreign"
    foreign.mkdir(mode=0o700)
    live = owned_folder(run_root, "htr.live", LIVE_OWNER)
    target = owned_folder(tmp_path, "htr.target", ENDED_OWNER)
    (run_root / "htr.link").symlink_to(target)
    linked = run_root / "htr.linked-owner"
    linked.mkdir(mode=0o700)
    (linked / "owner.json").symlink_to(target / "owner.json")
    ended = owned_folder(run_root, "htr.ended", ENDED_OWNER)
    assert ownership.clean() == (0, 1)
    assert foreign.exists() and live.exists() and linked.exists() and target.exists()
    assert (run_root / "htr.link").is_symlink() and not ended.exists()


def test_stop_skips_a_reused_pid(tmp_path):
    """Escaping bug: a PID reused between the scan and the signal was killed."""
    stranger = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert ownership.stop_processes([(stranger.pid, "1:1")]) == []
        assert stranger.poll() is None
    finally:
        kill(stranger)


def test_gate_passes_and_cleans_on_a_polluted_machine(tmp_path, run_root, monkeypatch):
    """Escaping bug: another run's leftovers failed the gate instead of being cleared."""
    ended = owned_folder(run_root, "htr.ended", ENDED_OWNER)
    leftover = sleeper(tmp_path, "leftover", ended / "pytest-of-someone")
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli.catalogue, "catalogue", lambda *_: [jobs.Check("quick", ("true",))])
    try:
        assert cli.main(["--ci", "--jobs", "1", "--report", str(tmp_path / "report.json")]) == 0
        assert leftover.wait(timeout=5) == -signal.SIGKILL
        assert not ended.exists()
    finally:
        kill(leftover)


def test_clean_flag_runs_only_the_cleanup(tmp_path, run_root, monkeypatch, capsys):
    """Escaping bug: agents had no way to clear leftovers without running the whole gate."""
    ended = owned_folder(run_root, "htr.ended", ENDED_OWNER)
    monkeypatch.setattr(cli.catalogue, "catalogue", lambda *_: pytest.fail("gate ran"))
    assert cli.main(["--clean"]) == 0
    assert not ended.exists() and "removed 1" in capsys.readouterr().out


@pytest.mark.parametrize(("original", "expected"), ((0, 1), (7, 7)))
def test_cleanup_failure_does_not_hide_the_original_result(
    tmp_path, run_root, monkeypatch, original, expected
):
    """Escaping bug: a failed stop turned a pass green or hid the job's own output."""
    monkeypatch.setattr(
        jobs.ownership,
        "stop_run",
        lambda root: (_ for _ in ()).throw(RuntimeError(f"test processes remain: {root}")),
    )
    code = f"print('original {original}'); raise SystemExit({original})"
    settings = scheduler.Settings(1, tmp_path, tmp_path / "logs")
    result = scheduler.run_checks([jobs.Check("cleanup", (sys.executable, "-c", code))], settings)
    row = result["results"][0]
    log = Path(row["log"]).read_text()
    assert row["returncode"] == expected
    assert log.index(f"original {original}") < log.index("cleanup failed:")
    assert Path(row["owner"]["root"]).exists(), "a folder with surviving processes is kept"


def test_timeout_stop_failure_remains_a_reportable_result(tmp_path, monkeypatch):
    """Escaping bug: a stop error replaced the timeout row and aborted the gate."""

    class TimedOut:
        pid = 123

    stream = io.StringIO()
    context = jobs.Context(tmp_path, tmp_path)
    monkeypatch.setattr(jobs.subprocess, "Popen", lambda *args, **kwargs: TimedOut())

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("fixture", jobs.CHECK_TIMEOUT)

    def fail_stop(process, *, anchored=False):
        assert anchored is True
        raise RuntimeError("stuck")

    monkeypatch.setattr(jobs, "wait_unreaped", timeout)
    monkeypatch.setattr(jobs, "stop_group", fail_stop)
    subject = jobs.Check("timeout", ("true",))
    assert jobs._run_child(jobs.Launch(subject, {}, stream), context) == jobs.EXIT_TIMEOUT
    assert "cleanup failed: stuck" in stream.getvalue()


def test_interrupted_removal_keeps_the_folder_provable(run_root, monkeypatch):
    """Escaping bug: a delete that stopped midway had removed owner.json and stranded the rest."""
    ended = owned_folder(run_root, "htr.ended", ENDED_OWNER)
    (locked := ended / "pytest-of-x").mkdir()
    (locked / "data").write_text("x")
    with monkeypatch.context() as patch:
        patch.setattr(ownership, "remove_tree", Mock(side_effect=PermissionError("interrupted")))
        with pytest.raises(PermissionError):
            ownership.clean()
        assert (ended / "owner.json").exists()
    assert ownership.clean() == (0, 1) and not ended.exists()
