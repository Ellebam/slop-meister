"""A disconnected client must not lose the request, and no other account may use the socket."""

import os
import socket
import threading

import pytest

from slopmeister.secret_ask.broker import Broker
from slopmeister.secret_ask.local import handle
from slopmeister.session.secret_transport import Refused, checked, receive_line

pytestmark = pytest.mark.xdist_group("secret-ask-sockets")
REQUEST = {
    "op": "run",
    "env": {"TOKEN": "op://Example/Demo/password"},
    "argv": ["/usr/bin/true"],
    "cwd": "/",
    "reason": "proof",
    "session": "session",
    "host": "host",
}


def exchange(client, data):
    import json

    client.sendall(json.dumps(data).encode() + b"\n")
    return checked(receive_line(client))


def served(broker, uid):
    client, server = socket.socketpair(type=socket.SOCK_STREAM)
    thread = threading.Thread(target=handle, args=(server, broker, uid))
    thread.start()
    return client, thread


@pytest.mark.parametrize("error", [ValueError, OSError])
def test_refusal_is_distinct_from_uncertain_storage_failure(tmp_path, monkeypatch, error):
    """Bug: a storage failure after admission is reported as a safe-to-repeat refusal."""
    broker = Broker(tmp_path, "operator")

    def fail(*args):
        raise error("synthetic error")

    monkeypatch.setattr("slopmeister.secret_ask.local.dispatch", fail)
    client, thread = served(broker, os.getuid())
    try:
        with pytest.raises(Refused if error is ValueError else OSError):
            exchange(client, {"op": "run"})
    finally:
        client.close()
        thread.join(timeout=3)
        broker.close()


def test_request_survives_client_disconnect(tmp_path):
    """Bug: a tool timeout drops the request, so the rerun needs a second approval."""
    broker = Broker(tmp_path, "operator")
    client, thread = served(broker, os.getuid())
    try:
        receipt = exchange(client, REQUEST)
    finally:
        client.close()
        thread.join(timeout=3)
    row = broker.pending()[0]
    approved = broker.decide(
        {"context": {"user_id": "operator"}, "data": {"action": row["approve"]}}
    )
    broker.ready(approved["id"], {"TOKEN": "v"})
    client, thread = served(broker, os.getuid())
    try:
        reply = exchange(client, {"op": "wait", "id": receipt["id"]})
    finally:
        client.close()
        thread.join(timeout=3)
    assert reply == {"id": receipt["id"], "state": "delivered", "values": {"TOKEN": "v"}}
    broker.close()


def test_other_peer_uid_cannot_submit_or_collect(tmp_path):
    """Bug: another local account can use the socket as the approved agent."""
    broker = Broker(tmp_path, "operator")
    broker.records["b" * 32] = {"id": "b" * 32, "uid": os.getuid(), "state": "pending"}
    client, thread = served(broker, os.getuid() + 1)
    try:
        with pytest.raises((Refused, OSError)):
            exchange(client, {"op": "wait", "id": "b" * 32})
    finally:
        client.close()
        thread.join(timeout=3)
        broker.close()


def test_values_return_when_the_reply_never_reaches_the_client(tmp_path):
    """Bug: a client gone before the reply consumes the approval, the rerun gets nothing."""
    broker = Broker(tmp_path, "operator")
    client, thread = served(broker, os.getuid())
    try:
        receipt = exchange(client, REQUEST)
    finally:
        client.close()
        thread.join(timeout=3)
    row = broker.pending()[0]
    broker.decide({"context": {"user_id": "operator"}, "data": {"action": row["approve"]}})
    broker.ready(receipt["id"], {"TOKEN": "v"})
    import json

    client, server = socket.socketpair(type=socket.SOCK_STREAM)
    client.sendall(json.dumps({"op": "wait", "id": receipt["id"]}).encode() + b"\n")
    client.close()
    handle(server, broker, os.getuid())
    assert broker.records[receipt["id"]]["state"] == "approved"
    assert broker.values == {receipt["id"]: {"TOKEN": "v"}}
    assert broker.collect(receipt["id"], os.getuid())["values"] == {"TOKEN": "v"}
    broker.close()
