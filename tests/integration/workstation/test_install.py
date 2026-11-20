"""The home install and its diff under a scratch home. Nothing live is touched."""

import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tomllib

import pytest

from slopmeister.workstation import codex_hooks, manifest, orca
from tests.support.fakes import fake_binary
from tests.support.orca_runtime import profile

ROOT = Path(__file__).resolve().parents[3]
CLAUDE_AGENT = "Library/LaunchAgents/local.claude-remote-control.plist"
VAULT_AGENT = "Library/LaunchAgents/local.vault-commit.plist"
APPLET = ".vault-git/VaultCommit.app"
ORCA_STORE = orca.NAME
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
    # Orca already holds the managed settings, so an install sends nothing to its runtime.
    profile(home, orca._wanted())
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


def trusted(home):
    """The trust tables the Codex config install writes for every owned hook."""
    return {key: {"trusted_hash": digest} for key, digest in codex_hooks.trust(home)}


def test_install_loads_the_vault_agent_and_sets_the_codex_window(tmp_path):
    """Escaping bug, the vault job never loads or Codex keeps its default window and compaction."""
    home, bin_dir = machine(tmp_path)
    assert workstation(home, bin_dir, "install", "--all").returncode == 0
    calls = (tmp_path / "launchctl.log").read_text()
    assert f"bootstrap gui/{os.getuid()} {home / VAULT_AGENT}" in calls
    assert tomllib.loads((home / ".codex/config.toml").read_text()) == {
        "model_auto_compact_token_limit": 300000,
        "model_post_turn_compact_threshold_percent": 30,
        "model_context_window": 872000,
        "features": {"memories": False},
        "hooks": {"state": trusted(home)},
    }


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


@pytest.mark.parametrize(
    ("label", "weekday", "kickoff"),
    [("local.glean", 0, "glean-kickoff.md"), ("local.weekly", 1, "update-kickoff.md")],
)
def test_install_loads_a_weekly_agent_with_its_kickoff(tmp_path, label, weekday, kickoff):
    """Escaping bug, a weekly job fails on $HOME, a lost kickoff or a missing log folder."""
    home, bin_dir = machine(tmp_path)
    assert workstation(home, bin_dir, "install", "--all").returncode == 0
    agent_path = home / f"Library/LaunchAgents/{label}.plist"
    agent = agent_path.read_text()
    job = plistlib.loads(agent.encode())
    assert "$HOME" not in agent and job["StartCalendarInterval"]["Weekday"] == weekday
    assert job["ProgramArguments"] == [str(home / ".local/bin/slopmeister-weekly"), label[6:]]
    assert (ROOT / "plots/home/launchd" / kickoff).is_file()
    assert {Path(job[key]).parent for key in ("StandardOutPath", "StandardErrorPath")} == {
        home / "Library/Logs"
    }
    calls = (tmp_path / "launchctl.log").read_text()
    assert f"bootstrap gui/{os.getuid()} {agent_path}" in calls


def test_a_failed_launchd_load_is_named_and_fails_the_install(tmp_path):
    """Escaping bug, bootout stopped the job, bootstrap failed, and install reported success."""
    home, bin_dir = machine(tmp_path)
    fake_binary(bin_dir, "launchctl", 'case "$1" in bootstrap) exit 1;; *) exit 0;; esac')
    result = workstation(home, bin_dir, "install", "--all")
    assert result.returncode != 0
    assert "NOT running, load it with: launchctl bootstrap" in result.stdout
    names = "local.vault-commit, local.claude-remote-control, local.glean, local.weekly"
    assert f"launchd job(s) not running: {names}" in result.stderr


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
    prior = (home / ".claude/CLAUDE.md").stat().st_ino
    (home / ".claude/CLAUDE.md").chmod(0o640)
    result = workstation(home, bin_dir, "install", ".claude/CLAUDE.md")
    installed = (home / ".claude/CLAUDE.md").stat()
    assert installed.st_ino != prior and installed.st_mode & 0o777 == 0o640
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
        "model_auto_compact_token_limit": 300000,
        "model_post_turn_compact_threshold_percent": 30,
        "model_context_window": 872000,
        "foreign": "keep-this-secret",
        "features": {"memories": False},
        "hooks": {"state": trusted(home)},
    }
    tables = "".join(
        f'\n[hooks.state."{key}"]\ntrusted_hash = "{digest}"\n'
        for key, digest in codex_hooks.trust(home)
    )
    assert live.read_text() == (
        "model_post_turn_compact_threshold_percent = 30\n"
        "model_auto_compact_token_limit = 300000\n"
        'model_context_window = 872000\nforeign = "keep-this-secret"\n\n'
        "[features]\nmemories = false\n" + tables
    )


def test_only_named_entries_are_written(tmp_path):
    """Escaping bug, a named install writes everything, or a declined applet is built anyway."""
    home, bin_dir = machine(tmp_path)
    workstation(home, bin_dir, "install", ".codex/AGENTS.md")
    assert not (home / APPLET).exists() and not (home / ".claude").exists()
    assert not (home / ".codex/config.toml").exists()
    result = workstation(home, bin_dir, "install", APPLET)
    assert (home / APPLET).is_dir() and f"built: {APPLET}" in result.stdout


@pytest.mark.parametrize(
    "text",
    [
        'model = "keep"\n',
        "[features]\nother = true\n",
        "[features] # keep\nmemories = true\nother = true\n"
        '[projects."/example"]\ntrust_level = "trusted"\n',
        "[features]\nmemories = false\nother = true\n",
        '[features.other]\nvalue = "keep"\n',
    ],
)
def test_codex_install_disables_memory_and_preserves_other_toml(tmp_path, text):
    home, bin_dir = machine(tmp_path)
    path = home / ".codex/config.toml"
    path.parent.mkdir()
    path.write_text(text)
    expected = tomllib.loads(text)
    expected["model_context_window"] = 872000
    expected["model_auto_compact_token_limit"] = 300000
    expected["model_post_turn_compact_threshold_percent"] = 30
    expected.setdefault("features", {})["memories"] = False
    expected["hooks"] = {"state": trusted(home)}
    installed = workstation(home, bin_dir, "install", ".codex/config.toml")
    assert installed.returncode == 0, installed.stderr
    assert tomllib.loads(path.read_text()) == expected
    before = path.stat().st_mtime_ns
    repeat = workstation(home, bin_dir, "install", ".codex/config.toml")
    assert repeat.returncode == 0 and "Everything already up to date" in repeat.stdout
    assert path.stat().st_mtime_ns == before


@pytest.mark.parametrize(
    "text",
    [
        "features = {memories = true}\n",
        "features.memories = true\n",
        '[features]\n"memories" = true\n',
    ],
)
def test_unsupported_codex_spelling_preserves_the_original(tmp_path, text):
    home, bin_dir = machine(tmp_path)
    path = home / ".codex/config.toml"
    path.parent.mkdir()
    path.write_text(text)
    result = workstation(home, bin_dir, "install", ".codex/config.toml")
    assert result.returncode == 1 and "unsupported" in result.stderr
    assert "nothing written" in result.stderr and path.read_text() == text
    assert not (home / ".slopmeister-backup").exists()


def test_install_without_names_writes_nothing(tmp_path):
    home, bin_dir = machine(tmp_path)
    original_orca = (home / ORCA_STORE).read_bytes()
    result = workstation(home, bin_dir, "install")
    assert result.returncode == 2 and "missing: .claude/CLAUDE.md" in result.stdout
    assert not (home / ".claude").exists() and not (home / ".slopmeister-backup").exists()
    assert (home / ORCA_STORE).read_bytes() == original_orca


def test_unknown_entry_is_refused(tmp_path):
    home, bin_dir = machine(tmp_path)
    result = workstation(home, bin_dir, "install", ".ssh/config")
    assert result.returncode == 2 and "unknown entries .ssh/config" in result.stderr


def test_exclude_waits_for_the_vault_repository(tmp_path):
    home, bin_dir = machine(tmp_path)
    result = workstation(home, bin_dir, "install", "--all")
    assert "no vault repository yet" in result.stdout
    assert not (home / ".vault-git/obsidian.git").exists()


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
    # The scratch Orca profile already holds the managed settings.
    assert "unchanged: " + ORCA_STORE in output
    assert f"{len(manifest.names()) - 2} file(s) differ. Nothing written." in output


def test_malformed_configuration_is_reported_without_live_content(tmp_path):
    home, bin_dir = machine(tmp_path)
    (home / ".claude").mkdir()
    (home / ".claude/settings.json").write_text('{"permissions": 5}\n')
    (home / ".codex").mkdir()
    (home / ".codex/config.toml").write_text('private_value = "do-not-print"\n[broken\n')
    result = workstation(home, bin_dir, "diff")
    assert result.returncode == 0 and "Traceback" not in result.stderr
    assert "differs: .claude/settings.json central restrictions" in result.stdout
    assert "unreadable: .codex/config.toml, compared nothing" in result.stdout
    assert "do-not-print" not in result.stdout + result.stderr
    unusual = '"model_context_window" = 272000\nprivate_value = "do-not-print"\n'
    (home / ".codex/config.toml").write_text(unusual)
    result = workstation(home, bin_dir, "install", ".codex/config.toml")
    assert result.returncode != 0 and "unsupported model_context_window spelling" in result.stderr
    assert (home / ".codex/config.toml").read_text() == unusual
    assert "do-not-print" not in result.stdout + result.stderr


@pytest.mark.parametrize("matching", [True, False])
def test_link_refusal_preserves_all_preceding_files(tmp_path, matching):
    home, bin_dir = machine(tmp_path)
    target = tmp_path / "other-file"
    if matching:
        target.write_bytes((ROOT / "dist/codex/AGENTS.md").read_bytes())
    live = home / ".codex/AGENTS.md"
    live.parent.mkdir(exist_ok=True)
    live.symlink_to(target)
    result = workstation(home, bin_dir, "install", ".claude/CLAUDE.md", ".codex/AGENTS.md")
    assert result.returncode == 1 and "symlink" in result.stderr
    assert not (home / ".claude/CLAUDE.md").exists()
    assert live.is_symlink() and target.exists() == matching
