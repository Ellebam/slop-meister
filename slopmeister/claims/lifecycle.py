"""Issue claim classification, inventory and lifecycle actions."""

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from urllib.parse import quote

from slopmeister.claims import evidence, github, inventory
from slopmeister.paths import main_checkout


@dataclass
class Initialization:
    workspace: Path
    number: int
    kickoff: Path
    delivery: dict | None = None


@dataclass
class Abandonment:
    path: Path
    saved: dict
    handoff: Path
    after: bool = False


@dataclass
class Closure:
    path: Path
    saved: dict
    reason: str = "completed"


@dataclass
class Preflight:
    number: int
    workspace: Path
    redispatch: bool


def other_owners(ctx: github.Repository, number: int, workspace: Path | str) -> list[dict]:
    return [
        value
        for value in evidence.receipts(ctx)
        if value["issue"] == number
        and value["phase"] in github.ACTIVE
        and value["workspace"] != str(workspace)
    ]


def confirm(ctx: github.Repository, path: Path, saved: dict) -> None:
    try:
        _confirm(ctx, path, saved)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("worker delivered, claim unconfirmed: " + str(error)) from error


def _confirm(ctx: github.Repository, path: Path, saved: dict) -> None:
    if saved["phase"] not in ("pending", "claimed"):
        raise ValueError("claim recovery cannot restart this lifecycle")
    evidence.delivery_evidence(saved)
    if other_owners(ctx, saved["issue"], saved["workspace"]):
        raise ValueError("another preserved worker owns this issue")
    item = github.remote_issue(ctx, saved["issue"])
    if item["state"] != "open":
        raise ValueError("issue is closed")
    _add_claim(ctx, (path, saved), item)
    if github.CLAIM not in github.labels(github.remote_issue(ctx, saved["issue"])):
        raise ValueError("claim readback disagrees")
    saved.update(phase="claimed")
    evidence.save(path, saved)


def _add_claim(ctx: github.Repository, receipt: tuple[Path, dict], item: dict) -> None:
    path, saved = receipt
    if github.CLAIM in github.labels(item):
        if saved["phase"] != "claimed" and not saved.get("claim_attempted"):
            raise ValueError("claim appeared without this worker recording a claim attempt")
        return
    available = github.pages(ctx, "labels")
    if not any(value.get("name") == github.CLAIM for value in available):
        payload = {
            "name": github.CLAIM,
            "color": "1d76db",
            "description": "A delivered agent worker owns this issue",
        }
        github.request(ctx, github.Request("labels", "POST", payload))
    saved["claim_attempted"] = True
    evidence.save(path, saved)
    github.request(
        ctx, github.Request(f"issues/{saved['issue']}/labels", "POST", {"labels": [github.CLAIM]})
    )


def close_issue(ctx: github.Repository, operation: Closure) -> None:
    path, saved = operation.path, operation.saved
    invalid = saved["phase"] not in ("claimed", "closing", "closed")
    if invalid or other_owners(ctx, saved["issue"], saved["workspace"]):
        raise ValueError("finalize requires this verified owning worker")
    evidence.delivery_evidence(saved)
    item = github.remote_issue(ctx, saved["issue"])
    if item["state"] != "closed":
        saved.update(phase="closing")
        evidence.save(path, saved)
        payload = {"state": "closed", "state_reason": operation.reason.replace("-", "_")}
        github.request(ctx, github.Request(f"issues/{saved['issue']}", "PATCH", payload))
    if github.remote_issue(ctx, saved["issue"])["state"] != "closed":
        raise ValueError("issue close unconfirmed")
    remove_label(ctx, saved["issue"])
    saved.update(phase="closed")
    evidence.save(path, saved)


def remove_label(ctx: github.Repository, number: int) -> None:
    if github.CLAIM in github.labels(github.remote_issue(ctx, number)):
        endpoint = f"issues/{number}/labels/{quote(github.CLAIM, safe='')}"
        github.request(ctx, github.Request(endpoint, "DELETE"))
    if github.CLAIM in github.labels(github.remote_issue(ctx, number)):
        raise ValueError("claim release unconfirmed")


def abandon(ctx: github.Repository, operation: Abandonment) -> None:
    recovery = evidence.safe_path(operation.handoff).resolve()
    saved = operation.saved
    workspace = Path(saved["workspace"])
    if not recovery.is_relative_to(workspace) or not recovery.read_text().strip():
        raise ValueError("abandon requires a nonempty handoff inside the worker workspace")
    invalid = saved["phase"] not in ("claimed", "pending", "abandoning")
    if invalid or other_owners(ctx, saved["issue"], saved["workspace"]):
        raise ValueError("abandon requires the exact owning workspace")
    current = {"path": str(recovery), "sha256": evidence.digest(recovery)}
    if saved.get("handoff", current) != current:
        raise ValueError("saved abandonment handoff changed")
    _abandon_worker_check(ctx, saved, operation.after)
    saved.update(phase="abandoning", handoff=current)
    evidence.save(operation.path, saved)
    if operation.after:
        remove_label(ctx, saved["issue"])
        saved.update(phase="released")
        evidence.save(operation.path, saved)


def _abandon_worker_check(ctx: github.Repository, saved: dict, after: bool) -> None:
    if github.remote_issue(ctx, saved["issue"])["state"] != "open":
        raise ValueError("abandon will not reopen a closed issue")
    processes = inventory.census(saved["workspace"])
    proof = saved.get("delivery", {})
    if after and processes:
        raise ValueError("worker still occupies workspace; claim preserved")
    wrong_process = any(
        process.pid != proof.get("pid") or process.signature != proof.get("pid_start")
        for process in processes
    )
    if not after and wrong_process:
        raise ValueError("worker identity disagrees; claim preserved")


def initialize(ctx: github.Repository, operation: Initialization) -> None:
    workspace = operation.workspace
    path = evidence.receipt_path(workspace)
    previous = evidence.read(path) if path.exists() else {}
    if previous and previous.get("issue") != operation.number:
        raise ValueError("workspace already belongs to a different issue")
    state = evidence.read(path.with_name("state.json"))
    if state["ship_target"]["remote"] != ctx.remote or not evidence.eligible(ctx.plot, workspace):
        raise ValueError("prepared workspace does not allow this issue association")
    saved = _new_receipt(ctx, operation, previous)
    if operation.delivery is not None:
        saved["delivery"] = operation.delivery
        evidence.delivery_evidence(saved)
    evidence.save(path, saved, exclusive=operation.delivery is not None)


def _new_receipt(ctx: github.Repository, operation: Initialization, previous: dict) -> dict:
    history = previous.get("previous_deliveries", [])
    if previous.get("delivery"):
        history += [
            {"delivery": previous["delivery"], "kickoff_sha256": previous["kickoff_sha256"]}
        ]
    return {
        "version": 1,
        "repository": ctx.name,
        "issue": operation.number,
        "workspace": str(operation.workspace.resolve()),
        "plot": ctx.plot,
        "tasks": "github",
        "slopmeister": str(main_checkout()),
        "kickoff": str(operation.kickoff.resolve()),
        "kickoff_sha256": evidence.digest(operation.kickoff, kickoff=True),
        "previous_deliveries": history,
        "phase": "claimed" if previous.get("phase") == "claimed" else "pending",
    }


def preflight(ctx: github.Repository, operation: Preflight) -> None:
    number, workspace = operation.number, operation.workspace
    if other_owners(ctx, number, workspace):
        raise ValueError("issue already has another preserved worker")
    item = github.remote_issue(ctx, number)
    if item["state"] != "open":
        raise ValueError("issue is closed")
    if _known_redispatch(ctx, operation, item):
        return
    if not operation.redispatch and github.CLAIM in github.labels(item):
        raise ValueError("issue is already claimed")
    row = next(
        (value for value in inventory.backlog(ctx)["issues"] if value["number"] == number), None
    )
    if row is None:
        raise ValueError("issue missing from complete backlog")
    if row["category"] in ("unknown", "claimed") and not _own_pending(row, operation):
        raise ValueError("issue ownership is unknown; inspect before dispatch")
    if row["blocked"]:
        print("issue is blocked; proceeding with explicitly requested dispatch", file=sys.stderr)


def _known_redispatch(ctx: github.Repository, operation: Preflight, item: dict) -> bool:
    workspace, number = operation.workspace, operation.number
    if (
        not operation.redispatch
        or not workspace.exists()
        or not evidence.receipt_path(workspace).exists()
    ):
        return False
    _, _, saved = evidence.workspace_record(workspace, ctx.plot)
    if saved["issue"] != number:
        raise ValueError("redispatch issue differs from its saved association")
    if saved["phase"] == "claimed" and github.CLAIM in github.labels(item):
        return True
    if github.CLAIM in github.labels(item):
        raise ValueError("claim identity is unknown; inspect and reconcile before redispatch")
    return False


def _own_pending(row: dict, operation: Preflight) -> bool:
    return (
        operation.redispatch
        and row["category"] == "unknown"
        and row["reasons"] == ["local worker and GitHub claim disagree"]
    )
