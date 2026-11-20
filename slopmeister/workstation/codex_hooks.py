"""Add Slopmeister's prompt and memory guard hooks to Codex's hooks file, others unchanged.

Orca writes its own groups to the same file, so the install merges one group per event and never
rewrites the rest. Codex runs a changed hook only when its trust entry matches, which the Codex
config install writes from `trust`, so no person has to approve it in `/hooks` on each machine.
"""

import hashlib
import json
import os
from pathlib import Path
import shlex
import tempfile

from slopmeister.errors import SlopmeisterError
from slopmeister.paths import ROOT
from slopmeister.render.settings import permission_contract
from slopmeister.workstation import rules

NAME = ".codex/hooks.json"
EVENT = "PermissionRequest"
COMMAND = "~/.local/bin/slopmeister-prompt notice"
# The hand-written group of the retired script, replaced in place.
RETIRED = "~/.claude/prompt-notice.sh"
# The notice has an eight-second transport timeout.
GROUP = {"hooks": [{"type": "command", "command": COMMAND, "timeout": 10}]}
# Codex on Linux runs without a sandbox, so this hook is the refusal of a patch into a private
# memory folder. Codex reports a patch inside a shell command as a Bash call. The quoted folders
# reach the guard unexpanded, it resolves them itself. Codex blocks only on exit 2, so a missing
# launcher must exit 2 too.
GUARD_EVENT = "PreToolUse"
GUARD_PREFIX = "~/.local/bin/slopmeister-prompt guard"
FOLDERS = permission_contract(ROOT / "src/permissions.toml")["private_memory"]["paths"]
GUARD = {
    "matcher": "^(apply_patch|Bash)$",
    "hooks": [
        {
            "type": "command",
            "command": f"{GUARD_PREFIX} {shlex.join(FOLDERS)} || exit 2",
            "timeout": 30,
        }
    ],
}
# Each owned event, its group, the native event name in the trust key and the commands it replaces.
OWNED = (
    (EVENT, GROUP, "permission_request", lambda command: command in (COMMAND, RETIRED)),
    (GUARD_EVENT, GUARD, "pre_tool_use", lambda command: command.startswith(GUARD_PREFIX)),
)


def _commands(group: dict) -> list:
    hooks = group.get("hooks")
    if not isinstance(hooks, list):
        return []
    return [hook.get("command") for hook in hooks if isinstance(hook, dict)]


def _owned(group: dict, replaces) -> bool:
    commands = _commands(group)
    return len(commands) == 1 and isinstance(commands[0], str) and replaces(commands[0])


def _updated(original: bytes | None) -> dict:
    settings = json.loads(original) if original is not None else {}
    hooks = settings.setdefault("hooks", {}) if isinstance(settings, dict) else None
    if not isinstance(hooks, dict):
        raise ValueError(f"unsupported {NAME} shape")
    for event, wanted, _, replaces in OWNED:
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list) or not all(isinstance(group, dict) for group in groups):
            raise ValueError(f"unsupported {NAME} shape")
        ours = [group for group in groups if _owned(group, replaces)]
        kept = [group for group in groups if group not in ours]
        first = groups.index(ours[0]) if ours else len(groups)
        hooks[event] = [*kept[:first], wanted, *kept[first:]]
    return settings


def _parsed(home: Path) -> tuple[bytes | None, dict]:
    try:
        original = rules._read(home / NAME)
        return original, _updated(original)
    except OSError, ValueError:
        raise SlopmeisterError(f"unreadable, unsafe or invalid {NAME}, nothing written") from None


def trust(home: Path) -> list[tuple[str, str]]:
    """Codex's trust key and hash for each owned group, as its hook discovery computes them."""
    hooks = _parsed(home)[1]["hooks"]
    found = []
    for event, group, native, _ in OWNED:
        key = f"{home / NAME}:{native}:{hooks[event].index(group)}:0"
        identity = {"event_name": native, "hooks": [{"async": False, **h} for h in group["hooks"]]}
        identity |= {"matcher": group["matcher"]} if "matcher" in group else {}
        data = json.dumps(identity, sort_keys=True, separators=(",", ":"))
        found.append((key, "sha256:" + hashlib.sha256(data.encode()).hexdigest()))
    return found


def status(home: Path) -> str:
    try:
        original, updated = _parsed(home)
    except SlopmeisterError:
        return "differs"
    if original is None:
        return "missing"
    return "unchanged" if json.loads(original) == updated else "differs"


def change(home: Path) -> str:
    try:
        _parsed(home)
    except SlopmeisterError:
        return f"  unreadable: {NAME}, compared nothing"
    return f"  {status(home)}: {NAME} {EVENT} group `{COMMAND}`, {GUARD_EVENT} memory guard"


def validate(home: Path) -> None:
    """Refuse before the first write of an install, so a bad file stops every item."""
    _parsed(home)


def install(home: Path, backups: Path) -> None:
    destination = home / NAME
    original, updated = _parsed(home)
    if original is not None:
        rules._backup(backups, NAME, original)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=destination.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(updated, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if rules._read(destination) != original:
            raise SlopmeisterError(f"{NAME} changed during install; nothing replaced")
        os.replace(temporary, destination)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
