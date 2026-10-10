"""Review result types, JSON schema and verdict validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import PurePosixPath

VALID_SEVERITIES = {"MUST-FIX", "SHOULD-FIX", "NITPICK"}
VALID_CONFIDENCES = {"high", "medium", "low"}


class ReviewErrorCategory(StrEnum):
    START_PRECONDITION = "START_PRECONDITION"
    TIMEOUT = "TIMEOUT"
    INVALID_REVIEWER_JSON = "INVALID_REVIEWER_JSON"
    CONTROL_FAILURE = "CONTROL_FAILURE"
    EXECUTION_FAILURE = "EXECUTION_FAILURE"


class CrossToolReviewError(RuntimeError):
    """Report a review boundary failure with process and mutation evidence."""

    def __init__(
        self,
        message: str,
        **details,
    ) -> None:
        super().__init__(message)
        self.category = ReviewErrorCategory(
            details.get("category", ReviewErrorCategory.CONTROL_FAILURE)
        )
        self.mutation_state = details.get("mutation_state")
        self.raw_stdout = details.get("raw_stdout")
        self.stderr_tail = details.get("stderr_tail")
        self.process_stopped = details.get("process_stopped", False)


class ReviewDirection(StrEnum):
    CLAUDE_TO_CODEX = "claude-to-codex"
    CODEX_TO_CLAUDE = "codex-to-claude"


@dataclass(frozen=True)
class ReviewFinding:
    severity: str
    file: str
    line: int
    title: str
    rationale: str
    suggested_action: str
    confidence: str


@dataclass(frozen=True)
class SecurityLens:
    finding: int | None
    checks: tuple[str, ...]
    evidence: str


@dataclass(frozen=True)
class ReviewResult:
    findings: tuple[ReviewFinding, ...]
    security_lens: SecurityLens
    preexisting_dirty: bool = False


def _invalid(message: str) -> CrossToolReviewError:
    return CrossToolReviewError(message, category=ReviewErrorCategory.INVALID_REVIEWER_JSON)


def _string(item: Mapping[str, object], key: str, label: str = "finding") -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{label}.{key} must be a non-empty string")
    return value


def _file(value: object) -> str:
    if not isinstance(value, str):
        raise _invalid("finding.file must be a string")
    if not value:
        raise _invalid("finding.file must not be empty")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise _invalid("finding.file contains control characters")
    if "\n" in value or "\r" in value or "|" in value:
        raise _invalid("finding.file contains gate-breaking characters")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise _invalid("finding.file must be repo-relative")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise _invalid("finding.file must not contain dot segments")
    return value


def _finding(item: object) -> ReviewFinding:
    if not isinstance(item, dict):
        raise _invalid("each finding must be an object")
    keys = {"severity", "file", "line", "title", "rationale", "suggested_action", "confidence"}
    if not set(item) <= keys:
        raise _invalid("review finding contains unknown keys")
    severity = _string(item, "severity")
    if severity not in VALID_SEVERITIES:
        raise _invalid(f"invalid finding.severity: {severity}")
    line = item.get("line")
    if isinstance(line, bool) or not isinstance(line, int) or line < 1:
        raise _invalid("finding.line must be a positive integer")
    confidence = _string(item, "confidence")
    if confidence not in VALID_CONFIDENCES:
        raise _invalid(f"invalid finding.confidence: {confidence}")
    return ReviewFinding(
        severity,
        _file(item.get("file")),
        line,
        _string(item, "title"),
        _string(item, "rationale"),
        _string(item, "suggested_action"),
        confidence,
    )


def _security_lens(value: object, count: int) -> SecurityLens:
    if not isinstance(value, dict):
        raise _invalid("review JSON must contain security_lens")
    if not set(value) <= {"finding", "checks", "evidence"}:
        raise _invalid("security_lens contains unknown keys")
    if "finding" not in value:
        raise _invalid("security_lens.finding must be an integer or null")
    index, checks = value["finding"], value.get("checks")
    if index is not None and (
        isinstance(index, bool) or not isinstance(index, int) or not 1 <= index <= count
    ):
        raise _invalid("security_lens.finding must index an existing finding")
    if (
        not isinstance(checks, list)
        or not checks
        or not all(isinstance(c, str) and c.strip() for c in checks)
    ):
        raise _invalid("security_lens.checks must be a non-empty list of non-empty strings")
    return SecurityLens(index, tuple(checks), _string(value, "evidence", "security_lens"))


def parse_review_json(raw: str) -> ReviewResult:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise _invalid(f"review JSON is malformed: {error.msg}") from error
    if not isinstance(payload, dict):
        raise _invalid("review JSON root must be an object")
    if not set(payload) <= {"findings", "security_lens"}:
        raise _invalid("review JSON root contains unknown keys")
    rows = payload.get("findings")
    if not isinstance(rows, list):
        raise _invalid("review JSON must contain findings list")
    findings = tuple(_finding(row) for row in rows)
    return ReviewResult(findings, _security_lens(payload.get("security_lens"), len(findings)))


def review_json_schema() -> str:
    return json.dumps(
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["findings", "security_lens"],
            "properties": {
                "security_lens": _lens_schema(),
                "findings": {"type": "array", "items": _finding_schema()},
            },
        },
        sort_keys=True,
    )


def _finding_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "severity",
            "file",
            "line",
            "title",
            "rationale",
            "suggested_action",
            "confidence",
        ],
        "properties": {
            "severity": {"type": "string", "enum": sorted(VALID_SEVERITIES)},
            "file": {"type": "string"},
            "line": {"type": "integer", "minimum": 1},
            "title": {"type": "string"},
            "rationale": {"type": "string"},
            "suggested_action": {"type": "string"},
            "confidence": {"type": "string", "enum": sorted(VALID_CONFIDENCES)},
        },
    }


def _lens_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["finding", "checks", "evidence"],
        "properties": {
            "finding": {"type": ["integer", "null"], "minimum": 1},
            "checks": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            "evidence": {"type": "string"},
        },
    }
