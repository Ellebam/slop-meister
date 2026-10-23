"""Old deliveries retain their fixed native contract and never adopt foreign scratch."""

import json
import os
import subprocess

import pytest

from slopmeister.launch import command, workspace
from slopmeister.launch.model import Launch, Stop


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    launch = Launch("example-notes", "example-notes-one", "", tool="codex")
    launch.wt = tmp_path / launch.name
    launch.wt.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(workspace, "state_directory", lambda _: (state, True))
    monkeypatch.setenv("PLOT_SESSION_STATE_DIR", str(tmp_path))
    (state / "state.json").write_text("{}")
    return launch, state / "state.json"


def test_legacy_state_never_adopts_a_same_named_scratch_directory(delivery):
    launch, _ = delivery
    foreign = launch.wt / ".slopmeister-tmp"
    foreign.mkdir()
    (foreign / "keep").write_text("foreign")
    before = (foreign / "keep").read_bytes()
    workspace.capabilities(launch)
    assert launch.scratch is None and launch.native_server_pins is False
    launch.line = f"cd '{launch.wt}' && env"
    command.write(launch)
    assert "export TMPDIR=" not in launch.command_file.read_text()
    assert (foreign / "keep").read_bytes() == before


def test_recorded_scratch_is_exported_to_the_executed_child(delivery):
    launch, state = delivery
    scratch = launch.wt / ".slopmeister-tmp"
    scratch.mkdir(mode=0o700)
    state.write_text(json.dumps({"scratch": scratch.name, "native_server_pins": True}))
    workspace.capabilities(launch)
    launch.line = f"cd '{launch.wt}' && env"
    command.write(launch)
    result = subprocess.run(
        ["zsh", "-f", str(launch.command_file)],
        capture_output=True,
        text=True,
        env={**os.environ, "TMPDIR": "/unused-parent"},
    )
    assert result.returncode == 0
    assert f"TMPDIR={scratch}\n" in result.stdout
    assert f"SLOPMEISTER_SESSION_WORKSPACE={launch.wt}\n" in result.stdout


@pytest.mark.parametrize("damage", ["missing", "linked", "public", "record", "pins"])
def test_invalid_saved_ownership_refuses_without_changing_files(delivery, damage):
    launch, state = delivery
    scratch = launch.wt / ".slopmeister-tmp"
    saved = {"scratch": scratch.name, "native_server_pins": True}
    if damage == "linked":
        scratch.symlink_to(state.parent, target_is_directory=True)
    elif damage != "missing":
        scratch.mkdir(mode=0o755 if damage == "public" else 0o700)
    if damage == "record":
        saved["scratch"] = "../foreign"
    if damage == "pins":
        saved["native_server_pins"] = "true"
    state.write_text(json.dumps(saved))
    before = state.read_bytes()
    with pytest.raises((Stop, FileNotFoundError)):
        workspace.capabilities(launch)
    assert state.read_bytes() == before


def test_legacy_pin_format_matches_the_fixed_consumer(delivery):
    launch, _ = delivery
    config = launch.wt / ".codex/config.toml"
    config.parent.mkdir()
    config.write_text(
        '[mcp_servers.writer]\ncommand="/writer"\n'
        '[mcp_servers.writer.tools.run]\napproval_mode="prompt"\n'
    )
    workspace.capabilities(launch)
    assert command._native_approvals(launch) == (
        " -c 'mcp_servers.writer.tools.run.approval_mode=\"prompt\"'"
    )
