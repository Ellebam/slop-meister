"""Native clients run the exact selected read and leave every other form to their own checks."""

from dataclasses import replace
import json
import os
from pathlib import Path
import shlex
import subprocess

import pytest

from slopmeister.install.service_actions import SHEBANG, action_payload
from slopmeister.session.service_actions.constants import PYTHON, PYTHON_FLAGS
from tests.integration.install.helpers import ROOT, profile, selected_context, unlock_deliveries
from tests.native.install.discovery_fixture import CODEX
from tests.native.install.intent_fixture import claude_host
from tests.native.install.test_permission_intent import _cleanup_world
from tests.native.install.test_permissions import client_command
from tests.support import standin
from tests.support.standin import capture_server, require_claude_safety, run


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
        str(CODEX),
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
def test_only_the_exact_read_entry_is_allowed_and_secret_denies_hold(tmp_path, namespaced):
    base = _policy_command(tmp_path, namespaced)
    action = "example/jira-read" if namespaced else "jira-read"
    entry = tmp_path / "session/.codex/service-actions" / action / "entry.py"
    cases = [
        ([str(entry), "--issue", "TEST-7"], "allow"),
        ([str(PYTHON), *PYTHON_FLAGS, str(entry), "--issue", "TEST-7"], None),
        ([str(PYTHON), str(entry), "--issue", "TEST-7"], None),
        ([str(tmp_path / "shadow/entry.py")], None),
        ([str(PYTHON), *PYTHON_FLAGS, str(tmp_path / "shadow/entry.py")], None),
        ([str(PYTHON), *PYTHON_FLAGS, "-m", "service_actions.supervisor"], None),
        (["op", "document", "get", "EXAMPLE"], "forbidden"),
    ]
    for argv, expected in cases:
        result = subprocess.run([*base, *argv], capture_output=True, text=True, timeout=10)
        assert json.loads(result.stdout).get("decision") == expected, argv


# The proof names the isolation the delivered first line must give the read.
ENTRY = b"""import os, sys
from pathlib import Path
isolated = sys.flags.ignore_environment and sys.flags.no_user_site and sys.flags.no_site
Path(os.environ["SLOPMEISTER_PROOF"]).write_text("RAN" if isolated else "NOT ISOLATED")
"""


def _deliver_entry(client, context, native):
    action = "example/jira-read" if context.namespaced else "jira-read"
    entry = client.cwd / native / "service-actions" / action / "entry.py"
    entry.parent.mkdir(parents=True)
    entry.write_bytes(SHEBANG + ENTRY)
    entry.chmod(0o555)
    return entry


def _codex_read(tmp_path, namespaced, shape):
    """Run one Codex command against the delivered rule, with a proof path outside the sandbox."""
    server = capture_server(tmp_path / "requests", "codex", [])
    outside = tmp_path / "outside"
    outside.mkdir()
    proof = outside / "ran"
    try:
        client = client_command("codex", tmp_path, server.server_port)
        context = replace(
            selected_context(tmp_path / "fixture"), workspace=client.cwd, namespaced=namespaced
        )
        rules = action_payload(context)[0][".codex/rules/service-actions.rules"][0].decode()
        (Path(client.env["CODEX_HOME"]) / "rules/service-actions.rules").write_text(rules)
        entry = _deliver_entry(client, context, ".codex")
        command = f"{entry} --issue TEST-7"
        server.script = [("exec_command", {"cmd": shape(command)})]
        sandbox = ["-c", "sandbox_workspace_write.exclude_slash_tmp=true"]
        sandbox += ["-c", "sandbox_workspace_write.exclude_tmpdir_env_var=true"]
        argv = [*client.argv[:2], "--approve-for-me", *sandbox, *client.argv[2:]]
        env = {**client.env, "SLOPMEISTER_PROOF": str(proof)}
        run(replace(client, argv=argv, env=env))
    finally:
        server.shutdown()
        server.server_close()
    return proof, len(server.requests)


@pytest.mark.xdist_group("native-standin")
@pytest.mark.parametrize("namespaced", [False, True])
def test_real_codex_runs_the_exact_read_with_no_review(tmp_path, namespaced):
    """Bug: a selected read stops at a reviewer or stays sandboxed, so a worker cannot finish."""
    proof, requests = _codex_read(tmp_path, namespaced, lambda command: command)
    assert proof.read_text() == "RAN" and requests == 2


@pytest.mark.xdist_group("native-standin")
def test_real_codex_keeps_a_chained_read_inside_the_sandbox(tmp_path):
    """Bug: the allow rule carries an added command outside the sandbox with no review."""
    proof, _ = _codex_read(tmp_path, False, lambda command: f"true && {command}")
    assert not proof.exists()


def _claude_read(tmp_path, namespaced, shape):
    server = capture_server(tmp_path / "requests", "claude", [])
    outside = tmp_path / "outside"
    outside.mkdir()
    proof = outside / "ran"
    try:
        client = client_command("claude", tmp_path, server.server_port)
        context = replace(
            selected_context(tmp_path / "fixture"), workspace=client.cwd, namespaced=namespaced
        )
        access = tmp_path / "access-settings.json"
        access.write_text(json.dumps({"permissions": action_payload(context)[1]}))
        entry = _deliver_entry(client, context, ".claude")
        command = shlex.join([str(entry), "--issue", "TEST-7"])
        server.script = [("Bash", {"command": shape(command)})]
        argv = ["auto" if arg == "bypassPermissions" else arg for arg in client.argv]
        argv[argv.index("--") : argv.index("--")] = ["--settings", str(access)]
        output = run(
            replace(client, argv=argv, env={**client.env, "SLOPMEISTER_PROOF": str(proof)})
        )
        frames = [json.loads(line) for line in output.splitlines()]
        require_claude_safety(frames)
    finally:
        server.shutdown()
        server.server_close()
    return proof, frames


@pytest.fixture
def flagged_classifier(monkeypatch):
    original = standin.messages_events

    def flagged_events(call, body, turn):
        events = original(call, body, turn)
        for event in events:
            for result in event.get("delta", {}).get("safeguard_results", []):
                for verdict in result["status"]["tool_uses"].values():
                    verdict["outcome"] = "flagged"
        return events

    monkeypatch.setattr(standin, "messages_events", flagged_events)


@pytest.mark.xdist_group("native-standin")
@pytest.mark.parametrize("namespaced", [False, True])
def test_real_claude_runs_the_exact_read_with_no_ask(tmp_path, namespaced, flagged_classifier):
    """Bug: a selected read stops at an ask or the auto mode classifier."""
    proof, results = _claude_read(tmp_path, namespaced, lambda command: command)
    assert proof.exists(), json.dumps(results)
    assert proof.read_text() == "RAN" and "requested permissions" not in json.dumps(results)


@pytest.mark.xdist_group("native-standin")
def test_real_claude_runs_a_read_from_a_workspace_with_a_space(tmp_path, flagged_classifier):
    """Bug: the delivered command quotes the entry and the unquoted allow entry misses it."""
    root = tmp_path / "with space"
    root.mkdir()
    proof, results = _claude_read(root, False, lambda command: command)
    assert proof.exists(), json.dumps(results)
    assert proof.read_text() == "RAN" and "requested permissions" not in json.dumps(results)


@pytest.mark.xdist_group("native-standin")
def test_real_claude_keeps_a_piped_read_out_of_the_allow_rule(tmp_path, flagged_classifier):
    """Bug: the allow rule carries an added command past the auto mode classifier."""
    proof, frames = _claude_read(
        tmp_path, False, lambda command: f"{command} | /usr/bin/tee {tmp_path}/piped"
    )
    assert any(
        item.get("non_execution_kind") == "automode-blocked"
        for frame in frames
        for item in frame.get("tool_result_meta", [])
    ), json.dumps(frames)
    assert not proof.exists()
    assert not (tmp_path / "piped").exists()


@pytest.mark.xdist_group("native-standin")
@pytest.mark.parametrize("fault", ["missing", "unavailable"])
@pytest.mark.parametrize("channel", ["stdout", "host"])
def test_claude_safety_service_failure_cannot_prove_a_permission_refusal(
    tmp_path, monkeypatch, fault, channel
):
    """A broken classifier must fail proof rather than pass because nothing ran."""
    original = standin.messages_events

    def broken_events(call, body, turn):
        events = original(call, body, turn)
        delta = next(event["delta"] for event in events if event["type"] == "message_delta")
        if fault == "missing":
            delta.pop("safeguard_results", None)
        else:
            delta["safeguard_results"] = [
                dict(type="dangerous_tool_use", status=dict(type="unavailable", reason="error"))
            ]
        return events

    monkeypatch.setattr(standin, "messages_events", broken_events)
    monkeypatch.setattr("tests.native.install.intent_fixture.messages_events", broken_events)
    with pytest.raises(RuntimeError, match="automode-unavailable") as failure:
        if channel == "host":
            # A session may enter the temporary roots by rule, so its own cleanup needs no
            # classifier here. Another workspace's path does.
            world = _cleanup_world(tmp_path, "claude", True, "path")
            try:
                claude_host(world, approved=False)
            finally:
                world.server.shutdown()
                world.server.server_close()
        else:
            _claude_read(
                tmp_path, False, lambda command: f"{command} | /usr/bin/tee {tmp_path}/piped"
            )
    result = json.loads(str(failure.value))["message"]["content"][0]
    assert result["is_error"] and result["content"]
    assert not (tmp_path / "outside/ran").exists() and not (tmp_path / "piped").exists()


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
    (home / ".local/bin/codex").symlink_to(CODEX)
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
