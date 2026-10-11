"""Allocate one slot and hand its environment to the existing launcher."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from slopmeister.errors import SlopmeisterError, UsageError
from slopmeister.launch import cli as launch_cli
from slopmeister.launch import remote
from slopmeister.slots import allocation, rollback


@dataclass(frozen=True)
class Request:
    repo: str
    target: str
    name: str
    wanted: str
    launcher: list[str]


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
        message = (
            f"slot {number} of target '{request.target}' holds residue at {residue}, release "
            f"it with: task slot:down -- {request.repo} {request.target} <name> --slot {number}"
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
    if (found := _candidate(request, candidates, {item.slot for item in held})) is not None:
        return found
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
    live = allocation.Live(request.target, number, request.name, root / ".worktrees" / request.name)
    relative = allocation.compose_relative(slots)
    compose = _claim_compose(root, live, relative)
    data.parent.mkdir(parents=True, exist_ok=True)
    try:
        data.mkdir()
    except FileExistsError as error:
        raise SlopmeisterError(f"could not claim {data}, a concurrent up or residue") from error
    claim = allocation.Claim(live, data, compose, ports)
    try:
        allocation.write(data / allocation.ALLOCATION, claim)
    except Exception:
        shutil.rmtree(data, ignore_errors=True)
        raise
    return claim


def _compose_up(claim: allocation.Claim) -> None:
    if not claim.compose:
        return
    relative = claim.compose.relative_to(claim.live.worktree)
    compose = allocation.resolve_compose(claim.live.worktree, str(relative))
    env = str(claim.data / allocation.ALLOCATION)
    project = f"{claim.live.target}-slot{claim.live.slot}"
    prefix = ["--env-file", env, "-f", str(compose), "-p", project]
    result = allocation.compose([*prefix, "up", "-d", "--wait", "--wait-timeout", "60"], ok=False)
    if result.returncode and not _compose_ready(prefix):
        raise SlopmeisterError(result.stderr.strip() or "docker compose failed")


def _compose_ready(prefix: list[str]) -> bool:
    services = allocation.compose([*prefix, "config", "--services"], ok=False)
    state = allocation.compose([*prefix, "ps", "--all", "--format", "json"], ok=False)
    if services.returncode or state.returncode:
        return False
    try:
        rows = [json.loads(line) for line in state.stdout.splitlines()]
    except json.JSONDecodeError:
        return False
    if len(rows) == 1 and isinstance(rows[0], list):
        rows = rows[0]
    if not rows:
        return False
    expected = set(services.stdout.split())
    found = {row.get("Service") for row in rows if isinstance(row, dict)}
    return bool(expected) and found == expected and all(_service_ready(row) for row in rows)


def _service_ready(row: dict) -> bool:
    return (row.get("State") == "running" and row.get("Health", "") in ("", "healthy")) or (
        row.get("State") == "exited" and row.get("ExitCode") == 0
    )


def _handoff(request: Request, root: Path, claim: allocation.Claim) -> tuple[int, bool]:
    path = claim.data / allocation.ALLOCATION
    command = [str(root), request.target, request.name, *request.launcher]
    if not os.environ.get("SLOT_LAUNCHER"):
        return launch_cli.run(
            command, prepared=lambda launch: _compose_up(claim), worktree_file=str(path)
        )
    if claim.compose:
        raise SlopmeisterError("SLOT_LAUNCHER cannot start a declared Compose project")
    env = dict(os.environ, PLOT_SESSION_WORKTREE_FILE=str(path))
    try:
        return subprocess.run([os.environ["SLOT_LAUNCHER"], *command], env=env).returncode, True
    except OSError as error:
        print(f"slot: launcher unavailable: {error}", file=sys.stderr)
        return 1, True


def main(argv: Sequence[str]) -> int:
    if (code := remote.launch(argv, ["slots", "up"])) is not None:
        return code
    request = parse(argv)
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
            f"slot: launcher failed; a worker may be live in {worktree}. Resources of "
            f"{project} stay up; inspect the worker before teardown.",
            file=sys.stderr,
        )
        return code
    print(f"slot: {project} allocated")
    for line in (claim.data / allocation.ALLOCATION).read_text().splitlines():
        print(line.replace("=", " ", 1))
    return 0
