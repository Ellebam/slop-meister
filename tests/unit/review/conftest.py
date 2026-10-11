"""Keep unit review tests away from installed reviewer binaries."""

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

    def forbidden(*args, **kwargs):
        raise AssertionError("unit test attempted to launch a process")

    monkeypatch.setattr(subprocess, "Popen", forbidden)


@pytest.fixture(autouse=True)
def placeholder_worktree(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(review_run, "_worktree", lambda cwd: ("tree", False))
