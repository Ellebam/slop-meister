"""Local and GitHub claim inventory classification."""

from dataclasses import dataclass, field
from pathlib import Path
import subprocess

from slopmeister.claims import evidence, github
from slopmeister.threads import occupants


@dataclass
class Classification:
    owners: list[dict] = field(default_factory=list)
    dependencies: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class WorkspaceState:
    mapped: dict
    finished: dict
    warnings: list[str] = field(default_factory=list)


@dataclass
class ResultState:
    reasons: list[str]
    blocked: bool
    owned: bool
    names: list[str]
    category: str = ""


def classify(item: dict, values: Classification) -> dict:
    names = github.labels(item)
    blocked = "blocked" in names or any(
        dependency.get("state") == "open" for dependency in values.dependencies
    )
    owned = github.CLAIM in names or bool(values.owners)
    reasons = list(values.errors)
    bad_owner = any(
        owner["phase"] != "claimed" or not owner.get("delivery") for owner in values.owners
    )
    if len(values.owners) > 1 or bad_owner or (values.owners and github.CLAIM not in names):
        reasons.append("local worker and GitHub claim disagree")
    result = ResultState(reasons, blocked, owned, names)
    result.category = _category(item["state"], result)
    return _row(item, values, result)


def _category(state: str, result: ResultState) -> str:
    if state == "closed":
        return "closed"
    if result.reasons:
        return "unknown"
    if result.blocked:
        return "blocked"
    return "claimed" if result.owned else "available"


def _row(item: dict, values: Classification, result: ResultState) -> dict:
    return {
        "number": item["number"],
        "title": item.get("title", ""),
        "category": result.category,
        "owned": result.owned,
        "blocked": result.blocked,
        "blocked_by": [
            value.get("html_url", value.get("number"))
            for value in values.dependencies
            if value.get("state") == "open"
        ],
        "reasons": result.reasons,
        "recommend": result.category == "available",
        "priority": "priority:high" in result.names,
    }


def census(workspace: Path | str) -> list:
    try:
        processes = occupants.census(str(workspace))
    except occupants.CensusError as error:
        raise ValueError(str(error)) from error
    return [process for process in processes if process.inside]


def _workspace_inventory(ctx: github.Repository) -> tuple[list[dict], list[str]]:
    """Receipts decide ownership, a worktree or its processes only ever add a warning."""
    records = evidence.receipts(ctx)
    state = WorkspaceState(
        {value["workspace"]: value for value in records if value["phase"] in github.ACTIVE},
        {value["workspace"]: value for value in records if value["phase"] not in github.ACTIVE},
    )
    for workspace in github.workspaces(ctx):
        if not workspace.is_dir():
            state.warnings.append("worktree directory is missing at " + str(workspace))
        elif workspace != ctx.root and str(workspace) not in state.mapped:
            _inspect_workspace(workspace, state)
    return records, state.warnings


def _inspect_workspace(workspace: Path, state: WorkspaceState) -> None:
    try:
        _classify_unmapped(workspace, census(workspace), state)
    except (ValueError, OSError) as error:
        state.warnings.append(f"cannot inspect worktree at {workspace}: {error}")


def _classify_unmapped(workspace: Path, processes: list, state: WorkspaceState):
    done = state.finished.get(str(workspace), {})
    proof = done.get("delivery", {})
    matching = all(
        process.pid == proof.get("pid") and process.signature == proof.get("pid_start")
        for process in processes
    )
    finishing = done.get("phase") == "closed" and proof and matching
    if finishing:
        state.warnings.append("finishing worker at " + str(workspace))
    elif processes or _has_notes(workspace, state.finished):
        state.warnings.append("unmapped worker at " + str(workspace))
    else:
        state.warnings.append("unassociated worktree at " + str(workspace))


def _has_notes(workspace: Path, finished: dict) -> bool:
    return str(workspace) not in finished and any(
        path.stat().st_size for path in workspace.glob("*-NOTES.md")
    )


def _dependencies(ctx: github.Repository, item: dict, failures: list[str]) -> list[dict]:
    try:
        endpoint = f"issues/{github.issue_number(item['number'])}/dependencies/blocked_by"
        values = github.pages(ctx, endpoint)
        if any(value.get("state") not in ("open", "closed") for value in values):
            raise ValueError("dependency state is unknown")
        return values
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        failures.append(str(error))
        return []


def backlog(ctx: github.Repository) -> dict:
    try:
        records, warnings = _workspace_inventory(ctx)
        errors = []
    except (ValueError, OSError) as error:
        records, errors, warnings = [], [str(error)], []
    rows = []
    for item in github.pages(ctx, "issues?state=open"):
        if "pull_request" in item:
            continue
        failures = list(errors)
        dependencies = _dependencies(ctx, item, failures)
        owners = [
            value
            for value in records
            if value["issue"] == item["number"] and value["phase"] in github.ACTIVE
        ]
        rows.append(classify(item, Classification(owners, dependencies, failures)))
    rows.sort(key=lambda row: (not row["priority"], row["number"]))
    recommended = [row["number"] for row in rows if row["recommend"]]
    warnings = [warning + ", does not block dispatch" for warning in warnings]
    return {"repository": ctx.name, "issues": rows, "recommend": recommended, "warnings": warnings}
