"""Migrated cross-tool review regressions."""

from __future__ import annotations

from pathlib import Path
import signal
import stat
import subprocess
import time

import pytest

from slopmeister.review.prompt import ReviewTarget
import slopmeister.review.run as review_run
from slopmeister.review.run import (
    CommandResult,
    owned_reviewer_runner,
    run_review,
    subprocess_runner,
)
from slopmeister.review.schema import (
    CrossToolReviewError,
    ReviewDirection,
)
from tests.support.fakes import fake_binary
from tests.support.review_helpers import (
    CLEAN_REVIEW_JSON,
    CONFIG,
    VALID_REVIEW_JSON,
    FakeReviewRuntime,
)


def test_permission_error_inside_invalid_json_is_not_retryable():
    fake = FakeReviewRuntime()
    fake.set_review_output('{"type":"result","is_error":true,"result":"Permission denied"}')
    with pytest.raises(CrossToolReviewError) as error:
        run_review(ReviewDirection.CODEX_TO_CLAUDE, ReviewTarget("Review.", "."), runner=fake)
    assert error.value.category.value == "CONTROL_FAILURE"


def test_owned_timeout_keeps_partial_output_and_stops_only_its_group(monkeypatch):
    class TimedOutReviewer:
        pid = 4321
        calls = 0
        returncode = None

        def communicate(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls < 3:
                raise subprocess.TimeoutExpired("claude", 1, output=b"partial evidence\n")
            self.returncode = -signal.SIGTERM
            return "partial evidence\n", ""

    process = TimedOutReviewer()
    sent = []
    monkeypatch.setenv("CROSS_TOOL_REVIEW_TIMEOUT_SECONDS", "1")
    monkeypatch.setattr(review_run, "_start_reviewer", lambda *_: process)
    monkeypatch.setattr(review_run, "group_members", lambda _: [])
    monkeypatch.setattr(
        review_run,
        "stop_owned_group",
        lambda child: sent.append((child.pid, signal.SIGTERM)),
    )
    with pytest.raises(CrossToolReviewError) as error:
        owned_reviewer_runner(["claude"])

    assert error.value.category.value == "TIMEOUT"
    assert error.value.process_stopped is True
    assert "partial evidence" in error.value.raw_stdout
    assert sent == [(process.pid, signal.SIGTERM)]


def test_subprocess_runner_converts_timeout_to_review_error(monkeypatch: pytest.MonkeyPatch):
    def timeout_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["claude"], timeout=1)

    monkeypatch.setattr(review_run.subprocess, "run", timeout_run)
    monkeypatch.setenv("CROSS_TOOL_REVIEW_TIMEOUT_SECONDS", "1")

    with pytest.raises(CrossToolReviewError, match="timed out after 1s"):
        subprocess_runner(["claude"])


@pytest.mark.parametrize(
    "value, match",
    [("soon", "must be an integer"), ("0", "must be >= 1"), ("-1", "must be >= 1")],
)
def test_subprocess_runner_rejects_invalid_timeout_env(
    value: str,
    match: str,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("CROSS_TOOL_REVIEW_TIMEOUT_SECONDS", value)

    with pytest.raises(CrossToolReviewError, match=match) as raised:
        subprocess_runner(["claude"])
    assert raised.value.category.value == "START_PRECONDITION"


def test_subprocess_runner_uses_list_argv_without_shell(monkeypatch: pytest.MonkeyPatch):
    seen: dict[str, object] = {}

    def completed_run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(review_run.subprocess, "run", completed_run)
    subprocess_runner(["git", "status"], env={"PATH": "/usr/bin"})

    assert seen["argv"] == ["git", "status"]
    assert "shell" not in seen["kwargs"]


def test_subprocess_runner_still_streams_stdin_text_when_provided(
    monkeypatch: pytest.MonkeyPatch,
):
    """The codex-to-claude direction sends its prompt over stdin; closing stdin
    unconditionally would truncate that prompt to nothing."""
    seen: dict[str, object] = {}

    def completed_run(argv, **kwargs):
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(review_run.subprocess, "run", completed_run)
    subprocess_runner(["claude"], stdin_text="review this")

    kwargs = seen["kwargs"]
    assert kwargs["input"] == "review this"
    assert "stdin" not in kwargs


def test_run_review_carries_the_security_lens_onto_the_result():
    """Escaping bug: rebuilding the result drops the Security Lens from the CLI gate."""
    fake = FakeReviewRuntime()
    fake.set_review_output(VALID_REVIEW_JSON)
    result = run_review(
        ReviewDirection.CODEX_TO_CLAUDE,
        ReviewTarget(prompt="Review.", cwd="."),
        runner=fake,
        env={},
        config=CONFIG,
    )
    assert result.security_lens.finding == 1
    assert result.security_lens.evidence == "The unvalidated JSON is a trust-boundary defect."


def test_run_review_cleans_secure_schema_file_after_review_command():
    seen: dict[str, object] = {}

    def runner(argv, *, cwd=None, env=None):
        argv_list = list(argv)
        schema_path = Path(argv_list[argv_list.index("--output-schema") + 1])
        seen["path"] = schema_path
        seen["exists_during_review"] = schema_path.is_file()
        seen["mode"] = stat.S_IMODE(schema_path.stat().st_mode)
        return CommandResult(returncode=0, stdout=CLEAN_REVIEW_JSON)

    run_review(
        ReviewDirection.CLAUDE_TO_CODEX,
        ReviewTarget(prompt="Review.", cwd="."),
        runner=runner,
        env={"PATH": "/usr/bin", "HOME": "/Users/tester"},
    )

    assert seen["exists_during_review"] is True
    assert seen["mode"] == 0o600
    assert isinstance(seen["path"], Path)
    assert not seen["path"].exists()


@pytest.mark.xdist_group("review-process-tree")
@pytest.mark.parametrize(
    ("script", "category"),
    [
        pytest.param(
            'printf "partial evidence\\n"\nsleep 6 &\n: > "$0.ready"\nexit 0',
            "TIMEOUT",
            id="timeout",
        ),
        pytest.param(
            "sleep 30 >/dev/null 2>&1 &\ndisown\nexit 0",
            "CONTROL_FAILURE",
            id="normal-exit",
        ),
    ],
)
def test_reviewer_stops_group_after_leader_already_exited(tmp_path, monkeypatch, script, category):
    tool = fake_binary(tmp_path, "claude", script)
    monkeypatch.setenv("CROSS_TOOL_REVIEW_TIMEOUT_SECONDS", "1" if category == "TIMEOUT" else "10")
    started = time.monotonic()
    if category == "TIMEOUT":
        ready = Path(f"{tool}.ready")

        def start_after_output(argv, options, start=review_run._start_reviewer):
            nonlocal started
            process = start(argv, options)
            deadline = time.monotonic() + 5
            try:
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert ready.exists(), "fake reviewer did not print before timeout"
            except BaseException:
                review_run.stop_owned_group(process)
                raise
            started = time.monotonic()
            return process

        monkeypatch.setattr(review_run, "_start_reviewer", start_after_output)
    with pytest.raises(CrossToolReviewError) as error:
        owned_reviewer_runner([str(tool)])
    assert error.value.category.value == category
    assert error.value.process_stopped is True
    if category == "TIMEOUT":
        assert "partial evidence" in error.value.raw_stdout
    assert time.monotonic() - started < 5
