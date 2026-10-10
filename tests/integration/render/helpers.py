"""Scratch renderer installations and deterministic tree digests."""

import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def scaffold(tmp_path: Path, fixture: str | None = None) -> Path:
    root = tmp_path / "slopmeister"
    shutil.copytree(ROOT / "slopmeister", root / "slopmeister")
    (root / "bin").mkdir(parents=True)
    shutil.copy2(ROOT / "bin/slopmeister", root / "bin/slopmeister")
    (root / "src/skills").mkdir(parents=True)
    if fixture:
        shutil.copytree(
            ROOT / "tests/data" / fixture,
            root / ("plots" if fixture == "plot-fixtures" else "src/skills"),
            dirs_exist_ok=True,
        )
    return root


def run_render(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "bin/slopmeister", "render", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def digest(path: Path) -> str:
    result = hashlib.sha256()
    for file in sorted(item for item in path.rglob("*") if item.is_file()):
        result.update(str(file.relative_to(path)).encode())
        result.update(b"\0")
        result.update(file.read_bytes())
    return result.hexdigest()
