"""Real Git path reporting must not hide changes to agent or gate files."""

import pytest

from slopmeister.session import ship, update_pr
from tests.integration.update_prs.test_batch import REPO, ScratchGH, _scratch_repos
from tests.support.repos import git as _git


def _stage_change(source, workflow, change):
    if change == "rename":
        (source / "docs").mkdir()
        _git(source, "mv", str(workflow.relative_to(source)), "docs/check.yml")
        return
    name = {
        "nonascii": ".github/workflows/über.yml",
        "nested_agents": "services/AGENTS.md",
        "override": "AGENTS.override.md",
        "local": "CLAUDE.local.md",
        "mcp": ".mcp.json",
        "nested_claude": "services/.claude/settings.json",
        "taskfile": "Taskfile.yml",
        "claude_case": ".Claude/settings.json",
        "agent_case": "Claude.md",
        "taskfile_yaml": "Taskfile.yaml",
    }[change]
    destination = source / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("new instructions\n")


@pytest.mark.parametrize(
    "change",
    [
        "rename",
        "nonascii",
        "nested_agents",
        "override",
        "local",
        "mcp",
        "nested_claude",
        "taskfile",
        "claude_case",
        "agent_case",
        "taskfile_yaml",
    ],
)
def test_gate_or_agent_path_change_cannot_push(tmp_path, monkeypatch, change):
    """Bug: Git's rename or quote display hid a protected source path."""
    bare, prepared, source, main = _scratch_repos(tmp_path)
    _git(source, "checkout", "-b", "dependabot/broken")
    workflow = source / ".github/workflows/check.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: check\n")
    _git(source, "add", "-A")
    _git(source, "commit", "-m", "Plant bot update")
    old = _git(source, "rev-parse", "HEAD").strip()
    _git(source, "push", "origin", "HEAD:refs/heads/dependabot/broken")
    _stage_change(source, workflow, change)
    _git(source, "add", "-A")
    _git(source, "commit", "-m", "Change protected path")
    monkeypatch.setattr(update_pr, "_context", lambda _: (REPO, "main"))
    monkeypatch.setattr(ship, "gh", ScratchGH(prepared, bare).gh)
    with pytest.raises(ValueError, match="fix changes"):
        update_pr.push(prepared, source, update_pr.Target(8, old, REPO))
    assert _git(bare, "rev-parse", "refs/heads/dependabot/broken").strip() == old
    assert _git(bare, "rev-parse", "refs/heads/main").strip() == main
