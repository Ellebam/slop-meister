"""Issue claims for a launch, through the claims command in-process with its lock held here."""

from __future__ import annotations

from collections.abc import Callable
import os

from slopmeister.claims import cli as claims
from slopmeister.launch import arguments
from slopmeister.launch.model import Delivery, Launch, Stop, call, die


def _workspace(launch: Launch) -> str:
    return f"{launch.repo or ''}/.worktrees/{launch.name}"


def _claims(launch: Launch, action: str, *options: str, capture: bool = False) -> str:
    locked = ("--lock-fd", str(launch.lock_fd)) if launch.lock_fd is not None else ()
    argv = [action, *options, *locked]
    return call(claims.main, argv, capture=capture)


def associate(launch: Launch) -> None:
    if launch.repo is None or not (launch.redispatch or launch.abandon):
        return
    saved = _claims(launch, "association", "--workspace", _workspace(launch), capture=True)
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
        permission = _claims(
            launch, "eligible", "--plot", launch.plot, "--workspace", workspace, capture=True
        )
    except Stop as error:
        raise die("issue permission inspection failed; preserve the worker") from error
    if permission != "allow":
        return
    launch.claim_managed = True
    scope = ("--repo", str(launch.repo), "--plot", launch.plot)
    launch.claim_target = _claims(launch, "target", *scope, capture=True)
    path = _claims(launch, "lock-path", *scope, "--issue-id", launch.issue_id, capture=True)
    launch.lock_fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    _claims(launch, "lock", *scope, "--issue-id", launch.issue_id)
    if not launch.abandon:
        recovery = ("--redispatch",) if launch.redispatch else ()
        preflight = ("--workspace", workspace, "--issue-id", launch.issue_id, *recovery)
        _claims(launch, "preflight", *scope, *preflight)
    if not launch.model_set:
        launch.claim_model = arguments.claim_model(launch)


def require_managed_abandon(launch: Launch) -> None:
    if launch.abandon and not launch.claim_managed:
        raise die("abandon requires a saved issue in an eligible project")


def initialize(launch: Launch) -> None:
    if launch.claim_managed:
        _claims(
            launch,
            "initialize",
            *("--repo", str(launch.repo), "--plot", launch.plot, "--workspace", str(launch.wt)),
            *("--issue-id", launch.issue_id, "--kickoff", str(launch.kickoff_file)),
        )


def abandon(launch: Launch, close: Callable[[Launch], None]) -> None:
    handoff = ("--workspace", str(launch.wt), "--handoff", launch.handoff)
    state = _claims(launch, "abandon-prepare", *handoff, capture=True)
    print(state)
    if state == "already released":
        return
    close(launch)
    _claims(launch, "abandon-complete", *handoff)


def bind(launch: Launch, delivery: Delivery) -> None:
    if not launch.claim_managed:
        return
    session = ("--tool", launch.tool, "--session", delivery.session, "--pid", str(delivery.pid))
    try:
        _claims(
            launch,
            "bind",
            *("--workspace", str(launch.wt), *session, "--evidence", delivery.evidence),
        )
    except Stop as error:
        raise die(
            "worker delivered, claim unconfirmed; preserve the worker and inspect its evidence"
        ) from error


def confirm(launch: Launch) -> None:
    if launch.claim_managed:
        _claims(launch, "confirm", "--workspace", str(launch.wt))
