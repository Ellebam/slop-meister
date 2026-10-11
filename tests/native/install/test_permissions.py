"""Real clients refuse direct denies and differ on env wrappers against a stand-in model."""

import json
from pathlib import Path
import shutil

import pytest

from slopmeister.render.settings import permission_contract
from tests.native.install.discovery_fixture import CLAUDE, CODEX
from tests.support.fakes import fake_binary, path_with
from tests.support.standin import Command, capture_server, run, tool_results

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = permission_contract(ROOT / "src/permissions.toml")
DENIED = [entry["prefix"] for entry in CONTRACT["command"] if entry["decision"] == "deny"]
EXECUTABLES = sorted({prefix.split()[0] for prefix in DENIED})
# Claude renders each deny as a bare and a `prefix *` pattern, so both forms are tried.
DENIED_CALLS = DENIED + [prefix + " standin-probe" for prefix in DENIED]
WRAPPED = ["env " + prefix for prefix in DENIED]
# Unlisted calls prove each stub runs when nothing refuses it, so a refusal is not a missing binary.
CONTROLS = [executable + " standin-control" for executable in EXECUTABLES]
CONTROLS += ["env " + command for command in CONTROLS]
# Every stub prints this, so an execution is told apart from a refusal that quotes the command.
RAN = "STANDIN_RAN"


@pytest.mark.xdist_group("native-standin")
@pytest.mark.parametrize("tool", ["claude", "codex"])
def test_every_deny_entry_is_refused_by_the_real_client(tmp_path, tool):
    assert DENIED, "src/permissions.toml lists no deny entry"
    for executable in EXECUTABLES:
        fake_binary(tmp_path / "stubs", executable, f'echo "{RAN} {executable} $*;"')
    commands = DENIED_CALLS + WRAPPED + CONTROLS
    server = capture_server(tmp_path / "requests", tool, [shell_call(tool, c) for c in commands])
    try:
        client = client_command(tool, tmp_path, server.server_port)
        for executable in EXECUTABLES:
            assert shutil.which(executable, path=client.env["PATH"]) == str(
                tmp_path / "stubs" / executable
            ), "a credential command would miss its private stub"
        run(client)
    finally:
        server.shutdown()
        server.server_close()
    results = tool_results(server.requests[-1])
    assert len(results) == len(commands), "a scripted call got no result"
    ran = {
        command
        for command, result in zip(commands, results, strict=True)
        if f"{RAN} {command.removeprefix('env ')};" in json.dumps(result)
    }
    assert [c for c in CONTROLS if c not in ran] == [], "a stub did not run when unrefused"
    assert [c for c in DENIED_CALLS if c in ran] == [], "a denied command executed"
    assert [c for c in WRAPPED if c in ran] == (WRAPPED if tool == "codex" else []), (
        "env matching changed; update the documented client gap"
    )


def shell_call(tool, command):
    if tool == "claude":
        return "Bash", {"command": command}
    return "exec_command", {"cmd": command, "login": False}


def client_command(tool, root, port):
    home, workspace = root / "home", root / "workspace"
    for path in (home, workspace):
        path.mkdir()
    env = {"PATH": path_with(root / "stubs"), "HOME": str(home), "TMPDIR": str(root)}
    if tool == "claude":
        return Command(claude_argv(root, env, port), workspace, env, root / "claude")
    return Command(codex_argv(root, env, port, workspace), workspace, env, root / "codex")


def claude_argv(root, env, port):
    config = root / "claude-config"
    config.mkdir()
    shutil.copy(ROOT / "dist/claude/settings.json", config / "settings.json")
    env.update(
        CLAUDE_CONFIG_DIR=str(config),
        ANTHROPIC_API_KEY="stand-in",
        ANTHROPIC_BASE_URL=f"http://127.0.0.1:{port}",
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
    )
    # bypassPermissions leaves the deny list as the only thing that can refuse a call.
    mode = ["--permission-mode", "bypassPermissions", "--tools", "Bash", "--strict-mcp-config"]
    return [CLAUDE, "-p", "--output-format", "stream-json", "--verbose", *mode, "--", "Go."]


def codex_argv(root, env, port, workspace):
    home = root / "codex-home"
    (home / "rules").mkdir(parents=True)
    shutil.copy(ROOT / "dist/codex/rules/permissions.rules", home / "rules/permissions.rules")
    env.update(CODEX_HOME=str(home), OPENAI_API_KEY="stand-in")
    provider = [
        "-c",
        "model_provider=standin",
        "-c",
        'model_providers.standin.name="standin"',
        "-c",
        f'model_providers.standin.base_url="http://127.0.0.1:{port}/v1"',
        "-c",
        'model_providers.standin.wire_api="responses"',
        "-c",
        'model_providers.standin.env_key="OPENAI_API_KEY"',
    ]
    command = [str(CODEX), "exec", "--skip-git-repo-check", "-C", str(workspace), *provider]
    return [*command, "-m", "stand-in", "Go."]
