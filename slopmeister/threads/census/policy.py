"""Retrospective threshold decisions and the original compaction replay model."""

from collections import Counter
import statistics

from slopmeister.threads.census.records import Interval, Session, number, total
from slopmeister.threads.census.report import notes_size, quantiles

LIMITS = (200_000, 300_000, 400_000)
DEFAULT_THRESHOLDS = {
    "debloat_bytes": 65_536,
    "compact_tokens": {"claude": 200_000, "codex": 300_000},
    "redispatch_compactions": 3,
}


def decide(state: dict, thresholds: dict) -> list[tuple[str, str]]:
    actions = []
    context = number(state.get("context"))
    limit = thresholds["compact_tokens"].get(state.get("client"))
    if context is not None and limit and context >= limit:
        actions.append(("native-compaction", "client"))
    if state.get("protected_window"):
        return actions
    notes = number(state.get("notes_bytes"))
    if notes is not None and notes > thresholds["debloat_bytes"]:
        actions.append(("trim-notes", "session"))
    safe = (
        state.get("state") == "done"
        and "wait" in state
        and state["wait"] is None
        and not state.get("question_open")
    )
    compactions = number(state.get("compactions"))
    if safe and compactions is not None and compactions >= thresholds["redispatch_compactions"]:
        actions.append(("recommend-redispatch", "manager-or-dispatcher"))
    return actions


def decisions(sessions: list[Session], thresholds: dict) -> dict:
    counts = Counter()
    unknown_notes = 0
    unknown_context = 0
    for session in sessions:
        notes = notes_size(session.cwd)
        unknown_notes += notes is None
        state = {
            "client": session.client,
            "context": session.requests[-1].context,
            "compactions": len(session.compactions),
            "notes_bytes": notes,
            "state": "done",
            "wait": None,
            "question_open": False,
        }
        unknown_context += number(state["context"]) is None
        counts.update("/".join(action) for action in decide(state, thresholds))
    return {
        "policy": "historical-recommendation",
        "thresholds": thresholds,
        "state_basis": "retrospective assumed ended turn, null wait and no open question",
        "recorded_states": len(sessions),
        "notes_unknown": unknown_notes,
        "context_unknown": unknown_context,
        "counts": dict(sorted(counts.items())),
    }


def ratios(sessions: list[Session], interval: Interval) -> dict[str, float | None]:
    result = {}
    for client in ("claude", "codex"):
        values = [
            c.after / c.before
            for s in sessions
            if s.client == client
            for c in s.compactions
            if interval.contains(c.timestamp)
            and c.before is not None
            and c.before > 0
            and c.after is not None
        ]
        result[client] = statistics.median(values) if values else None
    return result


def _simulate(session: Session, ratio: float, limit: int) -> tuple[int, int, int]:
    drop = extra = gross = cost = 0
    for request in session.requests:
        if request.after_compaction:
            drop = 0
        simulated = max(0, request.context - drop)
        if simulated >= limit:
            extra += 1
            cost += simulated
            after = int(simulated * ratio)
            drop += simulated - after
            simulated = after
        gross += request.context - simulated
    return gross, cost, extra


def replay(sessions: list[Session], ratio: float | None, limit: int) -> dict | None:
    contexts = [q.context if q.identity_known else None for s in sessions for q in s.requests]
    original = total(contexts)
    if ratio is None or original is None:
        return None
    observations = [_simulate(session, ratio, limit) for session in sessions]
    extras = [extra for _, _, extra in observations if extra]
    gross = sum(value[0] for value in observations)
    cost = sum(value[1] for value in observations)
    totals = [
        value[2] + len(session.compactions)
        for value, session in zip(observations, sessions, strict=True)
    ]
    return {
        "limit": limit,
        "sessions_affected": len(extras),
        "extra_compactions": sum(value[2] for value in observations),
        "median_extra_per_affected": statistics.median(extras) if extras else 0,
        "gross_saved": gross,
        "compaction_cost": cost,
        "net_saved": gross - cost,
        "net_share": round((gross - cost) / original, 4) if original else None,
        "compactions_per_session": quantiles(totals),
    }


def input_shares(sessions: list[Session]) -> dict:
    result = {}
    for client in ("claude", "codex"):
        values = [
            q.context if q.identity_known else None
            for s in sessions
            if s.client == client
            for q in s.requests
        ]
        original = total(values)
        result[client] = {
            limit: round(sum(v for v in values if v >= limit) / original, 4) if original else None
            for limit in LIMITS
        }
    return result
