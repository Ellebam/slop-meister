"""The doctor on Linux, through the command line, with fake systemctl and loginctl."""

from slopmeister.workstation import manifest
from tests.integration.workstation.test_doctor import HOST_BOUND, healthy, results
from tests.support.fakes import fake_binary

UNIT = "systemd:claude-remote-control"
TIMERS = {"vault-sync", "documents-sync", "vault-sweep"}
SYSTEMCTL = (
    'case "$2" in is-active) echo active;; is-enabled) echo {enabled};; '
    'is-failed) [ "$3" = "{failed}" ] && echo failed || {{ echo inactive; exit 1; }};; esac'
)


def machine(tmp_path, enabled="enabled", linger="yes", failed=""):
    home, bin_dir = healthy(tmp_path, "linux")
    fake_binary(bin_dir, "rclone", "exit 0")
    fake_binary(bin_dir, "systemctl", SYSTEMCTL.format(enabled=enabled, failed=failed))
    fake_binary(bin_dir, "loginctl", f"echo {linger}")
    return home, bin_dir


def problems(found: dict[str, dict]) -> set[str]:
    return {name for name, item in found.items() if item["status"] != "ok"} - HOST_BOUND


def test_healthy_linux_reports_every_vault_row_from_its_own_evidence(tmp_path):
    """Bug: a vault row of the contract has no result on Linux, or the doctor blames launchd."""
    found = results(*machine(tmp_path), "linux")
    assert problems(found) == set()
    assert {UNIT, "linger", "sleep-guard", "login:codex", "tool:zsh", "tool:lsof"} <= set(found)
    assert {*TIMERS, "vault-delete-guard", "vault-history", "tool:rclone"} <= set(found)
    assert found["vault-sync"]["evidence"] == "active, enabled, inactive"
    assert found["vault-local"]["status"] == "ok"
    assert not [name for name in found if name.startswith("launchd:")]


def test_a_running_but_disabled_unit_is_a_problem_with_its_repair(tmp_path):
    """Bug: the unit runs today, reads ok, and the phone loses the machine at the next reboot."""
    found = results(*machine(tmp_path, enabled="disabled"), "linux")
    assert problems(found) == {UNIT, *TIMERS}
    assert found[UNIT]["evidence"] == "active, disabled"
    assert "systemctl --user enable --now claude-remote-control.service" in found[UNIT]["fix"]


def test_lingering_off_is_a_problem(tmp_path):
    """Bug: the unit stops at logout and never starts at boot, and the doctor reads ok."""
    found = results(*machine(tmp_path, linger="no"), "linux")
    assert problems(found) == {"linger"}
    assert found["linger"]["evidence"] == "Linger=no"


def test_a_failed_last_sync_run_is_a_problem_that_names_the_journal(tmp_path):
    """Bug: the timer is active, every run fails or refuses, and the doctor reads healthy."""
    failed = f"{manifest.VAULT_SYNC}.service"
    found = results(*machine(tmp_path, failed=failed), "linux")
    assert problems(found) == {"vault-sync"}
    assert found["vault-sync"]["evidence"] == "active, enabled, failed"
    assert f"journalctl --user -u {failed}" in found["vault-sync"]["fix"]


def test_a_sync_command_without_its_deletion_limit_is_a_problem(tmp_path):
    """Bug: the installed command lost its limit and a mass deletion would spread unseen."""
    home, bin_dir = machine(tmp_path)
    command = home / manifest.SYNC_COMMAND
    command.write_text(command.read_text().replace("--max-delete", "--max-transfer"))
    found = results(home, bin_dir, "linux")
    assert problems(found) == {"vault-delete-guard", "home-install"}
