"""Aggregate normalized events without exposing workspace identities."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from slopmeister.session.context_redispatch import MANAGER_MARK
from slopmeister.threads.census.records import Interval, Request, Session, total

DELIVERED_MARK = (
    "Only the standing dispatcher, a session dispatched as a manager and a proof owner send"
)
MAIN_ROLES = {"dispatcher", "direct", "worker", "manager", "launched"}


def _delivered_role(cwd: str | None) -> str | None:
    if not cwd or not Path(cwd).is_absolute():
        return None
    for name in ("CLAUDE.md", "AGENTS.md"):
        path = Path(cwd) / name
        try:
            if path.is_symlink():
                continue
            text = path.read_text(errors="replace")
        except OSError, ValueError:
            continue
        if DELIVERED_MARK in text:
            return "manager" if MANAGER_MARK in text else "worker"
    return None


def classification(session: Session, plots: set[str]) -> tuple[str, str]:
    name = Path(session.cwd).name if session.cwd else ""
    matches = [plot for plot in plots if name == plot or name.startswith(plot + "-")]
    plot = max(matches, key=len) if matches else "unknown"
    role = session.role or ("launched" if plot != "unknown" else "unknown")
    if session.role is None:
        role = _delivered_role(session.cwd) or role
        if name in plots:
            role = "dispatcher" if name == "slopmeister" else "direct"
    return plot, role


@dataclass
class Cell:
    sessions: set[int] = field(default_factory=set)
    requests: list[Request] = field(default_factory=list)
    compactions: int = 0
    limit_hits: int = 0


def _model_at(session: Session, timestamp: datetime) -> str:
    previous = [q for q in session.requests if q.timestamp and q.timestamp <= timestamp]
    return previous[-1].model or "unknown" if previous else "unknown"


def _session_cells(session: Session, index: int, interval: Interval, groups: dict) -> None:
    for request in session.requests:
        if interval.contains(request.timestamp):
            key = (request.model or "unknown", interval.week(request.timestamp))
            groups[key].requests.append(request)
            groups[key].sessions.add(index)
    events = [(c.timestamp, "compactions") for c in session.compactions]
    events += [(timestamp, "limit_hits") for timestamp in session.limit_hits]
    for timestamp, kind in events:
        if interval.contains(timestamp):
            key = (_model_at(session, timestamp), interval.week(timestamp))
            cell = groups[key]
            setattr(cell, kind, getattr(cell, kind) + 1)
            cell.sessions.add(index)


def cells(sessions: list[Session], interval: Interval, host: str, plots: set[str]) -> list[dict]:
    grouped: dict[tuple, Cell] = {}
    for index, session in enumerate(sessions):
        plot, role = classification(session, plots)
        local = defaultdict(Cell)
        _session_cells(session, index, interval, local)
        for (model, week), value in local.items():
            key = (host, session.client, model, plot, role, week)
            destination = grouped.setdefault(key, Cell())
            destination.sessions.update(value.sessions)
            destination.requests.extend(value.requests)
            destination.compactions += value.compactions
            destination.limit_hits += value.limit_hits
    return [_cell(key, cell) for key, cell in sorted(grouped.items())]


def _cell(key: tuple, cell: Cell) -> dict:
    known = all(q.identity_known for q in cell.requests)
    contexts = [request.context for request in cell.requests]
    input_tokens = total(contexts) if known else None
    peak = max(contexts) if contexts and None not in contexts and known else None
    requests = len(cell.requests)
    if not requests:
        input_tokens = 0
    return dict(
        zip(("host", "client", "model", "plot", "role", "week"), key, strict=True),
        sessions=len(cell.sessions),
        requests=requests if known else None,
        usage_records=requests,
        input=input_tokens,
        output=(total([q.output for q in cell.requests]) if requests else 0) if known else None,
        peak_context=peak,
        mean_context=round(input_tokens / requests)
        if input_tokens is not None and requests
        else None,
        compactions=cell.compactions,
        limit_hits=cell.limit_hits,
    )


def quantiles(values: list[int | float]) -> dict | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "p50": ordered[len(ordered) // 2],
        "p90": ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))],
        "max": ordered[-1],
    }


def notes_size(cwd: str | None) -> int | None:
    if not cwd or not Path(cwd).is_absolute():
        return None
    try:
        paths = [
            p for p in sorted(Path(cwd).glob("*-NOTES.md")) if not p.is_symlink() and p.is_file()
        ]
        return paths[0].stat().st_size if paths else None
    except OSError, ValueError:
        return None


def mains(sessions: list[Session], interval: Interval, plots: set[str]) -> list[Session]:
    selected = []
    for session in sessions:
        if classification(session, plots)[1] in MAIN_ROLES:
            requests = [q for q in session.requests if interval.contains(q.timestamp)]
            compactions = [c for c in session.compactions if interval.contains(c.timestamp)]
            if requests:
                selected.append(
                    Session(session.client, session.cwd, session.role, requests, compactions)
                )
    return selected


def session_summaries(sessions: list[Session], plots: set[str]) -> dict:
    spans, per_workspace = defaultdict(list), defaultdict(list)
    for session in sessions:
        start = min(q.timestamp for q in session.requests)
        end = max(q.timestamp for q in session.requests)
        role = classification(session, plots)[1]
        spans[f"{session.client}/{role}"].append((end - start).total_seconds() / 3600)
        if session.cwd:
            per_workspace[session.cwd].append((start, end))
    successive = 0
    for runs in per_workspace.values():
        runs.sort()
        successive += sum(b[0] >= a[1] for a, b in zip(runs, runs[1:], strict=False))
    return {
        "sessions_by_role": {key: quantiles(value) for key, value in sorted(spans.items())},
        "successive_sessions_same_workspace": successive,
        "peak_context_main": {client: _peaks(sessions, client) for client in ("claude", "codex")},
    }


def _peaks(sessions: list[Session], client: str) -> dict | None:
    values = [
        [q.context for q in session.requests] for session in sessions if session.client == client
    ]
    if any(None in contexts for contexts in values):
        return None
    return quantiles([max(contexts) for contexts in values])


def messages(sessions: list[Session], interval: Interval) -> dict:
    """Count prompts per kind and the requests each kind triggered, per week."""
    weeks: dict = defaultdict(lambda: {"messages": defaultdict(int), "requests": defaultdict(int)})
    for session in sessions:
        for timestamp, kind in session.messages:
            if interval.contains(timestamp):
                weeks[interval.week(timestamp)]["messages"][kind] += 1
        for request in session.requests:
            if interval.contains(request.timestamp):
                weeks[interval.week(request.timestamp)]["requests"][request.trigger or "none"] += 1
    return {
        week: {name: dict(sorted(counts.items())) for name, counts in value.items()}
        for week, value in sorted(weeks.items())
    }
