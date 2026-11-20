"""The real clients run the push-only helper without approval and cannot replace it.

The stand-in classifier flags every Claude call, so a push that lands was allowed by the rule.
"""

from dataclasses import replace
from pathlib import Path
import shlex
from types import SimpleNamespace

import pytest

from slopmeister.launch.command import CODEX_APPROVAL, CODEX_SANDBOX
from tests.integration.session.test_ship_push import pushed, remote_head
from tests.native.install import intent_fixture
from tests.native.install.intent_fixture import IntentModel, claude_host, is_review, main_results
from tests.native.install.test_permissions import client_command, shell_call
from tests.support.repos import git
from tests.support.standin import capture_server, run

pytestmark = pytest.mark.xdist_group("native-standin")
LINUX = shlex.split(CODEX_SANDBOX["linux"])
# The Mac's workspace sandbox, so a push outside the worktree runs only when a rule takes it out
# of the sandbox. The fixture lives under the temporary directory, which it would make writable.
MAC = [
    *("-c", 'sandbox_mode="workspace-write"', *shlex.split(CODEX_SANDBOX["darwin"])),
    *("-c", "sandbox_workspace_write.exclude_slash_tmp=true"),
    *("-c", "sandbox_workspace_write.exclude_tmpdir_env_var=true"),
]


@pytest.fixture
def flagged(monkeypatch):
    original = intent_fixture.messages_events

    def flag(call, body, turn):
        events = original(call, body, turn)
        for result in events[-2]["delta"].get("safeguard_results", []):
            for verdict in result["status"]["tool_uses"].values():
                verdict["outcome"] = "flagged"
        return events

    monkeypatch.setattr(intent_fixture, "messages_events", flag)


def native_world(root, tool, command, sandbox):
    fixture = root / "fixture"
    fixture.mkdir()
    current = pushed(fixture)
    text = command(current, ".agents" if tool == "codex" else ".claude")
    server = capture_server(root / "requests", tool, [shell_call(tool, text)])
    server.RequestHandlerClass = IntentModel
    native_root = root / "native"
    native_root.mkdir()
    client = client_command(tool, native_root, server.server_port)
    client.env.update(PATH=current.env["PATH"])
    argv = ["auto" if arg == "bypassPermissions" else arg for arg in client.argv]
    if tool == "claude":
        settings = client.cwd / ".claude/access-settings.json"
        settings.parent.mkdir()
        settings.write_bytes((current.workspace / ".claude/access-settings.json").read_bytes())
    else:
        rules = Path(client.env["CODEX_HOME"]) / "rules/git-permission.rules"
        rules.write_bytes((current.workspace / ".codex/rules/git-permission.rules").read_bytes())
        argv = [argv[0], *shlex.split(CODEX_APPROVAL), *sandbox, *argv[1:]]
    return SimpleNamespace(
        client=replace(client, argv=argv),
        server=server,
        command=text,
        pushed=current,
    )


def push_only(current, native):
    entry = current.workspace / native / "skills/ship/scripts/ship.py"
    return shlex.join(["python3", str(entry), "--push-only", "--cwd", str(current.workspace)])


def host(current, tool):
    try:
        if tool == "claude":
            assert claude_host(current, approved=False) == []
        else:
            run(current.client)
        return main_results(current)
    finally:
        current.server.shutdown()
        current.server.server_close()


@pytest.mark.usefixtures("flagged")
@pytest.mark.parametrize("tool", ["claude", "codex"])
def test_push_only_helper_runs_in_auto_mode_without_approval(tmp_path, tool):
    current = native_world(tmp_path, tool, push_only, MAC)
    output = host(current, tool)
    head = git(current.pushed.workspace, "rev-parse", "HEAD").strip()
    assert remote_head(current.pushed.origin, "refs/heads/shop-t") == head, output
    assert not any(is_review(body) for body in current.server.requests)


@pytest.mark.parametrize("tool", ["claude", "codex"])
def test_client_cannot_overwrite_the_ship_entry(tmp_path, tool):
    def overwrite(pushed, _native):
        entry = pushed.workspace / ".agents/skills/ship/scripts/ship.py"
        return "printf replaced > " + shlex.quote(str(entry))

    current = native_world(tmp_path, tool, overwrite, LINUX)
    entry = current.pushed.workspace / ".agents/skills/ship/scripts/ship.py"
    original = entry.read_bytes()
    output = host(current, tool)
    assert entry.read_bytes() == original
    assert ("has been denied" if tool == "claude" else "permission denied") in output.lower()
