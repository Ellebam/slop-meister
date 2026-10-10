from __future__ import annotations

from dataclasses import dataclass, field
import os
import signal
import subprocess
import time

from slopmeister.launch import terminal
from slopmeister.launch.model import Launch, plain
from slopmeister.threads import occupants as inventory
from slopmeister.threads.occupants import Process

POLL_ATTEMPTS, POLL_SECONDS = 20, 0.5


@dataclass
class Closure:
    launch: Launch
    attempted: bool = False
    old: Process | None = None
    owned: list[Owned] = field(default_factory=list)


@dataclass(frozen=True)
class Owned:
    pid: int
    depth: int
    signature: str


def fail(closure: Closure, message: str) -> Exception:
    state = "predecessor closure was not attempted"
    if closure.attempted:
        state = "predecessor closure was attempted and may be incomplete"
    return plain(
        f"redispatch: {message}, no replacement started; {state}; "
        "resolve the error and retry the same name with --redispatch"
    )


def census(closure: Closure) -> list[Process]:
    """Workspace and runtime identity decide ownership; argv is never printed, it holds kickoffs."""
    launch = closure.launch
    try:
        return inventory.census(str(launch.claude_wt), launch.name)
    except inventory.CensusError as failure:
        raise fail(closure, str(failure)) from failure


def _run(closure: Closure, argv: list[str]) -> str:
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise fail(closure, "inspection or closure command unavailable") from error
    if result.returncode:
        name = argv[0].rsplit("/", 1)[-1]
        raise fail(closure, f"cannot complete {name} inspection or closure")
    return result.stdout.strip()


def _select(closure: Closure) -> None:
    launch = closure.launch
    processes = census(closure)
    for process in processes:
        if process.named and not process.inside:
            raise fail(closure, f"named PID {process.pid} belongs to a different workspace")
    occupying = [p for p in processes if p.inside]
    candidates = [p for p in processes if p.named] or occupying
    if len(occupying) > 1 or len(candidates) > 1:
        pids = ", ".join(str(p.pid) for p in occupying)
        raise fail(closure, f"multiple agents occupy {launch.claude_wt} (PIDs {pids})")
    closure.old = candidates[0] if candidates else None


def _handle(closure: Closure) -> str | None:
    """Read before anything stops, a replacement would overwrite the only record of the tab."""
    saved = closure.launch.orca_file
    if not saved.is_file():
        return None
    listed = terminal.terminals() if terminal.ready() else None
    if listed is None:
        raise fail(closure, "Orca is unreachable, the predecessor terminal cannot be checked")
    handle = saved.read_text().strip()
    return handle if listed.get(handle) == str(closure.launch.orca_workspace) else None


def _close_terminal(closure: Closure, handle: str) -> None:
    closure.attempted = True
    terminal.close(handle)
    listed = terminal.terminals()
    if listed is None or handle in listed:
        raise fail(closure, f"predecessor terminal {handle} did not close")


def unchanged(closure: Closure) -> bool:
    old = closure.old
    processes = census(closure)
    return any(p.pid == old.pid and p.signature == old.signature and p.inside for p in processes)


def _signature(closure: Closure, pid: int) -> str | None:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "stat=,lstart=,comm="],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise fail(closure, "inspection or closure command unavailable") from error
    if result.returncode:
        if not _alive(pid):
            return None
        raise fail(closure, f"cannot determine identity of descendant PID {pid}")
    value = result.stdout.strip()
    state, separator, signature = value.partition(" ")
    if state.startswith("Z"):
        return None
    if not separator or not signature.strip():
        raise fail(closure, f"cannot determine identity of descendant PID {pid}")
    return signature.lstrip()


def _snapshot(closure: Closure) -> None:
    rows = _run(closure, ["ps", "-axo", "pid=,ppid="]).splitlines()
    parents: dict[int, list[int]] = {}
    try:
        for row in rows:
            pid, parent = map(int, row.split())
            parents.setdefault(parent, []).append(pid)
    except ValueError as error:
        raise fail(closure, "invalid descendant process inventory") from error
    found = [Owned(closure.old.pid, 0, closure.old.signature)]
    pending = [(closure.old.pid, 1)]
    while pending:
        parent, depth = pending.pop(0)
        for pid in parents.get(parent, []):
            signature = _signature(closure, pid)
            if signature is None:
                continue
            found.append(Owned(pid, depth, signature))
            pending.append((pid, depth + 1))
    closure.owned = sorted(found, key=lambda item: (-item.depth, item.pid))


def _preflight_signals(closure: Closure) -> None:
    for process in closure.owned:
        current = _signature(closure, process.pid)
        if current is None:
            continue
        if current != process.signature:
            raise fail(closure, f"captured PID {process.pid} identity changed before termination")
        try:
            os.kill(process.pid, 0)
        except ProcessLookupError:
            continue
        except PermissionError as error:
            raise fail(closure, f"captured PID {process.pid} cannot be signalled") from error


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _terminate(closure: Closure, process: Owned) -> None:
    current = _signature(closure, process.pid)
    if current is None:
        return
    if current != process.signature:
        # An exiting child can change identity between snapshots; only absence is safe to skip.
        if _signature(closure, process.pid) is None:
            return
        raise fail(closure, f"captured PID {process.pid} identity changed before termination")
    closure.attempted = True
    try:
        os.kill(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError as error:
        raise fail(closure, f"captured PID {process.pid} became unsignallable") from error
    for _ in range(POLL_ATTEMPTS):
        if _signature(closure, process.pid) != process.signature:
            return
        time.sleep(POLL_SECONDS)
    raise fail(closure, f"captured PID {process.pid} did not stop")


def close(launch: Launch) -> None:
    closure = Closure(launch)
    _select(closure)
    handle = _handle(closure)
    if closure.old and not unchanged(closure):
        raise fail(closure, "predecessor PID identity changed")
    if closure.old:
        _snapshot(closure)
        _preflight_signals(closure)
    if closure.old:
        for process in closure.owned:
            _terminate(closure, process)
    # A tab with no live agent may already serve as someone's shell, so it stays open.
    if handle and closure.old:
        _close_terminal(closure, handle)
    closure.launch.orca_file.unlink(missing_ok=True)
    print(
        "plot-session: predecessor closed"
        if closure.old
        else "plot-session: no predecessor, recovering existing workspace"
    )
