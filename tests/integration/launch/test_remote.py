"""Drive the public remote routes through an SSH stand-in and a real remote shell."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.integration.launch.helpers import CLI, ROOT, executable

LAUNCHER = """
import json, os, pathlib, sys
pathlib.Path('request.json').write_text(json.dumps({'argv':sys.argv[1:], 'stdin':sys.stdin.read()}))
print('plot-session: delivered (fixture)')
sys.exit(int(os.environ.get('FAKE_LAUNCH_CODE', '0')))
"""
SSH = """
import json, os, pathlib, shlex, shutil, subprocess, sys
with open(os.environ['SSH_CALLS'], 'a') as stream:
    stream.write(json.dumps(sys.argv[1:])+'\\n')
if os.environ.get('FAKE_SSH') == 'down':
    print('fixture: connection refused', file=sys.stderr)
    sys.exit(255)
if len(pathlib.Path(os.environ['SSH_CALLS']).read_text().splitlines()) == 1:
    sys.stdin.read()
env = dict(os.environ, HOME=os.environ['REMOTE_HOME'])
shell = shlex.split(sys.argv[-1])
assert len(shell) == 3 and shell[:2] == ['/bin/zsh', '-lc']
shell[0] = shutil.which('zsh')
sys.exit(subprocess.run(shell, env=env).returncode)
"""


@pytest.fixture
def remote_world(tmp_path):
    host = tmp_path / "host"
    checkout = host / "dev/slop-meister"
    package = checkout / "slopmeister/launch"
    package.mkdir(parents=True)
    (checkout / "slopmeister/__init__.py").touch()
    (package / "__init__.py").touch()
    (package / "terminal.py").write_text(
        'import os\ndef _usable():\n    return os.environ.get("FAKE_ORCA") != "down"\n'
    )
    executable(checkout / "bin/slopmeister", f"#!{sys.executable}\n" + LAUNCHER)
    config = tmp_path / "client/.ssh/slopmeister-remote.conf"
    config.parent.mkdir(parents=True)
    config.write_text("Host remote-box\n")
    binary = tmp_path / "bin"
    executable(binary / "ssh", f"#!{sys.executable}\n" + SSH)
    env = dict(
        os.environ,
        HOME=str(tmp_path / "client"),
        REMOTE_HOME=str(host),
        SSH_CALLS=str(tmp_path / "ssh.jsonl"),
        PATH=f"{binary}:{os.environ['PATH']}",
    )
    return checkout, env


def invoke(world, command, extra=()):
    checkout, env = world
    args = [
        str(CLI),
        *command,
        "~/repo with space",
        "example-client",
        "example-client-one",
        "--host",
        "remote-box",
        *extra,
    ]
    result = subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        input="Mode: freeform\nä ' $() `x`\n",
        text=True,
        capture_output=True,
    )
    return result, checkout / "request.json"


@pytest.mark.parametrize("command", [["plot-session"], ["slots", "up"]])
@pytest.mark.parametrize(
    "value", ["literal ' $(touch BAD) `touch BAD` ; $HOME\nsecond line", "=ls", "=S483_NO_COMMAND"]
)
def test_remote_shell_preserves_kickoff_tilde_and_native_arguments(remote_world, command, value):
    """Bug: SSH expands Mac paths or evaluates an operator argument as shell code."""
    result, request = invoke(remote_world, command, ["--tool", "codex", "--", "-c", value])
    assert result.returncode == 0, result.stderr
    received = json.loads(request.read_text())
    expected = [*command, "~/repo with space", "example-client", "example-client-one"]
    expected += ["--tool", "codex", "--", "-c", value]
    assert received["argv"] == expected
    assert received["stdin"] == "Mode: freeform\nä ' $() `x`\n"
    assert not (request.parent / "BAD").exists()
    assert "remote host: remote-box" in result.stdout
    calls = [json.loads(row) for row in Path(remote_world[1]["SSH_CALLS"]).read_text().splitlines()]
    assert len(calls) == 2
    for call in calls:
        assert call[call.index("-F") + 1].endswith("/.ssh/slopmeister-remote.conf")
        assert "IdentityAgent=none" in call
        assert "StrictHostKeyChecking=yes" in call and "ControlPath=none" in call
        for option in (
            "BatchMode=yes",
            "IdentitiesOnly=yes",
            "ForwardAgent=no",
            "ClearAllForwardings=yes",
        ):
            assert option in call
        assert call[-3:-1] == ["--", "remote-box"]


@pytest.mark.parametrize(
    "failure,cause", [("FAKE_SSH", "connection refused"), ("FAKE_ORCA", "Orca is unreachable")]
)
@pytest.mark.parametrize("command", [["plot-session"], ["slots", "up"]])
def test_unreachable_host_or_orca_never_invokes_remote_launcher(
    remote_world, failure, cause, command
):
    """Bug: a failed preflight still creates a worktree, allocation or claim."""
    remote_world[1][failure] = "down"
    result, request = invoke(remote_world, command)
    assert result.returncode != 0 and cause in result.stderr
    assert not request.exists()
    assert len(Path(remote_world[1]["SSH_CALLS"]).read_text().splitlines()) == 1


@pytest.mark.parametrize("command", [["plot-session"], ["slots", "up"]])
def test_failed_launch_is_unknown_and_never_retried_locally(remote_world, command):
    """Bug: a lost launch connection creates another worker or releases remote resources."""
    remote_world[1]["FAKE_LAUNCH_CODE"] = "255"
    result, request = invoke(remote_world, command)
    assert result.returncode == 255 and request.exists()
    assert "worker may be live" in result.stderr and "--host remote-box" in result.stderr
    assert len(Path(remote_world[1]["SSH_CALLS"]).read_text().splitlines()) == 2
