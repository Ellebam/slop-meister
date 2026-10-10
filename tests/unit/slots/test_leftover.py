"""A leftover directory is guarded, and a failed removal keeps the state a rerun needs."""

from pathlib import Path
import stat
import subprocess

import pytest

from slopmeister.errors import SlopmeisterError
from slopmeister.slots import allocation, down, leftover
from tests.unit.slots.test_allocation import slot_identity

FORCED = down.Request("repo", "scratch", "scratch-one", True, "1")


def _slot(tmp_path, monkeypatch, output: str = "", code: int = 0) -> Path:
    """A scratch slot whose every subprocess returns the given result."""
    worktree = slot_identity(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(allocation, "definition", lambda target: {"ports": {"WEB": 4000}})
    monkeypatch.setattr(allocation, "main_root", lambda repo: tmp_path / "repo")
    result = subprocess.CompletedProcess([], code, output, output)
    monkeypatch.setattr(allocation, "run", lambda argv, **kwargs: result)
    return worktree


def test_down_refuses_a_leftover_that_a_worker_occupies(tmp_path, monkeypatch):
    """Bug: a directory Git let go of was deleted under a running worker."""
    worktree = _slot(tmp_path, monkeypatch, "claude pid 42\n")
    (worktree / allocation.ALLOCATION).unlink()
    with pytest.raises(SlopmeisterError, match="worker still occupies"):
        down._release(FORCED)
    assert worktree.is_dir() and (tmp_path / "slots/scratch-slot1").is_dir()


def test_down_keeps_a_worktree_and_its_state_when_git_refuses(tmp_path, monkeypatch):
    """Bug: the fallback wiped a worktree Git refused to remove, or lost the rerun's state."""
    worktree = _slot(tmp_path, monkeypatch)
    (worktree / ".git").write_text("gitdir: elsewhere\n")
    refusal = "fatal: cannot remove a locked working tree"

    def run(argv, **kwargs):
        code = 128 if "remove" in argv else 0
        output = f"worktree {worktree}\0\0" if "list" in argv else ""
        return subprocess.CompletedProcess(argv, code, output, refusal)

    monkeypatch.setattr(allocation, "run", run)
    monkeypatch.setattr(down, "_context", lambda request: ({}, tmp_path / "repo", worktree, 1))
    with pytest.raises(SlopmeisterError, match="locked working tree"):
        down._release(FORCED)
    assert (worktree / allocation.ALLOCATION).is_file()
    assert (tmp_path / "slots/scratch-slot1" / allocation.ALLOCATION).is_file()


def test_failed_deletion_names_the_rerun_that_then_finishes(tmp_path, monkeypatch):
    """Bug: teardown ended with 'git failed', the state was gone and no rerun could finish."""
    worktree = _slot(tmp_path, monkeypatch)
    (worktree / allocation.ALLOCATION).unlink()
    (worktree / "stuck").write_text("cache")
    state = tmp_path / "slots/scratch-slot1"

    def refuse(root):
        raise PermissionError(13, "Permission denied", str(root / "stuck"))

    with monkeypatch.context() as patched:
        patched.setattr(leftover, "remove_tree", refuse)
        with pytest.raises(SlopmeisterError) as refusal:
            down._release(FORCED)
    message = str(refusal.value)
    assert str(worktree / "stuck") in message and "Permission denied" in message
    rerun = f"task slot:down -- {tmp_path / 'repo'} scratch scratch-one --slot 1 --force"
    assert message.endswith(f"run: {rerun}")
    assert worktree.is_dir() and state.is_dir()
    assert down._release(FORCED) == 0
    assert not worktree.exists() and not state.exists()


def test_removal_never_unlocks_the_directory_above_the_worktree(tmp_path, monkeypatch):
    """Bug: removal made a directory outside the worktree writable to finish the deletion."""
    worktree = _slot(tmp_path, monkeypatch, "fatal: not a working tree", 128)
    (worktree / allocation.ALLOCATION).unlink()
    old_run = allocation.run
    monkeypatch.setattr(
        allocation,
        "run",
        lambda argv, **kwargs: (
            subprocess.CompletedProcess(argv, 0, "", "")
            if "list" in argv
            else old_run(argv, **kwargs)
        ),
    )
    worktree.parent.chmod(0o555)
    try:
        with pytest.raises(SlopmeisterError, match="not fully removed"):
            leftover.remove(worktree, "rerun")
        assert stat.S_IMODE(worktree.parent.stat().st_mode) == 0o555 and worktree.is_dir()
    finally:
        worktree.parent.chmod(0o755)


def test_git_inventory_keeps_a_locked_worktree_without_its_git_link(tmp_path, monkeypatch):
    """Bug: the link-only check deleted a locked directory while Git still registered it."""
    worktree = _slot(tmp_path, monkeypatch)

    def run(argv, **kwargs):
        if "list" in argv:
            return subprocess.CompletedProcess(argv, 0, f"worktree {worktree}\0locked\0", "")
        return subprocess.CompletedProcess(argv, 128, "", "fatal: locked working tree")

    monkeypatch.setattr(allocation, "run", run)
    with pytest.raises(SlopmeisterError, match="locked working tree"):
        leftover.remove(worktree, "rerun")
    assert worktree.is_dir()
