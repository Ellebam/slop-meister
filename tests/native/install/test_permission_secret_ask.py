"""Both native clients run op run without a prompt and refuse the value-printing forms."""

from dataclasses import replace
import json
from pathlib import Path
import subprocess

import pytest

from tests.native.install.test_permissions import client_command, shell_call
from tests.support.fakes import fake_binary
from tests.support.standin import capture_server, run, tool_results

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.xdist_group("native-standin")


def _client(tool, root, port):
    # The stub stands where the delivered op shim stands: first on PATH, named op.
    fake_binary(root / "stubs", "op", 'echo OP_RAN "$@"')
    client = client_command(tool, root, port)
    argv = ["auto" if part == "bypassPermissions" else part for part in client.argv]
    if tool == "codex":
        argv[2:2] = ["--approve-for-me"]
    return replace(client, argv=argv)


@pytest.mark.parametrize("tool", ["claude", "codex"])
def test_real_client_runs_op_run_unprompted_and_refuses_value_reads(tmp_path, monkeypatch, tool):
    """Bug: op run trips a native prompt nobody can answer remotely, or op read runs."""
    env_file = tmp_path / "demo.env"
    env_file.write_text("DEMO=op://Example/Demo/password\n")
    calls = ["op read op://Example/Demo/password", f"op run --env-file={env_file} -- true"]
    server = capture_server(tmp_path / "requests", tool, [shell_call(tool, c) for c in calls])
    try:
        run(_client(tool, tmp_path, server.server_port))
    finally:
        server.shutdown()
        server.server_close()
    main = [
        r
        for r in server.requests
        if r.get("model") != "codex-auto-review"
        and "security monitor" not in json.dumps(r.get("system", "")).lower()
    ]
    results = tool_results(main[-1])
    assert len(results) == 2
    assert "OP_RAN read" not in json.dumps(results[0])
    assert "OP_RAN run" in json.dumps(results[1])
    assert "review failure" not in json.dumps(results)


def test_codex_rules_allow_op_run_and_keep_the_value_denies():
    """Bug: the allow on op run overrides the refusal of unmasked output or value reads, or an
    agent types the relay and reads values from its transcript."""
    binary = str(Path.home() / ".local/bin/codex")
    base = [
        binary,
        "execpolicy",
        "check",
        "--rules",
        str(ROOT / "dist/codex/rules/permissions.rules"),
        "--",
    ]
    for argv, expected in (
        (["op", "run", "--env-file=x.env", "--", "true"], "allow"),
        (["op", "run", "--no-masking", "--", "true"], "forbidden"),
        (["op", "read", "op://A/B/C"], "forbidden"),
        (["op", "inject"], "forbidden"),
        (["slopmeister", "secret-ask", "relay"], "forbidden"),
    ):
        result = subprocess.run(
            [*base, *argv], capture_output=True, text=True, timeout=10, check=True
        )
        assert json.loads(result.stdout)["decision"] == expected, argv
