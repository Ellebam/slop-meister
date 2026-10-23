"""Start the delivered native write tools in the installed client before the tab opens.

A client update can change how it loads settings or starts tool servers. Starting them through
the client's own integration protocol, without a model call, finds that before a worker does.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import time
import tomllib

from slopmeister import paths
from slopmeister.launch import command, tool_arguments
from slopmeister.launch.model import Launch, die
from slopmeister.launch.native_client import Client, Refused

WAIT = 60
PAUSE = 1
CLIENT_NAME = {"name": "slopmeister-preflight", "version": "1"}
CLAUDE_STREAM = ["--input-format", "stream-json", "--output-format", "stream-json", "--verbose"]


def writers(launch: Launch) -> list[str]:
    codex = launch.wt / ".codex/config.toml"
    claude = launch.wt / ".claude/service-actions/mcp.json"
    if launch.tool == "codex" and codex.is_file():
        servers = tomllib.loads(codex.read_text()).get("mcp_servers", {})
        # Only write tools are required, optional plot servers start with the session.
        disabled = set()
        for index, token in enumerate(launch.extra):
            override = tool_arguments.config_override(token, launch.extra, index)
            if tool_arguments._disable_only(override):
                disabled.update(tomllib.loads(override)["mcp_servers"])
        return [
            name
            for name, server in servers.items()
            if server.get("required") and name not in disabled and server.get("enabled", True)
        ]
    if launch.tool == "claude" and claude.is_file():
        return list(json.loads(claude.read_text())["mcpServers"])
    return []


def _argv(launch: Launch) -> list[str]:
    """The worker's own approval, settings and tool-server arguments."""
    if launch.tool == "codex":
        settings = command.CODEX_APPROVAL + command.CODEX_SANDBOX[paths.platform()]
        settings += command._native_approvals(launch) + command.CODEX_ROOTS
        overrides = [
            value
            for index, token in enumerate(launch.extra)
            if (value := tool_arguments.config_override(token, launch.extra, index))
        ]
        extra = [word for override in overrides for word in ("-c", override)]
        return [str(launch.codex_bin), "app-server", *shlex.split(settings), *extra]
    return [
        launch.claude_bin,
        "-p",
        "--strict-mcp-config",
        "--mcp-config",
        str(launch.wt / ".claude/service-actions/mcp.json"),
        "--setting-sources",
        "user,project",
        "--settings",
        str(launch.wt / ".claude/access-settings.json"),
        "--permission-mode",
        "auto",
        *CLAUDE_STREAM,
        "--no-session-persistence",
    ]


def _codex(launch: Launch, client: Client) -> None:
    """Thread start fails when a required tool server does not start."""
    steps = [
        ("initialize", {"clientInfo": CLIENT_NAME}),
        ("account/read", {"refreshToken": False}),
        # The client process already runs in the workspace. An explicit cwd here would mark that
        # folder trusted in the operator's Codex store.
        ("thread/start", {"ephemeral": True}),
    ]
    for identity, (method, params) in enumerate(steps, 1):
        message = {"id": identity, "method": method, "params": params}
        reply = client.ask(message, lambda answer, wanted=identity: answer.get("id") == wanted)
        if "result" not in reply:
            raise Refused(f"{method} failed")
        if method == "initialize":
            client.send({"method": "initialized"})


def _control(client: Client, subtype: str) -> dict:
    identity = str(time.monotonic_ns())
    message = {"type": "control_request", "request_id": identity, "request": {"subtype": subtype}}
    reply = client.ask(
        message,
        lambda answer: (
            answer.get("type") == "control_response"
            and isinstance(answer.get("response"), dict)
            and answer["response"].get("request_id") == identity
        ),
    )["response"]
    if reply.get("subtype") != "success":
        raise Refused(f"{subtype} failed")
    result = reply.get("response") or {}
    if not isinstance(result, dict):
        raise Refused("invalid native control reply")
    return result


def _claude(names: list[str], client: Client) -> None:
    _control(client, "initialize")
    while True:
        listed = _control(client, "mcp_status").get("mcpServers", [])
        if not isinstance(listed, list) or not all(isinstance(row, dict) for row in listed):
            raise Refused("invalid native status reply")
        status = {server["name"]: server["status"] for server in listed}
        states = {name: status.get(name, "missing") for name in names}
        if any(
            value not in ("connected", "pending", "failed", "disabled", "missing")
            for value in states.values()
        ):
            raise Refused("unrecognized native status")
        if "pending" not in states.values():
            break
        time.sleep(PAUSE)
    if set(states.values()) != {"connected"}:
        raise Refused(", ".join(f"{name} {state}" for name, state in states.items()))


def _start(launch: Launch, names: list[str]) -> None:
    client = Client(_argv(launch), launch, WAIT)
    try:
        if launch.tool == "codex":
            _codex(launch, client)
        else:
            _claude(names, client)
    finally:
        client.close()


def _version(launch: Launch) -> str:
    binary = str(launch.codex_bin) if launch.tool == "codex" else launch.claude_bin
    try:
        found = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10)
    except OSError, subprocess.TimeoutExpired:
        return f"an unreadable {launch.tool} version"
    return found.stdout.strip().splitlines()[0] if found.stdout.strip() else launch.tool


def check(launch: Launch) -> None:
    """Fail closed, a worker without its write tools silently loses a capability it relies on."""
    names = writers(launch)
    if not names:
        return
    try:
        _start(launch, names)
    except (Refused, OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        recovery = (
            "Preflight cleanup is unverified; retain the workspace."
            if launch.native_pending
            else "Nothing opened."
        )
        raise die(
            f"native write tools {', '.join(names)} cannot start on {_version(launch)}: {error}. "
            f"{recovery} Report it, and once fixed retry the same name with --redispatch"
        ) from None
    print(f"plot-session: native write tools {', '.join(names)} started in a preflight")
