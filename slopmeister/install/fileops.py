"""Write and replace configuration payload paths."""

from pathlib import Path
import shutil


def remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def write_file(path: Path, value: tuple[bytes, int]) -> None:
    content, mode = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(mode)


def lock_service_actions(repo: Path, enabled: bool) -> None:
    if not enabled:
        return
    for native in (".codex", ".claude"):
        root = repo / native / "service-actions"
        for path in [root, *root.rglob("*")]:
            if path.is_dir():
                path.chmod(0o555)
