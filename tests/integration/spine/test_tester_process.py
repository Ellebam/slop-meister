"""The tester runner names and stops a process group that outlives the tester CLI."""

import json
import os
import signal
import subprocess
import sys
import time

import pytest

from slopmeister.check import ownership
from slopmeister.spine.tester import runs
from slopmeister.spine.tester.process import run_tester

LEFTOVER_ARGS = [
    "-c",
    "import time; time.sleep(30)",
    "marker-346",
    "API_KEY=hunter2hunter2",
    "https://u:hunter3hunter3@example.invalid/r",
    "--token",
    "hunter5hunter5",
]


def test_tester_live_group_is_named_redacted_and_stopped(tmp_path):
    """Escaping bugs: the block named only the group id and left the group running."""
    pid_file = tmp_path / "child.pid"
    tool = tmp_path / "codex"
    tool.write_text(
        f"#!{sys.executable}\nimport subprocess, sys\n"
        f"child = subprocess.Popen([sys.executable, *{LEFTOVER_ARGS!r}])\n"
        f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
    )
    tool.chmod(0o755)
    run = {"tool": "codex", "command": [str(tool)], "checkout": str(tmp_path)}
    child = []
    try:
        with pytest.raises(ValueError) as raised:
            run_tester(tmp_path, run, "prompt")
        child.append(int(pid_file.read_text()))
        assert "marker-346" in str(raised.value)
        assert f"{child[0]} " in run["live_group"][0] and "marker-346" in run["live_group"][0]
        saved = str(raised.value) + json.dumps(run)
        assert "hunter2hunter2" not in saved and "hunter3hunter3" not in saved
        assert "hunter5hunter5" not in saved
        assert run["process_stopped"] is True
        assert ownership.identity(child[0]) is None
    finally:
        for pid in child:
            if ownership.identity(pid):
                os.kill(pid, signal.SIGKILL)


def _start_after(pid_file, start=subprocess.Popen):
    """The short timeout must not include interpreter startup, or a loaded machine fails it."""

    def started(*args, **options):
        tester = start(*args, **options)
        deadline = time.monotonic() + 20
        while not (pid_file.exists() and pid_file.read_text()) and time.monotonic() < deadline:
            time.sleep(0.01)
        return tester

    return started


def test_timed_out_tester_group_is_stopped_with_its_child(tmp_path, monkeypatch):
    """Escaping bug: a child that outlives the timed-out CLI keeps running in the checkout."""
    pid_file = tmp_path / "child.pid"
    tool = tmp_path / "codex"
    tool.write_text(
        f"#!{sys.executable}\nimport subprocess, sys, time\n"
        f"child = subprocess.Popen([sys.executable, *{LEFTOVER_ARGS!r}])\n"
        f"open({str(pid_file)!r}, 'w').write(str(child.pid))\ntime.sleep(30)\n"
    )
    tool.chmod(0o755)
    monkeypatch.setattr(subprocess, "Popen", _start_after(pid_file))
    monkeypatch.setattr(runs, "TIMEOUT_SECONDS", 2)
    run = {"tool": "codex", "command": [str(tool)], "checkout": str(tmp_path)}
    try:
        with pytest.raises(ValueError, match="tester timed out; owned process group stopped"):
            run_tester(tmp_path, run, "prompt")
        assert run["process_stopped"] is True
        assert ownership.identity(int(pid_file.read_text())) is None
    finally:
        if pid_file.exists() and ownership.identity(int(pid_file.read_text())):
            os.kill(int(pid_file.read_text()), signal.SIGKILL)
