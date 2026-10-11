"""Isolate review artifacts and installed reviewer binaries."""

from pathlib import Path
import subprocess

import pytest

import slopmeister.review.run as review_run


@pytest.fixture(autouse=True)
def isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    popen = subprocess.Popen

    def isolated(argv, *args, **kwargs):
        if isinstance(argv, (list, tuple)) and Path(argv[0]).name in {"claude", "codex"}:
            executable = Path(argv[0])
            assert executable.is_absolute() and executable.is_relative_to(tmp_path)
        return popen(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", isolated)


@pytest.fixture(autouse=True)
def placeholder_worktree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only a repository under the test's own directory is read, never this checkout."""
    real = review_run._worktree

    def worktree(cwd: str) -> tuple[str, bool]:
        own = Path(cwd).resolve().is_relative_to(tmp_path.resolve())
        return real(cwd) if own else ("tree", False)

    monkeypatch.setattr(review_run, "_worktree", worktree)
