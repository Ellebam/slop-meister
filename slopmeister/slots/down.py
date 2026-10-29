"""Release the resources allocated by one slot after its worker has closed."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
import os
from pathlib import Path
import shutil
import sys
import time

from slopmeister.errors import SlopmeisterError
from slopmeister.launch import closure
from slopmeister.launch.model import Launch, Stop
from slopmeister.slots import allocation, claimed, leftover, setup, tester
from slopmeister.slots.down_arguments import Request as Request
from slopmeister.slots.down_arguments import parse as parse
from slopmeister.threads import occupants


def _occupied(worktree: Path, project: str) -> None:
    try:
        processes = [p for p in occupants.census(str(worktree)) if p.inside]
    except occupants.CensusError as error:
        raise SlopmeisterError(
            f"cannot tell whether a worker occupies {worktree}, "
            f"refusing to release {project}: {error}"
        ) from error
    if processes:
        rows = [f"{p.kind} pid {p.pid} in {occupants.printable(p.cwd)}" for p in processes]
        raise SlopmeisterError(
            f"a worker still occupies {worktree}, refusing to release {project}:\n"
            + "\n".join(rows)
            + "\nstop the exact worker through its launcher, then run down again"
        )


def _parents() -> dict[int, int]:
    rows = allocation.run(["ps", "-axo", "pid=,ppid="], capture=True).stdout.splitlines()
    return {int(pid): int(parent) for pid, parent in map(str.split, rows)}


def _calling_worker(worktree: Path, project: str) -> None:
    """Only the session that runs the command may have its slot released beneath it."""
    try:
        workers = {process.pid: process for process in occupants.census(str(worktree))}
    except occupants.CensusError as error:
        raise SlopmeisterError(
            f"cannot tell whether a worker occupies {worktree}, refusing to release {project}: "
            f"{error}, run this command outside the tool's sandbox"
        ) from error
    parents, nearest = _parents(), os.getpid()
    # The nearest worker decides, a reviewer or tester child must not release its parent's slot.
    while nearest in parents and nearest not in workers:
        nearest = parents[nearest]
    inside = [process for process in workers.values() if process.inside]
    if [process.pid for process in inside] != [nearest]:
        listed = [f"{p.kind} pid {p.pid} in {occupants.printable(p.cwd)}" for p in inside]
        raise SlopmeisterError(
            f"--self requires the calling worker to be the only occupant of {worktree}, "
            f"refusing to release {project}:\n" + "\n".join(listed or ["no occupant"])
        )


def _owned_state(request: Request) -> allocation.Live:
    matches = []
    pattern = f"{request.target}-slot*/{allocation.ALLOCATION}"
    for state in sorted(allocation.state_path().glob(pattern)):
        owned = allocation.read(state)
        if (owned.target, owned.name) == (request.target, request.name):
            expected = allocation.state_path() / f"{owned.target}-slot{owned.slot}"
            if state.parent != expected:
                raise SlopmeisterError(
                    f"owned state path disagrees with {owned.target}-slot{owned.slot}"
                )
            matches.append(owned)
    if len(matches) != 1:
        raise SlopmeisterError(
            f"owned state does not identify exactly one allocation for '{request.name}', refusing"
        )
    return matches[0]


def _refuse_duplicate(worktree: Path, owned: allocation.Live) -> None:
    duplicate = next(
        (
            live
            for live in allocation.live(worktree.parent.parent)
            if (live.target, live.slot) == (owned.target, owned.slot)
            and live.worktree.resolve() != worktree.resolve()
        ),
        None,
    )
    if duplicate:
        raise SlopmeisterError(
            f"slot {owned.slot} is also claimed by worktree {duplicate.worktree}, refusing"
        )


def _worktree_slot(request: Request, worktree: Path) -> int:
    path = worktree / allocation.ALLOCATION
    if not path.is_file():
        raise SlopmeisterError(f"{worktree} carries no {allocation.ALLOCATION}")
    item = allocation.read(path)
    if item.target != request.target or item.name != request.name:
        raise SlopmeisterError(
            f"the allocation names target '{item.target}' and name '{item.name}', not "
            f"'{request.target}' and '{request.name}', refusing"
        )
    owned = _owned_state(request)
    if (item.target, item.slot, item.name) != (owned.target, owned.slot, owned.name):
        raise SlopmeisterError(
            f"worktree allocation disagrees with owned state slot {owned.slot}, refusing"
        )
    _refuse_duplicate(worktree, owned)
    if request.wanted and request.wanted != str(owned.slot):
        raise SlopmeisterError(
            f"the allocation is slot {owned.slot}, not --slot {request.wanted}, refusing"
        )
    (_calling_worker if request.own else _occupied)(worktree, f"{request.target}-slot{owned.slot}")
    dirty = allocation.run(
        ["git", "-C", str(worktree), "status", "--porcelain"], capture=True
    ).stdout.strip()
    if dirty and not request.force:
        raise SlopmeisterError(f"uncommitted work in {worktree}; pass --force to confirm deletion")
    if not request.force:
        setup.check_ignored_output(worktree, owned)
    return owned.slot


def _context(request: Request) -> tuple[dict, Path, Path, int]:
    allocation.validate_name(request.name, "session")
    allocation.validate_name(request.target, "target")
    if allocation.is_none(slots := allocation.definition(request.target)):
        raise SlopmeisterError(f"target '{request.target}' declares no slot resources")
    root = allocation.main_root(request.repo)
    worktree = root / ".worktrees" / request.name
    if worktree.is_symlink():
        raise SlopmeisterError(f"{worktree} is a symlink and is never followed, refusing")
    if worktree.is_dir() and Path.cwd().resolve().is_relative_to(worktree.resolve()):
        raise SlopmeisterError(f"refusing to tear down this shell's worktree; run from {root}")
    if not (request.own and claimed.handback_recorded(worktree)):
        claimed.refuse(worktree, request.target)
    if worktree.is_dir() and not leftover.found(worktree):
        return slots, root, worktree, _worktree_slot(request, worktree)
    if not request.wanted:
        raise SlopmeisterError(f"no worktree at {worktree}, pass --slot <n> to release resources")
    number = leftover.numbered(worktree, request.target, request.wanted)
    if worktree.is_dir():
        leftover.confirm(request.force, leftover.command(worktree, request.target, number))
        _occupied(worktree, f"{request.target}-slot{number}")
    return slots, root, worktree, number


def _detach(log: Path) -> bool:
    """Fork the process that outlives the worker. True in it, once the command has returned."""
    sys.stdout.flush()
    command = os.getpid()
    if os.fork():
        return False
    os.setsid()
    output = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
    os.dup2(output, 1)
    os.dup2(output, 2)
    # Shutdown stops the worker's descendants, so this process must leave that tree first.
    while os.getppid() == command:
        time.sleep(0.05)
    return True


def _stop_worker(request: Request, root: Path, worktree: Path) -> None:
    launch = Launch(request.target, request.name, str(root), repo=root, wt=worktree)
    launch.claude_wt = Path(os.path.realpath(worktree))
    try:
        closure.close(launch)
    except Stop as stop:
        raise SlopmeisterError(f"worker not closed, nothing released: {stop.text}") from stop


def main(argv: Sequence[str]) -> int:
    request = parse(argv)
    if data := tester.find(request.target, request.name, request.wanted):
        if request.own or request.force:
            raise SlopmeisterError("tester recovery takes neither --self nor --force")
        tester.recover(data, allocation.main_root(request.repo), request.wanted)
        return 0
    if not request.own:
        return _release(request)
    _, root, worktree, _ = _context(request)
    log = allocation.state_path() / f"{request.name}.down.log"
    if not _detach(log):
        print(f"slot: releasing {request.name}, this worker stops now, result in {log}")
        return 0
    _stop_worker(request, root, worktree)
    claimed.complete_handback(worktree, root)
    return _release(replace(request, own=False))


def _release(request: Request) -> int:
    slots, root, worktree, number = _context(request)
    project = f"{request.target}-slot{number}"
    data = allocation.state_path() / project
    relative = allocation.compose_relative(slots)
    released = allocation.remove_project(project) if relative else []
    present = worktree.is_dir()
    if present:
        leftover.remove(worktree, leftover.command(worktree, request.target, number))
    # The state outlives a failed removal, a rerun needs it to prove the slot's identity.
    if data.is_dir():
        shutil.rmtree(data)
        released.append("data")
    if present:
        released.append("worktree")
    allocation.run(["git", "-C", str(root), "worktree", "prune"])
    message = f"slot: {project} released, {' '.join(released)}"
    print(message if released else f"slot: nothing live for {project}")
    print(f"slot: kept branch '{request.name}', launcher trust and kickoff files")
    return 0
