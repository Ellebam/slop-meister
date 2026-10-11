"""Directory review executes against an isolated frozen copy."""

from pathlib import Path
import subprocess

import pytest

from slopmeister.review.prompt import ReviewTarget
from slopmeister.review.run import CommandResult, run_review
from slopmeister.review.schema import CrossToolReviewError, ReviewDirection
from slopmeister.vault import subject
from tests.support.review_helpers import CLEAN_REVIEW_JSON


def _frozen_subject(tmp_path):
    candidate, evidence = tmp_path / "candidate", tmp_path / "evidence"
    candidate.mkdir()
    (candidate / "visible.md").write_text("visible\n")
    (candidate / "hidden.md").write_text("hidden\n")
    frozen = subject.freeze(candidate, [{"path": "visible.md"}], evidence / "subject.json")
    return candidate, frozen


def test_directory_review_sees_only_frozen_inputs_and_detects_copy_mutation(tmp_path):
    candidate, frozen = _frozen_subject(tmp_path)
    seen = {}

    def runner(argv, *, cwd=None, **options):
        seen["names"] = sorted(path.name for path in Path(cwd).iterdir())
        (Path(cwd) / "visible.md").write_text("mutated\n")
        return CommandResult(0, CLEAN_REVIEW_JSON)

    with pytest.raises(CrossToolReviewError, match="changed directory subject copy"):
        run_review(
            ReviewDirection.CODEX_TO_CLAUDE,
            ReviewTarget("Review.", subject_manifest=str(frozen.manifest)),
            runner=runner,
            env={},
        )
    assert seen["names"] == ["visible.md"]
    assert (candidate / "visible.md").read_text() == "visible\n"


def test_directory_review_timeout_reports_copy_mutation_without_using_git(tmp_path):
    candidate, frozen = _frozen_subject(tmp_path)

    def runner(argv, *, cwd=None, **options):
        (Path(cwd) / "visible.md").write_text("mutated\n")
        raise subprocess.TimeoutExpired(cmd=argv, timeout=600)

    with pytest.raises(CrossToolReviewError) as raised:
        run_review(
            ReviewDirection.CODEX_TO_CLAUDE,
            ReviewTarget("Review.", subject_manifest=str(frozen.manifest)),
            runner=runner,
            env={},
        )
    assert raised.value.category.value == "TIMEOUT"
    assert raised.value.mutation_state == "changed"
    assert (candidate / "visible.md").read_text() == "visible\n"
