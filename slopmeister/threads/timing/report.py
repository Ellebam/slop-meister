"""One JSON row per session, and the Markdown table and summary printed from such rows."""

import os
import time

from slopmeister.threads.timing.events import TEST_KINDS, Session
from slopmeister.threads.timing.stages import CATEGORIES, STAGES, account

WORKING = ("model", "tool", "gate", "wait_process", "approval")
HEAD = (
    "Session", "Host", "Tool, model", "Lines", "Files", "Start UTC",
    *(stage[:6] for stage in STAGES), "Op wait", "Tok out k / in M",
    "G", "T", "M", "A", "I", "R", "E", "H",
)  # fmt: skip


def _counts(session: Session, changes: list[tuple[float, str]]) -> dict:
    began = {stage: when for when, stage in reversed(changes)}
    go = min((when for stage, when in began.items() if stage not in ("resume", "frame", "answer")),
             default=float("inf"))  # fmt: skip
    handoff = began.get("accept", float("inf"))
    kinds = [user.kind for user in session.users]
    before_go = [user for user in session.users if user.kind == "operator" and user.when < go]
    gates = [c for c in session.commands if c.kind == "gate-full"]
    return {
        "operator_replies": kinds.count("operator"),
        "replies_before_go": len(before_go),
        "explain_replies_before_go": sum(user.explains for user in before_go),
        "relays": kinds.count("relay"),
        "interrupts": kinds.count("interrupt"),
        "approvals": len(session.approvals),
        "approval_seconds": round(sum(end - begin for begin, end in session.approvals)),
        "halts": sum(1 for turn in session.turns if turn.report and turn.end < handoff),
        "full_gates": len(gates),
        "full_gate_seconds": round(sum(c.end - c.start for c in gates)),
        "failed_full_gates": sum(c.failed for c in gates),
        "test_runs": sum(1 for c in session.commands if c.kind in TEST_KINDS) - len(gates),
        "checksums": sum(1 for c in session.commands if c.kind == "checksum"),
        "compactions": session.compactions,
        "source_files": len(session.sources),
        "lines": session.lines,
    }


def row(session: Session, host: str) -> dict:
    """Timings, counts and the session name. Never text from the log."""
    result = account(session)
    cwd = session.cwd.rstrip("/")
    repo = os.path.basename(cwd.split("/.worktrees/")[0]) if "/.worktrees/" in cwd else ""
    seconds = {
        stage: {category: round(value) for category, value in spent.items() if value >= 1}
        for stage, spent in result["seconds"].items()
    }
    return {
        "host": host, "tool": session.tool, "model": session.model, "effort": session.effort,
        "session": session.session_id, "name": os.path.basename(cwd), "repo": repo,
        "resumed": session.resumed,
        "start": round(min(session.activity)), "end": round(max(session.activity)),
        "stages": {stage: spent for stage, spent in seconds.items() if spent},
        "tokens": {stage: pair for stage, pair in result["tokens"].items() if any(pair)},
        "entered": {stage: round(when) for when, stage in reversed(result["changes"])},
        "tester_runs": session.tester_runs,
        "counts": _counts(session, result["changes"]),
        "cost_usd": round(session.cost_usd, 2),
    }  # fmt: skip


def _minutes(seconds: float) -> str:
    return str(round(seconds / 60)) if seconds >= 30 else ""


def _cells(item: dict, name: str) -> list[str]:
    stages, counts = item["stages"], item["counts"]
    worked = [sum(stages.get(stage, {}).get(c, 0) for c in WORKING) for stage in STAGES]
    waited = sum(spent.get("wait_operator", 0) for spent in stages.values())
    taken = sum(pair[0] for pair in item["tokens"].values())
    written = sum(pair[1] for pair in item["tokens"].values())
    model = item["model"].removeprefix("claude-").removeprefix("gpt-")
    return [
        name + (" (resumed)" if item["resumed"] else ""), item["host"],
        f"{item['tool']}, {model}", str(counts["lines"] or ""), str(counts["source_files"] or ""),
        time.strftime("%m-%d %H:%M", time.gmtime(item["start"])),
        *(_minutes(value) for value in worked), _minutes(waited),
        f"{round(written / 1000)} / {taken / 1e6:.0f}", str(counts["full_gates"]),
        "".join(verdict[:1].upper() for verdict in item["tester_runs"]),
        *(str(counts[key]) for key in ("checksums", "approvals", "interrupts")),
        *(str(counts[key]) for key in ("operator_replies", "explain_replies_before_go", "halts")),
    ]  # fmt: skip


def table(rows: list[dict], show: set[str]) -> str:
    """The session table. A session of a repository outside `show` gets a number for a name."""
    numbered: dict[tuple[str, str], str] = {}
    lines = ["| " + " | ".join(HEAD) + " |", "|" + "---|" * len(HEAD)]
    for item in sorted(rows, key=lambda item: item["start"]):
        name = item["name"]
        if item["repo"] not in show:
            name = numbered.setdefault((item["host"], name), f"other-{len(numbered) + 1}")
        lines.append("| " + " | ".join(_cells(item, name)) + " |")
    return "\n".join(lines) + "\n"


def summary(rows: list[dict]) -> str:
    """Hours per stage and category over all rows, with each stage's share of the total."""
    hours = {stage: dict.fromkeys(CATEGORIES, 0.0) for stage in STAGES}
    for item in rows:
        for stage, spent in item["stages"].items():
            for category, value in spent.items():
                hours[stage][category] += value / 3600
    total = sum(sum(spent.values()) for spent in hours.values()) or 1.0
    head = ("Stage", *CATEGORIES, "total", "share")
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for stage, spent in hours.items():
        cells = [f"{spent[category]:.1f}" for category in CATEGORIES]
        both = sum(spent.values())
        lines.append(
            f"| {stage} | " + " | ".join(cells) + f" | {both:.1f} | {100 * both / total:.1f}% |"
        )
    cells = [f"{sum(spent[category] for spent in hours.values()):.1f}" for category in CATEGORIES]
    lines.append("| all | " + " | ".join(cells) + f" | {total:.1f} | 100.0% |")
    return f"{len(rows)} sessions\n\n" + "\n".join(lines) + "\n"
