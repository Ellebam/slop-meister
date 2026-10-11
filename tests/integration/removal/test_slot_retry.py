"""Existing slot teardown recovers a locked tree that plain deletion leaves linkless."""

from pathlib import Path
import subprocess

import pytest

from tests.support.repos import git

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def slot_leftover(workspace):
    repo, worktree, env = workspace
    identity = "SLOT=1\nSLOT_TARGET=slopmeister\nSLOT_NAME=scratch\n"
    (worktree / ".slot.env").write_text(identity)
    state = Path(env["SLOT_STATE_DIR"]) / "slopmeister-slot1"
    state.mkdir(parents=True)
    (state / ".slot.env").write_text(identity)
    declarations = repo.parent / "plots/slopmeister"
    declarations.mkdir(parents=True)
    (declarations / "plot.toml").write_text(
        '[plot]\nbase = "code"\n[target]\ntasks = "manual"\n'
        '[target.repository]\ncommit = "allow"\n[slots.ports]\nWEB = 21001\n'
    )
    env["PLOT_DECLARATIONS"] = str(declarations.parent)
    return repo, worktree, env, state


def test_slot_down_releases_a_prunable_linkless_leftover(slot_leftover):
    """Bug: the inventory guard held a stale unlocked record and stranded the slot forever."""
    repo, worktree, env, state = slot_leftover
    failed = subprocess.run(["rm", "-rf", str(worktree)], env=env, capture_output=True, timeout=30)
    assert failed.returncode != 0 and not (worktree / ".git").exists()
    assert "prunable" in git(repo, "worktree", "list", "--porcelain")
    result = subprocess.run(
        [
            str(ROOT / "bin/slopmeister"),
            "slots",
            "down",
            str(repo),
            "slopmeister",
            "scratch",
            "--slot",
            "1",
            "--force",
        ],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not worktree.exists() and not state.exists()
    assert "scratch" not in git(repo, "worktree", "list")
