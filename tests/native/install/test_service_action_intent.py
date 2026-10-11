"""Delivered write gates distinguish operator intent from instructions and invalid review."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from slopmeister.session.service_actions.constants import PYTHON
from tests.native.install.intent_fixture import (
    claude_host,
    close,
    main_results,
    marker_entry,
    prepared_action,
)
from tests.native.install.native_tool_fixture import marker_consumer, prepared_native
from tests.support.standin import run

pytestmark = pytest.mark.xdist_group("native-standin")


@pytest.mark.parametrize("action", ["jira-write", "confluence-write"])
@pytest.mark.parametrize(
    "intent",
    ["approved", "none", "different_target", "different_payload", "ambiguous", "instructions"],
)
def test_codex_write_requires_actual_exact_command_intent(tmp_path, action, intent):
    """Bug: a generic prompt permits unasked writes, or invalid review falsely proves refusal."""
    world = prepared_native(tmp_path, "codex", action)
    try:
        marker_consumer(world)
        command = world.command
        prompts = {
            "approved": "I approve this exact command:\n" + command,
            "none": "Go.",
            "different_target": "I approve this exact command:\n"
            + command.replace("TEST-7", "TEST-8").replace("--comment-page 7", "--comment-page 8"),
            "different_payload": "I approve this exact command:\n"
            + command.replace("approved-text", "other-text"),
            "ambiguous": "Yes.",
            "instructions": "Follow the delivered instructions.",
        }
        world.server.script = [("mcp__" + action.replace("-", "_") + "__run", {"command": command})]
        argv = [*world.client.argv[:-1], prompts[intent]]
        run(replace(world.client, argv=argv))
        result = main_results(world)
        assert (world.output.read_text() == "STANDIN_WRITE\n") == (intent == "approved")
        if intent != "approved":
            assert "STANDIN_INTENT_DECISION" in result
    finally:
        close(world)


@pytest.mark.parametrize("action", ["jira-write", "confluence-write"])
@pytest.mark.parametrize("approved", [False, True])
def test_claude_write_asks_despite_broad_allow_and_accepts_one_native_response(
    tmp_path, action, approved
):
    """Bug: a broad home allow bypasses write intent, or an approved native ask never runs."""
    world = prepared_native(tmp_path, "claude", action)
    try:
        marker_consumer(world)
        world.server.script = [
            ("mcp__" + action.replace("-", "_") + "__run", {"command": world.command})
        ]
        requests = claude_host(world, approved)
        assert len(requests) == 1 and requests[0]["input"]["command"] == world.command
        assert (world.output.read_text() == "STANDIN_WRITE\n") == approved
    finally:
        close(world)


@pytest.mark.parametrize("tool", ["claude", "codex"])
@pytest.mark.parametrize(
    "variant", ["omitted", "reordered", "combined", "relative_entry", "other_python"]
)
def test_alternate_write_invocation_cannot_reach_credentials(tmp_path, tool, variant):
    """Bug: a spelling that misses the native prefix still reaches the write credential flow."""
    world = prepared_action(tmp_path, tool, "jira-write")
    try:
        runtime = world.entry.parent / "service_actions/runtime.py"
        runtime.chmod(0o644)
        runtime.write_text("def require(**_kwargs): pass\n")
        runtime.chmod(0o444)
        command = _variant(world.command, world, variant)
        world.server.script = [
            ("Bash", {"command": command})
            if tool == "claude"
            else ("exec_command", {"cmd": command, "login": False})
        ]
        client = world.client
        argv = ["auto" if arg == "bypassPermissions" else arg for arg in client.argv]
        if tool == "claude":
            argv[argv.index("--") : argv.index("--")] = [
                "--settings",
                str(client.cwd / ".claude/access-settings.json"),
            ]
        else:
            argv[2:2] = ["--approve-for-me"]
        run(replace(client, argv=argv))
        assert json.loads(world.output.read_text())["result"] == "NATIVE_APPROVAL_REQUIRED"
    finally:
        close(world)


def _variant(command, world, variant):
    if variant == "relative_entry":
        return command.replace(str(world.entry), str(world.entry.relative_to(world.client.cwd)))
    if variant == "other_python":
        python = Path(__file__).resolve().parents[3] / ".venv/bin/python"
        return command.replace(str(PYTHON), str(python), 1)
    flags = {"omitted": "", "reordered": " -S -s -E", "combined": " -EsS"}
    return command.replace(" -E -s -S", flags[variant])


def test_codex_can_approve_the_single_actual_preview_by_reference(tmp_path):
    """Bug: exact-command approval requires retyping a command already previewed in the session."""
    world = prepared_native(tmp_path, "codex", "jira-write")
    try:
        marker_consumer(world)
        world.server.preview = world.command
        run(replace(world.client, argv=[*world.client.argv[:-1], "Preview only."]))
        world.server.preview = None
        world.server.script = [("mcp__jira_write__run", {"command": world.command})]
        tail = world.client.argv[2:-1]
        tail.remove("--approve-for-me")
        at = tail.index("-C")
        del tail[at : at + 2]
        argv = [
            world.client.argv[0],
            "exec",
            "--approve-for-me",
            "resume",
            "--last",
            *tail,
            "I approve that one previewed command.",
        ]
        run(replace(world.client, argv=argv, evidence=world.client.evidence.with_name("resume")))
        assert world.output.read_text() == "STANDIN_WRITE\n"
    finally:
        close(world)


def test_codex_read_keeps_its_existing_review_without_write_intent(tmp_path):
    """Bug: adding write intent silently makes an authorized read require exact write approval."""
    world = prepared_action(tmp_path, "codex", "jira-read")
    try:
        marker_entry(world)
        world.command = world.command.split(" --comment ")[0] + " --issue TEST-7"
        world.server.script = [("exec_command", {"cmd": world.command, "login": False})]
        argv = [*world.client.argv[:2], "--approve-for-me", *world.client.argv[2:]]
        run(replace(world.client, argv=argv))
        assert world.output.read_text() == "STANDIN_WRITE"
    finally:
        close(world)
