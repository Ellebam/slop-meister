"""Read selected native fields. Transcript text never leaves these readers."""

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path

from slopmeister.threads.census import after_compaction
from slopmeister.threads.census.records import (
    Compaction,
    Request,
    Session,
    label,
    mapping,
    number,
    records,
    stamp,
    total,
)

CLAUDE_HINTS = ('"usage"', '"tool_use"', "compact_boundary", '"error"')
CODEX_HINTS = ('"token_count"', '"compacted"', '"session_meta"', '"turn_context"')


def _claude_request(record: dict, pending: bool) -> Request:
    message = mapping(record.get("message"))
    usage = mapping(message.get("usage"))
    parts = [
        number(usage.get(key))
        for key in (
            "input_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        )
    ]
    return Request(
        stamp(record.get("timestamp")),
        total(parts),
        number(usage.get("output_tokens")),
        label(message.get("model")),
        pending,
    )


def claude(path: Path) -> Session:
    session = Session("claude", role="subagent" if path.parent.name == "subagents" else None)
    requests: dict[str, Request] = {}
    pending = False
    seen_tools: set[tuple[str, str]] = set()
    for record in records(path, session, CLAUDE_HINTS):
        if record.get("isSidechain") and session.role != "subagent":
            continue
        if record.get("type") != "assistant" and (
            "usage" in record or "usage" in mapping(record.get("message"))
        ):
            session.unsupported += 1
        if record.get("error") == "rate_limit":
            session.limit_hits.append(stamp(record.get("timestamp")))
        if record.get("type") == "system" and record.get("subtype") == "compact_boundary":
            meta = mapping(record.get("compactMetadata"))
            session.compactions.append(
                Compaction(
                    stamp(record.get("timestamp")),
                    number(meta.get("preTokens")),
                    number(meta.get("postTokens")),
                )
            )
            pending = True
        elif record.get("type") == "assistant":
            pending = _claude_message(record, session, requests, pending)
            session.tools.extend(after_compaction.extract(record, seen_tools))
    session.requests = list(requests.values())
    return session


def _claude_message(record: dict, session: Session, requests: dict, pending: bool) -> bool:
    message = mapping(record.get("message"))
    if "usage" not in message or message.get("model") == "<synthetic>":
        return pending
    request = _claude_request(record, pending)
    identity = label(message.get("id")) or label(record.get("uuid"))
    request.identity_known = identity is not None
    key = identity or f"unknown-{len(requests)}"
    previous = requests.get(key)
    if previous:
        request.timestamp = previous.timestamp
        request.after_compaction = previous.after_compaction
    requests[key] = request
    session.cwd = label(record.get("cwd")) or session.cwd
    if record.get("entrypoint") == "sdk-cli" and session.role is None:
        session.role = "exec"
    return False


@dataclass
class CodexState:
    named: bool = False
    model: str | None = None
    last_total: str | None = None
    last_context: int | None = None
    pending: Compaction | None = None


def _metadata(payload: dict, session: Session) -> None:
    session.cwd = label(payload.get("cwd"))
    source = payload.get("source")
    if isinstance(source, dict) and "subagent" in source:
        subagent = mapping(source.get("subagent"))
        session.role = "review" if subagent.get("other") == "guardian" else "subagent"
    elif source == "exec":
        session.role = "exec"


def _codex_usage(record: dict, session: Session, state: CodexState) -> None:
    payload = mapping(record.get("payload"))
    timestamp = stamp(record.get("timestamp"))
    limits = mapping(payload.get("rate_limits"))
    percentages = [mapping(limits.get(key)).get("used_percent") for key in ("primary", "secondary")]
    if any(type(value) in (int, float) and value >= 100 for value in percentages):
        session.limit_hits.append(timestamp)
    info = mapping(payload.get("info"))
    if payload.get("info") is not None and not isinstance(payload.get("info"), dict):
        session.unsupported += 1
    # A limit-only update does not report a model request.
    if not info:
        return
    last = mapping(info.get("last_token_usage"))
    if state.pending is not None and state.pending.after is None:
        state.pending.after = number(last.get("total_tokens"))
    cumulative = mapping(info.get("total_token_usage"))
    known = number(cumulative.get("input_tokens")) is not None
    current_total = json.dumps(cumulative, sort_keys=True) if known else None
    context = number(last.get("input_tokens"))
    mirror = current_total is not None and current_total == state.last_total
    state.last_total = current_total
    if mirror or context == 0:
        return
    _codex_request(last, timestamp, session, state, known)


def _codex_request(
    last: dict, timestamp: datetime | None, session: Session, state: CodexState, known: bool
) -> None:
    context = number(last.get("input_tokens"))
    request = Request(
        timestamp,
        context,
        number(last.get("output_tokens")),
        state.model,
        state.pending is not None,
        known,
    )
    session.requests.append(request)
    if state.pending is not None:
        state.pending = None
    state.last_context = context


def codex(path: Path) -> Session:
    session, state = Session("codex"), CodexState()
    for record in records(path, session, CODEX_HINTS):
        payload = mapping(record.get("payload"))
        kind = record.get("type")
        if kind != "event_msg" and (kind == "token_count" or payload.get("type") == "token_count"):
            session.unsupported += 1
        if kind == "session_meta" and not state.named:
            state.named = True
            _metadata(payload, session)
        if kind == "turn_context":
            state.model = label(payload.get("model")) or state.model
        if kind == "compacted":
            state.pending = Compaction(stamp(record.get("timestamp")), state.last_context, None)
            session.compactions.append(state.pending)
        if kind == "event_msg" and payload.get("type") == "token_count":
            _codex_usage(record, session, state)
    return session
