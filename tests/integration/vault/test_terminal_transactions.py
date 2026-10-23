"""The lease preserves interactive prompts, cancellation and foreground ownership."""

import os
from pathlib import Path
import pty
import select
import shlex
import signal
import subprocess
import sys
import time

import pytest

from tests.integration.vault.test_transaction_lifecycle import LOAD, busy, command
from tests.support.repos import GIT_ENV

pytestmark = pytest.mark.xdist_group("vault-transactions")

TERMINAL_SETUP = """import os, time
foreground = lease.foreground
def handoff(fd, group, *, resume=False):
    if resume:
        deadline, event = time.monotonic() + 2, None
        while event is None and time.monotonic() < deadline:
            event = os.waitid(os.P_PID, group, os.WSTOPPED | os.WEXITED | os.WNOHANG | os.WNOWAIT)
            time.sleep(0.01)
        assert event and event.si_code == os.CLD_STOPPED, event
    foreground(fd, group, resume=resume)
lease.foreground = handoff
code = lease.main()
print('RESTORED', os.tcgetpgrp(0) == os.getpgrp(), flush=True)
raise SystemExit(code)
"""


def read_until(fd: int, marker: bytes) -> bytes:
    deadline, output = time.monotonic() + 5, b""
    while marker not in output and time.monotonic() < deadline:
        if select.select([fd], [], [], 0.05)[0]:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            output += chunk
    assert marker in output, output.decode(errors="replace")
    return output


def terminal_writer(root: Path) -> tuple[list[str], Path]:
    argv, git = command(
        root,
        """import os, signal
tty = os.open('/dev/tty', os.O_RDWR)
signal.signal(signal.SIGCONT, lambda *_: os.write(tty, b'RESUMED\\n'))
os.write(tty, b'PROMPT\\n')
answer = os.read(tty, 100)
assert os.tcgetpgrp(tty) == os.getpgrp()
assert answer == b'approved\\n'
os.write(tty, b'ACCEPTED\\n')
""",
    )
    argv[2] = LOAD.replace("lease.COMMAND_TIMEOUT = 5", "lease.COMMAND_TIMEOUT = 2").replace(
        "raise SystemExit(lease.main())",
        TERMINAL_SETUP,
    )
    return argv, git


def terminal_process(argv: list[str]) -> tuple[subprocess.Popen, int]:
    master, slave = pty.openpty()
    setup = (
        "import fcntl, os, sys, termios; "
        "fcntl.ioctl(0, termios.TIOCSCTTY, 0); "
        "attrs = termios.tcgetattr(0); attrs[3] |= termios.TOSTOP | termios.ICANON | termios.ISIG; "
        "attrs[6][termios.VINTR] = b'\x03'; "
        "termios.tcsetattr(0, termios.TCSANOW, attrs); os.execv(sys.argv[1], sys.argv[1:])"
    )
    try:
        process = subprocess.Popen(
            [sys.executable, "-c", setup, *argv],
            start_new_session=True,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env={**os.environ, **GIT_ENV}
            | {
                "HISTFILE": os.devnull,
                "INPUTRC": os.devnull,
                "PROMPT_COMMAND": "",
                "LC_ALL": "C",
            },
        )
    finally:
        os.close(slave)
    return process, master


@pytest.mark.parametrize("action,expected", [(b"approved\n", 0), (b"\x03", 130), (b"", 124)])
def test_controlling_terminal_prompts_cancel_and_restore(tmp_path, action, expected):
    argv, git = terminal_writer(tmp_path)
    process, fd = terminal_process(argv)
    try:
        read_until(fd, b"PROMPT")
        assert busy(git), "writer started outside the lease"
        if action:
            os.write(fd, action)
        output = read_until(fd, b"RESTORED True")
        assert process.wait(timeout=3) == expected, output
        assert not busy(git)
        if expected == 0:
            assert b"ACCEPTED" in output
        if expected == 130:
            assert b"vault transaction cancelled" in output
        if expected == 124:
            assert b"vault transaction timed out" in output
    finally:
        os.close(fd)
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)


def test_ctrl_z_returns_to_the_shell_and_fg_resumes_the_writer(tmp_path):
    argv, git = terminal_writer(tmp_path)
    shell, fd = terminal_process(["/bin/bash", "--noprofile", "--norc", "-i"])
    try:
        os.write(fd, shlex.join(argv).encode() + b"\n")
        read_until(fd, b"PROMPT")
        os.write(fd, b"\x1a")
        read_until(fd, b"Stopped")
        assert busy(git), "a suspended writer lost its lease"
        os.write(fd, b"fg\n")
        read_until(fd, b"RESUMED")
        os.write(fd, b"approved\n")
        output = read_until(fd, b"RESTORED True")
        assert b"ACCEPTED" in output and not busy(git)
        os.write(fd, b"exit\n")
        assert shell.wait(timeout=3) == 0
    finally:
        os.close(fd)
        if shell.poll() is None:
            os.killpg(shell.pid, signal.SIGKILL)
            shell.wait(timeout=3)
