"""Live elapsed time, observed repeat rounds and historical handoff estimates."""

from collections import Counter
from statistics import median

from slopmeister.threads.timing.events import Session
from slopmeister.threads.timing.history import LOOKBACK_SECONDS
from slopmeister.threads.timing.stages import COMMAND_STAGE, RANK, stage_changes


def extra_rounds(session: Session) -> int:
    commands = sorted(session.commands, key=lambda command: command.start)
    kinds = Counter(c.kind for c in commands if c.kind in COMMAND_STAGE)
    starts = Counter(kind for _, kind in session.command_starts)
    kinds |= starts
    repeated = sum(max(0, count - 1) for count in kinds.values())
    # A failed check creates an extra round only when another check actually follows it.
    checks = [c for c in commands if c.kind in ("gate-full", "gate-focused", "test-run")]
    repeated += sum(c.failed for c in checks[:-1])
    changes = stage_changes(session)
    handoff = next((when for when, stage in changes if stage == "accept"), float("inf"))
    halts = [t.end for t in session.turns if t.report and t.end < handoff]
    repeated += sum(
        any(u.when > halt and u.kind == "operator" for u in session.users) for halt in halts
    )
    return repeated


def timings(session: Session, now: float) -> dict:
    when, stage = stage_changes(session)[-1]
    return {
        "state": "known",
        "stage": stage,
        "step_started_at": round(when),
        "step_seconds": max(0, round(now - when)),
        "started_at": round(min(session.activity)),
        "total_seconds": max(0, round(now - min(session.activity))),
        "last_activity_at": round(max(session.activity)),
        "extra_rounds": extra_rounds(session),
    }


def estimate(row: dict, history: list[Session], active: set[str]) -> None:
    row["estimate_sessions"] = 0
    stage = row["stage"]
    if stage is None or RANK[stage] >= RANK["accept"]:
        return
    durations = []
    for session in history:
        if session.cwd in active or session.plot != row["plot"]:
            continue
        entered = dict((name, when) for when, name in stage_changes(session))
        finish, start = entered.get("accept"), entered.get(stage)
        if (
            finish is not None
            and start is not None
            and start <= finish
            and finish >= row["observed_at"] - LOOKBACK_SECONDS
        ):
            durations.append(finish - start)
    row["estimate_sessions"] = len(durations)
    if durations:
        row["expected_finish_at"] = round(row["step_started_at"] + median(durations))
