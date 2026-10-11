"""Dispatcher parsing preserves its optional name and model surface."""

import subprocess

import pytest

from slopmeister.dispatch import cli, command
from slopmeister.errors import SlopmeisterError, UsageError


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], command.Settings("claude", "", "")),
        (["codex"], command.Settings("codex", "", "")),
        (["claude", "phone"], command.Settings("claude", "phone", "")),
        (
            ["codex", "phone", "--model", "gpt-5"],
            command.Settings("codex", "phone", "gpt-5"),
        ),
    ],
)
def test_optional_name_and_model_keep_the_old_argument_order(argv, expected):
    """Bug: adding Python parsing made the formerly valid unnamed form fail."""
    assert cli.parse(argv) == expected


@pytest.mark.parametrize(
    "argv",
    [
        ["other"],
        ["claude", "Bad"],
        ["claude", "bad/name"],
        ["claude", "has space"],
        ["claude", "--unknown"],
        ["claude", "phone", "extra"],
        ["claude", "phone", "--model"],
        ["claude", "phone", "--model", "one", "--model", "two"],
        ["--model", "one"],
        ["claude", "--model=one"],
    ],
)
def test_invalid_dispatch_arguments_are_refused(argv):
    """Bug: an option or hostile name was treated as state-bearing input."""
    with pytest.raises(UsageError):
        cli.parse(argv)


@pytest.mark.parametrize("model", ["", "-danger"])
def test_empty_or_option_shaped_model_is_refused(model):
    """Bug: the model value could inject a native option or silently disappear."""
    with pytest.raises(SlopmeisterError):
        cli.parse(["claude", "phone", "--model", model])


def test_launch_line_quotes_workspace_arguments_and_kickoff(tmp_path):
    """Bug: spaces or quotes changed the same-tab command seen by the tool."""
    line = command.line(tmp_path / "work tree", ["tool", "a'b"], tmp_path / "kick off")
    assert "cd '" in line and "'a'\\''b'" in line
    assert ' -- "$(cat ' in line and "kick off" in line


def test_codex_dispatcher_pins_approval_policy_and_reviewer(tmp_path, monkeypatch):
    """Bug: a dispatcher inherits permissive approval settings unlike its worker."""
    executable = tmp_path / ".local/bin/codex"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    monkeypatch.setattr(command.Path, "home", lambda: tmp_path)
    args = command.prefix(command.Settings("codex", "", ""), tmp_path / "workspace")
    pins = [args[index + 1] for index, value in enumerate(args[:-1]) if value == "-c"]
    assert pins.count('approval_policy="on-request"') == 1
    assert pins.count('approvals_reviewer="auto_review"') == 1


def _guard(monkeypatch, path) -> None:
    monkeypatch.setattr(command, "sleep_guard", lambda: (str(path), "-i"))


def test_only_no_launch_fixture_may_skip_the_sleep_guard(tmp_path, monkeypatch):
    """Bug: portable dispatch fixtures required a system executable they never run."""
    _guard(monkeypatch, tmp_path / "missing")
    monkeypatch.delenv("DISPATCH_NO_LAUNCH", raising=False)
    with pytest.raises(SlopmeisterError, match="sleep guard not found"):
        cli.main(["claude"])
    monkeypatch.setenv("DISPATCH_NO_LAUNCH", "1")
    monkeypatch.setattr(
        cli,
        "_prepare",
        lambda settings: (tmp_path, tmp_path / "kickoff", "text", ["tool"], {}),
    )
    assert cli.main(["claude"]) == 0


def test_codex_launch_reaches_execute_without_daemon_preflight(tmp_path, monkeypatch):
    """Bug: a standalone dispatcher is still blocked by the shared daemon's preflight."""
    executable = tmp_path / "guard"
    executable.write_text("")
    executable.chmod(0o755)
    _guard(monkeypatch, executable)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.delenv("DISPATCH_NO_LAUNCH", raising=False)
    monkeypatch.setattr(
        cli,
        "_prepare",
        lambda settings: (tmp_path, tmp_path / "kickoff", "text", ["tool"], {}),
    )
    called = []
    monkeypatch.setattr(cli.command, "execute", lambda *args: called.append(args))
    assert cli.main(["codex"]) == 0
    assert called == [(tmp_path, ["tool"], "text")]


def test_open_uses_orca_without_preparing_in_the_callers_session(tmp_path, monkeypatch, capsys):
    """Bug: phone bootstrap replaced its own Claude session with the dispatcher."""
    from types import SimpleNamespace

    runnable = tmp_path / "guard"
    runnable.write_text("")
    runnable.chmod(0o755)
    _guard(monkeypatch, runnable)
    monkeypatch.setattr(cli, "_process_exists", lambda pattern: False)
    monkeypatch.setattr(cli, "_prepare", lambda settings: pytest.fail("prepared in caller"))
    calls = []
    monkeypatch.setattr(
        cli,
        "terminal",
        SimpleNamespace(
            ready=lambda: True,
            register=lambda repo: calls.append(("register", repo)),
            create=lambda *args: calls.append(("create", args)) or "term_fixture",
        ),
        raising=False,
    )
    assert cli.main(["--open", "claude", "phone-claude"]) == 0
    assert [name for name, _ in calls] == ["register", "create"]
    assert "term_fixture" in capsys.readouterr().out


def test_open_stops_when_orca_is_unreachable(monkeypatch, capsys):
    """Bug: an unreachable Orca printed a command for a person to paste into another terminal."""
    from types import SimpleNamespace

    monkeypatch.setattr(
        cli,
        "terminal",
        SimpleNamespace(ready=lambda: False, register=lambda repo: pytest.fail("registered")),
    )
    with pytest.raises(SlopmeisterError, match="Orca is unreachable") as stopped:
        cli._open(command.Settings("claude", "phone-claude", ""))
    assert "workstation skill" in str(stopped.value)
    assert "task' 'dispatch'" not in str(stopped.value) + capsys.readouterr().out


def test_open_without_a_terminal_handle_requires_inspection(monkeypatch, capsys):
    """Bug: an unconfirmed terminal create printed a rerun line and started two dispatchers."""
    from types import SimpleNamespace

    monkeypatch.setattr(
        cli,
        "terminal",
        SimpleNamespace(ready=lambda: True, register=lambda repo: None, create=lambda *args: None),
    )
    with pytest.raises(SlopmeisterError, match="unconfirmed"):
        cli._open(command.Settings("claude", "phone-claude", ""))
    assert "run this" not in capsys.readouterr().out


def test_open_preserves_inspection_advice_for_a_real_create_refusal(monkeypatch):
    calls = []

    def run(args, **_):
        calls.append(args)
        return subprocess.CompletedProcess(
            args, 1, '{"ok":false,"error":{"code":"selector_not_found"}}', ""
        )

    monkeypatch.setattr(cli.terminal, "ready", lambda: True)
    monkeypatch.setattr(cli.terminal, "register", lambda _: None)
    monkeypatch.setattr(cli.terminal.subprocess, "run", run)
    with pytest.raises(SlopmeisterError) as stopped:
        cli._open(command.Settings("claude", "phone-claude", ""))
    assert str(stopped.value) == (
        "Orca terminal creation is unconfirmed, inspect Orca before retrying"
    )
    assert len(calls) == 1 and calls[0][1:3] == ["terminal", "create"]


def test_open_name_collision_refuses_before_orca_start(tmp_path, monkeypatch):
    """Bug: a second phone request opened an Orca tab before detecting the live dispatcher."""
    from types import SimpleNamespace

    runnable = tmp_path / "guard"
    runnable.write_text("")
    runnable.chmod(0o755)
    _guard(monkeypatch, runnable)
    monkeypatch.setattr(cli, "_process_exists", lambda pattern: True)
    monkeypatch.setattr(
        cli,
        "terminal",
        SimpleNamespace(ready=lambda: pytest.fail("Orca was started")),
    )
    with pytest.raises(SlopmeisterError, match="already carries dispatcher name"):
        cli.main(["--open", "claude", "phone-claude"])


def test_open_codex_pins_normal_home_in_terminal(tmp_path, monkeypatch):
    """Bug: Orca's own CODEX_HOME sent the opened dispatcher to the wrong trust and daemon store."""
    from pathlib import Path
    from types import SimpleNamespace

    foreign = tmp_path / "orca-codex-home"
    monkeypatch.setenv("CODEX_HOME", str(foreign))
    created = []
    monkeypatch.setattr(
        cli,
        "terminal",
        SimpleNamespace(
            ready=lambda: True,
            register=lambda repo: None,
            create=lambda *args: created.append(args[-1]) or "term_codex",
        ),
    )
    settings = command.Settings("codex", "phone-codex", "")
    assert cli._open(settings) == 0
    normal = f"CODEX_HOME={Path.home() / '.codex'}"
    assert normal in created[0] and str(foreign) not in created[0]
