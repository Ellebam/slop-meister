"""Manage Slopmeister's top-level Codex settings, memory switch and hook trust.

This is the only writer of Codex's config file, so one install edits it with one backup.
"""

import os
from pathlib import Path
import re
import tempfile
import tomllib

from slopmeister.errors import SlopmeisterError
from slopmeister.paths import ROOT
from slopmeister.workstation import codex_hooks, rules

NAME = ".codex/config.toml"
SOURCE = "dist/codex/config.toml"
FIRST_TABLE = re.compile(r"(?m)^\s*\[")


def _wanted(root: Path = ROOT) -> dict:
    return tomllib.loads((root / SOURCE).read_text())


def _top(wanted: dict) -> dict:
    return {key: value for key, value in wanted.items() if not isinstance(value, dict)}


def _live(path: Path) -> dict | None:
    original = rules._read(path)
    return tomllib.loads(original.decode()) if original is not None else None


def _trust(live: dict, home: Path) -> str:
    """Whether Codex runs every owned hook: trusted, untrusted or disabled."""
    hooks = live.get("hooks")
    state = hooks.get("state") if isinstance(hooks, dict) else None
    found = set()
    for key, digest in codex_hooks.trust(home):
        entry = state.get(key) if isinstance(state, dict) else None
        if not isinstance(entry, dict):
            found.add("untrusted")
        elif entry.get("enabled") is False:
            found.add("disabled")
        else:
            found.add("trusted" if entry.get("trusted_hash") == digest else "untrusted")
    return next(word for word in ("disabled", "untrusted", "trusted") if word in found)


def status(home: Path, root: Path = ROOT) -> str:
    try:
        live = _live(home / NAME)
        trust = None if live is None else _trust(live, home)
    except OSError, ValueError, SlopmeisterError:
        return "differs"
    if live is None:
        return "missing"
    wanted = _wanted(root)
    features = live.get("features", {})
    same = (
        all(live.get(key) == value for key, value in _top(wanted).items())
        and isinstance(features, dict)
        and features.get("memories") is wanted["features"]["memories"]
        and trust == "trusted"
    )
    return "unchanged" if same else "differs"


def change(home: Path) -> str:
    try:
        live = _live(home / NAME) or {}
        trust = _trust(live, home)
    except OSError, ValueError, SlopmeisterError:
        return f"  unreadable: {NAME}, compared nothing"
    line = f"  {status(home)}: {NAME} {', '.join(_top(_wanted()))}, features.memories, hook trust"
    # The install never changes the operator's own switch, it only names it.
    return line + ("\n  disabled in /hooks: a Slopmeister hook" if trust == "disabled" else "")


def _features(text: str, wanted: bool) -> str:
    parsed = tomllib.loads(text)
    header = re.search(r"(?m)^[ \t]*\[features\][ \t]*(?:#[^\n]*)?$", text)
    if not isinstance(parsed.get("features", {}), dict):
        raise SlopmeisterError(f"unsupported features spelling in {NAME}, nothing written")
    if not header:
        updated = text.rstrip() + f"\n\n[features]\nmemories = {str(wanted).lower()}\n"
        try:
            tomllib.loads(updated)
        except tomllib.TOMLDecodeError:
            raise SlopmeisterError(
                f"unsupported features spelling in {NAME}, nothing written"
            ) from None
        return updated
    start = header.end()
    end = FIRST_TABLE.search(text, start)
    stop = end.start() if end else len(text)
    body = text[start:stop]
    matches = list(re.finditer(r"(?m)^[ \t]*memories[ \t]*=.*$", body))
    if "memories" in parsed["features"] and len(matches) != 1:
        raise SlopmeisterError(f"unsupported memories spelling in {NAME}, nothing written")
    line = f"memories = {str(wanted).lower()}"
    if matches:
        match = matches[0]
        body = body[: match.start()] + line + body[match.end() :]
    else:
        body = "\n" + line + "\n" + body.lstrip("\n")
    return text[:start] + body + text[stop:]


def _trusted(text: str, key: str, digest: str) -> str:
    """Set the trust hash in the entry's own table and leave its other values unchanged."""
    if any(character in key for character in '"\\') or not key.isprintable():
        raise SlopmeisterError(f"unsupported hook path for {NAME}, nothing written")
    header = re.search(rf'(?m)^\[hooks\.state\."{re.escape(key)}"\][ \t]*$', text)
    line = f'trusted_hash = "{digest}"'
    if not header:
        return text.rstrip("\n") + f'\n\n[hooks.state."{key}"]\n{line}\n'
    start = header.end()
    end = FIRST_TABLE.search(text, start)
    stop = end.start() if end else len(text)
    body = text[start:stop]
    matches = list(re.finditer(r"(?m)^[ \t]*trusted_hash[ \t]*=.*$", body))
    if len(matches) > 1:
        raise SlopmeisterError(f"unsupported trusted_hash spelling in {NAME}, nothing written")
    if matches:
        body = body[: matches[0].start()] + line + body[matches[0].end() :]
    else:
        body = "\n" + line + body
    return text[:start] + body + text[stop:]


def _all_trusted(text: str, parsed: dict, trust: list[tuple[str, str]]) -> str:
    """Write each trust entry and record it in the parsed copy the result is verified against."""
    state = parsed.setdefault("hooks", {}).setdefault("state", {})
    for key, digest in trust:
        text = _trusted(text, key, digest)
        state.setdefault(key, {})["trusted_hash"] = digest
    return text


def _updated(text: str, wanted: dict, trust: list[tuple[str, str]]) -> str:
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise SlopmeisterError(f"invalid {NAME}, nothing written") from error
    split = table.start() if (table := FIRST_TABLE.search(text)) else len(text)
    prefix, suffix = text[:split], text[split:]
    for key, value in _top(wanted).items():
        matches = list(re.finditer(rf"(?m)^{key}[ \t]*=.*$", prefix))
        if key in parsed and len(matches) != 1:
            raise SlopmeisterError(f"unsupported {key} spelling in {NAME}, nothing written")
        line = f"{key} = {value}"
        if matches:
            prefix = prefix[: matches[0].start()] + line + prefix[matches[0].end() :]
        else:
            prefix = line + "\n" + prefix
        parsed[key] = value
    updated = _features(prefix + suffix, wanted["features"]["memories"])
    parsed.setdefault("features", {})["memories"] = wanted["features"]["memories"]
    try:
        updated = _all_trusted(updated, parsed, trust)
        same = tomllib.loads(updated) == parsed
    except AttributeError, TypeError, tomllib.TOMLDecodeError:
        same = False
    if not same:
        raise SlopmeisterError(f"could not verify owned settings in {NAME}, nothing written")
    return updated


def install(home: Path, backups: Path, root: Path = ROOT) -> None:
    destination = home / NAME
    try:
        original = rules._read(destination)
        text = original.decode() if original is not None else ""
    except OSError, ValueError:
        raise SlopmeisterError(f"unreadable or unsafe {NAME}, nothing written") from None
    updated = _updated(text, _wanted(root), codex_hooks.trust(home))
    if original is not None:
        rules._backup(backups, NAME, original)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=destination.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        if rules._read(destination) != original:
            raise SlopmeisterError(f"{NAME} changed during install; nothing replaced")
        os.replace(temporary, destination)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
