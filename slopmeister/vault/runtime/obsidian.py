"""Run the Obsidian CLI with one bounded process lifecycle."""

from collections.abc import Sequence
import os
import signal
import subprocess
import sys

DEFAULT_TIMEOUT = 30
KILL_GRACE = 1
TIMEOUT_ENV = "SLOPMEISTER_OBSIDIAN_TIMEOUT"
READ_ONLY = {"backlinks", "links", "open", "orphans", "properties", "search", "tags", "unresolved"}
WRITE_OPERATIONS = {"append", "create", "delete", "move", "rename", "overwrite"}


def _operation(args: Sequence[str]) -> str | None:
    return next((value for value in args if not value.startswith("vault=")), None)


def call(args: Sequence[str], timeout: int = DEFAULT_TIMEOUT) -> tuple[int, bytes, bytes]:
    operation = _operation(args)
    if operation not in READ_ONLY or any(value in WRITE_OPERATIONS for value in args):
        message = f"refused: Obsidian operation is not read-only: {operation or 'missing'}\n"
        return 2, b"", message.encode()
    try:
        process = subprocess.Popen(
            ["obsidian", *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except FileNotFoundError:
        return 127, b"", b""
    try:
        output, error = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            output, error = process.communicate(timeout=KILL_GRACE)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            output, error = process.communicate()
        return 124, output, error
    return process.returncode, output, error


def cli(argv: Sequence[str]) -> int:
    raw_timeout = os.environ.get(TIMEOUT_ENV, str(DEFAULT_TIMEOUT))
    if not raw_timeout.isdecimal() or not int(raw_timeout):
        print(f"{TIMEOUT_ENV} must be positive whole seconds", file=sys.stderr)
        return 2
    args = list(argv)
    if args[:1] == ["--"]:
        args = args[1:]
    code, output, error = call(args, int(raw_timeout))
    sys.stdout.buffer.write(output)
    sys.stderr.buffer.write(error)
    return code
