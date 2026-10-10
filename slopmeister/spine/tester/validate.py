"""The tester verdict contract: guide scenarios, native identity, quoted evidence and report."""

from collections.abc import Sequence
import json
from pathlib import Path
import re

from slopmeister.review.redact import redact
from slopmeister.review.redact import sanitize_text as _sanitize_text

SCENARIO = re.compile(r"^### Scenario ([a-z0-9][a-z0-9_-]*): .+$", re.M)
VERDICTS = {"pass", "fail", "blocked"}
_EVIDENCE = {
    "type": "object",
    "additionalProperties": False,
    "required": ["path", "quote"],
    "properties": {"path": {"type": "string"}, "quote": {"type": "string"}},
}
_SCENARIO = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "verdict", "evidence"],
    "properties": {
        "id": {"type": "string"},
        "verdict": {"enum": ["pass", "fail", "blocked"]},
        "evidence": {"type": "array", "minItems": 1, "items": _EVIDENCE},
    },
}
_REGRESSION = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "bug", "evidence"],
    "properties": {
        "name": {"type": "string"},
        "bug": {"type": "string"},
        "evidence": {"type": "string"},
    },
}
VERDICT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["scenarios", "regressions"],
    "properties": {
        "scenarios": {"type": "array", "items": _SCENARIO},
        "regressions": {"type": "array", "items": _REGRESSION},
    },
}


def scenario_ids(text: str) -> list[str]:
    ids = SCENARIO.findall(text)
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("guide needs unique '### Scenario <id>: <title>' headings")
    return ids


def native_identity(path: Path, tool: str) -> tuple[str, str]:
    models, efforts = set(), set()
    for line in path.read_bytes().split(b"\n"):
        if not line.strip():
            continue
        identity = _identity(json.loads(line), tool)
        if identity is None:
            continue
        model, effort = identity
        if model:
            models.add(model)
        if effort:
            efforts.add(effort)
    if len(models) != 1 or len(efforts) != 1:
        raise ValueError("native record does not establish one model and effort")
    return models.pop(), efforts.pop()


def _identity(record: dict, tool: str) -> tuple[str | None, str | None] | None:
    if tool == "codex" and record.get("type") == "turn_context":
        context = record.get("payload", {})
        return context.get("model"), context.get("effort") or context.get("reasoning_effort")
    if tool == "claude":
        message = record.get("message")
        model = message.get("model") if isinstance(message, dict) else None
        return (model if model != "<synthetic>" else None), record.get("effort")
    return None


def validate_verdict(verdict: dict, required: list[str], root: Path) -> str:
    keys = {"scenarios", "regressions"}
    if not isinstance(verdict, dict) or set(verdict) != keys:
        raise ValueError("invalid tester verdict shape")
    scenarios = verdict["scenarios"]
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("tester omitted scenarios")
    seen, outcomes = set(), set()
    for position, row in enumerate(scenarios, 1):
        _scenario(row, seen)
        # A row the tester added is a regression candidate at most, it never decides the run.
        if row["id"] in required:
            outcomes.add(row["verdict"])
        for index, item in enumerate(row["evidence"], 1):
            _citation(item, f"scenario {position}, evidence {index}: ", root)
    if not set(required).issubset(seen):
        raise ValueError("tester omitted required scenarios")
    _regressions(verdict["regressions"])
    if not outcomes:
        # Nothing required was graded, so nothing may pass.
        raise ValueError("run names no required scenario")
    return "fail" if "fail" in outcomes else "blocked" if "blocked" in outcomes else "pass"


def _scenario(row: object, seen: set[str]) -> None:
    if not isinstance(row, dict) or set(row) != {"id", "verdict", "evidence"}:
        raise ValueError("invalid scenario shape")
    verdict = row["verdict"]
    if (
        not isinstance(row["id"], str)
        or row["id"] in seen
        or not isinstance(verdict, str)
        or verdict not in VERDICTS
    ):
        raise ValueError("duplicate scenario or unsupported verdict")
    seen.add(row["id"])
    if not isinstance(row["evidence"], list) or not row["evidence"]:
        raise ValueError("scenario lacks quoted evidence")


def _citation(item: object, location: str, root: Path) -> None:
    if not isinstance(item, dict) or set(item) != {"path", "quote"}:
        raise ValueError(location + "invalid evidence reference")
    path, quote = item["path"], item["quote"]
    if not isinstance(path, str) or not isinstance(quote, str) or not quote.strip():
        raise ValueError(location + "invalid evidence path or quote")
    evidence, resolved = root / "evidence", (root / path).resolve()
    if (
        evidence.is_symlink()
        or not resolved.is_relative_to(evidence.resolve())
        or not resolved.is_file()
        or resolved == evidence.resolve() / "draft.json"
    ):
        # The guide, the run records and the draft hold expected or claimed text, not output.
        raise ValueError(
            location + "evidence must be a saved file under evidence/, not the draft; "
            "copy the quoted file into evidence/"
        )
    if quote not in resolved.read_text(errors="replace"):
        raise ValueError(location + "evidence quote is absent from its file")


def _regressions(candidates: object) -> None:
    if not isinstance(candidates, list):
        raise ValueError("invalid regression candidates")
    for candidate in candidates:
        if (
            not isinstance(candidate, dict)
            or set(candidate) != {"name", "bug", "evidence"}
            or not all(isinstance(x, str) and x.strip() for x in candidate.values())
        ):
            raise ValueError("invalid regression candidate")


def render_report(verdict: dict, required: Sequence[str] | None = None) -> str:
    lines = ["Tester report", ""]
    for row in verdict["scenarios"]:
        counted = required is None or row["id"] in required
        note = "" if counted else ", added by the tester, not counted"
        lines.append(f"- {_sanitize_text(row['id'])}: {row['verdict']}{note}")
        lines.extend(_evidence_block(item) for item in row["evidence"])
    lines.append("")
    lines.extend(
        f"Regression candidate {_sanitize_text(r['name'])}: {_sanitize_text(r['bug'])} "
        f"Evidence: {_sanitize_text(r['evidence'])}"
        for r in verdict["regressions"]
    )
    return redact("\n".join(lines)) + "\n"


def _evidence_block(item: dict) -> str:
    """A fence longer than any backtick run, so quoted Markdown stays inside its block."""
    longest = max((len(run) for run in re.findall(r"`+", item["quote"])), default=0)
    fence = "`" * max(3, 1 + longest)
    path = _sanitize_text(item["path"])
    return f"  Evidence: {path}\n\n  {fence}text\n{item['quote']}\n  {fence}"


def check_draft(root: Path, draft: Path) -> str:
    """The outcome of a valid draft, never test proof; the run stays byte-identical."""
    if not draft.is_relative_to(root):
        raise ValueError("draft escapes the run")
    run = json.loads((root / "run.json").read_text())
    required = run.get("required") if isinstance(run, dict) else None
    if not isinstance(required, list) or not all(isinstance(x, str) for x in required):
        raise ValueError("invalid required scenario metadata")
    return validate_verdict(json.loads(draft.read_text()), required, root)
