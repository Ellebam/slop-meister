"""The reviewer change check compares what the work tree holds, not its status text."""

from pathlib import Path

import pytest

from slopmeister.review.prompt import ReviewTarget
from slopmeister.review.run import CommandResult, run_review
from slopmeister.review.schema import CrossToolReviewError, ReviewDirection
from tests.support.repos import git, scratch_repo
from tests.support.review_helpers import CLEAN_REVIEW_JSON


def _dirty_repo(tmp_path: Path) -> Path:
    """A repository with one modified tracked file and one untracked folder."""
    repo = scratch_repo(tmp_path / "reviewed")
    (repo / "README.md").write_text("worker edit\n")
    (repo / "drafts").mkdir()
    (repo / "drafts/plan.md").write_text("worker plan\n")
    return repo


def _review_with(repo: Path, reviewer_action) -> object:
    def reviewer(argv, **options):
        reviewer_action()
        return CommandResult(0, CLEAN_REVIEW_JSON)

    target = ReviewTarget(prompt="Review.", cwd=str(repo))
    return run_review(ReviewDirection.CODEX_TO_CLAUDE, target, runner=reviewer, env={})


@pytest.mark.parametrize(
    "path, text",
    [
        pytest.param("README.md", "reviewer edit\n", id="already-modified-file"),
        pytest.param("drafts/added.md", "reviewer file\n", id="already-untracked-folder"),
    ],
)
def test_reviewer_change_that_leaves_status_text_equal_blocks_the_gate(tmp_path, path, text):
    """Escaping bug: `git status --porcelain` prints the same lines before and after both edits."""
    repo = _dirty_repo(tmp_path)
    before = git(repo, "status", "--porcelain")
    with pytest.raises(CrossToolReviewError, match="reviewer changed the worktree"):
        _review_with(repo, lambda: (repo / path).write_text(text))
    assert git(repo, "status", "--porcelain") == before


def test_unchanged_worktree_reports_whether_it_was_already_dirty(tmp_path):
    repo = _dirty_repo(tmp_path)
    assert _review_with(repo, lambda: None).preexisting_dirty is True
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "Commit worker edits")
    assert _review_with(repo, lambda: None).preexisting_dirty is False


@pytest.mark.parametrize("change, state", [(False, "unchanged"), (True, "changed")])
def test_timeout_assessment_sees_an_edit_to_an_already_modified_file(tmp_path, change, state):
    repo = _dirty_repo(tmp_path)

    def reviewer():
        if change:
            (repo / "README.md").write_text("reviewer edit\n")
        raise CrossToolReviewError("reviewer timed out", category="TIMEOUT")

    with pytest.raises(CrossToolReviewError) as raised:
        _review_with(repo, reviewer)
    assert raised.value.mutation_state == state
