"""The public workstation command manages Orca only through a scratch profile."""

import json

from tests.integration.workstation.test_install import ORCA_DATA, ROOT, machine, workstation
from tests.support.fakes import fake_binary


def test_orca_install_merges_managed_keys_without_losing_live_state(tmp_path):
    """Bug: a template replacement deletes unrelated settings and Quick Commands."""
    home, bin_dir = machine(tmp_path)
    path = home / ORCA_DATA
    original = {
        "settings": {
            "telemetry": {"optedIn": True, "installId": "private-value"},
            "terminalQuickCommands": [
                {"id": "operator-command", "label": "Keep", "command": "echo keep"}
            ],
            "unmanaged": {"badge": "blue"},
        },
        "liveAppState": {"private": "keep-this-secret"},
    }
    path.write_text(json.dumps(original))
    result = workstation(home, bin_dir, "install", ORCA_DATA)
    assert result.returncode == 0, result.stderr
    updated = json.loads(path.read_text())
    assert updated["liveAppState"] == original["liveAppState"]
    assert updated["settings"]["unmanaged"] == original["settings"]["unmanaged"]
    assert updated["settings"]["telemetry"] == {"optedIn": False, "installId": "private-value"}
    assert (
        updated["settings"]["terminalQuickCommands"][0]
        == original["settings"]["terminalQuickCommands"][0]
    )
    assert len(updated["settings"]["terminalQuickCommands"]) == 3
    assert "private-value" not in result.stdout + result.stderr


def test_orca_diff_never_prints_live_state(tmp_path):
    """Bug: home:diff exposed an unrelated private value in Orca's app state."""
    home, bin_dir = machine(tmp_path)
    path = home / ORCA_DATA
    path.write_text(
        '{"settings":{"telemetry":{"optedIn":true,"installId":"private-value"}},"liveAppState":{"private":"keep-this-secret"}}'
    )
    output = workstation(home, bin_dir, "diff").stdout
    assert "managed Orca settings" in output
    assert "private-value" not in output and "keep-this-secret" not in output


def test_running_or_unanswered_orca_refuses_its_install_before_any_write(tmp_path):
    """Bug: live or unknown Orca status allowed an Orca update or partial home writes."""
    home, bin_dir = machine(tmp_path)
    original = (home / ORCA_DATA).read_bytes()
    for reply in (
        '{"ok":true,"result":{"app":{"running":true},"runtime":{"reachable":true}}}',
        '{"ok":false}',
    ):
        fake_binary(bin_dir, "orca", f"printf '%s\\n' '{reply}'")
        for selection in ("--all", ORCA_DATA):
            result = workstation(home, bin_dir, "install", selection)
            assert result.returncode != 0 and "nothing written" in result.stderr
            assert (home / ORCA_DATA).read_bytes() == original
            assert not (home / ".claude").exists()


def test_named_global_install_works_while_orca_runs(tmp_path):
    """Bug: a global instruction refresh is blocked by unrelated live Orca state."""
    home, bin_dir = machine(tmp_path)
    original_orca = (home / ORCA_DATA).read_bytes()
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
    assert (home / ORCA_DATA).read_bytes() == original_orca


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
