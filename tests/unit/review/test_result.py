"""Reviewer failure classification without any process."""

import pytest

from slopmeister.review.process import CommandResult
from slopmeister.review.prompt import ReviewTarget
from slopmeister.review.result import check_returncode, withhold_unverified
from slopmeister.review.schema import (
    CrossToolReviewError,
    ReviewFinding,
    ReviewResult,
    SecurityLens,
)


def test_failure_detail_names_a_cause_reported_only_on_stdout():
    """Escaping bug: the gate showed Codex's stdin banner and hid a model capacity failure."""
    review = CommandResult(
        1,
        stdout='{"type":"error","message":"Selected model is at capacity"}',
        stderr="Reading additional input from stdin...",
    )
    with pytest.raises(CrossToolReviewError) as raised:
        check_returncode(review)
    assert "Selected model is at capacity" in raised.value.stderr_tail[-1]


def test_failure_detail_masks_secrets_from_both_channels():
    """Escaping bug: adding stdout to the failure detail leaked credentials into the gate."""
    review = CommandResult(
        1,
        stdout="OPENAI_API_KEY=private-stdout-value",
        stderr="GITHUB_TOKEN=private-stderr-value",
    )
    with pytest.raises(CrossToolReviewError) as raised:
        check_returncode(review)
    shown = str(raised.value) + "\n".join(raised.value.stderr_tail)
    assert "OPENAI_API_KEY" in shown and "GITHUB_TOKEN" in shown
    assert "private-stdout-value" not in shown and "private-stderr-value" not in shown


def _finding(file: str, path: str, quote: str = "guard()") -> ReviewFinding:
    return ReviewFinding("MUST-FIX", file, 1, "t", "f", ((path, quote),), "a")


@pytest.fixture
def review(tmp_path):
    """A review root, a read directory and a check run root, each holding one quotable file."""
    root, outside, run = tmp_path / "repo", tmp_path / "notes", tmp_path / "run"
    for directory in (root, outside, run / "evidence"):
        directory.mkdir(parents=True)
    (root / "a.py").write_text("guard()\n")
    (outside / "plan.md").write_text("guard()\n")
    (run / "evidence" / "test.out").write_text("guard()\n")
    (tmp_path / "secret.txt").write_text("guard()\n")
    (root / "link.py").symlink_to(tmp_path / "secret.txt")
    return root, outside, run


def test_only_quotes_inside_the_reviewed_directories_reach_the_worker(review):
    """Reviewer output is untrusted: a quote from a file outside the given roots proves nothing."""
    root, outside, run = review
    findings = (
        _finding("a.py", "a.py"),
        _finding("a.py", str(outside / "plan.md")),
        _finding("a.py", str(run / "evidence" / "test.out")),
        _finding("a.py", "../secret.txt"),
        _finding("a.py", "link.py"),
        _finding("b.py", "a.py", "cleanup()"),
    )
    target = ReviewTarget("Review.", str(root), (str(outside),), check_root=str(run))
    result = withhold_unverified(ReviewResult(findings, SecurityLens(None, ("x",), "e")), target)
    assert result.findings == findings[:3]
    assert result.withheld == (
        "a.py:1 (../secret.txt is not a file in the reviewed directories)",
        "a.py:1 (link.py is not a file in the reviewed directories)",
        "b.py:1 (quote is absent from a.py)",
    )


def test_the_security_lens_finding_is_never_withheld_and_keeps_its_index(review):
    """A security defect with a sloppy quote still reaches the worker, at its renumbered row."""
    root, _, _ = review
    findings = (_finding("x.py", "a.py", "absent"), _finding("y.py", "a.py", "absent"))
    target = ReviewTarget("Review.", str(root))
    lens = SecurityLens(2, ("x",), "e")
    result = withhold_unverified(ReviewResult(findings, lens), target)
    assert result.findings == findings[1:]
    assert result.security_lens.finding == 1
    assert result.withheld == ("x.py:1 (quote is absent from a.py)",)


def test_a_symlinked_evidence_directory_verifies_nothing(review, tmp_path):
    """The checker writes its run root, so an evidence link to / would verify any quote."""
    root, _, run = review
    linked = tmp_path / "linked"
    (linked / "evidence").parent.mkdir()
    (linked / "evidence").symlink_to(tmp_path, target_is_directory=True)
    finding = _finding("a.py", str(tmp_path / "secret.txt"))
    target = ReviewTarget("Review.", str(root), check_root=str(linked))
    result = withhold_unverified(ReviewResult((finding,), SecurityLens(None, ("x",), "e")), target)
    assert result.findings == ()
    assert result.withheld == (
        f"a.py:1 ({tmp_path / 'secret.txt'} is not a file in the reviewed directories)",
    )
