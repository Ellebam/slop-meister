"""The doctor's per-system reads, answered by fake programs. Each names the bug it prevents."""

import pytest

from slopmeister import paths
from slopmeister.dispatch import command
from slopmeister.session.service_actions import runtime
from slopmeister.workstation import doctor, host, orca
from tests.support.fakes import fake_binary, path_with

SYSTEMCTL = 'case "$2" in is-active) echo {active};; is-enabled) echo {enabled};; esac'
REPAIR = "systemctl --user enable --now claude-remote-control.service"


@pytest.mark.parametrize(
    ("active", "enabled", "expected"),
    [
        ("active", "enabled", "ok"),
        ("inactive", "enabled", "problem"),
        ("active", "disabled", "problem"),
        ("inactive", "not-found", "problem"),
    ],
)
def test_the_unit_must_run_now_and_start_at_boot(tmp_path, monkeypatch, active, enabled, expected):
    """Bug: a running but disabled unit reads ok, and the phone loses the machine at a reboot."""
    fake_binary(tmp_path, "systemctl", SYSTEMCTL.format(active=active, enabled=enabled))
    monkeypatch.setenv("PATH", path_with(tmp_path))
    found = host._unit()
    assert (found.name, found.status) == ("systemd:claude-remote-control", expected)
    assert found.evidence == f"{active}, {enabled}"
    # The installer skips an unchanged unit, so the result itself must say how to repair it.
    assert REPAIR in found.fix


def test_a_missing_systemctl_is_unknown(tmp_path, monkeypatch):
    """Bug: a doctor that cannot ask systemd reports the phone route as ok."""
    monkeypatch.setenv("PATH", str(tmp_path))
    assert host._unit().status == "unknown"
    assert host._linger().status == "unknown"


@pytest.mark.parametrize(
    ("script", "expected"),
    [("echo yes", "ok"), ("echo no", "problem"), ("echo 'no such user' >&2; exit 1", "unknown")],
)
def test_lingering_is_read_from_loginctl(tmp_path, monkeypatch, script, expected):
    """Bug: a unit that runs now and stops at logout reads ok."""
    fake_binary(tmp_path, "loginctl", script)
    monkeypatch.setenv("PATH", path_with(tmp_path))
    found = host._linger()
    assert found.status == expected and "loginctl enable-linger" in found.fix


def test_services_follow_the_system(tmp_path, monkeypatch):
    """Bug: the doctor asks launchctl on Linux, or systemd on the Mac, and blames a missing tool."""
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv(paths.PLATFORM_VARIABLE, "linux")
    for entry in host.PHONE_ENTRIES.values():
        path = tmp_path / entry
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("configured\n")
    assert [found.name for found in host.services(tmp_path, True, False)] == [
        "systemd:claude-remote-control",
        "linger",
    ]
    monkeypatch.setenv(paths.PLATFORM_VARIABLE, "darwin")
    names = [found.name for found in host.services(tmp_path, True, False)]
    assert names == ["launchd:local.vault-commit", "launchd:local.claude-remote-control"]
    assert [found.name for found in host.services(tmp_path, False, False)] == [
        "launchd:local.claude-remote-control"
    ]


def test_sleep_guard_is_a_problem_when_its_program_is_gone(tmp_path, monkeypatch):
    """Bug: a machine without its sleep guard reads healthy, then no dispatcher starts."""
    guard = fake_binary(tmp_path, "guard", "exit 0")
    monkeypatch.setattr(command, "sleep_guard", lambda: (str(guard), "-i"))
    assert host.sleep_guard().status == "ok"
    monkeypatch.setattr(command, "sleep_guard", lambda: (str(tmp_path / "gone"),))
    found = host.sleep_guard()
    assert found.status == "problem" and str(tmp_path / "gone") in found.evidence


@pytest.mark.parametrize(("code", "expected"), [(0, "ok"), (1, "problem")])
def test_codex_login_is_read_from_the_exit_code(monkeypatch, code, expected):
    """Bug: a logged-out Codex passes the contract because the doctor has no result for it."""
    monkeypatch.setattr(host, "run", lambda *_args: (code, "private-account"))
    found = doctor.codex_login()
    assert found.status == expected and "private-account" not in found.evidence


def test_service_actions_names_each_missing_program(monkeypatch):
    """Bug: a machine that cannot run a service action reads healthy."""
    monkeypatch.setattr(runtime, "missing", lambda: ["/usr/bin/op", "/usr/bin/curl"])
    found = doctor._service_actions()
    assert found.status == "problem" and found.evidence == "missing: /usr/bin/op, /usr/bin/curl"
    monkeypatch.setattr(runtime, "missing", list)
    assert doctor._service_actions().status == "ok"


def test_vault_rows_have_a_result_on_both_systems(tmp_path, monkeypatch):
    """Bug: a vault row of the contract has no result and passes by absence."""
    monkeypatch.setenv(paths.PLATFORM_VARIABLE, "linux")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(host, "run", lambda *argv: (None, "systemctl could not run"))
    found = host.vault_rows(True, True)
    names = ["vault-sync", "documents-sync", "vault-sweep", "vault-delete-guard"]
    assert [item.name for item in found] == names
    assert [item.status for item in found] == ["unknown", "unknown", "unknown", "problem"]
    monkeypatch.setenv(paths.PLATFORM_VARIABLE, "darwin")
    assert doctor._vault_local(tmp_path / "missing")[0].status == "unknown"
    for name in ("a.md", "b.md"):
        (tmp_path / name).write_text("# note\n")
    assert doctor._vault_local(tmp_path)[0].status == "ok"
    monkeypatch.setattr(doctor, "_online_only", lambda path: path.name == "b.md")
    found = doctor._vault_local(tmp_path)[0]
    assert (found.name, found.status) == ("vault-local", "problem")
    assert found.evidence == "1 online-only note(s), first b.md"


def test_a_missing_system_package_on_linux_points_at_provisioning(tmp_path, monkeypatch):
    """Bug: an agent on Linux reads "install gh" and reaches for sudo, which no agent runs there."""
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(orca, "health", lambda: {"runtime": "missing", "hooks": "not checked"})
    monkeypatch.setenv(paths.PLATFORM_VARIABLE, "linux")
    assert "ask the operator to install it" in doctor._tool("gh").fix
    assert "ask the operator to install it" in doctor._tool("rclone").fix
    assert "ask the operator to install it" in doctor._orca()[0].fix
    assert doctor._tool("claude").fix == "install claude, see README.md"
    monkeypatch.setenv(paths.PLATFORM_VARIABLE, "darwin")
    assert doctor._tool("gh").fix == "install gh, see README.md"
    assert doctor._orca()[0].fix == "install Orca, then follow docs/orca.md"


def test_healthy_words_from_a_failed_systemctl_are_not_ok(tmp_path, monkeypatch):
    """Bug: systemctl prints active and enabled but exits with an error, and the unit reads ok."""
    fake_binary(tmp_path, "systemctl", SYSTEMCTL.format(active="active", enabled="enabled; exit 1"))
    monkeypatch.setenv("PATH", path_with(tmp_path))
    found = host._unit()
    assert found.status == "problem" and found.evidence == "active, enabled (exit 1)"
