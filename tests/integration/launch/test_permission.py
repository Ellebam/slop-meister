"""The declared permission reaches native policy on fresh launch and redispatch."""

import json
import subprocess
import sys
import tomllib

import pytest

from tests.integration.install.installer_helpers import git_result
from tests.integration.launch.helpers import ROOT, declare, executable, launch, machine, target
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
REFUSAL = "Only the standing dispatcher, a session dispatched as a manager and a proof owner"


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


# Lists one live terminal, the owner's, as Orca's terminal list reports it.
ORCA_LIST = """#!/bin/sh
echo '{"ok": true, "result": {"truncated": false, "terminals": [{"handle": "term_owner"}]}}'
"""


def _launch_proof(tmp_path, owner):
    """A shipping-allowed plot, so only the proof role can turn native approval on."""
    world = machine(tmp_path)
    plots = declare(tmp_path / "plots-declared", "example-app", "committed", commit="allow")
    declaration = plots / "example-app/plot.toml"
    declaration.write_text(
        declaration.read_text().replace('commit = "allow"', 'commit = "allow"\nshipping = "allow"')
    )
    repo = target(tmp_path / "repo")
    world.state.mkdir(parents=True, exist_ok=True)
    if owner != "missing":
        handle = "term_gone" if owner == "closed" else "term_owner"
        (world.state / "owner-1.orca").write_text(handle + "\n")
    tail = ("--", "--dangerously-skip-permissions") if owner == "bypass" else ()
    orca = executable(tmp_path / "orca", ORCA_LIST)
    named = "" if owner == "empty" else "owner-1"
    result = launch(
        world, str(repo), "example-app", "example-app-proof", "--proof-for", named, *tail, ok=None,
        PLOT_DECLARATIONS=str(plots), PLOT_SESSION_ORCA=str(orca),
    )  # fmt: skip
    if owner == "live":
        bypass = launch(
            world, str(repo), "example-app", "example-app-proof", "--redispatch", "--tool", "codex",
            "--", "-c", 'approval_policy="never"', ok=None,
            PLOT_DECLARATIONS=str(plots), PLOT_SESSION_ORCA=str(orca),
        )  # fmt: skip
        assert bypass.returncode != 0 and "override Slopmeister-owned" in bypass.stderr
    return result, repo


@pytest.mark.parametrize("owner", ["live", "closed", "missing", "bypass", "empty"])
def test_proof_session_binds_its_live_owner_and_never_ships(tmp_path, owner):
    """Bug: a proof session trusts a reusable owner name, skips approvals or ships on its word."""
    result, repo = _launch_proof(tmp_path, owner)
    worktree = repo / ".worktrees/example-app-proof"
    if owner != "live":
        assert result.returncode != 0 and not worktree.exists()
        refusal = {"bypass": "override Slopmeister-owned", "empty": "--proof-for needs a name"}.get(
            owner, "--proof-for owner-1 needs"
        )
        assert refusal in result.stderr
        return
    assert result.returncode == 0, result.stderr
    metadata = repo / ".git/worktrees/example-app-proof/slopmeister-config"
    state = json.loads((metadata / "state.json").read_text())
    assert state["proof_owner"] == {"name": "owner-1", "handle": "term_owner"}
    assert state["shipping"] == "deny"
    for agreement in ("AGENTS.md", "CLAUDE.md"):
        assert "disposable proof session for owner-1" in (worktree / agreement).read_text()
    from slopmeister.install.prepare import PROOF_OWNER_EXCEPTION, PROOF_SOFT_DENY

    mode = json.loads((worktree / ".claude/access-settings.json").read_text())["autoMode"]
    assert PROOF_SOFT_DENY in mode["soft_deny"] and PROOF_OWNER_EXCEPTION not in mode["allow"]
    shipped = subprocess.run(
        [sys.executable, str(metadata / "config-install.py"), "--verify-shipping"],
        cwd=worktree,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert shipped.returncode != 0 and "a proof session never ships" in shipped.stderr


def test_fresh_launch_refuses_a_name_whose_recorded_terminal_is_live(tmp_path):
    """Bug: a second fresh launch reused a live Codex session's name and overwrote its record."""
    world = machine(tmp_path)
    world.state.mkdir(parents=True, exist_ok=True)
    record = world.state / "example-app-owner.orca"
    record.write_text("term_owner\n")
    orca = executable(tmp_path / "orca", ORCA_LIST)
    result = launch(
        world, "example-app", "example-app-owner", "--directory", "--tool", "codex", ok=None,
        PLOT_SESSION_ORCA=str(orca),
    )  # fmt: skip
    assert result.returncode != 0 and "already carries" in result.stderr
    assert record.read_text() == "term_owner\n"
    assert not (world.sessions / "example-app-owner").exists()
