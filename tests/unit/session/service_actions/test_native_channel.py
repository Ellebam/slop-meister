"""A delivered write cannot reach credentials through an ordinary process launch."""

import json
from pathlib import Path
import sys

import pytest

from slopmeister.session.service_actions import native_gate
from slopmeister.session.service_actions.constants import PYTHON, PYTHON_FLAGS
from tests.integration.install.helpers import consumer

SERVER = (
    '[mcp_servers.jira_write]\ncommand="/writer"\nargs=[]\n'
    '[mcp_servers.jira_write.tools.run]\napproval_mode="prompt"\n'
)
PIN = 'mcp_servers.jira_write={command="/writer",args=[],tools={run={approval_mode="prompt"}}}'


@pytest.mark.parametrize("direct", [False, True])
def test_native_only_write_refuses_before_credential_resolution(tmp_path, monkeypatch, direct):
    """Bug: a shell wrapper keeps canonical argv and reaches the write credential flow."""
    subject, data, _ = consumer(tmp_path, monkeypatch)
    data.update(action="jira-write", native={"tool": "codex", "cli": "/missing/codex"})
    (tmp_path / "config.json").write_text(json.dumps(data))
    entry = [str(tmp_path / "entry.py")] if direct else ["-m", "service_actions.supervisor"]
    monkeypatch.setattr(sys, "executable", str(PYTHON))
    monkeypatch.setattr(sys, "orig_argv", [str(PYTHON), *PYTHON_FLAGS, *entry])
    monkeypatch.setattr(subject, "_identity", lambda *_args: pytest.fail("credentials reached"))
    args = ["--permissions", "TEST"] if direct else None
    with pytest.raises(ValueError, match="NATIVE_APPROVAL_REQUIRED"):
        subject.fetch(args)


@pytest.mark.parametrize(
    "override",
    [
        ["-c", 'mcp_servers.jira_write.tools.run.approval_mode="approve"'],
        ['--config=mcp_servers.jira_write.tools.run.approval_mode="approve"'],
        ['-cmcp_servers.jira_write.tools.run.approval_mode="approve"'],
        ['-c=mcp_servers.jira_write.tools.run.approval_mode="approve"'],
        ["-c", ' approval_policy = "never"'],
        ['--config=approval_policy="never"'],
        ["-a", "never"],
        ["-anever"],
        ["--ask-for-approval=never"],
        ["--dangerously-bypass-approvals-and-sandbox"],
        ["--yolo"],
        ["--profile", "foreign"],
        ["--profile=foreign"],
        ["-pforeign"],
        ["--worktree"],
        ["-c", 'projects."/foreign".trust_level="trusted"'],
        ["-c", 'approvals_reviewer="none"'],
    ],
)
def test_native_client_cannot_disable_the_write_gate(tmp_path, override):
    """Bug: CLI override spellings silently disable the native write approval boundary."""
    config = tmp_path / ".codex/config.toml"
    config.parent.mkdir()
    config.write_text(SERVER)
    binding = {"workspace": str(tmp_path)}
    argv = ["codex", "-c", PIN, *override]
    with pytest.raises(ValueError, match="NATIVE_APPROVAL_REQUIRED"):
        native_gate._codex(binding, argv, "jira_write")


@pytest.mark.parametrize("decision", ["approve", "auto", None])
def test_native_client_refuses_unprompted_write_configuration(tmp_path, decision):
    """Bug: a changed tool permission silently becomes standing write authority."""
    config = tmp_path / ".codex/config.toml"
    config.parent.mkdir()
    mode = f'approval_mode="{decision}"\n' if decision is not None else ""
    config.write_text("[mcp_servers.jira_write.tools.run]\n" + mode)
    with pytest.raises(ValueError, match="NATIVE_APPROVAL_REQUIRED: ask"):
        native_gate._codex(
            {"workspace": str(tmp_path)},
            ["codex", "-c", 'mcp_servers.jira_write.tools.run.approval_mode="prompt"'],
            "jira_write",
        )


def test_native_consumer_refuses_an_unrelated_python_parent(tmp_path, monkeypatch):
    """Bug: any Python parent can impersonate the approved native writer adapter."""
    monkeypatch.setattr(native_gate, "_host", lambda *_args: None)
    monkeypatch.setattr(sys, "executable", str(PYTHON))
    monkeypatch.setattr(
        native_gate,
        "_process",
        lambda _pid: (Path("/usr/bin/python"), ["python", "-c", "forged"], 7),
    )
    with pytest.raises(ValueError, match="NATIVE_APPROVAL_REQUIRED"):
        native_gate.require_consumer(tmp_path, {"tool": "codex"})


def test_codex_adapter_refuses_a_pipe_not_owned_by_the_native_host(tmp_path, monkeypatch):
    """Bug: shell process substitution preserves a native parent and forges MCP stdin."""
    monkeypatch.setattr(
        native_gate.os, "fstat", lambda _fd: type("Info", (), {"st_mode": 0o010000})()
    )
    monkeypatch.setattr(native_gate, "_owned_pipe", lambda _pid: False)
    monkeypatch.setattr(
        native_gate, "_host", lambda *_args: pytest.fail("untrusted pipe reached host")
    )
    with pytest.raises(ValueError, match="NATIVE_APPROVAL_REQUIRED"):
        native_gate.require_host(tmp_path, {"tool": "codex"})


def test_claude_adapter_refuses_a_socket_not_owned_by_the_native_host(tmp_path, monkeypatch):
    """Bug: a shell tool makes its own socket and impersonates native MCP input."""
    monkeypatch.setattr(
        native_gate.os, "fstat", lambda _fd: type("Info", (), {"st_mode": 0o140000})()
    )
    monkeypatch.setattr(native_gate, "_owned_socket", lambda _pid: False, raising=False)
    monkeypatch.setattr(
        native_gate, "_host", lambda *_args: pytest.fail("untrusted socket reached host")
    )
    with pytest.raises(ValueError, match="NATIVE_APPROVAL_REQUIRED"):
        native_gate.require_host(tmp_path, {"tool": "claude"})


def test_codex_refuses_a_client_without_effective_approval_pin(tmp_path):
    """Bug: on-disk prompt rules are mistaken for the config actually loaded by the caller."""
    config = tmp_path / ".codex/config.toml"
    config.parent.mkdir()
    config.write_text(SERVER)
    with pytest.raises(ValueError, match="NATIVE_APPROVAL_REQUIRED"):
        native_gate._codex({"workspace": str(tmp_path)}, ["codex"], "jira_write")


@pytest.mark.parametrize("flag", ["-c", "--config", "--config=", "-c="])
@pytest.mark.parametrize("reviewer", ["user", "auto_review"])
def test_native_client_accepts_its_pinned_native_approval(tmp_path, flag, reviewer):
    """Bug: override validation rejects the launcher's safe approval settings."""
    config = tmp_path / ".codex/config.toml"
    config.parent.mkdir()
    config.write_text(SERVER)
    pin = PIN
    argv = ["codex", *([flag, pin] if flag in ("-c", "--config") else [flag + pin])]
    argv += ["-aon-request", "-c", f'approvals_reviewer="{reviewer}"']
    native_gate._codex({"workspace": str(tmp_path)}, argv, "jira_write")


def test_native_host_refuses_a_different_executable(tmp_path, monkeypatch):
    """Bug: a shell interpreter impersonates the configured native client."""
    monkeypatch.setattr(native_gate, "_process", lambda _pid: (tmp_path / "shell", [], 1))
    monkeypatch.setattr(native_gate, "_claude", lambda *_args: None)
    with pytest.raises(ValueError, match="NATIVE_APPROVAL_REQUIRED: client"):
        native_gate._host({"cli": str(tmp_path / "claude"), "tool": "claude"}, "jira_write", 1)
    monkeypatch.setattr(
        native_gate.os, "fstat", lambda _fd: type("Info", (), {"st_mode": 0o010000})()
    )
    monkeypatch.setattr(native_gate, "_owned_pipe", lambda _pid: True)
    with pytest.raises(ValueError, match="NATIVE_APPROVAL_REQUIRED: client"):
        native_gate.require_host(tmp_path, {"cli": str(tmp_path / "codex"), "tool": "codex"})


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("mode", ""),
        ("bypass", ""),
        ("settings", ""),
        ("mcp", ""),
        ("ask", ": ask"),
        ("duplicate", ""),
    ],
)
def test_claude_caller_keeps_its_explicit_write_ask(tmp_path, change, reason):
    """Bug: a native client runs a writer after its permission mode or ask rule was replaced."""
    settings = tmp_path / ".claude/access-settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"permissions": {"ask": ["mcp__jira_write__run"]}}))
    argv = [
        "claude",
        "--permission-mode",
        "auto",
        "--settings",
        str(settings),
        "--mcp-config",
        str(tmp_path / ".claude/service-actions/mcp.json"),
    ]
    positions = {
        "mode": (2, "bypassPermissions"),
        "settings": (4, "/unprepared/settings.json"),
        "mcp": (6, "/unprepared/mcp.json"),
    }
    if change in positions:
        index, value = positions[change]
        argv[index] = value
    if change == "bypass":
        argv.append("--dangerously-skip-permissions")
    if change == "ask":
        settings.write_text('{"permissions":{"ask":[]}}')
    if change == "duplicate":
        argv += ["--settings=" + str(settings)]
    with pytest.raises(ValueError, match="NATIVE_APPROVAL_REQUIRED" + reason):
        native_gate._claude({"workspace": str(tmp_path)}, argv, "jira_write")


def test_native_adapter_refuses_an_ordinary_input_file(tmp_path, monkeypatch):
    """Bug: shell redirection is accepted as the native client's private RPC channel."""
    monkeypatch.setattr(
        native_gate.os, "fstat", lambda _fd: type("Info", (), {"st_mode": 0o100000})()
    )
    monkeypatch.setattr(native_gate, "_owned_pipe", lambda _pid: True)
    monkeypatch.setattr(native_gate, "_host", lambda *_args: None)
    with pytest.raises(ValueError, match="NATIVE_APPROVAL_REQUIRED"):
        native_gate.require_host(tmp_path, {"tool": "codex"})


def test_other_delivered_server_pins_and_disable_only_overrides_are_preserved(tmp_path):
    config = tmp_path / ".codex/config.toml"
    config.parent.mkdir()
    config.write_text(SERVER + '[mcp_servers.optional]\ncommand="/reader"\nargs=[]\n')
    argv = [
        "codex",
        "-c",
        PIN,
        "-c",
        'mcp_servers.optional={command="/reader",args=[]}',
        "-c",
        "mcp_servers.optional.enabled=false",
    ]
    native_gate._codex({"workspace": str(tmp_path)}, argv, "jira_write")
    argv += ["-c", "mcp_servers.jira_write.enabled=false"]
    with pytest.raises(ValueError, match="NATIVE_APPROVAL_REQUIRED"):
        native_gate._codex({"workspace": str(tmp_path)}, argv, "jira_write")


@pytest.mark.parametrize(
    "override",
    [
        'mcp_servers.jira_write={command="/other"}',
        'mcp_servers.jira_write.tools.run.approval_mode="prompt"',
        '"mcp_servers" . jira_write.command="/other"',
    ],
)
def test_server_replacement_or_partial_pin_is_refused(tmp_path, override):
    config = tmp_path / ".codex/config.toml"
    config.parent.mkdir()
    config.write_text(SERVER)
    with pytest.raises(ValueError, match="NATIVE_APPROVAL_REQUIRED"):
        native_gate._codex(
            {"workspace": str(tmp_path)}, ["codex", "-c", PIN, "-c", override], "jira_write"
        )
