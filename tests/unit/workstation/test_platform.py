"""The values that differ between macOS and Linux. Each test names the bug it prevents."""

import importlib
import sys

import pytest

from slopmeister import paths
from slopmeister.dispatch import command
from slopmeister.errors import SlopmeisterError
from slopmeister.launch import terminal
from slopmeister.session.service_actions import constants
from slopmeister.workstation import manifest, orca
from tests.support.fakes import fake_binary, path_with

VARIABLE = paths.PLATFORM_VARIABLE
UNIT = ".config/systemd/user/claude-remote-control.service"


def test_platform_is_the_machine_unless_a_test_names_one(monkeypatch):
    """Bug: an unknown system silently takes the Mac branch and calls launchctl on Linux."""
    monkeypatch.delenv(VARIABLE, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    assert paths.platform() == "linux"
    monkeypatch.setenv(VARIABLE, "darwin")
    assert paths.platform() == "darwin"
    for unknown in ("win32", "Linux"):
        monkeypatch.setenv(VARIABLE, unknown)
        with pytest.raises(SlopmeisterError, match="unsupported system"):
            paths.platform()
    monkeypatch.delenv(VARIABLE)
    monkeypatch.setattr(sys, "platform", "freebsd15")
    with pytest.raises(SlopmeisterError, match="unsupported system freebsd15"):
        paths.platform()


def test_orca_command_per_system(monkeypatch):
    """Bug: the launcher runs the GNOME screen reader, which owns /usr/bin/orca on Ubuntu."""
    monkeypatch.delenv("PLOT_SESSION_ORCA", raising=False)
    monkeypatch.setenv(VARIABLE, "linux")
    assert terminal.binary() == "/usr/bin/orca-ide"
    monkeypatch.setenv(VARIABLE, "darwin")
    assert terminal.binary() == "/Applications/Orca.app/Contents/Resources/bin/orca"
    monkeypatch.setenv("PLOT_SESSION_ORCA", "/scratch/orca")
    assert terminal.binary() == "/scratch/orca"


def test_linux_installs_one_systemd_unit_and_nothing_from_launchd(monkeypatch):
    """Bug: Linux is told to install launchd files, an applet or an Orca file it cannot have."""
    monkeypatch.setenv(VARIABLE, "linux")
    names = manifest.names()
    assert UNIT in names and orca.NAME not in names
    assert not [name for name in names if "LaunchAgents" in name or name.endswith(".app")]
    monkeypatch.setenv(VARIABLE, "darwin")
    names = manifest.names()
    assert UNIT not in names and manifest.APPLET in names and orca.NAME in names
    assert len([name for name in names if "LaunchAgents" in name]) == 2


def test_sleep_guard_wraps_both_tools_per_system(tmp_path, monkeypatch):
    """Bug: the dispatcher starts unguarded on Linux, or asks Linux for caffeinate."""
    fake_binary(tmp_path / ".local/bin", "codex", "exit 0")
    fake_binary(tmp_path / "bin", "claude", "exit 0")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", path_with(tmp_path / "bin"))
    monkeypatch.setenv(VARIABLE, "linux")
    guard = list(command.sleep_guard())
    assert guard[:2] == ["/usr/bin/systemd-inhibit", "--what=idle"] and "--mode=block" in guard
    claude = command.prefix(command.Settings("claude", "", ""), tmp_path)
    assert claude[:2] == ["/usr/bin/env", "SLOPMEISTER_SECRET_BROKER=1"]
    assert claude[2 : 2 + len(guard)] == guard
    assert claude[2 + len(guard)].endswith("/bin/claude")
    codex = command.prefix(command.Settings("codex", "", ""), tmp_path)
    assert codex[2] == "SLOPMEISTER_SECRET_BROKER=1"
    assert codex[3 : 3 + len(guard)] == guard
    assert codex[3 + len(guard)] == str(tmp_path / ".local/bin/codex")
    monkeypatch.setenv(VARIABLE, "darwin")
    claude = command.prefix(command.Settings("claude", "", ""), tmp_path)
    assert claude[2:4] == ["/usr/bin/caffeinate", "-i"] and claude[4].endswith("/bin/claude")


@pytest.fixture
def load(monkeypatch):
    def loaded(platform: str):
        monkeypatch.setattr(sys, "platform", platform)
        return importlib.reload(constants)

    yield loaded
    monkeypatch.undo()
    importlib.reload(constants)


def test_service_action_programs_per_system(load):
    """Bug: Linux looks for Homebrew's python3 and op, so every action reports them missing."""
    linux = load("linux")
    assert (str(linux.PYTHON), str(linux.OP)) == ("/usr/bin/python3", "/usr/bin/op")
    assert linux.BASE_PATH == "/usr/bin:/bin"
    mac = load("darwin")
    assert (str(mac.PYTHON), str(mac.OP)) == ("/opt/homebrew/bin/python3", "/opt/homebrew/bin/op")
    assert mac.BASE_PATH == "/opt/homebrew/bin:/usr/bin:/bin"


def test_no_skill_names_one_machines_home():
    """Bug: a Linux worker is told to launch the tester below a macOS home that does not exist."""
    named = [
        path.name for path in (paths.SRC / "skills").rglob("*.md") if "/Users/" in path.read_text()
    ]
    assert named == []
