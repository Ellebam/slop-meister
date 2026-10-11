"""The native adapter keeps ownership of its writer through protocol and lifecycle failures."""

from contextlib import suppress
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import pytest

from slopmeister.session.service_actions.constants import PYTHON_FLAGS

SOURCE = Path(__file__).resolve().parents[3] / "slopmeister/session"


def _writer(tmp_path):
    child = tmp_path / "entry.py"
    child.write_text(
        "import json,os,subprocess,sys,time\n"
        "child=subprocess.Popen([sys.executable,'-c',"
        "'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        "print(1,flush=True); time.sleep(30)'],stdout=subprocess.PIPE)\n"
        "child.stdout.readline()\n"  # the descendant ignores TERM from here on
        + f"open({str(tmp_path / 'ready.json')!r},'w').write(json.dumps([os.getpid(),child.pid]))\n"
        + "time.sleep(30)\n"
    )
    return child


def _adapter(tmp_path, timeout, after_start=""):
    child = _writer(tmp_path)
    runner = tmp_path / "runner.py"
    runner.write_text(
        "import os,signal,sys\nfrom pathlib import Path\n"
        + f"sys.path.insert(0,{str(SOURCE)!r})\n"
        + "from service_actions import native_tool\n"
        + "native_tool.PYTHON=Path(sys.executable)\n"
        + f"native_tool.ROOT=Path({str(tmp_path)!r})\n"
        + f"native_tool.TIMEOUT={timeout!r}\n"
        + "native_tool.require_host=lambda *_args: None\n"
        + "original_start=native_tool.start\n"
        + "def start(request,binding):\n"
        + " job=original_start(request,binding)\n"
        + f" Path({str(tmp_path / 'started.json')!r}).write_text(str([job['child'].pid]))\n"
        + f" {after_start}\n"
        + " return job\n"
        + "native_tool.start=start\n"
        + "native_tool.serve({'why':'synthetic lifecycle fixture'})\n"
    )
    process = subprocess.Popen(
        [sys.executable, str(runner)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    return process, _request(tmp_path, child)


def _request(tmp_path, child):
    command = " ".join(
        [sys.executable, *PYTHON_FLAGS, str(child), "--output", str(tmp_path / "out"), "--pause"]
    )
    request = dict(
        jsonrpc="2.0",
        id=1,
        method="tools/call",
        params={"name": "run", "arguments": {"command": command}},
    )
    return json.dumps(request).encode() + b"\n"


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _ready(tmp_path, name="ready.json"):
    path = tmp_path / name
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        # The file exists before its content does, so only parsed content counts as ready.
        with suppress(FileNotFoundError, ValueError):
            return json.loads(path.read_text())
        time.sleep(0.02)
    raise AssertionError("writer never started")


def _assert_gone(pids):
    deadline = time.monotonic() + 2
    while any(_alive(pid) for pid in pids) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not any(_alive(pid) for pid in pids), "adapter left a writer descendant alive"


def _cleanup(process, pids):
    if process.poll() is None:
        process.kill()
    for pid in pids[:1]:
        if _alive(pid):
            with suppress(ProcessLookupError):
                os.killpg(pid, signal.SIGKILL)
    process.communicate(timeout=5)


@pytest.mark.parametrize("ending", ["cancel", "disconnect", "timeout", "signal", "malformed"])
def test_native_adapter_cancellation_cleans_up_writer_descendants(tmp_path, ending):
    """Bug: cancellation waits only for the leader and leaves a TERM-ignoring descendant."""
    process, request = _adapter(tmp_path, 0.8 if ending == "timeout" else 30)
    pids = []
    try:
        process.stdin.write(request)
        process.stdin.flush()
        pids = _ready(tmp_path)
        if ending in ("cancel", "malformed"):
            messages = {
                "cancel": (
                    b'{"jsonrpc":"2.0","method":"notifications/cancelled",'
                    b'"params":{"requestId":1}}\n'
                ),
                "malformed": b"not-json\n",
            }
            process.stdin.write(messages[ending])
            process.stdin.flush()
        if ending == "signal":
            process.send_signal(signal.SIGTERM)
        if ending == "disconnect":
            process.stdin.close()
            process.stdin = None
        _assert_gone(pids)
    finally:
        _cleanup(process, pids)


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGHUP])
def test_stop_signal_during_the_writer_handoff_cannot_lose_the_writer(tmp_path, signum):
    """Bug: a signal between spawning the writer and recording it exited without stopping it."""
    sent = f"os.kill(os.getpid(), {int(signum)})"
    process, request = _adapter(tmp_path, 30, after_start=sent)
    pids = []
    try:
        process.stdin.write(request)
        process.stdin.flush()
        pids = _ready(tmp_path, "started.json")
        assert process.wait(timeout=5) == 1
        _assert_gone(pids)
    finally:
        _cleanup(process, pids)


def test_stop_signal_during_a_blocked_reply_still_stops_the_writer(tmp_path):
    """Bug: a handler that only set a flag let a blocked reply write defer cleanup and exit."""
    process, request = _adapter(tmp_path, 30)
    pids = []
    try:
        process.stdin.write(request)
        process.stdin.flush()
        pids = _ready(tmp_path)
        # Unread replies fill the adapter's stdout pipe, 1200 replies of 300 bytes, so the
        # adapter blocks inside a write when the signal arrives.
        listing = json.dumps(dict(jsonrpc="2.0", id=2, method="tools/list")).encode() + b"\n"
        process.stdin.write(listing * 1200)
        process.stdin.flush()
        time.sleep(0.5)
        process.send_signal(signal.SIGTERM)
        _assert_gone(pids)  # stopped while the reply pipe is still blocked
        # Only the exit flush needs a reader.
        threading.Thread(target=process.stdout.read, daemon=True).start()
        assert process.wait(timeout=5) == 1
    finally:
        _cleanup(process, pids)


@pytest.mark.parametrize(
    "bad", [b"not-json\n", b"[]\n", b'{"jsonrpc":"2.0","id":2,"method":"tools/call","params":[]}\n']
)
def test_malformed_request_after_start_in_same_read_cannot_lose_writer(tmp_path, bad):
    """Bug: batch parsing starts a writer then raises before returning its ownership handle."""
    process, request = _adapter(tmp_path, 30)
    pids = []
    try:
        process.stdin.write(request + bad)
        process.stdin.flush()
        pids = _ready(tmp_path, "started.json")
        process.stdin.close()
        process.stdin = None
        process.wait(timeout=5)
        _assert_gone(pids)
    finally:
        _cleanup(process, pids)
