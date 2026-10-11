"""Reviewer timeout cleanup reports deterministic process-control outcomes."""

import contextlib
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest

from slopmeister.check import jobs
import slopmeister.review.run as review_run
from slopmeister.review.run import owned_reviewer_runner, subprocess_runner
from slopmeister.review.schema import CrossToolReviewError

FAST_FORK_CHILD = (
    "import subprocess, sys, time\n"
    "from pathlib import Path\n"
    "pids = Path(sys.argv[1]); deadline = time.monotonic() + 1\n"
    "while time.monotonic() < deadline:\n"
    " child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
    " with pids.open('a') as stream: stream.write(str(child.pid) + '\\n')\n"
    "time.sleep(30)\n"
)
LEFTOVER_ARGS = [
    "-c",
    "import time; time.sleep(30)",
    "marker-346",
    "API_KEY=hunter2hunter2",
    "https://u:hunter3hunter3@example.invalid/r",
    "--token",
    "hunter5hunter5",
]


def reviewer(tmp_path: Path, body: str) -> Path:
    tool = tmp_path / "claude"
    tool.write_text(f"#!{sys.executable}\n{body}")
    tool.chmod(0o755)
    return tool


def test_non_reaping_wait_preserves_an_expired_zero_timeout(monkeypatch):
    process = type("Process", (), {"returncode": None})()
    seen = []
    monkeypatch.setattr(jobs, "wait_unreaped", lambda _process, timeout: seen.append(timeout))
    assert review_run._AnchoredPopen.wait(process, 0) == 0
    assert seen == [0]


def test_subprocess_runner_isolates_child_stdin_when_no_input_is_streamed(
    monkeypatch: pytest.MonkeyPatch,
):
    """A child that inherits an agent harness's stdin never sees EOF and hangs
    until the timeout, discarding the whole review — so stdin must be closed."""
    seen: dict[str, object] = {}

    def completed_run(argv, **kwargs):
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(review_run.subprocess, "run", completed_run)
    subprocess_runner(["codex", "exec"])

    kwargs = seen["kwargs"]
    assert kwargs["stdin"] == subprocess.DEVNULL
    # `input=` and `stdin=` together raise ValueError in subprocess.run.
    assert "input" not in kwargs


def stop_recorded(pids: list[int]) -> None:
    for pid in pids:
        if jobs.ownership.identity(pid):
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)


def test_timeout_partial_output_survives_stop_retries_that_miss_their_window(monkeypatch):
    class TimedOutReviewer:
        pid = 4321

        def communicate(self, *_args, **_kwargs):
            raise subprocess.TimeoutExpired("claude", 1, output=b"partial evidence\n")

    monkeypatch.setenv("CROSS_TOOL_REVIEW_TIMEOUT_SECONDS", "1")
    monkeypatch.setattr(review_run, "_start_reviewer", lambda *_: TimedOutReviewer())
    monkeypatch.setattr(review_run, "stop_owned_group", lambda _: None)
    monkeypatch.setattr(review_run, "group_members", lambda _: [])
    with pytest.raises(CrossToolReviewError) as error:
        owned_reviewer_runner(["claude"])
    assert error.value.process_stopped is True
    assert "partial evidence" in error.value.raw_stdout


def test_unexpected_reviewer_exception_still_stops_the_owned_group(monkeypatch):
    """Escaping bug: an exceptional runner exit left its reviewer group alive."""

    class BrokenReviewer:
        pid = 4321

        def communicate(self, *_args, **_kwargs):
            raise KeyboardInterrupt

    process = BrokenReviewer()
    stopped = []
    monkeypatch.setattr(review_run, "_start_reviewer", lambda *_: process)
    monkeypatch.setattr(review_run, "_stop_reviewer", lambda *args: stopped.append(args))
    with pytest.raises(KeyboardInterrupt):
        owned_reviewer_runner(["claude"])
    assert stopped == [(process,)]


def test_group_inspection_failure_stops_the_reviewer_and_reports_control_failure(monkeypatch):
    """Escaping bug: failed process inspection bypassed reviewer cleanup."""

    class Reviewer:
        pid = 4321

        def communicate(self, *_args, **_kwargs):
            return "", ""

    process = Reviewer()
    stopped = []
    monkeypatch.setattr(review_run, "_start_reviewer", lambda *_: process)
    monkeypatch.setattr(
        review_run,
        "group_members",
        lambda *_: (_ for _ in ()).throw(subprocess.TimeoutExpired("ps", 2)),
    )
    monkeypatch.setattr(review_run, "_stop_reviewer", lambda *args: stopped.append(args))
    with pytest.raises(CrossToolReviewError) as raised:
        owned_reviewer_runner(["claude"])
    assert raised.value.category.value == "CONTROL_FAILURE"
    assert raised.value.process_stopped is True
    assert stopped == [(process,)]


@pytest.mark.parametrize("denied", [signal.SIGTERM, signal.SIGKILL])
def test_stop_group_maps_permission_error_from_each_signal_to_review_error(monkeypatch, denied):
    class StubbornReviewer:
        pid = 4321

    def deny(_process):
        raise PermissionError(f"{denied.name}: denied by fixture")

    monkeypatch.setattr(review_run, "stop_owned_group", deny)
    with pytest.raises(CrossToolReviewError) as raised:
        review_run._stop_reviewer(StubbornReviewer())
    assert raised.value.category.value == "CONTROL_FAILURE"
    assert f"group {StubbornReviewer.pid}" in str(raised.value)
    assert signal.Signals(denied).name in str(raised.value)


@pytest.mark.xdist_group("review-process-tree")
def test_reviewer_fast_fork_cleanup_preserves_an_unrelated_process(tmp_path):
    """Escaping bug: a descendant forked between the final snapshot and signal."""
    pids = tmp_path / "pids"
    tool = reviewer(
        tmp_path,
        "import subprocess, sys, time\nfrom pathlib import Path\n"
        f"pids = Path({str(pids)!r})\n"
        f"subprocess.Popen([sys.executable, '-c', {FAST_FORK_CHILD!r}, {str(pids)!r}], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "deadline = time.monotonic() + 5\n"
        "while not pids.exists() and time.monotonic() < deadline: time.sleep(.01)\n"
        "if not pids.exists(): raise RuntimeError('forker did not start')\n",
    )
    foreign = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    foreign_birth = jobs.ownership.identity(foreign.pid)
    descendants = []
    try:
        with pytest.raises(CrossToolReviewError) as raised:
            owned_reviewer_runner([str(tool)])
        descendants = [int(pid) for pid in pids.read_text().splitlines()]
        assert raised.value.category.value == "CONTROL_FAILURE"
        assert raised.value.process_stopped is True
        assert descendants and all(jobs.ownership.identity(pid) is None for pid in descendants)
        assert foreign.poll() is None and jobs.ownership.identity(foreign.pid) == foreign_birth
    finally:
        stop_recorded(descendants)
        foreign.terminate()
        foreign.wait(timeout=5)


@pytest.mark.xdist_group("review-process-tree")
def test_reviewer_live_group_refusal_names_each_member_command(tmp_path):
    """Escaping bug: the refusal named only the group id, so every block was diagnosed by hand."""
    pid_file = tmp_path / "child.pid"
    tool = reviewer(
        tmp_path,
        "import subprocess, sys\n"
        f"child = subprocess.Popen([sys.executable, *{LEFTOVER_ARGS!r}], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n",
    )
    child = []
    try:
        with pytest.raises(CrossToolReviewError) as raised:
            owned_reviewer_runner([str(tool)])
        child.append(int(pid_file.read_text()))
        message = str(raised.value)
        assert f"{child[0]} " in message and "marker-346" in message
        assert "hunter2hunter2" not in message and "hunter3hunter3" not in message
        assert "hunter5hunter5" not in message
        assert raised.value.process_stopped is True
        assert jobs.ownership.identity(child[0]) is None
    finally:
        stop_recorded(child)
