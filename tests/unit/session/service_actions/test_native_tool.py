"""The native writer accepts literal fixed commands and bounded protocol inputs."""

import importlib
import json
from pathlib import Path
import shlex

import pytest

from slopmeister.session.service_actions.constants import PYTHON, PYTHON_FLAGS


@pytest.fixture
def adapter(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[4] / "slopmeister/session"))
    subject = importlib.import_module("service_actions.native_tool")
    monkeypatch.setattr(subject, "ROOT", tmp_path)
    return subject


@pytest.mark.parametrize("invalid", ["name", "extra", "type", "size", "prefix", "quote"])
def test_native_writer_rejects_unapproved_command_shapes(adapter, invalid):
    """Bug: altered input admits a different executable, hidden argument or unbounded command."""
    argv = [
        str(PYTHON),
        *PYTHON_FLAGS,
        str(adapter.ROOT / "entry.py"),
        "--output",
        "/out",
        "--permissions",
        "TEST",
    ]
    params = {"name": "run", "arguments": {"command": shlex.join(argv)}}
    commands = {
        "type": [],
        "size": params["arguments"]["command"] + "x" * adapter.MAX_COMMAND,
        "prefix": "env " + params["arguments"]["command"],
        "quote": params["arguments"]["command"] + "'",
    }
    if invalid in commands:
        params["arguments"]["command"] = commands[invalid]
    if invalid == "name":
        params["name"] = "other"
    if invalid == "extra":
        params["arguments"]["extra"] = "hidden"
    with pytest.raises(ValueError, match="ARGUMENTS_NOT_SUPPORTED|No closing quotation"):
        adapter.arguments(params)


def test_native_writer_passes_payload_as_literal_argv(adapter):
    """Bug: a approved shell-looking body is expanded instead of passed as text."""
    argv = [
        str(PYTHON),
        *PYTHON_FLAGS,
        str(adapter.ROOT / "entry.py"),
        "--output",
        "/out",
        "--body",
        "$(echo secret);\n'quoted'",
    ]
    result, output = adapter.arguments({"name": "run", "arguments": {"command": shlex.join(argv)}})
    assert result == argv and output == "/out"


@pytest.mark.parametrize(
    "raw",
    [
        b"[]\n",
        b'{"jsonrpc":"1.0"}\n',
        b'{"jsonrpc":"2.0","id":true}\n',
        b'{"jsonrpc":"2.0","params":[]}\n',
        b"\xff\n",
    ],
)
def test_malformed_protocol_cannot_reach_a_write(adapter, monkeypatch, raw):
    """Bug: malformed or ambiguous RPC input reaches dispatch and starts a writer."""
    monkeypatch.setattr(adapter.os, "read", lambda *_args: raw)
    monkeypatch.setattr(adapter, "dispatch", lambda *_args: pytest.fail("dispatch reached"))
    state = adapter.fresh_state()
    assert adapter.batch(b"", {}, state) is None
    assert state["job"] is None


def test_fragmented_protocol_input_remains_bounded(adapter, monkeypatch):
    """Bug: newline-free fragments can grow beyond the adapter's memory limit."""
    monkeypatch.setattr(adapter.os, "read", lambda *_args: b"x")
    with pytest.raises(ValueError, match="INPUT_INVALID"):
        adapter.batch(b"x" * adapter.MAX_INPUT, {}, adapter.fresh_state())


def test_cancellation_for_another_call_does_not_stop_the_writer(adapter, monkeypatch):
    """Bug: a stale cancellation interrupts the current approved write."""
    monkeypatch.setattr(adapter, "stop", lambda *_args: pytest.fail("writer stopped"))
    job = {"identity": 1}
    request = dict(method="notifications/cancelled", params={"requestId": 2})
    assert adapter.dispatch(request, {}, job) is job


def test_tool_advertises_the_central_intent_and_input_limits(adapter):
    """Bug: the native reviewer cannot see the selected writer's central permission rule."""
    value = adapter.tool("exact operator intent")
    assert value["description"] == "exact operator intent"
    assert value["annotations"]["readOnlyHint"] is False
    assert value["inputSchema"]["additionalProperties"] is False
    assert value["inputSchema"]["properties"]["command"]["maxLength"] == adapter.MAX_COMMAND
    json.dumps(value)


def test_native_adapter_checks_host_before_starting_a_writer(adapter, monkeypatch, capsys):
    """Bug: untrusted requests spawn the consumer before native caller validation."""

    def refused(*_args):
        raise ValueError("NATIVE_APPROVAL_REQUIRED: client")

    monkeypatch.setattr(adapter, "require_host", refused)
    monkeypatch.setattr(
        adapter.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("writer started")
    )
    with pytest.raises(ValueError, match="NATIVE_APPROVAL_REQUIRED"):
        adapter.start({"id": 1}, {})
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {}}
    monkeypatch.setattr(adapter.os, "read", lambda *_args: json.dumps(request).encode() + b"\n")
    adapter.batch(b"", {}, adapter.fresh_state())
    result = json.loads(capsys.readouterr().out)
    assert result["error"]["message"] == "NATIVE_APPROVAL_REQUIRED: client"


def test_native_adapter_refuses_host_before_serving_protocol(adapter, monkeypatch):
    """Bug: an untrusted process gets a usable native protocol server."""

    def refused(*_args):
        raise ValueError("NATIVE_APPROVAL_REQUIRED")

    monkeypatch.setattr(adapter, "require_host", refused)
    monkeypatch.setattr(adapter.signal, "signal", lambda *_args: pytest.fail("protocol served"))
    with pytest.raises(ValueError, match="NATIVE_APPROVAL_REQUIRED"):
        adapter.serve({})


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("NATIVE_APPROVAL_REQUIRED: client", "client"),
        ("NATIVE_APPROVAL_REQUIRED: ask", "ask"),
        ("private token and client path", "local"),
    ],
)
def test_native_startup_reports_only_fixed_reason_words(
    adapter, monkeypatch, capsys, message, reason
):
    (adapter.ROOT / "config.json").write_text('{"native":{}}')

    def refused(binding):
        assert binding == {}
        raise ValueError(message)

    monkeypatch.setattr(adapter, "serve", refused)
    assert adapter.main() == 1
    output = capsys.readouterr()
    assert output.err == f"NATIVE_APPROVAL_REQUIRED: {reason}\n"
    assert output.out == ""
