"""The slopmeister plot replaces a foreign agreement locally and grants its files to each tool."""

import json
import os
from pathlib import Path

import pytest

from tests.integration.launch.helpers import (
    ROOT,
    codex_writable,
    launch,
    machine,
    target,
    temporary_roots,
)
from tests.support.repos import git

ALLOW = (
    b"Agent commit permission for this plot is allow. Agent commits are allowed in this "
    b"session's repository. This grants no push, merge or other remote write.\nAgent shipping "
    b"permission for this session is allow. Ordinary push and PR create/update are allowed only "
    b"for the saved repository and current non-default task branch through ship, GitHub enforces "
    b"branch protection. Merge and finalize remain operator-controlled.\n"
)


def _claude(line: str, worktree: Path, granted: list[str], temporary: set[str]) -> None:
    """Claude receives file grants through its access settings, never as project directories."""
    access = json.loads((worktree / ".claude/access-settings.json").read_text())
    project = json.loads((worktree / ".claude/settings.json").read_text())
    assert set(granted) <= set(access["permissions"]["additionalDirectories"])
    assert "permissions" not in project
    assert {path + "/**" for path in granted} <= set(project["claudeMdExcludes"])
    assert f"--settings '{worktree}/.claude/access-settings.json'" in line
    assert "--add-dir" not in line


def _codex(line: str, worktree: Path, granted: list[str], temporary: set[str]) -> None:
    """Codex receives exactly its grants through the workspace project config, never a flag."""
    assert codex_writable(worktree) == {*granted, *temporary, str(worktree / ".slopmeister-tmp")}
    assert "--add-dir" not in line


@pytest.mark.parametrize(("tool", "grants"), [("claude", _claude), ("codex", _codex)])
def test_plot_grants_reach_each_tool(tmp_path, tool, grants):
    """Bug: a slopmeister worker loses its main-checkout or vault access, keeps the foreign
    agreement, rewrites the index, or cannot commit the application change it was allowed."""
    world = machine(tmp_path)
    repo = target(tmp_path / "repo")
    (repo / "AGENTS.md").write_text("foreign agreement\n")
    git(repo, "add", "AGENTS.md")
    git(repo, "commit", "-q", "-m", "agreement")
    result = launch(world, str(repo), "slopmeister", "slopmeister-s1", "--tool", tool)
    worktree = repo / ".worktrees/slopmeister-s1"
    render = (ROOT / "dist/codex/plots/slopmeister.md").read_bytes()
    assert (worktree / "AGENTS.md").read_bytes() == render + b"\n" + ALLOW
    assert git(worktree, "show", ":AGENTS.md") == "foreign agreement\n"
    assert git(repo, "status", "--porcelain") == git(worktree, "status", "--porcelain") == ""
    git(worktree, "commit", "-q", "--allow-empty", "-m", "allowed")
    granted = [os.path.realpath(repo), os.path.realpath(world.vault)]
    grants(result.stdout, worktree, granted, temporary_roots(world))
