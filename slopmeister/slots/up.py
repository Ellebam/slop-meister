"""Allocate one slot and hand its environment to the existing launcher."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys

from slopmeister.errors import SlopmeisterError, UsageError
from slopmeister.launch import arguments, remote, target
from slopmeister.launch import cli as launch_cli
from slopmeister.launch.model import Stop
from slopmeister.slots import allocation, rollback, setup
from slopmeister.slots.compose import _compose_up


@dataclass(frozen=True)
class Request:
    repo: str
    target: str
    name: str
    wanted: str
    launcher: list[str]
    checkout: Path | None = None
    prepare: Callable[[allocation.Claim], allocation.Claim] | None = None
    tester: bool = False


def parse(argv: Sequence[str]) -> Request:
    if len(argv) < 3:
        raise UsageError("usage: slopmeister slots up <repo> <target> <name> [--slot <n>]")
    repo, target, name, *tail = argv
    wanted, launcher = "", []
    while tail:
        if tail[0] == "--slot":
            if len(tail) < 2:
                raise UsageError("--slot requires a number")
            wanted, tail = tail[1], tail[2:]
        else:
            launcher.append(tail.pop(0))
    return Request(repo, target, name, wanted, launcher)


def _candidate(request: Request, candidates: list[int], used: set[int]) -> int | None:
    for number in candidates:
        if number in used:
            if request.wanted:
                raise SlopmeisterError(
                    f"slot {number} of target '{request.target}' is live, omit --slot"
                )
            continue
        residue = allocation.state_path() / f"{request.target}-slot{number}"
        if not residue.exists():
            return number
        name = "<name>"
        if (residue / allocation.TESTER_RECORD).is_file() and (
            residue / allocation.ALLOCATION
        ).is_file():
            name = allocation.read(residue / allocation.ALLOCATION).name
        message = (
            f"slot {number} of target '{request.target}' holds residue at {residue}, release "
            f"it with: task slot:down -- {request.repo} {request.target} {name} --slot {number}"
        )
        if request.wanted:
            raise SlopmeisterError(message)
        print("slot: " + message + ", skipped", file=sys.stderr)
    return None


def _available(request: Request, root: Path, slots: dict) -> int:
    held = [item for item in allocation.live(root) if item.target == request.target]
    maximum = allocation.maximum(slots)
    valid = request.wanted.isdigit() and len(request.wanted) <= 2
    if request.wanted and (not valid or not 1 <= int(request.wanted) <= maximum):
        raise SlopmeisterError(
            f"--slot must be 1 to {maximum} for target '{request.target}', got '{request.wanted}'"
        )
    candidates = [int(request.wanted)] if request.wanted else list(range(1, maximum + 1))
    if testers := request.tester and allocation.testers(slots):
        candidates = list(range(maximum + 1, maximum + testers + 1))
    if (found := _candidate(request, candidates, {item.slot for item in held})) is not None:
        return found
    if testers:
        raise SlopmeisterError(f"every tester slot of target '{request.target}' is in use")
    raise SlopmeisterError(
        f"every slot of target '{request.target}' is live or holds residue, "
        f"{maximum} declared, release one first"
    )


def _context(request: Request) -> tuple[dict, Path, Path, str]:
    allocation.validate_name(request.name, "session")
    allocation.validate_name(request.target, "target")
    if not request.name.startswith(request.target + "-"):
        raise SlopmeisterError(f"session name must begin with '{request.target}-'")
    slots = allocation.definition(request.target)
    if allocation.is_none(slots):
        path = allocation.declarations_path() / request.target / "plot.toml"
        raise SlopmeisterError(
            f"target '{request.target}' declares no slot resources in {path}, dispatch it "
            f"without a slot: task plot-session -- {request.repo} {request.target} {request.name}"
        )
    root = allocation.main_root(request.repo)
    worktree = root / ".worktrees" / request.name
    if worktree.exists():
        raise SlopmeisterError(f"worktree path already exists: {worktree}, pick a new name")
    branch = allocation.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "-q", f"refs/heads/{request.name}"],
        capture=True,
        ok=False,
    )
    if branch.returncode == 0:
        raise SlopmeisterError(f"branch '{request.name}' already exists in {root}")
    head = allocation.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "-q", "HEAD"], capture=True, ok=False
    )
    return slots, root, worktree, head.stdout.strip()


def _claim_compose(root: Path, live: allocation.Live, relative: str) -> Path | None:
    """Root is the checkout the stack runs from, a tester's being the tested commit."""
    if not relative:
        return None
    project = f"{live.target}-slot{live.slot}"
    allocation.resolve_compose(root, relative)
    resources = allocation.project_resources(project)
    if resources is None:
        raise SlopmeisterError(f"Docker is unavailable, refusing to claim {project}")
    if resources:
        raise SlopmeisterError(f"{resources[0].name} occupies {project}, refusing")
    return live.worktree / relative


def _claim(request: Request, slots: dict, root: Path) -> allocation.Claim:
    number = _available(request, root, slots)
    ports = allocation.expand(slots, number)
    by_port = {item.port: item for item in allocation.bound_ports()}
    for variable, port in ports.items():
        if holder := by_port.get(port):
            raise SlopmeisterError(
                f"port {port} for {variable} of slot {number} is bound by pid {holder.pid} "
                f"({holder.command}), no two live slots may collide"
            )
    project = f"{request.target}-slot{number}"
    data = allocation.state_path() / project
    live = allocation.Live(
        request.target, number, request.name, request.checkout or root / ".worktrees" / request.name
    )
    compose = _claim_compose(request.checkout or root, live, allocation.compose_relative(slots))
    data.parent.mkdir(parents=True, exist_ok=True)
    try:
        data.mkdir()
    except FileExistsError as error:
        raise SlopmeisterError(f"could not claim {data}, a concurrent up or residue") from error
    claim = allocation.Claim(live, data, compose, ports)
    try:
        if request.prepare:
            claim = request.prepare(claim)
        allocation.write(data / allocation.ALLOCATION, claim)
    except Exception:
        rollback.discard(claim)
        raise
    return claim


def _handoff(request: Request, root: Path, claim: allocation.Claim) -> tuple[int, bool]:
    slots = allocation.definition(request.target)
    path = claim.data / allocation.ALLOCATION
    command = [str(root), request.target, request.name, *request.launcher]

    def prepared(launch):
        _compose_up(claim)
        setup.run(claim, slots)

    if not os.environ.get("SLOT_LAUNCHER"):
        return launch_cli.run(command, prepared=prepared, worktree_file=str(path))
    if claim.compose or slots.get("setup"):
        raise SlopmeisterError("SLOT_LAUNCHER cannot prepare declared Compose or setup")
    env = dict(os.environ, PLOT_SESSION_WORKTREE_FILE=str(path))
    try:
        return subprocess.run([os.environ["SLOT_LAUNCHER"], *command], env=env).returncode, True
    except OSError as error:
        print(f"slot: launcher unavailable: {error}", file=sys.stderr)
        return 1, True


def _check_arguments(request: Request) -> None:
    try:
        launch = arguments.parse([request.repo, request.target, request.name, *request.launcher])
        target.policy(launch)
        arguments.check_tool_arguments(launch)
    except Stop as error:
        raise SlopmeisterError(error.text, error.code) from error


def main(argv: Sequence[str]) -> int:
    if (code := remote.launch(argv, ["slots", "up"])) is not None:
        return code
    request = parse(argv)
    _check_arguments(request)
    slots, root, worktree, start = _context(request)
    claim = _claim(request, slots, root)
    project = f"{request.target}-slot{claim.live.slot}"
    try:
        code, may_be_live = _handoff(request, root, claim)
    except Exception:
        rollback.run(claim, start)
        raise
    if code and not may_be_live:
        rollback.run(claim, start)
        return code
    if code:
        print(
            f"slot: launcher failed; a client may be live in {worktree}. Resources of "
            f"{project} stay up; inspect the worker before teardown.",
            file=sys.stderr,
        )
        return code
    print(f"slot: {project} allocated")
    for line in (claim.data / allocation.ALLOCATION).read_text().splitlines():
        print(line.replace("=", " ", 1))
    return 0
