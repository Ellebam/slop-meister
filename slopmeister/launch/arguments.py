"""Parse the launcher's command line and refuse arguments before anything is prepared."""

from __future__ import annotations

import re
import tomllib

from slopmeister.launch.model import Launch, Stop, die, plain

USAGE = (
    "usage: slopmeister plot-session [<repo-path>] <plot> <name> "
    "[--redispatch | --abandon --handoff <path>] [--directory] "
    "[--tool claude|codex|opencode] "
    "[--host <alias>] [--model <model>] "
    "[--issue <n> | --issue-id <n> | --note <path>] [-- <extra tool args>]"
)
SESSION_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
SOURCES = {
    "--add-dir", "--settings", "--setting-sources", "--system-prompt", "--system-prompt-file",
    "--append-system-prompt", "--append-system-prompt-file", "--plugin-dir", "--agents",
    "--agent", "--mcp-config", "--no-strict-mcp-config", "--cd", "--profile",
}  # fmt: skip
CLAUDE_OWNED = {
    "--worktree", "--resume", "--continue", "--bare", "--safe-mode", "--restricted",
    "--disable-slash-commands",
}  # fmt: skip
CLAUDE_APPROVAL_FLAGS = {"--permission-mode", "--dangerously-skip-permissions"}
PROTECTED = {
    "project_root_markers", "project_doc_fallback_filenames", "project_doc_max_bytes",
    "developer_instructions", "model_instructions_file", "experimental_instructions_file",
    "skills", "plugins", "agents", "mcp_servers", "profiles", "projects", "hooks", "auto_review",
}  # fmt: skip
ACTION_PROTECTED = {
    "approval_policy",
    "sandbox_mode",
    "sandbox_workspace_write",
}
ACTION_FLAGS = {
    "--ask-for-approval", "--sandbox", "--full-auto", "--yolo",
    "--dangerously-bypass-approvals-and-sandbox",
}  # fmt: skip
MODEL_KEY = re.compile(r"""^\s*(?:model|"model"|'model')\s*=""")
MCP_KEY = re.compile(r"""^\s*(?:mcp_servers|"mcp_servers"|'mcp_servers')\s*\.""")


def usage() -> Stop:
    return Stop(2, USAGE)


def _value(args: list[str]) -> str:
    if len(args) < 2:
        raise usage()
    return args[1]


def _model(launch: Launch, args: list[str]) -> None:
    if launch.model_set:
        raise die("--model may be supplied only once")
    if len(args) < 2:
        raise die("--model requires a value")
    launch.model, launch.model_set = args[1], True


def _issue(launch: Launch, flag: str, args: list[str]) -> None:
    if flag == "--issue" and not launch.issue and not launch.issue_id:
        launch.issue = launch.issue_id = _value(args)
        return
    if flag == "--issue-id" and not launch.issue_id:
        launch.issue_id = _value(args)
        return
    raise usage()


def _option(launch: Launch, args: list[str]) -> int:
    flag = args[0]
    if flag == "--directory":
        launch.directory_requested = True
        return 1
    if flag in ("--redispatch", "--abandon"):
        setattr(launch, flag[2:], True)
        return 1
    if flag == "--model":
        _model(launch, args)
    elif flag in ("--handoff", "--tool", "--note"):
        setattr(launch, flag[2:], _value(args))
    else:
        _issue(launch, flag, args)
    return 2


def parse(argv: list[str]) -> Launch:
    args = list(argv)
    positional = []
    while args and not args[0].startswith("--"):
        positional.append(args.pop(0))
    if len(positional) not in (2, 3):
        raise usage()
    repo_arg, plot, name = positional if len(positional) == 3 else ["", *positional]
    launch = Launch(plot, name, repo_arg)
    while args:
        if args[0] == "--":
            launch.extra = args[1:]
            break
        del args[: _option(launch, args)]
    return launch


def config_override(token: str, tail: list[str], index: int) -> str:
    if token in ("-c", "--config"):
        return tail[index + 1] if index + 1 < len(tail) else ""
    if token.startswith("--config="):
        return token[len("--config=") :]
    return token[2:].removeprefix("=") if token.startswith("-c") else ""


def check_model(launch: Launch) -> None:
    model = launch.model
    control = any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in model)
    if not model.strip() or model.startswith("-") or control:
        raise plain(
            "--model requires a nonempty value without option prefixes or control characters"
        )
    for index, token in enumerate(launch.extra):
        conflict = token == "--model" or token.startswith("--model=")
        if launch.tool == "codex":
            conflict |= token.startswith("-m")
            conflict |= bool(MODEL_KEY.match(config_override(token, launch.extra, index)))
        if conflict:
            raise plain("--model conflicts with a model selector in the tool arguments")


def _disable_only(config: str) -> bool:
    """A native connection may be disabled for an isolated test, never replaced or enabled."""
    if not MCP_KEY.match(config):
        return False
    try:
        parsed = tomllib.loads(config)
    except ValueError, TypeError:
        return False
    servers = parsed.get("mcp_servers", {})
    if set(parsed) != {"mcp_servers"} or len(servers) != 1:
        return False
    entry = next(iter(servers.values()))
    return isinstance(entry, dict) and set(entry) == {"enabled"} and entry["enabled"] is False


def _codex_refused(token: str, config: str, approval_required: bool) -> bool:
    refused = token.startswith(("-C", "-p")) or token == "--dangerously-bypass-hook-trust"
    if approval_required:
        refused |= token.startswith(("-a", "-s")) or token.split("=", 1)[0] in ACTION_FLAGS
    key = re.split(r"[.=]", config, maxsplit=1)[0].strip().strip("\"'")
    protected = PROTECTED | ACTION_PROTECTED if approval_required else PROTECTED
    return refused or key in protected and not _disable_only(config)


def check_tool_arguments(launch: Launch) -> None:
    if launch.tool == "opencode" and launch.extra:
        # OpenCode flags such as --auto, --session or --prompt replace owned session identity.
        raise plain(
            "tool argument would override Slopmeister-owned configuration: " + launch.extra[0]
        )
    for index, token in enumerate(launch.extra):
        refused = token.split("=", 1)[0] in SOURCES
        if launch.tool == "claude":
            refused |= token.split("=", 1)[0] in CLAUDE_OWNED
            refused |= token.startswith(("-w", "-r")) or token == "-c"
            if launch.approval_required:
                refused |= token.split("=", 1)[0] in CLAUDE_APPROVAL_FLAGS
        else:
            config = config_override(token, launch.extra, index)
            refused |= _codex_refused(token, config, launch.approval_required)
        if refused:
            raise plain("tool argument would override Slopmeister-owned configuration: " + token)


def _config_model(config: str) -> str | None:
    try:
        return tomllib.loads(config).get("model")
    except tomllib.TOMLDecodeError:
        key, separator, raw = config.partition("=")
        if not separator:
            raise plain("invalid issue-dispatch config override") from None
        return raw if key.strip() == "model" else None


def _selector(tool: str, args: list[str], index: int) -> str | None:
    arg = args[index]
    if arg in ("--model", "-m"):
        return args[index + 1] if index + 1 < len(args) else ""
    if arg.startswith("--model="):
        return arg.split("=", 1)[1]
    if tool == "codex" and arg.startswith("-m"):
        return arg[2:]
    config = arg in ("-c", "--config") or arg.startswith(("-c", "--config="))
    return _config_model(config_override(arg, args, index)) if tool == "codex" and config else None


def claim_model(launch: Launch) -> str:
    """Native tail selectors get the same observation as --model."""
    found = []
    for index in range(len(launch.extra)):
        value = _selector(launch.tool, launch.extra, index)
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise plain("invalid issue-dispatch model selector")
            found.append(value)
    if len(found) > 1:
        raise plain("conflicting issue-dispatch model selectors")
    return found[0] if found else ""


def check_basics(launch: Launch) -> None:
    if launch.directory_requested and launch.repo_arg:
        raise die("--directory cannot be combined with a repository path")
    if not SESSION_NAME.fullmatch(launch.name):
        raise die(
            f"session name '{launch.name}' must match [a-z0-9][a-z0-9-]*, it becomes the branch, "
            "the worktree or the directory, and the process identity"
        )
    if launch.tool not in ("claude", "codex", "opencode"):
        raise die(f"--tool must be claude, codex or opencode, got '{launch.tool}'")
    if launch.tool == "opencode" and (launch.redispatch or launch.abandon):
        raise die(
            "--redispatch and --abandon are not supported for OpenCode yet, see docs/opencode.md; "
            "close the worker's tab yourself and start a new session name"
        )


def check_sources(launch: Launch) -> None:
    if launch.issue and launch.note:
        raise die("--issue and --note are exclusive, a kickoff has one source")
    if launch.issue_id and not re.fullmatch(r"[1-9][0-9]*", launch.issue_id):
        raise die("issue identifier must be a positive integer")
    if launch.issue_id and launch.note:
        raise die("issue association and --note are exclusive")
    if launch.abandon and (launch.redispatch or not launch.handoff):
        raise die("--abandon requires --handoff and excludes --redispatch")
    if launch.handoff and not launch.abandon:
        raise die("--handoff requires --abandon")
