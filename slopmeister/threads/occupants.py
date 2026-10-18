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


class CensusError(Exception):
    """The inventory cannot safely establish absence."""


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


def gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        pass
    # A killed process stays listed until its parent collects it, on Linux under its own name.
    return run(["ps", "-p", str(pid), "-o", "stat="]).stdout.strip().startswith("Z")


def beneath(path: str, root: str) -> bool:
    return path == root or path.startswith(root + os.sep)


def printable(text: str) -> str:
    return "".join(char if char.isprintable() or char == " " else "?" for char in text)


def _inspect_process(fields: tuple[int, str, str], query: ProcessQuery) -> Process | None:
    pid, kind, tty = fields
    identity = run(["ps", "-p", str(pid), "-o", "lstart=,comm="])
    arguments = run(["ps", "-p", str(pid), "-o", "args="])
    location = run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"])
    paths = [line[1:] for line in location.stdout.splitlines() if line.startswith("n")]
    if identity.returncode or arguments.returncode or location.returncode or len(paths) != 1:
        if gone(pid):
            return None
        raise CensusError("cannot determine identity or cwd of PID " + str(pid))
    if kind == "codex" and DAEMON_ARGS.search(arguments.stdout.strip()):
        return None
    if kind == "opencode" and SERVER_ARGS.search(arguments.stdout.strip()):
        return None
    cwd = os.path.realpath(paths[0])
    return Process(
        pid,
        kind,
        tty,
        identity.stdout.strip(),
        cwd,
        beneath(cwd, query.root),
        bool(query.pattern and query.pattern.search(arguments.stdout)),
    )


def processes(root: str, name: str | None) -> list[Process]:
    listing = run(["ps", "-axo", "pid=,tty=,comm="])
    if listing.returncode:
        raise CensusError("cannot complete ps inspection")
    pattern = (
        re.compile(r"(?:^|\s)--remote-control=" + re.escape(name) + r"(?:\s|$)") if name else None
    )
    query = ProcessQuery(root, pattern)
    found = []
    for row in listing.stdout.splitlines():
        fields = row.strip().split(None, 2)
        if len(fields) != 3:
            raise CensusError("incomplete process inventory")
        pid_text, tty, executable = fields
        kind = os.path.basename(executable)
        if kind in KINDS:
            process = _inspect_process((int(pid_text), kind, tty), query)
            if process:
                found.append(process)
    return found


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
