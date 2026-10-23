"""Refused launches stop before fetching a kickoff or touching the target."""

from pathlib import Path

import pytest

from tests.integration.launch.helpers import declare, launch, machine, snapshot, target
from tests.support.repos import git


@pytest.mark.parametrize(
    ("tail", "message"),
    [
        (["--model", "-bad"], "--model requires a nonempty value"),
        (["--tool", "codex", "--", "-cproject_root_markers=[]"], "override Slopmeister-owned"),
        (["--tool", "bogus"], "--tool must be claude, codex or opencode"),
        (["--tool", "claude", "--", "--session-id=other"], "override Slopmeister-owned"),
        (["--tool", "claude", "--", "--tools=Read"], "override Slopmeister-owned"),
        (["--tool", "claude", "--", "--cloud"], "override Slopmeister-owned"),
        (["--tool", "codex", "--", "resume"], "override Slopmeister-owned"),
    ],
)
def test_argument_refusal_precedes_fetch_and_preparation(tmp_path, tail, message):
    """Bug: a bad argument fetches a private issue or leaves a half-prepared worktree."""
    world = machine(tmp_path)
    repo = target(tmp_path / "repo")
    plot = world.root / "plots/example-client/plot.toml"
    plot.write_text(plot.read_text().replace('tasks = "manual"', 'tasks = "github"'))
    gh = tmp_path / "bin/gh"
    gh.write_text(f"#!/bin/sh\ntouch {tmp_path / 'fetched'}\n")
    gh.chmod(0o755)
    before = snapshot(repo), snapshot(world.claude)
    result = launch(
        world,
        str(repo),
        "example-client",
        "example-client-refused",
        "--issue",
        "7",
        *tail,
        ok=False,
    )
    assert message in result.stderr
    assert not (tmp_path / "fetched").exists()
    assert (snapshot(repo), snapshot(world.claude)) == before
    assert not world.state.exists()


def _rerun(world, repo: Path) -> dict:
    launch(world, str(repo), "example-client", "example-client-wt1")
    return {}


def _undeclared(world, repo: Path) -> dict:
    return {"plot": "ghost", "name": "ghost-wt1"}


def _unrendered(world, repo: Path) -> dict:
    plots = declare(world.root / "declared", "nolane", "inject")
    return {"plot": "nolane", "name": "nolane-wt1", "PLOT_DECLARATIONS": str(plots)}


def _case_variant(world, repo: Path) -> dict:
    (repo / "agents.override.md").write_text("x\n")
    git(repo, "add", "agents.override.md")
    git(repo, "commit", "-qm", "track")
    return {}


def _symlinked_parent(world, repo: Path) -> dict:
    (repo / ".worktrees").symlink_to(world.root / "outside", target_is_directory=True)
    return {}


def _symlinked_exclude(world, repo: Path) -> dict:
    (repo / ".git/info/exclude").unlink(missing_ok=True)
    (repo / ".git/info/exclude").symlink_to(world.root / "outside/canary")
    return {}


def _branch_namespace(world, repo: Path) -> dict:
    git(repo, "branch", "example-client-wt1/child")
    return {}


def _bare(world, repo: Path) -> dict:
    git(repo, "config", "core.bare", "true")
    return {}


def _shared_worktree(world, repo: Path) -> dict:
    git(repo, "config", "core.worktree", "..")
    return {}


@pytest.mark.parametrize(
    ("arrange", "message"),
    [
        (_rerun, "already exists"),
        (_undeclared, "no launchable plot declared"),
        (_unrendered, "no rendered plot"),
        (_case_variant, "case-folded configuration path collision"),
        (_symlinked_parent, "symlinked configuration path"),
        (_symlinked_exclude, "symlinked configuration path"),
        (_branch_namespace, "branches exist under 'example-client-wt1/'"),
        (_bare, "not a non-bare git repository"),
        (_shared_worktree, "incompatible shared core.worktree"),
    ],
)
def test_preparation_refusal_leaves_target_untouched(tmp_path, arrange, message):
    """Bug: a refused launch mutates the target repository or writes through a symlink."""
    world = machine(tmp_path)
    repo = target(tmp_path / "repo")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "canary").write_text("canary\n")
    options = arrange(world, repo)
    argv = [
        str(repo),
        options.pop("plot", "example-client"),
        options.pop("name", "example-client-wt1"),
    ]
    argv += ["--tool", options.pop("tool", "claude")]
    before = snapshot(repo), snapshot(outside)
    result = launch(world, *argv, ok=False, **options)
    assert message in result.stderr
    assert (snapshot(repo), snapshot(outside)) == before


def test_bad_neighbouring_declaration_refuses_before_git(tmp_path):
    """Bug: one broken plot declaration still lets a launch mutate Git and trust state."""
    world = machine(tmp_path)
    plots = declare(tmp_path / "declared", "good", "committed")
    (plots / "bad").mkdir()
    (plots / "bad/plot.toml").write_text('[plot]\nbase="../code"\n')
    repo = target(tmp_path / "repo")
    before = git(repo, "config", "--local", "--list")
    result = launch(world, str(repo), "good", "good-worker", ok=False, PLOT_DECLARATIONS=str(plots))
    assert "bad/plot.toml: plot.base" in result.stderr
    assert git(repo, "config", "--local", "--list") == before
    assert not (repo / ".worktrees").exists()
    assert not world.state.exists()


@pytest.mark.parametrize("stdin", ["", "\n\n"])
def test_empty_kickoff_is_refused_before_preparation(tmp_path, stdin):
    """Bug: a session starts with no brief and sits idle in a prepared worktree."""
    world = machine(tmp_path)
    repo = target(tmp_path / "repo")
    result = launch(
        world, str(repo), "example-client", "example-client-wt1", kickoff=stdin, ok=False
    )
    assert "the kickoff is empty, a session with no brief sits idle" in result.stderr
    assert not (repo / ".worktrees").exists()


def test_snapshot_ignores_git_lock_files(tmp_path):
    """Bug: Git's background maintenance lock makes every untouched-target assertion flaky."""
    repo = target(tmp_path / "repo")
    before = snapshot(repo)
    (repo / ".git/objects/maintenance.lock").write_text("held\n")
    assert snapshot(repo) == before


def test_nested_repository_is_refused_before_preparation(tmp_path):
    world = machine(tmp_path)
    repo = target(tmp_path / "repo")
    nested = repo / "nested"
    nested.mkdir()
    before = snapshot(repo)
    result = launch(world, str(nested), "example-client", "example-client-nested", ok=False)
    assert "not a non-bare git repository" in result.stderr
    assert snapshot(repo) == before and not world.state.exists()


def test_symlink_to_the_actual_repository_root_remains_supported(tmp_path):
    world = machine(tmp_path)
    repo = target(tmp_path / "repo")
    link = tmp_path / "repo-link"
    link.symlink_to(repo, target_is_directory=True)
    result = launch(world, str(link), "example-client", "example-client-linked")
    assert result.returncode == 0 and (repo / ".worktrees/example-client-linked").is_dir()
