"""Select bounded, same-plot native history for the existing timing model."""

from collections import defaultdict
from copy import copy
from pathlib import Path
import time

from slopmeister import paths
from slopmeister.threads.timing import claude, codex
from slopmeister.threads.timing.events import Session
from slopmeister.threads.timing.records import records

LOOKBACK_SECONDS = 30 * 24 * 60 * 60
HISTORY_SECONDS = 10
MAX_FILES = 10_000


def plot_for(cwd: str, plots: set[str]) -> str | None:
    name = Path(cwd).name
    matched = [plot for plot in plots if name.startswith(plot + "-")]
    return max(matched, key=len) if matched else None


def merge(sessions: list[Session]) -> Session:
    ordered = sorted(sessions, key=lambda s: min(s.activity, default=float("inf")))
    result = copy(ordered[-1])
    for name in (
        "users",
        "turns",
        "commands",
        "command_starts",
        "skills",
        "edits",
        "tokens",
        "activity",
    ):
        setattr(result, name, [item for session in ordered for item in getattr(session, name)])
    result.resumed = all(session.resumed for session in ordered)
    return result


def _spine_cwd(path: Path, tool: str, deadline: float) -> str:
    reader = codex._Reader(Session(tool)) if tool == "codex" else claude._Reader(Session(tool))
    for index, record in enumerate(records(str(path), strict=True, deadline=deadline)):
        if index >= 128:
            break
        reader.record(record)
        payload = record.get("payload") or {}
        if tool == "codex" and (
            payload.get("thread_source") == "guardian_review"
            or payload.get("originator") == "codex_exec"
        ):
            return ""
        if reader.session.users:
            return reader.session.cwd if reader.session.mode == "spine" else ""
    return ""


def _candidates(home: Path, plots: set[str]):
    yield from ((path, "codex") for path in paths.codex_home().glob("sessions/**/*.jsonl"))
    for directory in (home / ".claude/projects").glob("*"):
        if any(directory.name == p or f"-{p}-" in directory.name for p in plots):
            yield from ((path, "claude") for path in directory.glob("*.jsonl"))


def scan(
    home: Path, plots: set[str], now: float, *, declared: set[str] | None = None
) -> tuple[list[Session], bool]:
    found = defaultdict(list)
    deadline = time.monotonic() + HISTORY_SECONDS
    selected = {name: name in plots for name in declared or plots}
    count = 0
    for path, tool in _candidates(home, plots):
        if time.monotonic() > deadline:
            return [merge(group) for group in found.values()], False
        try:
            session = _candidate(path, tool, selected, now, deadline)
        except OSError, ValueError, TypeError, KeyError, AttributeError:
            continue
        if session:
            count += 1
            if count > MAX_FILES:
                return [merge(group) for group in found.values()], False
            found[(session.cwd, session.tool)].append(session)
    return [merge(group) for group in found.values()], time.monotonic() <= deadline


def _candidate(
    path: Path, tool: str, selected: dict[str, bool], now: float, deadline: float
) -> Session | None:
    if path.stat().st_mtime < now - LOOKBACK_SECONDS:
        return None
    plot = plot_for(_spine_cwd(path, tool, deadline), set(selected))
    if not selected.get(plot):
        return None
    if tool == "codex":
        session, meta = codex.read(str(path), strict=True, deadline=deadline)
        worker = (
            meta.get("thread_source") != "guardian_review"
            and meta.get("originator") != "codex_exec"
        )
    else:
        session = claude.read(str(path), strict=True, deadline=deadline)
        worker = True
    session.plot = plot
    eligible = (
        worker and session.activity and max(session.activity) <= now and session.mode == "spine"
    )
    return session if eligible else None
