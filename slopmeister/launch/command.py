"""Build the launch line and the command file the new tab runs."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import tomllib

from slopmeister import paths
from slopmeister.errors import SlopmeisterError
from slopmeister.launch import terminal
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


def _mailbox_handle() -> str:
    handle = os.environ.get("ORCA_TERMINAL_HANDLE", "")
    if not re.fullmatch(r"term_[A-Za-z0-9_-]{1,128}", handle):
        raise SlopmeisterError("no inherited Orca terminal identity")
    listed = terminal._orca("terminal", "list", checked=True)
    rows = listed.get("terminals")
    if listed.get("truncated") is not False or not isinstance(rows, list):
        raise SlopmeisterError("incomplete terminal discovery")
    matches = [row for row in rows if isinstance(row, dict) and row.get("handle") == handle]
    if len(matches) != 1:
        raise SlopmeisterError("inherited terminal is not uniquely live")
    return handle


def _mailbox_id(run: object, handle: str, objective: str) -> str:
    if not isinstance(run, dict) or not isinstance(run.get("id"), str):
        raise SlopmeisterError("unsupported inbox binding")
    if not re.fullmatch(r"run_[A-Za-z0-9_-]{1,128}", run["id"]):
        raise SlopmeisterError("unsupported inbox identity")
    if run.get("coordinator_handle") != handle or run.get("legacy") != 0:
        raise SlopmeisterError("inbox does not belong to the inherited terminal")
    if run.get("objective") != objective:
        raise SlopmeisterError("existing inbox belongs to another task")
    return run["id"]


def initialize_mailbox(workspace: Path) -> None:
    """The native terminal owns setup, before a model can omit the inbox instruction."""
    try:
        handle = _mailbox_handle()
        current = terminal._orca("orchestration", "run-current", "--from", handle, checked=True)
        if "run" not in current:
            raise SlopmeisterError("unsupported inbox lookup")
        run = current["run"]
        if run is None:
            created = terminal._orca(
                "orchestration",
                "run-create",
                "--from",
                handle,
                "--objective",
                workspace.name,
                checked=True,
            )
            run = created.get("run")
        identity = _mailbox_id(run, handle, workspace.name)
        print(f"task inbox ready: {identity}", flush=True)
    except SlopmeisterError as error:
        print(f"task inbox unavailable: {error}", file=sys.stderr)


def mailbox_line(workspace: Path) -> str:
    """Run setup inside the new pane, never under the launching agent's identity."""
    args = (sys.executable, "-E", "-s", "-m", "slopmeister.launch.command", str(workspace))
    return f"(cd {shq(str(paths.ROOT))} && " + " ".join(shq(value) for value in args) + ")"


def _tail(launch: Launch) -> str:
    model = f" --model {shq(launch.model)}" if launch.model_set else ""
    return model + "".join(" " + shq(arg) for arg in launch.extra)


def _inline(value: object) -> str:
    if isinstance(value, dict):
        return (
            "{"
            + ", ".join(
                f"{json.dumps(key, ensure_ascii=False)}={_inline(item)}"
                for key, item in value.items()
            )
            + "}"
        )
    return json.dumps(value, ensure_ascii=False)


def native_pins(config: Path, whole: bool = True) -> list[str]:
    if not config.is_file():
        return []
    servers = tomllib.loads(config.read_text()).get("mcp_servers", {})
    if whole:
        return [f"mcp_servers.{name}={_inline(server)}" for name, server in servers.items()]
    return [
        f"mcp_servers.{name}.tools.run.approval_mode={json.dumps(server['tools']['run']['approval_mode'])}"
        for name, server in servers.items()
        if "run" in server.get("tools", {})
    ]


def _native_approvals(launch: Launch) -> str:
    return "".join(
        " -c " + shq(pin)
        for pin in native_pins(launch.wt / ".codex/config.toml", launch.native_server_pins)
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
        f"{CODEX_SANDBOX[paths.platform()]}{_native_approvals(launch)}{_tail(launch)}"
        f"{CODEX_ROOTS} -C {wt} {prompt}"
    )


def write(launch: Launch) -> None:
    """The first && of the launch line becomes the exec."""
    first, rest = launch.line.split(" && ", 1)
    lines = [
        "#!/bin/zsh -l",
        mailbox_line(launch.wt),
        f"export SLOPMEISTER_SESSION_WORKSPACE={shq(str(launch.wt))}",
    ]
    if launch.scratch is not None:
        lines.append(f"export TMPDIR={shq(str(launch.scratch))}")
    lines.append(f"{first} && exec {rest}")
    descriptor = os.open(launch.command_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write("\n".join(lines) + "\n")
    os.chmod(launch.command_file, 0o700)


if __name__ == "__main__":
    initialize_mailbox(Path(sys.argv[1]))
