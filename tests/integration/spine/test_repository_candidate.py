"""Repository candidates preserve exact uncommitted Git state without source mutation."""

import json
import os
from pathlib import Path
import stat
import subprocess

import pytest

from slopmeister.spine import candidate
from tests.support.repos import git


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "subject"
    root.mkdir()
    git(root, "init", "-qb", "task-267")
    (root / ".gitignore").write_text("ignored.lock\n")
    (root / "changed.txt").write_text("before\n")
    (root / "deleted.txt").write_text("delete me\n")
    (root / "delivered.txt").write_text("source configuration\n")
    (root / "mode.sh").write_text("#!/bin/sh\nexit 0\n")
    git(root, "add", ".gitignore", "changed.txt", "deleted.txt", "delivered.txt", "mode.sh")
    git(root, "commit", "-qm", "Create fixture")
    git(root, "update-index", "--skip-worktree", "delivered.txt")
    return root


def change_worktree(repo: Path) -> None:
    (repo / "changed.txt").write_text("after\n")
    (repo / "deleted.txt").unlink()
    (repo / "mode.sh").chmod(0o755)
    (repo / "delivered.txt").write_text("delivered session copy\n")
    (repo / "new.txt").write_text("new\n")
    (repo / "link").symlink_to("changed.txt")
    (repo / "ignored.lock").write_text("runtime\n")


def test_freeze_preserves_branch_and_real_index_while_capturing_git_visible_tree(repo, tmp_path):
    change_worktree(repo)
    branch = git(repo, "branch", "--show-current").strip()
    index = (repo / ".git/index").read_bytes()
    os.utime(repo / ".gitignore")
    frozen = candidate.freeze(repo, "task-267")

    assert git(repo, "branch", "--show-current").strip() == branch
    assert (repo / ".git/index").read_bytes() == index
    assert frozen.scope == (
        "changed.txt",
        "deleted.txt",
        "link",
        "mode.sh",
        "new.txt",
    )
    checkout = tmp_path / "checkout"
    candidate.materialize(frozen, checkout)
    assert (checkout / "changed.txt").read_text() == "after\n"
    assert not (checkout / "deleted.txt").exists()
    # Checkout applies the process umask, so assert the executable bit Git recorded, not 0o755.
    assert stat.S_IMODE((checkout / "mode.sh").stat().st_mode) & stat.S_IXUSR
    assert (checkout / "link").is_symlink()
    assert os.readlink(checkout / "link") == "changed.txt"
    assert (checkout / "new.txt").read_text() == "new\n"
    assert (checkout / "delivered.txt").read_text() == "source configuration\n"
    assert not (checkout / "ignored.lock").exists()
    assert candidate.worktree_tree(checkout) == frozen.tree


def test_live_checkout_drift_does_not_change_frozen_candidate(repo, tmp_path):
    change_worktree(repo)
    frozen = candidate.freeze(repo, "task-267")
    (repo / "changed.txt").write_text("later workspace churn\n")
    (repo / "ignored.lock").write_text("later runtime churn\n")

    loaded = candidate.load(repo, "task-267")
    checkout = tmp_path / "checkout"
    candidate.materialize(loaded, checkout)

    assert loaded == frozen
    assert (checkout / "changed.txt").read_text() == "after\n"


def test_private_candidate_ref_survives_gc_without_a_source_commit_or_ref(repo):
    change_worktree(repo)
    frozen = candidate.freeze(repo, "task-267")
    subprocess.run(["git", "--git-dir", str(frozen.repository), "gc", "--prune=now"], check=True)
    assert candidate.load(repo, "task-267") == frozen
    assert not git(repo, "for-each-ref", "--format=%(refname)", "refs/slopmeister").strip()


def test_candidate_tamper_is_rejected(repo):
    change_worktree(repo)
    frozen = candidate.freeze(repo, "task-267")
    manifest = json.loads(frozen.manifest.read_text())
    manifest["tree"] = "0" * 40
    frozen.manifest.write_text(json.dumps(manifest))
    frozen.manifest.chmod(0o600)

    with pytest.raises(ValueError, match="candidate tree"):
        candidate.load(repo, "task-267")


def test_operator_commit_must_match_proven_tree_without_repeating_proof(repo):
    change_worktree(repo)
    frozen = candidate.freeze(repo, "task-267")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "Freeze candidate")
    commit = git(repo, "rev-parse", "HEAD").strip()

    assert candidate.verify_commit(frozen, commit) == commit
    (repo / "changed.txt").write_text("different\n")
    git(repo, "add", "changed.txt")
    git(repo, "commit", "-qm", "Change candidate")

    with pytest.raises(ValueError, match="does not match frozen candidate"):
        candidate.verify_commit(frozen, "HEAD")
