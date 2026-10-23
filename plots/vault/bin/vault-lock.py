#!/usr/bin/env python3.14
"""Run one supported vault Git transaction under the shared process-owned lease."""

import argparse
from collections.abc import Iterator
import contextlib
import errno
import fcntl
import math
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import sys
import time

BUSY = 75
COMMAND_TIMEOUT = 300
KILL_GRACE = 5
POLL_SECONDS = 0.05
SUPPORTED_COMMANDS = {"slopmeister", "slopmeister-vault", "vault-commit.sh"}


def not_symlink(path: Path, label: str) -> None:
    if path.is_symlink():
        raise ValueError(f"{label} must not use a symlink")


def relative(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or not path.parts
        or ".." in value.split("/")
        or re.search(r"[\x00-\x1f\x7f]", value) is not None
    ):
        raise ValueError("lock paths must be vault-relative")
    return str(path)


def acquire(lock, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--git-dir", type=Path, required=True)
    result.add_argument("--kind", choices=("manual", "scheduled"), required=True)
    result.add_argument("--timeout", type=float, default=0)
    result.add_argument("--command-timeout", type=positive_seconds, default=COMMAND_TIMEOUT)
    result.add_argument("--path", dest="paths", action="append", default=[])
    result.add_argument("command", nargs=argparse.REMAINDER)
    return result


def positive_seconds(value: str) -> float:
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("command timeout must be positive finite seconds")
    return seconds


def signal_group(pid: int, signum: int) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pid, signum)


def exit_status(process: subprocess.Popen) -> os.waitid_result | None:
    # Do not reap the leader before cleanup: its PID anchors the owned process group.
    return os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)


def foreground(fd: int | None, group: int, *, resume: bool = False) -> None:
    if fd is None:
        return
    previous = signal.signal(signal.SIGTTOU, signal.SIG_IGN)
    try:
        os.tcsetpgrp(fd, group)
    finally:
        signal.signal(signal.SIGTTOU, previous)
    if resume:
        # An early terminal read may stop the child before the foreground handoff.
        signal_group(group, signal.SIGCONT)


@contextlib.contextmanager
def terminal() -> Iterator[int | None]:
    try:
        fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
    except OSError as error:
        if error.errno not in (errno.ENXIO, errno.ENODEV, errno.ENOENT, errno.EPERM, errno.EACCES):
            raise
        yield None
        return
    try:
        group = os.tcgetpgrp(fd)
        if group != os.getpgrp():
            yield None
            return
        yield fd
    finally:
        os.close(fd)


def job_control(process: subprocess.Popen) -> None:
    status = os.waitid(os.P_PID, process.pid, os.WSTOPPED | os.WNOHANG | os.WNOWAIT)
    if status is None or status.si_status != signal.SIGTSTP:
        return
    try:
        fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
    except OSError:
        return
    try:
        if os.tcgetpgrp(fd) == process.pid:
            # Terminal Ctrl-Z belongs to the caller's whole job, as before group isolation.
            foreground(fd, os.getpgrp())
            signal_group(os.getpgrp(), signal.SIGTSTP)
        if os.tcgetpgrp(fd) == os.getpgrp():
            foreground(fd, process.pid, resume=True)
    finally:
        os.close(fd)


def watch(process: subprocess.Popen, seconds: float, cancelled: list[int]) -> bool:
    deadline = time.monotonic() + seconds
    while not cancelled and not exit_status(process) and time.monotonic() < deadline:
        job_control(process)
        time.sleep(POLL_SECONDS)
    status = exit_status(process)
    if status:
        # Foreground Ctrl-C reaches the writer, whose CLI may translate it to exit 130.
        signum = status.si_status - 128 if status.si_code == os.CLD_EXITED else status.si_status
        if signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            cancelled.append(signum)
    return bool(cancelled) or status is None


def finish(process: subprocess.Popen, stopped: bool, fd: int | None) -> int:
    # Descendants must not outlive the lease, even when their leader exited normally.
    try:
        signal_group(process.pid, signal.SIGTERM)
        time.sleep(KILL_GRACE if stopped else POLL_SECONDS)
        signal_group(process.pid, signal.SIGKILL)
    except PermissionError as error:
        if exit_status(process) is None:
            raise
        print(
            f"warning: vault process group {process.pid} cleanup denied after child exit: {error}",
            file=sys.stderr,
        )
    try:
        owned = fd is not None and os.tcgetpgrp(fd) == process.pid
    finally:
        result = process.wait()
    if owned:
        foreground(fd, os.getpgrp())
    return 128 - result if result < 0 else result


def transaction(command: list[str], environment: dict, seconds: float) -> int:
    cancelled = []
    previous = {
        sig: signal.signal(sig, lambda sig, _: cancelled.append(sig))
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    }
    try:
        with terminal() as fd:
            process = subprocess.Popen(command, env=environment, process_group=0)
            stopped = True
            try:
                foreground(fd, process.pid, resume=True)
                stopped = watch(process, seconds, cancelled)
            finally:
                result = finish(process, stopped, fd)
        if stopped:
            reason = "cancelled" if cancelled else "timed out"
            print(
                f"vault transaction {reason}: {Path(command[0]).name}; inspect partial writes",
                file=sys.stderr,
                flush=True,
            )
        return 128 + cancelled[0] if cancelled else 124 if stopped else result
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if (
        not math.isfinite(args.timeout)
        or args.timeout < 0
        or not args.command
        or args.command[0] != "--"
    ):
        raise ValueError("lock requires a nonnegative timeout and a command after --")
    command = args.command[1:]
    if not command or Path(command[0]).name not in SUPPORTED_COMMANDS:
        raise ValueError("unsupported vault transaction command")
    not_symlink(args.git_dir, "Git directory")
    git_dir = args.git_dir.resolve(strict=True)
    coordination = git_dir / "slopmeister-coordination"
    not_symlink(coordination, "coordination directory")
    coordination.mkdir(mode=0o700, parents=True, exist_ok=True)
    coordination = coordination.resolve(strict=True)
    for item in args.paths:
        relative(item)
    lock_path = coordination / "commit.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+") as lock:
        if not acquire(lock, args.timeout):
            print("vault transaction busy", file=sys.stderr)
            return 0 if args.kind == "scheduled" else BUSY
        environment = os.environ.copy()
        environment["SLOPMEISTER_VAULT_LOCKED"] = "1"
        return transaction(command, environment, args.command_timeout)


if __name__ == "__main__":
    raise SystemExit(main())
