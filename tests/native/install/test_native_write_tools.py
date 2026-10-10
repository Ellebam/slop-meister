"""Native write action calls require exact intent independently of shell spelling."""

from dataclasses import replace
import json
from pathlib import Path
import shlex
import sys

import pytest

from slopmeister.session.service_actions.constants import PYTHON
from tests.native.install.intent_fixture import claude_host, close, main_results
from tests.native.install.native_tool_fixture import marker_consumer, prepared_native
from tests.support.standin import run

pytestmark = pytest.mark.xdist_group("native-standin")

SOCKET_PROGRAM = """
import os, socket, sys
left, right = socket.socketpair()
if os.fork() == 0:
    left.close()
    right.settimeout(10)
    right.sendall(open(sys.argv[1], 'rb').read())
    print('FORGED_SOCKET_RESPONSE', right.recv(65536))
    right.close()
    raise SystemExit(0)
right.close()
os.dup2(left.fileno(), 0)
os.dup2(left.fileno(), 1)
left.close()
os.execv(sys.argv[2], sys.argv[2:])
"""

PROC_PROGRAM = """
import os, pathlib, stat, sys, time
adapter, request, output = sys.argv[1:]
found = False
for process in pathlib.Path('/proc').iterdir():
    if not process.name.isdigit():
        continue
    try:
        argv = process.joinpath('cmdline').read_bytes().split(b'\\0')
        if argv[1:5] != [b'-E', b'-s', b'-S', os.fsencode(adapter)]:
            continue
        found = True
        channel = process.joinpath('fd/0').stat()
        if not stat.S_ISFIFO(channel.st_mode):
            print('PROC_CHANNEL_NOT_PIPE')
            continue
        parent = process.joinpath('stat').read_text().rsplit(')', 1)[1].split()[1]
        for descriptor in pathlib.Path('/proc', parent, 'fd').iterdir():
            try:
                info = descriptor.stat()
                flags = pathlib.Path('/proc', parent, 'fdinfo', descriptor.name).read_text()
                flags = int(flags.split('flags:', 1)[1].split()[0], 8)
                if info.st_ino != channel.st_ino or info.st_dev != channel.st_dev:
                    continue
                if flags & os.O_ACCMODE == os.O_RDONLY:
                    continue
                fd = os.open(descriptor, os.O_WRONLY | os.O_NONBLOCK)
                try:
                    os.write(fd, pathlib.Path(request).read_bytes())
                finally:
                    os.close(fd)
                print('PROC_INJECTION_SENT')
                for _ in range(20):
                    if pathlib.Path(output).read_bytes():
                        break
                    time.sleep(0.1)
                raise SystemExit(0)
            except OSError:
                print('PROC_CHANNEL_REFUSED')
    except OSError:
        print('PROC_CHANNEL_REFUSED')
if not found:
    print('PROC_CHANNEL_HIDDEN')
"""


@pytest.mark.parametrize("tool", ["claude", "codex"])
@pytest.mark.parametrize("action", ["jira-write", "confluence-write"])
@pytest.mark.parametrize("approved", [False, True])
def test_native_write_tool_runs_only_with_exact_operator_approval(tmp_path, tool, action, approved):
    """Bug: a named write tool runs without operator intent or cannot execute an approved write."""
    world = prepared_native(tmp_path, tool, action)
    try:
        marker_consumer(world)
        name = "mcp__" + action.replace("-", "_") + "__run"
        world.server.script = [(name, {"command": world.command})]
        if tool == "claude":
            requests = claude_host(world, approved)
            assert len(requests) == 1 and requests[0]["tool_name"] == name
        else:
            prompt = "I approve this exact command:\n" + world.command if approved else "Go."
            run(replace(world.client, argv=[*world.client.argv[:-1], prompt]))
            assert any(body.get("model") == "codex-auto-review" for body in world.server.requests)
            main_results(world)
        offered = {item.get("name") for item in world.server.requests[0].get("tools", [])}
        assert name in offered or name.rsplit("__", 1)[0] in offered, offered
        assert (world.output.read_text() == "STANDIN_WRITE\n") == approved
    finally:
        close(world)


@pytest.mark.parametrize("tool", ["claude", "codex"])
@pytest.mark.parametrize("route", ["redirect", "pipeline", "process_substitution", "socket"])
def test_shell_cannot_send_a_forged_native_write_request(tmp_path, tool, route):
    """Bug: the write adapter accepts direct shell RPC without the native client's approval."""
    world = prepared_native(tmp_path, tool, "jira-write")
    try:
        marker_consumer(world)
        command = _forged_command(world, route, tmp_path / "forged.jsonl")
        world.server.script = (
            [("Bash", {"command": command})]
            if tool == "claude"
            else [("exec_command", {"cmd": command, "login": False})]
        )
        argv = ["auto" if value == "bypassPermissions" else value for value in world.client.argv]
        if tool == "claude":
            argv[-2:-2] = ["--settings", str(world.client.cwd / ".claude/access-settings.json")]
        run(replace(world.client, argv=argv))
        assert "NATIVE_APPROVAL_REQUIRED" in main_results(world)
        assert world.output.read_text() == ""
    finally:
        close(world)


@pytest.mark.skipif(sys.platform != "linux", reason="The attack uses Linux /proc descriptors")
@pytest.mark.parametrize("tool", ["claude", "codex"])
def test_client_shell_cannot_reopen_its_native_write_channel(tmp_path, tool):
    """Bug: a shell injects an unapproved call through the native client's genuine pipe."""
    world = prepared_native(tmp_path, tool, "jira-write")
    try:
        marker_consumer(world)
        command = _forged_command(world, "proc", tmp_path / "forged.jsonl")
        world.server.script = (
            [("Bash", {"command": command})]
            if tool == "claude"
            else [("exec_command", {"cmd": command, "login": False})]
        )
        argv = ["auto" if value == "bypassPermissions" else value for value in world.client.argv]
        if tool == "claude":
            argv[-2:-2] = ["--settings", str(world.client.cwd / ".claude/access-settings.json")]
        run(replace(world.client, argv=argv))
        result = main_results(world)
        offered = {item.get("name") for item in world.server.requests[0].get("tools", [])}
        assert "mcp__jira_write__run" in offered or "mcp__jira_write" in offered, offered
        assert any(
            marker in result
            for marker in ("PROC_CHANNEL_HIDDEN", "PROC_CHANNEL_REFUSED", "PROC_CHANNEL_NOT_PIPE")
        ), result
        assert "PROC_INJECTION_SENT" not in result, result
        assert world.output.read_text() == ""
    finally:
        close(world)


def _forged_command(world, route, request):
    message = dict(
        jsonrpc="2.0",
        id=1,
        method="tools/call",
        params={"name": "run", "arguments": {"command": world.command}},
    )
    request.write_text(json.dumps(message) + "\n")
    adapter = world.command.split(" --output ")[0].replace("entry.py", "native_tool.py")
    if route == "proc":
        args = [str(world.entry.with_name("native_tool.py")), str(request), str(world.output)]
        return shlex.join([str(PYTHON), "-c", PROC_PROGRAM, *args])
    if route == "socket":
        return (
            f"exec {PYTHON} -c {shlex.quote(SOCKET_PROGRAM)} {shlex.quote(str(request))} {adapter}"
        )
    commands = {
        "redirect": adapter + " < " + shlex.quote(str(request)),
        "pipeline": "cat " + shlex.quote(str(request)) + " | " + adapter,
        "process_substitution": "exec " + adapter + " < <(cat " + shlex.quote(str(request)) + ")",
    }
    return commands[route]


@pytest.mark.parametrize(
    "override",
    [
        '--config=mcp_servers.jira_write.tools.run.approval_mode="approve"',
        '-cmcp_servers.jira_write.tools.run.approval_mode="approve"',
        "--yolo",
    ],
)
def test_native_write_tool_refuses_compact_approval_override(tmp_path, override):
    """Bug: equals and compact config flags bypass approval and reach the write consumer."""
    world = prepared_native(tmp_path, "codex", "jira-write")
    try:
        marker_consumer(world)
        world.server.script = [("mcp__jira_write__run", {"command": world.command})]
        argv = list(world.client.argv[:-1])
        if override == "--yolo":
            argv.remove("--approve-for-me")
        with pytest.raises(RuntimeError, match="command exited 1"):
            run(replace(world.client, argv=[*argv, override, "Go."]))
        assert (
            "required MCP servers failed to initialize"
            in world.client.evidence.with_suffix(".stderr").read_text()
        )
        assert world.output.read_text() == ""
        assert not any(body.get("model") == "codex-auto-review" for body in world.server.requests)
    finally:
        close(world)


@pytest.mark.parametrize("mismatch", ["foreign-cwd", "untrusted"])
def test_native_approval_pin_survives_home_and_project_config_mismatch(tmp_path, mismatch):
    """Bug: native admission checks a prompt file while the caller loaded automatic approval."""
    world = prepared_native(tmp_path, "codex", "jira-write")
    try:
        marker_consumer(world)
        config = Path(world.client.env["CODEX_HOME"]) / "config.toml"
        value = config.read_text().replace('approval_mode="prompt"', 'approval_mode="approve"')
        argv = list(world.client.argv)
        if mismatch == "untrusted":
            value = value.replace('trust_level="trusted"', 'trust_level="untrusted"')
        else:
            foreign = tmp_path / "foreign"
            foreign.mkdir()
            argv[argv.index("-C") + 1] = str(foreign)
        config.write_text(value)
        world.server.script = [("mcp__jira_write__run", {"command": world.command})]
        run(replace(world.client, argv=argv))
        assert world.output.read_text() == ""
        assert any(body.get("model") == "codex-auto-review" for body in world.server.requests)
    finally:
        close(world)
