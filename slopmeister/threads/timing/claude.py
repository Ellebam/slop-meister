"""Read one Claude Code session log into a Session."""

from dataclasses import dataclass, field
import json
import os
import re

from slopmeister.threads.timing.events import REPORT, Session, Turn, User, epoch

TASK_ID = re.compile(r"<task-id>([^<]+)</task-id>")
EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")
INPUT_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
# A file read is classified like the shell command that would print the file.
COMMAND_TEXT = {
    "Bash": lambda data: data.get("command") or "",
    "Read": lambda data: "cat " + (data.get("file_path") or ""),
}


@dataclass
class _Reader:
    session: Session
    opened: dict[str, tuple[float, str]] = field(default_factory=dict)
    background: dict[str, tuple[float, str]] = field(default_factory=dict)
    counted: set[str] = field(default_factory=set)
    said: list[str] = field(default_factory=list)

    def record(self, record: dict) -> None:
        kind, stamp = record.get("type"), record.get("timestamp")
        if kind == "cost-state":
            self.session.cost_usd = record.get("totalCostUSD") or 0.0
            added, removed = record.get("totalLinesAdded"), record.get("totalLinesRemoved")
            self.session.lines = (added or 0) + (removed or 0)
        if not stamp or kind == "attachment" or record.get("isSidechain"):
            return
        when = epoch(stamp)
        self.session.cwd = self.session.cwd or record.get("cwd") or ""
        self.session.activity.append(when)
        handler = {"system": self.system, "assistant": self.assistant, "user": self.user}.get(kind)
        if handler:
            handler(when, record)

    def system(self, when: float, record: dict) -> None:
        subtype = record.get("subtype")
        if subtype == "turn_duration":
            seconds = (record.get("durationMs") or 0) / 1000
            report = bool(REPORT.search("\n".join(self.said)))
            self.session.turns.append(Turn(when, seconds, report))
            self.said = []
        elif subtype == "compact_boundary":
            self.session.compactions += 1

    def assistant(self, when: float, record: dict) -> None:
        message = record.get("message") or {}
        model = message.get("model")
        if model and model != "<synthetic>":
            self.session.model = model
        self.session.effort = record.get("effort") or self.session.effort
        self.usage(when, message)
        content = message.get("content")
        for block in content if isinstance(content, list) else []:
            if block.get("type") == "text":
                self.said.append(block.get("text") or "")
            elif block.get("type") == "tool_use":
                self.tool(when, block)

    def usage(self, when: float, message: dict) -> None:
        if message.get("id") in self.counted:
            return
        self.counted.add(message.get("id"))
        usage = message.get("usage") or {}
        taken = sum(usage.get(key) or 0 for key in INPUT_KEYS)
        self.session.tokens.append((when, taken, usage.get("output_tokens") or 0))

    def tool(self, when: float, block: dict) -> None:
        name, data = block.get("name"), block.get("input") or {}
        read = COMMAND_TEXT.get(name)
        self.opened[block.get("id")] = (when, read(data) if read else "")
        if name == "Skill":
            self.session.skills.append((when, (data.get("skill") or "").split(":")[-1]))
        if name in EDIT_TOOLS:
            body = (data.get("new_string") or "") + (data.get("content") or "")
            self.session.add_edit(when, data.get("file_path") or "", body)

    def user(self, when: float, record: dict) -> None:
        content = (record.get("message") or {}).get("content")
        if record.get("isMeta"):
            return
        if isinstance(content, list) and any(b.get("type") == "tool_result" for b in content):
            self.results(when, record)
            return
        text = content if isinstance(content, str) else _text(content or [])
        origin = (record.get("origin") or {}).get("kind")
        if origin == "task-notification" or text.startswith("<task-notification>"):
            self.returned(when, text)
        elif origin in (None, "human"):
            self.session.add_user(when, text)

    def results(self, when: float, record: dict) -> None:
        result = record.get("toolUseResult")
        task = result.get("backgroundTaskId") if isinstance(result, dict) else None
        for block in record["message"]["content"]:
            opened = self.opened.pop(block.get("tool_use_id"), None)
            if opened and task:
                self.background[task] = opened
            elif opened:
                self.session.add_command((opened[0], when), opened[1], bool(block.get("is_error")))

    def returned(self, when: float, text: str) -> None:
        """A background command ends when its task notification arrives."""
        task = TASK_ID.search(text)
        opened = self.background.pop(task.group(1), None) if task else None
        if opened:
            self.session.add_command((opened[0], when), opened[1], "<status>failed" in text)
        self.session.users.append(User(when, "notify"))


def _text(content: list) -> str:
    return "".join(block.get("text") or "" for block in content if block.get("type") == "text")


def read(path: str) -> Session:
    reader = _Reader(Session("claude", os.path.basename(path).removesuffix(".jsonl")))
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            reader.record(record)
    return reader.session
