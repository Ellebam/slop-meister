"""Fake executables and memory databases for tests."""

import os
from pathlib import Path
import sqlite3


def memory_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(path)
    database.executescript(
        "CREATE TABLE _sqlx_migrations(version INTEGER);"
        "INSERT INTO _sqlx_migrations VALUES(1),(2);"
        "CREATE TABLE stage1_outputs(value TEXT);"
        "CREATE TABLE jobs(value TEXT);"
        "CREATE TABLE consolidation_progress(max_thread_count INTEGER);"
        "INSERT INTO consolidation_progress VALUES(0);"
    )
    database.commit()
    return database


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
