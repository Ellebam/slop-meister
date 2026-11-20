"""Reviewer command result classification and structured parsing."""

from dataclasses import replace
import json
from pathlib import Path

from slopmeister.review.command import normalize_review_stdout
from slopmeister.review.process import CommandResult, stderr_tail
from slopmeister.review.prompt import ReviewTarget
from slopmeister.review.redact import redact
from slopmeister.review.scenarios import grade, quote_problem
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
    # Codex puts its stdin banner on stderr and the actual cause, such as capacity, on stdout,
    # so the bounded tail the CLI prints before the gate ends with stdout.
    output = "\n".join((review.stderr, review.stdout))
    raise CrossToolReviewError(
        f"review command failed with exit code {review.returncode}, "
        "the last output lines are printed before this gate",
        # Each stream alone, because a banner before formatted JSON stops the joined text parsing.
        category="CONTROL_FAILURE"
        if control_denial(review.stdout) or control_denial(review.stderr)
        else "EXECUTION_FAILURE",
        mutation_state="unchanged",
        process_stopped=review.process_stopped,
        raw_stdout=redact(review.stdout),
        stderr_tail=stderr_tail(output),
    )


def control_denial(text: str) -> bool:
    """Recognize evidence of an actual control refusal, not an empty metadata key. Words such as
    "forbidden" stay out, because reviewer prose and command output carry them too."""
    for candidate in (text, *text.splitlines()):
        try:
            payload = json.loads(candidate)
        except TypeError, json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            denials = payload.get("permission_denials")
            if isinstance(denials, list) and denials:
                return True
    return False


def parse_result(
    direction: ReviewDirection, review: CommandResult, target: ReviewTarget, check=None
) -> ReviewResult:
    """A check's result also grades every guide scenario against the evidence it saved."""
    try:
        raw = normalize_review_stdout(direction, review.stdout)
        result = parse_review_json(raw, check is not None)
        result = grade(result, raw, check.scenarios, check.root) if check else result
        return withhold_unverified(result, target)
    except CrossToolReviewError as error:
        error.raw_stdout = redact(review.stdout)
        if control_denial(review.stdout):
            error.category = ReviewErrorCategory.CONTROL_FAILURE
        error.mutation_state = "unchanged"
        error.process_stopped = review.process_stopped
        raise


def withhold_unverified(result: ReviewResult, target: ReviewTarget) -> ReviewResult:
    """Keep a finding only when every quote is in its cited file, so no invented claim reaches
    the worker. The Security Lens finding stays regardless, because a security defect is never
    set aside."""
    base = Path(target.cwd).resolve()
    roots = (base, *map(Path, target.read_dirs))
    if target.check_root and not (evidence := Path(target.check_root) / "evidence").is_symlink():
        roots += (evidence,)
    lens = result.security_lens
    kept, withheld, index = [], [], None
    for number, finding in enumerate(result.findings, 1):
        problems = [p for item in finding.evidence if (p := quote_problem(item, base, roots))]
        if problems and number != lens.finding:
            withheld.append(f"{finding.file}:{finding.line} ({'; '.join(problems)})")
            continue
        kept.append(finding)
        index = len(kept) if number == lens.finding else index
    return replace(
        result,
        findings=tuple(kept),
        security_lens=replace(lens, finding=index),
        withheld=tuple(withheld),
    )
