"""Installed Codex policy keeps selected actions behind native approval."""

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess

import pytest

from slopmeister.install.service_actions import action_payload
from slopmeister.session.service_actions.constants import PYTHON, PYTHON_FLAGS
from tests.integration.install.helpers import ROOT, profile, selected_context, unlock_deliveries
from tests.native.install.test_permissions import client_command
from tests.support.standin import capture_server, run, tool_results


def test_action_prompt_names_review_without_claiming_operator_approval(tmp_path):
    """Bug: the automatic reviewer is told a human approval is required or already present."""
    entries, _, _ = action_payload(selected_context(tmp_path))
    rules = entries[".codex/rules/service-actions.rules"][0].decode()
    assert "Native approval review required" in rules
    assert "Operator approval required" not in rules


def _policy_command(tmp_path, namespaced=False):
    context = replace(selected_context(tmp_path), namespaced=namespaced)
    entries, _, _ = action_payload(context)
    rules = tmp_path / "actions.rules"
    rules.write_bytes(entries[".codex/rules/service-actions.rules"][0])
    allow = tmp_path / "saved.rules"
    allow.write_text(
        'prefix_rule(pattern=["task"], decision="allow")\n'
        'prefix_rule(pattern=["op"], decision="allow")\n'
        'prefix_rule(pattern=["python3"], decision="allow")\n'
    )
    return [
        str(Path.home() / ".local/bin/codex"),
        "execpolicy",
        "check",
        "--rules",
        str(rules),
        "--rules",
        str(allow),
        "--rules",
        str(ROOT / "dist/codex/rules/permissions.rules"),
        "--",
    ]


@pytest.mark.parametrize("namespaced", [False, True])
def test_broad_saved_allow_cannot_remove_action_prompt_or_direct_secret_deny(tmp_path, namespaced):
    base = _policy_command(tmp_path, namespaced)
    action = "example/jira-read" if namespaced else "jira-read"
    entry = tmp_path / "session/.codex/service-actions" / action / "entry.py"
    direct = [str(PYTHON), *PYTHON_FLAGS, str(entry)]
    cases = [
        ([*direct, "--output", str(tmp_path / "result"), "--issue", "TEST-7"], "prompt"),
        ([str(PYTHON), *PYTHON_FLAGS, str(tmp_path / "shadow/entry.py")], None),
        ([str(PYTHON), *PYTHON_FLAGS, "-m", "service_actions.supervisor"], "forbidden"),
        (["op", "document", "get", "EXAMPLE"], "forbidden"),
    ]
    for argv, expected in cases:
        result = subprocess.run([*base, *argv], capture_output=True, text=True, timeout=10)
        assert json.loads(result.stdout).get("decision") == expected, argv


@pytest.mark.xdist_group("native-standin")
@pytest.mark.parametrize("namespaced", [False, True])
def test_real_codex_matches_fixed_entry_with_output_argument(tmp_path, namespaced):
    """Bug: shell redirection hides the selected read from the native rule."""
    server = capture_server(tmp_path / "requests", "codex", [])
    try:
        client = client_command("codex", tmp_path, server.server_port)
        context = replace(
            selected_context(tmp_path / "fixture"), workspace=client.cwd, namespaced=namespaced
        )
        rules = action_payload(context)[0][".codex/rules/service-actions.rules"][0].decode()
        assert "/.codex/" in rules.splitlines()[0] and 'decision="prompt"' in rules.splitlines()[0]
        rules = rules.replace('decision="prompt"', 'decision="forbidden"', 1)
        (Path(client.env["CODEX_HOME"]) / "rules/service-actions.rules").write_text(rules)
        action = "example/jira-read" if namespaced else "jira-read"
        entry = client.cwd / ".codex/service-actions" / action / "entry.py"
        entry.parent.mkdir(parents=True)
        entry.write_text(
            "from pathlib import Path\nimport sys\nPath(sys.argv[2]).write_text('RAN')\n"
        )
        output = client.cwd / "result.json"
        output.write_bytes(b"")
        command = f"{PYTHON} {' '.join(PYTHON_FLAGS)} {entry} --output {output} --issue TEST-7"
        server.script = [("exec_command", {"cmd": command, "login": False})]
        run(replace(client, argv=[*client.argv[:2], "--approve-for-me", *client.argv[2:]]))
    finally:
        server.shutdown()
        server.server_close()
    assert "rejected: Native approval review required" in json.dumps(
        tool_results(server.requests[-1])
    )
    assert output.read_bytes() == b""


@pytest.mark.xdist_group("native-standin")
@pytest.mark.parametrize("namespaced", [False, True])
def test_real_claude_asks_for_fixed_entry_in_auto_mode(tmp_path, namespaced):
    """Bug: Claude auto mode runs the selected read without its explicit ask."""
    server = capture_server(tmp_path / "requests", "claude", [])
    try:
        client = client_command("claude", tmp_path, server.server_port)
        context = replace(
            selected_context(tmp_path / "fixture"), workspace=client.cwd, namespaced=namespaced
        )
        access = tmp_path / "access-settings.json"
        access.write_text(json.dumps({"permissions": action_payload(context)[1]}))
        action = "example/jira-read" if namespaced else "jira-read"
        entry = client.cwd / ".claude/service-actions" / action / "entry.py"
        entry.parent.mkdir(parents=True)
        entry.write_text(
            "from pathlib import Path\nimport sys\nPath(sys.argv[2]).write_text('RAN')\n"
        )
        output = client.cwd / "result.json"
        output.write_bytes(b"")
        command = f"{PYTHON} {' '.join(PYTHON_FLAGS)} {entry} --output {output} --issue TEST-7"
        server.script = [("Bash", {"command": command})]
        argv = ["auto" if arg == "bypassPermissions" else arg for arg in client.argv]
        argv[argv.index("--") : argv.index("--")] = ["--settings", str(access)]
        run(replace(client, argv=argv))
    finally:
        server.shutdown()
        server.server_close()
    assert "Claude requested permissions to use Bash" in json.dumps(
        tool_results(server.requests[-1])
    )
    assert output.read_bytes() == b""


def _declaration(tmp_path, enabled):
    declarations = tmp_path / "plots/example-app"
    declarations.mkdir(parents=True)
    action = 'service_actions=["jira-read"]\n' if enabled else ""
    text = (
        '[plot]\nbase="code"\n[target]\ntasks="manual"\n'
        f'{action}[target.repository]\ncommit="deny"\n[slots]\nnone=true\n'
    )
    (declarations / "plot.toml").write_text(text)
    return declarations.parent


def _launcher_fixture(tmp_path, enabled):
    home = tmp_path / "home"
    (home / ".local/bin").mkdir(parents=True)
    (home / ".codex").mkdir()
    (home / ".local/bin/codex").symlink_to(Path.home() / ".local/bin/codex")
    declarations = _declaration(tmp_path, enabled)
    config = home / ".config/slopmeister/access/example-app/jira-read.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps(profile("example-app")))
    config.chmod(0o600)
    vault = tmp_path / "vault"
    vault.mkdir()
    return {
        **os.environ,
        "HOME": str(home),
        "CODEX_HOME": str(home / ".codex"),
        "PLOT_DECLARATIONS": str(declarations),
        "PLOT_SESSION_ROOT": str(tmp_path / "sessions"),
        "PLOT_SESSION_STATE_DIR": str(tmp_path / "state"),
        "PLOT_SESSION_NO_LAUNCH": "1",
        "SLOPMEISTER_VAULT": str(vault),
        "XDG_STATE_HOME": str(tmp_path / "followup"),
    }


@pytest.mark.parametrize("enabled", [False, True])
def test_launcher_keeps_auto_review_with_or_without_service_actions(tmp_path, enabled):
    """Bug: selecting a fixed action silently restores the Mac-only human reviewer."""
    env = _launcher_fixture(tmp_path, enabled)
    args = [
        str(ROOT / "bin/slopmeister"),
        "plot-session",
        "example-app",
        "example-app-actions-test",
        "--tool",
        "codex",
    ]
    try:
        result = subprocess.run(
            args,
            env=env,
            input="Synthetic launch fixture",
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'approvals_reviewer="auto_review"' in result.stdout
        assert 'approvals_reviewer="user"' not in result.stdout
        assert (
            tmp_path / "sessions/example-app-actions-test/.codex/service-actions"
        ).exists() == enabled
    finally:
        unlock_deliveries(tmp_path)
