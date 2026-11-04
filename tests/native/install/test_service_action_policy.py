"""Native clients run the exact selected read and leave every other form to their own checks."""

from dataclasses import replace
import json
import os
from pathlib import Path
import shlex
import subprocess

import pytest

from slopmeister.install.service_actions import action_payload
from slopmeister.session.service_actions.constants import PYTHON, PYTHON_FLAGS
from tests.integration.install.helpers import ROOT, profile, selected_context, unlock_deliveries
from tests.native.install.test_permissions import client_command
from tests.support.standin import capture_server, run, tool_results


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
def test_only_the_exact_read_entry_is_allowed_and_secret_denies_hold(tmp_path, namespaced):
    base = _policy_command(tmp_path, namespaced)
    action = "example/jira-read" if namespaced else "jira-read"
    entry = tmp_path / "session/.codex/service-actions" / action / "entry.py"
    direct = [str(PYTHON), *PYTHON_FLAGS, str(entry)]
    cases = [
        ([*direct, "--issue", "TEST-7"], "allow"),
        ([str(PYTHON), str(entry), "--issue", "TEST-7"], None),
        ([str(PYTHON), *PYTHON_FLAGS, str(tmp_path / "shadow/entry.py")], None),
        ([str(PYTHON), *PYTHON_FLAGS, "-m", "service_actions.supervisor"], None),
        (["op", "document", "get", "EXAMPLE"], "forbidden"),
    ]
    for argv, expected in cases:
        result = subprocess.run([*base, *argv], capture_output=True, text=True, timeout=10)
        assert json.loads(result.stdout).get("decision") == expected, argv


ENTRY = """import os, sys
from pathlib import Path
Path(os.environ["SLOPMEISTER_PROOF"]).write_text("RAN")
"""


def _deliver_entry(client, context, native):
    action = "example/jira-read" if context.namespaced else "jira-read"
    entry = client.cwd / native / "service-actions" / action / "entry.py"
    entry.parent.mkdir(parents=True)
    entry.write_text(ENTRY)
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
        command = f"{PYTHON} {' '.join(PYTHON_FLAGS)} {entry} --issue TEST-7"
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
        command = shlex.join([str(PYTHON), *PYTHON_FLAGS, str(entry), "--issue", "TEST-7"])
        server.script = [("Bash", {"command": shape(command)})]
        argv = ["auto" if arg == "bypassPermissions" else arg for arg in client.argv]
        argv[argv.index("--") : argv.index("--")] = ["--settings", str(access)]
        run(replace(client, argv=argv, env={**client.env, "SLOPMEISTER_PROOF": str(proof)}))
    finally:
        server.shutdown()
        server.server_close()
    return proof, json.dumps(tool_results(server.requests[-1]))


@pytest.mark.xdist_group("native-standin")
@pytest.mark.parametrize("namespaced", [False, True])
def test_real_claude_runs_the_exact_read_with_no_ask(tmp_path, namespaced):
    """Bug: a selected read stops at an ask or the auto mode classifier."""
    proof, results = _claude_read(tmp_path, namespaced, lambda command: command)
    assert proof.read_text() == "RAN" and "requested permissions" not in results


@pytest.mark.xdist_group("native-standin")
def test_real_claude_runs_a_read_from_a_workspace_with_a_space(tmp_path):
    """Bug: the delivered command quotes the entry and the unquoted allow entry misses it."""
    root = tmp_path / "with space"
    root.mkdir()
    proof, results = _claude_read(root, False, lambda command: command)
    assert proof.read_text() == "RAN" and "requested permissions" not in results


@pytest.mark.xdist_group("native-standin")
def test_real_claude_keeps_a_piped_read_out_of_the_allow_rule(tmp_path):
    """Bug: the allow rule carries an added command past the auto mode classifier."""
    proof, _ = _claude_read(tmp_path, False, lambda command: f"{command} | /usr/bin/tee /tmp/x")
    assert not proof.exists()


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
