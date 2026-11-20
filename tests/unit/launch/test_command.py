"""The launch line and the command file are the bytes the dispatcher and the tab rely on."""

import contextlib
import os
from pathlib import Path
import pty
import select
import shlex
import shutil
import subprocess
import time
import tomllib

import pytest

from slopmeister.errors import SlopmeisterError
from slopmeister.launch import cli, command
from slopmeister.launch.model import INBOX_NOTICE, Launch

WT = "/r/.worktrees/example-client-wt1"


def _launch(tmp_path: Path, tool: str, monkeypatch) -> Launch:
    monkeypatch.setenv("PLOT_SESSION_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", "/h")
    monkeypatch.delenv("CODEX_HOME", raising=False)
    launch = Launch(
        "example-client", "example-client-wt1", "/r", tool=tool, claude_bin="/bin/claude"
    )
    launch.wt, launch.session_id = Path(WT), "sid"
    launch.model, launch.model_set, launch.extra = "o'k", True, ["--allowedTools", "Bash(git *)"]
    return launch


def test_claude_launch_line_golden(tmp_path, monkeypatch):
    """Bug: a variadic option swallows the kickoff, the config store override is lost, an
    ordinary launch starts in default mode and prompts a phone operator who cannot switch modes,
    or the session is not marked and its op run opens the desktop prompt."""
    launch = _launch(tmp_path, "claude", monkeypatch)
    kickoff = f"'{tmp_path}/example-client-wt1.md'"
    assert command.line(launch) == (
        f"cd '{WT}' && env -u CLAUDE_CONFIG_DIR SLOPMEISTER_SECRET_BROKER=1 '/bin/claude' "
        "--remote-control=example-client-wt1 -n example-client-wt1 "
        f"--session-id sid --strict-mcp-config --append-system-prompt-file '{WT}/CLAUDE.md' "
        f"--setting-sources user,project --settings '{WT}/.claude/access-settings.json' "
        "--model 'o'\\''k' '--allowedTools' 'Bash(git *)' --permission-mode auto "
        f'-- "$(cat {kickoff})${{inbox_notice}}"'
    )


@pytest.mark.parametrize(
    "platform,sandbox",
    [
        ("linux", "-c 'sandbox_mode=\"danger-full-access\"' "),
        ("darwin", "-c 'sandbox_workspace_write.network_access=true' "),
    ],
)
def test_codex_launch_line_golden(tmp_path, monkeypatch, platform, sandbox):
    """Bug: a worker inherits Orca's home, service actions force manual review, or the session's
    op cannot reach 1Password and Home Assistant from inside the sandbox."""
    launch = _launch(tmp_path, "codex", monkeypatch)
    monkeypatch.setattr(command.paths, "platform", lambda: platform)
    launch.service_actions = launch.approval_required = True
    launch.grants = ["--grant", "/v"]
    assert command.line(launch) == (
        f"cd '{WT}' && env CODEX_HOME='/h/.codex' SLOPMEISTER_SECRET_BROKER=1 "
        "'/h/.local/bin/codex' --no-daemon "
        "-c 'approval_policy=\"on-request\"' -c 'approvals_reviewer=\"auto_review\"' "
        f"{sandbox}"
        "--model 'o'\\''k' '--allowedTools' "
        "'Bash(git *)' -c 'project_root_markers=[\"AGENTS.md\"]' "
        f"-c 'project_doc_fallback_filenames=[]' -C '{WT}' "
        f"-- \"$(cat '{tmp_path}/example-client-wt1.md')${{inbox_notice}}\""
    )


@pytest.mark.parametrize("selected", [False, True])
def test_claude_service_action_retains_auto_mode(tmp_path, monkeypatch, selected):
    launch = _launch(tmp_path, "claude", monkeypatch)
    launch.service_actions = True
    launch.wt = tmp_path / "workspace"
    if selected:
        config = launch.wt / ".claude/service-actions/mcp.json"
        config.parent.mkdir(parents=True)
        config.write_text('{"mcpServers":{}}')
    line = command.line(launch)
    assert "--permission-mode auto" in line
    assert ("--mcp-config" in line) == selected


def test_codex_git_prompt_uses_auto_review(tmp_path, monkeypatch):
    """Bug: an ordinary worker inherits a machine's manual reviewer and stalls on the Mac."""
    launch = _launch(tmp_path, "codex", monkeypatch)
    launch.git_prompts = launch.approval_required = True
    line = command.line(launch)
    assert 'approval_policy="on-request"' in line
    assert 'approvals_reviewer="auto_review"' in line


def test_codex_explicit_manual_reviewer_wins(tmp_path, monkeypatch):
    """Bug: the default pin overrides a requested manual approval control."""
    launch = _launch(tmp_path, "codex", monkeypatch)
    launch.extra = ["-c", 'approvals_reviewer="user"']
    line = command.line(launch)
    assert line.index('approvals_reviewer="auto_review"') < line.index('approvals_reviewer="user"')


@pytest.mark.parametrize("redispatch", [False, True])
def test_failed_preparation_leaves_no_earlier_inbox(tmp_path, monkeypatch, redispatch):
    """Bug: a fresh launch of a reused name fails before its command file, and the redispatch
    that follows reads the mail of the earlier session."""
    launch = _launch(tmp_path, "claude", monkeypatch)
    launch.redispatch = redispatch
    launch.run_file.write_text("run_old\n")

    def fail(_: Launch) -> None:
        raise OSError("issue claim failed")

    monkeypatch.setattr(cli, "_prepare", fail)
    with pytest.raises(OSError, match="issue claim failed"):
        cli._launch(launch)
    assert launch.run_file.exists() is redispatch


@pytest.mark.parametrize("tool", ["claude", "codex"])
@pytest.mark.parametrize("redispatch", [False, True])
def test_command_file_execs_the_tool(tmp_path, monkeypatch, tool, redispatch):
    """Bug: the exec is lost and the terminal runs a login shell only, or a first launch whose
    pane never starts leaves the inbox of an earlier session of the same name for a redispatch."""
    launch = _launch(tmp_path, tool, monkeypatch)
    launch.line, launch.redispatch = f"cd '{WT}' && tool --flag && more", redispatch
    launch.run_file.write_text("run_old\n")
    command.write(launch)
    assert launch.run_file.exists() is redispatch
    mailbox, export, tool_line = launch.command_file.read_text().splitlines()[1:]
    saved = f"'{WT}' '{tmp_path}/example-client-wt1.run'"
    assert mailbox.endswith(saved + (" 'adopt'" if redispatch else "") + ')"')
    assert export == f"export SLOPMEISTER_SESSION_WORKSPACE='{WT}'"
    assert tool_line == f"cd '{WT}' && exec tool --flag && more"
    assert launch.command_file.stat().st_mode & 0o777 == 0o700


CLAUDE_EFFORT = " '--effort' 'high'"
CODEX_EFFORT = " '-c' 'model_reasoning_effort=\"high\"'"


@pytest.mark.parametrize(
    "tool,selection",
    [
        ("claude", (True, [], " --model 'o'\\''k'" + CLAUDE_EFFORT)),
        ("codex", (True, [], " --model 'o'\\''k'" + CODEX_EFFORT)),
        ("claude", (False, [], " '--model' 'claude-opus-5-5'" + CLAUDE_EFFORT)),
        ("codex", (False, [], " '--model' 'gpt-6.2-sol'" + CODEX_EFFORT)),
        ("claude", (False, ["--model", "requested"], CLAUDE_EFFORT + " '--model' 'requested'")),
        ("codex", (False, ["-mrequested"], CODEX_EFFORT + " '-mrequested'")),
        ("claude", (True, ["--effort=low"], " --model 'o'\\''k' '--effort=low'")),
        (
            "codex",
            (
                True,
                ["-cmodel_reasoning_effort=low"],
                " --model 'o'\\''k' '-cmodel_reasoning_effort=low'",
            ),
        ),
    ],
)
def test_native_argv(tmp_path, monkeypatch, tool, selection):
    """Bug: an omitted model or effort falls to the client's own default, or a default replaces
    or duplicates an explicit or native selector."""
    launch = _launch(tmp_path, tool, monkeypatch)
    launch.model_set, launch.extra, tail = selection
    command.select(launch)
    line = command.line(launch)
    anchor = "--settings '/r/.worktrees/example-client-wt1/.claude/access-settings.json'"
    if tool == "codex":
        anchor = (
            "--no-daemon -c 'approval_policy=\"on-request\"' "
            "-c 'approvals_reviewer=\"auto_review\"'"
            + command.CODEX_SANDBOX[command.paths.platform()]
        )
    assert anchor + tail + (" --permission-mode" if tool == "claude" else " -c ") in line


def test_codex_writer_pins_effective_native_approval(tmp_path, monkeypatch):
    """Bug: untrusted project config leaves a home MCP auto-approval setting effective."""
    launch = _launch(tmp_path, "codex", monkeypatch)
    launch.wt = tmp_path / "workspace"
    config = launch.wt / ".codex/config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        '[mcp_servers.jira_write]\ncommand="/writer"\nargs=["--scope", "🐙"]\n'
        'required=true\n[mcp_servers.jira_write.tools.run]\napproval_mode="prompt"\n'
    )
    pins = [word for word in shlex.split(command.line(launch)) if word.startswith("mcp_servers.")]
    assert len(pins) == 1
    assert tomllib.loads(pins[0])["mcp_servers"] == tomllib.loads(config.read_text())["mcp_servers"]


def _typed(line: str, cwd: Path) -> str:
    """Orca types the line into a starting shell, as oh-my-zsh's update question reads one key."""
    zsh = shutil.which("zsh")
    assert zsh
    leader, follower = pty.openpty()
    shell = subprocess.Popen(
        [zsh, "-f", "-c", f"print -n 'update? '; read -r -k 1 option; exec {zsh} -f"],
        stdin=follower,
        stdout=follower,
        stderr=follower,
        cwd=cwd,
        start_new_session=True,
    )
    os.close(follower)
    screen, typed, deadline = b"", False, time.monotonic() + 10
    # The terminal is drained throughout, a full buffer would block the shell.
    while shell.poll() is None and time.monotonic() < deadline:
        if select.select([leader], [], [], 0.1)[0]:
            with contextlib.suppress(OSError):
                screen += os.read(leader, 4096)
        # Orca types only after its shell-ready wait, while the question is already reading.
        if not typed and b"update? " in screen:
            os.write(leader, f"{line.replace('/bin/zsh', zsh, 1)}\nexit\n".encode())
            typed = True
    shell.kill()
    os.close(leader)
    return screen.decode(errors="replace")


def test_typed_line_survives_a_startup_question_taking_one_key(monkeypatch, tmp_path):
    """Bug: the update question took the leading slash, `bin/zsh` failed and a dead tab stayed."""
    launch = _launch(tmp_path, "claude", monkeypatch)
    marker = tmp_path / "ran"
    launch.command_file.write_text(f"touch '{marker}'\n")
    zsh = shutil.which("zsh")
    assert zsh
    missing = f"no such file or directory: {zsh[1:]}"
    assert missing in _typed(launch.terminal_line.lstrip(), tmp_path)
    assert not marker.exists()
    _typed(launch.terminal_line, tmp_path)
    assert marker.exists()


def test_complete_pins_precede_the_users_optional_server_disable(tmp_path, monkeypatch):
    launch = _launch(tmp_path, "codex", monkeypatch)
    launch.wt = tmp_path / "workspace"
    config = launch.wt / ".codex/config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('[mcp_servers.optional]\ncommand="/reader"\nenabled=true\n')
    launch.extra = ["-c", "mcp_servers.optional.enabled=false"]
    words = shlex.split(command.line(launch))
    pin = next(word for word in words if word.startswith("mcp_servers.optional="))
    assert words.index(pin) < words.index("mcp_servers.optional.enabled=false")


def _takeover(monkeypatch, adopted: object) -> list[tuple[str, ...]]:
    """An unbound new terminal, and Orca's answer when it resumes the saved Run."""
    calls: list[tuple[str, ...]] = []

    def fake(*args: str, checked: bool = False) -> dict:
        calls.append(args)
        if args[:2] == ("terminal", "list"):
            return {"truncated": False, "terminals": [{"handle": "term_fixture"}]}
        if args[1] == "run-current":
            return {"run": None}
        if args[1] == "run-use" and isinstance(adopted, SlopmeisterError):
            raise adopted
        owner = {"coordinator_handle": "term_fixture", "legacy": 0, "objective": "wt"}
        return {"run": {"id": "run_new", **owner} if args[1] == "run-create" else adopted}

    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", "term_fixture")
    monkeypatch.setattr(command.terminal, "_orca", fake)
    return calls


def test_redispatch_takes_over_the_saved_inbox(tmp_path, monkeypatch, capsys):
    """Bug: the replacement session creates a new Run, and mail that the dispatcher or a manager
    sends to the address of the replaced session is never read."""
    saved = tmp_path / "wt.run"
    saved.write_text("run_old\n")
    owner = {"coordinator_handle": "term_fixture", "legacy": 0, "objective": "wt"}
    calls = _takeover(monkeypatch, {"id": "run_old", **owner})
    assert command.initialize_mailbox(Path("/r/wt"), saved, adopt=True) == ""
    assert "task inbox ready: run_old" in capsys.readouterr().err
    use = ("orchestration", "run-use", "--id", "run_old", "--from", "term_fixture", "--full")
    assert calls[2:] == [use]
    assert saved.read_text() == "run_old\n"


@pytest.mark.parametrize(
    "case",
    [
        ("run_old\n", SlopmeisterError("timeout"), "timeout"),
        (
            "run_old\n",
            {"id": "run_old", "coordinator_handle": "term_fixture", "legacy": 0, "objective": "x"},
            "existing inbox belongs to another task",
        ),
        ("run_old --id run_other\n", None, "saved inbox identity is unreadable"),
    ],
)
def test_failed_takeover_creates_no_second_inbox(tmp_path, monkeypatch, capsys, case):
    """Bug: a fresh Run replaces a takeover that failed or whose outcome is unknown. Senders
    keep the old address, so the session must learn of the failure in its first prompt."""
    content, adopted, reason = case
    saved = tmp_path / "wt.run"
    saved.write_text(content)
    calls = _takeover(monkeypatch, adopted)
    assert command.initialize_mailbox(Path("/r/wt"), saved, adopt=True) == INBOX_NOTICE
    assert f"task inbox unavailable: {reason}" in capsys.readouterr().err
    assert not [call for call in calls if call[1] == "run-create"]
    assert saved.read_text() == content


@pytest.mark.parametrize("adopt", [False, True])
def test_launch_without_a_predecessor_inbox_creates_and_saves_one(tmp_path, monkeypatch, adopt):
    """Bug: a first launch takes over the inbox of an earlier session of the same name and reads
    its mail, or a redispatch of a session that predates the saved file starts without an inbox."""
    saved = tmp_path / "wt.run"
    if not adopt:
        saved.write_text("run_old\n")
    calls = _takeover(monkeypatch, None)
    assert command.initialize_mailbox(Path("/r/wt"), saved, adopt=adopt) == ""
    assert [call[1] for call in calls[2:]] == ["run-create"]
    assert saved.read_text() == "run_new\n"
    assert saved.stat().st_mode & 0o777 == 0o600


def test_fresh_launch_without_an_inbox_leaves_no_earlier_inbox_to_take_over(tmp_path, monkeypatch):
    """Bug: a first launch that gets no inbox keeps the file of an earlier session of the same
    name, and its later redispatch takes over that session's Run and reads its mail."""
    saved = tmp_path / "wt.run"
    saved.write_text("run_old\n")
    monkeypatch.delenv("ORCA_TERMINAL_HANDLE", raising=False)
    assert command.initialize_mailbox(Path("/r/wt"), saved) == INBOX_NOTICE
    assert not saved.exists()


def test_saved_inbox_is_never_read_or_written_through_a_link(tmp_path, monkeypatch):
    """Bug: a link in the state directory makes the launcher adopt a Run named by another file,
    or overwrite the file the link points to."""
    target, saved = tmp_path / "other", tmp_path / "wt.run"
    target.write_text("run_other\n")
    saved.symlink_to(target)
    calls = _takeover(monkeypatch, None)
    assert command.initialize_mailbox(Path("/r/wt"), saved, adopt=True) == INBOX_NOTICE
    assert calls == []
    assert command.initialize_mailbox(Path("/r/wt"), saved) == ""
    assert target.read_text() == "run_other\n"
    assert not saved.is_symlink()
