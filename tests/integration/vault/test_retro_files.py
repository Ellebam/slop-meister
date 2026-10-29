"""Retired automatic retro entry points refuse without changing notes or spills."""

import subprocess

import pytest

from tests.integration.vault.test_repository import COMMAND, vaultgit
from tests.integration.vault.test_repository import repository as repository


@pytest.mark.parametrize("kind", ["automatic-note", "counter"])
def test_retired_default_route_preserves_existing_notes_index_and_spills(
    repository, tmp_path, kind
):
    env, vault = repository
    note = vault / "_system/retros/existing.md"
    note.parent.mkdir(parents=True)
    note.write_text("existing note\n")
    (vault / "foreign.md").write_text("foreign change\n")
    vaultgit(env, "add", "--", "foreign.md")
    spill = tmp_path / "spill"
    spill.mkdir()
    owed = spill / "owed.md"
    owed.write_text("existing spill\n")
    before = {p.relative_to(vault): p.read_bytes() for p in vault.rglob("*") if p.is_file()}
    index = vaultgit(env, "diff", "--cached", "--name-only").stdout
    args = (
        [
            "retro",
            "--repo",
            "fixture",
            "--task",
            "task",
            "--title",
            "title",
            "--tool",
            "codex",
            "--model",
            "model",
        ]
        if kind == "automatic-note"
        else ["retro-count"]
    )
    result = subprocess.run(
        [*COMMAND, *args],
        input="one\ntwo\nthree\n",
        env=env | {"RETRO_SPILL_DIR": str(spill)},
        capture_output=True,
        text=True,
    )
    expected = "--note" if kind == "automatic-note" else "invalid choice"
    assert result.returncode == 2 and expected in result.stderr
    assert result.stdout == ""
    assert before == {p.relative_to(vault): p.read_bytes() for p in vault.rglob("*") if p.is_file()}
    assert vaultgit(env, "diff", "--cached", "--name-only").stdout == index
    assert owed.read_text() == "existing spill\n"
