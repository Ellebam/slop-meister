"""The drift gate fails on installed or delivered drift and nothing else, nothing live touched."""

import json

from slopmeister.workstation import drift, manifest
from tests.integration.install.installer_helpers import prepared, state
from tests.integration.workstation.test_install import ORCA_DATA, machine, workstation
from tests.support.repos import git, scratch_repo

HELPER = ".claude/skills/ship/scripts/ship.py"
PREPARED_ENV = ("HOME", "XDG_STATE_HOME", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM")


def _installed_home(tmp_path, monkeypatch):
    # The install below runs the Mac branch, so the drift read in this process must too.
    monkeypatch.setenv("SLOPMEISTER_PLATFORM", "darwin")
    home, bin_dir = machine(tmp_path)
    (home / manifest.VAULT_REPOSITORY).mkdir(parents=True)
    assert workstation(home, bin_dir, "install", "--all").returncode == 0
    return home


def _prepared(tmp_path, monkeypatch):
    installed = prepared(tmp_path)
    for key in PREPARED_ENV:
        monkeypatch.setenv(key, installed.env[key])
    monkeypatch.setattr(drift, "ROOT", installed.workspace)
    monkeypatch.setattr(drift, "PLOT", "example-app")
    monkeypatch.setattr(drift.state, "items", lambda home: [])
    return installed


def test_main_checkout_with_review_results_and_no_state_passes(tmp_path, monkeypatch, capsys):
    """Escaping bug: review results in the shared config folder read as a broken launch."""
    home = _installed_home(tmp_path, monkeypatch)
    checkout = scratch_repo(tmp_path / "checkout")
    (checkout / ".git/slopmeister-config/reviews").mkdir(parents=True)
    monkeypatch.setattr(drift, "ROOT", checkout)
    assert drift.drift(home) == 0
    output = capsys.readouterr().out
    assert "invalid Slopmeister configuration state" not in output
    assert "Drifted or missing: 0" in output


def test_drifted_home_file_fails_and_names_it(tmp_path, monkeypatch, capsys):
    """Escaping bug: the prune drops the one check the gate exists for."""
    home = _installed_home(tmp_path, monkeypatch)
    monkeypatch.setattr(drift, "ROOT", scratch_repo(tmp_path / "checkout"))
    (home / ".codex/AGENTS.md").write_text("stale line\n")
    assert drift.drift(home) == 1
    assert "drifted: ~/.codex/AGENTS.md" in capsys.readouterr().out


def test_linked_home_drift_is_a_notice_but_doctor_stays_strict(tmp_path, monkeypatch, capsys):
    from slopmeister.workstation import doctor

    home = _installed_home(tmp_path, monkeypatch)
    checkout = scratch_repo(tmp_path / "checkout")
    workspace = tmp_path / "workspace"
    git(checkout, "worktree", "add", "-q", "-b", "task", str(workspace))
    monkeypatch.setattr(drift, "ROOT", workspace)
    (home / ".codex/AGENTS.md").write_text("stale line\n")
    assert drift.drift(home) == 0
    output = capsys.readouterr().out
    assert "Notice:" in output and "~/.codex/AGENTS.md" in output
    assert doctor._home_install(home, doctor.host.home_setup(home)[2]).status == "problem"
    monkeypatch.setattr(drift, "ROOT", checkout)
    assert drift.drift(home) == 1
    assert doctor._home_install(home, doctor.host.home_setup(home)[2]).status == "problem"


def test_orca_ui_edit_of_managed_key_fails_drift_without_printing_app_state(
    tmp_path, monkeypatch, capsys
):
    """Bug: changing a managed setting in Orca's UI passed the workstation gate."""
    home = _installed_home(tmp_path, monkeypatch)
    monkeypatch.setattr(drift, "ROOT", scratch_repo(tmp_path / "checkout"))
    path = home / ORCA_DATA
    data = json.loads(path.read_text())
    data["settings"]["telemetry"]["optedIn"] = True
    data["otherState"]["private"] = "do-not-print"
    path.write_text(json.dumps(data))
    assert drift.drift(home) == 1
    output = capsys.readouterr().out
    assert f"drifted: ~/{ORCA_DATA}" in output
    assert "do-not-print" not in output


def test_prepared_worktree_with_changed_delivery_fails(tmp_path, monkeypatch, capsys):
    """Escaping bug: detection by the state file skips a real launcher worktree."""
    installed = _prepared(tmp_path, monkeypatch)
    assert drift.drift(tmp_path) == 0
    monkeypatch.setattr(
        drift.state,
        "items",
        lambda home: [type("Difference", (), {"status": "differs", "name": ".codex/AGENTS.md"})()],
    )
    helper = installed.workspace / HELPER
    helper.write_bytes(helper.read_bytes() + b"\nchanged helper\n")
    # A delivered-root file name can carry a terminal escape that would forge the report.
    (helper.parent / "forged\x1b[2Kname").write_text("")
    assert drift.drift(tmp_path) == 1
    error = capsys.readouterr().err
    assert "saved session configuration" in error
    assert HELPER in error
    assert "forged\\u001b[2Kname" in error and "\x1b" not in error


def test_prepared_worktree_with_unreadable_state_fails(tmp_path, monkeypatch, capsys):
    """Escaping bug: a corrupt saved state passes the gate instead of failing it."""
    installed = _prepared(tmp_path, monkeypatch)
    path, _ = state(installed.workspace)
    path.write_text(json.dumps({"no": "grants"}))
    assert drift.drift(tmp_path) == 1
    assert "invalid Slopmeister configuration state" in capsys.readouterr().out


def test_prepared_worktree_with_a_directory_for_state_fails(tmp_path, monkeypatch, capsys):
    """Escaping bug: something other than a file at the saved state path skips the replay."""
    installed = _prepared(tmp_path, monkeypatch)
    path, _ = state(installed.workspace)
    path.unlink()
    path.mkdir()
    assert drift.drift(tmp_path) == 1
    assert "invalid Slopmeister configuration state" in capsys.readouterr().out
