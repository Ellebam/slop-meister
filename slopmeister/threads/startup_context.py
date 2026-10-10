"""Report the context a Claude Code session received at startup."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
import json
import sys

USAGE_FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
LATER_KINDS = ("deferred_tools_delta", "mcp_instructions_delta")
MCP_PREFIX = "mcp__"


def records(path: str) -> Iterable[dict]:
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def body_bytes(attachment: dict) -> int:
    body = attachment.get("content") or "".join(attachment.get("addedLines", []))
    body = body or "".join(attachment.get("addedBlocks", [])) or attachment.get("text", "")
    return len(body.encode())


def names_of(attachment: dict) -> list[str]:
    return (
        attachment.get("names")
        or attachment.get("addedNames")
        or attachment.get("addedTypes")
        or []
    )


def servers_of(names: Iterable[str]) -> list[str]:
    return sorted(
        {
            name.split("__")[1]
            for name in names
            if name.startswith(MCP_PREFIX) and name.count("__") >= 2
        }
    )


def kickoff_bytes(record: dict) -> int:
    content = record.get("message", {}).get("content", "")
    if isinstance(content, list):
        content = "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return len(content.encode())


@dataclass
class TranscriptState:
    turn: int = 0
    last_id: str | None = None
    usage: dict | None = None
    kickoff: int | None = None
    startup: list = field(default_factory=list)
    later: list = field(default_factory=list)
    servers: set = field(default_factory=set)
    mcp_names: int = 0

    def assistant(self, record: dict) -> None:
        message = record.get("message", {})
        message_id = message.get("id")
        if message_id != self.last_id:
            self.turn += 1
            self.last_id = message_id
        if self.usage is None and self.turn == 1 and message.get("usage"):
            self.usage = message["usage"]

    def attachment(self, item: dict) -> None:
        names = names_of(item)
        if self.turn == 0:
            self.startup.append((item["type"], body_bytes(item), names))
        elif item["type"] in LATER_KINDS:
            self.later.append((self.turn, item["type"], body_bytes(item), names))
        found = [name for name in names if name.startswith(MCP_PREFIX)]
        self.mcp_names += len(found)
        self.servers.update(servers_of(found))

    def consume(self, record: dict) -> None:
        kind = record.get("type")
        if kind == "assistant":
            self.assistant(record)
        elif kind == "user" and self.turn == 0 and self.kickoff is None:
            self.kickoff = kickoff_bytes(record)
        elif kind == "attachment":
            self.attachment(record["attachment"])


def _collect(path: str) -> TranscriptState:
    state = TranscriptState()
    for record in records(path):
        state.consume(record)
    return state


def report(path: str) -> None:
    state = _collect(path)
    if state.usage is None:
        sys.exit(f"{path}: the first assistant turn carries no usage, the session never answered")
    total = sum(state.usage.get(field, 0) for field in USAGE_FIELDS)
    parts = ", ".join(f"{field} {state.usage.get(field, 0)}" for field in USAGE_FIELDS)
    print(f"first turn {total} prompt tokens ({parts})")
    print(f"kickoff {state.kickoff or 0} bytes")
    for kind, size, names in state.startup:
        print(
            f"startup {kind} {size} bytes, {len(names)} names"
            + (": " + " ".join(names) if names else "")
        )
    for after, kind, size, names in state.later:
        found = servers_of(names)
        suffix = ", mcp servers " + " ".join(found) if found else ""
        print(f"after turn {after} {kind} {size} bytes, {len(names)} names" + suffix)
    print(f"mcp servers seen: {' '.join(sorted(state.servers)) if state.servers else 'none'}")
    print(f"mcp tool names: {state.mcp_names}")


def main(argv: Sequence[str]) -> int:
    if len(argv) != 1:
        sys.stderr.write("usage: slopmeister startup-context <transcript>\n")
        return 2
    report(argv[0])
    return 0
