"""Bound native record reads and never follow a supplied final symlink."""

from collections.abc import Iterator
import json
import os
import re
import time

from slopmeister.session import launch_identity

MAX_LINE_BYTES = 8 * 1024 * 1024
READ_SECONDS = 10


def _decode(line: bytes, strict: bool, passive: re.Pattern[bytes] | None) -> dict | None:
    # Unused native payloads can duplicate megabytes of command output. Their timestamp is enough.
    if passive is not None and (match := passive.match(line)):
        return {"timestamp": match.group(1).decode("ascii")}
    try:
        record = json.loads(line)
    except ValueError:
        if strict and line.endswith(b"\n"):
            raise ValueError("invalid native record") from None
        return None
    if not isinstance(record, dict):
        raise ValueError("invalid native record")
    return record


def records(
    path: str,
    *,
    strict: bool = False,
    deadline: float | None = None,
    passive: re.Pattern[bytes] | None = None,
) -> Iterator[dict]:
    deadline = min(deadline or float("inf"), time.monotonic() + READ_SECONDS)
    with os.fdopen(launch_identity.open_nofollow(path), "rb") as stream:
        if not launch_identity.regular_file(os.fstat(stream.fileno()), owned=True):
            raise ValueError("native record unavailable")
        while line := stream.readline(MAX_LINE_BYTES + 1):
            if len(line) > MAX_LINE_BYTES or time.monotonic() > deadline:
                raise ValueError("native read limit")
            record = _decode(line, strict, passive)
            if record is not None:
                yield record
