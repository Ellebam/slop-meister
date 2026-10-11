#!/usr/bin/env python3
"""Run one supported vault Git transaction under the shared process-owned lease."""

import argparse
import fcntl
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import time

BUSY = 75
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
    result.add_argument("--path", dest="paths", action="append", default=[])
    result.add_argument("command", nargs=argparse.REMAINDER)
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if args.timeout < 0 or not args.command or args.command[0] != "--":
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
        return subprocess.run(command, env=environment, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
