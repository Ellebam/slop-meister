"""Drive the daemon, Unix client, HA HTTP/WebSocket transport and resolution together."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import shutil
import tempfile
import threading
import time

import pytest
from websockets.sync.client import connect
from websockets.sync.server import serve

from slopmeister.secret_ask import daemon, home_assistant
from slopmeister.secret_ask.config import Config
from slopmeister.session.secret_transport import exchange

pytestmark = pytest.mark.xdist_group("secret-ask-sockets")


class HTTP(BaseHTTPRequestHandler):
    def do_POST(self):
        assert self.headers["Authorization"] == "Bearer synthetic-ha-token"
        self.server.calls.append(
            (self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        )
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_args):
        pass


@contextmanager
def fake_ha():
    calls, decisions = [], queue.Queue()

    http = ThreadingHTTPServer(("127.0.0.1", 0), HTTP)
    http.calls = calls
    worker = threading.Thread(target=http.serve_forever)
    worker.start()
    with serve(lambda ws: socket_handler(ws, decisions), "127.0.0.1", 0) as ws_server:
        ws_worker = threading.Thread(target=ws_server.serve_forever)
        ws_worker.start()
        try:
            yield http.server_port, ws_server.socket.getsockname()[1], calls, decisions
        finally:
            decisions.put(None)
            ws_server.shutdown()
            ws_worker.join(timeout=5)
            http.shutdown()
            http.server_close()
            worker.join(timeout=5)


def socket_handler(ws, decisions):
    ws.send(json.dumps({"type": "auth_required"}))
    assert json.loads(ws.recv())["access_token"] == "synthetic-ha-token"
    ws.send(json.dumps({"type": "auth_ok"}))
    for identifier in (1, 2):
        message = json.loads(ws.recv())
        assert message["type"] == "subscribe_events" and message["id"] == identifier
        ws.send(json.dumps({"id": identifier, "type": "result", "success": True}))
    while (event := decisions.get()) is not None:
        ws.send(json.dumps({"type": "event", "id": 1, "event": event}))


def configuration(root, port):
    for name, value in (("ha-token", "synthetic-ha-token"), ("op-token", "synthetic-op-token")):
        (root / name).write_text(value)
        (root / name).chmod(0o600)
    op = root / "op"
    op.write_text(
        '#!/bin/sh\ntest "$OP_SERVICE_ACCOUNT_TOKEN" = synthetic-op-token || exit 9\n'
        "printf synthetic-demo-secret\n"
    )
    op.chmod(0o700)
    return Config(
        f"http://127.0.0.1:{port}",
        "operator",
        os.getuid(),
        ("mobile_app_phone", "mobile_app_mac"),
        root,
        # macOS caps socket paths at about a hundred characters, pytest's directory is longer.
        Path(tempfile.mkdtemp(prefix="sa-", dir="/tmp")) / "control.sock",
        op,
        root / "op-token",
        root / "ha-token",
    )


def eventually(probe):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if result := probe():
            return result
        time.sleep(0.05)
    raise AssertionError("expected state was not reached in ten seconds")


def call(path, message):
    return exchange(path, message)


def ready(config):
    """The receipt once the daemon listens, a bound but not yet listening socket refuses."""
    if not config.socket.exists():
        return None
    try:
        return submit(config)
    except ConnectionRefusedError:
        return None


def submit(config):
    return call(
        config.socket,
        {
            "op": "run",
            "env": {"DEMO_SECRET": "op://Example/Demo/password"},
            "argv": ["/usr/bin/true"],
            "cwd": "/",
            "reason": "roundtrip",
            "session": "test-session",
            "host": "test-host",
        },
    )


@pytest.mark.parametrize("decision", ["Approve", "Deny"])
def test_request_roundtrip_survives_disconnect_and_honors_only_operator(
    tmp_path, monkeypatch, decision
):
    """Bug: the assembled route loses approvals, delivers before approval, delivers twice, or
    fails to retract peers."""
    with fake_ha() as (port, ws_port, calls, decisions):
        monkeypatch.setattr(
            home_assistant,
            "connect",
            lambda url, **kw: connect(f"ws://127.0.0.1:{ws_port}/api/websocket", **kw),
        )
        config = configuration(tmp_path, port)
        service = daemon.Daemon(config)
        worker = threading.Thread(target=service.run)
        worker.start()
        try:
            receipt = eventually(lambda: ready(config))
            check_roundtrip(service, calls, decisions, (receipt, decision))
        finally:
            service.stop.set()
            worker.join(timeout=20)
            shutil.rmtree(config.socket.parent, ignore_errors=True)
        assert not worker.is_alive()
    for name in ("audit.log", "requests.json"):
        assert "synthetic-demo-secret" not in (tmp_path / name).read_text()
        assert "synthetic-op-token" not in (tmp_path / name).read_text()


def check_roundtrip(service, calls, decisions, choice):
    receipt, decision = choice
    pushes = eventually(lambda: notifications(calls))
    eventually(lambda: len(notifications(calls)) == 2)
    assert "op://Example/Demo/password" in pushes[0]["message"]
    action = next(a["action"] for a in pushes[0]["data"]["actions"] if a["title"] == decision)
    decisions.put({"context": {"user_id": "family"}, "data": {"action": action}})
    eventually(lambda: "decision_refused" in (service.config.state / "audit.log").read_text())
    assert service.broker.collect(receipt["id"], os.getuid())["state"] == "pending"
    decisions.put({"context": {"user_id": "operator"}, "data": {"action": action}})
    expected = "delivered" if decision == "Approve" else "denied"
    replies = []
    eventually(
        lambda: (
            replies.append(call(service.config.socket, {"op": "wait", "id": receipt["id"]}))
            or replies[-1]["state"] == expected
        )
    )
    if decision == "Approve":
        assert replies[-1]["values"] == {"DEMO_SECRET": "synthetic-demo-secret"}
        again = call(service.config.socket, {"op": "wait", "id": receipt["id"]})
        assert again == {"id": receipt["id"], "state": "delivered"}
    else:
        assert all("values" not in reply for reply in replies)
    eventually(lambda: len(notifications(calls, cleared=True)) == 2)


def notifications(calls, cleared=False):
    return [
        body
        for route, body in calls
        if "/notify/" in route and (body.get("message") == "clear_notification") == cleared
    ]
