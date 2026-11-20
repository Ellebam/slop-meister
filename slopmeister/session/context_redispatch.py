"""Read context recovery eligibility without sending mail or starting a worker."""

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any

from slopmeister.session import launch_identity

COMPACTIONS = 3
MAX_LINE_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
TIMEOUT = 30
ROUTE = re.compile(r"run:run_[a-zA-Z0-9_-]+")
MARKER = "Context redispatch request: "
MANAGER_MARK = "This session is a manager."


class ObservationError(ValueError):
    """A static diagnostic safe to report without external exception data."""


def worker_action(
    count: int | None, sent: bool, questions: bool, windows: bool, *, manager: bool = False
) -> str:
    if count is None:
        return "unknown"
    if count < COMPACTIONS:
        return "continue"
    if sent:
        return "already-requested"
    # A manager nearly always holds an operator question, and its saved handoff carries it.
    return "request" if windows and (questions or manager) else "protected"


def manager(workspace: Path) -> bool:
    """The launcher delivers the manager mark in the session's own instruction copy."""
    for name in ("CLAUDE.md", "AGENTS.md"):
        try:
            descriptor = launch_identity.open_nofollow(workspace / name)
        except OSError:
            continue
        with os.fdopen(descriptor, "rb") as stream:
            if MANAGER_MARK.encode() in stream.read(MAX_OUTPUT_BYTES):
                return True
    return False


def _native_record(record: dict, identity: dict) -> tuple[bool, bool]:
    if identity["tool"] == "codex":
        payload = record.get("payload", {})
        named = record.get("type") == "session_meta"
        valid = (
            payload.get("id") == identity["session_id"]
            and payload.get("cwd") == identity["workspace"]
        )
        if named and not valid:
            raise ObservationError("native identity mismatch")
        return named, record.get("type") == "compacted"
    if record.get("isSidechain"):
        return False, False
    named = (
        record.get("sessionId") == identity["session_id"]
        and record.get("cwd") == identity["workspace"]
    )
    if record.get("sessionId", identity["session_id"]) != identity["session_id"]:
        raise ObservationError("native identity mismatch")
    return named, record.get("type") == "system" and record.get("subtype") == "compact_boundary"


def compactions(path: Path, identity: dict) -> int:
    count, named = 0, False
    deadline = time.monotonic() + TIMEOUT
    with os.fdopen(launch_identity.open_nofollow(path), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not launch_identity.regular_file(info, owned=True):
            raise ObservationError("native log is not an owned regular file")
        # Native logs grow across compactions, so bound time and each read, not total size.
        while line := stream.readline(MAX_LINE_BYTES + 1):
            if time.monotonic() > deadline:
                raise ObservationError("native log read timed out")
            if len(line) > MAX_LINE_BYTES:
                raise ObservationError("native record exceeds size limit")
            try:
                record = json.loads(line)
            except ValueError as error:
                raise ObservationError("unknown native record") from error
            if not isinstance(record, dict):
                raise ObservationError("unknown native record")
            seen, compacted = _native_record(record, identity)
            named = named or seen
            count += int(compacted)
    if not named:
        raise ObservationError("native identity mismatch")
    return count


def _log(identity: dict) -> Path:
    session = identity["session_id"]
    if identity["tool"] == "codex":
        root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        matches = list((root / "sessions").rglob(f"*{session}.jsonl"))
    elif identity["tool"] == "claude":
        root = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
        matches = list((root / "projects").glob(f"*/{session}.jsonl"))
    else:
        raise ObservationError("unsupported native tool")
    if len(matches) != 1:
        raise ObservationError("unknown native log")
    return matches[0]


def _sent(workspace: Path, session: str) -> bool:
    notes = workspace / f"{workspace.name}-NOTES.md"
    if not notes.exists() and not notes.is_symlink():
        return False
    with os.fdopen(launch_identity.open_nofollow(notes), "rb") as stream:
        if not launch_identity.regular_file(os.fstat(stream.fileno()), owned=True):
            raise ObservationError("unknown task notes")
        # Restart essentials, including this marker, belong in the first 8 KB.
        return (MARKER + session).encode() in stream.read(8192)


def inspect(workspace: Path, *, questions_clear: bool, windows_clear: bool) -> dict:
    identity = launch_identity.read(workspace)
    count = compactions(_log(identity), identity)
    sent = _sent(workspace, identity["session_id"])
    managing = manager(workspace)
    return {
        "task": identity["task"],
        "tool": identity["tool"],
        "session_id": identity["session_id"],
        "compactions": count,
        "manager": managing,
        "action": worker_action(count, sent, questions_clear, windows_clear, manager=managing),
    }


@dataclass(frozen=True)
class Request:
    workspace: str
    tool: str
    session_id: str
    dispatcher: str
    owner: str
    receiver: str
    handoff: bool
    questions_clear: bool
    windows_clear: bool
    manager: bool = False


def _integer(value: Any) -> bool:
    return type(value) is int and value >= 0


def _meter(meter: dict, request: Request) -> str | None:
    known = (
        _integer(meter.get("schema"))
        and meter.get("schema") == 1
        and meter.get("available") is True
        and meter.get("complete") is True
        and meter.get("live") is True
        and _integer(meter.get("malformed"))
        and meter.get("malformed") == 0
    )
    if not known or not isinstance(meter.get("sessions"), list):
        return "unavailable-meter"
    rows = [
        s
        for s in meter["sessions"]
        if isinstance(s, dict)
        and s.get("sessionId") == request.session_id
        and s.get("client") == request.tool
        and s.get("workspace") == Path(request.workspace).name
    ]
    if len(rows) != 1:
        return "unknown-session"
    row = rows[0]
    figures = row.get("context", {})
    compaction = row.get("compactions", {})
    count = compaction.get("count") if isinstance(compaction, dict) else None
    valid = (
        isinstance(figures, dict)
        and all(_integer(figures.get(k)) for k in ("current", "peak", "window"))
        and figures.get("window", 0) > 0
        and figures["peak"] >= figures["current"]
        and _integer(count)
        and isinstance(row.get("model"), str)
        and bool(row["model"].strip())
    )
    if not valid:
        return "unknown-figures"
    return "below-threshold" if count < COMPACTIONS else None


def _wait(status: dict, request: Request) -> str | None:
    result = status.get("result", {})
    if (
        status.get("ok") is not True
        or not isinstance(result, dict)
        or result.get("truncated") is not False
        or not isinstance(result.get("worktrees"), list)
    ):
        return "unavailable-host"
    rows = [
        w for w in result["worktrees"] if isinstance(w, dict) and w.get("path") == request.workspace
    ]
    groups = [w.get("agents") for w in rows]
    agents = [agent for group in groups if isinstance(group, list) for agent in group]
    if (
        not all(isinstance(group, list) for group in groups)
        or len(agents) != 1
        or not isinstance(agents[0], dict)
    ):
        return "unknown-agent"
    agent = agents[0]
    if agent.get("agentType") != request.tool or agent.get("state") != "done":
        return "turn-not-ended"
    return "wait-not-clear" if "agentWait" not in agent or agent["agentWait"] is not None else None


def verify(meter: dict, status: dict, request: Request) -> str:
    if not all(ROUTE.fullmatch(r) for r in (request.dispatcher, request.owner, request.receiver)):
        return "unknown-route"
    if request.receiver not in (request.owner, request.dispatcher):
        return "wrong-recovery-owner"
    checks = (
        (request.handoff, "handoff-not-verified"),
        (request.questions_clear or request.manager, "question-not-clear"),
        (request.windows_clear, "window-not-clear"),
    )
    failure = next((reason for passed, reason in checks if not passed), None)
    if failure or (failure := _meter(meter, request)) or (failure := _wait(status, request)):
        return failure
    return "redispatch" if request.receiver == request.owner else "forward"


def _json_command(argv: list[str]) -> dict:
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=TIMEOUT)
    if result.returncode or len(result.stdout) > MAX_OUTPUT_BYTES:
        raise ObservationError("observation unavailable")
    data = json.loads(result.stdout)
    if not isinstance(data, dict):
        raise ObservationError("unknown observation")
    return data


def observe(host: str | None) -> tuple[dict, dict]:
    if sys.platform != "darwin":
        raise ObservationError("Context Meter verification runs on the Mac")
    if host is not None and not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", host):
        raise ObservationError("unknown host")
    plugins = Path.home() / "Library/Application Support/orca/plugins/ellebam.context-meter"
    readers = list(plugins.glob("*/src/reader.mjs"))
    if not readers:
        raise ObservationError("Context Meter unavailable")
    reader = max(readers, key=lambda p: p.stat().st_mtime)
    meter = _json_command(
        ["node", str(reader), "--json", "--live", *(["--host", host] if host else [])]
    )
    orca = "/Applications/Orca.app/Contents/Resources/bin/orca"
    status = _json_command(
        [
            orca,
            "worktree",
            "ps",
            "--json",
            "--agent-wait",
            *(["--environment", host] if host else []),
        ]
    )
    return meter, status


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("inspect", "verify"))
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--questions-clear", action="store_true")
    parser.add_argument("--windows-clear", action="store_true")
    parser.add_argument("--handoff-checked", action="store_true")
    parser.add_argument("--manager", action="store_true", help="verify only: sender is a manager")
    for name in ("tool", "session-id", "dispatcher-run", "owner-run", "self-run", "host"):
        parser.add_argument("--" + name)
    return parser


def main(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.mode == "inspect":
            output = inspect(
                args.workspace.resolve(),
                questions_clear=args.questions_clear,
                windows_clear=args.windows_clear,
            )
        else:
            request = Request(
                str(args.workspace if args.host else args.workspace.resolve()),
                args.tool,
                args.session_id,
                args.dispatcher_run or "",
                args.owner_run or "",
                args.self_run or "",
                args.handoff_checked,
                args.questions_clear,
                args.windows_clear,
                args.manager,
            )
            output = {"action": verify(*observe(args.host), request)}
    except ObservationError as error:
        output = {"action": "unknown", "reason": str(error)}
    except OSError, ValueError, TypeError, AttributeError, subprocess.TimeoutExpired:
        output = {"action": "unknown", "reason": "context observation unavailable"}
    print(json.dumps(output))
    return (
        0
        if output["action"] in ("continue", "request", "already-requested", "redispatch", "forward")
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
