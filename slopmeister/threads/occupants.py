"""Trusted census of the worker processes in a worktree."""

from collections.abc import Sequence
from dataclasses import dataclass
import os
import re
import subprocess
import sys

KINDS = ("claude", "codex", "opencode")
# Freeze the first executable match so a worker's prompt cannot become a second command.
DAEMON_ARGS = re.compile(
    r"^(?>(?:codex|.*?/codex)\s+)(?:app-server|remote-control|sandbox)(?:\s|$)"
)
# A headless OpenCode server holds no conversation, only its TUI or run process is a worker.
SERVER_ARGS = re.compile(r"(?:^|/)opencode\s+(?:serve|web|acp)(?:\s|$)")
COMMAND_TIMEOUT = 15
# ps cuts its rows at COLUMNS unless told twice to go wide, and a cut row can drop a worker name.
WIDE = "-ww"
# macOS shows a process that is starting a program or exiting as "(name)" for a moment, so one
# changed reading proves no new owner. A PID that keeps changing over these passes stops the census.
CENSUS_PASSES = 3


class CensusError(Exception):
    """The inventory cannot safely establish absence."""


class IdentityChanged(CensusError):
    """A PID showed two identities in one pass, a new pass reads it again."""


@dataclass
class Process:
    pid: int
    kind: str
    tty: str
    signature: str
    cwd: str
    inside: bool
    named: bool


@dataclass
class ProcessQuery:
    root: str
    pattern: re.Pattern | None


def run(args: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=COMMAND_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CensusError("inspection command unavailable: " + args[0]) from error


def _absent(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        pass
    return False


def gone(pid: int) -> bool:
    if _absent(pid):
        return True
    # A killed process stays listed until its parent collects it, on Linux under its own name.
    state = run(["ps", "-p", str(pid), "-o", "stat="]).stdout.strip()
    # No row means its parent collected it since the first probe, only the kernel confirms that.
    return state.startswith("Z") or (not state and _absent(pid))


def beneath(path: str, root: str) -> bool:
    return path == root or path.startswith(root + os.sep)


def printable(text: str) -> str:
    return "".join(char if char.isprintable() or char == " " else "?" for char in text)


def process_text(pid: int, fields: str) -> str | None:
    result = run(["ps", WIDE, "-p", str(pid), "-o", fields])
    if result.returncode or not result.stdout.strip():
        if gone(pid):
            return None
        raise CensusError("cannot determine identity or cwd of PID " + str(pid))
    return result.stdout.strip()


def signature(pid: int, *, living: bool = False) -> str | None:
    value = process_text(pid, "stat=,lstart=,comm=" if living else "lstart=,comm=")
    if value is None or not living:
        return value
    state, separator, identity = value.partition(" ")
    if state.startswith("Z"):
        return None
    if not separator or not identity.strip():
        raise CensusError("cannot determine identity of PID " + str(pid))
    return identity.strip()


def cwd(pid: int) -> str | None:
    result = run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"])
    paths = [line[1:] for line in result.stdout.splitlines() if line.startswith("n")]
    if result.returncode or len(paths) != 1 or not paths[0]:
        if gone(pid):
            return None
        raise CensusError("cannot determine identity or cwd of PID " + str(pid))
    return os.path.realpath(paths[0])


def parents() -> dict[int, int]:
    result = run(["ps", "-axo", "pid=,ppid="])
    if result.returncode:
        raise CensusError("cannot complete ps parent inspection")
    try:
        rows = [tuple(map(int, row.split())) for row in result.stdout.splitlines()]
        found = {pid: parent for pid, parent in rows}
        if not found or any(pid <= 0 or parent < 0 or pid == parent for pid, parent in rows):
            raise ValueError
    except ValueError as error:
        raise CensusError("invalid descendant process inventory") from error
    return found


def _rows(result: subprocess.CompletedProcess, pids: set[int]) -> dict[int, str]:
    """The row of each requested PID that ps listed, the caller decides about a missing one."""
    rows: dict[int, str] = {}
    for line in result.stdout.splitlines():
        pid_text, _, rest = line.strip().partition(" ")
        if pid_text.isdigit() and int(pid_text) in pids:
            rows[int(pid_text)] = rest.strip()
    return rows


def _listed(pids: set[int]) -> str:
    return ",".join(str(pid) for pid in sorted(pids))


def _identities(pids: set[int]) -> dict[int, str | None]:
    """The living identity of each PID, or None for one that exited or awaits collection."""
    rows = _rows(run(["ps", WIDE, "-p", _listed(pids), "-o", "pid=,stat=,lstart=,comm="]), pids)
    found: dict[int, str | None] = {}
    for pid in pids:
        if pid not in rows:
            # No row means exited only when the kernel confirms it.
            if not _absent(pid):
                raise CensusError("cannot determine identity of PID " + str(pid))
            found[pid] = None
            continue
        state, separator, identity = rows[pid].partition(" ")
        if state.startswith("Z"):
            found[pid] = None
        elif not separator or not identity.strip():
            raise CensusError("cannot determine identity of PID " + str(pid))
        else:
            found[pid] = identity.strip()
    return found


def _kind(identity: str) -> str:
    """The program name after the five fields of the start time, or empty when absent. macOS
    puts the name in parentheses when it cannot read the arguments."""
    fields = identity.split(None, 5)
    return os.path.basename(fields[5].strip("()")) if len(fields) == 6 else ""


def _directories(pids: set[int]) -> dict[int, str]:
    result = run(["lsof", "-a", "-p", _listed(pids), "-d", "cwd", "-Fn"])
    found: dict[int, str] = {}
    current = 0
    for line in result.stdout.splitlines():
        if line[:1] == "p" and line[1:].isdigit():
            current = int(line[1:])
        elif line[:1] == "n" and line[1:] and current in pids:
            found[current] = os.path.realpath(line[1:])
    return found


def _inspect(candidates: dict[int, tuple[str, str]], query: ProcessQuery) -> list[Process]:
    """A fixed number of reads for any count of agents. The identity read before and after the
    argument and directory reads proves all of them describe one process, so a reused PID can
    never borrow another process's directory or name."""
    before = _identities(set(candidates))
    pids = {pid for pid, identity in before.items() if identity}
    if not pids:
        return []
    arguments = _rows(run(["ps", WIDE, "-p", _listed(pids), "-o", "pid=,args="]), pids)
    directories = _directories(pids)
    after = _identities(pids)
    found = []
    for pid, (kind, tty) in candidates.items():
        if pid not in pids or after[pid] is None:
            continue
        if after[pid] != before[pid]:
            # A forked agent child keeps the agent's name until it starts its own program, and
            # then it is no agent. Any other change may hide an agent, so the census stops.
            kind_now = _kind(after[pid])
            if kind_now and kind_now not in KINDS:
                continue
            raise IdentityChanged(
                f"PID {pid} changed identity during inspection: "
                f"{printable(before[pid])} then {printable(after[pid])}"
            )
        if pid not in arguments or pid not in directories:
            raise CensusError("cannot determine identity or cwd of PID " + str(pid))
        text, location = arguments[pid], directories[pid]
        if kind == "codex" and DAEMON_ARGS.search(text):
            continue
        if kind == "opencode" and SERVER_ARGS.search(text):
            continue
        named = bool(query.pattern and query.pattern.search(text))
        found.append(
            Process(pid, kind, tty, before[pid], location, beneath(location, query.root), named)
        )
    return found


def processes(root: str, name: str | None) -> list[Process]:
    for _ in range(CENSUS_PASSES - 1):
        try:
            return _pass(root, name)
        except IdentityChanged:
            continue
    return _pass(root, name)


def _pass(root: str, name: str | None) -> list[Process]:
    listing = run(["ps", WIDE, "-axo", "pid=,tty=,comm="])
    if listing.returncode:
        raise CensusError("cannot complete ps inspection")
    pattern = (
        re.compile(r"(?:^|\s)--remote-control=" + re.escape(name) + r"(?:\s|$)") if name else None
    )
    candidates: dict[int, tuple[str, str]] = {}
    for row in listing.stdout.splitlines():
        fields = row.strip().split(None, 2)
        if len(fields) != 3:
            raise CensusError("incomplete process inventory")
        pid_text, tty, executable = fields
        kind = os.path.basename(executable)
        if kind in KINDS:
            candidates[int(pid_text)] = (kind, tty)
    return _inspect(candidates, ProcessQuery(root, pattern)) if candidates else []


def census(worktree: str, name: str | None = None) -> list[Process]:
    return processes(os.path.realpath(worktree), name)


def main(argv: Sequence[str]) -> int:
    if len(argv) != 1:
        sys.stderr.write("usage: slopmeister occupants <worktree>\n")
        return 2
    try:
        found = census(argv[0])
    except CensusError as error:
        print(f"occupants: {error}", file=sys.stderr)
        return 2
    for process in found:
        if process.inside:
            print(f"{process.kind} pid {process.pid} in {printable(process.cwd)}")
    return 0
