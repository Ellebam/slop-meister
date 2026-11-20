"""Hard-gate rendering for review results and failures."""

import re

from slopmeister.review.redact import redact, sanitize_text
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


def status(result: ReviewResult) -> str:
    """Exit 1 belongs to MUST_FIX and to any scenario short of pass, unproven is not clean."""
    outcomes = {scenario.status for scenario in result.scenarios}
    if any(finding.severity == "MUST-FIX" for finding in result.findings):
        return "MUST_FIX"
    if "fail" in outcomes:
        return "TEST_FAIL"
    if "could_not_run" in outcomes:
        return "TEST_INCOMPLETE"
    return "REVIEW" if result.findings else "CLEAN_ADVISORY"


BLOCKING = {"MUST_FIX", "TEST_FAIL", "TEST_INCOMPLETE"}


def render_hard_gate(result: ReviewResult | CrossToolReviewError) -> str:
    if isinstance(result, CrossToolReviewError):
        return _blocked_gate(result)
    suffix = " Pre-existing dirty worktree was unchanged." if result.preexisting_dirty else ""
    lines = [
        "#### Cross-Tool Review Gate",
        "",
        f"**Status:** {status(result)}{suffix if not result.findings else ''}",
        _security_lens_line(result),
    ]
    if result.findings:
        lines += [
            "",
            "| Severity | Location | Finding | Failure | Suggested action |",
            "|---|---:|---|---|---|",
            *(_finding_row(finding) for finding in result.findings),
            "",
            "**Finding evidence:**",
        ]
        for finding in result.findings:
            lines.append(f"- {sanitize_text(f'{finding.file}:{finding.line}')}")
            lines.extend(_evidence_block(path, quote) for path, quote in finding.evidence)
    else:
        lines.append("**Findings:** 0")
    if result.withheld:
        count = len(result.withheld)
        lines += [""] if result.findings else []
        lines.append(
            f"**Withheld:** {count} finding{'s' * (count != 1)} without a verified quote: "
            + sanitize_text("; ".join(result.withheld))
        )
    return "\n".join(lines + _scenario_lines(result))


def _scenario_lines(result: ReviewResult) -> list[str]:
    if not result.scenarios:
        return []
    counts = {name: 0 for name in ("pass", "fail", "could_not_run")}
    for scenario in result.scenarios:
        counts[scenario.status] += 1
    summary = ", ".join(f"{count} {name.replace('_', ' ')}" for name, count in counts.items())
    lines = ["", f"**Scenarios:** {summary}"]
    for scenario in result.scenarios:
        reason = f" - {sanitize_text(scenario.reason)}" if scenario.reason.strip() else ""
        label = scenario.status.replace("_", " ")
        lines.append(f"- {sanitize_text(scenario.id)}: {label}{reason}")
        lines.extend(_evidence_block(path, quote) for path, quote in scenario.evidence)
    if result.guide_findings:
        lines += ["", "**Guide findings:**"]
        lines += [f"- {sanitize_text(s)}: {sanitize_text(p)}" for s, p in result.guide_findings]
    return lines


def _evidence_block(path: str, quote: str) -> str:
    """A fence longer than any backtick run, so a quoted line stays inside its block.

    Every quoted line carries the list item's indent, an unindented line would end the item
    and its fence, and the rest of the quote would render as live Markdown.
    """
    text = "".join(c if c.isprintable() or c in "\n\t" else " " for c in redact(quote))
    fence = "`" * max(3, 1 + max((len(run) for run in re.findall(r"`+", text)), default=0))
    body = "\n".join(f"  {line}" for line in text.split("\n"))
    return f"  Evidence: {sanitize_text(path)}\n\n  {fence}text\n{body}\n  {fence}"


def _finding_row(finding) -> str:
    values = [
        finding.severity,
        f"{finding.file}:{finding.line}",
        finding.title,
        finding.failure,
        finding.suggested_action,
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
            "Correct the named start condition, such as an argument, an input file or the "
            "reviewer CLI, then run the standalone review again."
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
