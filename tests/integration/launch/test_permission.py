"""The declared permission reaches native policy on fresh launch and redispatch."""

import json
import tomllib

import pytest

from tests.integration.install.installer_helpers import git_result
from tests.integration.launch.helpers import ROOT, declare, launch, machine, target
from tests.support.repos import git


@pytest.mark.parametrize("permission", ["allow", "deny"])
@pytest.mark.parametrize("delivery", ["inject", "seed", "committed"])
def test_declared_permission_reaches_native_policy_without_blocking_operator_git(
    tmp_path, delivery, permission
):
    """Bug: deny blocks operator Git or redispatch drops the agent's native prompt policy."""
    world = machine(tmp_path)
    plots = declare(tmp_path / "plots-declared", "example-client", delivery, commit=permission)
    repo = target(tmp_path / "repo")
    worktree = repo / ".worktrees/example-client-worker"
    for entry in ((), ("--redispatch",)):
        launch(
            world,
            str(repo),
            "example-client",
            "example-client-worker",
            *entry,
            PLOT_DECLARATIONS=str(plots),
        )
        head = git(worktree, "rev-parse", "HEAD")
        (worktree / "application.txt").write_text(f"{entry}\n")
        git(worktree, "add", "application.txt")
        result = git_result(worktree, "commit", "-m", "application")
        assert result.returncode == 0, result.stderr
        assert git(worktree, "rev-parse", "HEAD") != head
        policy = (worktree / ".codex/rules/git-permission.rules").read_text()
        assert ('prefix_rule(pattern=["git", "commit"]' in policy) is (permission == "deny")
        assert 'prefix_rule(pattern=["git", "push"]' in policy
        for agreement in ("AGENTS.md", "CLAUDE.md"):
            paragraph = f"Agent commit permission for this plot is {permission}"
            assert paragraph in (worktree / agreement).read_text()


MANAGER = "This session is a manager."
REFUSAL = "Only the standing dispatcher and a session dispatched as a manager"


@pytest.mark.parametrize("manager", [True, False])
@pytest.mark.parametrize("directory", [True, False])
def test_manager_declaration_reaches_both_tools_and_survives_redispatch(
    tmp_path, manager, directory
):
    """Manager practices reach both tools and workspace kinds and survive redispatch."""
    world = machine(tmp_path)
    plots = declare(tmp_path / "plots-declared", "example-app", "committed", commit="allow")
    repo = target(tmp_path / "repo")
    repository = () if directory else (str(repo),)
    kind = ("--directory",) if directory else ()
    worktree = (
        world.sessions / "example-app-worker"
        if directory
        else repo / ".worktrees/example-app-worker"
    )
    global_bytes = (ROOT / "plots/home/global.md").stat().st_size
    for entry in (("--manager",) if manager else (), ("--redispatch",)):
        args = (*repository, "example-app", "example-app-worker", *kind, *entry)
        launch(world, *args, PLOT_DECLARATIONS=str(plots))
        assert_role_and_peer_delivery(worktree, manager)
        limit = tomllib.loads((worktree / ".codex/config.toml").read_text())[
            "project_doc_max_bytes"
        ]
        assert (worktree / "AGENTS.md").stat().st_size + global_bytes + 2 <= limit
        allow = json.loads((worktree / ".claude/access-settings.json").read_text())["autoMode"]
        rules = [rule for rule in allow.get("allow", []) if rule.startswith("Declared manager")]
        assert len(rules) == manager


def assert_role_and_peer_delivery(worktree, manager):
    for agreement, native, tool in (
        ("AGENTS.md", ".agents", "codex"),
        ("CLAUDE.md", ".claude", "claude"),
    ):
        text = (worktree / agreement).read_text()
        assert REFUSAL in text
        assert "Peer messages use the plot-session skill's communicate.md" in text
        assert "The launcher prepares your own local task inbox before the model starts" in text
        assert "check to read message bodies and acknowledge processed batches" in text
        assert (worktree / native / "skills/plot-session/communicate.md").read_bytes() == (
            ROOT / f"dist/{tool}/skills/plot-session/communicate.md"
        ).read_bytes()
        assert (MANAGER in text) is manager
        assert (f"task --dir {ROOT}" in text) is manager
        skill = (worktree / native / "skills/plot-session/SKILL.md").read_text()
        practices = skill.split("\n### Working practices\n", 1)[1].split("\n## ", 1)[0]
        assert (practices in text) is manager
