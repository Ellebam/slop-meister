"""Set managed Orca settings through Orca's runtime and read the settings it uses."""

from contextlib import closing
import json
import os
from pathlib import Path
import socket
import sqlite3
import stat
import time
import uuid

from slopmeister.errors import SlopmeisterError
from slopmeister.launch import terminal
from slopmeister.paths import ROOT
from slopmeister.session import launch_identity

# Orca's profile database, read only. Orca owns it, and an outside write to it or to
# orca-data.json makes Orca ask at its next start which copy to keep, see docs/orca.md.
STORE = {
    "darwin": "Library/Application Support/orca/profiles/local-default/profile-state.db",
    "linux": ".config/orca/profiles/local-default/profile-state.db",
}
STORE_GUIDE = "see docs/workspace-removal.md"
# Managed on the Mac only, a fresh profile as on Linux has no settings yet.
NAME = STORE["darwin"]
SOURCE = "plots/home/orca/settings.json"
# Written by a running Orca at mode 0600. It holds the local token its own CLI uses.
RUNTIME = "Library/Application Support/orca/orca-runtime.json"
# Orca's runtime accepts only these managed keys, the others stay a read-only check.
ROUTED = ("terminalQuickCommands", "agentStatusHooksEnabled", "agentDefaultArgs")
MAX_FRAME = 1024 * 1024
DEADLINE = 30.0
RUNTIME_GUIDE = "open Orca and retry; nothing written"


def _wanted(root: Path = ROOT) -> dict:
    return json.loads((root / SOURCE).read_text())["settings"]


def _document(store: Path, domain: str) -> object:
    """One profile state document, read only, or None when the store cannot give it."""
    query = "select payload from profile_state_documents where domain = ?"
    try:
        with closing(sqlite3.connect(f"{store.as_uri()}?mode=ro", uri=True)) as database:
            row = database.execute(query, (domain,)).fetchone()
        return json.loads(row[0]) if row else None
    except sqlite3.Error, ValueError, TypeError:
        return None


def _settings(home: Path) -> dict | None:
    settings = _document(home / NAME, "settings")
    return settings if isinstance(settings, dict) else None


def _stale_commands(current: object, wanted: list[dict]) -> list[dict]:
    """Managed Quick Commands that Orca lacks or holds in another form."""
    held = [item for item in current if isinstance(item, dict)] if isinstance(current, list) else []
    return [
        command
        for command in wanted
        if [item for item in held if item.get("id") == command["id"]] != [command]
    ]


def _differs(current: dict, wanted: dict) -> list[str]:
    """Managed keys whose value in Orca differs from the source. Values are never printed."""
    keys = []
    for key, value in wanted.items():
        have = current.get(key)
        if key == "terminalQuickCommands":
            same = not _stale_commands(have, value)
        elif isinstance(value, dict):
            same = isinstance(have, dict) and all(
                name in have and have[name] == item for name, item in value.items()
            )
        else:
            same = key in current and have == value
        if not same:
            keys.append(key)
    return keys


def status(home: Path, root: Path = ROOT) -> str:
    store = home / NAME
    if not store.exists() and not store.is_symlink():
        return "missing"
    settings = _settings(home)
    return (
        "unchanged" if settings is not None and not _differs(settings, _wanted(root)) else "differs"
    )


def change(home: Path) -> str:
    return f"  {status(home)}: {NAME} managed Orca settings"


def _trusted(endpoint: Path) -> bool:
    """The socket and its folder belong to this user, and the folder is closed to others."""
    try:
        sock, folder, parent = (
            os.lstat(p) for p in (endpoint, endpoint.parent, endpoint.parent.parent)
        )
    except OSError:
        return False
    uid = os.getuid()
    return (
        endpoint.is_absolute()
        and stat.S_ISSOCK(sock.st_mode)
        and sock.st_uid == uid
        and stat.S_ISDIR(folder.st_mode)
        and folder.st_uid == uid
        and not folder.st_mode & 0o077
        and parent.st_uid == uid
    )


def _runtime(home: Path) -> tuple[str, str, str]:
    """Orca's socket, token and runtime id. The token stays in memory and out of every message."""
    try:
        with os.fdopen(launch_identity.open_nofollow(home / RUNTIME), "rb") as stream:
            info = os.fstat(stream.fileno())
            raw = stream.read(MAX_FRAME)
        if (
            not launch_identity.regular_file(info, owned=True)
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise ValueError("unsafe Orca runtime file")
        meta = json.loads(raw)
        unix = [
            t.get("endpoint")
            for t in meta["transports"]
            if isinstance(t, dict) and t.get("kind") == "unix"
        ]
        found = (unix[0] if unix else None, meta["authToken"], meta["runtimeId"])
    except OSError, ValueError, TypeError, KeyError:
        found = None
    if (
        found is None
        or not all(isinstance(v, str) and v for v in found)
        or not _trusted(Path(found[0]))
    ):
        raise SlopmeisterError(
            f"Orca is not running, or its runtime file is not private to you, {RUNTIME_GUIDE}"
        )
    return found


def _printable(text: object, token: str) -> str:
    """Orca's error text for a message. The token goes before the cut, so no part of it remains."""
    if not isinstance(text, str):
        return ""
    return "".join(ch for ch in text if ch.isprintable()).replace(token, "[token]")[:200]


def _exchange(endpoint: str, request: dict) -> object:
    """Send one request line and return the first reply that is not a keepalive."""
    deadline = time.monotonic() + DEADLINE
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    with connection, connection.makefile("rb") as frames:
        connection.settimeout(DEADLINE)
        connection.connect(endpoint)
        connection.sendall(json.dumps(request).encode() + b"\n")
        while True:
            connection.settimeout(max(deadline - time.monotonic(), 0.001))
            frame = frames.readline(MAX_FRAME + 1)
            if not frame.endswith(b"\n"):
                raise ValueError("no complete reply")
            reply = json.loads(frame)
            if not isinstance(reply, dict) or reply.get("_keepalive") is not True:
                return reply


def _call(runtime: tuple[str, str, str], method: str, params: dict | None = None) -> dict:
    """One request to Orca's runtime. Errors name the method and Orca's reason, never the token."""
    endpoint, token, runtime_id = runtime
    request = {"id": str(uuid.uuid4()), "authToken": token, "method": method}
    if params is not None:
        request["params"] = params
    try:
        reply = _exchange(endpoint, request)
    except OSError, ValueError:
        raise SlopmeisterError(f"Orca runtime call {method} got no valid reply") from None
    if not isinstance(reply, dict) or reply.get("id") != request["id"]:
        raise SlopmeisterError(f"Orca runtime call {method} got a reply to another request")
    if reply.get("ok") is not True:
        error = reply.get("error") if isinstance(reply.get("error"), dict) else {}
        code, message = (_printable(error.get(key), token) for key in ("code", "message"))
        reason = f"{code} {message}".strip()
        raise SlopmeisterError(f"Orca refused {method}: {reason or 'no reason given'}")
    meta, result = reply.get("_meta"), reply.get("result")
    if not isinstance(meta, dict) or meta.get("runtimeId") != runtime_id:
        raise SlopmeisterError(f"Orca runtime call {method} got a reply from another runtime")
    if not isinstance(result, dict):
        raise SlopmeisterError(f"Orca runtime call {method} returned an unknown shape")
    return result


def _live(runtime: tuple[str, str, str]) -> dict:
    """The routed settings as Orca's runtime serves them."""
    settings = _call(runtime, "settings.get").get("settings")
    commands = _call(runtime, "settings.getTerminalQuickCommands").get("terminalQuickCommands")
    if not isinstance(settings, dict) or not isinstance(commands, list):
        raise SlopmeisterError("Orca runtime returned settings in an unknown shape")
    return {**settings, "terminalQuickCommands": commands}


def _apply(runtime: tuple[str, str, str], wanted: dict, live: dict) -> None:
    for command in _stale_commands(
        live["terminalQuickCommands"], wanted.get("terminalQuickCommands", [])
    ):
        mutation = {"type": "upsert", "command": command}
        _call(runtime, "settings.updateTerminalQuickCommands", {"mutation": mutation})
    update = {key: wanted[key] for key in _differs(live, wanted) if key != "terminalQuickCommands"}
    if "agentDefaultArgs" in update:
        # Orca replaces the whole map, so unmanaged agents keep their current arguments.
        current = live.get("agentDefaultArgs")
        update["agentDefaultArgs"] = {
            **(current if isinstance(current, dict) else {}),
            **update["agentDefaultArgs"],
        }
    if update:
        _call(runtime, "settings.update", update)
    left = _differs(_live(runtime), wanted)
    if left:
        raise SlopmeisterError(f"Orca did not keep these managed settings: {', '.join(left)}")


def validate(home: Path) -> None:
    """Refuse before any write when a key without a route differs or Orca is unreachable."""
    settings = _settings(home)
    if settings is None:
        raise SlopmeisterError(
            f"Orca's profile settings are missing or unreadable, {RUNTIME_GUIDE}"
        )
    unrouted = [key for key in _differs(settings, _wanted()) if key not in ROUTED]
    if unrouted:
        raise SlopmeisterError(
            f"Orca accepts no outside change of {', '.join(unrouted)}, set it by hand in Orca's "
            f"Settings to the value in {SOURCE}, see docs/orca.md; nothing written"
        )
    _runtime(home)


def _backup(backups: Path, settings: dict) -> Path:
    backups.mkdir(mode=0o700, parents=True, exist_ok=True)
    backups.chmod(0o700)
    saved = backups / f"{NAME}.settings.json"
    saved.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    saved.parent.chmod(0o700)
    with os.fdopen(os.open(saved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        json.dump(settings, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return saved


def install(home: Path, backups: Path) -> None:
    """Send each differing managed setting to the running Orca, after a backup of its settings."""
    prior = _settings(home)
    if prior is None:
        raise SlopmeisterError(
            f"Orca's profile settings are missing or unreadable, {RUNTIME_GUIDE}"
        )
    runtime = _runtime(home)
    wanted = {key: value for key, value in _wanted().items() if key in ROUTED}
    live = _live(runtime)
    if not _differs(live, wanted):
        return
    # Orca's runtime can hold newer values than its store, so the backup keeps what it serves.
    saved = _backup(backups, {**prior, **live})
    try:
        _apply(runtime, wanted, live)
    except SlopmeisterError as error:
        raise SlopmeisterError(
            f"{error}; Orca's settings before this install are in {saved}"
        ) from None


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
