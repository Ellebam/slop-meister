"""Every committed plot declaration prepares, so no substitute declaration hides a broken row."""

import csv
import os
import subprocess

import pytest

from tests.integration.launch.helpers import CLI, ROOT, launch, machine, target

DIRECTORY = (
    b"This session runs outside any repository. There is nothing to commit.\nAgent shipping "
    b"permission for this session is deny. No push or PR write, including during finalize.\n"
)


def _rows() -> list[list[str]]:
    env = {key: value for key, value in os.environ.items() if key != "PLOT_DECLARATIONS"}
    listed = subprocess.run(
        [str(CLI), "plots", "--list"], env=env, capture_output=True, text=True, check=True
    )
    return [
        row for line in listed.stdout.splitlines() if (row := line.split("\t"))[1] != "template"
    ]


def _skills() -> list[str]:
    with (ROOT / "dist/manifest.tsv").open() as stream:
        return [
            row["name"] for row in csv.DictReader(stream, delimiter="\t") if row["kind"] == "skill"
        ]


@pytest.mark.parametrize("row", _rows(), ids=lambda row: row[0])
def test_every_registry_row_prepares(tmp_path, row):
    """Bug: a real plot cannot launch, or a directory session gets the wrong agreement, no notes
    file, a Git repository around it, or procedures it cannot read."""
    world = machine(tmp_path)
    plot, mode = row[0], row[1]
    name = f"{plot}-registry"
    if mode != "-":
        repo = target(tmp_path / "repo")
        launch(world, str(repo), plot, name)
        assert (repo / ".worktrees" / name / "AGENTS.md").is_file()
        return
    launch(world, plot, name)
    directory = world.sessions / name
    for tool, agreement in (("claude", "CLAUDE.md"), ("codex", "AGENTS.md")):
        render = (ROOT / f"dist/{tool}/plots/{plot}.md").read_bytes()
        assert (directory / agreement).read_bytes() == render + b"\n" + DIRECTORY
    assert (directory / f"{name}-NOTES.md").read_bytes() == b""
    inside = subprocess.run(
        ["git", "-C", str(directory), "rev-parse", "--git-dir"], capture_output=True
    )
    assert inside.returncode != 0
    for skill in _skills():
        for native in (".claude", ".agents"):
            path = directory / native / "skills" / skill
            assert not path.is_symlink() and os.access(path / "SKILL.md", os.R_OK), path
