"""Bind a native write adapter and its consumer to the configured native client."""

import json
import os
from pathlib import Path
import stat
import sys
import tomllib

from .constants import PYTHON, PYTHON_FLAGS
from .native_process import NATIVE_ERROR
from .native_process import (
    owned_pipe as _owned_pipe,
)
from .native_process import (
    owned_socket as _owned_socket,
)
from .native_process import (
    process as _process,
)


def diagnostic(error: Exception) -> str:
    message = str(error)
    if message in (f"{NATIVE_ERROR}: client", f"{NATIVE_ERROR}: ask"):
        return message
    return f"{NATIVE_ERROR}: local"


def _values(argv: list[str], name: str, short: str = "") -> list[str]:
    values = []
    for index, token in enumerate(argv):
        if token == "--":
            break
        if token in (name, short):
            values.extend(argv[index + 1 : index + 2] or [""])
            continue
        if token.startswith(name + "="):
            values.append(token[len(name) + 1 :])
            continue
        if short and token.startswith(short):
            values.append(token[len(short) :].removeprefix("="))
    return values


def _option(argv: list[str], name: str) -> str:
    values = _values(argv, name)
    if len(values) != 1:
        raise ValueError(NATIVE_ERROR)
    return values[0]


def _claude(binding: dict, argv: list[str], alias: str) -> None:
    workspace = Path(binding["workspace"])
    settings = workspace / ".claude/access-settings.json"
    config = workspace / ".claude/service-actions/mcp.json"
    if (
        _option(argv, "--permission-mode") != "auto"
        or _option(argv, "--settings") != str(settings)
        or _option(argv, "--mcp-config") != str(config)
        or "--dangerously-skip-permissions" in argv
    ):
        raise ValueError(NATIVE_ERROR)
    permissions = json.loads(settings.read_text())["permissions"]
    if f"mcp__{alias}__run" not in permissions.get("ask", []):
        raise ValueError(f"{NATIVE_ERROR}: ask")


def _codex(binding: dict, argv: list[str], alias: str) -> None:
    flags = {value.split("=", 1)[0] for value in argv[: argv.index("--") if "--" in argv else None]}
    if flags & {"--dangerously-bypass-approvals-and-sandbox", "--yolo", "--worktree"} or _values(
        argv, "--profile", "-p"
    ):
        raise ValueError(NATIVE_ERROR)
    if any(value != "on-request" for value in _values(argv, "--ask-for-approval", "-a")):
        raise ValueError(NATIVE_ERROR)
    _codex_overrides(_values(argv, "--config", "-c"), alias)
    config = Path(binding["workspace"]) / ".codex/config.toml"
    data = tomllib.loads(config.read_text())
    try:
        decision = data["mcp_servers"][alias]["tools"]["run"]["approval_mode"]
    except KeyError:
        raise ValueError(f"{NATIVE_ERROR}: ask") from None
    if decision != "prompt":
        raise ValueError(f"{NATIVE_ERROR}: ask")


def _codex_overrides(overrides: list[str], alias: str) -> None:
    pins = set()
    for override in overrides:
        key, separator, value = override.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        root = key.split(".", 1)[0].strip("\"'")
        if root == "mcp_servers":
            parts = key.split(".")
            if (
                len(parts) != 5
                or parts[1] not in ("jira_write", "confluence_write")
                or (parts[2:] != ["tools", "run", "approval_mode"] or value != "prompt")
            ):
                raise ValueError(NATIVE_ERROR)
            pins.add(parts[1])
        if not separator or root in ("profiles", "projects", "auto_review"):
            raise ValueError(NATIVE_ERROR)
        if root in ("approval_policy", "approvals_reviewer"):
            expected = ("on-request",) if root == "approval_policy" else ("auto_review", "user")
            if value not in expected:
                raise ValueError(NATIVE_ERROR)
    if alias not in pins:
        raise ValueError(NATIVE_ERROR)


def _host(binding: dict, alias: str, pid: int) -> None:
    executable, argv, _ = _process(pid)
    if not binding.get("cli") or executable.resolve() != Path(binding["cli"]).resolve():
        raise ValueError(f"{NATIVE_ERROR}: client")

    if binding["tool"] == "claude":
        _claude(binding, argv, alias)
    elif binding["tool"] == "codex":
        _codex(binding, argv, alias)
    else:
        raise ValueError(NATIVE_ERROR)


def require_host(root: Path, binding: dict) -> None:
    try:
        kind = stat.S_IFIFO if binding["tool"] == "codex" else stat.S_IFSOCK
        if stat.S_IFMT(os.fstat(0).st_mode) != kind:
            raise ValueError(NATIVE_ERROR)
        owned = _owned_pipe if binding["tool"] == "codex" else _owned_socket
        if not owned(os.getppid()):
            raise ValueError(NATIVE_ERROR)
        _host(binding, root.name.replace("-", "_"), os.getppid())
    except (OSError, KeyError, TypeError, UnicodeError, ValueError) as error:
        raise ValueError(diagnostic(error)) from None


def require_consumer(root: Path, binding: dict | bool | None) -> None:
    if binding is False:
        return
    try:
        if not isinstance(binding, dict):
            raise ValueError(NATIVE_ERROR)
        executable, argv, parent = _process(os.getppid())
        current, _, _ = _process(os.getpid())
        wanted = [*PYTHON_FLAGS, str(root / "native_tool.py")]
        if (
            Path(sys.executable).resolve() != PYTHON.resolve()
            or executable != current
            or argv[1:] != wanted
        ):
            raise ValueError(NATIVE_ERROR)
        _host(binding, root.name.replace("-", "_"), parent)
    except OSError, KeyError, TypeError, UnicodeError, ValueError:
        raise ValueError(NATIVE_ERROR) from None
