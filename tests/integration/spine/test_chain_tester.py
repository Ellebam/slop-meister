"""Every tester invocation is a fresh isolated run with its own collection path."""

import argparse
import json
import os
from pathlib import Path
import subprocess

import pytest

from slopmeister.spine.tester import collect, launch, runs
from tests.support.repos import git

GUIDE = "### Scenario basic: Read subject\nExpect original.\n"
ORIGINAL_POPEN = subprocess.Popen


@pytest.fixture
def subject(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "subject"
    repo.mkdir()
    git(repo, "init", "-qb", "task-241")
    (repo / "subject.py").write_text("print('original')\n")
    git(repo, "add", "subject.py")
    git(repo, "commit", "-qm", "Fixture")
    notes = repo / "TASK-NOTES.md"
    notes.write_text("## Plan\nKeep behavior.\n\n## Validation\nObserved local proof.\n")
    guide = tmp_path / "guide.md"
    guide.write_text(GUIDE)
    return repo, notes, guide


def arguments(subject: tuple[Path, Path, Path]) -> argparse.Namespace:
    repo, notes, guide = subject
    return argparse.Namespace(
        cwd=str(repo),
        task="fixture",
        worker_tool="codex",
        tester_tool=None,
        tester_model=None,
        commit="HEAD",
        guide=str(guide),
        validation=str(notes),
        subject_manifest=None,
    )


@pytest.mark.parametrize("changed", [False, True], ids=["identical", "changed"])
def test_repeated_launches_create_distinct_collectable_runs(
    subject, tmp_path, monkeypatch, capsys, changed
):
    state = tmp_path / "tester-state"
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    starts = []

    def start(command, **kwargs):
        if command[0] == "git":
            return ORIGINAL_POPEN(command, **kwargs)
        root = Path(command[-1])
        assert (root / "checkout/subject.py").is_file()
        runs.save(root / "accepted.json", {"supervisor_pid": os.getpid()})
        starts.append(root)

    monkeypatch.setattr(subprocess, "Popen", start)
    first = launch.launch(arguments(subject))
    if changed:
        subject[1].write_text("## Plan\nKeep behavior.\n\n## Validation\nChanged proof.\n")
    second = launch.launch(arguments(subject))

    assert first != second
    assert starts == [first, second]
    assert collect.collect(first, 0) == collect.collect(second, 0) == 3
    capsys.readouterr()
    assert json.loads((first / "run.json").read_text())["status"] == "prepared"
    assert json.loads((second / "run.json").read_text())["status"] == "prepared"
    assert not (state / "slopmeister/spine-tests/admissions").exists()
