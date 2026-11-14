"""Native clients discover only the installed session configuration."""

import json
import os

import pytest

from slopmeister.workstation import memory
from tests.native.install.discovery_claude import verify_claude
from tests.native.install.discovery_codex import verify_codex
from tests.native.install.discovery_fixture import ROOT, prepare
from tests.native.install.test_permissions import claude_argv, codex_argv
from tests.support.standin import Command, capture_server, run


@pytest.mark.xdist_group("native-standin")
def test_installed_configuration_excludes_competing_native_discovery(tmp_path):
    root = tmp_path / "discovery"
    root.mkdir()
    verify_claude(prepare(root), verify_codex)


@pytest.mark.xdist_group("native-standin")
@pytest.mark.parametrize("enabled,seeded", [(False, False), (True, True), (False, True)])
def test_codex_memory_switch_controls_native_prompt_loading(tmp_path, enabled, seeded):
    user, workspace, home = tmp_path / "home", tmp_path / "workspace", tmp_path / "codex-home"
    user.mkdir()
    workspace.mkdir()
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(user),
        "TMPDIR": str(tmp_path),
        "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    server = capture_server(tmp_path, "memory", [])
    try:
        argv = codex_argv(tmp_path, env, server.server_port, workspace)
        argv.insert(1, "--no-daemon")
        (home / "config.toml").write_bytes((ROOT / "dist/codex/config.toml").read_bytes())
        if enabled:
            argv[-1:-1] = ["-c", "features.memories=true"]
        if seeded:
            (home / "memories").mkdir()
            (home / "memories/memory_summary.md").write_text("v1\nNATIVE_MEMORY_CONTROL\n")
        before = {str(p): p.read_bytes() for p in (home / "memories").rglob("*") if p.is_file()}
        output = run(Command(argv, workspace, env, tmp_path / "client", 45))
        assert server.requests and "STAND_IN_DONE" in output
        assert ("NATIVE_MEMORY_CONTROL" in json.dumps(server.requests)) is enabled
        if not enabled:
            assert {
                str(p): p.read_bytes() for p in (home / "memories").rglob("*") if p.is_file()
            } == before
            assert not (home / "memories_1.sqlite").exists() or not memory._database_populated(
                home / "memories_1.sqlite"
            )
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.xdist_group("native-standin")
@pytest.mark.parametrize("enabled", [True, False])
def test_claude_memory_switch_controls_native_prompt_section(tmp_path, enabled):
    user, workspace, memory = tmp_path / "home", tmp_path / "workspace", tmp_path / "memory"
    user.mkdir()
    workspace.mkdir()
    memory.mkdir()
    (memory / "MEMORY.md").write_text("NATIVE_CLAUDE_MEMORY_CONTROL\n")
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(user),
        "TMPDIR": str(tmp_path),
        "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    server = capture_server(tmp_path, "memory", [])
    try:
        argv = claude_argv(tmp_path, env, server.server_port)
        settings = json.loads((ROOT / "plots/home/claude/settings.json.tmpl").read_text())
        settings["autoMemoryDirectory"] = str(memory)
        if enabled:
            settings["autoMemoryEnabled"] = True
        (tmp_path / "claude-config/settings.json").write_text(json.dumps(settings))
        before = (memory / "MEMORY.md").read_bytes()
        output = run(Command(argv, workspace, env, tmp_path / "client", 45))
        assert server.requests and "STAND_IN_DONE" in output
        assert ("NATIVE_CLAUDE_MEMORY_CONTROL" in json.dumps(server.requests)) is enabled
        system = json.dumps([request.get("system", []) for request in server.requests])
        assert ("persistent file-based memory" in system.lower()) is enabled
        assert (memory / "MEMORY.md").read_bytes() == before
    finally:
        server.shutdown()
        server.server_close()
