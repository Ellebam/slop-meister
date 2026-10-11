"""Command-line interface for GitHub issue claims."""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys

from slopmeister.claims import arguments, evidence, github, inventory, lifecycle, locks


@dataclass
class Run:
    ctx: github.Repository
    path: Path | None
    saved: dict | None
    number: int
    legacy: bool


def _initial(args: argparse.Namespace) -> int | None:
    if args.action == "eligible":
        print("allow" if evidence.eligible(args.plot, args.workspace) else "deny")
        return 0
    if args.action == "association":
        if args.workspace.is_dir():
            path = evidence.receipt_path(args.workspace)
            if path.exists():
                print(github.issue_number(evidence.read(path)["issue"]))
        return 0
    return None


def _resolve(args: argparse.Namespace) -> Run:
    legacy = args.action == "reconcile" and not evidence.receipt_path(args.workspace).exists()
    if args.action in arguments.REPOSITORY_ACTIONS:
        root = args.repo if args.repo is not None else Path.cwd()
        try:
            ctx = github.context(root, args.plot)
        except ValueError as error:
            if args.repo is not None:
                raise
            raise ValueError(f"{error}; pass --repo to name the repository explicitly") from error
        return Run(ctx, None, None, args.issue_id, False)
    ctx, path, saved = evidence.workspace_record(args.workspace, args.plot, unassociated=legacy)
    number = args.issue_id if legacy else saved["issue"]
    if args.issue_id is not None and args.issue_id != number:
        raise ValueError("explicit issue differs from saved worker association")
    return Run(ctx, path, saved, number, legacy)


def _read_only(run: Run, args: argparse.Namespace) -> int | None:
    handler = READ_ONLY.get(args.action)
    if handler is None:
        return None
    handler(run, args)
    return 0


def _target(run: Run, args: argparse.Namespace) -> None:
    print(run.ctx.name)


def _lock_path(run: Run, args: argparse.Namespace) -> None:
    print(locks.lock_path(run.ctx, run.number))


def _backlog(run: Run, args: argparse.Namespace) -> None:
    _print_backlog(inventory.backlog(run.ctx), args.json)


def _inspect(run: Run, args: argparse.Namespace) -> None:
    processes = inventory.census(args.workspace)
    value = {"receipt": run.saved, "issue": github.remote_issue(run.ctx, run.number)}
    value.update(processes=[vars(process) for process in processes], evidence=str(run.path))
    print(json.dumps(value, indent=2))


READ_ONLY = {"target": _target, "lock-path": _lock_path, "backlog": _backlog, "inspect": _inspect}


def _print_backlog(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result))
        return
    for row in result["issues"]:
        print(f"{row['category']}: #{row['number']} " + json.dumps(row))
    for warning in result["warnings"]:
        print("warning: " + json.dumps(warning))


def _legacy(run: Run, args: argparse.Namespace) -> Run:
    current = evidence.workspace_record(args.workspace, args.plot, unassociated=True)
    if current[2] is not None:
        raise ValueError("association appeared while acquiring its lock; inspect before recovery")
    if not all((run.number, args.kickoff, args.tool, args.session, args.evidence, args.pid)):
        raise ValueError(
            "legacy recovery requires issue-id, kickoff, tool, session, evidence and pid"
        )
    item = github.remote_issue(run.ctx, run.number)
    conflicting = lifecycle.other_owners(run.ctx, run.number, args.workspace.resolve())
    if item["state"] != "open" or github.CLAIM in github.labels(item) or conflicting:
        raise ValueError("legacy recovery requires an open issue without another owner")
    proof = _proof(args)
    _verify_worker(args.workspace, proof, legacy=True)
    operation = lifecycle.Initialization(args.workspace, run.number, args.kickoff, proof)
    lifecycle.initialize(run.ctx, operation)
    return Run(run.ctx, run.path, evidence.read(run.path), run.number, False)


def _proof(args: argparse.Namespace) -> dict:
    signature = github.command(["ps", "-p", str(args.pid), "-o", "lstart=,comm="])
    return {
        "tool": args.tool,
        "session": args.session,
        "evidence": str(args.evidence.resolve()),
        "pid": args.pid,
        "pid_start": signature,
    }


def _verify_worker(workspace: Path, proof: dict, legacy: bool) -> None:
    """A legacy association needs a living worker, a reconcile only refuses a disagreeing one."""
    processes = inventory.census(workspace)
    wrong = (legacy and not processes) or any(
        process.pid != proof.get("pid") or process.signature != proof.get("pid_start")
        for process in processes
    )
    if wrong:
        raise ValueError(
            "legacy worker identity disagrees; preserve the worker"
            if legacy
            else "worker identity disagrees; claim unconfirmed"
        )


def _mutate(run: Run, args: argparse.Namespace) -> int:
    return MUTATIONS[args.action](run, args)


def _preflight(run: Run, args: argparse.Namespace) -> int:
    lifecycle.preflight(run.ctx, lifecycle.Preflight(run.number, args.workspace, args.redispatch))
    return 0


def _initialize(run: Run, args: argparse.Namespace) -> int:
    lifecycle.initialize(
        run.ctx, lifecycle.Initialization(args.workspace, run.number, args.kickoff)
    )
    return 0


def _bind(run: Run, args: argparse.Namespace) -> int:
    run.saved["delivery"] = _proof(args)
    evidence.delivery_evidence(run.saved)
    evidence.save(run.path, run.saved)
    return 0


def _confirm_action(run: Run, args: argparse.Namespace) -> int:
    _claim(run, args)
    return 0


def _close(run: Run, args: argparse.Namespace) -> int:
    lifecycle.close_issue(run.ctx, lifecycle.Closure(run.path, run.saved, args.reason))
    print(f"issue closed: {run.ctx.name}#{run.number}")
    return 0


def _noop(run: Run, args: argparse.Namespace) -> int:
    return 0


def _claim(run: Run, args: argparse.Namespace) -> None:
    if args.action == "reconcile":
        _verify_worker(args.workspace, run.saved.get("delivery", {}), legacy=False)
    lifecycle.confirm(run.ctx, run.path, run.saved)
    print(f"issue claimed: {run.ctx.name}#{run.number}")


def _abandon(run: Run, args: argparse.Namespace) -> int:
    if run.saved["phase"] == "released":
        print("already released")
        return 0
    after = args.action == "abandon-complete"
    operation = lifecycle.Abandonment(run.path, run.saved, args.handoff, after)
    lifecycle.abandon(run.ctx, operation)
    print("claim released" if after else "abandonment recorded")
    return 0


MUTATIONS = {
    "lock": _noop,
    "preflight": _preflight,
    "initialize": _initialize,
    "bind": _bind,
    "confirm": _confirm_action,
    "reconcile": _confirm_action,
    "close": _close,
    "abandon-prepare": _abandon,
    "abandon-complete": _abandon,
}


def _locked(run: Run, args: argparse.Namespace) -> int:
    if not evidence.eligible(run.ctx.plot, args.workspace):
        raise ValueError("existing shipping permission does not allow issue management")
    with locks.locked(run.ctx, run.number, args.lock_fd):
        if run.legacy:
            run = _legacy(run, args)
        if run.saved is not None:
            ctx, path, saved = evidence.workspace_record(args.workspace, args.plot)
            run = Run(ctx, path, saved, run.number, False)
            if saved["issue"] != run.number:
                raise ValueError("association changed while acquiring its lock")
        return _mutate(run, args)


def main(argv: Sequence[str]) -> int:
    args = arguments.parse(argv)
    try:
        if (result := _initial(args)) is not None:
            return result
        run = _resolve(args)
        if (result := _read_only(run, args)) is not None:
            return result
        return _locked(run, args)
    except (ValueError, OSError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        print("issue-claims: " + json.dumps(str(error)), file=sys.stderr)
        return 1
