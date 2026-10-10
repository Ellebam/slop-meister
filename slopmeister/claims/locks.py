"""Per-issue file locks for claim lifecycle operations."""

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat

from slopmeister.claims import evidence, github


def lock_path(ctx: github.Repository | dict, number: int) -> Path:
    common = ctx.common if isinstance(ctx, github.Repository) else ctx["common"]
    directory = evidence.safe_path(common / "slopmeister-claims")
    directory.mkdir(mode=0o700, exist_ok=True)
    path = evidence.safe_path(directory / f"{github.issue_number(number)}.lock")
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    os.close(descriptor)
    return path


def _validate_descriptor(descriptor: int, path: Path) -> None:
    opened = os.fstat(descriptor)
    target = path.stat()
    same_file = (opened.st_dev, opened.st_ino) == (target.st_dev, target.st_ino)
    if not stat.S_ISREG(opened.st_mode) or not same_file:
        raise ValueError("claim lock descriptor belongs to another issue")


@contextmanager
def locked(ctx: github.Repository | dict, number: int, inherited: int | None = None):
    path = lock_path(ctx, number)
    descriptor = inherited if inherited is not None else os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        _validate_descriptor(descriptor, path)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("issue is busy with another launch or lifecycle operation") from None
        yield
    finally:
        if inherited is None:
            os.close(descriptor)
