"""Run-directory primitives shared by launch, supervision and collection."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from slopmeister.paths import ROOT

TIMEOUT_SECONDS = 1800
ENTRY = ROOT / "bin" / "slopmeister"


def save(path: Path, value: dict) -> None:
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".part")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
        check=True,
    )
    return result.stdout.strip()


def command(producer: str, *args: str) -> list[str]:
    """A tester subcommand run through the fixed producer entry."""
    return [sys.executable, producer, "tester", *args]
