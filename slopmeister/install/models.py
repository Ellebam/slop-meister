"""State carried between installation stages."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class InstallRequest:
    action: str
    target: str
    workspace: str
    allocation: str | None
    grants: list[str]
    dispatcher_jira: bool = False


@dataclass(frozen=True)
class PayloadContext:
    root: Path
    target: str
    permission: str
    directory: bool
    shipping: str = "deny"


@dataclass(frozen=True)
class ToolPayload:
    files: dict
    context: PayloadContext
    tool: str
    native: str
    agreement: str


@dataclass
class InstallContext:
    request: InstallRequest
    root: Path
    data: dict
    repo: Path
    directory: bool
    permission: str
    shipping: str
    grants: list[str]
    files: dict = field(default_factory=dict)
    settings: dict = field(default_factory=dict)
    state: dict = field(default_factory=dict)
    roots: list[str] = field(default_factory=list)
    common: Path | None = None
    gitdir: Path | None = None
    state_dir: Path | None = None
    indexed: list[bytes] = field(default_factory=list)
    ignore_bytes: bytes = b""
