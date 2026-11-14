"""Where spine worker sessions on this machine spent their time, by stage and by who waited."""

import argparse
from collections.abc import Sequence
import glob
import json
import os
from pathlib import Path
import socket
import sys

from slopmeister.threads.timing import claude, codex, live
from slopmeister.threads.timing.events import Command, Session, epoch
from slopmeister.threads.timing.report import row, summary, table

LIMITS = """\
Each line carries timings, counts and the session name, never text from a log.
For several machines, run --since on each and pipe all lines into one --table.

Stages follow actions: the first turn end, the plan review command, the first source
edit, the first full gate, the test guide file, a saved tester run, the ship command,
the diff review command, the closing report and the operator's harvest or finalize.
The historical finalize event name is retained.

Limits. The line between implement and proof is approximate. A review launched from a
script is not seen. A full gate is recognized as `task check` or `slopmeister check`
only. Lines changed come from Claude's own record, files from edits seen in the log, so
an edit made through the shell is in neither.

Table columns: G full gates, T tester verdicts, M checksum commands as a sign of
mutation passes, A approval reviews, I interrupts, R operator replies, E replies before
go that ask for an explanation, H halts.
"""

LIVE_LIMITS = """\
Live JSON contract (--live).
One line per connected local Claude Code or Codex session, including idle sessions
waiting for an answer. Closed and orphaned terminals are excluded. Inventory failure
exits nonzero with a generic diagnostic, never a successful empty reading.

session is an opaque identifier for one local terminal and workspace/tool task.
name, host, plot and tool identify the session. --host keeps its existing label
meaning. manager_host and manager group workers by an explicit manager host/Run in
their initial kickoff. Unsupported or conflicting routes stay null. Rows sort by
manager then session. No relationship is inferred from similar session names.

state is known or unknown. stage is one of resume, frame, answer, plan-review,
implement, proof, test-guide, tester, ship, diff-review, fix-pass, accept, finalize.
Unreadable identities/records and non-spine sessions remain present with null stage.
started_at and total_seconds cover the earliest readable same-workspace/tool record
in the 30-day history window. step_started_at and step_seconds cover the current
stage. observed_at is this reading's time. last_activity_at is the native record's
last timestamp. Times are UTC epoch seconds. Durations are seconds.

extra_rounds counts repeated observed review/ship rounds, retries after failed
checks, and resumptions after reported halts. Ordinary tool calls are not rounds.
It is null when records are unknown. Historical stage detection remains approximate.

expected_finish_at = step_started_at + median historical seconds from the same
plot/stage to the acceptance-ready delivery handoff. An overdue estimate is not
clamped. It is null with no samples or at/after handoff. estimate_sessions counts
distinct earlier workspace/tool tasks, excluding every live task. Redispatch
fragments count once. Only handoffs from the last 30 days contribute. History is
preselected by declared plot, worker metadata and spine kickoff, then bounded to
10 seconds and 10,000 eligible worker records. Unavailable history gives null
estimate_sessions and unknown state before handoff. Sessions at/after handoff
remain known. No usable completed samples gives zero. Native reads have a
10-second deadline and 8 MiB line limit. Finished records do not parse live call
starts or decode unused duplicate tool payloads. Their timestamps are retained.

Names matching the local private identifier patterns are null. Missing or invalid
patterns withhold all free labels. Opaque session identifiers still distinguish
lines. No paths, note text, commands, customer names or terminal content are emitted.
The command reads existing state only. It creates no cache and contacts no agent.
"""


def _tester_runs(root: Path) -> list[dict]:
    """Saved tester runs. A launch from a script leaves no trace in the worker's own log."""
    runs = []
    for path in sorted(root.glob("run-*/run.json")):
        try:
            run = json.loads(path.read_text())
            done = path.with_name("result.json")
            result = json.loads(done.read_text()) if done.exists() else {}
            start = float(run["started_at"])
        except OSError, ValueError, KeyError, TypeError:
            continue
        end = float(result.get("completed_at") or start)
        owner = (run.get("cwd"), run.get("worker_tool"))
        status = result.get("status") or "unfinished"
        runs.append({"owner": owner, "start": start, "end": end, "status": status})
    return sorted(runs, key=lambda run: run["start"])


def _attach(sessions: list[Session], runs: list[dict]) -> None:
    """Give each run to the one session that launched it, the latest that was open then."""
    for run in runs:
        owners = [
            session
            for session in sessions
            if (session.cwd.rstrip("/"), session.tool) == run["owner"]
            and min(session.activity) <= run["start"] <= max(session.activity)
        ]
        if owners:
            owner = max(owners, key=lambda session: min(session.activity))
            failed = run["status"] != "pass"
            owner.commands.append(Command(run["start"], run["end"], "tester-run", failed))
            owner.tester_runs.append(run["status"])


def _codex_workers(root: Path, since: float) -> list[Session]:
    """Interactive Codex sessions, each with the approval reviews of its guardian thread."""
    workers, reviews = [], {}
    for path in glob.glob(str(root / "**" / "*.jsonl"), recursive=True):
        if os.path.getmtime(path) < since:
            continue
        session, meta = codex.read(path)
        if meta.get("thread_source") == "guardian_review":
            spans = [(turn.end - turn.seconds, turn.end) for turn in session.turns]
            reviews.setdefault(meta.get("parent_thread_id"), []).extend(spans)
        elif meta.get("originator") != "codex_exec":
            workers.append(session)
    for session in workers:
        session.approvals = reviews.get(session.session_id, [])
    return workers


def scan(home: Path, since: float, runs: Path) -> list[Session]:
    """Spine worker sessions of both tools that started at or after `since`."""
    logs = glob.glob(str(home / ".claude/projects/*/*.jsonl"))
    sessions = [claude.read(path) for path in logs if os.path.getmtime(path) >= since]
    sessions += _codex_workers(home / ".codex/sessions", since)
    kept = [
        session
        for session in sessions
        if session.mode == "spine" and session.activity and min(session.activity) >= since
    ]
    _attach(kept, _tester_runs(runs))
    return kept


def _arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="slopmeister spine-timing",
        description=__doc__,
        epilog=LIMITS + LIVE_LIMITS,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--since", help="print one JSON line per session started at this ISO time or later"
    )
    mode.add_argument(
        "--table", action="store_true", help="read such lines on stdin, print table and summary"
    )
    mode.add_argument(
        "--live", action="store_true", help="print local running session progress as JSON lines"
    )
    show = "with --table, a repository whose session names are printed, repeatable"
    parser.add_argument("--show", action="append", default=[], metavar="REPOSITORY", help=show)
    host = socket.gethostname().split(".")[0]
    parser.add_argument("--host", default=host, help="the machine name written into each line")
    return parser.parse_args(argv)


def _tester_runs_home() -> Path:
    """Where the retired separate tester saved its runs, read for sessions before the diff check."""
    state = Path(os.environ.get("XDG_STATE_HOME", ""))
    if not state.is_absolute():
        state = Path.home() / ".local/state"
    return (state / "slopmeister/spine-tests").resolve()


def main(argv: Sequence[str]) -> int:
    arguments = _arguments(argv)
    if arguments.live:
        for measured in live.rows(arguments.host):
            print(json.dumps(measured, sort_keys=True))
        return 0
    if arguments.table:
        rows = [json.loads(line) for line in sys.stdin if line.strip()]
        sys.stdout.write(table(rows, set(arguments.show)) + "\n" + summary(rows))
        return 0
    runs = _tester_runs_home()
    for session in scan(Path.home(), epoch(arguments.since), runs):
        print(json.dumps(row(session, arguments.host), sort_keys=True))
    return 0
