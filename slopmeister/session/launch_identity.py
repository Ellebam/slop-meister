"""Persist and validate one launcher-confirmed task and native session identity."""

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile
import uuid

TASK = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
TOOLS = {"claude", "codex", "opencode"}


def open_nofollow(
    path: Path | str, flags: int = os.O_RDONLY | os.O_NONBLOCK, *, dir_fd: int | None = None
) -> int:
    """Open without following the final link, retaining the caller's flags and OSError."""
    return os.open(path, flags | os.O_NOFOLLOW, dir_fd=dir_fd)


def replace_bytes(path: Path, data: bytes, mode: int | None = None) -> None:
    """Publish one complete file. A new file uses the process umask unless a mode is required."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISREG(info.st_mode):
            raise OSError(f"cannot replace nonregular file: {path}")
        if mode is None:
            mode = stat.S_IMODE(info.st_mode)
    candidate = path.with_name(f".{path.name}.{secrets.token_hex(8)}.part")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(candidate, flags, 0o666 if mode is None else 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            if mode is not None:
                os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(candidate, path)
    finally:
        candidate.unlink(missing_ok=True)


def regular_file(info: os.stat_result, *, owned: bool = False) -> bool:
    """Check a regular file and, when requested, ownership by the current user."""
    return stat.S_ISREG(info.st_mode) and (not owned or info.st_uid == os.getuid())


def state_home() -> Path:
    return Path.home().resolve() / ".local/state"


def path(workspace: Path) -> Path:
    key = hashlib.sha256(str(workspace.resolve()).encode()).hexdigest()
    return state_home() / "slopmeister/launch" / f"{key}.json"


def private_json(source: Path, label: str) -> dict:
    """An object from a regular file that only this user can read or write."""
    if source.is_symlink():
        raise ValueError(f"symlinked {label}")
    with os.fdopen(open_nofollow(source)) as stream:
        info = os.fstat(stream.fileno())
        if not regular_file(info, owned=True) or info.st_mode & 0o077:
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
