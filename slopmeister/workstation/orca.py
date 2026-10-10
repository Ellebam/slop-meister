"""Manage only Slopmeister's Orca settings inside its live app-state file."""

import copy
import json
import os
from pathlib import Path
import stat
import tempfile

from slopmeister.errors import SlopmeisterError
from slopmeister.launch import terminal
from slopmeister.paths import ROOT

# Managed on the Mac only. A current Orca profile keeps its state in a database, and a fresh
# one, as on Linux, has no such file, see docs/orca.md.
NAME = "Library/Application Support/orca/profiles/local-default/orca-data.json"
SOURCE = "plots/home/orca/settings.json"


def _wanted(root: Path = ROOT) -> dict:
    return json.loads((root / SOURCE).read_text())["settings"]


def _read(path: Path) -> tuple[bytes, dict, os.stat_result]:
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("unsafe Orca state file")
        original = stream.read()
    parsed = json.loads(original)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("settings"), dict):
        raise ValueError("invalid Orca state object")
    return original, parsed, info


def _quick_commands(current: object, wanted: list[dict]) -> list:
    if not isinstance(current, list):
        raise ValueError("invalid Orca Quick Commands")
    commands = list(current)
    for managed in wanted:
        matches = [
            index
            for index, item in enumerate(commands)
            if isinstance(item, dict) and item.get("id") == managed["id"]
        ]
        if len(matches) > 1:
            raise ValueError("duplicate managed Orca Quick Command")
        if matches:
            commands[matches[0]] = managed
        else:
            commands.append(managed)
    return commands


def _merge(parsed: dict, wanted: dict) -> dict:
    merged = copy.deepcopy(parsed)
    settings = merged["settings"]
    for key, value in wanted.items():
        if key == "terminalQuickCommands":
            settings[key] = _quick_commands(settings.get(key, []), value)
            continue
        if not isinstance(value, dict):
            settings[key] = value
            continue
        current = settings.get(key, {})
        if not isinstance(current, dict):
            raise ValueError("invalid managed Orca settings object")
        settings[key] = {**current, **value}
    return merged


def status(home: Path, root: Path = ROOT) -> str:
    path = home / NAME
    if not path.exists() and not path.is_symlink():
        return "missing"
    try:
        _, parsed, _ = _read(path)
        return "unchanged" if _merge(parsed, _wanted(root)) == parsed else "differs"
    except OSError, ValueError, TypeError, KeyError:
        return "differs"


def change(home: Path) -> str:
    return f"  {status(home)}: {NAME} managed Orca settings"


def require_closed() -> None:
    reply = terminal._orca("status")
    app = reply.get("app") if isinstance(reply, dict) else None
    if not isinstance(app, dict) or app.get("running") is not False:
        raise SlopmeisterError(
            "Orca is running or its closed state is unverified, "
            "install Orca and open it once if missing, otherwise close it "
            "before home:install; nothing written"
        )


def validate(home: Path) -> None:
    try:
        _, parsed, _ = _read(home / NAME)
        _merge(parsed, _wanted())
    except OSError, ValueError, TypeError, KeyError:
        raise SlopmeisterError(
            "Orca state is missing or invalid, open Orca once, "
            "close it, then retry; nothing written"
        ) from None


def _backup(backups: Path, original: bytes) -> None:
    backups.mkdir(mode=0o700, parents=True, exist_ok=True)
    backups.chmod(0o700)
    saved = backups / NAME
    saved.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    saved.parent.chmod(0o700)
    with os.fdopen(os.open(saved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())


def _same_snapshot(
    original: tuple[bytes, os.stat_result], current: tuple[bytes, os.stat_result]
) -> bool:
    old_bytes, before = original
    new_bytes, after = current
    return new_bytes == old_bytes and (before.st_dev, before.st_ino, before.st_mtime_ns) == (
        after.st_dev,
        after.st_ino,
        after.st_mtime_ns,
    )


def install(home: Path, backups: Path) -> None:
    path = home / NAME
    try:
        original, parsed, before = _read(path)
        updated = (
            json.dumps(_merge(parsed, _wanted()), indent=2, ensure_ascii=False).encode() + b"\n"
        )
    except OSError, ValueError, TypeError, KeyError:
        raise SlopmeisterError("Orca state is missing or invalid; nothing written") from None
    _backup(backups, original)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        require_closed()
        try:
            current, _, after = _read(path)
        except OSError, ValueError, TypeError, KeyError:
            raise SlopmeisterError("Orca state changed during install; nothing replaced") from None
        if not _same_snapshot((original, before), (current, after)):
            raise SlopmeisterError("Orca state changed during install; nothing replaced")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _hooks_health(hooks: dict | None) -> str:
    if not isinstance(hooks, dict) or type(hooks.get("enabled")) is not bool:
        return "unverified"
    if not hooks["enabled"]:
        return "off"
    statuses = hooks.get("statuses")
    if not isinstance(statuses, list):
        return "unverified"
    by_agent = {
        item["agent"]: item
        for item in statuses
        if isinstance(item, dict) and isinstance(item.get("agent"), str)
    }
    installed = all(
        by_agent.get(agent, {}).get("state") == "installed"
        and by_agent[agent].get("managedHooksPresent") is True
        for agent in ("claude", "codex")
    )
    return "on" if installed else "unverified"


def health() -> dict[str, str]:
    answer = {"runtime": "missing", "hooks": "not checked"}
    binary = Path(terminal.binary())
    if binary.is_file() and os.access(binary, os.X_OK):
        reply = terminal._orca("status")
        app = reply.get("app") if isinstance(reply, dict) else None
        runtime = reply.get("runtime") if isinstance(reply, dict) else None
        if isinstance(app, dict) and app.get("running") is False:
            answer["runtime"] = "not running"
        elif (
            not isinstance(app, dict)
            or app.get("running") is not True
            or not isinstance(runtime, dict)
            or runtime.get("reachable") is not True
        ):
            answer["runtime"] = "unreachable"
        else:
            answer["runtime"] = "running"
            answer["hooks"] = _hooks_health(terminal._orca("agent", "hooks", "status"))
    return answer
