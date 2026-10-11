"""The real Task dispatcher replaces itself with the tool in the terminal it runs in."""

import os
import subprocess

from tests.integration.launch.helpers import ROOT, executable, machine


def test_public_dispatch_execs_the_tool_and_writes_no_terminal_escape(tmp_path):
    """Bug: the dispatcher never reached the tool, or wrote a terminal colour escape."""
    world = machine(tmp_path)
    executable(tmp_path / "bin/claude", "#!/bin/sh\nprintf TOOL-RAN\n")
    env = dict(world.env, DISPATCH_STATE_DIR=str(tmp_path / "dispatch"))
    launched = subprocess.run(
        ["task", "dispatch", "--", "claude", "native-dispatch"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        timeout=60,
    )
    assert launched.returncode == 0, launched.stderr.decode()
    assert b"TOOL-RAN" in launched.stdout and b"\x1b]6;1;bg;" not in launched.stdout
    dry = subprocess.run(
        ["task", "dispatch", "--", "claude", "native-dispatch-dry"],
        cwd=ROOT,
        env=dict(env, DISPATCH_NO_LAUNCH="1"),
        capture_output=True,
        timeout=60,
    )
    assert dry.returncode == 0 and b"TOOL-RAN" not in dry.stdout
    assert os.path.isdir(world.sessions)
