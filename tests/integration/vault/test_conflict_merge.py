"""The merge steps the lint prints for a conflict copy, followed against a scratch history."""

import os
from pathlib import Path
import subprocess

import pytest

from tests.integration.vault.test_repository import run, vaultgit
from tests.support.repos import GIT_ENV

NOTE = "_system/note.md"
COPY = "_system/note.sync-conflict-linux.md"
LINES = [f"line {number}\n" for number in range(1, 21)]
FIRST_LOCAL, SECOND_LOCAL, REMOTE = (
    "line 2, first local\n",
    "line 5, second local\n",
    "line 18, remote\n",
)


def changed(lines: list[str], **edits: str) -> str:
    return "".join(edits.get(f"l{number}", line) for number, line in enumerate(lines, 1))


class World:
    def __init__(self, root: Path) -> None:
        self.vault, self.scratch = root / "vault", root / "scratch"
        (self.vault / "_system").mkdir(parents=True)
        self.scratch.mkdir()
        (self.vault / NOTE).write_text(changed(LINES, l15="line 15, before\n"))
        self.env = {
            **os.environ,
            **GIT_ENV,
            "HOME": str(root / "home"),
            "SLOPMEISTER_VAULT": str(self.vault),
            "VAULT_GIT_DIR": str(root / "vault.git"),
            "SLOPMEISTER_VAULT_LOCKED": "1",
            "VAULTGIT": str(ROOT_WRAPPER),
        }
        assert run("init", env=self.env).returncode == 0
        self.early = self.head()
        self.base = self.commit(changed(LINES))
        self.first = self.commit(changed(LINES, l2=FIRST_LOCAL))
        local = changed(LINES, l2=FIRST_LOCAL, l5=SECOND_LOCAL)
        self.commit(local)
        # What the sync leaves: the newer remote text under the name, the local text beside it.
        (self.vault / NOTE).write_text(changed(LINES, l18=REMOTE))
        (self.vault / COPY).write_text(local)

    def head(self) -> str:
        return vaultgit(self.env, "rev-parse", "HEAD").stdout.strip()

    def commit(self, text: str) -> str:
        (self.vault / NOTE).write_text(text)
        done = run("commit", "Edit", "--", NOTE, env=self.env)
        assert done.returncode == 0, done.stderr
        return self.head()

    def merged(self, commit: str) -> tuple[int, str]:
        """Steps 1 and 2 on a copy of the note, with the given commit as base."""
        note, base = self.scratch / "note.md", self.scratch / "base.md"
        note.write_text((self.vault / NOTE).read_text())
        base.write_text(vaultgit(self.env, "show", f"{commit}:{NOTE}").stdout)
        done = subprocess.run(
            ["git", "merge-file", str(note), str(base), str(self.vault / COPY)], check=False
        )
        return done.returncode, note.read_text()


ROOT_WRAPPER = Path(__file__).resolve().parents[3] / "plots/vault/bin/vaultgit"


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_a_base_from_before_both_edits_merges_without_manual_work(world: World) -> None:
    """Bugs: edits that do not overlap still need manual work, or an older base than the
    last shared version loses an edit."""
    for commit in (world.base, world.early):
        status, text = world.merged(commit)
        assert status == 0
        assert all(edit in text for edit in (FIRST_LOCAL, SECOND_LOCAL, REMOTE))
        assert "line 15\n" in text
    (world.vault / NOTE).write_text(world.merged(world.base)[1])
    (world.vault / COPY).unlink()
    done = run("commit", "Merge conflict copy", "--", NOTE, env=world.env)
    assert done.returncode == 0, done.stderr
    assert vaultgit(world.env, "status", "--porcelain").stdout == ""


def test_a_base_that_holds_one_sides_edit_reverts_it_silently(world: World) -> None:
    """Bug: the steps are shortened to "take the newest different commit", which picks this
    machine's own first edit as base. The merge then exits 0 and drops that edit."""
    status, text = world.merged(world.first)
    assert status == 0
    assert FIRST_LOCAL not in text and SECOND_LOCAL in text and REMOTE in text
