"""Real Claude runs an allowed command shape by rule, asks on its exceptions and reviews the rest.

The stand-in classifier flags every call, so a command that runs was decided by a rule alone.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.integration.install.helpers import unlock_deliveries
from tests.integration.install.installer_helpers import (
    ROOT,
    environment,
    install,
    project,
    worktree,
)
from tests.integration.launch.test_permission import _launch_proof
from tests.native.install.intent_fixture import claude_host
from tests.native.install.test_permissions import RAN, client_command, shell_call
from tests.support import standin
from tests.support.fakes import fake_binary

pytestmark = pytest.mark.xdist_group("native-standin")
READ = "gh api --method GET repos/owner/repository/issues"
VIEW = "gh pr view 1"
STUBS = ("gh", "glab", "op", "az", "task")
# A rule names Orca by absolute path. The other platform's path does not exist on this host, so
# an allowed call fails to start and reaches no real terminal.
ORCA = next(
    path
    for path in ("/usr/bin/orca-ide", "/Applications/Orca.app/Contents/Resources/bin/orca")
    if not Path(path).exists()
)
SEND = ORCA + " terminal send --terminal term_standin --text continue --enter"
CLOSE = ORCA + " terminal close --terminal term_standin"
LAUNCH = f"task --dir {ROOT} plot-session -- repository example-app name"
REMOVE = f"{ROOT}/bin/slopmeister workspace-remove"
# What a started command prints: a stub's mark, the shell's word for the missing Orca binary or
# the real removal helper's refusal of a missing path.
STARTED = (RAN.lower(), "no such file", "workspace directory not found")
# The native host fixture reads a bounded number of frames, so a long list runs in batches.
BATCH = 8


@pytest.fixture(autouse=True)
def flagging_classifier(monkeypatch):
    original = standin.messages_events

    def flagged(call, body, turn):
        events = original(call, body, turn)
        for result in events[-2]["delta"].get("safeguard_results", []):
            for verdict in result["status"]["tool_uses"].values():
                verdict["outcome"] = "flagged"
        return events

    monkeypatch.setattr(standin, "messages_events", flagged)


def _workspace(root: Path, role: str) -> Path:
    if role == "proof":
        result, repo = _launch_proof(root, "live")
        assert result.returncode == 0, result.stderr
        return repo / ".worktrees/example-app-proof"
    root.mkdir()
    env, repo = environment(root), project(root / "project")
    workspace = worktree(repo, role)
    install(
        env, "--prepare", "example-app", workspace, *(["--manager"] if role == "manager" else [])
    )
    return workspace


def _session(root: Path, workspace: Path, commands: list[str]) -> list[tuple[dict, dict]]:
    """Run one real client session and return each call's result and permission decision."""
    for name in STUBS:
        fake_binary(root / "stubs", name, f'echo "{RAN} {name} $*;"')
    script = [shell_call("claude", command) for command in commands]
    server = standin.capture_server(root / "requests", "claude", script)
    try:
        client = client_command("claude", root, server.server_port)
        settings = client.cwd / ".claude/access-settings.json"
        settings.parent.mkdir()
        settings.write_bytes((workspace / ".claude/access-settings.json").read_bytes())
        claude_host(SimpleNamespace(client=client, server=server, command=""), approved=False)
    finally:
        server.shutdown()
        server.server_close()
    results = standin.tool_results(server.requests[-1])
    assert len(results) == len(commands), "a scripted call got no result"
    frames = client.evidence.with_suffix(".stdout").read_text().splitlines()
    decisions = {
        item["id"]: item["permission_decision"]
        for frame in map(json.loads, frames)
        for item in frame.get("tool_result_meta", [])
    }
    return [(result, decisions[f"standin_{index}"]) for index, result in enumerate(results)]


def _verdict(decision: dict) -> str:
    outcome = (decision["decision"], decision["source"])
    if outcome == ("reject", "config"):
        return "reviewed" if decision["reason_type"] == "classifier" else "denied"
    return {("accept", "config"): "ran", ("reject", "user_reject"): "asked"}[outcome]


def _verdicts(root: Path, commands: list[str], role: str = "worker") -> dict[str, str]:
    """Run each command in one launched-session configuration and name what decided it."""
    workspace = _workspace(root / "install", role)
    found = {}
    try:
        for start in range(0, len(commands), BATCH):
            batch = commands[start : start + BATCH]
            session = _session(root / f"session-{start}", workspace, batch)
            for command, (result, decision) in zip(batch, session, strict=True):
                found[command] = _verdict(decision)
                output = json.dumps(result).lower()
                executed = any(mark in output for mark in STARTED)
                assert executed is (found[command] == "ran"), command
    finally:
        unlock_deliveries(root)
    return found


def _reviewed(root: Path, commands: list[str], role: str = "worker") -> dict[str, str]:
    """An allowed read after each command keeps the client from asking after repeated blocks."""
    script = [step for command in commands for step in (command, VIEW)]
    found = _verdicts(root, script, role)
    assert found.pop(VIEW) == "ran"
    return found


def test_explicit_get_api_reads_run_by_rule(tmp_path):
    """Bug: an ordered API read waits for a reviewer that can refuse it."""
    commands = [
        READ,
        "gh api -X GET repos/owner/repository/issues",
        "glab api --method GET projects/1/issues",
        "glab api -X GET projects/1/issues",
        "gh api --method GET 'search/issues?q=is:open&per_page=5'",
        "glab api --method GET projects/group%2Fproject/issues",
        READ + " --paginate --jq '.[].number'",
    ]
    assert _verdicts(tmp_path, commands) == dict.fromkeys(commands, "ran")


def test_api_read_exceptions_ask_and_do_not_run(tmp_path):
    """Bug: an allowed read prefix carries a second method, a body or a credential endpoint."""
    commands = [
        READ + " --method DELETE",
        READ + " --method=POST",
        READ + " -XPOST",
        READ + " -iX DELETE",
        READ + " --input body.json",
        READ + " -f title=x",
        READ + " --hostname other.invalid",
        "gh api --method GET --method DELETE repos/owner/repository",
        "gh api --method GET repos/owner/repository/actions/variables",
        "glab api --method GET projects/1/triggers",
        "glab api -X GET projects/1/variables",
        "glab api --method GET projects/1/pipeline_schedules/2",
        "glab api -X GET projects/1/terraform/state/main",
        "glab api --method GET projects/1/%76ariables",
        "glab api --method GET projects/1/pipeline%5fschedules/2",
        "gh api -X GET repos/owner/repository/actions/%53ecrets",
    ]
    assert _verdicts(tmp_path, commands) == dict.fromkeys(commands, "asked")


def test_other_api_shapes_reach_the_reviewer(tmp_path):
    """Bug: a read rule also runs a chained write, a shell pipe or a command without the method."""
    commands = [
        READ + " && gh issue close 1",
        READ + " | sh",
        "X=1 " + READ,
        "gh api repos/owner/repository",
        "gh api --method POST repos/owner/repository/issues",
    ]
    assert _reviewed(tmp_path, commands) == dict.fromkeys(commands, "reviewed")


def test_mailbox_and_terminal_reads_run_by_rule(tmp_path):
    """Bug: a mailbox check, a peer message or a terminal read waits for a reviewer."""
    commands = [
        ORCA + " orchestration check --terminal term_standin",
        ORCA + " orchestration send --to run:run_standin --body text",
        ORCA + " terminal read --terminal term_standin",
        ORCA + " terminal list",
    ]
    assert _verdicts(tmp_path, commands) == dict.fromkeys(commands, "ran")


def test_remote_writes_and_tier_two_reach_the_reviewer(tmp_path):
    """Bug: a rule alone runs a merge, a raw rerun, a tracker write or a tier-two command."""
    commands = [
        "gh pr merge 12 --squash --delete-branch",
        "gh pr merge 12 --admin",
        "glab mr merge 12",
        "az repos pr update --status completed --id 12",
        "az repos pr update --status completed --id 12 --bypass-policy true",
        "gh run rerun 123 --failed",
        "glab ci retry 123",
        "gh issue create --title title --body text",
        "gh issue comment 1 --body text",
        "gh issue edit 1 --add-label bug",
        "gh pr create --title title --body text",
        "gh pr comment 1 --body text",
        "gh pr edit 1 --title title",
        "glab issue create --title title",
        "glab issue note 1 --message text",
        "glab issue update 1 --title title",
        "glab mr create --title title --description text",
        "glab mr create --fill",
        "glab mr note 1 --message text",
        "glab mr update 1 --title title",
        "op tier-two -- true",
    ]
    assert _reviewed(tmp_path, commands) == dict.fromkeys(commands, "reviewed")


def test_kept_commands_reach_the_reviewer(tmp_path):
    """Bug: a cancel, a close, the desktop route or a worker's send or launch runs by rule."""
    commands = [
        "gh run cancel 123",
        "glab ci cancel 123",
        "gh pr close 12",
        "gh pr merge 12 && gh repo delete owner/repository --yes",
        "SECRET_ASK_REASON=deploy op tier-two -- true",
        "op desktop -- true",
        "az repos pr update --id 12 --status completed",
        SEND,
        CLOSE,
        LAUNCH,
    ]
    assert _reviewed(tmp_path, commands) == dict.fromkeys(commands, "reviewed")


def test_manager_session_sends_terminal_input_and_runs_session_helpers_by_rule(tmp_path):
    """Bug: a manager's ordered relay, launch or removal waits for a reviewer, or force runs."""
    task = f"task --dir {ROOT}"
    expected = {
        SEND: "ran",
        f"{task} --taskfile other.yml plot-session -- repository example-app name": "reviewed",
        CLOSE: "ran",
        f"{task} plot-session other -- repository example-app name": "reviewed",
        LAUNCH + " --redispatch < kickoff.md": "ran",
        LAUNCH + " --abandon --handoff notes.md": "asked",
        f"{task} slot:up -- repository example-app name": "ran",
        f"{task} slot:down -- repository example-app name --force": "asked",
        f"{task} slot:down -- repository example-app name": "ran",
        f"{REMOVE} --force {tmp_path}/absent": "asked",
        f"{REMOVE} --fo {tmp_path}/absent": "asked",
        f"{task} workspace:remove -- {tmp_path}/absent --f": "asked",
        f"{task} workspace:remove -- {tmp_path}/absent": "ran",
        f"{REMOVE} {tmp_path}/absent": "ran",
    }
    assert _verdicts(tmp_path, list(expected), "manager") == expected


def test_proof_session_is_denied_remote_writes_and_terminal_input(tmp_path):
    """Bug: an allow rule lets a proof session merge, post or steer a terminal for its owner."""
    commands = [
        "gh pr merge 12",
        "glab mr merge 12",
        "gh issue comment 1 --body text",
        "glab mr create --title title",
        "gh run rerun 123",
        "az repos pr update --status completed --id 12",
        SEND,
        CLOSE,
    ]
    found = _verdicts(tmp_path, [*commands, VIEW], "proof")
    assert found.pop(VIEW) == "ran"
    assert found == dict.fromkeys(commands, "denied")
