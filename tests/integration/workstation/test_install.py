"""The home install, its diff and the rule report under a scratch home. Nothing live is touched."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

from slopmeister.workstation import manifest, orca
from tests.support.fakes import fake_binary

ROOT = Path(__file__).resolve().parents[3]
CLAUDE_AGENT = "Library/LaunchAgents/local.claude-remote-control.plist"
VAULT_AGENT = "Library/LaunchAgents/local.vault-commit.plist"
APPLET = ".vault-git/VaultCommit.app"
ORCA_DATA = orca.NAME
BUILD = 'while [ $# -gt 0 ]; do [ "$1" = -o ] && { mkdir -p "$2"; exit 0; }; shift; done; exit 1'


def machine(tmp_path: Path) -> tuple[Path, Path]:
    home, bin_dir = tmp_path / "home", tmp_path / "bin"
    home.mkdir()
    fake_binary(bin_dir, "launchctl", f'echo "$*" >> {tmp_path}/launchctl.log')
    fake_binary(bin_dir, "osacompile", BUILD)
    for name in ("systemctl", "loginctl"):
        fake_binary(bin_dir, name, f'echo "{name} $*" >> {tmp_path}/service.log')
    fake_binary(
        bin_dir,
        "orca",
        "printf '%s\\n' "
        '\'{"ok":true,"result":{"app":{"running":false},"runtime":{"reachable":false}}}\'',
    )
    state = home / ORCA_DATA
    state.parent.mkdir(parents=True)
    state.write_text('{"settings":{},"otherState":{"private":"keep"}}\n')
    (bin_dir / "python3").symlink_to(sys.executable)
    return home, bin_dir


def workstation(
    home: Path, bin_dir: Path, *args: str, **extra_env: str
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "PLOT_SESSION_ORCA": str(bin_dir / "orca"),
        "SLOPMEISTER_PLATFORM": "darwin",
        **extra_env,
    }
    command = [str(ROOT / "bin/slopmeister"), "workstation", *args]
    return subprocess.run(command, capture_output=True, text=True, env=env, check=False)


def test_install_loads_the_vault_agent_and_sets_the_codex_window(tmp_path):
    """Escaping bug, the vault job never loads or Codex keeps its default context window."""
    home, bin_dir = machine(tmp_path)
    assert workstation(home, bin_dir, "install", "--all").returncode == 0
    calls = (tmp_path / "launchctl.log").read_text()
    assert f"bootstrap gui/{os.getuid()} {home / VAULT_AGENT}" in calls
    assert (
        tomllib.loads((home / ".codex/config.toml").read_text())["model_context_window"] == 872000
    )


def test_install_loads_the_claude_agent_with_a_substituted_home(tmp_path):
    """Escaping bug, the phone has no entry point because the agent never loaded or holds $HOME."""
    home, bin_dir = machine(tmp_path)
    assert workstation(home, bin_dir, "install", "--all").returncode == 0
    agent = (home / CLAUDE_AGENT).read_text()
    assert f"<string>{home}/.local/bin/claude</string><string>remote-control</string>" in agent
    assert f"<key>WorkingDirectory</key><string>{home}/dev/slop-meister</string>" in agent
    assert "<key>KeepAlive</key><true/>" in agent and "$HOME" not in agent
    assert agent.count("<string>/dev/null</string>") == 2
    assert "<key>ThrottleInterval</key><integer>60</integer>" in agent
    calls = (tmp_path / "launchctl.log").read_text()
    assert f"bootstrap gui/{os.getuid()} {home / CLAUDE_AGENT}" in calls


def test_a_failed_launchd_load_is_named_and_fails_the_install(tmp_path):
    """Escaping bug, bootout stopped the job, bootstrap failed, and install reported success."""
    home, bin_dir = machine(tmp_path)
    fake_binary(bin_dir, "launchctl", 'case "$1" in bootstrap) exit 1;; *) exit 0;; esac')
    result = workstation(home, bin_dir, "install", "--all")
    assert result.returncode != 0
    assert "NOT running, load it with: launchctl bootstrap" in result.stdout
    assert "launchd job(s) not running: local.vault-commit, local.claude-remote-control" in (
        result.stderr
    )


def test_diff_after_install_reports_zero_and_writes_nothing(tmp_path):
    home, bin_dir = machine(tmp_path)
    workstation(home, bin_dir, "install", "--all")
    before = sorted((p, p.stat().st_mtime_ns) for p in home.rglob("*"))
    result = workstation(home, bin_dir, "diff")
    assert "0 file(s) differ. Nothing written." in result.stdout
    assert sorted((p, p.stat().st_mtime_ns) for p in home.rglob("*")) == before


def test_install_backs_up_a_replaced_file(tmp_path):
    home, bin_dir = machine(tmp_path)
    (home / ".claude").mkdir()
    (home / ".claude/CLAUDE.md").write_text("old\n")
    result = workstation(home, bin_dir, "install", ".claude/CLAUDE.md")
    backups = list((home / ".slopmeister-backup").glob("*/.claude/CLAUDE.md"))
    assert result.returncode == 0 and [b.read_text() for b in backups] == ["old\n"]
    assert (home / ".claude/CLAUDE.md").read_bytes() == (
        ROOT / "dist/claude/CLAUDE.md"
    ).read_bytes()
    live = home / ".codex/config.toml"
    live.parent.mkdir(exist_ok=True)
    original = 'model_context_window = 272000\nforeign = "keep-this-secret"\n'
    live.write_text(original)
    live.chmod(0o600)
    result = workstation(home, bin_dir, "install", ".codex/config.toml")
    backups = list((home / ".slopmeister-backup").glob("*/.codex/config.toml"))
    assert result.returncode == 0 and [b.read_text() for b in backups] == [original]
    assert all((backup.stat().st_mode & 0o777) == 0o600 for backup in backups)
    assert tomllib.loads(live.read_text()) == {
        "model_context_window": 872000,
        "foreign": "keep-this-secret",
    }
    assert live.read_text() == 'model_context_window = 872000\nforeign = "keep-this-secret"\n'


def test_only_named_entries_are_written(tmp_path):
    """Escaping bug, a named install writes everything, or a declined applet is built anyway."""
    home, bin_dir = machine(tmp_path)
    workstation(home, bin_dir, "install", ".codex/AGENTS.md")
    assert not (home / APPLET).exists() and not (home / ".claude").exists()
    assert not (home / ".codex/config.toml").exists()
    result = workstation(home, bin_dir, "install", APPLET)
    assert (home / APPLET).is_dir() and f"built: {APPLET}" in result.stdout


def test_install_without_names_writes_nothing(tmp_path):
    home, bin_dir = machine(tmp_path)
    original_orca = (home / ORCA_DATA).read_bytes()
    result = workstation(home, bin_dir, "install")
    assert result.returncode == 2 and "missing: .claude/CLAUDE.md" in result.stdout
    assert not (home / ".claude").exists() and not (home / ".slopmeister-backup").exists()
    assert (home / ORCA_DATA).read_bytes() == original_orca


def test_unknown_entry_is_refused(tmp_path):
    home, bin_dir = machine(tmp_path)
    result = workstation(home, bin_dir, "install", ".ssh/config")
    assert result.returncode == 2 and "unknown entries .ssh/config" in result.stderr


def test_exclude_waits_for_the_vault_repository(tmp_path):
    home, bin_dir = machine(tmp_path)
    result = workstation(home, bin_dir, "install", "--all")
    assert "no vault repository yet" in result.stdout
    assert not (home / ".vault-git/obsidian.git").exists()


RULES = {
    "permissions": {
        "allow": ["Bash(task plot-session *)", "Bash(op read *)"],
        "deny": ["Bash(unrelated-field-host-probe *)"],
    }
}


def _assert_rule_status(output: str, home: Path) -> None:
    assert "  present: claude allow Bash(task plot-session *)" in output
    assert "  present: claude allow Bash($HOME/" in output
    assert "  decision differs: claude deny Bash(op read *)" in output
    assert "  absent: claude deny Bash(op inject *)" in output
    assert "  present: codex allow task plot-session" in output
    assert "  decision differs: codex forbidden op read" in output
    assert "unrelated-field-host-probe" not in output and "unrelated-secret-value" not in output
    assert str(home) not in output.split("=== allow rules")[1]


def test_rule_report_names_status_and_never_echoes_live_content(tmp_path):
    """Escaping bug, the report prints the live file's field approvals into agent output."""
    home, bin_dir = machine(tmp_path)
    (home / ".claude").mkdir()
    launcher = f"{home}/dev/slop-meister/bin/slopmeister"
    review = f"Bash({launcher} review review *)"
    rules = {
        "permissions": {**RULES["permissions"], "allow": [*RULES["permissions"]["allow"], review]}
    }
    (home / ".claude/settings.json").write_text(json.dumps(rules))
    (home / ".codex/rules").mkdir(parents=True)
    live = (
        'prefix_rule(pattern=["task", "plot-session"], decision="allow")\n'
        'prefix_rule(pattern=["op", "read"], decision="allow")\n'
        'prefix_rule(pattern=["unrelated-field-host-probe"], decision="allow")\n'
    )
    (home / ".codex/rules/default.rules").write_text(live)
    (home / ".codex/config.toml").write_text(
        'model_context_window = 272000\napi_token = "unrelated-secret-value"\n'
    )
    output = workstation(home, bin_dir, "diff").stdout
    assert "differs: .codex/config.toml model_context_window" in output
    _assert_rule_status(output, home)


def test_unreadable_rule_file_names_the_file_and_nothing_in_it(tmp_path):
    home, bin_dir = machine(tmp_path)
    (home / ".codex/rules").mkdir(parents=True)
    (home / ".codex/rules/default.rules").write_text('prefix_rule(pattern=["unrelated-probe" \n')
    output = workstation(home, bin_dir, "diff").stdout
    assert "  unreadable: ~/.codex/rules/default.rules, compared nothing" in output
    assert "unrelated-probe" not in output


def test_diff_shows_a_changed_file_as_a_unified_diff(tmp_path, monkeypatch):
    """Escaping bug, diff names a drifted file but hides what install would change in it."""
    monkeypatch.setenv("SLOPMEISTER_PLATFORM", "darwin")
    home, bin_dir = machine(tmp_path)
    (home / ".codex").mkdir()
    (home / ".codex/AGENTS.md").write_text("stale line\n")
    output = workstation(home, bin_dir, "diff").stdout
    assert "--- .codex/AGENTS.md ---" in output and "-stale line" in output
    assert "+++ dist/codex/AGENTS.md" in output
    assert "--- ~/.codex/AGENTS.md" in output
    assert f"{len(manifest.names()) - 1} file(s) differ. Nothing written." in output


def test_oddly_typed_rule_file_is_unreadable_not_a_traceback(tmp_path):
    """Escaping bug, a numeric allow bucket crashes diff and prints local paths in a traceback."""
    home, bin_dir = machine(tmp_path)
    (home / ".claude").mkdir()
    (home / ".claude/settings.json").write_text('{"permissions": {"allow": 5}}\n')
    (home / ".codex").mkdir()
    (home / ".codex/config.toml").write_text('private_value = "do-not-print"\n[broken\n')
    result = workstation(home, bin_dir, "diff")
    assert result.returncode == 0 and "Traceback" not in result.stderr
    assert "  unreadable: ~/.claude/settings.json, compared nothing" in result.stdout
    assert "unreadable: .codex/config.toml, compared nothing" in result.stdout
    assert "do-not-print" not in result.stdout + result.stderr
    unusual = '"model_context_window" = 272000\nprivate_value = "do-not-print"\n'
    (home / ".codex/config.toml").write_text(unusual)
    result = workstation(home, bin_dir, "install", ".codex/config.toml")
    assert result.returncode != 0 and "unsupported model_context_window spelling" in result.stderr
    assert (home / ".codex/config.toml").read_text() == unusual
    assert "do-not-print" not in result.stdout + result.stderr
