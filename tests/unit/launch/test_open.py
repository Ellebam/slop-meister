"""Where a prepared launch opens: an Orca terminal, or a printed line for any terminal."""

import json
from pathlib import Path
import subprocess

import pytest

from slopmeister.launch import cli, confirm
from slopmeister.launch import model as launch_model
from slopmeister.launch.model import ROOT, Launch, Stop


class Seam:
    """The Orca seam as the launcher sees it, recording every call."""

    def __init__(self, ready=True, handle="term_1", named=True):
        self.state = {"ready": ready, "handle": handle, "named": named}
        self.calls: list[tuple] = []

    def ready(self):
        self.calls.append(("ready",))
        return self.state["ready"]

    def register(self, repo):
        self.calls.append(("register", repo))

    def create(self, workspace, title, command):
        self.calls.append(("create", workspace, title, command))
        return self.state["handle"]

    def name(self, workspace, display, issue):
        self.calls.append(("name", workspace, display, issue))
        return self.state["named"]


@pytest.fixture
def seam(monkeypatch, tmp_path):
    monkeypatch.setenv("PLOT_SESSION_STATE_DIR", str(tmp_path))

    def install(**state):
        fake = Seam(**state)
        for method in ("ready", "register", "create", "name"):
            monkeypatch.setattr(cli.terminal, method, getattr(fake, method))
        return fake

    return install


def _worktree(tmp_path: Path, **fields) -> Launch:
    wt = tmp_path / "repo/.worktrees/example-client-a"
    return Launch(
        "example-client", "example-client-a", "/repo", repo=tmp_path / "repo", wt=wt, **fields
    )


def test_unreachable_orca_stops_before_anything_opens(seam, tmp_path, capsys):
    """Bug: an unreachable Orca printed a line to paste, or the caller believed a launch began."""
    fake = seam(ready=False)
    launch = _worktree(tmp_path)
    with pytest.raises(Stop, match="Orca is unreachable") as stopped:
        cli._open(launch)
    assert fake.calls == [("ready",)] and not launch.open_attempted
    assert "workstation skill" in stopped.value.text
    assert "/bin/zsh -l" not in stopped.value.text + capsys.readouterr().out


def test_worktree_opens_named_with_its_issue_and_records_the_handle(seam, tmp_path, capsys):
    """Bug: the handle was not recorded, or the workspace carried no session name or issue."""
    fake = seam()
    launch = _worktree(tmp_path, issue_id="337")
    cli._open(launch)
    line = f" /bin/zsh -l '{tmp_path}/example-client-a.command'"
    assert fake.calls == [
        ("ready",),
        ("register", tmp_path / "repo"),
        ("create", launch.wt, "example-client-a", line),
        ("name", launch.wt, "example-client-a", "337"),
    ]
    assert launch.orca_file.read_text() == "term_1\n"
    said = capsys.readouterr()
    assert said.out == "plot-session: Orca terminal term_1 opened, confirming delivery by polling\n"
    assert said.err == ""


def test_directory_session_opens_in_the_checkout_and_renames_nothing(seam, tmp_path):
    """Bug: a directory session renamed the operator's shared Slopmeister workspace."""
    fake = seam()
    launch = Launch(
        "example-client", "example-client-a", "", wt=tmp_path / "sessions/example-client-a"
    )
    cli._open(launch)
    assert [call[0] for call in fake.calls] == ["ready", "create"]
    assert fake.calls[1][1] == ROOT


def test_failed_name_still_reaches_delivery(seam, tmp_path, capsys):
    """Bug: a naming failure over a live session reported failure and invited a relaunch."""
    seam(named=False)
    launch = _worktree(tmp_path)
    cli._open(launch)
    assert "did not take the workspace name, continuing" in capsys.readouterr().err
    assert launch.orca_file.read_text() == "term_1\n"


def test_lost_create_reply_polls_instead_of_printing_a_second_line(seam, tmp_path, capsys):
    """Bug: a create that opened the tab but lost its reply printed a line, two agents ran."""
    seam(handle=None)
    launch = _worktree(tmp_path)
    cli._open(launch)
    said = capsys.readouterr()
    assert "polling for the session anyway" in said.err
    assert "/bin/zsh -l" not in said.out
    assert not launch.orca_file.exists()


def test_orca_launch_keeps_the_short_wait(monkeypatch, tmp_path):
    """Bug: a failed Orca launch sat ten minutes before saying so."""
    polls = []
    monkeypatch.setattr(launch_model, "pause", polls.append)
    monkeypatch.setattr(confirm, "_pids", lambda launch: [])
    with pytest.raises(Stop, match="appeared within 20s") as stop:
        confirm._one_pid(_worktree(tmp_path))
    assert len(polls) == confirm.PROCESS_POLL
    # Bug: a slow tab plus a printed runnable line started two agents for one session.
    assert "/bin/zsh -l" not in stop.value.text and "--redispatch" in stop.value.text


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        (
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "permission_denied",
                        "message": "COMMAND_CONTENT KICKOFF_CONTENT",
                    },
                }
            ),
            "permission_denied",
        ),
        (subprocess.TimeoutExpired(["orca", "COMMAND_CONTENT KICKOFF_CONTENT"], 30), "timeout"),
        ("COMMAND_CONTENT KICKOFF_CONTENT", "unreadable_reply"),
        (OSError("COMMAND_CONTENT KICKOFF_CONTENT"), "execution_failed"),
        (json.dumps({"ok": True, "result": {"terminal": "KICKOFF_CONTENT"}}), "unreadable_reply"),
        (json.dumps({"ok": False, "error": {"code": "bad\nKICKOFF_CONTENT"}}), "unreadable_reply"),
        (json.dumps({"ok": False, "error": ["KICKOFF_CONTENT"]}), "unreadable_reply"),
        ("[]", "unreadable_reply"),
    ],
)
def test_create_failure_prints_one_safe_reason_and_keeps_polling(
    reply, reason, monkeypatch, tmp_path, capsys
):
    calls = []

    def run(args, **_):
        calls.append(args)
        if isinstance(reply, Exception):
            raise reply
        return subprocess.CompletedProcess(args, 1, reply, "COMMAND_CONTENT KICKOFF_CONTENT")

    monkeypatch.setenv("PLOT_SESSION_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(cli.terminal, "ready", lambda: True)
    monkeypatch.setattr(cli.terminal, "register", lambda _: None)
    monkeypatch.setattr(cli.terminal.subprocess, "run", run)
    launch = _worktree(tmp_path)
    cli._open(launch)
    said = capsys.readouterr()
    assert reason in said.err and "polling for the session anyway" in said.err
    assert len(said.err.splitlines()) == 1 and said.out == ""
    assert "COMMAND_CONTENT" not in said.err and "KICKOFF_CONTENT" not in said.err
    assert launch.open_attempted and not launch.orca_file.exists()
    assert len(calls) == 1 and calls[0][1:3] == ["terminal", "create"]


@pytest.mark.parametrize("recovers", [True, False])
def test_selector_retry_opens_once_or_stops_at_the_bound(recovers, monkeypatch, tmp_path, capsys):
    calls, opened, now = [], [], [0.0]

    def run(args, **_):
        calls.append(args)
        now[0] += 20
        if recovers and len(calls) >= 2:
            opened.append("term_retry")
            reply = {"ok": True, "result": {"terminal": {"handle": "term_retry"}}}
        else:
            reply = {"ok": False, "error": {"code": "selector_not_found"}}
        return subprocess.CompletedProcess(args, 0, json.dumps(reply), "")

    monkeypatch.setenv("PLOT_SESSION_STATE_DIR", str(tmp_path))
    for method in ("ready", "register", "name"):
        monkeypatch.setattr(cli.terminal, method, lambda *_: True)
    monkeypatch.setattr(cli.terminal.subprocess, "run", run)
    monkeypatch.setattr(cli.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    launch = _worktree(tmp_path)
    cli._open(launch)
    said = capsys.readouterr()
    assert len(calls) > 1 and now[0] <= 60
    assert opened == (["term_retry"] if recovers else [])
    assert launch.orca_file.exists() is recovers
    assert ("selector_not_found" in said.err) is (not recovers)
    assert ("polling for the session anyway" in said.err) is (not recovers)
    assert len(said.err.splitlines()) == (0 if recovers else 1)


def test_refusal_then_handleless_reply_reports_the_latest_failure(monkeypatch, tmp_path, capsys):
    replies = iter(
        [
            {"ok": False, "error": {"code": "selector_not_found"}},
            {"ok": True, "result": {"terminal": {}}},
        ]
    )
    calls = []

    def run(args, **_):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, json.dumps(next(replies)), "")

    monkeypatch.setenv("PLOT_SESSION_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(cli.terminal, "ready", lambda: True)
    monkeypatch.setattr(cli.terminal, "register", lambda _: None)
    monkeypatch.setattr(cli.terminal.subprocess, "run", run)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    launch = _worktree(tmp_path)
    cli._open(launch)
    said = capsys.readouterr()
    assert "unreadable_reply" in said.err and "selector_not_found" not in said.err
    assert "polling for the session anyway" in said.err and len(said.err.splitlines()) == 1
    assert len(calls) == 2 and not launch.orca_file.exists()
