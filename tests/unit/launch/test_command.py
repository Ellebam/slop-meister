"""The launch line and the command file are the bytes the dispatcher and the tab rely on."""

from pathlib import Path

import pytest

from slopmeister.launch import command
from slopmeister.launch.model import Launch

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
        f'-- "$(cat {kickoff})"'
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
        f"-- \"$(cat '{tmp_path}/example-client-wt1.md')\""
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


@pytest.mark.parametrize("tool", ["claude", "codex"])
def test_command_file_execs_the_tool(tmp_path, monkeypatch, tool):
    """Bug: the exec is lost and the terminal runs a login shell only."""
    launch = _launch(tmp_path, tool, monkeypatch)
    launch.line = f"cd '{WT}' && tool --flag && more"
    command.write(launch)
    assert launch.command_file.read_text() == (
        f"#!/bin/zsh -l\ncd '{WT}' && exec tool --flag && more\n"
    )
    assert launch.command_file.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("tool", ["claude", "codex"])
@pytest.mark.parametrize(
    "selection",
    [
        (True, [], " --model 'o'\\''k'"),
        (False, [], ""),
        (False, ["--model", "requested"], " '--model' 'requested'"),
    ],
)
def test_native_argv(tmp_path, monkeypatch, tool, selection):
    """Bug: an explicit, omitted or native model selector changes the launch line shape."""
    launch = _launch(tmp_path, tool, monkeypatch)
    launch.model_set, launch.extra, tail = selection
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
    config.write_text('[mcp_servers.jira_write.tools.run]\napproval_mode="prompt"\n')
    assert "-c 'mcp_servers.jira_write.tools.run.approval_mode=\"prompt\"'" in command.line(launch)
