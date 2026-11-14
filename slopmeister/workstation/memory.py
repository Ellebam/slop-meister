"""Read-only private-memory diagnosis for normal and relocated client homes."""

from collections.abc import Iterator
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile

from slopmeister import paths
from slopmeister.workstation import codex_config, rules
from slopmeister.workstation.host import Result

MEMORY_READ_LIMIT = 16 * 1024 * 1024


def _memory_paths(root: Path, tool: str, primary: Path) -> Iterator[Path]:
    if root.is_symlink():
        raise OSError("linked configuration root")
    if tool == "codex":
        yield from (
            root / name
            for name in (
                "memories",
                "memories_v2",
                "memories_1.sqlite",
                "memories_1.sqlite-wal",
                "memories_1.sqlite-shm",
            )
        )
        return
    projects = root / "projects"
    if projects.is_symlink():
        # An Orca account home links its history into the normal store, inspected as `primary`.
        if root == primary or projects.resolve() != (primary / "projects").resolve():
            raise OSError("linked projects directory")
        return
    if not projects.exists():
        return
    for project in projects.iterdir():
        if project.is_symlink():
            raise OSError("linked project directory")
        if project.is_dir():
            yield project / "memory"


def _database_populated(path: Path) -> bool:
    # SQLite may write live sidecars even in read-only mode. Query only a private snapshot.
    sources = (path, path.with_name(path.name + "-wal"))
    original = {source: rules._read(source, limit=MEMORY_READ_LIMIT) for source in sources}
    if original[path] is None:
        raise OSError("memory database disappeared")
    with tempfile.TemporaryDirectory(prefix="slopmeister-memory-", dir="/tmp") as directory:
        for source, data in original.items():
            if data is not None:
                copied = Path(directory) / source.name
                copied.write_bytes(data)
                copied.chmod(0o600)
        uri = (Path(directory) / path.name).as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as database:
            database.set_progress_handler(lambda: 1, 10000)
            database.execute("PRAGMA query_only=ON")
            database.execute("PRAGMA trusted_schema=OFF")
            populated = database.execute(
                "SELECT EXISTS(SELECT 1 FROM stage1_outputs) "
                "OR EXISTS(SELECT 1 FROM jobs) "
                "OR EXISTS(SELECT 1 FROM consolidation_progress WHERE max_thread_count > 0)"
            ).fetchone()[0]
        if any(
            rules._read(source, limit=MEMORY_READ_LIMIT) != data
            for source, data in original.items()
        ):
            raise OSError("memory database changed during inspection")
    return bool(populated)


def _directory_populated(path: Path) -> bool:
    pending = [path]
    while pending:
        for entry in pending.pop().iterdir():
            mode = entry.lstat().st_mode
            if stat.S_ISREG(mode):
                return True
            if not stat.S_ISDIR(mode):
                raise OSError("unsafe store entry")
            pending.append(entry)
    return False


def _populated(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    if stat.S_ISDIR(mode):
        return _directory_populated(path)
    if not stat.S_ISREG(mode):
        raise OSError("unsafe store entry")
    if (
        path.name in ("memories_1.sqlite-wal", "memories_1.sqlite-shm")
        and path.with_name("memories_1.sqlite").is_file()
    ):
        return False
    return (
        _database_populated(path) if path.name == "memories_1.sqlite" else path.stat().st_size > 0
    )


def check(home: Path, tool: str) -> Result:
    variable = "CLAUDE_CONFIG_DIR" if tool == "claude" else "CODEX_HOME"
    roots = [home / f".{tool}"]
    if os.environ.get(variable):
        roots.append(Path(os.environ[variable]).expanduser())
    if tool == "codex":
        data = Path(
            os.environ.get("ORCA_USER_DATA_PATH")
            or (
                home / "Library/Application Support/orca"
                if paths.platform() == "darwin"
                else Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "orca"
            )
        )
        roots.append(data / "codex-runtime-home/home")
    fix = "finish any ordered migration, then request memory switch-off and store removal"
    try:
        for root in (path for path in roots[1:] if path != roots[0]):
            if tool == "claude":
                original = rules._read(root / "settings.json")
                live = json.loads(original) if original is not None else {}
                disabled = isinstance(live, dict) and live.get("autoMemoryEnabled") is False
            else:
                live = codex_config._live(root / "config.toml")
                disabled = live is None or (
                    isinstance(live.get("features"), dict)
                    and live["features"].get("memories") is False
                )
            if not disabled:
                return Result(
                    f"memory:{tool}",
                    "problem",
                    f"private memory switch is not false in a secondary {tool} home",
                    fix,
                )
        populated = any(
            _populated(path) for root in roots for path in _memory_paths(root, tool, roots[0])
        )
    except OSError, ValueError, sqlite3.Error:
        return Result(
            f"memory:{tool}",
            "unknown",
            "memory configuration or store metadata is unreadable or unsafe",
            "inspect the metadata and native read access; do not alter the store",
        )
    if populated:
        return Result(f"memory:{tool}", "problem", "private memory store is populated", fix)
    return Result(f"memory:{tool}", "ok", "private memory stores absent or empty", "none")
