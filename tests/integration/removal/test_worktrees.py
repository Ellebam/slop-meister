"""The public command removes locked delivery and recovers failed Git removal."""

import shlex
import stat
import subprocess

from tests.support.repos import git


def test_locked_service_actions_do_not_leave_a_ghost_worktree(workspace, invoke, tmp_path):
    repo, worktree, _ = workspace
    sibling = worktree.parent / "sibling"
    sibling.mkdir()
    (sibling / "kept").write_text("outside bytes")
    sibling.chmod(0o555)
    (worktree / ".claude/service-actions").chmod(0o755)
    (worktree / ".claude/service-actions/outside").symlink_to(sibling)
    (worktree / ".claude/service-actions").chmod(0o555)
    try:
        refused = invoke(worktree)
        assert refused.returncode != 0 and "ignored work" in refused.stderr
        result = invoke(worktree, "--force")
        assert result.returncode == 0, result.stderr
        assert not worktree.exists()
        assert git(repo, "worktree", "list", "--porcelain").count("worktree ") == 1
        assert git(repo, "branch", "--list", "scratch").strip() == "scratch"
        assert stat.S_IMODE(sibling.stat().st_mode) == 0o555
        assert (sibling / "kept").read_text() == "outside bytes"
    finally:
        sibling.chmod(0o755)


def test_stale_git_link_requires_confirmation_then_is_removed(workspace, invoke, snapshot):
    repo, worktree, env = workspace
    failed = subprocess.run(
        ["git", "-C", str(repo), "worktree", "remove", str(worktree)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert failed.returncode != 0 and (worktree / ".git").is_file()
    before = snapshot(worktree)
    refused = invoke(worktree)
    assert refused.returncode != 0 and snapshot(worktree) == before
    assert len(refused.stderr.splitlines()) == 1
    retry = shlex.split(refused.stderr.split("run: ", 1)[1])
    assert retry[-1] == "--force" and "workspace-remove" in retry
    removed = subprocess.run(retry, env=env, capture_output=True, text=True, timeout=30)
    assert removed.returncode == 0, removed.stderr
    assert not worktree.exists()


def test_ancestor_alias_does_not_hide_registration_or_dirty_work(workspace, invoke, tmp_path):
    repo, worktree, _ = workspace
    alias = tmp_path / "alias"
    alias.symlink_to(repo, target_is_directory=True)
    target = alias / ".worktrees/scratch"
    (worktree / "README.md").write_text("unshipped bytes\n")
    refused = invoke(target)
    assert refused.returncode != 0 and "uncommitted" in refused.stderr
    git(worktree, "restore", "README.md")
    removed = invoke(target)
    assert removed.returncode == 0, removed.stderr
    assert not worktree.exists()


def test_linkless_locked_registration_survives_even_force(workspace, invoke, snapshot):
    repo, worktree, _ = workspace
    git(repo, "worktree", "lock", str(worktree))
    (worktree / ".git").unlink()
    (worktree / "README.md").write_text("unsaved work\n")
    before = snapshot(worktree)
    result = invoke(worktree, "--force")
    assert result.returncode != 0 and snapshot(worktree) == before
    assert "locked" in git(repo, "worktree", "list", "--porcelain")
    assert str(worktree) in git(repo, "worktree", "list")


def test_quoted_leftover_retry_is_an_executable_exact_command(workspace, invoke):
    _, worktree, env = workspace
    target = worktree.parent / "retired ' directory"
    target.mkdir()
    result = invoke(target)
    assert result.returncode != 0, result.stdout
    argv = shlex.split(result.stderr.split("run: ", 1)[1])
    assert str(target) in argv
    removed = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=30)
    assert removed.returncode == 0 and not target.exists(), removed.stderr


def test_linkless_registered_workspace_names_repair_and_retries_safely(workspace, invoke, snapshot):
    """Bug: a refused linkless worktree gave only prune as an apparent recovery, losing claims."""
    repo, worktree, _ = workspace
    (worktree / ".git").unlink()
    before = snapshot(worktree)
    result = invoke(worktree, "--force")
    assert result.returncode != 0 and snapshot(worktree) == before
    command = shlex.split(result.stderr.split("repair with: ", 1)[1].strip())
    assert command == ["git", "-C", str(repo), "worktree", "repair"]
    repaired = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert repaired.returncode == 0 and (worktree / ".git").is_file(), repaired.stderr
    removed = invoke(worktree)
    assert removed.returncode == 0 and not worktree.exists(), removed.stderr
