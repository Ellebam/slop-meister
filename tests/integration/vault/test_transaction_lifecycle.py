"""Cancellation must stop writers before the shared vault lock is released."""

import contextlib
import fcntl
import os
import signal
import subprocess
import sys
import time

import pytest

from tests.integration.vault.test_lock import LOCK

pytestmark = pytest.mark.xdist_group("vault-transactions")

LOAD = f"""import importlib.util
spec = importlib.util.spec_from_file_location('lease', {str(LOCK)!r})
lease = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lease)
lease.KILL_GRACE = 0.4
lease.COMMAND_TIMEOUT = 5
raise SystemExit(lease.main())
"""


def busy(root):
    with (root / "slopmeister-coordination/commit.lock").open("r+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


def wait_file(path):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        if path.exists() and path.read_text():
            return path.read_text()
        time.sleep(0.01)
    raise AssertionError(f"writer never reached {path.name}")


def command(root, body):
    git = root / "vault.git"
    git.mkdir()
    child = root / "slopmeister-vault"
    child.write_text(f"#!{sys.executable}\n" + body)
    child.chmod(0o700)
    return [
        sys.executable,
        "-c",
        LOAD,
        "--git-dir",
        str(git),
        "--kind",
        "manual",
        "--",
        str(child),
    ], git


@pytest.fixture
def writer(tmp_path):
    ready, stopped, writes = (tmp_path / name for name in ("ready", "stopped", "writes"))
    argv, git = command(
        tmp_path,
        f"""import os, signal, time
from pathlib import Path
signal.signal(signal.SIGTERM, lambda *_: Path({str(stopped)!r}).write_text('received'))
Path({str(ready)!r}).write_text(str(os.getpid()))
while True:
    Path({str(writes)!r}).write_text(str(time.monotonic()))
    time.sleep(0.01)
""",
    )
    process = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    pid = int(wait_file(ready))
    try:
        yield process, pid, git, stopped, writes
    finally:
        if process.poll() is None:
            process.kill()
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
        process.communicate(timeout=5)


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM, signal.SIGHUP])
def test_cancellation_keeps_lock_until_the_writer_stops(writer, sig):
    process, _, git, stopped, writes = writer
    wait_file(writes)
    assert busy(git)
    process.send_signal(sig)
    wait_file(stopped)
    assert busy(git), "lock released while the writer still runs"
    _, error = process.communicate(timeout=5)
    assert process.returncode == 128 + sig and b"cancelled" in error
    assert not busy(git)
    before = writes.read_bytes()
    time.sleep(0.1)
    assert writes.read_bytes() == before, "writer changed data after lock release"


def test_child_stops_before_lock_release_even_when_its_leader_exits(tmp_path):
    marker = tmp_path / "writes"
    argv, git = command(
        tmp_path,
        f"""import os, signal, time
from pathlib import Path
if os.fork() == 0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True:
        Path({str(marker)!r}).write_text(str(time.monotonic()))
        time.sleep(0.01)
while not Path({str(marker)!r}).exists(): time.sleep(0.01)
""",
    )
    result = subprocess.run(argv, capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    before = marker.read_bytes()
    time.sleep(0.1)
    assert marker.read_bytes() == before and not busy(git)


def test_deadline_keeps_partial_writes_and_releases_the_lock(tmp_path):
    note = tmp_path / "note"
    argv, git = command(
        tmp_path,
        f"from pathlib import Path\nimport time\n"
        f"Path({str(note)!r}).write_text('retain')\ntime.sleep(30)\n",
    )
    argv.insert(argv.index("--"), "--command-timeout=0.2")
    result = subprocess.run(argv, capture_output=True, text=True, timeout=5)
    assert result.returncode == 124 and "timed out" in result.stderr
    assert note.read_text() == "retain" and not busy(git)
