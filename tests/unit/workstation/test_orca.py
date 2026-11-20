"""Orca's managed settings go through its runtime, and status reads only what Orca uses."""

import json
import stat

import pytest

from slopmeister.errors import SlopmeisterError
from slopmeister.workstation import install, orca
from tests.support.orca_runtime import RUNTIME_ID, TOKEN, Runtime, profile

STALE = {"id": "slopmeister-fixture", "label": "Old", "scope": {"type": "global"}}
FIXTURE = {**STALE, "label": "Fixture", "action": "terminal-command", "command": "true"}
FIXTURE["appendEnter"] = True
KEPT = {"id": "operator-command", "label": "Keep", "command": "echo keep"}
# A scratch template, so an edit of the committed one fails no unit test.
TEMPLATE = {
    "telemetry": {"optedIn": False},
    "agentStatusHooksEnabled": True,
    "agentDefaultArgs": {"claude": ""},
    "terminalQuickCommands": [FIXTURE],
}
PRIOR = {
    "telemetry": {"optedIn": False, "installId": "private-identifier"},
    "agentStatusHooksEnabled": False,
    "agentDefaultArgs": {"claude": "--old", "other": "--keep"},
    "terminalQuickCommands": [KEPT, STALE],
}


@pytest.fixture(autouse=True)
def mac(monkeypatch):
    """Orca's managed settings are a Mac-only install entry."""
    monkeypatch.setenv("SLOPMEISTER_PLATFORM", "darwin")


@pytest.fixture
def home(tmp_path, monkeypatch):
    root = tmp_path / "home"
    profile(root, PRIOR)
    monkeypatch.setattr(orca, "_wanted", lambda *args: TEMPLATE)
    return root


@pytest.fixture
def runtime(home):
    with Runtime(home, json.loads(json.dumps(PRIOR))) as fake:
        yield fake


def test_install_sends_only_differing_settings_after_a_private_backup(home, runtime, tmp_path):
    """Bug: the install rewrote Orca's files, dropped unmanaged values or wrote before a backup."""
    backups = tmp_path / "backups"
    saved = backups / f"{orca.NAME}.settings.json"
    seen = []

    def first_write(request):
        seen.append(json.loads(saved.read_text()))
        seen.append(stat.S_IMODE(saved.stat().st_mode))
        return runtime._frames(request)

    runtime.replies["settings.updateTerminalQuickCommands"] = first_write
    store = (home / orca.NAME).read_bytes()
    assert orca.status(home) == "differs"
    orca.install(home, backups)
    assert seen == [PRIOR, 0o600] and stat.S_IMODE(backups.stat().st_mode) == 0o700
    assert runtime.methods() == [
        "settings.get",
        "settings.getTerminalQuickCommands",
        "settings.updateTerminalQuickCommands",
        "settings.update",
        "settings.get",
        "settings.getTerminalQuickCommands",
    ]
    assert runtime.requests[2]["params"] == {"mutation": {"type": "upsert", "command": FIXTURE}}
    assert runtime.requests[3]["params"] == {
        "agentStatusHooksEnabled": True,
        "agentDefaultArgs": {"claude": "", "other": "--keep"},
    }
    assert runtime.settings["terminalQuickCommands"] == [KEPT, FIXTURE]
    assert (home / orca.NAME).read_bytes() == store


def test_install_with_matching_runtime_sends_no_mutation(home, runtime, tmp_path):
    runtime.settings.update(TEMPLATE)
    orca.install(home, tmp_path / "backups")
    assert runtime.methods() == ["settings.get", "settings.getTerminalQuickCommands"]
    assert not (tmp_path / "backups").exists()


def test_backup_keeps_what_the_runtime_serves(home, runtime, tmp_path):
    """Bug: the backup took Orca's store copy, which can lag the values the install replaces."""
    runtime.settings["agentDefaultArgs"] = {"claude": "--live", "newer": "--live"}
    orca.install(home, tmp_path / "backups")
    saved = json.loads((tmp_path / "backups" / f"{orca.NAME}.settings.json").read_text())
    assert saved["agentDefaultArgs"] == {"claude": "--live", "newer": "--live"}
    assert saved["telemetry"] == PRIOR["telemetry"]


def test_failed_backup_sends_no_mutation(home, runtime, tmp_path):
    """Bug: a write reached Orca although the prior settings were not saved."""
    backups = tmp_path / "backups"
    backups.write_text("not a folder")
    with pytest.raises(OSError):
        orca.install(home, backups)
    assert runtime.methods() == ["settings.get", "settings.getTerminalQuickCommands"]


def unsafe_mode(runtime):
    runtime.metadata.chmod(0o644)


def open_folder(runtime):
    runtime.endpoint.parent.chmod(0o750)


def linked_file(runtime):
    target = runtime.root / "elsewhere.json"
    runtime.metadata.rename(target)
    runtime.metadata.symlink_to(target)


def closed_orca(runtime):
    runtime.metadata.unlink()


def no_unix_transport(runtime):
    runtime.write_metadata(transports=[{"kind": "websocket", "endpoint": "ws://127.0.0.1:1"}])


def foreign_socket(runtime):
    runtime.write_metadata(transports=[{"kind": "unix", "endpoint": str(runtime.metadata)}])


@pytest.mark.parametrize(
    "spoil",
    [unsafe_mode, open_folder, linked_file, closed_orca, no_unix_transport, foreign_socket],
)
def test_unsafe_or_absent_runtime_refuses_before_any_write(home, runtime, spoil):
    """Bug: the token went to a socket another user controls, or a closed Orca read as success."""
    spoil(runtime)
    with pytest.raises(SlopmeisterError, match="open Orca and retry; nothing written") as raised:
        install.install(home, {orca.NAME, ".claude/CLAUDE.md"})
    assert TOKEN not in str(raised.value)
    assert runtime.requests == []
    assert not (home / ".claude").exists() and not (home / ".slopmeister-backup").exists()


def frames(*replies):
    return lambda request: [
        json.dumps(reply(request)).encode() + b"\n" if callable(reply) else reply
        for reply in replies
    ]


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (frames(), "no valid reply"),
        (frames(b'{"id": "partial"'), "no valid reply"),
        (frames(b"[]\n"), "another request"),
        (frames(lambda r: {"id": "other", "ok": True, "result": {}}), "another request"),
        (
            frames(
                lambda r: {"id": r["id"], "ok": True, "result": {}, "_meta": {"runtimeId": "x"}}
            ),
            "another runtime",
        ),
        (
            frames(
                lambda r: {
                    "id": r["id"],
                    "ok": False,
                    "error": {"code": "forbidden", "message": f"{r['authToken']}\x1b[2J"},
                }
            ),
            "Orca refused settings.get: forbidden",
        ),
        (
            frames(
                lambda r: {
                    "id": r["id"],
                    "ok": False,
                    "error": {"code": "forbidden", "message": "x" * 190 + r["authToken"]},
                }
            ),
            "Orca refused settings.get: forbidden x+\\[token\\]$",
        ),
        (
            frames(
                lambda r: {
                    "id": r["id"],
                    "ok": True,
                    "result": [],
                    "_meta": {"runtimeId": RUNTIME_ID},
                }
            ),
            "unknown shape",
        ),
    ],
)
def test_invalid_runtime_reply_stops_before_any_mutation(home, runtime, tmp_path, reply, message):
    """Bug: a reply from another runtime or of another shape was taken as Orca's settings."""
    runtime.replies["settings.get"] = reply
    with pytest.raises(SlopmeisterError, match=message) as raised:
        orca.install(home, tmp_path / "backups")
    assert "\x1b" not in str(raised.value) and TOKEN[:5] not in str(raised.value)
    assert runtime.methods() == ["settings.get"]
    assert not (tmp_path / "backups").exists()


def test_setting_orca_does_not_keep_fails_the_install(home, runtime, tmp_path):
    """Bug: the install claimed success although Orca ignored or rewrote a managed value."""
    runtime.settings.update(
        {key: TEMPLATE[key] for key in ("agentStatusHooksEnabled", "agentDefaultArgs")}
    )
    runtime.replies["settings.updateTerminalQuickCommands"] = frames(
        lambda r: {"id": r["id"], "ok": True, "result": {}, "_meta": {"runtimeId": RUNTIME_ID}}
    )
    with pytest.raises(
        SlopmeisterError, match="did not keep these managed settings: terminalQuickCommands"
    ) as raised:
        orca.install(home, tmp_path / "backups")
    assert str(tmp_path / "backups") in str(raised.value)


def test_key_without_a_route_refuses_and_names_it(home, runtime):
    """Bug: the install reported success while Orca kept a value no outside route can set."""
    profile(home, {**PRIOR, "telemetry": {"optedIn": True}})
    with pytest.raises(SlopmeisterError, match="no outside change of telemetry") as raised:
        install.install(home, {orca.NAME, ".claude/CLAUDE.md"})
    assert "nothing written" in str(raised.value)
    assert runtime.requests == [] and not (home / ".claude").exists()


def test_status_compares_only_managed_values_in_orcas_store(home):
    """Bug: home:diff compared a file Orca no longer uses, or an unmanaged value."""
    assert orca.status(home) == "differs"
    current = {**PRIOR, **TEMPLATE, "terminalQuickCommands": [KEPT, FIXTURE], "unmanaged": 1}
    profile(home, current)
    assert orca.status(home) == "unchanged"
    profile(home, {**current, "telemetry": {"optedIn": False, "installId": "changed"}})
    assert orca.status(home) == "unchanged"
    profile(home, {**current, "terminalQuickCommands": [KEPT, FIXTURE, FIXTURE]})
    assert orca.status(home) == "differs"
    profile(home, None)
    assert orca.status(home) == "differs"
    (home / orca.NAME).unlink()
    assert orca.status(home) == "missing"


def test_missing_profile_refuses_before_other_install(home):
    """Bug: a new Orca profile caused a partial all-home installation."""
    (home / orca.NAME).unlink()
    with pytest.raises(SlopmeisterError, match="missing or unreadable"):
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


def test_template_uses_manual_agent_defaults_and_safe_quick_commands():
    """Bug: Orca's direct launcher silently used bypass flags or a Codex home from its daemon."""
    settings = orca._wanted()
    assert settings["agentDefaultArgs"]
    assert set(settings["agentDefaultArgs"].values()) == {""}
    commands = settings["terminalQuickCommands"]
    assert len(commands) == 3
    for item in commands:
        assert item["action"] == "terminal-command" and item["appendEnter"] is True
        assert item["scope"] == {"type": "global"}
    for item in commands[:2]:
        assert item["command"].startswith("/bin/zsh -lc 'cd ")
        assert "task dispatch --" in item["command"]
    # Typed into the terminal itself, where Orca's `claude` function applies the selected account.
    assert commands[2]["command"] == "claude auth login --claudeai"
    assert 'CODEX_HOME="$HOME/.codex"' in commands[1]["command"]
