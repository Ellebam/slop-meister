"""Aggregate usage in an explicit UTC interval. Output contains no transcript text.

Weeks start at --since. --until is exclusive. The thirty-call after-compaction
comparison covers Claude main logs only. Decisions replay the historical
recommendation rules with assumed safe final states; they never order an action.
Run this same command on a paired checkout through the existing dedicated SSH route.

Compare equal, complete seven-day UTC intervals before and after the actual
threshold installation on each host. Keep the same plot labels and notes roots.
Compare input per main-session request and per session, along with requests,
compactions, after-compaction reads and unknown-data coverage. Workload changes
mean a reduction in raw weekly input alone does not establish a token saving.
"""

import argparse
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys

from slopmeister.paths import plot_declarations
from slopmeister.threads.census import after_compaction, policy, readers, report
from slopmeister.threads.census.records import Interval, Session, mapping, number, total


def date(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("use an ISO date or timestamp") from error
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="slopmeister context-census", description=__doc__)
    parser.add_argument("--since", type=date, required=True)
    parser.add_argument("--until", type=date, required=True, help="exclusive end")
    parser.add_argument(
        "--home", type=Path, default=Path.home(), help="home containing native logs"
    )
    parser.add_argument("--host", default="local", help="output label, never inferred hostname")
    parser.add_argument("--plots", help="comma-separated declared plots; default: checkout plots")
    parser.add_argument("--notes-root", action="append", type=Path, default=[])
    parser.add_argument("--thresholds", help="historical rule thresholds, inline JSON or a file")
    args = parser.parse_args(argv)
    if args.since >= args.until:
        parser.error("since must precede until")
    return args


def _thresholds(value: str | None) -> dict:
    if value is None:
        return policy.DEFAULT_THRESHOLDS
    text = value if value.lstrip().startswith("{") else Path(value).read_text()
    result = mapping(json.loads(text))
    compact = mapping(result.get("compact_tokens"))
    values = [
        result.get("debloat_bytes"),
        result.get("redispatch_compactions"),
        compact.get("claude"),
        compact.get("codex"),
    ]
    if any(number(item) is None or item == 0 for item in values):
        raise ValueError("invalid thresholds")
    return {
        "debloat_bytes": values[0],
        "redispatch_compactions": values[1],
        "compact_tokens": {"claude": values[2], "codex": values[3]},
    }


def _paths(home: Path) -> tuple[list[tuple[str, Path]], dict[str, str]]:
    roots = {"claude": home / ".claude/projects", "codex": home / ".codex/sessions"}
    status, paths = {}, []
    for client, root in roots.items():
        status[client] = "present"
        paths.extend((client, path) for path in _walk(client, root, status))
    return sorted(set(paths)), status


def _walk(client: str, root: Path, status: dict) -> Iterator[Path]:
    def failed(error: OSError) -> None:
        status[client] = "missing" if isinstance(error, FileNotFoundError) else "unreadable"

    for directory, _, names in os.walk(root, onerror=failed):
        relative = Path(directory).relative_to(root).parts
        for name in names:
            claude_log = len(relative) == 1 or (len(relative) == 3 and relative[-1] == "subagents")
            selected = name.startswith("rollout-") if client == "codex" else claude_log
            if selected and name.endswith(".jsonl"):
                yield Path(directory) / name


def _scan(home: Path) -> tuple[list[Session], dict]:
    paths, roots = _paths(home)
    sessions, unreadable = [], 0
    for client, path in paths:
        try:
            if path.is_symlink():
                unreadable += 1
                continue
            sessions.append((readers.claude if client == "claude" else readers.codex)(path))
        except OSError:
            unreadable += 1
    coverage = {
        "source_roots": roots,
        "unreadable_files": unreadable,
        "unreadable_roots": sum(status == "unreadable" for status in roots.values()),
        "undated_usage_records": sum(q.timestamp is None for s in sessions for q in s.requests),
        "undated_compactions": sum(c.timestamp is None for s in sessions for c in s.compactions),
        "undated_limit_hits": sum(ts is None for s in sessions for ts in s.limit_hits),
        "unsupported_usage_records": sum(s.unsupported for s in sessions),
    }
    return sessions, coverage


def _notes(roots: list[Path]) -> dict | None:
    sizes = []
    for root in roots:
        for path in root.expanduser().glob("**/*-NOTES.md"):
            if len(path.relative_to(root.expanduser()).parts) <= 5 and not path.is_symlink():
                sizes.append(path.stat().st_size)
    return report.quantiles(sizes)


def _result(sessions: list[Session], args: argparse.Namespace, thresholds: dict) -> dict:
    interval = Interval(args.since, args.until)
    plots = (
        set(filter(None, args.plots.split(",")))
        if args.plots is not None
        else {path.name for path in plot_declarations().iterdir() if path.is_dir()}
    )
    for session in sessions:
        session.role = report.classification(session, plots)[1]
    mains = report.mains(sessions, interval, plots)
    ratios = policy.ratios(sessions, interval)
    result = {
        "schema": 2,
        "host": args.host,
        "interval": [args.since.isoformat(), args.until.isoformat()],
        "cells": report.cells(sessions, interval, args.host, plots),
        **report.session_summaries(mains, plots),
        "notes_bytes": _notes(args.notes_root),
        "compaction_ratio_median": ratios,
        "main_input_share_above": policy.input_shares(mains),
        "replay": {
            client: [
                policy.replay([s for s in mains if s.client == client], ratios[client], limit)
                for limit in policy.LIMITS
            ]
            for client in ("claude", "codex")
        },
        "decisions": policy.decisions(mains, thresholds),
        "after_compaction": after_compaction.summarize(sessions, interval),
    }
    result["multi_compaction_main"] = _multi(mains)
    return result


def _multi(sessions: list[Session]) -> dict:
    selected = [s for s in sessions if len(s.compactions) >= 2]
    original = total(
        [q.context if q.identity_known else None for s in sessions for q in s.requests]
    )
    observed = total([q.context for s in selected for q in s.requests])
    return {
        "sessions": len(selected),
        "input_share": round((observed or 0) / original, 4) if original else None,
    }


def _coverage(sessions: list[Session], interval: Interval) -> dict:
    requests = [q for s in sessions for q in s.requests if interval.contains(q.timestamp)]
    active = [s for s in sessions if any(interval.contains(q.timestamp) for q in s.requests)]
    inactive = [s for s in sessions if not any(interval.contains(q.timestamp) for q in s.requests)]
    return {
        "unknown_input_records": sum(q.context is None for q in requests),
        "unknown_output_records": sum(q.output is None for q in requests),
        "unknown_request_identity_records": sum(not q.identity_known for q in requests),
        "unclassified_role_request_sessions": sum(s.role == "unknown" for s in active),
        "limit_hits_without_in_window_requests": sum(
            interval.contains(ts) for s in inactive for ts in s.limit_hits
        ),
        "out_of_window_limit_hits_in_active_sessions": sum(
            not interval.contains(ts) for s in active for ts in s.limit_hits if ts is not None
        ),
    }


def main(argv: Sequence[str]) -> int:
    args = _arguments(argv)
    try:
        thresholds = _thresholds(args.thresholds)
        sessions, coverage = _scan(args.home.expanduser())
        result = _result(sessions, args, thresholds)
        coverage.update(_coverage(sessions, Interval(args.since, args.until)))
        result["coverage"] = coverage
        result["files"] = {
            "selected": len(sessions),
            "malformed": sum(s.malformed for s in sessions),
        }
        print(json.dumps(result, indent=1))
        return int(bool(coverage["unreadable_files"] or coverage["unreadable_roots"]))
    except OSError, ValueError, ArithmeticError:
        print("context-census: cannot read inputs or unsupported argument data", file=sys.stderr)
        return 1
