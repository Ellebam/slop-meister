"""The relay prints every broker reply as one line and never a value anywhere else."""

import io
import json
import os

from slopmeister.secret_ask import cli
from slopmeister.session import secret_transport as transport

REQUEST = {
    "env": {"X": "op://A/B/C"},
    "argv": ["true"],
    "cwd": "/",
    "reason": "",
    "session": "s",
    "host": "h",
}


def connected_source(text: str):
    """A pipe-backed stdin whose writer stays open, as a live SSH client's does."""
    reader, writer = os.pipe()
    os.write(writer, text.encode())
    return os.fdopen(reader), writer


def test_relay_prints_receipt_then_final_result(monkeypatch):
    """Bug: the Mac shim cannot parse the broker's answer or misses the receipt."""
    calls = []
    replies = iter(
        [
            {"id": "a" * 32, "state": "pending"},
            {"id": "a" * 32, "state": "approved"},
            {"id": "a" * 32, "state": "delivered", "values": {"X": "v"}},
        ]
    )

    def exchange(path, data):
        calls.append(data)
        return next(replies)

    monkeypatch.setattr(transport, "exchange", exchange)
    monkeypatch.setattr(transport, "POLL_SECONDS", 0)
    sink = io.StringIO()
    request = REQUEST
    source, writer = connected_source(json.dumps(request) + "\n")
    assert cli.relay(source, sink) == 0
    os.close(writer)
    lines = [json.loads(line) for line in sink.getvalue().splitlines()]
    assert lines == [
        {"id": "a" * 32, "state": "pending"},
        {"id": "a" * 32, "state": "delivered", "values": {"X": "v"}},
    ]
    assert calls[0] == {**request, "op": "run"}
    assert calls[1:] == [{"op": "wait", "id": "a" * 32}] * 2


def test_relay_reports_refusal_and_unavailability_as_error_lines(monkeypatch):
    """Bug: a refused or unreachable broker leaves the Mac shim with a bare SSH failure."""
    for error, kind in (
        (transport.Refused("bad request"), "request refused"),
        (OSError("down"), "broker unavailable"),
    ):

        def exchange(path, data, error=error):
            raise error

        monkeypatch.setattr(transport, "exchange", exchange)
        sink = io.StringIO()
        assert cli.relay(io.StringIO("{}\n"), sink) == 1
        assert json.loads(sink.getvalue())["error"] == kind
    sink = io.StringIO()
    assert cli.relay(io.StringIO("[]\n"), sink) == 1
    assert "object" in json.loads(sink.getvalue())["detail"]


def test_relay_stops_polling_once_its_client_is_gone(monkeypatch):
    """Bug: a relay left by a timed-out Mac client collects an approval nobody receives."""
    polls = []

    def exchange(path, data):
        polls.append(data["op"])
        return {"id": "a" * 32, "state": "pending"}

    monkeypatch.setattr(transport, "exchange", exchange)
    monkeypatch.setattr(transport, "POLL_SECONDS", 0)
    request = REQUEST
    source, writer = connected_source(json.dumps(request) + "\n")
    os.close(writer)
    sink = io.StringIO()
    assert cli.relay(source, sink) == 1
    lines = [json.loads(line) for line in sink.getvalue().splitlines()]
    assert lines[0] == {"id": "a" * 32, "state": "pending"}
    assert lines[-1]["error"] == "broker unavailable" and "disconnected" in lines[-1]["detail"]
    assert polls == ["run"]
