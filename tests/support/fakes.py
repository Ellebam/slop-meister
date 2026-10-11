"""Fake executables on PATH. A test records what the product invoked and answers as it likes."""

import os
from pathlib import Path


def fake_binary(directory: Path, name: str, script: str) -> Path:
    """Write an executable `name` under `directory` whose body is `script`, a bash fragment."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("#!/bin/bash\n" + script + "\n")
    path.chmod(0o755)
    return path


def path_with(directory: Path) -> str:
    """A PATH value that finds `directory` first and the real tools after it."""
    return f"{directory}{os.pathsep}{os.environ.get('PATH', '')}"
