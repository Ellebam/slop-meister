"""Persist and validate one launcher-confirmed task and native session identity."""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid

TASK = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
TOOLS = {"claude", "codex", "opencode"}


def state_home() -> Path:
    return Path.home().resolve() / ".local/state"


def path(workspace: Path) -> Path:
    key = hashlib.sha256(str(workspace.resolve()).encode()).hexdigest()
    return state_home() / "slopmeister/launch" / f"{key}.json"


def private_json(source: Path, label: str) -> dict:
    """An object from a regular file that only this user can read or write."""
    if source.is_symlink():
        raise ValueError(f"symlinked {label}")
    with os.fdopen(os.open(source, os.O_RDONLY | os.O_NOFOLLOW)) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError(f"unsafe {label}")
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"invalid {label}")
    return value


def read(workspace: Path, expected_tool: str | None = None) -> dict:
    workspace = workspace.resolve()
    value = private_json(path(workspace), "launcher identity file")
    required = {"version", "state", "workspace", "task", "tool", "session_id"}
    if set(value) != required or value.get("version") != 1 or value.get("state") != "confirmed":
        raise ValueError("launcher identity is not confirmed")
    task, tool = value.get("task"), value.get("tool")
    if (
        value.get("workspace") != str(workspace)
        or task != workspace.name
        or not TASK.fullmatch(task)
    ):
        raise ValueError("launcher task identity mismatch")
    if tool not in TOOLS or expected_tool is not None and tool != expected_tool:
        raise ValueError("launcher tool identity mismatch")
    if tool != "opencode" and str(uuid.UUID(value["session_id"])) != value["session_id"]:
        raise ValueError("launcher session identity mismatch")
    selected = os.environ.get("CODEX_THREAD_ID", value["session_id"])
    if tool == "codex" and selected != value["session_id"]:
        raise ValueError("native session identity mismatch")
    return value


def write(workspace: Path, identity: tuple[str, str, str | None]) -> Path:
    task, tool, session_id = identity
    workspace = workspace.resolve()
    if task != workspace.name or not TASK.fullmatch(task) or tool not in TOOLS:
        raise ValueError("invalid launcher identity")
    if session_id is not None:
        if tool != "opencode":
            session_id = str(uuid.UUID(session_id))
        elif not session_id or not session_id.isprintable():
            raise ValueError("invalid OpenCode session identity")
    value = {
        "version": 1,
        "state": "confirmed" if session_id else "prepared",
        "workspace": str(workspace),
        "task": task,
        "tool": tool,
    }
    if session_id:
        value["session_id"] = session_id
    return _save(path(workspace), value)


def _save(destination: Path, value: dict) -> Path:
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = destination.parent.stat()
    safe = not destination.parent.is_symlink() and info.st_uid == os.getuid()
    if not safe or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("launcher identity directory is not owned and private")
    descriptor, temporary = tempfile.mkstemp(
        dir=destination.parent, prefix=destination.name, suffix=".part"
    )
    candidate = Path(temporary)
    try:
        os.chmod(candidate, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(candidate, destination)
    finally:
        candidate.unlink(missing_ok=True)
    return destination
