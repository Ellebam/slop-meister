"""Reviewer defaults and timeout configuration."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tomllib

from slopmeister.review.schema import CrossToolReviewError, ReviewDirection, ReviewErrorCategory

DEFAULT_CONFIG_PATH = Path(__file__).with_name("defaults.toml")
DEFAULT_COMMAND_TIMEOUT_SECONDS = 1800


@dataclass(frozen=True)
class ReviewerConfig:
    codex_model: str
    codex_effort: str
    claude_model: str
    claude_effort: str

    def for_direction(self, direction: ReviewDirection) -> tuple[str, str]:
        if direction == ReviewDirection.CODEX_TO_CLAUDE:
            return self.claude_model, self.claude_effort
        return self.codex_model, self.codex_effort


def load_config(path: Path | None = None) -> ReviewerConfig:
    source = path or DEFAULT_CONFIG_PATH
    try:
        payload = tomllib.loads(source.read_text(encoding="utf-8"))
    except OSError as error:
        raise CrossToolReviewError(
            f"reviewer config could not be read: {source}: {error}",
            category=ReviewErrorCategory.START_PRECONDITION,
        ) from error
    except tomllib.TOMLDecodeError as error:
        raise CrossToolReviewError(
            f"reviewer config is not valid TOML: {source}: {error}",
            category=ReviewErrorCategory.START_PRECONDITION,
        ) from error
    values: dict[str, str] = {}
    for section in ("codex", "claude"):
        table = payload.get(section)
        for key in ("model", "effort"):
            value = table.get(key) if isinstance(table, dict) else None
            if not isinstance(value, str) or not value.strip():
                raise CrossToolReviewError(
                    f"reviewer config {source} lacks [{section}].{key}",
                    category=ReviewErrorCategory.START_PRECONDITION,
                )
            values[f"{section}_{key}"] = value
    return ReviewerConfig(**values)


def command_timeout_seconds() -> int:
    raw = os.environ.get("CROSS_TOOL_REVIEW_TIMEOUT_SECONDS")
    if raw is None:
        return DEFAULT_COMMAND_TIMEOUT_SECONDS
    try:
        timeout = int(raw)
    except ValueError as error:
        raise CrossToolReviewError(
            "CROSS_TOOL_REVIEW_TIMEOUT_SECONDS must be an integer",
            category=ReviewErrorCategory.START_PRECONDITION,
        ) from error
    if timeout < 1:
        raise CrossToolReviewError(
            "CROSS_TOOL_REVIEW_TIMEOUT_SECONDS must be >= 1",
            category=ReviewErrorCategory.START_PRECONDITION,
        )
    return timeout
