"""The launch preflight starts the delivered write tools the way the worker's client will."""

import json
from pathlib import Path
import sys

import pytest

from slopmeister.check import ownership
from slopmeister.launch import command, native_check, native_client
from slopmeister.launch.model import Launch, Stop

pytestmark = pytest.mark.xdist_group("native-preflight")

STANDIN = """#!{python}
import json, os, sys, subprocess, time
if sys.argv[1:] == ["--version"]:
    print("standin 9.9")
    raise SystemExit
seen = {{"argv": sys.argv[1:], "orca": [k for k in os.environ if k.startswith("ORCA_")]}}
open(os.environ["STANDIN_SEEN"], "w").write(json.dumps(seen))
fail = os.environ.get("STANDIN_FAIL", "")
if fail == "malformed":
    print("PRIVATE_REPLY_NOT_JSON", flush=True)
if fail == "shape":
    print("[]", flush=True)
if fail == "timeout":
    time.sleep(60)
if fail == "oversize":
    sys.stdout.write("x" * 2048); sys.stdout.flush(); time.sleep(60)
if os.environ.get("STANDIN_CHILD"):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    open(os.environ["STANDIN_SEEN"] + ".child", "w").write(str(child.pid))
for line in sys.stdin:
    asked = json.loads(line)
    open(os.environ["STANDIN_SEEN"] + ".asked", "a").write(line)
    if asked.get("type") == "control_request":
        status = [{{"name": "jira_write", "status": fail or "connected"}}]
        answer = {{"mcpServers": status}} if asked["request"]["subtype"] == "mcp_status" else {{}}
        reply = {{"subtype": "success", "request_id": asked["request_id"], "response": answer}}
        reply = {{"type": "control_response", "response": reply}}
        print(json.dumps({{"type": "system"}}) + "\\n" + json.dumps(reply), flush=True)
    elif "id" in asked and asked["method"] == fail:
        error = {{"code": -32603, "message": "failed to load workspace requirements"}}
        print(json.dumps({{"id": asked["id"], "error": error}}), flush=True)
    elif "id" in asked:
        reply = {{"id": asked["id"], "result": {{}}}}
        print(json.dumps({{"method": "account/updated"}}) + "\\n" + json.dumps(reply), flush=True)
"""

SERVER = (
    '[mcp_servers.jira_write]\ncommand="/p"\nrequired=true\n[mcp_servers.jira_write.tools.run]\n'
)
PLOT_SERVER = '[mcp_servers.optional_reader]\ncommand="npx"\nargs=["-y"]\n'


def _launch(tmp_path: Path, monkeypatch, tool: str) -> Launch:
    # A notification and a reply arrive in one read, which must not wait out the deadline.
    monkeypatch.setattr(native_check, "WAIT", 5)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    monkeypatch.setenv("STANDIN_SEEN", str(tmp_path / "seen.json"))
    monkeypatch.setenv("ORCA_PANE_KEY", "pane")
    client = tmp_path / ".local/bin/codex"
    client.parent.mkdir(parents=True)
    client.write_text(STANDIN.format(python=sys.executable))
    client.chmod(0o755)
    launch = Launch("scratch", "scratch-one", "", tool=tool, claude_bin=str(client))
    launch.wt = tmp_path / "wt"
    if tool == "codex":
        (launch.wt / ".codex").mkdir(parents=True)
        (launch.wt / ".codex/config.toml").write_text(SERVER + 'approval_mode="prompt"\n')
    else:
        (launch.wt / ".claude/service-actions").mkdir(parents=True)
        servers = {"mcpServers": {"jira_write": {"command": "/p", "args": []}}}
        (launch.wt / ".claude/service-actions/mcp.json").write_text(json.dumps(servers))
    return launch


@pytest.mark.parametrize(("tool", "fail"), [("codex", "account/read"), ("claude", "failed")])
def test_preflight_stops_and_names_the_write_tools_and_client(tmp_path, monkeypatch, tool, fail):
    """Bug: a client update breaks the write tools and the launch reports an account error."""
    launch = _launch(tmp_path, monkeypatch, tool)
    monkeypatch.setenv("STANDIN_FAIL", fail)
    with pytest.raises(Stop) as stopped:
        native_check.check(launch)
    reason = "account/read failed" if tool == "codex" else "jira_write failed"
    assert f"native write tools jira_write cannot start on standin 9.9: {reason}" in (
        stopped.value.text
    )
    assert "Nothing opened" in stopped.value.text


@pytest.mark.parametrize("tool", ["codex", "claude"])
def test_preflight_starts_the_worker_client_settings(tmp_path, monkeypatch, capsys, tool):
    """Bug: the preflight starts a client unlike the worker's, reports itself to Orca, or trusts
    the workspace in the operator's Codex store."""
    launch = _launch(tmp_path, monkeypatch, tool)
    native_check.check(launch)
    seen = json.loads((tmp_path / "seen.json").read_text())
    if tool == "codex":
        assert seen["argv"][0] == "app-server"
        asked = [
            json.loads(line) for line in (tmp_path / "seen.json.asked").read_text().splitlines()
        ]
        start = next(message for message in asked if message.get("method") == "thread/start")
        # A thread started with a cwd marks that folder trusted in the operator's Codex store.
        assert start["params"] == {"ephemeral": True}
        assert command.native_pins(launch.wt / ".codex/config.toml")[0] in seen["argv"]
        assert 'approval_policy="on-request"' in seen["argv"]
    else:
        assert seen["argv"][seen["argv"].index("--permission-mode") + 1] == "auto"
        assert str(launch.wt / ".claude/access-settings.json") in seen["argv"]
    assert seen["orca"] == []
    assert "native write tools jira_write started in a preflight" in capsys.readouterr().out


@pytest.mark.parametrize("tool", ["codex", "claude"])
def test_preflight_skips_a_workspace_without_write_tools(tmp_path, monkeypatch, tool):
    """Bug: a plot that declares no write action is blocked by the write-tool preflight."""
    launch = _launch(tmp_path, monkeypatch, tool)
    for delivered in (".codex/config.toml", ".claude/service-actions/mcp.json"):
        (launch.wt / delivered).unlink(missing_ok=True)
    native_check.check(launch)
    assert not (tmp_path / "seen.json").exists()


def test_preflight_leaves_plot_servers_to_the_session(tmp_path, monkeypatch):
    """Bug: an optional plot server is started and reported as a native write tool."""
    launch = _launch(tmp_path, monkeypatch, "codex")
    config = launch.wt / ".codex/config.toml"
    assert native_check.writers(launch) == ["jira_write"]
    config.write_text(config.read_text() + PLOT_SERVER)
    assert native_check.writers(launch) == ["jira_write"]
    config.write_text(PLOT_SERVER)
    assert native_check.writers(launch) == []


def test_explicitly_disabled_writers_do_not_start(tmp_path, monkeypatch):
    launch = _launch(tmp_path, monkeypatch, "codex")
    launch.extra = ["-c", "mcp_servers.jira_write.enabled=false"]
    native_check.check(launch)
    assert not (tmp_path / "seen.json").exists()
    assert not launch.native_pending


def test_preflight_passes_optional_disable_after_the_complete_pin(tmp_path, monkeypatch):
    launch = _launch(tmp_path, monkeypatch, "codex")
    config = launch.wt / ".codex/config.toml"
    config.write_text(config.read_text() + PLOT_SERVER)
    launch.extra = ["-c", "mcp_servers.optional_reader.enabled=false"]
    native_check.check(launch)
    words = json.loads((tmp_path / "seen.json").read_text())["argv"]
    pin = next(word for word in words if word.startswith("mcp_servers.optional_reader="))
    assert words.index(pin) < words.index("mcp_servers.optional_reader.enabled=false")


@pytest.mark.parametrize(
    "fault,reason", [("timeout", "deadline exceeded"), ("oversize", "frame exceeds")]
)
def test_unfinished_protocol_is_bounded_and_its_process_is_reaped(
    tmp_path, monkeypatch, fault, reason
):
    launch = _launch(tmp_path, monkeypatch, "codex")
    monkeypatch.setattr(native_check, "WAIT", 0.2)
    monkeypatch.setattr(native_client, "EXIT_WAIT", 0.01)
    monkeypatch.setattr(native_client, "MAX_FRAME_BYTES", 1024)
    monkeypatch.setenv("STANDIN_FAIL", fault)
    with pytest.raises(Stop, match=reason):
        native_check.check(launch)
    assert not launch.native_pending


def test_exited_leader_keeps_its_group_owned_until_children_stop(tmp_path, monkeypatch):
    launch = _launch(tmp_path, monkeypatch, "codex")
    monkeypatch.setenv("STANDIN_CHILD", "1")
    native_check.check(launch)
    child = int((tmp_path / "seen.json.child").read_text())
    assert ownership.identity(child) is None
    assert not launch.native_pending


@pytest.mark.parametrize("fault", ["malformed", "shape"])
def test_untrusted_client_frames_are_refused_without_echoing_them(tmp_path, monkeypatch, fault):
    launch = _launch(tmp_path, monkeypatch, "codex")
    monkeypatch.setenv("STANDIN_FAIL", fault)
    with pytest.raises(Stop, match="invalid native-client reply") as stopped:
        native_check.check(launch)
    assert "PRIVATE_REPLY" not in stopped.value.text and not launch.native_pending
