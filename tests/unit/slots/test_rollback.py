"""A failed slot:up removes the branch it created, and never another branch."""

from pathlib import Path

from slopmeister.slots import allocation, rollback
from tests.support import repos


def _failed_launch(tmp_path, *, delivered: bool = True) -> tuple[Path, allocation.Claim, str]:
    root = repos.scratch_repo(tmp_path / "repo").resolve()
    start = repos.git(root, "rev-parse", "HEAD").strip()
    repos.git(root, "worktree", "add", "-q", "-b", "scratch-one", ".worktrees/scratch-one")
    worktree = root / ".worktrees/scratch-one"
    data = tmp_path / "scratch-slot1"
    data.mkdir()
    (data / allocation.ALLOCATION).write_text("SLOT=1\n")
    (worktree / allocation.ALLOCATION).write_text("SLOT=1\n" if delivered else "SLOT=2\n")
    live = allocation.Live("scratch", 1, "scratch-one", worktree)
    return root, allocation.Claim(live, data, None, {}), start


def _branch(root: Path) -> bool:
    return bool(repos.git(root, "branch", "--list", "scratch-one").strip())


def test_rollback_removes_the_branch_it_created_so_the_name_can_be_retried(tmp_path):
    """Bug: the rollback kept the branch and the same session name was refused forever."""
    root, claim, start = _failed_launch(tmp_path)
    rollback.run(claim, start)
    assert not claim.live.worktree.exists() and not claim.data.exists()
    assert not _branch(root)


def test_rollback_keeps_a_branch_that_gained_a_commit(tmp_path):
    """Bug: the rollback deleted a branch that already carried work."""
    root, claim, start = _failed_launch(tmp_path)
    repos.git(claim.live.worktree, "commit", "-q", "--allow-empty", "-m", "Work")
    rollback.run(claim, start)
    assert _branch(root)


def test_rollback_keeps_a_branch_another_launch_created(tmp_path):
    """Bug: a launch refused before it created anything deleted a concurrent run's branch."""
    root, claim, start = _failed_launch(tmp_path, delivered=False)
    rollback.run(claim, start)
    assert _branch(root)
