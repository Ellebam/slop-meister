"""A directory session is a prepared folder outside Git with its agreements and a vault grant."""

import json
from pathlib import Path

import pytest

from tests.integration.install.installer_helpers import git_result
from tests.integration.launch.helpers import (
    ROOT,
    Machine,
    codex_writable,
    declare,
    launch,
    machine,
    snapshot,
    temporary_roots,
)

OUTSIDE = "This session runs outside any repository. There is nothing to commit."
NO_SHIPPING = (
    "Agent shipping permission for this session is deny. No push or PR write, including during "
    "finalize."
)
AGREEMENTS = (("claude", "CLAUDE.md"), ("codex", "AGENTS.md"))


def _claude_granted(session: Path, world: Machine, output: str) -> bool:
    vault = world.vault
    access = json.loads((session / ".claude/access-settings.json").read_text())
    project = json.loads((session / ".claude/settings.json").read_text())
    return (
        str(vault.resolve()) in access["permissions"]["additionalDirectories"]
        and "permissions" not in project
        and f"{vault.resolve()}/**" in project["claudeMdExcludes"]
        and "--add-dir" not in output
    )


def _codex_granted(session: Path, world: Machine, output: str) -> bool:
    expected = {
        str(world.vault.resolve()),
        *temporary_roots(world),
        str(session / ".slopmeister-tmp"),
    }
    return "--add-dir" not in output and codex_writable(session) == expected


GRANTED = {"claude": _claude_granted, "codex": _codex_granted}


@pytest.mark.parametrize("tool", ["claude", "codex"])
def test_directory_session_prepared(tmp_path, tool):
    """Bug: a vault session starts without agreements or grant, inside Git, or writes the vault."""
    world = machine(tmp_path)
    (world.vault / "note.md").write_text("operator record\n")
    vault = snapshot(world.vault)
    output = launch(
        world, "example-client", "example-client-ns1", "--directory", "--tool", tool
    ).stdout
    session = world.sessions / "example-client-ns1"
    assert f"session directory ready at {session}" in output
    for rendered, name in AGREEMENTS:
        source = (ROOT / f"dist/{rendered}/plots/example-client.md").read_bytes()
        assert (session / name).read_bytes() == source + f"\n{OUTSIDE}\n{NO_SHIPPING}\n".encode()
    assert not any((session / name).exists() for name in ("CLAUDE.local.md", "AGENTS.override.md"))
    access = json.loads((session / ".claude/access-settings.json").read_text())
    assert not any(rule.startswith("Bash(git ") for rule in access["permissions"].get("ask", []))
    assert not (session / ".codex/rules/git-permission.rules").exists()
    assert "approval_policy" not in (session / ".codex/config.toml").read_text()
    assert (session / "example-client-ns1-NOTES.md").read_bytes() == b""
    assert git_result(session, "rev-parse", "--git-dir").returncode
    assert GRANTED[tool](session, world, output)
    assert snapshot(world.vault) == vault


@pytest.mark.parametrize("delivery", ["inject", "seed", "committed"])
def test_repository_plot_launches_as_directory(tmp_path, delivery):
    """Bug: a repository-capable plot refuses the directory form or loses its paragraph or grant."""
    world = machine(tmp_path)
    plots = str(declare(tmp_path / "plots-declared", "example-client", delivery))
    session = world.sessions / "example-client-directory"
    for entry in ((), ("--redispatch",)):
        output = launch(
            world, "example-client", "example-client-directory", *entry, PLOT_DECLARATIONS=plots
        ).stdout
        for _, name in AGREEMENTS:
            assert OUTSIDE in (session / name).read_text()
        assert _claude_granted(session, world, output)
