"""Keep native client tail arguments inside the launcher's configuration boundary."""

import re
import tomllib

from slopmeister.launch.model import Launch, plain

SOURCES = {
    "--add-dir", "--settings", "--setting-sources", "--system-prompt", "--system-prompt-file",
    "--append-system-prompt", "--append-system-prompt-file", "--plugin-dir", "--agents",
    "--agent", "--mcp-config", "--no-strict-mcp-config", "--cd", "--profile",
}  # fmt: skip
CLAUDE_OWNED = {
    "--worktree", "--resume", "--continue", "--bare", "--safe-mode", "--restricted",
    "--disable-slash-commands", "--session-id", "--name", "--remote-control", "--fork-session",
    "--allowedTools", "--allowed-tools", "--disallowedTools", "--disallowed-tools", "--tools",
    "--teleport", "--from-pr", "--cloud", "--environment", "--bg", "--background", "--desktop",
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
MCP_KEY = re.compile(r"""^\s*(?:mcp_servers|"mcp_servers"|'mcp_servers')\s*\.""")


def config_override(token: str, tail: list[str], index: int) -> str:
    if token in ("-c", "--config"):
        return tail[index + 1] if index + 1 < len(tail) else ""
    if token.startswith("--config="):
        return token[len("--config=") :]
    return token[2:].removeprefix("=") if token.startswith("-c") else ""


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
    refused = (
        token in ("resume", "fork")
        or token.split("=", 1)[0] in ("--worktree", "--remote")
        or token.startswith(("-C", "-p"))
        or token == "--dangerously-bypass-hook-trust"
    )
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
            refused |= token.startswith(("-w", "-r", "-n")) or token == "-c"
            if launch.approval_required:
                refused |= token.split("=", 1)[0] in CLAUDE_APPROVAL_FLAGS
        else:
            config = config_override(token, launch.extra, index)
            refused |= _codex_refused(token, config, launch.approval_required)
        if refused:
            raise plain("tool argument would override Slopmeister-owned configuration: " + token)
