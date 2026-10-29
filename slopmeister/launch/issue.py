"""Issue lifecycle calls for a launch, with its issue lock held through delivery."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import subprocess

from slopmeister.claims import evidence, github, lifecycle, locks
from slopmeister.launch import arguments
from slopmeister.launch.model import Delivery, Launch, die


def _workspace(launch: Launch) -> Path:
    return Path(launch.repo or "") / ".worktrees" / launch.name


def associate(launch: Launch) -> None:
    workspace = _workspace(launch)
    if launch.repo is None or not (launch.redispatch or launch.abandon) or not workspace.is_dir():
        return
    path = evidence.receipt_path(workspace)
    saved = str(github.issue_number(evidence.read(path)["issue"])) if path.exists() else ""
    if launch.issue_id and saved and launch.issue_id != saved:
        raise die("explicit issue differs from saved worker association")
    launch.issue_id = launch.issue_id or saved


def claim(launch: Launch) -> None:
    """The open descriptor holds the OS lock until this launcher exits."""
    launch.claim_model = launch.model
    if not launch.issue_id:
        return
    workspace = _workspace(launch)
    try:
        allowed = evidence.eligible(launch.plot, workspace)
    except (ValueError, OSError, KeyError, TypeError) as error:
        raise die(f"issue permission inspection failed; preserve the worker: {error}") from error
    if not allowed:
        return
    launch.claim_managed = True
    ctx = github.context(launch.repo, launch.plot)
    number = github.issue_number(launch.issue_id)
    launch.claim_target = ctx.name
    launch.lock_fd = os.open(locks.lock_path(ctx, number), os.O_RDWR | os.O_NOFOLLOW)
    run = lifecycle.Run(ctx, None, None, number, False)
    with lifecycle.locked(run, workspace, launch.lock_fd):
        if not launch.abandon:
            lifecycle.preflight(ctx, lifecycle.Preflight(number, workspace, launch.redispatch))
    if not launch.model_set:
        launch.claim_model = arguments.claim_model(launch)


def require_managed_abandon(launch: Launch) -> None:
    if launch.abandon and not launch.claim_managed:
        raise die("abandon requires a saved issue in an eligible project")


def initialize(launch: Launch) -> None:
    if not launch.claim_managed:
        return
    ctx = github.context(launch.repo, launch.plot)
    number = github.issue_number(launch.issue_id)
    run = lifecycle.Run(ctx, None, None, number, False)
    with lifecycle.locked(run, launch.wt, launch.lock_fd):
        lifecycle.initialize(ctx, lifecycle.Initialization(launch.wt, number, launch.kickoff_file))


def abandon(launch: Launch, close: Callable[[Launch], None]) -> None:
    run = lifecycle.resolve(launch.wt)
    handoff = Path(launch.handoff)
    with lifecycle.locked(run, launch.wt, launch.lock_fd) as current:
        if current.saved["phase"] == "released":
            print("already released")
            return
        lifecycle.abandon(current.ctx, lifecycle.Abandonment(current.path, current.saved, handoff))
    print("abandonment recorded")
    close(launch)
    with lifecycle.locked(run, launch.wt, launch.lock_fd) as current:
        operation = lifecycle.Abandonment(current.path, current.saved, handoff, after=True)
        lifecycle.abandon(current.ctx, operation)
    print("claim released")


def bind(launch: Launch, delivery: Delivery) -> None:
    if not launch.claim_managed:
        return
    try:
        run = lifecycle.resolve(launch.wt)
        with lifecycle.locked(run, launch.wt, launch.lock_fd) as current:
            current.saved["delivery"] = evidence.proof(
                launch.tool, delivery.session, delivery.pid, Path(delivery.evidence)
            )
            evidence.delivery_evidence(current.saved)
            evidence.save(current.path, current.saved)
    except (ValueError, OSError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        raise die(
            "worker delivered, claim unconfirmed; preserve the worker and inspect its evidence: "
            + str(error)
        ) from error


def confirm(launch: Launch) -> None:
    if launch.claim_managed:
        run = lifecycle.resolve(launch.wt)
        with lifecycle.locked(run, launch.wt, launch.lock_fd) as current:
            lifecycle.confirm(current.ctx, current.path, current.saved)
        print(f"issue claimed: {current.ctx.name}#{current.number}")
