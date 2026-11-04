"""Commit-deny candidates reach the diff check without changing repository authority."""

import argparse
import json
import uuid

import pytest

from slopmeister.review import check
from slopmeister.review.schema import CrossToolReviewError
from slopmeister.session import launch_identity
from slopmeister.spine import candidate, candidate_cli
from tests.support.repos import git


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
    guide = tmp_path / "guide.md"
    guide.write_text("### Scenario basic: Read candidate\nInspect subject.txt.\n")
    args = argparse.Namespace(
        cwd=str(repo), guide=str(guide), subject_manifest=None, slot_target=None
    )
    return repo, frozen, args


def test_candidate_check_needs_no_commit_and_protects_every_tested_file(frozen_run):
    """A scratch file is the checker's own; an edit to a tested file is a changed subject."""
    repo, frozen, args = frozen_run
    with check.prepared(args, frozen) as prepared:
        checkout = prepared.checkout
        assert (checkout / "subject.txt").read_text() == "candidate\n"
        assert (checkout / "new.txt").read_text() == "new\n"
        assert git(repo, "branch", "--show-current").strip() == repo.name
        assert git(repo, "rev-parse", "HEAD").strip() == frozen.base
        (checkout / "scratch.txt").write_text("checker output\n")
        prepared.verify()
        for name in ("subject.txt", "new.txt"):
            original = (checkout / name).read_bytes()
            (checkout / name).write_text("checker mutation\n")
            with pytest.raises(CrossToolReviewError, match="changed the tested files"):
                prepared.verify()
            (checkout / name).write_bytes(original)
        (checkout / "new.txt").unlink()
        with pytest.raises(CrossToolReviewError, match="changed the tested files"):
            prepared.verify()
    assert not checkout.exists()


def test_candidate_status_discovers_launcher_task_state_without_manifest(frozen_run, capsys):
    repo, frozen, _ = frozen_run
    assert candidate_cli.main(["status", "--cwd", str(repo)]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["task"] == repo.name
    assert value["tree"] == frozen.tree
    assert value["scope"] == ["new.txt", "subject.txt"]
