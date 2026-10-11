"""Orca's shared app state is merged only after a proven closed-app reply."""

import json
import stat

import pytest

from slopmeister.errors import SlopmeisterError
from slopmeister.workstation import install, orca


@pytest.fixture(autouse=True)
def mac(monkeypatch):
    """Orca's settings file is a Mac-only install entry."""
    monkeypatch.setenv("SLOPMEISTER_PLATFORM", "darwin")


@pytest.fixture
def home(tmp_path, monkeypatch):
    root = tmp_path / "home"
    path = root / orca.NAME
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "settings": {
                    "telemetry": {"optedIn": True, "installId": "private-identifier"},
                    "terminalQuickCommands": [
                        {"id": "operator-command", "label": "Keep", "command": "echo keep"}
                    ],
                },
                "sessionState": {"token": "private-token"},
            }
        )
    )
    monkeypatch.setattr(
        orca.terminal,
        "_orca",
        lambda *args: {"app": {"running": False}, "runtime": {"reachable": False}},
    )
    return root


def test_install_preserves_foreign_values_and_exact_private_backup(home, tmp_path):
    """Bug: rewriting Orca's file dropped live state or exposed its old bytes in a backup."""
    path = home / orca.NAME
    original = path.read_bytes()
    backups = tmp_path / "backups"
    assert orca.status(home) == "differs"
    orca.install(home, backups)
    saved = backups / orca.NAME
    assert saved.read_bytes() == original
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    assert stat.S_IMODE(backups.stat().st_mode) == 0o700
    updated = json.loads(path.read_text())
    assert updated["sessionState"] == {"token": "private-token"}
    assert updated["settings"]["telemetry"]["installId"] == "private-identifier"
    assert updated["settings"]["terminalQuickCommands"][0]["id"] == "operator-command"
    assert orca.status(home) == "unchanged"
    updated["sessionState"]["token"] = "changed-foreign-value"
    path.write_text(json.dumps(updated))
    assert orca.status(home) == "unchanged"
    updated["settings"]["telemetry"]["optedIn"] = True
    path.write_text(json.dumps(updated))
    assert orca.status(home) == "differs"


@pytest.mark.parametrize(
    "reply",
    [None, {}, {"app": {}}, {"app": {"running": True}}, {"app": {"running": 0}}],
)
def test_install_refuses_unverified_closed_state_before_any_home_write(
    home, tmp_path, monkeypatch, reply
):
    """Bug: a timed-out or malformed status allowed a live Orca file to be replaced."""
    monkeypatch.setattr(orca.terminal, "_orca", lambda *args: reply)
    original = (home / orca.NAME).read_bytes()
    with pytest.raises(SlopmeisterError, match="closed state is unverified"):
        install.install(home, {orca.NAME, ".claude/CLAUDE.md"})
    assert (home / orca.NAME).read_bytes() == original
    assert not (home / ".claude").exists()
    assert not (home / ".slopmeister-backup").exists()


def test_install_refuses_changed_orca_file_after_backup(home, tmp_path, monkeypatch):
    """Bug: Orca changed its state between the installer's read and replace."""
    path = home / orca.NAME
    original = path.read_bytes()

    def status(*args):
        path.write_bytes(original + b" ")
        return {"app": {"running": False}}

    monkeypatch.setattr(orca.terminal, "_orca", status)
    with pytest.raises(SlopmeisterError, match="changed during install"):
        orca.install(home, tmp_path / "backups")
    assert path.read_bytes() == original + b" "
    assert (tmp_path / "backups" / orca.NAME).read_bytes() == original


def test_missing_or_malformed_orca_state_refuses_before_other_install(home):
    """Bug: a new or corrupted Orca profile caused a partial all-home installation."""
    path = home / orca.NAME
    for text in (None, "{invalid", '{"settings":[]}', '{"settings":{"terminalQuickCommands":{}}}'):
        if text is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(text)
        with pytest.raises(SlopmeisterError, match="open Orca once"):
            install.install(home, {orca.NAME, ".claude/CLAUDE.md"})
        assert not (home / ".claude").exists()


@pytest.mark.parametrize(
    ("status_reply", "hooks_reply", "expected"),
    [
        ({"app": {"running": False}}, None, ("not running", "not checked")),
        (
            {"app": {"running": True}, "runtime": {"reachable": False}},
            None,
            ("unreachable", "not checked"),
        ),
        (
            {"app": {"running": True}, "runtime": {"reachable": True}},
            {"enabled": False},
            ("running", "off"),
        ),
        (
            {"app": {"running": True}, "runtime": {"reachable": True}},
            {
                "enabled": True,
                "statuses": [
                    {"agent": "claude", "state": "installed", "managedHooksPresent": True},
                    {"agent": "codex", "state": "installed", "managedHooksPresent": True},
                ],
            },
            ("running", "on"),
        ),
        (
            {"app": {"running": True}, "runtime": {"reachable": True}},
            {"enabled": True, "statuses": []},
            ("running", "unverified"),
        ),
        (
            {"app": {"running": True}, "runtime": {"reachable": True}},
            {"enabled": True},
            ("running", "unverified"),
        ),
        (
            {"app": {"running": True}, "runtime": {"reachable": True}},
            {"enabled": True, "statuses": [{"agent": [], "state": "installed"}]},
            ("running", "unverified"),
        ),
        (
            {"app": {"running": True}, "runtime": {"reachable": True}},
            {
                "enabled": True,
                "statuses": [
                    {"agent": "claude", "state": "installed", "managedHooksPresent": True},
                    {"agent": "codex", "state": "installed", "managedHooksPresent": False},
                ],
            },
            ("running", "unverified"),
        ),
    ],
)
def test_doctor_reports_orca_runtime_and_hook_health(
    tmp_path, monkeypatch, status_reply, hooks_reply, expected
):
    """Bug: ok:true from closed Orca or enabled hooks without installed agents read as healthy."""
    binary = tmp_path / "orca"
    binary.write_text("")
    binary.chmod(0o755)
    monkeypatch.setenv("PLOT_SESSION_ORCA", str(binary))
    calls = []

    def answer(*args):
        calls.append(args)
        return status_reply if args == ("status",) else hooks_reply

    monkeypatch.setattr(orca.terminal, "_orca", answer)
    assert tuple(orca.health().values()) == expected
    assert calls == [("status",)] + (
        [("agent", "hooks", "status")] if expected[0] == "running" else []
    )


def test_doctor_reports_missing_cli_without_starting_orca(tmp_path, monkeypatch):
    monkeypatch.setenv("PLOT_SESSION_ORCA", str(tmp_path / "missing"))
    monkeypatch.setattr(orca.terminal, "_orca", lambda *args: pytest.fail("Orca CLI called"))
    assert orca.health() == {"runtime": "missing", "hooks": "not checked"}


def test_missing_orca_cli_install_refusal_names_the_missing_app(home, monkeypatch):
    """Bug: first-time setup told the operator to close an app that was not installed."""
    monkeypatch.setattr(orca.terminal, "_orca", lambda *args: None)
    with pytest.raises(SlopmeisterError, match="install Orca"):
        install.install(home, {".claude/CLAUDE.md", orca.NAME})
    assert not (home / ".claude").exists()


def test_template_uses_manual_agent_defaults_and_safe_quick_commands():
    """Bug: Orca's direct launcher silently used bypass flags or a Codex home from its daemon."""
    settings = orca._wanted()
    assert settings["agentDefaultArgs"]
    assert set(settings["agentDefaultArgs"].values()) == {""}
    commands = settings["terminalQuickCommands"]
    assert len(commands) == 2
    for item in commands:
        assert item["action"] == "terminal-command" and item["appendEnter"] is True
        assert item["scope"] == {"type": "global"}
        assert item["command"].startswith("/bin/zsh -lc 'cd ")
        assert "task dispatch --" in item["command"]
    assert 'CODEX_HOME="$HOME/.codex"' in commands[1]["command"]
