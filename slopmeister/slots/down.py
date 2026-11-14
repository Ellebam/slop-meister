"""Release the resources allocated by one slot after its worker has closed."""

from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import select
import shutil
import sys
import time

from slopmeister.errors import SlopmeisterError, UsageError
from slopmeister.launch import closure
from slopmeister.launch.model import Launch, Stop
from slopmeister.removal import nested
from slopmeister.slots import allocation, claimed, leftover, setup, tester
from slopmeister.slots.down_arguments import Request as Request
from slopmeister.slots.down_arguments import parse as parse
from slopmeister.threads import occupants

REPORT_BYTES = 64 * 1024
REPORT_TIMEOUT = 5


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


def _calling_worker(worktree: Path, project: str) -> occupants.Process:
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
    return inside[0]


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
    from slopmeister.repositories import check_companions

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
        ["git", "-C", str(worktree), "status", "--porcelain", "--untracked-files=all"],
        capture=True,
    ).stdout.strip()
    if dirty and not request.force:
        raise SlopmeisterError(f"uncommitted work in {worktree}; pass --force to confirm deletion")
    children = check_companions(worktree, request.force)
    companions = frozenset(Path(row["worktree"]) for row in children)
    nested(worktree, companions)
    if not request.force:
        setup.check_ignored_output(worktree, owned, companions)
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


def _report() -> str:
    if sys.stdin.isatty():
        raise UsageError("--self requires a nonempty harvest report on standard input")
    descriptor, data = sys.stdin.fileno(), bytearray()
    deadline = time.monotonic() + REPORT_TIMEOUT
    while True:
        ready, _, _ = select.select([descriptor], [], [], max(0, deadline - time.monotonic()))
        if not ready:
            raise UsageError("harvest report input did not close before the timeout")
        chunk = os.read(descriptor, min(4096, REPORT_BYTES + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > REPORT_BYTES:
            raise UsageError(f"harvest report exceeds {REPORT_BYTES} bytes")
    report = data.decode("utf-8")
    if not report.strip():
        raise UsageError("--self requires a nonempty harvest report on standard input")
    if any((ord(c) < 32 or 127 <= ord(c) < 160) and c not in "\n\t" for c in report):
        raise UsageError("harvest report contains terminal control characters")
    return report if report.endswith("\n") else report + "\n"


def _detach(log: Path) -> bool:
    """Deliver the report before forking the process that outlives the worker."""
    try:
        report = _report()
        descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(report)
            output.flush()
            print(report, end="", flush=True)
            command = os.getpid()
            if os.fork():
                return False
            os.setsid()
            os.dup2(output.fileno(), 1)
            os.dup2(output.fileno(), 2)
    except (OSError, ValueError) as error:
        raise SlopmeisterError(
            f"harvest report delivery failed, worker not stopped: {error}"
        ) from error
    with open(os.devnull, "rb") as source:
        os.dup2(source.fileno(), 0)
    # Shutdown stops the worker's descendants, so this process must leave that tree first.
    while os.getppid() == command:
        time.sleep(0.05)
    return True


def _stop_worker(
    request: Request, root: Path | None, worktree: Path, caller: occupants.Process
) -> None:
    # No repository argument marks a directory session, whose tab the launcher saved elsewhere.
    launch = Launch(request.target, request.name, str(root or ""), repo=root, wt=worktree)
    launch.claude_wt = Path(os.path.realpath(worktree))
    try:
        closure.close(launch, caller=caller)
    except Stop as stop:
        raise SlopmeisterError(f"worker not closed, nothing released: {stop.text}") from stop


def main(argv: Sequence[str]) -> int:
    return _release(parse(argv))


def _stop_applications(worktree: Path, data: Path) -> None:
    registry = data / "applications"
    if registry.is_symlink():
        raise SlopmeisterError("application registry is a symlink; slot retained")
    if registry.exists() and not registry.is_dir():
        raise SlopmeisterError("application registry is not a directory; slot retained")
    if not registry.exists() or not any(registry.iterdir()):
        return
    item = allocation.read(worktree / allocation.ALLOCATION)
    claim, slots = tester._worker({"cwd": str(worktree)}, item.target)
    evidence = data / "evidence"
    if evidence.is_symlink():
        raise SlopmeisterError("slot stop evidence is a symlink; slot retained")
    evidence.mkdir(mode=0o700, exist_ok=True)
    setup.phase(claim, slots, "stop", data)
    if any(registry.iterdir()):
        raise SlopmeisterError("registered applications remain after stop; slot retained")


def _release(request: Request) -> int:
    from slopmeister.repositories import remove_companions

    number = request.wanted or str(_owned_state(request).slot)
    if data := tester.find(request.target, request.name, number):
        tester.recover(data, allocation.main_root(request.repo), request.wanted)
        return 0
    slots, root, worktree, number = _context(request)
    project = f"{request.target}-slot{number}"
    data = allocation.state_path() / project
    _stop_applications(worktree, data)
    relative = allocation.compose_relative(slots)
    released = allocation.remove_project(project) if relative else []
    present = worktree.is_dir()
    if present:
        remove_companions(worktree)
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
