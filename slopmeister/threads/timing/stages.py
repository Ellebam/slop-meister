"""Assign a session's time to spine stages and to who was working or waiting."""

from dataclasses import dataclass

from slopmeister.threads.timing.events import TEST_KINDS, WAIT_KINDS, Session

STAGES = (
    "resume", "frame", "answer", "plan-review", "implement", "proof", "test-guide",
    "tester", "ship", "diff-review", "fix-pass", "accept", "finalize",
)  # fmt: skip
RANK = {name: index for index, name in enumerate(STAGES)}
CATEGORIES = ("model", "tool", "gate", "wait_process", "approval", "wait_operator")
COMMAND_STAGE = {
    "review-plan": "plan-review",
    "tester-launch": "tester",
    "tester-run": "tester",
    "ship": "ship",
    "review-diff": "diff-review",
}
# A turn with no end record is over once the log stays silent this long before the next message.
SILENT_TURN_END = 300.0
# Procedures are read in batches, so a proof marker counts only this long after building began.
BUILD_SECONDS = 60.0


@dataclass
class _Machine:
    """Stages only move forward, and each move needs an action, never a procedure being read."""

    stage: str
    entered: float
    # A closing report before the diff review began is a halt, the handoff comes after it.
    reviewed: float
    answered: bool = False
    plan_done: bool = False
    diff_done: bool = False

    def on_turn(self, when: float, report: bool) -> str | None:
        if self.stage == "frame":
            return "answer"
        tested = RANK[self.stage] >= RANK["tester"] and when >= self.reviewed
        return "accept" if report and tested else None

    def on_user(self, when: float, kind: str) -> str | None:
        self.answered = self.answered or kind == "operator"
        return "finalize" if kind == "finalize" else None

    def on_command(self, when: float, kind: str) -> str | None:
        if kind == "gate-full" and self.stage == "implement":
            return "proof"
        if kind in TEST_KINDS and self.stage == "plan-review" and self.plan_done:
            return "implement"
        return COMMAND_STAGE.get(kind)

    def on_done(self, when: float, kind: str) -> None:
        self.plan_done = self.plan_done or kind == "review-plan"
        self.diff_done = self.diff_done or kind == "review-diff"

    def on_skill(self, when: float, name: str) -> str | None:
        if name == "local-qa":
            return self.on_edit(when, "validation")
        starts = name in ("implement", "execute-plan")
        return "implement" if starts and self.stage == "plan-review" and self.plan_done else None

    def on_edit(self, when: float, kind: str) -> str | None:
        if kind == "guide":
            return "test-guide"
        if kind == "validation":
            built = self.stage == "implement" and when - self.entered > BUILD_SECONDS
            return "proof" if built else None
        if self.stage == "diff-review" and self.diff_done:
            return "fix-pass"
        begins = self.stage in ("plan-review", "resume") or (
            self.stage == "answer" and self.answered
        )
        return "implement" if begins else None


def _events(session: Session) -> list[tuple[float, int, str, object]]:
    events: list[tuple[float, int, str, object]] = []
    events += [(turn.end, 0, "turn", turn.report) for turn in session.turns]
    events += [(when, 1, "skill", name) for when, name in session.skills]
    events += [(command.start, 1, "command", command.kind) for command in session.commands]
    events += [(command.end, 1, "done", command.kind) for command in session.commands]
    events += [(when, 1, "edit", kind) for when, kind in session.edits]
    events += [(user.when, 2, "user", user.kind) for user in session.users]
    return sorted(events, key=lambda event: event[:2])


def stage_changes(session: Session) -> list[tuple[float, str]]:
    start = min(session.activity)
    reviews = [c.start for c in session.commands if c.kind == "review-diff"]
    stage = "resume" if session.resumed else "frame"
    machine = _Machine(stage, start, min(reviews, default=start))
    changes = [(start, machine.stage)]
    for when, _, kind, value in _events(session):
        target = getattr(machine, "on_" + kind)(when, value)
        if target and RANK[target] > RANK[machine.stage]:
            machine.stage, machine.entered = target, when
            changes.append((when, target))
    return changes


def turns(session: Session) -> list[tuple[float, float, str]]:
    """Worker turns as start, end and the kind of message that started each."""
    events = [(user.when, 0, user.kind, 0.0) for user in session.users if user.kind != "interrupt"]
    events += [(turn.end, 1, "end", turn.seconds) for turn in session.turns]
    found: list[tuple[float, float, str]] = []
    opened: tuple[float, str] | None = None
    for when, _, kind, seconds in sorted(events):
        if kind == "end":
            start, starter = opened or (when - seconds, "operator")
            found.append((min(start, when), when, starter))
            opened = None
            continue
        quiet = _silent_end(session, opened[0], when) if opened else None
        if opened and quiet:
            found.append((opened[0], quiet, opened[1]))
        if opened is None or quiet:
            opened = (when, kind)
    last = max(session.activity)
    if opened and last > opened[0]:
        found.append((opened[0], last, opened[1]))
    return found


def _silent_end(session: Session, start: float, until: float) -> float | None:
    """When a turn that left no end record stopped, or None while it is still running."""
    quiet = max((moment for moment in session.activity if start <= moment < until), default=start)
    busy = any(c.start <= quiet + 1 and c.end >= until - 1 for c in session.commands)
    return quiet if until - quiet > SILENT_TURN_END and not busy else None


def spans(session: Session) -> list[tuple[float, float, str]]:
    """Turns and the idle gaps between them, each gap named for what it waited on."""
    found: list[tuple[float, float, str]] = []
    previous = min(session.activity)
    for begin, end, starter in sorted(turns(session)):
        begin = max(begin, previous)
        if begin > previous:
            waited = "wait_process" if starter == "notify" else "wait_operator"
            found.append((previous, begin, waited))
        if end > begin:
            found.append((begin, end, "turn"))
        previous = max(previous, end)
    return found


def _category(session: Session, base: str, middle: float) -> str:
    if base != "turn":
        return base
    if any(begin <= middle < end for begin, end in session.approvals):
        return "approval"
    kinds = {c.kind for c in session.commands if c.start <= middle < c.end}
    if "gate-full" in kinds:
        return "gate"
    busy = "tool" if kinds - WAIT_KINDS else "wait_process"
    return busy if kinds else "model"


def _points(session: Session, parts: list, changes: list) -> list[float]:
    points = {point for begin, end, _ in parts for point in (begin, end)}
    points |= {point for c in session.commands for point in (c.start, c.end)}
    points |= {point for span in session.approvals for point in span}
    return sorted(points | {when for when, _ in changes})


def account(session: Session) -> dict:
    """Seconds per stage and category, tokens per stage, and when each stage began."""
    changes, parts = stage_changes(session), spans(session)
    seconds = {stage: dict.fromkeys(CATEGORIES, 0.0) for stage in STAGES}
    points = _points(session, parts, changes)
    for left, right in zip(points, points[1:], strict=False):
        middle = (left + right) / 2
        base = next((kind for begin, end, kind in parts if begin <= middle < end), None)
        if base:
            stage = [name for when, name in changes if when <= middle][-1]
            seconds[stage][_category(session, base, middle)] += right - left
    tokens = {stage: [0, 0] for stage in STAGES}
    for when, taken, written in session.tokens:
        stage = ([name for at, name in changes if at <= when] or [changes[0][1]])[-1]
        tokens[stage][0] += taken
        tokens[stage][1] += written
    return {"seconds": seconds, "tokens": tokens, "changes": changes}
