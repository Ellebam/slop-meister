"""A local vault needs no optional integration, and partial setups remain visible."""

import json
import shlex

import pytest

from slopmeister.workstation import manifest
from tests.integration.workstation.test_install import machine, workstation
from tests.support.fakes import fake_binary


@pytest.fixture
def plain_vault(tmp_path):
    home, bin_dir = machine(tmp_path)
    vault = tmp_path / "vault"
    (vault / "_system").mkdir(parents=True)
    (vault / "note.md").write_text("# Local note\n")
    return home, bin_dir, vault


def report(plain_vault, platform, **env):
    home, bin_dir, vault = plain_vault
    run = workstation(
        home, bin_dir, "doctor", "--vault", str(vault), SLOPMEISTER_PLATFORM=platform, **env
    )
    assert run.returncode == 0, run.stderr
    return {row["name"]: row for row in json.loads(run.stdout)}


@pytest.mark.parametrize("platform", ("linux", "darwin"))
def test_plain_vault_needs_only_readable_local_notes(plain_vault, platform):
    found = report(plain_vault, platform)
    rows = {name: row for name, row in found.items() if name.startswith("vault")}
    assert set(rows) == {"vault", "vault-local"}
    assert all(row["status"] == "ok" for row in rows.values())
    assert "tool:rclone" not in found and "documents-sync" not in found
    assert f"launchd:{manifest.VAULT_LABEL}" not in found
    assert "drive-sync" not in json.dumps(found)


@pytest.mark.parametrize("platform", ("linux", "darwin"))
def test_declined_phone_route_is_not_required_or_selected_by_a_repair(plain_vault, platform):
    found = report(plain_vault, platform)
    assert not any("claude-remote-control" in name for name in found)
    assert "linger" not in found
    row = found["home-install"]
    assert "claude-remote-control" not in row["evidence"]
    repair = shlex.split(row["fix"].partition("task home:install ")[2])
    assert repair and repair[0] == "--" and ".claude/CLAUDE.md" in repair
    assert not any("claude-remote-control" in name or "drive-sync" in name for name in repair)


@pytest.mark.parametrize("platform", ("linux", "darwin"))
def test_configured_phone_route_retains_its_failed_service_probe(plain_vault, platform):
    home, bin_dir, _ = plain_vault
    prefix, entry, binary = (
        ("systemd", ".config/systemd/user/claude-remote-control.service", "systemctl")
        if platform == "linux"
        else ("launchd", "Library/LaunchAgents/local.claude-remote-control.plist", "launchctl")
    )
    path = home / entry
    path.parent.mkdir(parents=True)
    path.write_text("incomplete configuration\n")
    fake_binary(bin_dir, binary, "exit 1")
    found = report(plain_vault, platform)
    label = manifest.CLAUDE_UNIT if platform == "linux" else manifest.CLAUDE_LABEL
    assert found[f"{prefix}:{label}"]["status"] == "problem"
    assert entry in found["home-install"]["evidence"]


@pytest.mark.parametrize(
    "platform,marker",
    [
        ("linux", manifest.VAULT_REPOSITORY),
        ("linux", ".config/systemd/user/vault-commit.service"),
        ("linux", ".config/systemd/user/vault-commit.timer"),
        ("darwin", manifest.VAULT_REPOSITORY),
        ("darwin", "Library/LaunchAgents/local.vault-commit.plist"),
    ],
)
def test_partial_history_configuration_remains_a_problem(plain_vault, platform, marker):
    path = plain_vault[0] / marker
    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir() if marker == manifest.VAULT_REPOSITORY else path.write_text("fixture\n")
    found = report(plain_vault, platform)
    assert found["vault-repository"]["status"] == "problem"
    assert found["vault-history"]["status"] == "problem"
    assert "tool:rclone" not in found and "vault-sync" not in found
    name = "vault-sweep" if platform == "linux" else f"launchd:{manifest.VAULT_LABEL}"
    assert name in found
    if platform == "linux":
        assert "linger" in found


@pytest.mark.parametrize(
    "marker",
    [
        manifest.SYNC_COMMAND,
        ".config/systemd/user/drive-sync-vault.service",
        ".config/systemd/user/drive-sync-vault.timer",
        ".config/systemd/user/drive-sync-documents.service",
        ".config/systemd/user/drive-sync-documents.timer",
    ],
)
def test_partial_drive_configuration_keeps_missing_requirements(plain_vault, marker):
    path = plain_vault[0] / marker
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture\n")
    found = report(plain_vault, "linux", PATH=str(plain_vault[1]))
    for name in ("tool:rclone", "vault-sync", "documents-sync", "vault-delete-guard"):
        assert found[name]["status"] == "problem"
    assert "vault-history" not in found and "vault-sweep" not in found
    assert "linger" in found


@pytest.mark.parametrize("relative", ("note.md", "_system"))
def test_unreadable_local_content_is_not_reported_healthy(plain_vault, relative):
    path = plain_vault[2] / relative
    mode = path.stat().st_mode
    path.chmod(0)
    try:
        found = report(plain_vault, "linux")
    finally:
        path.chmod(mode)
    assert found["vault-local"]["status"] == "problem"
    assert "read" in found["vault-local"]["evidence"].lower()
