"""Manage the one Codex configuration value owned by Slopmeister."""

import os
from pathlib import Path
import re
import shutil
import tempfile
import tomllib

from slopmeister.errors import SlopmeisterError
from slopmeister.paths import ROOT

NAME = ".codex/config.toml"
SOURCE = "dist/codex/config.toml"
KEY = "model_context_window"
ASSIGNMENT = re.compile(rf"(?m)^{KEY}[ \t]*=.*$")
FIRST_TABLE = re.compile(r"(?m)^\s*\[")


def _wanted(root: Path = ROOT) -> int:
    return tomllib.loads((root / SOURCE).read_text())[KEY]


def _live(home: Path) -> dict | None:
    path = home / NAME
    if not path.is_file():
        return None
    return tomllib.loads(path.read_text())


def status(home: Path, root: Path = ROOT) -> str:
    try:
        live = _live(home)
    except OSError, tomllib.TOMLDecodeError:
        return "differs"
    if live is None:
        return "missing"
    return "unchanged" if live.get(KEY) == _wanted(root) else "differs"


def change(home: Path) -> str:
    path = home / NAME
    if path.is_file():
        try:
            tomllib.loads(path.read_text())
        except OSError, tomllib.TOMLDecodeError:
            return f"  unreadable: {NAME}, compared nothing"
    return f"  {status(home)}: {NAME} {KEY}"


def _updated(text: str, wanted: int) -> str:
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise SlopmeisterError(f"invalid {NAME}, nothing written") from error
    table = FIRST_TABLE.search(text)
    split = table.start() if table else len(text)
    prefix, suffix = text[:split], text[split:]
    matches = list(ASSIGNMENT.finditer(prefix))
    if KEY in parsed and len(matches) != 1:
        raise SlopmeisterError(f"unsupported {KEY} spelling in {NAME}, nothing written")
    line = f"{KEY} = {wanted}"
    if matches:
        match = matches[0]
        prefix = prefix[: match.start()] + line + prefix[match.end() :]
    else:
        prefix = line + "\n" + prefix
    updated = prefix + suffix
    if tomllib.loads(updated).get(KEY) != wanted:
        raise SlopmeisterError(f"could not verify {KEY} in {NAME}, nothing written")
    return updated


def install(home: Path, backups: Path, root: Path = ROOT) -> None:
    destination = home / NAME
    text = destination.read_text() if destination.is_file() else ""
    updated = _updated(text, _wanted(root))
    if destination.is_file():
        backups.mkdir(parents=True, exist_ok=True, mode=0o700)
        backups.chmod(0o700)
        saved = backups / NAME
        saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        saved.parent.chmod(0o700)
        shutil.copy2(destination, saved)
        saved.chmod(0o600)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=destination.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
