"""Install central global restrictions without reading client-saved Codex approvals."""

import json
import os
from pathlib import Path
import tempfile

from slopmeister.errors import SlopmeisterError
from slopmeister.paths import ROOT
from slopmeister.render.settings import codex_rules, permission_contract
from slopmeister.session import launch_identity

CLAUDE_LIVE = ".claude/settings.json"
CODEX_LIVE = ".codex/rules/permissions.rules"
NAMES = (CLAUDE_LIVE, CODEX_LIVE)


def _read(path: Path, *, limit: int | None = None) -> bytes | None:
    try:
        descriptor = launch_identity.open_nofollow(path, os.O_RDONLY | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "rb") as stream:
        if not launch_identity.regular_file(os.fstat(stream.fileno()), owned=True):
            raise ValueError("unsafe policy file")
        data = stream.read() if limit is None else stream.read(limit + 1)
        if limit is not None and len(data) > limit:
            raise ValueError("file exceeds read limit")
        return data


def _claude(original: bytes | None, root: Path) -> bytes:
    settings = json.loads(original) if original is not None else {}
    if not isinstance(settings, dict):
        raise ValueError("invalid settings object")
    home = json.loads((root / "plots/home/claude/settings.json.tmpl").read_bytes())
    settings["autoMemoryEnabled"] = home["autoMemoryEnabled"]
    wanted = json.loads((root / "dist/claude/settings.json").read_bytes())
    for section, key, value in (
        (
            "permissions",
            "deny",
            [r for r in wanted["permissions"]["deny"] if r.startswith("Bash(")],
        ),
        ("autoMode", "soft_deny", wanted["autoMode"]["soft_deny"]),
    ):
        current = settings.setdefault(section, {})
        if not isinstance(current, dict):
            raise ValueError("invalid settings section")
        previous = current.get(key, [])
        if not isinstance(previous, list) or any(not isinstance(rule, str) for rule in previous):
            raise ValueError("invalid policy list")
        current[key] = [*previous, *(rule for rule in value if rule not in previous)]
    return (json.dumps(settings, indent=2, ensure_ascii=False) + "\n").encode()


def _expected(name: str, original: bytes | None, root: Path) -> bytes:
    if name == CLAUDE_LIVE:
        return _claude(original, root)
    contract = permission_contract(root / "src/permissions.toml")
    contract["command"] = [entry for entry in contract["command"] if entry["decision"] != "allow"]
    return codex_rules(contract).encode()


def status(home: Path, name: str, root: Path = ROOT) -> str:
    try:
        original = _read(home / name)
        if original is None:
            return "missing"
        expected = _expected(name, original, root)
        same = (
            json.loads(original) == json.loads(expected)
            if name == CLAUDE_LIVE
            else original == expected
        )
        return "unchanged" if same else "differs"
    except OSError, ValueError, TypeError:
        return "differs"


def change(home: Path, name: str) -> str:
    return f"  {status(home, name)}: {name} central restrictions"


def validate(home: Path, names: set[str]) -> None:
    try:
        for name in names:
            _expected(name, _read(home / name), ROOT)
    except OSError, ValueError, TypeError:
        raise SlopmeisterError("Global policy is unreadable or unsafe; nothing written") from None


def _backup(backups: Path, name: str, original: bytes) -> None:
    backups.mkdir(parents=True, exist_ok=True, mode=0o700)
    backups.chmod(0o700)
    saved = backups / name
    saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    saved.parent.chmod(0o700)
    with os.fdopen(os.open(saved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())


def install(home: Path, backups: Path, name: str) -> None:
    path = home / name
    try:
        original = _read(path)
        updated = _expected(name, original, ROOT)
        if original is not None:
            _backup(backups, name, original)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    except OSError, ValueError, TypeError:
        raise SlopmeisterError(f"Cannot prepare {name}; nothing replaced") from None
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        if _read(path) != original:
            raise SlopmeisterError(f"{name} changed during install; nothing replaced")
        os.replace(temporary, path)
    except OSError, ValueError:
        raise SlopmeisterError(f"Cannot replace {name}; original kept") from None
    finally:
        Path(temporary).unlink(missing_ok=True)
