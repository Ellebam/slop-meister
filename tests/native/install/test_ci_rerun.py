"""The real clients admit the fixed entry without sending an approval request."""

from dataclasses import replace
import json
from pathlib import Path
import shlex
from types import SimpleNamespace

import pytest

from tests.integration.session.test_ci_rerun_world import world as provider_world
from tests.native.install.intent_fixture import IntentModel, claude_host, is_review, main_results
from tests.native.install.test_permissions import client_command, shell_call
from tests.support.standin import capture_server, run


def native_world(root, tool, shipping="allow"):
    fixture = root / "fixture"
    fixture.mkdir()
    workspace, environment, state = provider_world(fixture, "github", shipping)
    native = ".agents" if tool == "codex" else ".claude"
    entry = workspace / native / "skills/ci-rerun/scripts/ci_rerun.py"
    command = shlex.join(["python3", str(entry), "--run", "7"])
    server = capture_server(root / "requests", tool, [shell_call(tool, command)])
    server.RequestHandlerClass = IntentModel
    native_root = root / "native"
    native_root.mkdir()
    client = client_command(tool, native_root, server.server_port)
    client.env.update(PATH=environment["PATH"], CI_FIXTURE=environment["CI_FIXTURE"])
    argv = ["auto" if arg == "bypassPermissions" else arg for arg in client.argv]
    if tool == "claude":
        settings = client.cwd / ".claude/access-settings.json"
        settings.parent.mkdir()
        settings.write_bytes((workspace / ".claude/access-settings.json").read_bytes())
    else:
        rules = Path(client.env["CODEX_HOME"]) / "rules/ci-rerun.rules"
        rules.write_bytes((workspace / ".codex/rules/ci-rerun.rules").read_bytes())
    return SimpleNamespace(
        client=replace(client, argv=argv),
        server=server,
        command=command,
        state=state,
        workspace=workspace,
    )


@pytest.mark.xdist_group("native-standin")
@pytest.mark.parametrize("tool", ["claude", "codex"])
@pytest.mark.parametrize("shipping", ["allow", "deny"])
def test_fixed_ci_entry_runs_in_auto_mode_without_approval(tmp_path, tool, shipping):
    current = native_world(tmp_path, tool, shipping)
    try:
        if tool == "claude":
            assert claude_host(current, approved=False) == []
        else:
            run(current.client)
        output = main_results(current)
        assert '"result": "success"' in output.replace('\\"', '"'), output
        assert json.loads(current.state.read_text())["attempt"] == 2
        assert not any(is_review(body) for body in current.server.requests)
    finally:
        current.server.shutdown()
        current.server.server_close()


@pytest.mark.xdist_group("native-standin")
@pytest.mark.parametrize("tool", ["claude", "codex"])
def test_client_cannot_overwrite_the_fixed_entry(tmp_path, tool):
    current = native_world(tmp_path, tool)
    entry = current.workspace / ".agents/skills/ci-rerun/scripts/ci_rerun.py"
    original = entry.read_bytes()
    if tool == "codex":
        current.client = replace(
            current.client,
            argv=[
                current.client.argv[0],
                "-c",
                'sandbox_mode="danger-full-access"',
                *current.client.argv[1:],
            ],
        )
    command = "printf replaced > " + shlex.quote(str(entry))
    current.server.script = [shell_call(tool, command)]
    current.command = command
    try:
        if tool == "claude":
            claude_host(current, approved=False)
        else:
            run(current.client)
        assert entry.read_bytes() == original
        expected = "has been denied" if tool == "claude" else "permission denied"
        assert expected in main_results(current).lower()
        assert "attempt" not in json.loads(current.state.read_text())
    finally:
        current.server.shutdown()
        current.server.server_close()
