"""The home install on Linux under a scratch home, with fake systemctl and loginctl."""

import pytest

from slopmeister.workstation import manifest, orca
from tests.integration.workstation.test_install import APPLET, ROOT, machine, workstation
from tests.support.fakes import fake_binary

UNIT = ".config/systemd/user/claude-remote-control.service"
SOURCE = "plots/home/systemd/claude-remote-control.service"
STEPS = [
    "systemctl --user daemon-reload",
    "systemctl --user enable claude-remote-control.service",
    "systemctl --user restart claude-remote-control.service",
    "loginctl enable-linger",
]
UNITS = ".config/systemd/user"
TIMER_STEPS = [
    step
    for name in manifest.TIMERS
    for step in (
        "systemctl --user daemon-reload",
        f"systemctl --user enable {name}.timer",
        f"systemctl --user restart {name}.timer",
        "loginctl enable-linger",
    )
]


def linux(home, bin_dir, *args):
    return workstation(home, bin_dir, *args, SLOPMEISTER_PLATFORM="linux")


def test_install_enables_the_unit_and_lingering_in_order(tmp_path):
    """Bug: the unit is written but never enabled or lingering, so a reboot drops the phone."""
    home, bin_dir = machine(tmp_path)
    result = linux(home, bin_dir, "install", "--all")
    assert result.returncode == 0, result.stderr
    assert (home / UNIT).read_bytes() == (ROOT / SOURCE).read_bytes()
    assert (tmp_path / "service.log").read_text().splitlines() == STEPS + TIMER_STEPS


def test_install_places_the_sync_command_and_enables_only_the_timers(tmp_path):
    """Bugs: a sync or sweep service is started by the install, before any sign-in, or its
    timer is enabled before the service it names exists, or the command is not executable."""
    home, bin_dir = machine(tmp_path)
    assert linux(home, bin_dir, "install", "--all").returncode == 0
    command = home / manifest.SYNC_COMMAND
    assert command.read_bytes() == (ROOT / "plots/home/drive/drive-sync.sh").read_bytes()
    assert command.stat().st_mode & 0o111
    order = [entry.destination for entry in manifest.SERVICES["linux"]]
    for name in manifest.TIMERS:
        for kind in ("service", "timer"):
            source = (ROOT / f"plots/home/systemd/{name}.{kind}").read_bytes()
            assert (home / UNITS / f"{name}.{kind}").read_bytes() == source
        assert order.index(f"{UNITS}/{name}.service") < order.index(f"{UNITS}/{name}.timer")
    assert ".service" not in "".join(TIMER_STEPS)
    assert not [
        line
        for line in (tmp_path / "service.log").read_text().splitlines()
        if "drive-sync" in line and ".service" in line
    ]


@pytest.mark.parametrize(
    ("name", "command", "schedule"),
    [
        (manifest.VAULT_SYNC, "%h/.local/bin/slopmeister-drive-sync vault", "OnCalendar=*:0/5"),
        (
            manifest.DOCUMENTS_SYNC,
            "%h/.local/bin/slopmeister-drive-sync documents",
            "OnCalendar=*:2/5",
        ),
        (manifest.VAULT_SWEEP, "%h/.vault-git/bin/vault-commit.sh", "OnCalendar=*-*-* 08,20:00:00"),
    ],
)
def test_each_timer_runs_its_command_on_its_schedule(name, command, schedule):
    """Bug: a timer runs the wrong folder pair, never fires, or does not start at boot."""
    service = (ROOT / f"plots/home/systemd/{name}.service").read_text().splitlines()
    timer = (ROOT / f"plots/home/systemd/{name}.timer").read_text().splitlines()
    assert f"ExecStart={command}" in service and "Type=oneshot" in service
    assert schedule in timer and "WantedBy=timers.target" in timer


def test_the_unit_restarts_and_starts_at_boot():
    """Bug: an exited remote-control server stays down, or the unit never starts at boot."""
    unit = (ROOT / SOURCE).read_text()
    for line in (
        "ExecStart=%h/.local/bin/claude remote-control",
        "WorkingDirectory=%h/dev/slop-meister",
        "Restart=always",
        "RestartSec=60",
        "WantedBy=default.target",
    ):
        assert line in unit.splitlines()


def test_linux_install_places_nothing_from_launchd(tmp_path):
    """Bug: the Linux install writes launchd files, builds the applet or stops on Orca's file."""
    home, bin_dir = machine(tmp_path)
    # A fresh Orca profile has no settings file, so the install must not ask for one.
    (home / orca.NAME).unlink()
    assert linux(home, bin_dir, "install", "--all").returncode == 0
    assert not (home / "Library/LaunchAgents").exists() and not (home / APPLET).exists()
    (tmp_path / "mac").mkdir()
    mac_home, mac_bin = machine(tmp_path / "mac")
    assert workstation(mac_home, mac_bin, "install", "--all").returncode == 0
    assert not (mac_home / UNITS).exists() and not (mac_home / manifest.SYNC_COMMAND).exists()
    assert not (tmp_path / "launchctl.log").exists() and not (home / orca.NAME).exists()
    assert "0 file(s) differ. Nothing written." in linux(home, bin_dir, "diff").stdout
    refused = linux(home, bin_dir, "install", APPLET)
    assert refused.returncode == 2 and f"unknown entries {APPLET}" in refused.stderr


@pytest.mark.parametrize("failing", STEPS[1:])
def test_a_failed_service_step_is_named_and_fails_the_install(tmp_path, failing):
    """Bug: enabling, starting or lingering failed, and the install still reported success."""
    home, bin_dir = machine(tmp_path)
    name = failing.split()[0]
    fake_binary(bin_dir, name, f'[ "{name} $*" = "{failing}" ] && exit 1; exit 0')
    result = linux(home, bin_dir, "install", "--all")
    assert result.returncode != 0
    assert f"NOT set up, this step failed: {failing}" in result.stdout
    assert "systemd unit(s) not set up: claude-remote-control" in result.stderr
