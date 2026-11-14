"""Rerun a task's initially failed CI jobs once, then report the actual result."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

from slopmeister.session import ci_rerun_azure as azure
from slopmeister.session import ci_rerun_common as common
from slopmeister.session import ci_rerun_github as github
from slopmeister.session import ci_rerun_gitlab as gitlab
from slopmeister.session.launch_identity import open_nofollow, regular_file

POLL_SECONDS = 2


def provider(name: str):
    if name == "github":
        return github
    if name == "gitlab":
        return gitlab
    return azure


def report(run: common.Run, initial: common.Run) -> None:
    previous = {job.id: job for job in initial.jobs}
    # GitHub copies successful jobs into a new attempt with new IDs but their original times.
    completed = {
        (j.name, j.native.get("started_at"), j.native.get("completed_at"), j.result)
        for j in initial.jobs
        if j.native.get("started_at") and j.native.get("completed_at")
    }
    jobs = [
        dict(id=j.id, name=j.name, result=j.result, attempt=j.attempt)
        for j in run.jobs
        if (
            j.id not in previous
            or j.attempt > previous[j.id].attempt
            or j.result != previous[j.id].result
        )
        and (j.name, j.native.get("started_at"), j.native.get("completed_at"), j.result)
        not in completed
    ]
    print(json.dumps(dict(run=run.url, result=run.result, jobs=jobs)), flush=True)


def execute(ctx: common.Context, run_id: int) -> int:
    service = provider(ctx.provider)
    run = initial = service.read(ctx, run_id)
    print(
        json.dumps(dict(run=run.url, status_command=shlex.join(service.status(ctx, run_id)))),
        flush=True,
    )
    print(
        json.dumps(
            dict(
                requested_jobs=[
                    j.name for j in initial.jobs if j.result in ("failure", "failed", "timed_out")
                ]
            )
        ),
        flush=True,
    )
    service.retry(ctx, run_id, initial)
    while time.monotonic() + POLL_SECONDS < ctx.deadline:
        run = service.read(ctx, run_id)
        if run.complete and run.generation > initial.generation:
            report(run, initial)
            return 0 if run.result in ("success", "succeeded") else 1
        time.sleep(POLL_SECONDS)
    report(run, initial)
    raise ValueError(
        "CI result is incomplete; use the printed read-only status command; do not retry"
    )


def locked(ctx: common.Context, directory: Path, run_id: int) -> int:
    descriptor = open_nofollow(directory / "ci-rerun.lock", os.O_WRONLY | os.O_CREAT, dir_fd=None)
    with os.fdopen(descriptor, "w") as stream:
        os.fchmod(stream.fileno(), 0o600)
        if not regular_file(os.fstat(stream.fileno()), owned=True):
            raise ValueError("unsafe CI rerun lock")
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("another CI rerun command is active in this task") from None
        return execute(ctx, run_id)


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=int, required=True)
    parser.add_argument("--cwd", type=Path)
    args = parser.parse_args(argv)
    try:
        common.number(args.run)
        ctx, directory = common.context(args.cwd)
        return locked(ctx, directory, args.run)
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"CI RERUN BLOCKED: {error}", file=sys.stderr)
        return 1
