"""Build the launch line and the command file the new tab runs."""

from __future__ import annotations

import os
import tomllib

from slopmeister import paths
from slopmeister.launch.model import BROKER_MARK, Launch, shq
from slopmeister.opencode import launch as opencode

CODEX_APPROVAL = " -c 'approval_policy=\"on-request\"' -c 'approvals_reviewer=\"auto_review\"'"
CODEX_ROOTS = " -c 'project_root_markers=[\"AGENTS.md\"]' -c 'project_doc_fallback_filenames=[]'"
# The session's op starts the real op, which reaches 1Password and Home Assistant over the
# network. The Mac's sandbox gets network access for it, Linux runs without the sandbox.
CODEX_SANDBOX = {
    "linux": " -c 'sandbox_mode=\"danger-full-access\"'",
    "darwin": " -c 'sandbox_workspace_write.network_access=true'",
}


def _tail(launch: Launch) -> str:
    model = f" --model {shq(launch.model)}" if launch.model_set else ""
    return model + "".join(" " + shq(arg) for arg in launch.extra)


def _native_approvals(launch: Launch) -> str:
    config = launch.wt / ".codex/config.toml"
    if not config.is_file():
        return ""
    servers = tomllib.loads(config.read_text()).get("mcp_servers", {})
    return "".join(
        " -c "
        + shq(
            f'mcp_servers.{name}.tools.run.approval_mode="{server["tools"]["run"]["approval_mode"]}"'
        )
        for name, server in servers.items()
    )


def line(launch: Launch) -> str:
    """Extra arguments land before a non-variadic separator so no option swallows the kickoff."""
    prompt = f'-- "$(cat {shq(str(launch.kickoff_file))})"'
    wt = shq(str(launch.wt))
    if launch.tool == "opencode":
        return opencode.line(launch)
    if launch.tool == "claude":
        config = launch.wt / ".claude/service-actions/mcp.json"
        mcp = f" --mcp-config {shq(str(config))}" if config.is_file() else ""
        env = "env -u CLAUDE_CONFIG_DIR"
        if launch.claude_root:
            env = f"env CLAUDE_CONFIG_DIR={shq(str(launch.claude_root))}"
        env += " " + BROKER_MARK
        return (
            f"cd {wt} && {env} {shq(launch.claude_bin)} "
            f"--remote-control={launch.name} -n {launch.name} --session-id {launch.session_id} "
            f"--strict-mcp-config{mcp} "
            f"--append-system-prompt-file {shq(str(launch.wt / 'CLAUDE.md'))} "
            "--setting-sources user,project "
            f"--settings {shq(str(launch.wt / '.claude/access-settings.json'))}"
            f"{_tail(launch)} --permission-mode auto {prompt}"
        )
    # Orca may carry its own CODEX_HOME, while the worker must use its saved store.
    env = f"env CODEX_HOME={shq(str(launch.codex_home))} {BROKER_MARK} "
    return (
        f"cd {wt} && {env}{shq(str(launch.codex_bin))} --no-daemon{CODEX_APPROVAL}"
        f"{CODEX_SANDBOX[paths.platform()]}{_tail(launch)}{_native_approvals(launch)}"
        f"{CODEX_ROOTS} -C {wt} {prompt}"
    )


def write(launch: Launch) -> None:
    """The first && of the launch line becomes the exec."""
    first, rest = launch.line.split(" && ", 1)
    lines = ["#!/bin/zsh -l", f"{first} && exec {rest}"]
    descriptor = os.open(launch.command_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write("\n".join(lines) + "\n")
    os.chmod(launch.command_file, 0o700)
