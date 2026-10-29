"""The retained lock helper admits the installed command without weakening its guards."""

from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
LOCK = ROOT / "plots/vault/bin/vault-lock.py"


def call(git_dir: Path, launcher: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(LOCK),
            "--git-dir",
            str(git_dir),
            "--kind",
            "manual",
            *extra,
            "--",
            str(launcher),
        ],
        capture_output=True,
        text=True,
    )


def test_installed_command_is_admitted(tmp_path: Path):
    git_dir = tmp_path / "vault.git"
    git_dir.mkdir()
    launcher = tmp_path / "slopmeister-vault"
    launcher.write_text("#!/bin/sh\nexit 0\n")
    launcher.chmod(0o755)
    assert call(git_dir, launcher, "--path", "free.md").returncode == 0


def test_symlinked_git_and_coordination_are_refused(tmp_path: Path):
    launcher = tmp_path / "slopmeister-vault"
    launcher.write_text("#!/bin/sh\nexit 0\n")
    launcher.chmod(0o755)
    real_git = tmp_path / "real.git"
    real_git.mkdir()
    linked_git = tmp_path / "linked.git"
    linked_git.symlink_to(real_git)
    assert call(linked_git, launcher).returncode != 0
    coordination = real_git / "slopmeister-coordination"
    outside = tmp_path / "outside"
    outside.mkdir()
    coordination.symlink_to(outside)
    assert call(real_git, launcher).returncode != 0


@pytest.mark.parametrize("path", [".", "./", "././", "bad\nname"])
def test_lock_refuses_root_and_control_paths_before_running_command(
    tmp_path: Path, path: str
) -> None:
    git_dir = tmp_path / "vault.git"
    git_dir.mkdir()
    marker = tmp_path / "called"
    launcher = tmp_path / "slopmeister-vault"
    launcher.write_text(f"#!/bin/sh\ntouch {marker!s}\n")
    launcher.chmod(0o755)
    assert call(git_dir, launcher, "--path", path).returncode != 0
    assert not marker.exists()
