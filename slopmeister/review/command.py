"""Reviewer command construction and output normalization."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
import json
import os
from pathlib import Path
import re
import tempfile
import tomllib

from slopmeister.review.config import load_config
from slopmeister.review.prompt import ReviewTarget, build_review_prompt
from slopmeister.review.schema import (
    CrossToolReviewError,
    ReviewDirection,
    ReviewErrorCategory,
    review_json_schema,
)


def _review_schema_file_path() -> str:
    descriptor, name = tempfile.mkstemp(prefix="cross-tool-review-schema-", suffix=".json")
    path = Path(name)
    try:
        os.chmod(path, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(review_json_schema())
    except Exception:
        with suppress(OSError):
            os.close(descriptor)
        path.unlink(missing_ok=True)
        raise
    return str(path)


def _schema_file_from_argv(argv: Sequence[str]) -> Path | None:
    try:
        index = list(argv).index("--output-schema") + 1
    except ValueError:
        return None
    if index < len(argv) and Path(argv[index]).name.startswith("cross-tool-review-schema-"):
        return Path(argv[index])
    return None


def cleanup_schema_file(argv: Sequence[str]) -> None:
    path = _schema_file_from_argv(argv)
    if path is not None:
        path.unlink(missing_ok=True)


def build_review_command(
    direction: ReviewDirection,
    target: ReviewTarget,
    **options,
) -> list[str]:
    settings = options.get("config") or load_config()
    prompt = build_review_prompt(target)
    model, effort = settings.for_direction(direction)
    if direction == ReviewDirection.CLAUDE_TO_CODEX:
        return _codex_command((model, effort), prompt, target.cwd)
    if direction == ReviewDirection.CODEX_TO_CLAUDE:
        return _claude_command((model, effort), target)
    raise CrossToolReviewError(f"unknown review direction: {direction}")


def _workspace_mcp_overrides(cwd: str) -> list[str]:
    """A write adapter refuses every parent but the workspace's interactive client, and a
    required server that fails ends the session, so the reviewer loads none of them."""
    config = Path(cwd) / ".codex/config.toml"
    if not config.is_file():
        return []
    servers = tomllib.loads(config.read_text()).get("mcp_servers", {})
    if not servers:
        return []
    # Codex refuses a server without a transport when it has not loaded an untrusted
    # workspace's file, so each entry carries a placeholder of the declared kind. The declared
    # value stays out of argv, a URL can hold credentials.
    disabled = ",".join(
        f'{json.dumps(name)}={{enabled=false,{"url" if "url" in server else "command"}="disabled"}}'
        for name, server in servers.items()
    )
    return ["--config", f"mcp_servers={{{disabled}}}"]


def _codex_command(settings: tuple[str, str], prompt: str, cwd: str) -> list[str]:
    model, effort = settings
    return [
        "codex",
        "exec",
        # The reviewer runs commands and tests like the tester; its prompt forbids changes.
        "--dangerously-bypass-approvals-and-sandbox",
        # A plugin marketplace refresh and the turn-end notify program both outlive the CLI
        # and trip the group check, and the reviewer needs neither.
        "--disable",
        "plugins",
        "--model",
        model,
        "--config",
        f"model_reasoning_effort={effort!r}",
        "--config",
        "notify=[]",
        *_workspace_mcp_overrides(cwd),
        "--ephemeral",
        "--output-schema",
        _review_schema_file_path(),
        prompt,
    ]


def _claude_command(settings: tuple[str, str], target: ReviewTarget) -> list[str]:
    model, effort = settings
    command = [
        "claude",
        "-p",
        "--model",
        model,
        "--effort",
        effort,
        "--permission-mode",
        "auto",
        "--tools",
        "Bash,Read,Grep,Glob",
        "--restricted",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--output-format",
        "json",
        "--json-schema",
        review_json_schema(),
    ]
    if target.read_dirs:
        command.extend(["--add-dir", *target.read_dirs])
    return command


def extract_review_json(raw: str) -> str:
    text = raw.strip()
    decoder = json.JSONDecoder()
    try:
        _, end = decoder.raw_decode(text)
    except json.JSONDecodeError:
        pass
    else:
        if not text[end:].strip():
            return text
    fenced = _json_candidates(
        re.finditer(r"```(?:json)?\s*(.*?)```", text, re.I | re.S), decoder, 1
    )
    if fenced:
        return fenced
    embedded = _json_candidates(re.finditer(r"{", text), decoder, 0)
    if embedded:
        return embedded
    raise CrossToolReviewError(
        "review output does not contain reviewer JSON",
        category=ReviewErrorCategory.INVALID_REVIEWER_JSON,
    )


def _json_candidates(matches, decoder: json.JSONDecoder, group: int) -> str:
    candidates = []
    for match in matches:
        candidate = match.group(group).strip() if group else match.string[match.start() :]
        try:
            payload, end = decoder.raw_decode(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and (group or "findings" in payload):
            candidates.append(candidate[:end])
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        label = "blocks" if group else "objects"
        raise CrossToolReviewError(
            f"review output contains multiple JSON {label}",
            category=ReviewErrorCategory.INVALID_REVIEWER_JSON,
        )
    return ""


def normalize_review_stdout(direction: ReviewDirection, stdout: str) -> str:
    if direction == ReviewDirection.CODEX_TO_CLAUDE:
        stdout = _claude_envelope(stdout)
    return extract_review_json(stdout)


def _claude_envelope(stdout: str) -> str:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout
    if not isinstance(payload, dict) or "findings" in payload:
        return stdout
    if payload.get("is_error") is True:
        raise CrossToolReviewError(
            "Claude reviewer returned an error envelope", category="INVALID_REVIEWER_JSON"
        )
    if "result" not in payload:
        raise CrossToolReviewError(
            "Claude reviewer envelope is missing result", category="INVALID_REVIEWER_JSON"
        )
    result = payload["result"]
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return json.dumps(result)
    raise CrossToolReviewError(
        "Claude reviewer envelope result has invalid type", category="INVALID_REVIEWER_JSON"
    )
