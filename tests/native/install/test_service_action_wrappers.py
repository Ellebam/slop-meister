"""Shell wrappers cannot replace the native write tool route."""

from dataclasses import replace
import json
import shlex

import pytest

from tests.native.install.intent_fixture import close, main_results, marker_entry, prepared_action
from tests.native.install.native_tool_fixture import marker_consumer, prepared_native
from tests.support.standin import run

pytestmark = pytest.mark.xdist_group("native-standin")


def wrapped(command, variant):
    if variant in ("shell", "bash_ec", "sh_ec", "split_flags"):
        shell = {
            "shell": "/bin/sh -c",
            "bash_ec": "bash -ec",
            "sh_ec": "/bin/sh -ec",
            "split_flags": "bash -e -c",
        }[variant]
        return shell + " " + shlex.quote(command)
    prefixes = {
        "direct": "",
        "env": "env PROBE=1 ",
        "absolute_env": "/usr/bin/env PROBE=1 ",
        "assignment": "PROBE=1 ",
        "nohup": "nohup ",
        "nice": "nice ",
        "command": "command ",
        "exec": "exec ",
    }
    return prefixes[variant] + command


@pytest.mark.parametrize("tool", ["claude", "codex"])
@pytest.mark.parametrize(
    "variant",
    [
        "direct",
        "env",
        "absolute_env",
        "assignment",
        "shell",
        "bash_ec",
        "sh_ec",
        "split_flags",
        "nohup",
        "nice",
        "command",
        "exec",
    ],
)
def test_direct_and_wrapped_shell_writes_cannot_replace_native_approval(tmp_path, tool, variant):
    """Bug: a terminal wrapper reaches write credentials without native approval."""
    world = prepared_native(tmp_path, tool, "jira-write")
    try:
        marker_consumer(world)
        command = wrapped(world.command, variant)
        world.server.script = (
            [("Bash", {"command": command})]
            if tool == "claude"
            else [("exec_command", {"cmd": command, "login": False})]
        )
        argv = ["auto" if value == "bypassPermissions" else value for value in world.client.argv]
        run(replace(world.client, argv=argv))
        main_results(world)
        assert json.loads(world.output.read_text())["result"] == "NATIVE_APPROVAL_REQUIRED"
    finally:
        close(world)


@pytest.mark.parametrize("variant", ["env", "assignment", "shell"])
def test_wrapped_read_in_write_plot_needs_no_exact_write_approval(tmp_path, variant):
    """Bug: adding native write tools imposes exact write intent on an ordinary selected read."""
    world = prepared_action(tmp_path, "codex", ["jira-read", "jira-write"])
    try:
        marker_entry(world)
        command = wrapped(world.command.split(" --comment ")[0] + " --issue TEST-7", variant)
        world.server.script = [("exec_command", {"cmd": command, "login": False})]
        argv = [*world.client.argv[:2], "--approve-for-me", *world.client.argv[2:]]
        run(replace(world.client, argv=argv))
        main_results(world)
        assert world.output.read_text() == "STANDIN_WRITE"
    finally:
        close(world)
