"""A frozen session and its review copy include the companion's actual changes."""

import argparse
import json
import subprocess
import uuid

import pytest

from slopmeister import repositories
from slopmeister.review import check
from slopmeister.review.schema import CrossToolReviewError
from slopmeister.session import launch_identity
from slopmeister.session import repositories as saved
from slopmeister.spine import candidate
from tests.integration.launch.helpers import CLI, declare, launch, machine, target
from tests.support.repos import git


def prepared(tmp_path, monkeypatch):
    world = machine(tmp_path)
    declare(tmp_path / "plots", "example-app", "committed")
    sources = [target(tmp_path / name) for name in ("entry", "service", "later")]
    for repo in sources:
        (repo / "subject.txt").write_text("before\n")
        git(repo, "add", "subject.txt")
        git(repo, "commit", "-qm", "Seed subject")
    launch(
        world, str(sources[0]), "example-app", "example-app-group", "--repository", str(sources[1])
    )
    for key, value in world.env.items():
        monkeypatch.setenv(key, value)
    primary = sources[0] / ".worktrees/example-app-group"
    companion = primary / ".slopmeister-repos/service"
    for root in (primary, companion):
        (root / "subject.txt").write_text("after\n")
    return primary, companion, sources[2]


@pytest.mark.parametrize("frozen_mode", [True, False], ids=["uncommitted", "committed"])
def test_combined_review_contains_companion_and_rejects_changed_membership(
    tmp_path, monkeypatch, frozen_mode
):
    primary, companion, later = prepared(tmp_path, monkeypatch)
    if not frozen_mode:
        for root in (primary, companion):
            git(root, "add", "subject.txt")
            git(root, "commit", "-qm", "Implement fixture result")
    frozen = candidate.freeze(primary, primary.name) if frozen_mode else None
    guide = tmp_path / "guide.md"
    guide.write_text("### Scenario combined: Both inputs\nRead both subject files.\n")
    args = argparse.Namespace(
        cwd=str(primary), guide=str(guide), subject_manifest=None, slot_target=None
    )
    with check.prepared(args, frozen) as run:
        copied = run.checkout / ".slopmeister-repos/service/subject.txt"
        assert copied.read_text() == "after\n"
        assert (run.checkout / "subject.txt").read_text() == "after\n"
        run.verify()
        copied.write_text("mutated\n")
        with pytest.raises(CrossToolReviewError, match="changed the tested files"):
            run.verify()
    assert (companion / "subject.txt").read_text() == "after\n"
    repositories.add(primary, later)
    with pytest.raises(ValueError, match="membership changed"):
        candidate.load(primary, primary.name)


@pytest.mark.parametrize("selected", ["primary", "companion"])
def test_verify_commit_cli_uses_selected_member_and_checks_entire_set(
    tmp_path, monkeypatch, selected
):
    primary, companion, _ = prepared(tmp_path, monkeypatch)
    candidate.freeze(primary, primary.name)
    for root in (primary, companion):
        git(root, "add", "subject.txt")
        git(root, "commit", "-qm", "Commit proven result")
    launch_identity.write(primary, (primary.name, "claude", str(uuid.uuid4())))
    cwd = primary if selected == "primary" else companion
    commit = git(cwd, "rev-parse", "HEAD").strip()
    command = [str(CLI), "candidate", "verify-commit", "--cwd", str(cwd), "--commit", commit]
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["commit"] == commit
    assert len(json.loads(result.stdout)["members"]) == 1
    (companion / "subject.txt").write_text("different commit\n")
    git(companion, "add", "subject.txt")
    git(companion, "commit", "-qm", "Drift from candidate")
    if selected == "companion":
        explicit = subprocess.run(command, text=True, capture_output=True, timeout=30)
        assert explicit.returncode == 0, explicit.stdout + explicit.stderr
    result = subprocess.run(
        [str(CLI), "candidate", "verify-commit", "--cwd", str(primary), "--commit", "HEAD"],
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert str(companion) in result.stderr
    assert "does not match frozen candidate" in result.stderr


@pytest.mark.parametrize("changed", ["manifest", "permission", "missing-member", "symlink"])
def test_load_names_the_member_that_blocks_verification(tmp_path, monkeypatch, changed):
    primary, companion, _ = prepared(tmp_path, monkeypatch)
    frozen = candidate.freeze(primary, primary.name)
    if changed == "manifest":
        frozen.members[0].manifest.unlink()
    elif changed == "permission":
        state = saved.read(companion)
        state["shipping"] = "allow"
        saved.save(saved.state_path(companion), state)
    else:
        moved = companion.with_name("moved-service")
        companion.rename(moved)
        if changed == "symlink":
            companion.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ValueError, match=str(companion)):
        candidate.load(primary, primary.name)
