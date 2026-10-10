"""The Orca seam trusts what Orca reports about itself, never its bare ok."""

import json
from pathlib import Path
import subprocess

import pytest

from slopmeister.errors import SlopmeisterError
from slopmeister.launch import terminal

DOWN = {"app": {"running": False}, "runtime": {"reachable": False}}
UP = {"app": {"running": True}, "runtime": {"reachable": True}}


class Orca:
    """Answers each Orca command from a queue and records what was asked."""

    def __init__(self, **answers):
        self.answers = {key: list(value) for key, value in answers.items()}
        self.calls: list[list[str]] = []

    def run(self, args, **_):
        assert args[0] == terminal.binary() and args[-1] == "--json", args
        self.calls.append(args[1:-1])
        key = " ".join(args[1:3]) if args[1] in ("terminal", "repo", "worktree") else args[1]
        queue = self.answers.get(key, [])
        result = queue.pop(0) if queue else None
        if isinstance(result, Exception):
            raise result
        reply = {"ok": result is not None, "result": result}
        return subprocess.CompletedProcess(args, 0, json.dumps(reply), "")

    def asked(self, command: str) -> list[list[str]]:
        return [call for call in self.calls if " ".join(call).startswith(command)]


@pytest.fixture
def orca(monkeypatch):
    monkeypatch.delenv("PLOT_SESSION_ORCA", raising=False)

    def install(**answers):
        fake = Orca(**answers)
        monkeypatch.setattr(terminal.subprocess, "run", fake.run)
        return fake

    return install


def test_closed_app_is_opened_even_though_status_says_ok(orca):
    """Bug: `orca status` answers ok with the app closed, so a launch aimed at a dead app."""
    fake = orca(status=[DOWN, UP], open=[{}])
    assert terminal.ready()
    assert fake.asked("open") == [["open"]]


def test_orca_still_unreachable_after_open_is_not_ready(orca):
    """Bug: an unreachable Orca counted as usable and the launch failed instead of going manual."""
    orca(status=[DOWN, {"app": {"running": True}, "runtime": {"reachable": False}}], open=[{}])
    assert not terminal.ready()


def test_running_orca_is_not_reopened(orca):
    """Bug: every launch ran `orca open` and pulled Orca to the front."""
    fake = orca(status=[UP])
    assert terminal.ready()
    assert fake.asked("open") == []


def test_missing_cli_is_not_ready(monkeypatch):
    """Bug: a machine without Orca crashed the launcher instead of printing the line."""

    def missing(args, **_):
        raise FileNotFoundError(args[0])

    monkeypatch.setattr(terminal.subprocess, "run", missing)
    assert not terminal.ready()


def test_known_repository_is_not_added_again(orca):
    """Bug: every launch re-registered its repository in Orca."""
    fake = orca(**{"repo list": [{"repos": [{"path": "/r"}]}]})
    terminal.register(Path("/r"))
    assert fake.asked("repo add") == []


def test_unknown_repository_is_added(orca):
    """Bug: the first launch of a repository Orca had not seen found no workspace to open in."""
    fake = orca(**{"repo list": [{"repos": [{"path": "/other"}]}], "repo add": [{}]})
    terminal.register(Path("/r"))
    assert fake.asked("repo add") == [["repo", "add", "--path", "/r"]]


def test_open_returns_the_runtime_handle(orca):
    """Bug: the handle was lost, so a later redispatch could not close the tab."""
    created = {"terminal": {"handle": "term_1"}}
    fake = orca(**{"terminal create": [created]})
    assert (
        terminal.create(Path("/w"), "example-client-a", "/bin/zsh -l '/s/example-client-a.command'")
        == "term_1"
    )
    args = [
        "--worktree",
        "path:/w",
        "--title",
        "example-client-a",
        "--command",
        "/bin/zsh -l '/s/example-client-a.command'",
    ]
    assert fake.asked("terminal create") == [["terminal", "create", *args]]


def test_lost_create_reply_has_a_timeout_reason(orca):
    """Bug: a timed-out create was treated as a handle and written as garbage."""
    orca(**{"terminal create": [subprocess.TimeoutExpired("orca", 30)]})
    with pytest.raises(SlopmeisterError, match="^timeout$"):
        terminal.create(Path("/w"), "example-client-a", "line")


def test_name_links_the_issue_only_when_there_is_one(orca):
    """Bug: an empty issue argument unlinked or broke the workspace naming."""
    fake = orca(**{"worktree set": [{}, {}]})
    assert terminal.name(Path("/w"), "example-client-a", "")
    assert terminal.name(Path("/w"), "example-client-a", "337")
    base = ["worktree", "set", "--worktree", "path:/w", "--display-name", "example-client-a"]
    assert fake.asked("worktree set") == [base, [*base, "--issue", "337"]]


def test_terminals_maps_handles_to_workspaces(orca):
    """Bug: `terminal show` still answers for a closed handle, only the list tells it is gone."""
    listed = {"terminals": [{"handle": "term_1", "worktreePath": "/w"}], "truncated": False}
    orca(**{"terminal list": [listed]})
    assert terminal.terminals() == {"term_1": "/w"}


def test_truncated_list_is_unreadable(orca):
    """Bug: a handle beyond the list limit looked closed and closure reported success."""
    orca(**{"terminal list": [{"terminals": [], "truncated": True}]})
    assert terminal.terminals() is None


def test_orca_refusal_is_a_failure(orca):
    """Bug: an `ok: false` reply counted as success, so a refused name looked applied."""
    orca(**{"worktree set": [None]})
    assert not terminal.name(Path("/w"), "example-client-a", "")


def test_override_points_every_call_at_the_named_binary(monkeypatch):
    """Bug: launcher subprocesses under test drove the operator's real Orca."""
    seen = []

    def run(args, **_):
        seen.append(args[0])
        return subprocess.CompletedProcess(args, 0, "{}", "")

    monkeypatch.setattr(terminal.subprocess, "run", run)
    monkeypatch.setenv("PLOT_SESSION_ORCA", "/scratch/orca")
    terminal.ready()
    assert seen and set(seen) == {"/scratch/orca"}


def test_orca_is_started_without_the_callers_agent_variables(monkeypatch):
    """Bug: Orca started from an agent inherited its session token and passed it to every tab."""
    monkeypatch.delenv("PLOT_SESSION_ORCA", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "secret")
    monkeypatch.setenv("CODEX_SESSION_ID", "thread")
    monkeypatch.setenv("HOME", "/h")
    statuses, opened = [DOWN, UP], []

    def run(args, **kwargs):
        if args[1] == "open":
            opened.append(kwargs.get("env"))
        result = statuses.pop(0) if args[1] == "status" else {}
        return subprocess.CompletedProcess(args, 0, json.dumps({"ok": True, "result": result}), "")

    monkeypatch.setattr(terminal.subprocess, "run", run)
    assert terminal.ready()
    [env] = opened
    assert env is not None and env["HOME"] == "/h" and "PATH" in env
    assert "CLAUDE_CODE_MESSAGING_TOKEN" not in env and "CODEX_SESSION_ID" not in env


DESKTOP = (
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XDG_RUNTIME_DIR",
    "DBUS_SESSION_BUS_ADDRESS",
    "XAUTHORITY",
)


def test_a_closed_orca_on_linux_is_opened_with_the_desktop_session(monkeypatch):
    """Bug: Orca on Linux is started without its display and session bus, so no window opens."""
    seen: dict[str, str] = {}

    def run(args, env=None, **_):
        if args[1] == "open":
            seen.update(env)
        reply = {"ok": True, "result": DOWN if args[1] == "status" else {}}
        return subprocess.CompletedProcess(args, 0, json.dumps(reply), "")

    monkeypatch.setattr(terminal.subprocess, "run", run)
    for name in (*DESKTOP, "CODEX_SESSION_ID"):
        monkeypatch.setenv(name, "set")
    monkeypatch.setenv("SLOPMEISTER_PLATFORM", "linux")
    assert not terminal.ready()
    # An agent's own variables still never reach Orca, which hands its start environment on.
    assert set(DESKTOP) <= set(seen) and "HOME" in seen and "CODEX_SESSION_ID" not in seen
    seen.clear()
    monkeypatch.setenv("SLOPMEISTER_PLATFORM", "darwin")
    assert not terminal.ready()
    assert "HOME" in seen and not set(DESKTOP) & set(seen)
