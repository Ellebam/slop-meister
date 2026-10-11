"""The Drive sync command with the real rclone between local folders. No account is used."""

from collections.abc import Iterator
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

import pytest

ROOT = Path(__file__).resolve().parents[3]
SYNC = ROOT / "plots/home/drive/drive-sync.sh"
LINT = [str(ROOT / "bin/slopmeister"), "vault", "lint"]
NOTES = 20
HOUR = 3600

pytestmark = pytest.mark.skipif(shutil.which("rclone") is None, reason="rclone is not installed")


class World:
    """A local vault and documents folder, and a folder that stands in for Drive."""

    def __init__(self, root: Path) -> None:
        self.vault, self.documents = root / "v", root / "m"
        self.drive = root / "d"
        self.drive_vault = self.drive / "obsidian"
        (self.drive_vault / "_system").mkdir(parents=True)
        for number in range(NOTES):
            (self.drive_vault / f"n{number}.md").write_text(f"note {number}\n")
        (root / "rclone.conf").touch()
        self.env = {
            **os.environ,
            "HOME": str(root / "h"),
            "RCLONE_CONFIG": str(root / "rclone.conf"),
            "SLOPMEISTER_VAULT": str(self.vault),
            "DRIVE_SYNC_DOCUMENTS": str(self.documents),
            "DRIVE_SYNC_REMOTE": f"{self.drive}/",
            "DRIVE_SYNC_STATE": str(root / "s"),
        }

    def sync(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SYNC), *args], env=self.env, capture_output=True, text=True, check=False
        )

    def first_sync(self, mode: str = "vault") -> None:
        done = self.sync(mode, "--resync")
        assert done.returncode == 0, done.stderr


def edit(path: Path, text: str, age: int) -> None:
    path.write_text(text)
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))


@pytest.fixture
def world() -> Iterator[World]:
    # bisync names its state files after both paths, so a deep pytest folder overflows a name.
    root = Path(tempfile.mkdtemp(prefix="ds", dir="/tmp"))
    try:
        yield World(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_deleting_a_tenth_refuses_and_drive_keeps_every_note(world: World) -> None:
    """Bugs: a mass deletion on this machine reaches Drive, and a refused run locks sync
    until a resync even after the notes are back."""
    world.first_sync()
    for number in range(NOTES // 10):
        (world.vault / f"n{number}.md").unlink()
    for _ in range(2):
        refused = world.sync("vault")
        assert refused.returncode != 0 and "too many deletes" in refused.stderr
        assert len(list(world.drive_vault.glob("n*.md"))) == NOTES
    for number in range(NOTES // 10):
        (world.vault / f"n{number}.md").write_text(f"note {number}\n")
    assert world.sync("vault").returncode == 0


@pytest.mark.parametrize(("older", "suffix"), [("vault", "linux"), ("drive_vault", "drive")])
def test_newer_edit_keeps_the_name_and_lint_reports_the_older_copy(
    world: World, older: str, suffix: str
) -> None:
    """Bugs: the older edit is lost, the newer one is renamed away, or the copy gets a name
    the lint does not look for."""
    world.first_sync()
    newer = "drive_vault" if older == "vault" else "vault"
    edit(getattr(world, older) / "n3.md", "the older edit\n", HOUR)
    edit(getattr(world, newer) / "n3.md", "the newer edit, longer\n", 0)
    done = world.sync("vault")
    assert done.returncode == 0, done.stderr
    copy = f"n3.sync-conflict-{suffix}1.md"
    for side in (world.vault, world.drive_vault):
        assert (side / "n3.md").read_text() == "the newer edit, longer\n"
        assert (side / copy).read_text() == "the older edit\n"
    lint = subprocess.run(LINT, env=world.env, capture_output=True, text=True, check=False)
    assert lint.returncode == 1
    assert "conflict copies:  1 (must be 0)" in lint.stdout and copy in lint.stdout


def test_documents_run_mirrors_folders_and_never_touches_the_vault(world: World) -> None:
    """Bugs: the documents run copies the vault a second time or deletes inside it, and an
    empty Drive folder is missing on this machine."""
    (world.drive / "Papers").mkdir()
    (world.drive / "Papers/scan.pdf").write_text("scan\n")
    (world.drive / "Empty").mkdir()
    world.first_sync("documents")
    assert (world.documents / "Papers/scan.pdf").read_text() == "scan\n"
    assert (world.documents / "Empty").is_dir()
    assert not (world.documents / "obsidian").exists()
    (world.documents / "Papers/filed.txt").write_text("filed here\n")
    assert world.sync("documents").returncode == 0
    assert (world.drive / "Papers/filed.txt").read_text() == "filed here\n"
    assert len(list(world.drive_vault.glob("n*.md"))) == NOTES


def test_a_failed_listing_fails_the_run_and_frees_the_next(world: World) -> None:
    """Bug: one network outage locks every later run until someone resyncs by hand."""
    world.first_sync()
    world.drive_vault.chmod(0o000)
    try:
        assert world.sync("vault").returncode != 0
    finally:
        world.drive_vault.chmod(0o755)
    (world.drive_vault / "later.md").write_text("after the outage\n")
    done = world.sync("vault")
    assert done.returncode == 0, done.stderr
    assert (world.vault / "later.md").read_text() == "after the outage\n"


def test_first_sync_keeps_a_note_that_changes_on_drive_meanwhile(
    world: World, tmp_path: Path
) -> None:
    """Bug: a note edited on Drive while the first sync downloads is overwritten by the older
    copy this machine just fetched, and no copy of the edit is kept."""
    wrapper = tmp_path / "rclone"
    # The stand-in puts the fetched older copy in place after the command's empty-folder check.
    wrapper.write_text(
        "#!/bin/bash\n"
        'if [ "$1" = bisync ]; then echo "the fetched older copy" > "$2/n3.md"; '
        'touch -t 202601010000 "$2/n3.md"; fi\n'
        f'exec {shutil.which("rclone")} "$@"\n'
    )
    wrapper.chmod(0o755)
    world.env["PATH"] = f"{tmp_path}:{world.env['PATH']}"
    (world.drive_vault / "n3.md").write_text("edited on Drive meanwhile, longer\n")
    world.first_sync()
    for side in (world.vault, world.drive_vault):
        assert (side / "n3.md").read_text() == "edited on Drive meanwhile, longer\n"


def test_a_second_conflict_keeps_the_copy_of_the_first(world: World) -> None:
    """Bug: a second conflict on one note before the first copy is merged overwrites that copy,
    and the first losing edit is gone on both sides."""
    world.first_sync()
    for text in ("the first older edit\n", "the second older edit, other\n"):
        edit(world.vault / "n3.md", text, HOUR)
        edit(world.drive_vault / "n3.md", f"newer than {text.strip()}, longer\n", 0)
        assert world.sync("vault").returncode == 0
    for side in (world.vault, world.drive_vault):
        kept = sorted(path.read_text() for path in side.glob("n3.sync-conflict-*.md"))
        assert kept == ["the first older edit\n", "the second older edit, other\n"]
