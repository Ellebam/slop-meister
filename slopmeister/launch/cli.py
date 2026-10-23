"""slopmeister plot-session: launch or recover a worker and confirm its kickoff was delivered."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import contextlib
import os
import shutil
import sys
import time
import traceback
import uuid

from slopmeister.errors import SlopmeisterError
from slopmeister.launch import (
    arguments,
    closure,
    command,
    confirm,
    issue,
    kickoff,
    native_check,
    remote,
    report,
    target,
    terminal,
    workspace,
)
from slopmeister.launch.model import REPORT, Delivery, Launch, Stop, die, plain, shq

Prepared = Callable[[Launch], None]
DISCOVERY_WAIT = 60
DISCOVERY_PAUSE = 1


def _validate(argv: Sequence[str], worktree_file: str = "") -> Launch:
    """Everything is validated before the target is touched."""
    launch = arguments.parse(list(argv))
    arguments.check_basics(launch)
    if launch.model_set:
        arguments.check_model(launch)
    target.policy(launch)
    arguments.check_tool_arguments(launch)
    arguments.check_sources(launch)
    target.declaration(launch)
    target.repository(launch)
    target.sources(launch)
    issue.associate(launch)
    issue.claim(launch)
    issue.require_managed_abandon(launch)
    target.rendered(launch)
    if not (launch.redispatch or launch.abandon) and target.name_lookup(launch) == 0:
        raise die(
            f"a live process already carries remote-control={launch.name}, "
            "delivery polling would confirm the wrong session; pick a new session name, or pass "
            "--redispatch to replace that session"
        )
    target.staged_file(launch, worktree_file)
    target.binaries(launch)
    kickoff.resolve(launch)
    target.require_slot(launch, argv)
    return launch


def _redispatch(launch: Launch) -> None:
    workspace.adopt(launch)
    workspace.capabilities(launch)
    if os.environ.get("PLOT_SESSION_NO_LAUNCH") != "1":
        native_check.check(launch)
        closure.close(launch)
        status = target.name_lookup(launch)
        if status == 0:
            raise die(
                "the session name remains occupied after closure; "
                "retry the same name with --redispatch"
            )
        if status != 1:
            raise die("cannot inspect the session name after closure" + REPORT)
        if launch.tool == "codex":
            launch.codex_baseline = target.codex_clients()
    launch.state_dir.mkdir(parents=True, exist_ok=True)
    workspace.trust_write(launch)
    print(f"plot-session: existing workspace adopted at {launch.wt} (plot {launch.plot})")


def _prepare(launch: Launch) -> None:
    if launch.redispatch:
        _redispatch(launch)
    elif launch.directory:
        workspace.prepare_directory(launch)
    else:
        workspace.prepare_worktree(launch)
    if not launch.redispatch:
        workspace.capabilities(launch)
    if launch.wt_file:
        shutil.copyfile(launch.wt_file, launch.wt / launch.wt_file_name)
    kickoff.prune(launch)
    kickoff.write(launch)
    issue.initialize(launch)


def _skipped(launch: Launch) -> None:
    print("plot-session: launch skipped (PLOT_SESSION_NO_LAUNCH), launch line:")
    print(f"  {launch.line}")
    print(f"  kickoff file: {launch.kickoff_file}")
    print(f"  command file: {launch.command_file}")
    if launch.model_set:
        print(f"  model requested (prepared): {shq(launch.model)}")


# Reserve a full Orca call timeout before retrying an explicit unknown-selector refusal.
# A create without a handle may have started the command, so delivery polling decides.
def _open(launch: Launch) -> None:
    if not terminal.ready():
        raise plain(
            "plot-session: Orca is unreachable, nothing opened; have the workstation skill "
            "diagnose Orca, then retry the same name with --redispatch"
        )
    launch.open_attempted = True
    if launch.repo:
        terminal.register(launch.repo)
    handle, reason = None, "unreadable_reply"
    deadline = time.monotonic() + DISCOVERY_WAIT - terminal.TIMEOUT
    while time.monotonic() < deadline:
        try:
            handle = terminal.create(launch.orca_workspace, launch.name, launch.terminal_line)
            break
        except SlopmeisterError as error:
            handle, reason = None, str(error)
            if reason != "selector_not_found" or time.monotonic() + DISCOVERY_PAUSE >= deadline:
                break
            time.sleep(DISCOVERY_PAUSE)
    if not handle:
        print(
            f"plot-session: Orca terminal create failed ({reason}), polling for the session anyway",
            file=sys.stderr,
        )
        return
    launch.orca_file.write_text(handle + "\n")
    print(f"plot-session: Orca terminal {handle} opened, confirming delivery by polling")
    if launch.repo and not terminal.name(launch.wt, launch.name, launch.issue_id):
        print("plot-session: Orca did not take the workspace name, continuing", file=sys.stderr)


def _finish_delivery(launch: Launch, delivery: Delivery) -> None:
    report.confirm_identity(launch, delivery)
    report.delivered(launch, delivery)
    issue.bind(launch, delivery)
    report.observe_model(launch, delivery)
    issue.confirm(launch)


def _launch(launch: Launch, prepared: Prepared | None = None) -> None:
    if not launch.redispatch:
        launch.state_dir.mkdir(parents=True, exist_ok=True)
    if launch.abandon:
        workspace.adopt(launch)
        issue.abandon(launch, closure.close)
        return
    _prepare(launch)
    if prepared:
        prepared(launch)
    launch.session_id = str(uuid.uuid4())
    report.prepare_identity(launch)
    launch.line = command.line(launch)
    command.write(launch)
    if os.environ.get("PLOT_SESSION_NO_LAUNCH") == "1":
        _skipped(launch)
        return
    if not launch.redispatch:
        native_check.check(launch)
    marker = time.time()
    _open(launch)
    _finish_delivery(launch, confirm.deliver(launch, marker))


def run(
    argv: Sequence[str], *, prepared: Prepared | None = None, worktree_file: str = ""
) -> tuple[int, bool]:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    launch = None
    try:
        launch = _validate(argv, worktree_file)
        _launch(launch, prepared)
    except Stop as stop:
        if stop.text:
            with contextlib.suppress(OSError):
                print(stop.text, file=sys.stderr)
        return stop.code, bool(launch and (launch.open_attempted or launch.native_pending))
    except Exception as error:
        if not launch or not (launch.open_attempted or launch.native_pending):
            raise
        with contextlib.suppress(OSError):
            traceback.print_exception(error)
        return 1, bool(launch and (launch.open_attempted or launch.native_pending))
    return 0, bool(launch and (launch.open_attempted or launch.native_pending))


def main(argv: Sequence[str]) -> int:
    code = remote.launch(argv, ["plot-session"])
    return run(argv)[0] if code is None else code
