"""Trust one launch root without removing unrelated native project settings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import tomllib

ATTEMPTS = 2
CODEX_TABLE = re.compile(r"^\s*\[\s*projects\s*\.")


@dataclass(frozen=True)
class TrustRequest:
    mode: str
    path: Path
    workspace: str


class Changed(Exception):
    """The store changed between reading and replacing it."""


def reject(message: str) -> None:
    raise SystemExit(message)


def _read_bytes(path: Path) -> bytes:
    if path.is_symlink():
        reject(f"{path} is a symlink, refusing to replace native trust state through it")
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            reject(f"{path} is not a regular file, refusing to replace native trust state")
        return path.read_bytes()
    except FileNotFoundError:
        return b""


def _unique(pairs: list[tuple[str, object]]) -> dict:
    if len({key for key, _ in pairs}) != len(pairs):
        raise ValueError("duplicate JSON key")
    return dict(pairs)


def _claude_data(path: Path, raw: bytes) -> dict:
    try:
        data = json.loads(raw.decode() or "{}", object_pairs_hook=_unique)
    except (UnicodeDecodeError, ValueError) as error:
        reject(
            f"{path} does not parse as Claude JSON: {error}; stop and report this to the operator"
        )
    if not isinstance(data, dict) or not isinstance(data.get("projects", {}), dict):
        reject(
            f"{path} does not parse as a Claude store object; stop and report this to the operator"
        )
    return data


def _claude_edit(path: Path, raw: bytes, key: str) -> bytes | None:
    data = _claude_data(path, raw)
    projects = dict(data.get("projects", {}))
    entry = projects.get(key) if isinstance(projects.get(key), dict) else {}
    if entry.get("hasTrustDialogAccepted") is True:
        return None
    projects[key] = {**entry, "hasTrustDialogAccepted": True}
    updated = {**data, "projects": projects}
    encoded = json.dumps(updated, indent=2, ensure_ascii=False).encode()
    if json.loads(encoded) != updated:
        reject(f"the Claude trust update would change other state, {path} untouched")
    return encoded


def _codex_data(path: Path, raw: bytes) -> dict:
    try:
        return tomllib.loads(raw.decode())
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        reject(f"{path} does not parse and Codex would not load it either: {error}")


def _codex_blocks(text: str) -> list[tuple[str | None, str]]:
    """Split into top-level table blocks, each keyed by its project path or None."""
    blocks: list[tuple[str | None, str]] = [(None, "")]
    for line in text.splitlines(keepends=True):
        if CODEX_TABLE.match(line):
            blocks.append((next(iter(tomllib.loads(line)["projects"])), line))
        elif line.lstrip().startswith("["):
            blocks.append((None, line))
        else:
            blocks[-1] = (blocks[-1][0], blocks[-1][1] + line)
    return blocks


def _codex_text(raw: bytes, key: str) -> bytes:
    blocks = _codex_blocks(raw.decode())
    for index, (name, text) in enumerate(blocks):
        if name != key:
            continue
        header, _, body = text.partition("\n")
        if tomllib.loads(header) != {"projects": {key: {}}}:
            continue
        updated, count = re.subn(
            r"(?m)^[ \t]*trust_level[ \t]*=.*$", 'trust_level = "trusted"', body, count=1
        )
        if not count:
            updated = 'trust_level = "trusted"\n' + body
        blocks[index] = (name, header + "\n" + updated)
        return "".join(text for _, text in blocks).encode()
    kept = raw.decode()
    separator = "" if not kept or kept.endswith("\n") else "\n"
    return f'{kept}{separator}[projects."{key}"]\ntrust_level = "trusted"\n'.encode()


def _codex_matches(encoded: bytes, data: dict, projects: dict) -> bool:
    try:
        return tomllib.loads(encoded.decode()) == {**data, "projects": projects}
    except tomllib.TOMLDecodeError:
        return False


def _codex_key(key: str) -> None:
    if not key.isprintable() or '"' in key or "\\" in key:
        reject(
            "the working directory path holds a quote, a backslash or a control character, "
            f"no Codex trust entry can name it: {key}"
        )


def _codex_edit(path: Path, raw: bytes, key: str) -> bytes | None:
    _codex_key(key)
    data = _codex_data(path, raw)
    projects = data.get("projects", {})
    entry = projects.get(key, {})
    if entry.get("trust_level") == "trusted":
        return None
    try:
        encoded = _codex_text(raw, key)
    except tomllib.TOMLDecodeError, KeyError, StopIteration:
        encoded = b""
    updated = {**projects, key: {**entry, "trust_level": "trusted"}}
    if _codex_matches(encoded, data, updated):
        return encoded
    reject(
        f"{path} lays out its projects in a way the launcher cannot rewrite safely to trust "
        f"{key}; stop and report this to the operator"
    )


@dataclass(frozen=True)
class Replacement:
    path: Path
    data: bytes
    mode: int
    expected: bytes


def _atomic(replacement: Replacement) -> None:
    path = replacement.path
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(replacement.data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, replacement.mode)
        if _read_bytes(path) != replacement.expected:
            raise Changed
        if path.is_symlink():
            reject(f"{path} is a symlink, refusing to write native trust state through it")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _apply(request: TrustRequest, edit_for: Callable[[Path, bytes, str], bytes | None]) -> bool:
    raw = _read_bytes(request.path)
    edit = edit_for(request.path, raw, request.workspace)
    if edit is None:
        return True
    request.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    mode = stat.S_IMODE(request.path.stat().st_mode) if raw else 0o600
    try:
        _atomic(Replacement(request.path, edit, mode, raw))
    except Changed:
        return False
    return True


def _trusted(tool: str, path: Path, key: str) -> bool:
    if tool == "claude":
        entry = _claude_data(path, _read_bytes(path)).get("projects", {}).get(key)
        return isinstance(entry, dict) and entry.get("hasTrustDialogAccepted") is True
    entry = _codex_data(path, _read_bytes(path)).get("projects", {}).get(key)
    return isinstance(entry, dict) and entry.get("trust_level") == "trusted"


def trust(request: TrustRequest, tool: str) -> None:
    if request.mode not in ("check", "write") or tool not in ("claude", "codex"):
        raise ValueError("invalid native trust operation")
    if request.mode == "check":
        if tool == "codex":
            _codex_key(request.workspace)
        (_claude_data if tool == "claude" else _codex_data)(request.path, _read_bytes(request.path))
        return
    edit_for = _claude_edit if tool == "claude" else _codex_edit
    for _ in range(ATTEMPTS):
        if _apply(request, edit_for) and _trusted(tool, request.path, request.workspace):
            return
    if _trusted(tool, request.path, request.workspace):
        return
    reject(
        f"{request.path} kept changing while trust for {request.workspace} was written; "
        "retry the launch once, and if it repeats stop and report this to the operator"
    )
