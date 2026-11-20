"""The public workstation command sets Orca through a stand-in runtime and a scratch profile."""

import json

from slopmeister.workstation import orca
from tests.integration.workstation.test_install import ORCA_STORE, ROOT, machine, workstation
from tests.support.fakes import fake_binary
from tests.support.orca_runtime import TOKEN, Runtime, profile

COMMAND_ID = "slopmeister-phone-claude"
KEPT = {"id": "operator-command", "label": "Keep", "command": "echo keep"}


def live_settings() -> dict:
    """Orca's settings with one stale managed command, one unmanaged command and private values."""
    wanted = orca._wanted()
    stale = next(item for item in wanted["terminalQuickCommands"] if item["id"] == COMMAND_ID)
    stale = {**stale, "label": "Old label", "scope": {"type": "repo", "repoId": "old-repository"}}
    return {
        **wanted,
        "telemetry": {"optedIn": False, "installId": "private-value"},
        "terminalQuickCommands": [KEPT, stale],
        "unmanaged": {"badge": "blue"},
    }


def test_orca_install_sends_managed_commands_to_the_running_orca(tmp_path):
    """Bug: the install wrote Orca's files, lost an unmanaged command or printed private state."""
    home, bin_dir = machine(tmp_path)
    store = profile(home, live_settings())
    before = store.read_bytes()
    with Runtime(home, live_settings()) as runtime:
        result = workstation(home, bin_dir, "install", ORCA_STORE)
        assert result.returncode == 0, result.stderr
        commands = runtime.settings["terminalQuickCommands"]
        assert commands[0] == KEPT
        assert [item for item in commands if item["id"] == COMMAND_ID][0][
            "label"
        ] == "Claude dispatcher"
        assert {item["id"] for item in commands[1:]} == {
            item["id"] for item in orca._wanted()["terminalQuickCommands"]
        }
        updates = [m for m in runtime.methods() if m.startswith("settings.update")]
        assert updates == ["settings.updateTerminalQuickCommands"] * 3
        assert runtime.settings["unmanaged"] == {"badge": "blue"}
        for private in (TOKEN, "private-value"):
            assert private not in result.stdout + result.stderr
        assert store.read_bytes() == before
        saved = next((home / ".slopmeister-backup").glob(f"*/{ORCA_STORE}.settings.json"))
        assert json.loads(saved.read_text()) == live_settings()
        # Orca saves its database on its own schedule, a repeat asks the runtime and sends nothing.
        runtime.requests.clear()
        assert workstation(home, bin_dir, "install", ORCA_STORE).returncode == 0
        assert not [m for m in runtime.methods() if m.startswith("settings.update")]
        assert len(list((home / ".slopmeister-backup").glob(f"*/{ORCA_STORE}.settings.json"))) == 1


def test_orca_diff_never_prints_live_state(tmp_path):
    """Bug: home:diff exposed an unrelated private value in Orca's settings."""
    home, bin_dir = machine(tmp_path)
    profile(home, {**live_settings(), "private": "keep-this-secret"})
    output = workstation(home, bin_dir, "diff").stdout
    assert f"differs: {ORCA_STORE} managed Orca settings" in output
    assert "private-value" not in output and "keep-this-secret" not in output


def test_closed_orca_refuses_its_install_before_any_write(tmp_path):
    """Bug: a closed Orca let the install write other files and then fail or claim success."""
    home, bin_dir = machine(tmp_path)
    store = profile(home, live_settings())
    before = store.read_bytes()
    for selection in ("--all", ORCA_STORE):
        result = workstation(home, bin_dir, "install", selection)
        assert result.returncode != 0 and "open Orca and retry; nothing written" in result.stderr
        assert store.read_bytes() == before
        assert not (home / ".claude").exists() and not (home / ".slopmeister-backup").exists()


def test_named_global_install_works_while_orca_runs(tmp_path):
    """Bug: a global instruction refresh is blocked by unrelated live Orca state."""
    home, bin_dir = machine(tmp_path)
    original_orca = (home / ORCA_STORE).read_bytes()
    fake_binary(
        bin_dir,
        "orca",
        "printf '%s\n' "
        '\'{"ok":true,"result":{"app":{"running":true},"runtime":{"reachable":true}}}\'',
    )
    result = workstation(home, bin_dir, "install", ".claude/CLAUDE.md", ".codex/AGENTS.md")
    assert result.returncode == 0, result.stderr
    assert "Installed 2 file(s)" in result.stdout
    for name, source in (
        (".claude/CLAUDE.md", "dist/claude/CLAUDE.md"),
        (".codex/AGENTS.md", "dist/codex/AGENTS.md"),
    ):
        assert (home / name).read_bytes() == (ROOT / source).read_bytes()
    assert (home / ORCA_STORE).read_bytes() == original_orca


def test_doctor_reports_orca_hooks_off_from_the_two_cli_replies(tmp_path):
    """Bug: doctor trusted ok:true while Orca's status hooks were disabled."""
    home, bin_dir = machine(tmp_path)
    fake_binary(
        bin_dir,
        "orca",
        "case \"$1\" in status) printf '%s\\n' "
        '\'{"ok":true,"result":{"app":{"running":true},"runtime":{"reachable":true}}}\';; '
        "agent) printf '%s\\n' "
        '\'{"ok":true,"result":{"enabled":false,"statuses":[]}}\';; esac',
    )
    result = workstation(home, bin_dir, "doctor")
    assert result.returncode == 0
    found = {item["name"]: item for item in json.loads(result.stdout)}
    assert (found["orca:runtime"]["status"], found["orca:runtime"]["evidence"]) == ("ok", "running")
    assert (found["orca:hooks"]["status"], found["orca:hooks"]["evidence"]) == ("problem", "off")
