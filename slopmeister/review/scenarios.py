"""The diff check's guide scenarios: their IDs and the grading of the checker's reported results."""

import json
from pathlib import Path
import re

from slopmeister.review.schema import (
    SCENARIO_STATUSES,
    CrossToolReviewError,
    ReviewErrorCategory,
    ReviewResult,
    Scenario,
)

HEADING = re.compile(r"^### Scenario ([a-z0-9][a-z0-9_-]*): .+$", re.M)


def scenario_ids(text: str) -> tuple[str, ...]:
    ids = HEADING.findall(text)
    if not ids or len(ids) != len(set(ids)):
        raise CrossToolReviewError(
            "the test guide needs unique '### Scenario <id>: <title>' headings",
            category=ReviewErrorCategory.START_PRECONDITION,
        )
    return tuple(ids)


def _invalid(message: str) -> CrossToolReviewError:
    return CrossToolReviewError(message, category=ReviewErrorCategory.INVALID_REVIEWER_JSON)


def _strings(item: object, keys: set[str], label: str) -> dict:
    if not isinstance(item, dict) or set(item) != keys:
        raise _invalid(f"invalid {label} shape")
    if not all(isinstance(item[key], str) for key in keys - {"evidence"}):
        raise _invalid(f"invalid {label} values")
    return item


def grade(result: ReviewResult, raw: str, required: tuple[str, ...], root: Path) -> ReviewResult:
    """Every required scenario gets exactly one status. Unproven claims become could_not_run."""
    payload = json.loads(raw)
    rows, findings = payload.get("scenarios"), payload.get("guide_findings")
    if not isinstance(rows, list) or not isinstance(findings, list):
        raise _invalid("the check result needs scenarios and guide_findings lists")
    reported: dict[str, list[dict]] = {}
    for row in rows:
        row = _strings(row, {"id", "status", "reason", "evidence"}, "scenario")
        if row["status"] not in SCENARIO_STATUSES or not isinstance(row["evidence"], list):
            raise _invalid("invalid scenario status or evidence")
        reported.setdefault(row["id"], []).append(row)
    guide = tuple(
        (item["scenario"], item["problem"])
        for item in (_strings(f, {"scenario", "problem"}, "guide finding") for f in findings)
    )
    graded = tuple(_scenario(name, reported.get(name, []), root) for name in required)
    return ReviewResult(
        result.findings, result.security_lens, result.preexisting_dirty, graded, guide
    )


def _scenario(name: str, rows: list[dict], root: Path) -> Scenario:
    if len(rows) != 1:
        count = "did not report" if not rows else "reported more than once"
        return Scenario(name, "could_not_run", f"the checker {count} this scenario", ())
    row = rows[0]
    evidence = tuple(_strings(e, {"path", "quote"}, "evidence") for e in row["evidence"])
    cited = tuple((item["path"], item["quote"]) for item in evidence)
    reason = row["reason"].strip()
    if row["status"] == "could_not_run":
        return Scenario(name, "could_not_run", reason or "no reason given", cited)
    # A pass or fail counts only with quotes found in files the checker saved.
    problems = [problem for item in cited if (problem := _citation(item, root))]
    if not cited or problems:
        detail = "; ".join(problems) or "no evidence quoted"
        claimed = f"reported {row['status']}, evidence not verified: {detail}"
        return Scenario(name, "could_not_run", claimed, cited)
    return Scenario(name, row["status"], reason, cited)


def _citation(item: tuple[str, str], root: Path) -> str:
    path, quote = item
    evidence = root / "evidence"
    if not quote.strip():
        return f"empty quote from {path}"
    try:
        resolved = (root / path).resolve()
        saved = (
            not evidence.is_symlink()
            and resolved.is_relative_to(evidence.resolve())
            and resolved.is_file()
        )
        if not saved:
            problem = f"{path} is not a saved file under evidence/"
        elif quote not in resolved.read_text(errors="replace"):
            problem = f"quote is absent from {path}"
        else:
            problem = ""
    except (OSError, ValueError) as error:
        problem = f"{path} is unreadable: {error}"
    return problem
