"""Removal refuses unsaved work, active ownership and unsafe paths before mutation."""

import json
from pathlib import Path

import pytest

from tests.support.repos import git


@pytest.mark.parametrize("kind", ["tracked", "untracked", "hidden-untracked"])
def test_unsaved_work_is_removed_only_after_explicit_force(workspace, invoke, snapshot, kind):
    repo, worktree, _ = workspace
    if kind == "hidden-untracked":
        git(repo, "config", "status.showUntrackedFiles", "no")
    (worktree / ("README.md" if kind == "tracked" else "unshipped.txt")).write_text("keep me\n")
    before = snapshot(worktree)
    result = invoke(worktree)
    assert result.returncode != 0 and "uncommitted" in result.stderr
    assert snapshot(worktree) == before
    forced = invoke(worktree, "--force")
    assert forced.returncode == 0 and not worktree.exists(), forced.stderr


@pytest.mark.parametrize("phase", ["claimed", "closing", "unknown", "corrupt"])
def test_active_or_unreadable_claim_never_loses_its_workspace(workspace, invoke, snapshot, phase):
    repo, worktree, _ = workspace
    receipt = repo / ".git/worktrees/scratch/slopmeister-config/issue.json"
    receipt.parent.mkdir(exist_ok=True)
    receipt.write_text("{" if phase == "corrupt" else json.dumps({"phase": phase, "issue": 7}))
    before = snapshot(worktree)
    result = invoke(worktree, "--force")
    assert result.returncode != 0 and snapshot(worktree) == before
    assert receipt.is_file()


def test_missing_git_link_does_not_hide_an_active_claim(workspace, invoke, snapshot):
    repo, worktree, _ = workspace
    receipt = repo / ".git/worktrees/scratch/slopmeister-config/issue.json"
    receipt.parent.mkdir(exist_ok=True)
    receipt.write_text(json.dumps({"phase": "claimed", "issue": 7}))
    (worktree / ".git").unlink()
    before = snapshot(worktree)
    refused = invoke(worktree, "--force")
    assert refused.returncode != 0 and "claim" in refused.stderr
    assert snapshot(worktree) == before and receipt.exists()


def test_worktree_local_receipt_cannot_release_the_metadata_claim(workspace, invoke, snapshot):
    """Bug: a worker-created released receipt hid its active claim from both cleanup routes."""
    repo, worktree, _ = workspace
    receipt = repo / ".git/worktrees/scratch/slopmeister-config/issue.json"
    receipt.parent.mkdir(exist_ok=True)
    receipt.write_text(json.dumps({"phase": "claimed", "issue": 7}))
    local = worktree / ".slopmeister-config/issue.json"
    local.parent.mkdir()
    local.write_text(json.dumps({"phase": "released", "issue": 7}))
    with (repo / ".git/info/exclude").open("a") as stream:
        stream.write(".slopmeister-config\n")
    before = snapshot(worktree)
    for flags in ([], ["--force"]):
        result = invoke(worktree, *flags)
        assert result.returncode != 0 and "claim" in result.stderr
        assert snapshot(worktree) == before and receipt.exists()


def test_detached_commits_require_explicit_loss_confirmation(workspace, invoke, snapshot):
    """Bug: clean detached commits became unreachable when their only worktree was removed."""
    repo, worktree, _ = workspace
    git(worktree, "checkout", "--detach", "-q")
    git(worktree, "commit", "--allow-empty", "-q", "-m", "Detached")
    before = snapshot(worktree)
    result = invoke(worktree)
    assert result.returncode != 0 and "detached" in result.stderr
    assert snapshot(worktree) == before
    assert invoke(worktree, "--force").returncode == 0
    assert not worktree.exists() and "scratch" in git(repo, "branch", "--list")


@pytest.mark.parametrize("kind", ["leaf", "managed-root"])
def test_symlinked_managed_paths_do_not_unlock_or_delete_targets(workspace, invoke, snapshot, kind):
    repo, worktree, _ = workspace
    before = snapshot(worktree)
    alias = repo / ".worktrees/link"
    if kind == "managed-root":
        moved = repo / "real-worktrees"
        worktree.parent.rename(moved)
        worktree.parent.symlink_to(moved, target_is_directory=True)
        alias = worktree
        target = moved / "scratch"
    else:
        alias.symlink_to(worktree, target_is_directory=True)
        target = worktree
    result = invoke(alias, "--force")
    assert result.returncode != 0 and "symlink" in result.stderr
    assert snapshot(target) == before


def test_slot_is_routed_by_name_without_removing_its_workspace(workspace, invoke, snapshot):
    _, worktree, _ = workspace
    (worktree / ".slot.env").write_text("SLOT=1\nSLOT_TARGET=slopmeister\nSLOT_NAME=scratch\n")
    before = snapshot(worktree)
    result = invoke(worktree, "--force")
    assert result.returncode != 0 and "slot:down" in result.stderr
    assert "slopmeister scratch" in result.stderr and snapshot(worktree) == before


@pytest.mark.parametrize("kind", ["same-name", "corrupt"])
def test_unrelated_slot_state_cannot_block_a_plain_workspace(workspace, invoke, kind):
    """Bug: a foreign same-name allocation or malformed unrelated record blocked plain removal."""
    _, worktree, env = workspace
    state = Path(env["SLOT_STATE_DIR"]) / "other-slot3/.slot.env"
    state.parent.mkdir(parents=True)
    state.write_text(
        "bad" if kind == "corrupt" else "SLOT=3\nSLOT_TARGET=other\nSLOT_NAME=scratch\n"
    )
    result = invoke(worktree)
    assert result.returncode == 0 and not worktree.exists(), result.stderr
    assert state.exists()


def test_saved_slot_allocation_refuses_when_its_local_file_is_lost(workspace, invoke, snapshot):
    """Bug: losing the local allocation let plain removal strand the saved slot resources."""
    repo, worktree, _ = workspace
    state = repo / ".git/worktrees/scratch/slopmeister-config/state.json"
    state.parent.mkdir(exist_ok=True)
    state.write_text(json.dumps({"allocation": ".slot.env", "plot": "slopmeister"}))
    before = snapshot(worktree)
    result = invoke(worktree, "--force")
    assert result.returncode != 0 and "slot:down" in result.stderr
    assert snapshot(worktree) == before and state.exists()


def test_git_lock_is_not_overridden_by_confirmation(workspace, invoke, snapshot):
    repo, worktree, _ = workspace
    git(repo, "worktree", "lock", str(worktree))
    before = snapshot(worktree)
    result = invoke(worktree, "--force")
    assert result.returncode != 0 and "locked" in result.stderr
    assert snapshot(worktree) == before and "locked" in git(repo, "worktree", "list", "--porcelain")


def test_git_lock_refuses_self_cleanup_before_caller_shutdown(workspace, invoke, snapshot):
    """Bug: self-cleanup stopped its worker before discovering a Git lock."""
    repo, worktree, _ = workspace
    git(repo, "worktree", "lock", str(worktree))
    before = snapshot(worktree)
    result = invoke(worktree, "--self", "--force")
    assert result.returncode != 0 and "locked" in result.stderr
    assert snapshot(worktree) == before


@pytest.mark.parametrize("census", ["occupied", "failed"])
def test_worker_or_failed_census_refuses_before_deletion(workspace, invoke, snapshot, census):
    _, worktree, env = workspace
    binaries = Path(env["PATH"].split(":")[0])
    script = "#!/bin/sh\nexit 1\n"
    if census == "occupied":
        script = """#!/bin/sh
case "$*" in
  '-axo pid=,tty=,comm=') echo '123456 ?? codex' ;;
  '-p 123456 -o lstart=,comm=') echo 'started codex' ;;
  '-p 123456 -o args=') echo 'codex' ;;
esac
"""
        (binaries / "lsof").write_text(f"#!/bin/sh\nprintf 'n%s\\n' '{worktree}'\n")
        (binaries / "lsof").chmod(0o755)
    (binaries / "ps").write_text(script)
    before = snapshot(worktree)
    result = invoke(worktree, "--force")
    assert result.returncode != 0 and snapshot(worktree) == before
    assert "occup" in result.stderr or "inspection" in result.stderr
