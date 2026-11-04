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


def _fixture_repository(scratch, outside, layout):
    """A fixture repository in scratch whose checkout or worktree may lie outside it."""
    if layout == "dotgit":
        (scratch / "project").mkdir(parents=True)
        git(
            scratch, "init", "-q", "--separate-git-dir", str(scratch / "project/.git"), str(outside)
        )
        git(outside, "commit", "-q", "--allow-empty", "-m", "init")
        git(outside, "worktree", "add", "-q", "-b", "inner", str(scratch / "inner"))
        return
    project = scratch_repo(scratch / "project")
    if layout == "inside":
        git(project, "worktree", "add", "-q", "-b", "inner", str(project / ".worktrees/inner"))
    else:
        git(project, "worktree", "add", "-q", "-b", "outside", str(outside))


@pytest.mark.parametrize("layout", ["inside", "external", "unreadable", "dotgit"])
def test_fixture_repository_in_scratch_never_strands_a_worktree(
    workspace, invoke, snapshot, layout
):
    """Bug: removal deleted Git metadata that a checkout outside the workspace still used."""
    repo, worktree, _ = workspace
    with (repo / ".git/info/exclude").open("a") as stream:
        stream.write("/.slopmeister-tmp/\n")
    scratch = worktree / ".slopmeister-tmp/pytest-of-user"
    outside = repo.parent / "outside"
    _fixture_repository(scratch, outside, layout)
    registration = scratch / "project/.git/worktrees/outside"
    before = snapshot(worktree)
    mode = registration.stat().st_mode if layout == "unreadable" else 0
    if layout == "unreadable":
        registration.chmod(0)
    try:
        result = invoke(worktree, "--force")
    finally:
        if layout == "unreadable":
            registration.chmod(mode)
    assert result.returncode != 0, result.stderr
    assert "nested linked worktree" in result.stderr or "Permission denied" in result.stderr
    assert snapshot(worktree) == before
    if layout != "inside":
        assert git(outside, "rev-parse", "HEAD")


def test_separate_git_dir_repository_with_an_outside_worktree_refuses(workspace, invoke):
    """Bug: a nested repository's metadata inside the tree is deleted under an outside worktree."""
    repo, worktree, _ = workspace
    nested = worktree / "inner"
    nested.mkdir()
    metadata = worktree / "inner-metadata"
    git(nested, "init", "-q", "--separate-git-dir", str(metadata))
    git(nested, "commit", "-q", "--allow-empty", "-m", "Initial")
    outside = repo.parent / "outside"
    git(nested, "worktree", "add", "-q", "-b", "outside", str(outside))
    result = invoke(worktree, "--force")
    assert result.returncode != 0 and "nested linked worktree" in result.stderr
    assert outside.is_dir() and metadata.is_dir()


@pytest.mark.parametrize("kind", ["symlink", "pipe"])
@pytest.mark.parametrize("layout", ["link", "registration"])
def test_nested_git_metadata_that_is_no_file_refuses(workspace, invoke, tmp_path, kind, layout):
    """Bug: a symlinked link hides a nested worktree, and a pipe hangs the read."""
    _, worktree, _ = workspace
    nested = worktree / "inner"
    nested.mkdir()
    pointer = nested / ".git"
    if layout == "registration":
        pointer = pointer / "worktrees/inner/gitdir"
        pointer.parent.mkdir(parents=True)
    if kind == "symlink":
        target = tmp_path / "gitfile"
        target.write_text("gitdir: /nowhere\n")
        pointer.symlink_to(target)
    else:
        os.mkfifo(pointer)
    result = invoke(worktree, "--force")
    assert result.returncode != 0 and "is not a file" in result.stderr
    assert worktree.is_dir()
