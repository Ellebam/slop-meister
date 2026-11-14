"""Normalized usage records, with absence kept separate from zero."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import cast


def mapping(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def number(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def label(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def stamp(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def total(values: list[int | None]) -> int | None:
    return sum(cast(list[int], values)) if values and None not in values else None


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime

    def contains(self, timestamp: datetime | None) -> bool:
        return timestamp is not None and self.start <= timestamp < self.end

    def week(self, timestamp: datetime) -> str:
        return f"W{(timestamp - self.start).days // 7 + 1}"


@dataclass
class Request:
    timestamp: datetime | None
    context: int | None
    output: int | None
    model: str | None
    after_compaction: bool = False
    identity_known: bool = True


@dataclass
class Compaction:
    timestamp: datetime | None
    before: int | None
    after: int | None


@dataclass(frozen=True)
class ToolEvent:
    timestamp: datetime | None
    name: str
    target: str | None
    notes: bool = False


@dataclass
class Session:
    client: str
    cwd: str | None = None
    role: str | None = None
    requests: list[Request] = field(default_factory=list)
    compactions: list[Compaction] = field(default_factory=list)
    limit_hits: list[datetime | None] = field(default_factory=list)
    malformed: int = 0
    unsupported: int = 0
    tools: list[ToolEvent] = field(default_factory=list)


def records(path: Path, session: Session, hints: tuple[str, ...]) -> Iterator[dict[str, object]]:
    with path.open("rb") as stream:
        for raw in stream:
            text = raw.decode("utf-8", errors="replace")
            if not any(hint in text for hint in hints):
                continue
            try:
                value = json.loads(text)
            except ValueError:
                session.malformed += 1
                continue
            if isinstance(value, dict):
                yield value
            else:
                session.malformed += 1
