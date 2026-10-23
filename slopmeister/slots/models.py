"""Slot identities and exact resource claims."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Live:
    target: str
    slot: int
    name: str
    worktree: Path


@dataclass(frozen=True)
class Listener:
    port: int
    pid: int
    command: str


@dataclass(frozen=True)
class Resource:
    kind: str
    identifier: str
    name: str
    state: str = ""


@dataclass(frozen=True)
class Claim:
    live: Live
    data: Path
    compose: Path | None
    ports: dict[str, int]
    lease: int | None = None
