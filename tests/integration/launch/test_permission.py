"""The declared permission reaches native policy on fresh launch and redispatch."""

import pytest

from tests.integration.install.installer_helpers import git_result
from tests.integration.launch.helpers import declare, launch, machine, target
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
