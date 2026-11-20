"""Read the existing local session inventory without touching agent state."""

import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

from slopmeister import paths
from slopmeister.errors import SlopmeisterError
from slopmeister.launch import terminal
from slopmeister.quality import identifiers
from slopmeister.session import launch_identity
from slopmeister.session.service_actions.process import Run, invoke
from slopmeister.threads.timing import claude, codex, history, progress
from slopmeister.threads.timing.events import Session
from slopmeister.threads.timing.stages import RANK

TIMEOUT = 15
NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}")


def inventory() -> list[dict]:
    env = os.environ.copy()
    for key in ("ORCA_ENVIRONMENT", "ORCA_PAIRING_CODE"):
        env.pop(key, None)
    output = invoke(Run([terminal.binary(), "terminal", "list", "--json"], env, timeout=TIMEOUT))
    envelope = json.loads(output)
    data = envelope.get("result", {})
    if envelope.get("ok") is not True or data.get("truncated") is not False:
        raise SlopmeisterError("local session inventory incomplete")
    if not isinstance(data.get("terminals"), list):
        raise SlopmeisterError("local session inventory invalid")
    return [entry for entry in data["terminals"] if _running(entry)]


def _running(entry: dict) -> bool:
    if not isinstance(entry, dict):
        raise ValueError("invalid terminal")
    return (
        entry.get("agentIdentity") in ("claude", "codex")
        and entry.get("executionHostId") == "local"
        and entry.get("connected") is not False
        and entry.get("orphaned") is not True
    )


def _identity(workspace: Path, tool: str) -> dict:
    source = launch_identity.path(workspace)
    if source.stat().st_size > 8192:
        raise ValueError("invalid launcher identity")
    value = launch_identity.private_json(source, "launcher identity")
    valid = (
        value.get("version") == 1
        and value.get("state") == "confirmed"
        and value.get("workspace") == str(workspace)
        and value.get("task") == workspace.name
        and value.get("tool") == tool
        and launch_identity.TASK.fullmatch(workspace.name)
        and str(uuid.UUID(value["session_id"])) == value["session_id"]
    )
    if not valid:
        raise ValueError("unconfirmed session")
    return value


def _session(workspace: Path, tool: str) -> Session:
    identity = _identity(workspace, tool)
    session_id = identity["session_id"]
    if tool == "codex":
        matches = list(paths.codex_home().glob(f"sessions/**/*{session_id}.jsonl"))
    else:
        matches = list((Path.home() / ".claude/projects").glob(f"*/{session_id}.jsonl"))
    if len(matches) != 1:
        raise ValueError("native record unavailable")
    path = matches[0]
    session = (
        codex.read(str(path), strict=True, starts=True)[0]
        if tool == "codex"
        else claude.read(str(path), time.time(), strict=True)
    )
    if session.session_id != session_id or Path(session.cwd).resolve() != workspace:
        raise ValueError("native identity mismatch")
    return session


def _label(value: str | None, pattern: re.Pattern | None) -> str | None:
    if not isinstance(value, str) or pattern is None or not NAME.fullmatch(value):
        return None
    return None if pattern.search(value) else value


def _row(entry: dict, host: str, plots: set[str], now: float) -> tuple[dict, Session | None, str]:
    location = entry.get("worktreePath")
    try:
        workspace = Path(location).resolve() if isinstance(location, str) else None
    except OSError, RuntimeError:
        workspace = None
    key = str(workspace) if workspace else str(entry.get("handle"))
    identity = key + str(entry["agentIdentity"]) + str(entry.get("handle"))
    result = {
        "session": hashlib.sha256(identity.encode()).hexdigest()[:20],
        "name": workspace.name if workspace else None,
        "host": host,
        "plot": history.plot_for(str(workspace), plots) if workspace else None,
        "tool": entry["agentIdentity"],
        "manager_host": None,
        "manager": None,
        "state": "unknown",
        "stage": None,
        "step_started_at": None,
        "step_seconds": None,
        "started_at": None,
        "total_seconds": None,
        "extra_rounds": None,
        "expected_finish_at": None,
        "estimate_sessions": None,
        "observed_at": round(now),
        "last_activity_at": None,
    }
    try:
        session = _session(workspace, entry["agentIdentity"]) if workspace else None
        if session and session.mode == "spine" and session.activity:
            result.update(progress.timings(session, now))
            if session.manager:
                result["manager_host"], result["manager"] = session.manager
        return result, session, str(workspace) if workspace else ""
    except OSError, ValueError, KeyError, TypeError, AttributeError:
        return result, None, str(workspace) if workspace else ""


def rows(host: str) -> list[dict]:
    try:
        pattern = identifiers._pattern(paths.ROOT)
    except SlopmeisterError:
        pattern = None
    now = time.time()
    try:
        plots = {p.parent.name for p in paths.plot_declarations().glob("*/plot.toml")}
        pairs = [_row(entry, host, plots, now) for entry in inventory()]
        needed = {row["plot"] for row, _, _ in pairs if row["plot"]}
        earlier, complete = (
            history.scan(Path.home(), needed, now, declared=plots) if needed else ([], True)
        )
        active = {cwd for _, _, cwd in pairs if cwd}
        return _finish(pairs, earlier, active, pattern, complete)
    except OSError, ValueError, TypeError, AttributeError:
        raise SlopmeisterError("local session inventory unavailable") from None


def _finish(pairs: list, earlier: list, active: set[str], pattern, complete: bool) -> list[dict]:
    rows = []
    for row, session, _ in pairs:
        if session and row["state"] == "known":
            _enrich(row, session, earlier, active)
            if not complete and RANK[row["stage"]] < RANK["accept"]:
                row.update(state="unknown", estimate_sessions=None, expected_finish_at=None)
        for key in ("name", "host", "plot", "manager_host", "manager"):
            row[key] = _label(row[key], pattern)
        rows.append(row)
    return sorted(
        rows, key=lambda row: (row["manager_host"] or "", row["manager"] or "", row["session"])
    )


def _enrich(row: dict, session: Session, earlier: list[Session], active: set[str]) -> None:
    same = [s for s in earlier if (s.cwd, s.tool) == (session.cwd, session.tool)]
    if same:
        combined = (
            history.merge(same)
            if same[0].session_id == session.session_id
            else history.merge([*same, session])
        )
        # History omits live call starts. Retain them from the confirmed current record.
        combined.command_starts = session.command_starts
        row.update(progress.timings(combined, row["observed_at"]))
    progress.estimate(row, earlier, active)
