"""Each native tool receives the plot's publication policy in its own fixed snapshot."""

import json

import pytest

from tests.integration.launch.helpers import launch, machine, target
from tests.support.repos import git


@pytest.mark.parametrize("tool,tree", [("claude", ".claude"), ("codex", ".agents")])
def test_fixed_bloom_entry_and_owning_policy_reach_both_tools(tmp_path, tool, tree):
    world = machine(tmp_path)
    repo = target(tmp_path / "repo")
    launch(world, str(repo), "slopmeister", "slopmeister-bloom-example", "--tool", tool)
    worktree = repo / ".worktrees/slopmeister-bloom-example"
    state_dir = worktree / git(worktree, "rev-parse", "--git-dir").strip()
    state = json.loads((state_dir / "slopmeister-config/state.json").read_text())
    assert state["bloom"] == "tailnet" and state["worktree"] == str(worktree)
    entry = worktree / tree / "skills/bloom/scripts/bloom.py"
    assert state["snapshot"] in entry.read_text()
    assert (state_dir / "slopmeister-config/snapshot/slopmeister/session/bloom.py").is_file()
    assert git(worktree, "status", "--porcelain") == ""
