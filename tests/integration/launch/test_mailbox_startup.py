"""Every startup route prepares the own inbox before the model can skip it."""

import json
import shlex
import subprocess
import sys

import pytest

from slopmeister.dispatch import command as dispatcher
from slopmeister.launch import command
from slopmeister.launch.model import Launch
from tests.integration.launch.helpers import executable
from tests.support.fakes import fake_binary

ORCA = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:-1]
with open(os.environ['MAILBOX_CALLS'], 'a') as out:
    out.write(json.dumps(args) + '\\n')
case = os.environ['MAILBOX_CASE']
handle = os.environ.get('ORCA_TERMINAL_HANDLE', '')
run = dict(id='run_fixture', coordinator_handle=handle,
           objective=os.environ['MAILBOX_OBJECTIVE'], legacy=0)
if args[:2] == ['terminal', 'list']:
    result = dict(truncated=case == 'truncated', terminals=[
        dict(handle='term_foreign' if case == 'foreign' else handle)])
elif args[1] == 'run-current':
    if case == 'lookup-error':
        print(json.dumps(dict(ok=False, error=dict(code='unavailable', message='PRIVATE_BODY'))))
        sys.exit(1)
    if case == 'malformed':
        print('PRIVATE_BODY')
        sys.exit(0)
    if case == 'conflict':
        run['objective'] = 'PRIVATE_BODY'
    if case == 'legacy':
        run['legacy'] = 1
    if case == 'wrong-binding':
        run['coordinator_handle'] = 'term_foreign'
    result = {} if case == 'missing-run' else dict(
        run=run if case in ['bound', 'conflict', 'legacy', 'wrong-binding'] else None)
else:
    if case == 'create-error':
        print(json.dumps(dict(ok=False, error=dict(code='unavailable', message='PRIVATE_BODY'))))
        sys.exit(1)
    result = dict(run=run)
print(json.dumps(dict(ok=True, result=result)))
"""


def _world(tmp_path, monkeypatch, case):
    workspace = tmp_path / "work tree'$(touch BREACH)"
    workspace.mkdir()
    calls = tmp_path / "calls.jsonl"
    binary = executable(tmp_path / "bin/orca", ORCA)
    agent = fake_binary(tmp_path / "bin", "agent", 'printf \'["agent"]\\n\' >> "$MAILBOX_CALLS"')
    monkeypatch.setenv("PLOT_SESSION_ORCA", str(binary))
    monkeypatch.setenv("PLOT_SESSION_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", "term_fixture")
    monkeypatch.setenv("MAILBOX_CALLS", str(calls))
    monkeypatch.setenv("MAILBOX_CASE", case)
    monkeypatch.setenv("MAILBOX_OBJECTIVE", workspace.name)
    if case == "no-handle":
        monkeypatch.delenv("ORCA_TERMINAL_HANDLE")
    return workspace, calls, agent


def _startup(workspace, agent, route):
    kickoff = workspace / "kickoff"
    kickoff.write_text("Synthetic arithmetic")
    if route == "worker":
        launch = Launch("fixture", "fixture", str(workspace.parent))
        launch.wt = workspace
        launch.line = f"cd {shlex.quote(str(workspace))} && {shlex.quote(str(agent))}"
        command.write(launch)
        return ["zsh", "-f", str(launch.command_file)]
    if route == "reported-dispatcher-line":
        return ["zsh", "-f", "-c", dispatcher.line(workspace, [str(agent)], kickoff)]
    code = (
        "from pathlib import Path; from slopmeister.dispatch.command import execute; "
        "import sys; execute(Path(sys.argv[1]), [sys.argv[2]], 'Synthetic arithmetic')"
    )
    return [sys.executable, "-c", code, str(workspace), str(agent)]


@pytest.mark.parametrize(
    "route", ["worker", "reported-dispatcher-line", "same-terminal-dispatcher"]
)
@pytest.mark.parametrize("case", ["new", "bound"])
def test_inbox_is_ready_before_the_agent_starts(tmp_path, monkeypatch, route, case):
    """A model that answers immediately must already have its own usable inbox."""
    workspace, calls, agent = _world(tmp_path, monkeypatch, case)
    result = subprocess.run(_startup(workspace, agent, route), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    observed = [json.loads(line) for line in calls.read_text().splitlines()]
    expected = [["terminal", "list"], ["orchestration", "run-current", "--from", "term_fixture"]]
    if case == "new":
        expected.append(
            ["orchestration", "run-create", "--from", "term_fixture", "--objective", workspace.name]
        )
    assert observed == [*expected, ["agent"]]
    assert "task inbox ready: run_fixture" in result.stdout
    assert not (workspace.parent / "BREACH").exists()


@pytest.mark.parametrize(
    "case,reads",
    [
        ("no-handle", 0),
        ("foreign", 1),
        ("truncated", 1),
        ("lookup-error", 2),
        ("malformed", 2),
        ("missing-run", 2),
        ("conflict", 2),
        ("legacy", 2),
        ("wrong-binding", 2),
        ("create-error", 3),
    ],
)
def test_unavailable_inbox_never_replaces_a_binding_or_blocks_the_task(
    tmp_path, monkeypatch, case, reads
):
    """Failed discovery must not become a guessed inbox creation or leaked runtime error."""
    workspace, calls, agent = _world(tmp_path, monkeypatch, case)
    result = subprocess.run(_startup(workspace, agent, "worker"), capture_output=True, text=True)
    assert result.returncode == 0
    observed = [json.loads(line) for line in calls.read_text().splitlines()]
    assert len(observed) == reads + 1 and observed[-1] == ["agent"]
    assert "task inbox unavailable:" in result.stderr
    assert "PRIVATE_BODY" not in result.stdout + result.stderr
    assert not (workspace.parent / "BREACH").exists()
