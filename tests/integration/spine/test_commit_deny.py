"""Commit-deny candidates reach the existing tester without changing repository authority."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import uuid

import pytest

from slopmeister.session import launch_identity
from slopmeister.spine import candidate, candidate_cli
from slopmeister.spine.tester import launch, runs
from slopmeister.spine.tester.supervise import _verify_subject
from tests.support.repos import git

ORIGINAL_POPEN = subprocess.Popen


def repository(tmp_path):
    repo = tmp_path / "task-267"
    repo.mkdir()
    git(repo, "init", "-qb", repo.name)
    (repo / "subject.txt").write_text("base\n")
    git(repo, "add", "subject.txt")
    git(repo, "commit", "-qm", "Create fixture")
    (repo / "subject.txt").write_text("candidate\n")
    (repo / "new.txt").write_text("new\n")
    return repo


def request(tmp_path, repo):
    guide, notes = tmp_path / "guide.md", tmp_path / "notes.md"
    guide.write_text("### Scenario basic: Read candidate\nInspect subject.txt.\n")
    notes.write_text("Notes\n\n## Validation\nScenario basic is required.\n")
    defaults = tmp_path / "defaults.toml"
    defaults.write_text('[claude]\nmodel="fake-model"\neffort="high"\n')
    return defaults, argparse.Namespace(
        cwd=str(repo), commit=None, candidate=True, subject_manifest=None,
        guide=str(guide), validation=str(notes), worker_tool="codex",
        tester_tool=None, tester_model=None, task=repo.name,
    )  # fmt: skip


@pytest.fixture
def frozen_run(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    session = str(uuid.uuid4())
    monkeypatch.setenv("CODEX_THREAD_ID", session)
    launch_identity.write(repo, (repo.name, "codex", session))
    frozen = candidate.freeze(repo, repo.name)
    defaults, args = request(tmp_path, repo)
    monkeypatch.setattr(launch, "DEFAULTS", defaults)
    return repo, frozen, args


def test_commit_deny_candidate_reaches_tester_without_commit_or_live_checkout_dependency(
    frozen_run, monkeypatch
):
    repo, frozen, args = frozen_run
    starts = []

    def start(command, **kwargs):
        if command[0] == "git":
            return ORIGINAL_POPEN(command, **kwargs)
        root = Path(command[-1])
        assert (root / "checkout/subject.txt").read_text() == "candidate\n"
        assert (root / "checkout/new.txt").read_text() == "new\n"
        runs.save(root / "accepted.json", {"supervisor_pid": os.getpid()})
        starts.append(root)

    monkeypatch.setattr(subprocess, "Popen", start)
    root = launch.launch(args)
    run = json.loads((root / "run.json").read_text())

    assert starts == [root]
    assert run["candidate_tree"] == frozen.tree
    assert run["candidate_base"] == frozen.base
    assert run["commit"] == "candidate:" + frozen.tree
    assert git(repo, "branch", "--show-current").strip() == repo.name
    assert git(repo, "rev-parse", "HEAD").strip() == frozen.base
    _assert_subject_rule(run, ("subject.txt", "new.txt"))


def _assert_subject_rule(run: dict, tested: tuple[str, ...]) -> None:
    """A scratch file is the tester's own; an edit to a tested file is a changed subject."""
    checkout = Path(run["checkout"])
    _verify_subject(run)
    (checkout / "scratch.txt").write_text("tester output\n")
    _verify_subject(run)
    for name in tested:
        original = (checkout / name).read_bytes()
        (checkout / name).write_text("tester mutation\n")
        with pytest.raises(ValueError, match="tester changed the tested commit or files"):
            _verify_subject(run)
        (checkout / name).write_bytes(original)
    _verify_subject(run)
    (checkout / tested[0]).unlink()
    with pytest.raises(ValueError, match="tester changed the tested commit or files"):
        _verify_subject(run)


def test_commit_subject_allows_new_files_and_refuses_tracked_edits(tmp_path):
    repo = repository(tmp_path)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "Commit candidate")
    run = {"checkout": str(repo), "commit": git(repo, "rev-parse", "HEAD").strip()}
    _assert_subject_rule(run, ("subject.txt",))


def test_candidate_route_requires_launcher_task_and_explicit_flag(frozen_run, monkeypatch):
    _, _, args = frozen_run
    args.task = "other-task"
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("tester started"))
    with pytest.raises(ValueError, match="tester task differs from launcher task"):
        launch.launch(args)
    args.task = "task-267"
    args.candidate = False
    with pytest.raises(ValueError, match="repository testing requires both --cwd and --commit"):
        launch.launch(args)


def test_candidate_status_discovers_launcher_task_state_without_manifest(frozen_run, capsys):
    repo, frozen, _ = frozen_run
    assert candidate_cli.main(["status", "--cwd", str(repo)]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["task"] == repo.name
    assert value["tree"] == frozen.tree
    assert value["scope"] == ["new.txt", "subject.txt"]
