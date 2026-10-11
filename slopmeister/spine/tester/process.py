"""Run the tester CLI in its own process group and prove the group stopped."""

import os
from pathlib import Path
import subprocess
import time

from slopmeister.check import jobs
from slopmeister.opencode import tester as opencode_tester
from slopmeister.review.process import group_members
from slopmeister.review.run import project_child_env
from slopmeister.spine.tester import runs


def run_tester(root: Path, run: dict, prompt: str) -> None:
    """Records `process_stopped` in `run`; any unproven stop or failed exit raises."""
    opencode = run["tool"] == "opencode"
    try:
        _start(root, run, prompt)
    finally:
        if opencode:
            opencode_tester.scrub(root, run)
    # OpenCode's exit code is classified with its event stream, as a provider error or interruption.
    if run["tester_exit"] and not opencode:
        raise ValueError(f"tester exited {run['tester_exit']}; see stderr.log")


def _start(root: Path, run: dict, prompt: str) -> None:
    env = opencode_tester.child_env(run) if run["tool"] == "opencode" else project_child_env()
    with (root / "events.jsonl").open("w") as output, (root / "stderr.log").open("w") as errors:
        process = subprocess.Popen(
            run["command"],
            cwd=run["checkout"],
            env=env,
            stdin=subprocess.PIPE,
            stdout=output,
            stderr=errors,
            text=True,
            start_new_session=True,
        )
        record = {"pid": process.pid, "group": process.pid, "started_at": time.time()}
        runs.save(root / "process.json", record)
        _communicate(process, run, prompt)
    _check_group(process, run)
    run["tester_exit"] = process.returncode


def _check_group(process: subprocess.Popen, run: dict) -> None:
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        run["process_stopped"] = True
        return
    run["process_stopped"] = False
    try:
        run["live_group"] = group_members(process.pid)
    finally:
        # The leader is reaped, so its id may be reused: signal identity-checked members only.
        jobs.stop_group(process)
    run["process_stopped"] = not group_members(process.pid)
    detail = "owned process group stopped" if run["process_stopped"] else "stop unverified"
    members = "; ".join(run["live_group"])
    raise ValueError(f"tester left a live process group {process.pid}: {members}; {detail}")


def _communicate(process: subprocess.Popen, run: dict, prompt: str) -> None:
    try:
        process.communicate(prompt, timeout=runs.TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            jobs.stop_group(process, anchored=True)
        except OSError, RuntimeError, subprocess.SubprocessError:
            run["process_stopped"] = False
        else:
            run["process_stopped"] = True
        detail = (
            "owned process group stopped"
            if run["process_stopped"]
            else f"unverified live group {process.pid}"
        )
        raise ValueError(f"tester timed out; {detail}") from None
