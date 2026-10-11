"""Installer honors Git configuration spellings and project hooks."""

from tests.integration.install.installer_helpers import (
    environment,
    git_result,
    install,
    project,
    worktree,
)
from tests.support.repos import git


def test_included_shared_worktree_setting_is_refused(tmp_path):
    env = environment(tmp_path)
    repo = project(tmp_path / "project")
    included = tmp_path / "included-config"
    included.write_text(f"[core]\nworktree = {repo}\n")
    git(repo, "config", "include.path", str(included))
    result = install(env, "--preflight", "example-app", str(repo), ok=False)
    assert "core.worktree" in result.stderr


def test_late_project_hook_runs_directly_with_arguments_and_status(tmp_path):
    env = environment(tmp_path)
    repo = project(tmp_path / "project")
    git(repo, "config", "core.hooksPath", ".late-hooks")
    workspace = worktree(repo, "late")
    install(env, "--prepare", "example-app", str(workspace))
    hook = workspace / ".late-hooks/commit-msg"
    hook.parent.mkdir()
    hook.write_text("#!/bin/sh\necho late-message-refusal >&2\nexit 1\n")
    hook.chmod(0o700)
    result = git_result(workspace, "commit", "--allow-empty", "-m", "late-message")
    assert result.returncode and "late-message-refusal" in result.stderr


def test_absolute_reference_transaction_hook_runs_directly(tmp_path):
    env = environment(tmp_path)
    repo = project(tmp_path / "project")
    hooks = tmp_path / "absolute-hooks"
    hooks.mkdir()
    hook = hooks / "reference-transaction"
    hook.write_text(
        '#!/bin/sh\n[ "$1" = prepared ] || exit 0\n'
        "grep -q 'refs/heads/project-refusal$' && echo original-reference-refusal >&2 && exit 1\n"
    )
    hook.chmod(0o700)
    workspace = worktree(repo, "absolute")
    git(repo, "config", "core.hooksPath", str(hooks))
    install(env, "--prepare", "example-app", str(workspace))
    result = git_result(workspace, "update-ref", "refs/heads/project-refusal", "HEAD")
    assert result.returncode and "original-reference-refusal" in result.stderr
