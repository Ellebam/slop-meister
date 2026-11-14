"""Fresh workers must execute the fixed context check for either native tool."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from slopmeister.session import launch_identity
from tests.integration.install.installer_helpers import install, prepared, worktree

SESSION = "00000000-0000-4000-8000-000000000001"
MANAGER = "00000000-0000-4000-8000-000000000002"
TOOLS = [(".agents", "codex"), (".claude", "claude")]


def _compacted(home: Path, workspace: Path, tool: str, session: str) -> None:
    """Record a launched session with three native compactions."""
    launch_identity.write(workspace, (workspace.name, tool, session))
    # Identity has its own home route, independent of the install subprocess environment.
    destination = home / ".local/state/slopmeister/launch" / launch_identity.path(workspace).name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(launch_identity.path(workspace).read_bytes())
    destination.chmod(0o600)
    log = (
        home / ".claude/projects/example" / f"{session}.jsonl"
        if tool == "claude"
        else home / ".codex/sessions" / f"rollout-{session}.jsonl"
    )
    log.parent.mkdir(parents=True, exist_ok=True)
    records = (
        [
            dict(sessionId=session, cwd=str(workspace), type="system", subtype="compact_boundary")
            for _ in range(3)
        ]
        if tool == "claude"
        else [
            {"type": "session_meta", "payload": {"id": session, "cwd": str(workspace)}},
            *[{"type": "compacted", "payload": {}} for _ in range(3)],
        ]
    )
    log.write_text("".join(json.dumps(r) + "\n" for r in records))


@pytest.mark.parametrize("native,tool", TOOLS)
def test_only_a_delivered_manager_requests_with_open_questions(tmp_path, native, tool):
    """Bug: a manager with an open operator question can never request recovery, or the
    exception also reaches a worker or an open lab or deploy window."""
    world = prepared(tmp_path)
    world.env.pop("CODEX_THREAD_ID", None)
    home = Path(world.env["HOME"])
    manager = worktree(world.repo, "manager")
    install(world.env, "--prepare", "--manager", "example-app", str(manager))
    _compacted(home, world.workspace, tool, SESSION)
    _compacted(home, manager, tool, MANAGER)

    def read(workspace: Path, *flags: str) -> tuple[bool, str]:
        entry = workspace / native / "skills/plot-session/scripts/context_redispatch.py"
        arguments = [sys.executable, str(entry), "inspect", "--workspace", str(workspace), *flags]
        result = subprocess.run(arguments, env=world.env, text=True, capture_output=True)
        report = json.loads(result.stdout)
        return report["manager"], report["action"]

    assert read(manager, "--windows-clear") == (True, "request")
    assert read(manager) == (True, "protected")
    assert read(world.workspace, "--windows-clear") == (False, "protected")


@pytest.mark.parametrize("native,tool", TOOLS)
def test_installed_context_check_uses_snapshot_and_suppresses_duplicate(tmp_path, native, tool):
    world = prepared(tmp_path)
    world.env.pop("CODEX_THREAD_ID", None)
    workspace = world.workspace
    home = Path(world.env["HOME"])
    _compacted(home, workspace, tool, SESSION)
    entry = workspace / native / "skills/plot-session/scripts/context_redispatch.py"
    skill = (workspace / native / "skills/plot-session/SKILL.md").read_text()
    assert f"python3 {native}/skills/plot-session/scripts/context_redispatch.py inspect" in skill
    assert "{{TOOL:" not in skill
    arguments = [
        sys.executable,
        str(entry),
        "inspect",
        "--workspace",
        str(workspace),
        "--questions-clear",
        "--windows-clear",
    ]
    result = subprocess.run(arguments, env=world.env, text=True, capture_output=True, check=True)
    assert json.loads(result.stdout)["action"] == "request"
    (workspace / f"{workspace.name}-NOTES.md").write_text(
        "Context redispatch request: " + SESSION + "\n"
    )
    duplicate = subprocess.run(arguments, env=world.env, text=True, capture_output=True, check=True)
    assert json.loads(duplicate.stdout)["action"] == "already-requested"
    assert 'SNAPSHOT = ""' not in entry.read_text()
    for agreement in ("AGENTS.md", "CLAUDE.md"):
        assert "Before every worker turn ends" in (workspace / agreement).read_text()
