"""Build the launch line and the command file the new tab runs."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys
import tomllib

from slopmeister import paths
from slopmeister.errors import SlopmeisterError
from slopmeister.launch import arguments, terminal
from slopmeister.launch.model import BROKER_MARK, INBOX_NOTICE, NOTICE_VARIABLE, Launch, shq
from slopmeister.opencode import launch as opencode
from slopmeister.review.config import load_config
from slopmeister.session import prompt_record

RUN = r"run_[A-Za-z0-9_-]{1,128}"
RUN_FILE_LIMIT = 200
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
    if not re.fullmatch(RUN, run["id"]):
        raise SlopmeisterError("unsupported inbox identity")
    if run.get("coordinator_handle") != handle or run.get("legacy") != 0:
        raise SlopmeisterError("inbox does not belong to the inherited terminal")
    if run.get("objective") != objective:
        raise SlopmeisterError("existing inbox belongs to another task")
    return run["id"]


def saved_run(saved: Path) -> str | None:
    try:
        descriptor = os.open(saved, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor) as stream:
        identity = stream.read(RUN_FILE_LIMIT).strip()
    if not re.fullmatch(RUN, identity):
        raise SlopmeisterError("saved inbox identity is unreadable")
    return identity


def _save_run(saved: Path, identity: str) -> None:
    saved.unlink(missing_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    with os.fdopen(os.open(saved, flags, 0o600), "w") as stream:
        stream.write(identity + "\n")


def _run(handle: str, objective: str, previous: str | None) -> object:
    """The terminal's own Run, else the saved one of its predecessor, else a new one."""
    # Newer Orca prints the binding's owner only with --full, older Orca refuses the flag.
    full: tuple[str, ...] = ("--full",)
    lookup = ("orchestration", "run-current", "--from", handle)
    try:
        current = terminal._orca(*lookup, *full, checked=True)
    except SlopmeisterError as error:
        if str(error) != "invalid_argument":
            raise
        full = ()
        current = terminal._orca(*lookup, checked=True)
    if "run" not in current:
        raise SlopmeisterError("unsupported inbox lookup")
    if current["run"] is not None:
        return current["run"]
    if previous:
        change = ("run-use", "--id", previous, "--from", handle)
    else:
        change = ("run-create", "--from", handle, "--objective", objective)
    return terminal._orca("orchestration", *change, *full, checked=True).get("run")


def initialize_mailbox(workspace: Path, saved: Path | None = None, adopt: bool = False) -> str:
    """The native terminal owns setup, before a model can omit the inbox instruction. The
    returned notice reaches the model's first prompt, because the pane's output is hidden."""
    try:
        # Senders keep the address of the replaced session, so a redispatch takes over its Run.
        # A failed takeover creates no second Run, which would leave their mail unread.
        previous = saved_run(saved) if saved and adopt else None
        if saved and not adopt:
            saved.unlink(missing_ok=True)
        handle = _mailbox_handle()
        identity = _mailbox_id(_run(handle, workspace.name, previous), handle, workspace.name)
        if saved:
            _save_run(saved, identity)
        print(f"task inbox ready: {identity}", file=sys.stderr)
        return ""
    except (SlopmeisterError, OSError) as error:
        print(f"task inbox unavailable: {error}", file=sys.stderr)
        return INBOX_NOTICE


def mailbox_line(workspace: Path, saved: Path | None = None, adopt: bool = False) -> str:
    """Run setup inside the new pane, never under the launching agent's identity. The unexported
    variable carries the failure notice into the prompt and nowhere else."""
    module = (sys.executable, "-E", "-s", "-m", "slopmeister.launch.command", str(workspace))
    args = (*module, *([str(saved)] if saved else []), *(["adopt"] * adopt))
    run = f"cd {shq(str(paths.ROOT))} && " + " ".join(shq(value) for value in args)
    return f'{NOTICE_VARIABLE}="$({run})"'


def _saved_tail(launch: Launch) -> list[str]:
    """The tokens of the replaced worker's saved line before its kickoff separator."""
    # workspace.adopt refuses an unusable state path or a non-regular file before anything is
    # touched, and a nonblocking open keeps a FIFO from hanging the launch before that.
    try:
        descriptor = os.open(launch.command_file, os.O_RDONLY | os.O_NONBLOCK)
    except FileNotFoundError, NotADirectoryError:
        return []
    with os.fdopen(descriptor) as stream:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return []
        lines = stream.read().splitlines()
    tokens = shlex.split(lines[-1]) if lines else []
    if "--" not in tokens:
        raise ValueError(f"saved command has no kickoff separator: {launch.command_file}")
    return tokens[: len(tokens) - 1 - tokens[::-1].index("--")]


def _default(tool: str, setting: str, value: str) -> list[str]:
    if setting == "model":
        return ["--model", value]
    return ["--effort", value] if tool == "claude" else ["-c", f'model_reasoning_effort="{value}"']


def select(launch: Launch) -> None:
    """An omitted model or effort keeps a redispatched worker's saved choice, otherwise it takes
    the shared default that reviews also use. Runs before anything is prepared or closed."""
    if launch.tool == "opencode":
        return
    missing = [
        setting
        for setting in ("model", "effort")
        if not (setting == "model" and launch.model_set)
        and not arguments.selector(launch.tool, launch.extra, setting)
    ]
    config = load_config()
    saved = _saved_tail(launch) if launch.redispatch and missing else []
    chosen: list[str] = []
    for setting in missing:
        value = getattr(config, f"{launch.tool}_{setting}")
        chosen += arguments.selector(launch.tool, saved, setting) or _default(
            launch.tool, setting, value
        )
    launch.extra[:0] = chosen


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


def _prompt_route(launch: Launch) -> str:
    """A managed worker's permission hook waits for its manager only where a prompt would wait for
    a person, because Codex runs the hook before its automatic reviewer."""
    if not launch.manager_run:
        return ""
    if launch.tool == "codex":
        reviewers = [
            value.partition("=")[2].strip(" '\"")
            for index, token in enumerate(launch.extra)
            if (value := arguments.config_override(token, launch.extra, index))
            and value.partition("=")[0].strip(" '\"") == "approvals_reviewer"
        ]
        if reviewers[-1:] != ["user"]:
            return ""
    return f" {prompt_record.ROUTE_VARIABLE}={shq(launch.manager_run)}"


def line(launch: Launch) -> str:
    """Extra arguments land before a non-variadic separator so no option swallows the kickoff."""
    prompt = f'-- "$(cat {shq(str(launch.kickoff_file))})${{{NOTICE_VARIABLE}}}"'
    wt = shq(str(launch.wt))
    marker = BROKER_MARK + _prompt_route(launch)
    if launch.tool == "opencode":
        return opencode.line(launch)
    if launch.tool == "claude":
        config = launch.wt / ".claude/service-actions/mcp.json"
        mcp = f" --mcp-config {shq(str(config))}" if config.is_file() else ""
        env = "env -u CLAUDE_CONFIG_DIR"
        if launch.claude_root:
            env = f"env CLAUDE_CONFIG_DIR={shq(str(launch.claude_root))}"
        env += " " + marker
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
    env = f"env CODEX_HOME={shq(str(launch.codex_home))} {marker} "
    return (
        f"cd {wt} && {env}{shq(str(launch.codex_bin))} --no-daemon{CODEX_APPROVAL}"
        f"{CODEX_SANDBOX[paths.platform()]}{_native_approvals(launch)}{_tail(launch)}"
        f"{CODEX_ROOTS} -C {wt} {prompt}"
    )


def write(launch: Launch) -> None:
    """The first && of the launch line becomes the exec."""
    first, rest = launch.line.split(" && ", 1)
    if not launch.redispatch:
        # The pane may never start, and a later redispatch must not find an earlier session's Run.
        launch.run_file.unlink(missing_ok=True)
    lines = [
        "#!/bin/zsh -l",
        mailbox_line(launch.wt, launch.run_file, launch.redispatch),
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
    print(initialize_mailbox(*map(Path, sys.argv[1:3]), adopt=sys.argv[3:] == ["adopt"]), end="")
