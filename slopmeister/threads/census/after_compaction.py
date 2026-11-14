"""Claude's thirty-tool-call comparison. Targets are hashed in memory, never executed."""

from collections import deque
import hashlib
import json
import statistics

from slopmeister.threads.census.records import Interval, Session, ToolEvent, label, mapping, stamp

WINDOW = 30


def extract(record: dict, seen: set[tuple[str, str]]) -> list[ToolEvent]:
    message = mapping(record.get("message"))
    content = message.get("content")
    if not isinstance(content, list):
        return []
    events = []
    for value in content:
        block = mapping(value)
        if block.get("type") == "tool_use":
            event = _tool(record, block, seen)
            if event is not None:
                events.append(event)
    return events


def _tool(record: dict, block: dict, seen: set[tuple[str, str]]) -> ToolEvent | None:
    message_id = label(mapping(record.get("message")).get("id"))
    tool_id = label(block.get("id"))
    name = label(block.get("name"))
    if message_id is None or tool_id is None or name is None:
        return None
    key = (message_id, tool_id)
    if key in seen:
        return None
    seen.add(key)
    arguments = mapping(block.get("input"))
    target = label(arguments.get("command" if name == "Bash" else "file_path"))
    digest = hashlib.sha256(json.dumps([name, target]).encode()).hexdigest() if target else None
    return ToolEvent(
        stamp(record.get("timestamp")), name, digest, bool(target and "-NOTES.md" in target)
    )


def _observations(session: Session, interval: Interval) -> list[dict]:
    tools = [event for event in session.tools if interval.contains(event.timestamp)]
    boundaries = [c.timestamp for c in session.compactions if interval.contains(c.timestamp)]
    events = [(t.timestamp, 1, t) for t in tools] + [(ts, 0, None) for ts in boundaries]
    events.sort(key=lambda row: (row[0], row[1]))
    previous, seen, reads = deque(maxlen=WINDOW), set(), set()
    notes_seen = False
    observations = []
    for index, (_, _, event) in enumerate(events):
        if event is None:
            following = _following(events[index + 1 :])
            if len(previous) == WINDOW and len(following) == WINDOW:
                observations.append(_window(list(previous), following, seen, reads, notes_seen))
        else:
            notes_seen = notes_seen or event.notes
            signature = (event.name, event.target)
            previous.append(
                (event, bool(event.target and signature in seen), event.target in reads)
            )
            seen.add(signature)
            if event.name == "Read" and event.target:
                reads.add(event.target)
    return observations


def _following(events: list) -> list[ToolEvent]:
    result = []
    for _, _, event in events:
        if event is None or len(result) == WINDOW:
            break
        result.append(event)
    return result


def _window(previous: list, following: list[ToolEvent], seen: set, reads: set, notes: bool) -> dict:
    return {
        "reads_before": sum(event.name == "Read" for event, _, _ in previous),
        "reads_after": sum(event.name == "Read" for event in following),
        "reread_before": sum(event.name == "Read" and repeat for event, _, repeat in previous),
        "reread_after": sum(event.name == "Read" and event.target in reads for event in following),
        "repeat_before": sum(repeat for _, repeat, _ in previous),
        "repeat_after": sum(
            bool(event.target and (event.name, event.target) in seen) for event in following
        ),
        "notes_read_before": notes,
        "notes_in_first10": any(event.notes for event in following[:10]),
    }


def summarize(sessions: list[Session], interval: Interval) -> dict:
    rows = [
        row
        for session in sessions
        if session.client == "claude" and session.role != "subagent"
        for row in _observations(session, interval)
    ]
    means = {
        key + "_mean": round(statistics.mean(row[key] for row in rows), 2) if rows else None
        for key in (
            "reads_before",
            "reads_after",
            "reread_before",
            "reread_after",
            "repeat_before",
            "repeat_after",
        )
    }
    unknown = sum(
        event.name in {"Read", "Bash"} and event.target is None
        for session in sessions
        if session.client == "claude" and session.role != "subagent"
        for event in session.tools
        if interval.contains(event.timestamp)
    )
    result = {
        "status": "complete" if rows else "no-full-windows",
        "unknown_target_calls": unknown,
        "client": "claude",
        "tool_calls_per_window": WINDOW,
        "compactions_with_full_windows": len(rows),
        **means,
        "compactions_with_prior_notes": sum(row["notes_read_before"] for row in rows),
        "notes_reopened_in_first_10_calls": sum(
            row["notes_read_before"] and row["notes_in_first10"] for row in rows
        ),
    }
    if unknown:
        result.update({key: None for key in means})
        result.update(
            status="unknown",
            compactions_with_prior_notes=None,
            notes_reopened_in_first_10_calls=None,
        )
    return result
