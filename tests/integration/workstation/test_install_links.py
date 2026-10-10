"""Home installation refuses linked destinations without touching foreign files."""

import pytest

from slopmeister.errors import SlopmeisterError
from slopmeister.workstation import doctor, drift, install, manifest, orca, state
from tests.integration.workstation.test_install import machine, workstation

NAME = ".local/bin/op"
ENTRY = next(entry for entry in manifest.COMMON if entry.destination == NAME)


@pytest.fixture(
    params=[
        (part, kind) for part in ("entry", "parent") for kind in ("existing", "equal", "dangling")
    ]
)
def linked_home(tmp_path, request):
    home, binaries = machine(tmp_path)
    part, kind = request.param
    outside = tmp_path / "outside"
    if part == "entry" or kind != "dangling":
        outside.mkdir()
    target = outside / ("op" if part == "entry" else "bin/op")
    original = ENTRY.expected(home) if kind == "equal" else b"FOREIGN_ONLY_CONTENT\n"
    if kind != "dangling":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(original)
        target.chmod(0o640)
    link = home / (NAME if part == "entry" else ".local")
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target if part == "entry" else outside, target_is_directory=part == "parent")
    return home, binaries, link, target, original if kind != "dangling" else None


def test_selected_batch_refuses_links_before_any_install_or_backup(linked_home):
    home, binaries, link, target, original = linked_home
    ordinary = home / ".claude/CLAUDE.md"
    ordinary.parent.mkdir()
    ordinary.write_bytes(b"keep ordinary entry\n")
    result = workstation(home, binaries, "install", ".claude/CLAUDE.md", NAME)
    assert result.returncode != 0 and "unsafe symlink" in result.stderr
    assert "Resolve the link before retrying" in result.stderr
    assert ordinary.read_bytes() == b"keep ordinary entry\n"
    assert (target.read_bytes() if target.exists() else None) == original
    assert original is None or target.stat().st_mode & 0o777 == 0o640
    assert link.is_symlink() and not (home / install.BACKUP_ROOT).exists()


def test_diff_reports_link_drift_without_reading_foreign_content(linked_home):
    home, binaries, _, _, _ = linked_home
    result = workstation(home, binaries, "diff")
    assert result.returncode == 0
    assert f"unsafe symlink: {NAME}" in result.stdout
    assert "FOREIGN_ONLY_CONTENT" not in result.stdout + result.stderr
    item = next(item for item in state.items(home) if item.name == NAME)
    assert item.pending and item.status == "unsafe symlink"
    row = doctor._home_install(home, set())
    assert row.status == "problem" and f"unsafe symlink: {NAME}" in row.evidence


def test_drift_reports_link_as_unsafe_instead_of_unchanged(linked_home, capsys):
    home = linked_home[0]
    assert drift._home_install(home) > 0
    assert f"unsafe symlink: ~/{NAME}" in capsys.readouterr().out


def test_unselected_link_does_not_block_an_unrelated_named_install(linked_home):
    home, binaries, link, target, original = linked_home
    result = workstation(home, binaries, "install", ".claude/CLAUDE.md")
    assert result.returncode == 0, result.stderr
    assert (home / ".claude/CLAUDE.md").is_file() and link.is_symlink()
    assert (target.read_bytes() if target.exists() else None) == original


def test_alias_above_selected_home_remains_supported(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    home, binaries = machine(real)
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    result = workstation(alias / "home", binaries, "install", NAME)
    assert result.returncode == 0, result.stderr
    assert (home / NAME).read_bytes() == ENTRY.expected(home)


@pytest.mark.parametrize("name", (manifest.CODEX_CONFIG, orca.NAME, manifest.APPLET))
def test_special_entries_refuse_links_before_another_selected_write(tmp_path, monkeypatch, name):
    monkeypatch.setenv("SLOPMEISTER_PLATFORM", "darwin")
    home, binaries = machine(tmp_path)
    destination = home / name
    if destination.exists():
        destination.unlink()
    destination.parent.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "foreign"
    target.write_text(
        '{"settings": {}}' if name == orca.NAME else "model_context_window = 872000\n"
    )
    destination.symlink_to(target)
    before = target.read_bytes()
    result = workstation(home, binaries, "install", name, ".claude/CLAUDE.md")
    assert result.returncode != 0 and "unsafe symlink" in result.stderr
    assert target.read_bytes() == before and destination.is_symlink()
    assert not (home / ".claude").exists()
    assert not (home / install.BACKUP_ROOT).exists()


@pytest.mark.parametrize("linked", ("entry", "parent"))
def test_linked_backup_destination_refuses_before_either_file_changes(
    tmp_path, monkeypatch, linked
):
    home, _ = machine(tmp_path)
    destination = home / NAME
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"original installed bytes\n")
    backups = home / install.BACKUP_ROOT / "fixed"
    target = tmp_path / "outside" / ("saved" if linked == "entry" else "bin/op")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"foreign backup bytes\n")
    link = backups / (NAME if linked == "entry" else ".local")
    link.parent.mkdir(parents=True)
    link.symlink_to(target if linked == "entry" else target.parent.parent)
    monkeypatch.setattr(install, "backup_dir", lambda _: backups)
    with pytest.raises(SlopmeisterError, match="unsafe symlink"):
        install.install(home, {NAME})
    assert destination.read_bytes() == b"original installed bytes\n"
    assert target.read_bytes() == b"foreign backup bytes\n" and link.is_symlink()
