"""Command-line interface for GitHub issue claims."""

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import subprocess
import sys

from slopmeister.claims import arguments, evidence, github, inventory, lifecycle


def _repository(args: argparse.Namespace) -> github.Repository:
    root = args.repo if args.repo is not None else Path.cwd()
    try:
        return github.context(root, args.plot)
    except ValueError as error:
        if args.repo is not None:
            raise
        raise ValueError(f"{error}; pass --repo to name the repository explicitly") from error


def _claim(run: lifecycle.Run, args: argparse.Namespace) -> int:
    _verify_worker(args.workspace, run.saved.get("delivery", {}), legacy=False)
    lifecycle.confirm(run.ctx, run.path, run.saved)
    print(f"issue claimed: {run.ctx.name}#{run.number}")
    return 0


def _inspect(run: lifecycle.Run, args: argparse.Namespace) -> None:
    processes = inventory.census(args.workspace)
    value = {"receipt": run.saved, "issue": github.remote_issue(run.ctx, run.number)}
    value.update(processes=[vars(process) for process in processes], evidence=str(run.path))
    print(json.dumps(value, indent=2))


def _print_backlog(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result))
        return
    for row in result["issues"]:
        print(f"{row['category']}: #{row['number']} " + json.dumps(row))
    for warning in result["warnings"]:
        print("warning: " + json.dumps(warning))


def _legacy(run: lifecycle.Run, args: argparse.Namespace) -> lifecycle.Run:
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
    proof = evidence.proof(args.tool, args.session, args.pid, args.evidence)
    _verify_worker(args.workspace, proof, legacy=True)
    operation = lifecycle.Initialization(args.workspace, run.number, args.kickoff, proof)
    lifecycle.initialize(run.ctx, operation)
    return lifecycle.Run(run.ctx, run.path, evidence.read(run.path), run.number, False)


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


def _close(run: lifecycle.Run, args: argparse.Namespace) -> int:
    lifecycle.close_issue(run.ctx, lifecycle.Closure(run.path, run.saved, args.reason))
    print(f"issue closed: {run.ctx.name}#{run.number}")
    return 0


def _abandon(run: lifecycle.Run, args: argparse.Namespace) -> int:
    if run.saved["phase"] == "released":
        print("already released")
        return 0
    after = args.action == "abandon-complete"
    operation = lifecycle.Abandonment(run.path, run.saved, args.handoff, after)
    lifecycle.abandon(run.ctx, operation)
    print("claim released" if after else "abandonment recorded")
    return 0


MUTATIONS = {
    "reconcile": _claim,
    "close": _close,
    "abandon-prepare": _abandon,
    "abandon-complete": _abandon,
}


def main(argv: Sequence[str]) -> int:
    args = arguments.parse(argv)
    try:
        if args.action == "backlog":
            _print_backlog(inventory.backlog(_repository(args)), args.json)
            return 0
        legacy = args.action == "reconcile" and not evidence.receipt_path(args.workspace).exists()
        run = lifecycle.resolve(args.workspace, args.plot, args.issue_id, unassociated=legacy)
        if args.action == "inspect":
            _inspect(run, args)
            return 0
        with lifecycle.locked(run, args.workspace) as current:
            if current.legacy:
                current = _legacy(current, args)
            return MUTATIONS[args.action](current, args)
    except (ValueError, OSError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        print("issue-claims: " + json.dumps(str(error)), file=sys.stderr)
        return 1
