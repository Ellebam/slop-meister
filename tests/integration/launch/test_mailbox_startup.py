"""Every startup route prepares the own inbox before the model can skip it."""

import json
import subprocess
import sys

import pytest

from slopmeister.dispatch import command as dispatcher
from slopmeister.launch import command
from slopmeister.launch.model import INBOX_NOTICE, Launch
from tests.integration.launch.helpers import executable

AGENT = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ['MAILBOX_CALLS'], 'a') as out:
    out.write(json.dumps(['agent', sys.argv[-1]]) + '\\n')
"""

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
    agent = executable(tmp_path / "bin/agent", AGENT)
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
        launch = Launch("fixture", "fixture", str(workspace.parent), claude_bin=str(agent))
        launch.wt = workspace
        launch.kickoff_file.write_text("Synthetic arithmetic\n")
        launch.line = command.line(launch)
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
    lookup = ["orchestration", "run-current", "--from", "term_fixture", "--full"]
    expected = [["terminal", "list"], lookup]
    if case == "new":
        create = ["orchestration", "run-create", "--from", "term_fixture"]
        expected.append([*create, "--objective", workspace.name, "--full"])
    assert observed == [*expected, ["agent", "Synthetic arithmetic"]]
    assert "task inbox ready: run_fixture" in result.stderr
    assert not (workspace.parent / "BREACH").exists()


@pytest.mark.parametrize(
    "route", ["worker", "reported-dispatcher-line", "same-terminal-dispatcher"]
)
def test_failed_inbox_setup_reaches_the_first_prompt(tmp_path, monkeypatch, route):
    """Bug: the failure reached only the pane's stderr, which the agent's screen hides."""
    workspace, calls, agent = _world(tmp_path, monkeypatch, "lookup-error")
    result = subprocess.run(_startup(workspace, agent, route), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    observed = [json.loads(line) for line in calls.read_text().splitlines()]
    assert observed[-1] == ["agent", "Synthetic arithmetic" + INBOX_NOTICE]
    assert "task inbox unavailable: unavailable" in result.stderr


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
    assert len(observed) == reads + 1
    assert observed[-1] == ["agent", "Synthetic arithmetic" + INBOX_NOTICE]
    assert "task inbox unavailable:" in result.stderr
    assert "PRIVATE_BODY" not in result.stdout + result.stderr
    assert not (workspace.parent / "BREACH").exists()
