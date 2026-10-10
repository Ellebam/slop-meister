"""Reviewer subprocess execution primitives."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import os
import subprocess

from slopmeister.check import jobs
from slopmeister.review.config import command_timeout_seconds
from slopmeister.review.redact import redact, sanitize_text
from slopmeister.review.schema import CrossToolReviewError, ReviewErrorCategory

CHILD_ENV_KEYS = ("PATH", "HOME", "USER", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE")
STDERR_TAIL_LINES = 20
STDERR_LINE_CHARS = 300
_Popen = subprocess.Popen


class _AnchoredPopen(_Popen):
    def wait(self, timeout=None):
        if self.returncode is not None:
            return self.returncode
        limit = jobs.CHECK_TIMEOUT if timeout is None else timeout
        jobs.wait_unreaped(self, limit)
        return 0

    def reap(self, timeout=None):
        return _Popen.wait(self, timeout)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    process_stopped: bool = False


def _text(value: str | bytes | None) -> str:
    value = value or ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value


def _finish_output(process: subprocess.Popen, partial: tuple) -> tuple[str, str]:
    try:
        streams = process.communicate(timeout=jobs.GROUP_STOP_TIMEOUT)
    except subprocess.TimeoutExpired as error:
        streams = (error.stdout, error.stderr)
    stdout, stderr = (
        _text(now) or _text(before) for now, before in zip(streams, partial, strict=True)
    )
    return stdout, stderr


def stderr_tail(text: str) -> tuple[str, ...]:
    """Redact the whole text before the cut, so a secret the cut splits cannot survive."""
    lines = [line for line in redact(text).splitlines() if line.strip()]
    return tuple(sanitize_text(line)[:STDERR_LINE_CHARS] for line in lines[-STDERR_TAIL_LINES:])


def stderr_tail_log(tail: tuple[str, ...] | None) -> list[str]:
    if tail is None:
        return []
    if not tail:
        return ["stderr tail, empty"]
    return [f"stderr tail, last {len(tail)} lines", *(f"stderr| {line}" for line in tail)]


def group_members(group_id: int) -> list[str]:
    """Name each live member from one snapshot, so a refused group is diagnosable after its stop."""
    rows = subprocess.run(
        ["ps", "-ww", "-axo", "pid=,pgid=,stat=,command="],
        capture_output=True,
        text=True,
        check=True,
        timeout=jobs.PROCESS_INSPECT_TIMEOUT,
    ).stdout.splitlines()
    members = []
    for row in rows:
        pid, pgid, status, *command = row.split(None, 3)
        if int(pgid) == group_id and not status.startswith("Z"):
            members.append(redact(" ".join([pid, *command])))
    return members


def project_child_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Project only the seven process keys required by local reviewer CLIs."""
    parent = os.environ if env is None else env
    return {key: parent[key] for key in CHILD_ENV_KEYS if key in parent}


def subprocess_runner(argv: Sequence[str], **options) -> CommandResult:
    cwd, env, stdin_text = (options.get(name) for name in ("cwd", "env", "stdin_text"))
    stdin = {"input": stdin_text} if stdin_text is not None else {"stdin": subprocess.DEVNULL}
    try:
        completed = subprocess.run(
            list(argv),
            cwd=cwd,
            env=dict(env) if env is not None else None,
            check=False,
            capture_output=True,
            text=True,
            timeout=command_timeout_seconds(),
            **stdin,
        )
    except OSError as error:
        command = argv[0] if argv else "command"
        raise CrossToolReviewError(
            f"{command} could not start: {error}",
            category=ReviewErrorCategory.START_PRECONDITION,
        ) from error
    except subprocess.TimeoutExpired as error:
        command = argv[0] if argv else "command"
        raise CrossToolReviewError(
            f"{command} timed out after {command_timeout_seconds()}s",
            category=ReviewErrorCategory.TIMEOUT,
        ) from error
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)
