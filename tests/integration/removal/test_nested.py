"""Removal does not strand another worktree's records or claim behind a removed parent."""

import json
import os

import pytest

from tests.support.repos import git, scratch_repo


@pytest.mark.parametrize("owner", ["same", "same-linkless", "foreign", "foreign-relative"])
def test_nested_registered_worktree_refuses_container_deletion(workspace, invoke, snapshot, owner):
    """Bug: force deleted a nested claimed worktree and left its registry and claim as ghosts."""
    repo, worktree, _ = workspace
    source = repo if owner.startswith("same") else scratch_repo(repo.parent / "foreign")
    nested = worktree / "inner"
    git(source, "worktree", "add", "-q", "-b", "inner", str(nested))
    receipt = source / ".git/worktrees/inner/slopmeister-config/issue.json"
    receipt.parent.mkdir()
    receipt.write_text(json.dumps({"phase": "claimed", "issue": 9}))
    (nested / "work.txt").write_text("unshipped child work")
    if owner == "foreign-relative":
        metadata = receipt.parent.parent
        pointer = metadata / "gitdir"
        pointer.write_text(os.path.relpath(nested / ".git", metadata) + "\n")
        (nested / ".git").write_text("gitdir: " + os.path.relpath(metadata, nested) + "\n")
    if owner == "same-linkless":
        (nested / ".git").unlink()
    before = snapshot(worktree)
    result = invoke(worktree, "--force")
    assert result.returncode != 0 and snapshot(worktree) == before
    assert receipt.exists()
    if owner != "foreign-relative":
        assert str(nested) in git(source, "worktree", "list")


def test_foreign_git_worktree_is_not_a_forgotten_local_workspace(workspace, invoke, snapshot):
    """Bug: a foreign locked dirty worktree was deleted while its owner still registered it."""
    repo, worktree, _ = workspace
    foreign = scratch_repo(repo.parent / "foreign")
    target = worktree.parent / "foreign"
    git(foreign, "worktree", "add", "-q", "-b", "foreign", str(target))
    git(foreign, "worktree", "lock", str(target))
    (target / "work.txt").write_text("unshipped foreign work")
    before = snapshot(target)
    result = invoke(target, "--force")
    assert result.returncode != 0 and snapshot(target) == before
    assert "locked" in git(foreign, "worktree", "list", "--porcelain")
