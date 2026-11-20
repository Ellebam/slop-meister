"""A managed worker gets its manager's inbox from the launcher's own record, never from text."""

import json
import shlex

import pytest

from tests.integration.launch.helpers import declare, launch, machine, reported, target

ROUTE = "SLOPMEISTER_PROMPT_ROUTE=run_manager1"


def routed(output: str) -> bool:
    """Whether the saved launch line gives the client the manager route."""
    with open(reported(output, "command file")) as saved:
        return ROUTE in shlex.split(saved.read().splitlines()[-1])


@pytest.mark.parametrize("manager", ["recorded", "missing", "redispatch", "manager", "outside"])
def test_managed_worker_records_the_managers_own_inbox(tmp_path, manager):
    """Bug: a waiting prompt reached nobody, or a kickoff could name any inbox as the manager."""
    world = machine(tmp_path)
    plots = declare(tmp_path / "plots-declared", "example-app", "committed", commit="allow")
    repo = target(tmp_path / "repo")
    world.state.mkdir(parents=True, exist_ok=True)
    if manager != "missing":
        (world.state / "mgr-1.run").write_text("run_manager1\n")
    # A record outside the launcher's state is never a manager route.
    (world.state.parent / "mgr-1.run").write_text("run_other\n")
    named = "../mgr-1" if manager == "outside" else "mgr-1"
    tail = {"redispatch": ("--redispatch",), "manager": ("--manager",)}.get(manager, ())
    result = launch(
        world,
        str(repo),
        "example-app",
        "example-app-worker",
        "--managed-by",
        named,
        *tail,
        ok=None,
        PLOT_DECLARATIONS=str(plots),
    )
    if manager != "recorded":
        refusal = {
            "missing": "--managed-by mgr-1 needs that session's inbox record",
            "redispatch": "a managed worker is declared at first dispatch",
            "manager": "a managed worker is declared at first dispatch as a plain worker",
            "outside": "--managed-by '../mgr-1' must match",
        }[manager]
        assert result.returncode != 0 and refusal in result.stderr
        assert not (repo / ".worktrees/example-app-worker").exists()
        return
    assert result.returncode == 0, result.stderr
    state = repo / ".git/worktrees/example-app-worker/slopmeister-config/state.json"
    assert json.loads(state.read_text())["manager_run"] == "run_manager1"
    assert routed(result.stdout)
    again = launch(
        world,
        str(repo),
        "example-app",
        "example-app-worker",
        "--redispatch",
        PLOT_DECLARATIONS=str(plots),
    )
    assert routed(again.stdout)


@pytest.mark.parametrize(
    ("reviewer", "waits"),
    [
        ((), False),
        (("-c", 'approvals_reviewer="user"'), True),
        (("-c", 'approvals_reviewer="user"', "-c", "approvals_reviewer=auto_review"), False),
    ],
)
def test_codex_hook_waits_for_the_manager_only_where_a_person_answers(tmp_path, reviewer, waits):
    """Bug: the hook runs before Codex's automatic reviewer, so a route held every action."""
    world = machine(tmp_path)
    plots = declare(tmp_path / "plots-declared", "example-app", "committed", commit="allow")
    repo = target(tmp_path / "repo")
    world.state.mkdir(parents=True, exist_ok=True)
    (world.state / "mgr-1.run").write_text("run_manager1\n")
    result = launch(
        world,
        str(repo),
        "example-app",
        "example-app-worker",
        "--tool",
        "codex",
        "--managed-by",
        "mgr-1",
        "--",
        *reviewer,
        PLOT_DECLARATIONS=str(plots),
    )
    assert routed(result.stdout) is waits
