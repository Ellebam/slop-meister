"""Run slot setup and preserve the public ignored-work removal guard."""

import os
from pathlib import Path
import subprocess

from slopmeister.check import jobs
from slopmeister.errors import SlopmeisterError
from slopmeister.removal import IGNORED_ARGS, check_ignored
from slopmeister.slots import allocation

LOG = "setup.log"
TIMEOUT = 900


def _execute(claim: allocation.Claim, command: list[str]) -> None:
    environment = dict(os.environ)
    environment.update(line.split("=", 1) for line in allocation.content(claim).splitlines())
    descriptor = os.open(claim.data / LOG, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as log:
        process = subprocess.Popen(
            command,
            cwd=claim.live.worktree,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            jobs.wait_unreaped(process, TIMEOUT)
        except subprocess.TimeoutExpired as error:
            raise SlopmeisterError(
                f"setup exceeded {TIMEOUT} seconds; see {claim.data / LOG}"
            ) from error
        finally:
            jobs.stop_group(process, anchored=True)
    if process.returncode:
        raise SlopmeisterError(f"setup exited {process.returncode}; see {claim.data / LOG}")


def run(claim: allocation.Claim, slots: dict) -> None:
    """Callable after stack readiness in either a worker or a tester's prepared checkout."""
    if not (command := slots.get("setup")):
        return
    _execute(claim, command)


def check_ignored_output(worktree: Path, owned: allocation.Live) -> None:
    command = ["git", "-C", str(worktree)]
    entries = allocation.run([*command, *IGNORED_ARGS], capture=True).stdout.split("\0")
    names = [entry for entry in entries if entry.startswith(("? ", "S ", "s ", "h "))]
    gitdir = allocation.run([*command, "rev-parse", "--absolute-git-dir"], capture=True).stdout
    record = allocation.state_path() / f"{owned.target}-slot{owned.slot}" / allocation.ALLOCATION
    if (worktree / allocation.ALLOCATION).read_bytes() == record.read_bytes():
        names = [name for name in names if name[2:] != allocation.ALLOCATION]
    check_ignored(
        worktree,
        names,
        Path(gitdir.strip()) / "slopmeister-config",
    )
