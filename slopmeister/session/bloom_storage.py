"""Grove's bounded, locked store. The installed receive and cleanup commands share this owner."""

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import re
import secrets
import stat
import time
from typing import BinaryIO

MAX_BYTES = 64 * 1024 * 1024
RETENTION_SECONDS = 7 * 24 * 60 * 60
PAGE = re.compile(r"[0-9a-f]{32}\.html")
PART = re.compile(r"\.[0-9a-f]{32}\.part")
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


@contextmanager
def directory(path: Path):
    """Keep a descriptor to the real directory, even if a path is replaced concurrently."""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("expected an absolute directory without traversal")
    descriptor = os.open("/", DIRECTORY_FLAGS)
    try:
        for part in path.parts[1:]:
            child = os.open(part, DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def read_page(stream: BinaryIO) -> bytes:
    data = stream.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise ValueError("page must be nonempty and fit Grove's 64 MiB storage bound")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("page must be UTF-8") from None
    return data


@contextmanager
def locked(path: Path):
    with directory(path) as folder:
        info = os.fstat(folder)
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError("Grove directory needs publisher ownership and no other writers")
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
        descriptor = os.open(".lock", flags, 0o600, dir_fd=folder)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("unsafe Grove directory lock")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield folder
        finally:
            os.close(descriptor)


def _inventory(folder: int) -> tuple[list[tuple[str, os.stat_result]], int]:
    pages, unexpected = [], 0
    names = sorted(os.listdir(folder), key=lambda name: (not PART.fullmatch(name), name))
    for name in names:
        if name == ".lock":
            continue
        info = os.stat(name, dir_fd=folder, follow_symlinks=False)
        regular = stat.S_ISREG(info.st_mode) and info.st_nlink == 1
        owned = info.st_uid == os.getuid()
        if PART.fullmatch(name) and stat.S_ISREG(info.st_mode) and owned:
            os.unlink(name, dir_fd=folder)
        elif PAGE.fullmatch(name) and regular and owned:
            pages.append((name, info))
        else:
            unexpected += 1
    return pages, unexpected


def _cleanup(folder: int, now: float, keep: str | None = None) -> tuple[int, int]:
    pages, unexpected = _inventory(folder)
    removed, retained = 0, []
    for name, info in pages:
        if name != keep and info.st_mtime < now - RETENTION_SECONDS:
            os.unlink(name, dir_fd=folder)
            removed += 1
        else:
            retained.append((name, info))
    size = sum(info.st_size for _, info in retained)
    for name, info in sorted(retained, key=lambda item: (item[1].st_mtime, item[0])):
        if size <= MAX_BYTES:
            break
        if name != keep:
            os.unlink(name, dir_fd=folder)
            size -= info.st_size
            removed += 1
    if unexpected:
        raise ValueError(f"cleaned managed pages; preserved {unexpected} unsupported Grove entries")
    return removed, size


def cleanup(path: Path) -> tuple[int, int]:
    with locked(path) as folder:
        return _cleanup(folder, time.time())


def publish(path: Path, data: bytes) -> str:
    if not data or len(data) > MAX_BYTES:
        raise ValueError("page exceeds Grove's storage bound or is empty")
    token = secrets.token_hex(16)
    temporary, name = f".{token}.part", f"{token}.html"
    with locked(path) as folder:
        _cleanup(folder, time.time())
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600, dir_fd=folder)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fchmod(stream.fileno(), 0o640)
                os.fsync(stream.fileno())
            os.link(temporary, name, src_dir_fd=folder, dst_dir_fd=folder, follow_symlinks=False)
        finally:
            os.unlink(temporary, dir_fd=folder)
        _cleanup(folder, time.time(), keep=name)
    return name
