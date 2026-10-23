"""Delete a directory tree that holds read-only entries."""

from collections.abc import Callable, Iterator
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

from slopmeister.errors import SlopmeisterError

SCRATCH = ".slopmeister-tmp"
CACHES = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".venv",
    "node_modules",
}
SHOWN_PATHS = 8
IGNORED_ARGS = (
    "ls-files",
    "--others",
    "--ignored",
    "--exclude-standard",
    "--directory",
    "--cached",
    "-v",
    "-z",
)


def _digest(path: Path) -> str:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(descriptor, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_inventory(state_dir: Path) -> dict | None:
    path = state_dir / "state.json"
    if state_dir.is_symlink() or path.is_symlink():
        raise SlopmeisterError("symlinked delivery inventory, refusing removal")
    if not path.exists():
        return None
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor) as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise SlopmeisterError("delivery inventory is not a regular file")
        state = json.load(stream)
    if not isinstance(state, dict) or not isinstance(state.get("files", {}), dict):
        raise SlopmeisterError("unreadable delivery inventory, refusing removal")
    return state


def _recorded(root: Path, state_dir: Path) -> tuple[dict[str, str], bool]:
    state = read_inventory(state_dir)
    if state is None:
        return {}, False
    state_path = state_dir / "state.json"
    known = {
        path: value[0]
        for path, value in state.get("files", {}).items()
        if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str)
    }
    scratch = state.get("scratch") == SCRATCH and state.get("worktree") == str(root)
    if not state_dir.is_relative_to(root):
        return known, scratch
    prefix = state_dir.relative_to(root).as_posix()
    known[prefix + "/state.json"] = _digest(state_path)
    known[prefix + "/config-install.py"] = state.get("helper_sha256", "")
    manifest = state_dir / "snapshot/manifest.json"
    if (
        not manifest.parent.is_symlink()
        and manifest.is_file()
        and not manifest.is_symlink()
        and (digest := _digest(manifest)) == state.get("snapshot_sha256")
    ):
        known[prefix + "/snapshot/manifest.json"] = digest
        entries = json.loads(manifest.read_text())
        if not isinstance(entries, dict):
            raise SlopmeisterError("unreadable snapshot inventory, refusing removal")
        for path, value in entries.items():
            known[prefix + "/snapshot/" + path] = value
    return known, scratch


def _files(
    root: Path, paths: list[str], scratch: bool = False
) -> Iterator[tuple[Path, os.stat_result, str]]:
    """Retain Git's marker so tracked files do not inherit the cache exemption."""
    pending = []
    for entry in paths:
        relative = Path(entry[2:].rstrip("/"))
        if relative.is_absolute() or ".." in relative.parts:
            raise SlopmeisterError("unsafe ignored path, refusing removal")
        pending.append((root / relative, entry[:2]))
    allowed = CACHES | ({SCRATCH} if scratch else set())
    while pending:
        path, marker = pending.pop()
        caches = set() if path.is_relative_to(root / "tmp") else allowed
        try:
            info = path.lstat()
            if marker == "? " and any(
                parent.name in caches and stat.S_ISDIR(parent.lstat().st_mode)
                for parent in path.parents
                if parent != root and parent.is_relative_to(root)
            ):
                continue
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(info.st_mode):
            if path.name not in caches:
                pending.extend((child, marker) for child in path.iterdir())
        else:
            yield path, info, marker


def check_ignored(root: Path, paths: list[str], state_dir: Path) -> None:
    """Only unchanged delivery and disposable caches may disappear without confirmation."""
    known, scratch = _recorded(root, state_dir)
    blocked = []
    for path, info, _marker in _files(root, paths, scratch):
        relative = path.relative_to(root).as_posix()
        if stat.S_ISREG(info.st_mode):
            empty_note = (
                path.parent == root and path.name.endswith("-NOTES.md") and not info.st_size
            )
            saved = known.get(relative)
            if not empty_note and (saved is None or saved != _digest(path)):
                blocked.append(relative)
        else:
            blocked.append(relative)
    if blocked:
        shown = ", ".join(json.dumps(path) for path in sorted(blocked)[:SHOWN_PATHS])
        tail = f" and {len(blocked) - SHOWN_PATHS} more" if len(blocked) > SHOWN_PATHS else ""
        raise SlopmeisterError(f"ignored work: {shown}{tail}; pass --force to confirm deletion")


def remove_tree(root: Path) -> None:
    """Delete root. Only directories inside it become writable, and no symlink is followed."""

    def retry(function: Callable[..., object], path: str, error: BaseException) -> None:
        if not isinstance(error, PermissionError) or function not in (os.unlink, os.rmdir):
            raise error
        parent = Path(path).parent
        if not parent.is_relative_to(root):
            raise error
        mode = parent.lstat().st_mode
        if not stat.S_ISDIR(mode):
            raise error
        # Removing a read-only cache file requires write permission on its directory.
        parent.chmod(mode | stat.S_IWUSR | stat.S_IXUSR, follow_symlinks=False)
        function(path)

    shutil.rmtree(root, onexc=retry)
