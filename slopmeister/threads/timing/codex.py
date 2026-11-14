"""Read one Codex session log into a Session and the facts that say what kind of thread it is."""

from dataclasses import dataclass, field
import json
import re

from slopmeister.threads.timing.events import REPORT, Command, Session, Turn, User, epoch
from slopmeister.threads.timing.records import records

META_KEYS = ("originator", "thread_source", "parent_thread_id")
# Codex records its own injected context as user messages.
INJECTED = ("<environment_context", "# AGENTS.md", "<user_instructions", "<turn_aborted")
SHELL_ARGUMENT = re.compile(r'\bcmd:\s*("(?:[^"\\]|\\.)*")')
HEADER = (
    rb'^\s*\{\s*"timestamp"\s*:\s*"([^"\\]+)"\s*,(?:\s*"ordinal"\s*:\s*\d+\s*,)?'
    rb'\s*"type"\s*:\s*"response_item"\s*,'
)
PASSIVE = re.compile(
    HEADER + rb'\s*"payload"\s*:\s*\{\s*"type"\s*:\s*'
    rb'"(?:reasoning|custom_tool_call_output|function_call_output|message)"'
)


@dataclass
class _Reader:
    session: Session
    meta: dict = field(default_factory=dict)
    said: list[str] = field(default_factory=list)
    turn_start: float = 0.0

    def record(self, record: dict) -> None:
        kind, payload = record.get("type"), record.get("payload") or {}
        if kind == "session_meta":
            self.meta = {key: payload.get(key) for key in META_KEYS}
            self.session.session_id = payload.get("id") or ""
            self.session.cwd = payload.get("cwd") or ""
        stamp = record.get("timestamp")
        if not stamp or kind == "session_meta":
            return
        when = epoch(stamp)
        self.session.activity.append(when)
        handlers = {
            "turn_context": self.context,
            "token_usage_record": self.usage,
            "event_msg": self.event,
            "response_item": self.call,
        }
        if kind == "compacted":
            self.session.compactions += 1
        elif kind in handlers:
            handlers[kind](when, payload)

    def context(self, when: float, payload: dict) -> None:
        self.session.model = payload.get("model") or self.session.model
        self.session.effort = payload.get("effort") or self.session.effort

    def call(self, when: float, payload: dict) -> None:
        kind, name = payload.get("type"), payload.get("name", "").split(".")[-1]
        if kind == "custom_tool_call" and name == "exec":
            for match in SHELL_ARGUMENT.finditer(payload.get("input") or ""):
                try:
                    command = json.loads(match.group(1))
                except ValueError:
                    continue
                self.session.start_command(when, command)
        elif kind == "function_call" and name == "exec_command":
            try:
                arguments = json.loads(payload.get("arguments") or "{}")
            except ValueError:
                return
            command = arguments.get("cmd") if isinstance(arguments, dict) else None
            if isinstance(command, str):
                self.session.start_command(when, command)

    def usage(self, when: float, payload: dict) -> None:
        usage = payload.get("usage") or {}
        taken, written = usage.get("input_tokens") or 0, usage.get("output_tokens") or 0
        self.session.tokens.append((when, taken, written))

    def event(self, when: float, payload: dict) -> None:
        inner = payload.get("type")
        if inner == "task_started":
            self.turn_start = when
        elif inner in ("task_complete", "turn_aborted"):
            seconds = (payload.get("duration_ms") or 0) / 1000 or max(when - self.turn_start, 0)
            report = bool(REPORT.search("\n".join(self.said)))
            self.session.turns.append(Turn(when, seconds, report))
            self.said = []
            if inner == "turn_aborted":
                self.session.users.append(User(when, "interrupt"))
        elif inner == "item_completed":
            self.item(when, payload)

    def item(self, when: float, payload: dict) -> None:
        item = payload.get("item") or {}
        start = (payload.get("started_at_ms") or 0) / 1000 or when
        end = (payload.get("completed_at_ms") or 0) / 1000 or when
        handlers = {
            "CommandExecution": self.command,
            "Extension": self.extension,
            "FileChange": self.change,
            "AgentMessage": self.agent,
            "UserMessage": self.user,
        }
        if item.get("type") in handlers:
            handlers[item["type"]]((start, end), item)

    def command(self, span: tuple[float, float], item: dict) -> None:
        argv = item.get("command")
        text = argv[-1] if isinstance(argv, list) and argv else str(argv or "")
        self.session.add_command(span, text, item.get("exit_code") not in (0, None))

    def extension(self, span: tuple[float, float], item: dict) -> None:
        if item.get("kind") == "clock.sleep":
            seconds = float(item.get("durationMs") or 0) / 1000
            self.session.commands.append(Command(span[1] - seconds, span[1], "sleep", False))

    def change(self, span: tuple[float, float], item: dict) -> None:
        changes = item.get("changes") or {}
        for path in changes:
            self.session.add_edit(span[1], path, json.dumps(changes[path]))

    def agent(self, span: tuple[float, float], item: dict) -> None:
        self.said.extend(part.get("text") or "" for part in item.get("content") or [])

    def user(self, span: tuple[float, float], item: dict) -> None:
        text = "".join(part.get("text") or "" for part in item.get("content") or [])
        if not text.startswith(INJECTED):
            self.session.add_user(span[1], text)


def read(
    path: str, *, strict: bool = False, deadline: float | None = None, starts: bool = False
) -> tuple[Session, dict]:
    reader = _Reader(Session("codex"))
    passive = PASSIVE if starts else re.compile(HEADER)
    for record in records(path, strict=strict, deadline=deadline, passive=passive):
        reader.record(record)
    return reader.session, reader.meta
