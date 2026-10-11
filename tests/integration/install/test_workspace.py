"""Prepared worktrees are isolated snapshots with preserved repository state."""

import json

from slopmeister.install import snapshot
from slopmeister.install.entries import entry_text
from tests.integration.install.installer_helpers import (
    ROOT,
    environment,
    install,
    state,
    worktree,
)
from tests.support.repos import git, scratch_repo


def test_preparation_replaces_only_root_configuration(installed):
    workspace = installed.workspace
    expected_denies = json.loads((ROOT / "dist/claude/settings.json").read_text())["permissions"][
        "deny"
    ]
    access = json.loads((workspace / ".claude/access-settings.json").read_text())
    assert access["permissions"]["deny"] == [
        *expected_denies,
        "Edit(~/.local/state/slopmeister/**)",
    ]
    assert not (workspace / "CLAUDE.md").is_symlink()
    assert git(workspace, "show", ":AGENTS.md").strip() == "original agreement"
    assert not (workspace / ".claude/skills/neighbour").exists()
    assert not (workspace / ".claude/settings.local.json").exists()
    assert not (workspace / "product/.claude").exists()
    assert not (workspace / "product/.codex").exists()


def test_prepared_worktree_is_clean_and_repository_isolated(installed):
    repo, workspace = installed.repo, installed.workspace
    sibling = worktree(repo, "sibling")
    assert not git(workspace, "status", "--short", "--untracked-files=all")
    assert git(repo, "config", "core.hooksPath").strip() == ".hooks"
    assert git(sibling, "config", "core.hooksPath").strip() == ".hooks"
    assert (sibling / "AGENTS.md").read_text() == "original agreement\n"
    assert (workspace / "product/AGENTS.md").read_text() == "product document\n"
    assert git(repo, "rev-parse", "HEAD").strip() == installed.baseline


def test_delivered_helpers_are_copies_and_snapshot_drift_is_refused(installed):
    workspace = installed.workspace
    for native in (".agents", ".claude"):
        helper = workspace / native / "skills/ship/scripts/ship.py"
        bound = state(workspace)[0].parent / snapshot.DIRECTORY
        assert helper.read_text() == entry_text("slopmeister.session.ship", bound)
        assert not helper.is_symlink()
        original = helper.read_bytes()
        helper.write_bytes(original + b"\nchanged helper\n")
        result = install(installed.env, "--check", "example-app", str(workspace), ok=False)
        assert "saved session configuration" in result.stderr
        helper.write_bytes(original)
    install(installed.env, "--check", "example-app", str(workspace))


def test_existing_permission_and_payload_ignore_later_source_changes(installed, tmp_path):
    path, saved = state(installed.workspace)
    assert saved["shipping"] == "allow"
    before = installed.workspace.joinpath("AGENTS.md").read_bytes()
    source = tmp_path / "plots"
    declaration = (
        (ROOT / "plots/example-app/plot.toml")
        .read_text()
        .replace('shipping = "allow"', 'shipping = "deny"')
    )
    target = source / "example-app/plot.toml"
    target.parent.mkdir(parents=True)
    target.write_text(declaration)
    installed.env["PLOT_DECLARATIONS"] = str(source)
    install(installed.env, "--check", "example-app", str(installed.workspace))
    assert installed.workspace.joinpath("AGENTS.md").read_bytes() == before
    assert path.exists()


def test_tracked_config_symlink_is_replaced_not_followed(tmp_path):
    """Bug: preparation writes the session configuration through a tracked `.claude` link into
    a directory outside the repository, or leaves the link in place."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "ordinary").write_text("keep\n")
    repo = scratch_repo(tmp_path / "project")
    (repo / ".claude").symlink_to(outside)
    git(repo, "add", ".claude")
    git(repo, "commit", "-q", "-m", "Link configuration")
    workspace = worktree(repo, "worker")
    install(environment(tmp_path), "--prepare", "example-app", str(workspace))
    assert not (workspace / ".claude").is_symlink()
    assert (workspace / ".claude/access-settings.json").is_file()
    assert [path.name for path in outside.iterdir()] == ["ordinary"]
    assert (outside / "ordinary").read_text() == "keep\n"
    assert not git(repo, "status", "--porcelain")
