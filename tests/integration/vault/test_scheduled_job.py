"""The scheduled job against a scratch vault and repository. Nothing live is touched."""

import fcntl
import os
from pathlib import Path
import subprocess
import time

import pytest

from tests.support.repos import GIT_ENV

ROOT = Path(__file__).resolve().parents[3]
JOB = ROOT / "plots/vault/bin/vault-commit.sh"
LOCK = ROOT / "plots/vault/bin/vault-lock.py"
TWO_DAYS = 2 * 24 * 60 * 60


class World:
    def __init__(self, root: Path) -> None:
        self.vault = root / "drive/vault"
        self.git_dir = root / "vault.git"
        self.log = root / "vault-commit.log"
        self.bundle = root / "drive/Backups/vault-history.bundle"
        (self.vault / "_system").mkdir(parents=True)
        self.note = self.vault / "_system/start.md"
        self.note.write_text("# Start\n")
        self.env = {
            **os.environ,
            **GIT_ENV,
            "HOME": str(root / "home"),
            "SLOPMEISTER_VAULT": str(self.vault),
            "VAULT_GIT_DIR": str(self.git_dir),
            "VAULT_LOG": str(self.log),
            "VAULT_LOCK": str(LOCK),
            "VAULT_NOTIFY": "0",
        }
        self.fresh_repository()

    def fresh_repository(self) -> None:
        subprocess.run(["rm", "-rf", str(self.git_dir)], check=True)
        subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(self.git_dir)], check=True)

    def git(self, *args: str) -> str:
        command = ["git", f"--git-dir={self.git_dir}", f"--work-tree={self.vault}", *args]
        return subprocess.run(
            command, env=self.env, capture_output=True, text=True, check=True
        ).stdout.strip()

    def run(self, locked: bool = True) -> str:
        """One job run, the log it left. `locked` skips the lease like the helper's re-entry."""
        env = {**self.env, **({"SLOPMEISTER_VAULT_LOCKED": "1"} if locked else {})}
        job = subprocess.run([str(JOB)], env=env, capture_output=True, text=True, check=False)
        assert job.returncode == 0, job.stderr
        return self.log.read_text() if self.log.exists() else ""

    def aged_bundle(self) -> tuple[bytes, str]:
        """A bundle of the current history, old enough for the next run to rewrite it."""
        self.bundle.parent.mkdir(parents=True, exist_ok=True)
        self.git("bundle", "create", str(self.bundle), "--all")
        self.age_bundle()
        return self.bundle.read_bytes(), self.git("rev-parse", "HEAD")

    def age_bundle(self) -> None:
        old = time.time() - TWO_DAYS
        os.utime(self.bundle, (old, old))


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_rebuilt_repository_keeps_the_longer_bundle(world: World) -> None:
    """Escaping bug: a fresh one-commit repository overwrites the only copy of the long history."""
    world.run()
    world.note.write_text("# Start\n\nSecond.\n")
    world.run()
    before, old_head = world.aged_bundle()
    world.fresh_repository()
    log = world.run()
    assert world.bundle.read_bytes() == before
    assert "bundle kept" in log and "docs/vault-version-control.md" in log
    assert old_head in world.git("bundle", "list-heads", str(world.bundle))
    assert world.git("rev-list", "--count", "HEAD") == "1"


@pytest.mark.parametrize("damaged", [b"not a bundle\n", b"# v2 git bundle\n"])
def test_unreadable_bundle_is_kept(world: World, damaged: bytes) -> None:
    """Escaping bug: a bundle Git cannot read right now is replaced, and its history with it."""
    world.run()
    world.bundle.write_bytes(damaged)
    world.age_bundle()
    log = world.run()
    assert world.bundle.read_bytes() == damaged and "bundle kept" in log


def test_repository_holding_the_bundle_heads_replaces_it(world: World) -> None:
    """Escaping bug: the guard refuses the normal daily bundle and the backup stops ageing."""
    world.run()
    _, old_head = world.aged_bundle()
    world.note.write_text("# Start\n\nSecond.\n")
    log = world.run()
    new_head = world.git("rev-parse", "HEAD")
    assert new_head != old_head and "bundle kept" not in log
    assert new_head in world.git("bundle", "list-heads", str(world.bundle))


def _refusing_hook(world: World) -> None:
    hook = world.git_dir / "hooks/pre-commit"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text("#!/bin/sh\necho 'refused by the test hook' >&2\nexit 1\n")
    hook.chmod(0o755)


def _locked_index(world: World) -> None:
    (world.git_dir / "index.lock").write_text("")


@pytest.mark.parametrize(
    ("breakage", "line", "cause"),
    [
        (_refusing_hook, "commit failed", "refused by the test hook"),
        (_locked_index, "add failed", "index.lock"),
    ],
)
def test_failed_git_step_logs_its_cause_and_writes_no_bundle(
    world: World, breakage, line: str, cause: str
) -> None:
    """Escaping bug: a failure is logged with no cause, a failed add as nothing to commit."""
    breakage(world)
    log = world.run()
    assert line in log and cause in log
    assert "nothing to commit" not in log and not world.bundle.exists()


def test_busy_lock_leaves_a_line_in_the_log(world: World) -> None:
    """Escaping bug: a run that never started because of the lease leaves no trace."""
    lock = world.git_dir / "slopmeister-coordination/commit.lock"
    lock.parent.mkdir(mode=0o700)
    with lock.open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        log = world.run(locked=False)
    assert "vault transaction busy" in log and "committed" not in log
