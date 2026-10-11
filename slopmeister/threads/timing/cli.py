"""Where spine worker sessions on this machine spent their time, by stage and by who waited."""

import argparse
from collections.abc import Sequence
import glob
import json
import os
from pathlib import Path
import socket
import sys

from slopmeister.spine.tester.launch import evidence_home
from slopmeister.threads.timing import claude, codex
from slopmeister.threads.timing.events import Command, Session, epoch
from slopmeister.threads.timing.report import row, summary, table

LIMITS = """\
Each line carries timings, counts and the session name, never text from a log.
For several machines, run --since on each and pipe all lines into one --table.

Stages follow actions: the first turn end, the plan review command, the first source
edit, the first full gate, the test guide file, a saved tester run, the ship command,
the diff review command, the closing report and the operator's finalize.

Limits. The line between implement and proof is approximate. A review launched from a
script is not seen. A full gate is recognized as `task check` or `slopmeister check`
only. Lines changed come from Claude's own record, files from edits seen in the log, so
an edit made through the shell is in neither.

Table columns: G full gates, T tester verdicts, M checksum commands as a sign of
mutation passes, A approval reviews, I interrupts, R operator replies, E replies before
go that ask for an explanation, H halts.
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
        epilog=LIMITS,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--since", help="print one JSON line per session started at this ISO time or later"
    )
    mode.add_argument(
        "--table", action="store_true", help="read such lines on stdin, print table and summary"
    )
    show = "with --table, a repository whose session names are printed, repeatable"
    parser.add_argument("--show", action="append", default=[], metavar="REPOSITORY", help=show)
    host = socket.gethostname().split(".")[0]
    parser.add_argument("--host", default=host, help="the machine name written into each line")
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    arguments = _arguments(argv)
    if arguments.table:
        rows = [json.loads(line) for line in sys.stdin if line.strip()]
        sys.stdout.write(table(rows, set(arguments.show)) + "\n" + summary(rows))
        return 0
    # The launcher owns where tester runs are saved. Its checkout guard has nothing to guard here.
    runs = evidence_home(Path(os.devnull), create=False)
    for session in scan(Path.home(), epoch(arguments.since), runs):
        print(json.dumps(row(session, arguments.host), sort_keys=True))
    return 0
