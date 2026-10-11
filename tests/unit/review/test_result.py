"""Reviewer failure classification without any process."""

import pytest

from slopmeister.review.process import CommandResult
from slopmeister.review.result import check_returncode
from slopmeister.review.schema import CrossToolReviewError


def test_failure_detail_names_a_cause_reported_only_on_stdout():
    """Escaping bug: the gate showed Codex's stdin banner and hid a model capacity failure."""
    review = CommandResult(
        1,
        stdout='{"type":"error","message":"Selected model is at capacity"}',
        stderr="Reading additional input from stdin...",
    )
    with pytest.raises(CrossToolReviewError, match="Selected model is at capacity"):
        check_returncode(review)


def test_failure_detail_masks_secrets_from_both_channels():
    """Escaping bug: adding stdout to the failure detail leaked credentials into the gate."""
    review = CommandResult(
        1,
        stdout="OPENAI_API_KEY=private-stdout-value",
        stderr="GITHUB_TOKEN=private-stderr-value",
    )
    with pytest.raises(CrossToolReviewError) as raised:
        check_returncode(review)
    assert "private-stdout-value" not in str(raised.value)
    assert "private-stderr-value" not in str(raised.value)
