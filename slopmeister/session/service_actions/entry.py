"""Run the delivered supervisor with literal, reviewed read arguments."""

from contextlib import redirect_stdout
import os
from pathlib import Path
import stat
import sys

from service_actions.supervisor import main


def _result_file(value: str):
    path = Path(value)
    if (
        not path.is_absolute()
        or ".." in path.parts
        or any(part.is_symlink() for part in path.parents)
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError("OUTPUT_FILE_UNSAFE")
    parent = path.parent.stat()
    if parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) != 0o700:
        raise ValueError("OUTPUT_FILE_UNSAFE")
    fd = os.open(path, os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    info = os.fstat(fd)
    if not (
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_nlink == 1
        and info.st_size == 0
    ):
        os.close(fd)
        raise ValueError("OUTPUT_FILE_UNSAFE")
    return os.fdopen(fd, "w", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 4 or sys.argv[1] != "--output":
        print('{"result":"ARGUMENTS_NOT_SUPPORTED"}')
        raise SystemExit(1)
    try:
        stream = _result_file(sys.argv[2])
    except OSError, ValueError:
        print('{"result":"OUTPUT_FILE_UNSAFE"}')
        raise SystemExit(1) from None
    with stream, redirect_stdout(stream):
        raise SystemExit(main(sys.argv[3:], direct=True))
