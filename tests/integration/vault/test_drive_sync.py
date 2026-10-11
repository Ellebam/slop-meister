"""The Drive sync command against a recording stand-in for rclone. Nothing is synced."""

import os
from pathlib import Path
import stat
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
SYNC = ROOT / "plots/home/drive/drive-sync.sh"
STAND_IN = """#!/bin/bash
if [ "$1" = version ]; then echo "rclone v${FAKE_VERSION:-1.75.1}"; exit 0; fi
printf '%s\\n' "$@" > "$FAKE_LOG"
exit "${FAKE_EXIT:-0}"
"""
SAFETY = (
    "--max-delete\n2\n",
    "--conflict-resolve\nnewer\n",
    "--conflict-loser\nnum\n",
    "--conflict-suffix\nsync-conflict-linux,sync-conflict-drive\n",
    "--suffix-keep-extension\n",
    "--create-empty-src-dirs\n",
    "--drive-skip-gdocs\n",
    "--drive-skip-shortcuts\n",
    "--resilient\n",
    "--max-lock\n2m\n",
)


class World:
    def __init__(self, root: Path) -> None:
        self.vault, self.documents = root / "vault", root / "My Drive"
        self.state, self.log = root / "state", root / "rclone.args"
        (root / "bin").mkdir()
        rclone = root / "bin/rclone"
        rclone.write_text(STAND_IN)
        rclone.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{root / 'bin'}:/usr/bin:/bin",
            "HOME": str(root / "home"),
            "SLOPMEISTER_VAULT": str(self.vault),
            "DRIVE_SYNC_DOCUMENTS": str(self.documents),
            "DRIVE_SYNC_REMOTE": "drive:",
            "DRIVE_SYNC_STATE": str(self.state),
            "FAKE_LOG": str(self.log),
        }

    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SYNC), *args], env={**self.env, **env}, capture_output=True, text=True, check=False
        )

    def recorded(self) -> str:
        return self.log.read_text() if self.log.exists() else ""


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_vault_run_carries_every_safety_flag_and_private_state(world: World) -> None:
    """Bugs: a guard dropped from the command spreads a mass deletion or loses the older edit,
    and a state folder others can read exposes the names of private documents."""
    assert world.run("vault").returncode == 0
    recorded = world.recorded()
    assert recorded.startswith(f"bisync\n{world.vault}\ndrive:obsidian\n")
    assert f"--workdir\n{world.state}\n" in recorded
    assert [flag for flag in SAFETY if flag not in recorded] == []
    assert "--filter" not in recorded and "--resync" not in recorded and "--force" not in recorded
    assert "--recover" not in recorded and "--resync-mode" not in recorded
    assert stat.S_IMODE(world.state.stat().st_mode) == 0o700


def test_documents_run_leaves_the_vault_folder_to_the_vault_run(world: World) -> None:
    """Bug: the documents run syncs the vault a second time, outside its deletion guard."""
    assert world.run("documents").returncode == 0
    recorded = world.recorded()
    assert recorded.startswith(f"bisync\n{world.documents}\ndrive:\n")
    assert "--filter\n- /obsidian/**\n" in recorded
    assert [flag for flag in SAFETY if flag not in recorded] == []


@pytest.mark.parametrize(
    "args", [(), ("notes",), ("vault", "--recover"), ("vault", "--force", "--resync")]
)
def test_unknown_mode_or_argument_never_reaches_rclone(world: World, args: tuple[str, ...]) -> None:
    """Bug: a typed flag such as --recover passes through and removes the halt on errors."""
    result = world.run(*args)
    assert result.returncode == 2 and "usage" in result.stderr
    assert world.recorded() == ""


def test_rclone_failure_is_the_command_failure(world: World) -> None:
    """Bug: a refused or failed sync exits 0, so the timer and the doctor read it as healthy."""
    assert world.run("vault", FAKE_EXIT="7").returncode == 7
    assert world.run("vault", "--force", FAKE_EXIT="1").returncode == 1
    assert "--force\n" in world.recorded()


def test_resync_refuses_a_folder_that_holds_files(world: World) -> None:
    """Bug: a recovery resync lets an older local file overwrite the newer Drive version."""
    world.vault.mkdir()
    (world.vault / "note.md").write_text("unsynced\n")
    refused = world.run("vault", "--resync")
    assert refused.returncode == 2 and "empty" in refused.stderr
    assert world.recorded() == ""
    (world.vault / "note.md").unlink()
    assert world.run("vault", "--resync").returncode == 0
    assert "--resync\n--resync-mode\nnewer\n" in world.recorded()


@pytest.mark.parametrize(("version", "status"), [("1.74.1", 2), ("1.74.2", 0), ("1.100.0", 0)])
def test_rclone_before_the_conflict_fix_is_refused(world: World, version: str, status: int) -> None:
    """Bug: an older rclone accepts the flags and renames the newer version away too."""
    result = world.run("vault", FAKE_VERSION=version)
    assert result.returncode == status
    assert (world.recorded() == "") == bool(status)
