"""Reviewer command result classification and structured parsing."""

import json
import re

from slopmeister.review.command import normalize_review_stdout
from slopmeister.review.process import CommandResult
from slopmeister.review.redact import redact
from slopmeister.review.schema import (
    CrossToolReviewError,
    ReviewDirection,
    ReviewErrorCategory,
    ReviewResult,
    parse_review_json,
)


def check_returncode(review: CommandResult) -> None:
    if not review.returncode:
        return
    # Codex puts its stdin banner on stderr and the actual cause, such as capacity, on stdout.
    detail = redact("\n".join(part for part in (review.stderr, review.stdout) if part))
    refusal = control_denial("\n".join((review.stderr, review.stdout)))
    raise CrossToolReviewError(
        f"review command failed: {detail}",
        category="CONTROL_FAILURE" if refusal else "EXECUTION_FAILURE",
        mutation_state="unchanged",
        process_stopped=review.process_stopped,
        raw_stdout=redact(review.stdout),
    )


def control_denial(text: str) -> bool:
    """Recognize evidence of an actual control refusal, not an empty metadata key."""
    for candidate in (text, *text.splitlines()):
        try:
            payload = json.loads(candidate)
        except TypeError, json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            denials = payload.get("permission_denials")
            if isinstance(denials, list) and denials:
                return True
    pattern = (
        r"permission denied|approval.{0,30}(?:required|denied)|forbidden|"
        r"unauthori[sz]ed|auth(?:entication)?\s+fail"
    )
    return bool(re.search(pattern, text, re.I))


def parse_result(direction: ReviewDirection, review: CommandResult) -> ReviewResult:
    try:
        return parse_review_json(normalize_review_stdout(direction, review.stdout))
    except CrossToolReviewError as error:
        error.raw_stdout = redact(review.stdout)
        if control_denial(review.stdout):
            error.category = ReviewErrorCategory.CONTROL_FAILURE
        error.mutation_state = "unchanged"
        error.process_stopped = review.process_stopped
        raise
