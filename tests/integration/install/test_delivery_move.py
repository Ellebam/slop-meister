"""The private exclusion stays local while saved workspace identity remains fixed."""

from pathlib import Path

from tests.integration.install.installer_helpers import git_result, install, prepared
from tests.support.repos import git


def test_moved_checkout_keeps_relative_delivery_exclusion(tmp_path):
    """Bug: moving a checkout exposes injected files because its exclusion path was absolute."""
    installed = prepared(tmp_path)
    exclude = git(installed.workspace, "config", "--worktree", "core.excludesFile").strip()
    assert not Path(exclude).is_absolute()

    moved = tmp_path / "moved"
    installed.repo.rename(moved)
    workspace = moved / ".worktrees" / installed.workspace.name
    git(moved, "worktree", "repair", str(workspace))

    assert not git(workspace, "status", "--porcelain", "--untracked-files=all")
    result = install(installed.env, "--check", "example-app", str(workspace), ok=False)
    assert f"this workspace moved from {installed.workspace} to {workspace}" in result.stderr


def test_legacy_guarded_state_names_one_operator_recovery(tmp_path):
    """Bug: redispatch accepts an old guard or recommends only another equally denied session."""
    installed = prepared(tmp_path)
    gitdir = Path(git(installed.workspace, "rev-parse", "--absolute-git-dir").strip())
    state = gitdir / "slopmeister-config/state.json"
    state.write_text(state.read_text().replace('"version": 3', '"version": 2'))

    result = install(installed.env, "--check", "example-app", str(installed.workspace), ok=False)

    assert "legacy prepared workspace" in result.stderr
    assert "git config --worktree --unset core.hooksPath" in result.stderr
    hooks = gitdir / "slopmeister-config/hooks"
    hooks.mkdir()
    blocker = hooks / "pre-commit"
    blocker.write_text("#!/bin/sh\nexit 1\n")
    blocker.chmod(0o700)
    git(installed.workspace, "config", "--worktree", "core.hooksPath", str(hooks))
    assert git_result(installed.workspace, "commit", "--allow-empty", "-m", "blocked").returncode
    git(installed.workspace, "config", "--worktree", "--unset", "core.hooksPath")
    assert not git_result(
        installed.workspace, "commit", "--allow-empty", "-m", "Operator recovery"
    ).returncode
