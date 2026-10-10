"""Hard-gate rendering for review results and failures."""

from slopmeister.review.redact import sanitize_text
from slopmeister.review.schema import CrossToolReviewError, ReviewErrorCategory, ReviewResult


def _security_lens_line(result: ReviewResult) -> str:
    lens = result.security_lens
    if lens.finding is None:
        verdict = "verified clean"
    else:
        finding = result.findings[lens.finding - 1]
        verdict = f"finding {finding.file}:{finding.line} {finding.severity}"
    return "**Security Lens:** " + sanitize_text(
        f"{verdict}, checks: {', '.join(lens.checks)}, evidence: {lens.evidence}"
    )


def render_hard_gate(result: ReviewResult | CrossToolReviewError) -> str:
    if isinstance(result, CrossToolReviewError):
        return _blocked_gate(result)
    if not result.findings:
        suffix = " Pre-existing dirty worktree was unchanged." if result.preexisting_dirty else ""
        return "\n".join(
            [
                "#### Cross-Tool Review Gate",
                "",
                f"**Status:** CLEAN_ADVISORY{suffix}",
                _security_lens_line(result),
                "**Findings:** 0",
            ]
        )
    return _findings_gate(result)


def _findings_gate(result: ReviewResult) -> str:
    status = (
        "MUST_FIX"
        if any(finding.severity == "MUST-FIX" for finding in result.findings)
        else "REVIEW"
    )
    lines = [
        "#### Cross-Tool Review Gate",
        "",
        f"**Status:** {status}",
        _security_lens_line(result),
        "",
        "| Severity | Location | Finding | Suggested action | Confidence |",
        "|---|---:|---|---|---|",
    ]
    lines.extend(_finding_row(finding) for finding in result.findings)
    return "\n".join(lines)


def _finding_row(finding) -> str:
    values = [
        finding.severity,
        f"{finding.file}:{finding.line}",
        f"{finding.title} - {finding.rationale}",
        finding.suggested_action,
        finding.confidence,
    ]
    return "| " + " | ".join(sanitize_text(value) for value in values) + " |"


def _blocked_gate(error: CrossToolReviewError) -> str:
    lines = [
        "#### Cross-Tool Review Gate",
        "",
        "**Status:** BLOCKED",
        f"**Category:** `{error.category.value}`",
        f"**Reason:** {sanitize_text(str(error))}",
    ]
    if error.mutation_state is not None:
        lines.append(f"**Mutation assessment:** `{error.mutation_state}`")
    lines.extend(_blocked_options(error))
    return "\n".join(lines)


def _blocked_options(error: CrossToolReviewError) -> list[str]:
    actions = {
        ReviewErrorCategory.START_PRECONDITION: (
            "Install or repair the required reviewer CLI/control surface, then run the "
            "standalone review again."
        ),
        ReviewErrorCategory.TIMEOUT: (
            "Inspect the timeout state and mutation assessment before deciding whether to "
            "run a new review."
        ),
        ReviewErrorCategory.INVALID_REVIEWER_JSON: (
            "Fix the reviewer output or schema contract before running a new review."
        ),
        ReviewErrorCategory.CONTROL_FAILURE: (
            "Inspect the failed control and restore the read-only review boundary before "
            "running a new review."
        ),
        ReviewErrorCategory.EXECUTION_FAILURE: (
            "Inspect the failed reviewer execution and its persisted attempt evidence."
        ),
    }
    return [
        "",
        "| Option | Consequence |",
        "|---|---|",
        f"| Resolve cause (Recommended) | {actions[error.category]} |",
        "| Stop and re-plan | Return to the orchestrator because the review boundary "
        "is not trustworthy. |",
    ]
