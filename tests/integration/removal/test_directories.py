"""Retired dispatcher trees use the same deletion without admitting arbitrary roots."""

from pathlib import Path

import pytest

from slopmeister.install.fileops import lock_service_actions
from tests.support.repos import git


def test_locked_dispatcher_tree_does_not_survive_removal(workspace, invoke):
    _, _, env = workspace
    retired = Path(env["PLOT_SESSION_ROOT"]) / "retired"
    for native in (".claude", ".codex"):
        action = retired / native / "service-actions/jira-read"
        action.mkdir(parents=True)
        (action / "entry.py").touch()
    lock_service_actions(retired, True)
    refused = invoke(retired)
    assert refused.returncode != 0 and "ignored work" in refused.stderr
    result = invoke(retired, "--force")
    assert result.returncode == 0 and not retired.exists(), result.stderr


@pytest.mark.parametrize("kind", ["outside", "repository", "worktrees", "sessions", "nested"])
def test_force_does_not_admit_unsupported_roots(workspace, invoke, snapshot, tmp_path, kind):
    repo, worktree, env = workspace
    candidates = {
        "outside": tmp_path / "outside",
        "repository": repo,
        "worktrees": worktree.parent,
        "sessions": Path(env["PLOT_SESSION_ROOT"]),
        "nested": worktree / ".claude",
    }
    target = candidates[kind]
    target.mkdir(exist_ok=True)
    before = snapshot(target)
    result = invoke(target, "--force")
    assert result.returncode != 0 and snapshot(target) == before


@pytest.mark.parametrize("kind", ["entry", "container"])
def test_unverified_orca_trash_layout_is_refused(workspace, invoke, snapshot, kind):
    _, worktree, _ = workspace
    target = worktree.parent / ".orca-worktree-trash/scratch"
    target.mkdir(parents=True)
    (target / "notes").write_text("unshipped work")
    if kind == "container":
        target = target.parent
    before = snapshot(target)
    result = invoke(target, "--force")
    assert result.returncode != 0 and snapshot(target) == before


@pytest.mark.parametrize("kind", ["main", "linked"])
def test_session_root_cannot_bypass_git_workspace_checks(workspace, invoke, snapshot, kind):
    """Bug: session-root routing deleted dirty or Git-locked workspaces without confirmation."""
    repo, worktree, env = workspace
    if kind == "main":
        env["PLOT_SESSION_ROOT"] = str(repo.parent)
        target = repo
    else:
        target = Path(env["PLOT_SESSION_ROOT"]) / "linked"
        target.parent.mkdir()
        git(repo, "worktree", "add", "-q", "-b", "linked", str(target))
        git(repo, "worktree", "lock", str(target))
    (target / "README.md").write_text("unsaved Git work\n")
    before = snapshot(target)
    result = invoke(target)
    assert result.returncode != 0 and snapshot(target) == before
    assert str(target) in git(repo, "worktree", "list")


def test_example_app_cannot_stop_a_dispatcher_or_remove_a_forgotten_tree(workspace, invoke):
    _, worktree, env = workspace
    for target in (Path(env["PLOT_SESSION_ROOT"]) / "retired", worktree.parent / "forgotten"):
        target.mkdir(parents=True)
        result = invoke(target, "--self", "--force")
        assert result.returncode != 0 and "registered worktree" in result.stderr
        assert target.is_dir()
