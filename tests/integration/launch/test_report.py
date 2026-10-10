"""The launch report states the observed model with its evidence, or says it is unconfirmed."""

import hashlib
import io
import json
from pathlib import Path
import re
import sys

import pytest

from slopmeister.launch import confirm
from slopmeister.launch import model as launch_model
from slopmeister.session import launch_identity
from tests.integration.launch.helpers import declare, executable, launch_here, machine

# One double answers pgrep, ps, lsof, claude and orca. The terminal it "creates" writes the
# session record a real worker would, with the model record only when REPORT_MODEL is set.
DRIVER = """#!/usr/bin/env python3
import json, os, re, sys
from pathlib import Path
env, command = os.environ, Path(sys.argv[0]).name
wt, tool, model = env["REPORT_WT"], env["REPORT_TOOL"], env["REPORT_MODEL"]
opened = Path(env["PLOT_SESSION_STATE_DIR"]) / "opened"
if command == "pgrep" and not opened.exists():
    sys.exit(1)
if command in ("pgrep", "ps", "lsof", "claude"):
    answers = {"pgrep": "909090", "ps": f"codex --no-daemon -C {wt}", "lsof": "n" + wt}
    print(answers.get(command, json.dumps([{"pid": 909090}])))
    sys.exit(0)
if command == "orca" and sys.argv[1:3] != ["terminal", "create"]:
    status = {"app": {"running": True}, "runtime": {"reachable": True}}
    print(json.dumps({"ok": True, "result": status if sys.argv[1] == "status" else {}}))
    sys.exit(0)
name = sys.argv[sys.argv.index("--title") + 1]
kickoff = (opened.parent / f"{name}.md").read_text().rstrip("\\n")
if tool == "codex":
    thread = "11111111-1111-4111-8111-111111111111"
    path = Path(env["CODEX_HOME"]) / f"sessions/rollout-2026-09-06T00-00-00-{thread}.jsonl"
    text = [{"type": "input_text", "text": kickoff}]
    message = {"type": "message", "role": "user", "content": text}
    user = {"type": "response_item", "payload": message}
    rows = [{"type": "session_meta", "payload": {"cwd": wt, "id": thread}}, user]
    record = {"type": "turn_context", "payload": {"model": model}}
else:
    line = (opened.parent / f"{name}.command").read_text()
    session = re.search(r"--session-id ([0-9a-f-]+)", line)[1]
    path = Path(env["CLAUDE_CONFIG_DIR"]) / f"projects/fixture/{session}.jsonl"
    rows = [{"type": "user", "sessionId": session, "cwd": wt, "message": {"content": kickoff}}]
    record = {"type": "assistant", "message": {"model": model}}
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text("".join(json.dumps(row) + "\\n" for row in rows + ([record] if model else [])))
opened.write_text(str(path))
print(json.dumps({"ok": True, "result": {"terminal": {"handle": "term_fixture"}}}))
"""
UNCONFIRMED = "plot-session: worker running, model unconfirmed after 60s, kickoff delivered"
REQUESTED = ("--model", "requested")


def _world(tmp_path, monkeypatch, tool: str, model: str):
    world = machine(tmp_path)
    driver = executable(tmp_path / "driver", DRIVER)
    for command in ("pgrep", "ps", "lsof", "claude", "orca"):
        (tmp_path / "bin" / command).unlink(missing_ok=True)
        (tmp_path / "bin" / command).symlink_to(driver)
    wt = world.sessions / "example-client-report"
    world.env.update(
        PLOT_DECLARATIONS=str(declare(tmp_path / "declared", "example-client", "-", tasks="vault")),
        PLOT_SESSION_NO_LAUNCH="0",
        PLOT_SESSION_ORCA=str(tmp_path / "bin/orca"),
        REPORT_WT=str(wt), REPORT_TOOL=tool, REPORT_MODEL=model,
    )  # fmt: skip
    polls = []
    monkeypatch.setattr(launch_model, "pause", polls.append)
    return world, wt, polls


def _release_reply_endpoint(world) -> None:
    """A live Claude launch reserves a /tmp directory for its reply socket, nothing binds it."""
    command = world.state / "example-client-report.command"
    text = command.read_text() if command.exists() else ""
    for endpoint in re.findall(r"CLAUDE_BG_RENDEZVOUS_SOCK='?([^' ]+)", text):
        Path(endpoint).parent.rmdir()


def _assert_identity(world, wt, tool):
    digest = hashlib.sha256(str(wt.resolve()).encode()).hexdigest()
    identity = Path(world.env["HOME"]) / ".local/state/slopmeister/launch" / f"{digest}.json"
    record = json.loads(identity.read_text())
    assert record["state"] == "confirmed"
    assert record["task"] == "example-client-report" and record["tool"] == tool
    assert record["workspace"] == str(wt.resolve())
    evidence = Path((world.state / "opened").read_text())
    first = json.loads(evidence.read_text().splitlines()[0])
    session = first["sessionId"] if tool == "claude" else first["payload"]["id"]
    assert record["session_id"] == session


CASES = {
    "observed": (REQUESTED, "requested", 0),
    "absent": (REQUESTED, "", 1),
    "no-option": ((), "requested", 0),
    "legacy": (("--", *REQUESTED), "requested", 0),
}


@pytest.mark.parametrize("tool", ["claude", "codex"])
@pytest.mark.parametrize("case", CASES.values(), ids=CASES.keys())
def test_report_states_evidence_or_unconfirmed(tmp_path, monkeypatch, capfd, tool, case):
    """Bug: a missing model record reads as confirmed, polls forever, or invites a relaunch."""
    args, model, code = case
    world, wt, polls = _world(tmp_path, monkeypatch, tool, model)
    worker = ("example-client", "example-client-report", "--tool", tool)
    try:
        assert launch_here(monkeypatch, world, *worker, *args) == code
    finally:
        _release_reply_endpoint(world)
    out, err = capfd.readouterr()
    evidence = (world.state / "opened").read_text()
    assert f"  pid: 909090\n  directory: {wt}\n" in out and f"  evidence: {evidence}\n" in out
    expected = ['  model requested: "requested"'] if args == REQUESTED else []
    if expected and code == 0:
        line, kind = (3, "turn_context") if tool == "codex" else (2, "assistant")
        expected += ['  model observed: "requested"', "  model comparison: same"]
        expected.append(f"  model evidence: {evidence}:{line} ({kind})")
    assert [line for line in out.splitlines() if line.startswith("  model ")] == expected
    if code:
        assert UNCONFIRMED in err and "Inspect the existing worker" in err and 0 < len(polls) <= 60
    else:
        assert not polls
    assert not any(advice in err for advice in ("Manual fallback", "slot:down", "remove"))
    assert (
        wt.is_dir() and (world.state / "example-client-report.orca").read_text() == "term_fixture\n"
    )
    _assert_identity(world, wt, tool)


class BrokenOutput(io.StringIO):
    def write(self, text):
        raise BrokenPipeError("closed launch output")


@pytest.mark.parametrize("tool", ["claude", "codex"])
def test_delivery_report_failure_keeps_confirmed_identity(tmp_path, monkeypatch, capfd, tool):
    """Bug: _finish_delivery reports before saving, so broken stdout leaves prepared identity."""
    world, wt, _ = _world(tmp_path, monkeypatch, tool, "")
    deliver = confirm.deliver

    def close_output(*args):
        delivery = deliver(*args)
        monkeypatch.setattr(sys, "stdout", BrokenOutput())
        return delivery

    monkeypatch.setattr(confirm, "deliver", close_output)
    try:
        assert (
            launch_here(
                monkeypatch, world, "example-client", "example-client-report", "--tool", tool
            )
            == 1
        )
    finally:
        _release_reply_endpoint(world)
    _, err = capfd.readouterr()
    _assert_identity(world, wt, tool)
    assert "BrokenPipeError: closed launch output" in err
    assert "launcher identity unconfirmed" not in err
    assert wt.is_dir() and (world.state / "opened").exists()


@pytest.mark.parametrize("tool", ["claude", "codex"])
@pytest.mark.parametrize("failure", [OSError, ValueError])
def test_identity_write_failure_refuses_normal_launch(tmp_path, monkeypatch, capfd, tool, failure):
    """Bug: failed identity persistence announces normal delivery without a usable identity."""
    world, wt, _ = _world(tmp_path, monkeypatch, tool, "")
    write = launch_identity.write

    def fail_confirmation(workspace, identity):
        if identity[2] is not None:
            raise failure("identity store refused")
        return write(workspace, identity)

    monkeypatch.setattr(launch_identity, "write", fail_confirmation)
    try:
        assert (
            launch_here(
                monkeypatch, world, "example-client", "example-client-report", "--tool", tool
            )
            == 1
        )
    finally:
        _release_reply_endpoint(world)
    out, err = capfd.readouterr()
    record = json.loads(launch_identity.path(wt).read_text())
    evidence = (world.state / "opened").read_text()
    assert record["state"] == "prepared" and "session_id" not in record
    assert "plot-session: delivered" not in out and "launcher identity: confirmed" not in out
    assert "launcher identity unconfirmed" in err and "kickoff delivered" in err
    assert "identity store refused" in err and "Inspect the existing worker" in err
    assert str(wt) in err and evidence in err and wt.is_dir()
