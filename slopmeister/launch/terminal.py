"""The Orca seam: open a command in an Orca terminal, name the workspace, list and close."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess

from slopmeister import paths
from slopmeister.errors import SlopmeisterError

# The Mac app bundle's copy, the /usr/local/bin link is readable only by root there. On Linux
# the package's own link, because a bare `orca` is the GNOME screen reader.
ORCA = {
    "darwin": "/Applications/Orca.app/Contents/Resources/bin/orca",
    "linux": "/usr/bin/orca-ide",
}
TIMEOUT = 30
LIST_LIMIT = "1000"
# Orca hands its start environment to every terminal it opens, never an agent's session.
START_ENV = ("HOME", "USER", "LOGNAME", "PATH", "SHELL", "TMPDIR", "LANG")
# A Linux desktop app opens no window without its session's display and bus.
LINUX_SESSION_ENV = (
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XDG_RUNTIME_DIR",
    "DBUS_SESSION_BUS_ADDRESS",
    "XAUTHORITY",
)


def binary() -> str:
    return os.environ.get("PLOT_SESSION_ORCA") or ORCA[paths.platform()]


def _orca(*args: str, env: dict[str, str] | None = None, checked: bool = False) -> dict | None:
    """Orca answers ok even while its app is closed, so callers read the result itself."""
    try:
        done = subprocess.run(
            [binary(), *args, "--json"], capture_output=True, text=True, timeout=TIMEOUT, env=env
        )
        reply = json.loads(done.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        if checked:
            reason = (
                "timeout" if isinstance(error, subprocess.TimeoutExpired) else "unreadable_reply"
            )
            if isinstance(error, OSError):
                reason = "execution_failed"
            raise SlopmeisterError(reason) from None
        return None
    if not isinstance(reply, dict) or not reply.get("ok"):
        if checked:
            error = reply.get("error") if isinstance(reply, dict) else None
            code = error.get("code") if isinstance(error, dict) else None
            safe = isinstance(code, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", code)
            raise SlopmeisterError(code if safe else "unreadable_reply")
        return None
    result = reply.get("result")
    return result if isinstance(result, dict) else {}


def _usable() -> bool:
    status = _orca("status") or {}
    app, runtime = status.get("app") or {}, status.get("runtime") or {}
    return bool(app.get("running") and runtime.get("reachable"))


def ready() -> bool:
    """A closed Orca is started once, `orca open` waits for its runtime itself."""
    if _usable():
        return True
    names = START_ENV + (LINUX_SESSION_ENV if paths.platform() == "linux" else ())
    _orca("open", env={key: os.environ[key] for key in names if key in os.environ})
    return _usable()


def register(repo: Path) -> None:
    listed = _orca("repo", "list") or {}
    if str(repo) not in {entry.get("path") for entry in listed.get("repos", [])}:
        _orca("repo", "add", "--path", str(repo))


def create(workspace: Path, title: str, command: str) -> str:
    args = ["--worktree", f"path:{workspace}", "--title", title, "--command", command]
    created = _orca("terminal", "create", *args, checked=True) or {}
    tab = created.get("terminal")
    handle = tab.get("handle") if isinstance(tab, dict) else None
    if isinstance(handle, str) and handle:
        return handle
    raise SlopmeisterError("unreadable_reply")


def name(workspace: Path, display: str, issue: str) -> bool:
    """Agent CLIs rewrite their tab titles, the workspace name and issue are what stay."""
    args = ["--worktree", f"path:{workspace}", "--display-name", display]
    if issue:
        args += ["--issue", issue]
    return _orca("worktree", "set", *args) is not None


def terminals() -> dict[str, str] | None:
    """Handle to workspace path. `terminal show` still answers for a closed handle, the list not."""
    listed = _orca("terminal", "list", "--limit", LIST_LIMIT)
    if listed is None or listed.get("truncated") is not False:
        return None
    return {entry.get("handle"): entry.get("worktreePath") for entry in listed.get("terminals", [])}


def close(handle: str) -> None:
    _orca("terminal", "close", "--terminal", handle)
