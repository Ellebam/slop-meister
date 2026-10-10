"""Installer path validation prevents partial or redirected writes."""

from pathlib import Path

import pytest

from tests.integration.install.installer_helpers import (
    checkout,
    environment,
    install,
    project,
    worktree,
)
from tests.support.repos import git, scratch_repo


def test_untracked_configuration_and_local_settings_stay_out_of_commits(tmp_path):
    env = environment(tmp_path)
    repo = scratch_repo(tmp_path / "plain")
    workspace = worktree(repo, "plain-worker")
    install(env, "--prepare", "example-app", str(workspace))
    git(workspace, "add", "-A")
    assert not git(workspace, "diff", "--cached", "--name-only")
    (workspace / ".claude/settings.local.json").write_text("{}\n")
    (workspace / ".codex/config.toml").write_text("# local tool settings\n")
    (workspace / "app.txt").write_text("application\n")
    git(workspace, "add", "-A")
    assert git(workspace, "diff", "--cached", "--name-only").strip() == "app.txt"
    git(workspace, "commit", "-q", "-m", "Application")
    assert git(workspace, "ls-tree", "-r", "--name-only", "HEAD").splitlines() == [
        "README.md",
        "app.txt",
    ]


def test_dirty_or_symlinked_destination_is_refused_without_content_change(tmp_path):
    env = environment(tmp_path)
    repo = scratch_repo(tmp_path / "plain")
    workspace = worktree(repo, "dirty")
    local = workspace / "local.txt"
    local.write_text("keep me\n")
    install(env, "--prepare", "example-app", str(workspace), ok=False)
    assert local.read_text() == "keep me\n"
    outside = tmp_path / "outside"
    outside.write_text("sentinel\n")
    (workspace / "AGENTS.md").symlink_to(outside)
    install(env, "--prepare", "example-app", str(workspace), ok=False)
    assert outside.read_text() == "sentinel\n"


@pytest.mark.parametrize("shape", ["parent-file", "folded-path", "config-link"])
def test_malformed_destination_writes_no_session_state(tmp_path, shape):
    env = environment(tmp_path)
    repo = scratch_repo(tmp_path / "plain")
    workspace = worktree(repo, shape)
    gitdir = Path(git(workspace, "rev-parse", "--absolute-git-dir").strip())
    if shape == "parent-file":
        (workspace / ".claude").write_text("project file\n")
    elif shape == "folded-path":
        (workspace / "agents.md").write_text("case collision\n")
    else:
        outside = tmp_path / "config-sentinel"
        outside.write_text("[core]\n")
        (gitdir / "config.worktree").symlink_to(outside)
    if shape != "config-link":
        git(workspace, "add", "-A")
        git(workspace, "commit", "-q", "-m", "Malformed shape")
    install(env, "--prepare", "example-app", str(workspace), ok=False)
    assert not (gitdir / "slopmeister-config").exists()


@pytest.mark.parametrize(
    "kind", ["skill-symlink", "skill-missing", "rules-symlink", "rules-missing"]
)
def test_incomplete_or_redirected_source_payload_is_refused(tmp_path, kind):
    root = checkout(tmp_path / "copy")
    env = environment(tmp_path)
    repo = project(tmp_path / "project")
    target = root / "dist/codex/skills/sow/SKILL.md"
    if kind.startswith("rules"):
        target = root / "dist/codex/rules/permissions.rules"
    saved = target.with_name(target.name + ".saved")
    target.rename(saved)
    if kind.endswith("symlink"):
        target.symlink_to(saved)
    result = _copied_install(root, env, "--preflight", "example-app", str(repo))
    assert result.returncode and "config-install:" in result.stderr


def _copied_install(root, env, *args):
    import subprocess

    return subprocess.run(
        [str(root / "bin/slopmeister"), "install", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_removed_worktree_removes_session_state_without_shared_setting_changes(tmp_path):
    env = environment(tmp_path)
    repo = project(tmp_path / "project")
    workspace = worktree(repo, "removable")
    install(env, "--prepare", "example-app", str(workspace))
    gitdir = Path(git(workspace, "rev-parse", "--absolute-git-dir").strip())
    hooks = git(repo, "config", "core.hooksPath").strip()
    git(repo, "worktree", "remove", "--force", str(workspace))
    assert not gitdir.exists()
    assert git(repo, "config", "core.hooksPath").strip() == hooks
    assert git(repo, "config", "extensions.worktreeConfig").strip() == "true"
