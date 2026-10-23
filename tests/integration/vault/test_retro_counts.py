"""Counts normalize repository names and do not count reviewed-copy candidates twice."""

import subprocess

import pytest

from tests.integration.vault.test_repository import COMMAND
from tests.integration.vault.test_repository import repository as repository
from tests.integration.vault.test_retro import ARGS


@pytest.fixture
def retro_copies(repository):
    env, vault = repository
    names = [
        "project",
        "Owner/Project",
        "https://example.org/Owner/project.git",
        "/checkout/project/.worktrees/work",
    ]
    for name in names:
        result = subprocess.run(
            [*COMMAND, "retro", *ARGS, "--repo", name],
            env=env,
            input="one\ntwo\nthree\n",
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
    directory = vault / "_system/retros"
    original = next(directory.glob("*.md"))
    original.with_name(original.stem + " (1).md").write_bytes(original.read_bytes())
    original.with_name(original.stem + ".sync-conflict-fixture.md").write_bytes(
        original.read_bytes()
    )
    (directory / "README.md").write_text("# Retros\n")
    return env, original


def test_counts_normalize_labels_and_skip_numbered_and_conflicted_duplicates(retro_copies):
    env, original = retro_copies
    counted = subprocess.run([*COMMAND, "retro-count"], env=env, capture_output=True, text=True)
    assert counted.returncode == 0 and counted.stdout == "project\t4\n", counted.stderr
    linted = subprocess.run(
        [*COMMAND, "lint", "--area", "_system/retros"], env=env, capture_output=True, text=True
    )
    assert linted.returncode == 1 and "numbered copy candidate" in linted.stdout
    assert "keep both until reviewed" in linted.stdout
    assert original.is_file() and original.with_name(original.stem + " (1).md").is_file()
