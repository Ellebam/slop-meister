"""One JSON line per request over the agent-only Unix socket, checked against the peer's uid."""

import json
import socket
import struct
import sys

from slopmeister.session.secret_transport import LINE_LIMIT, receive_line

from .broker import Broker

LOCAL_PEERCRED = 0x0001
# macOS xucred: version, uid, group count, sixteen groups.
XUCRED = "IIh16I"
REQUEST_LIMIT = 65536


def peer_uid(sock: socket.socket) -> int:
    if sys.platform == "darwin":
        data = sock.getsockopt(0, LOCAL_PEERCRED, struct.calcsize(XUCRED))
        return struct.unpack(XUCRED, data)[1]
    _, uid, _ = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    return uid


def receive(sock: socket.socket) -> dict:
    data = receive_line(sock)
    if len(data) > min(REQUEST_LIMIT, LINE_LIMIT):
        raise ValueError("request exceeds limit")
    message = json.loads(data)
    if not isinstance(message, dict):
        raise ValueError("request must be an object")
    return message


def dispatch(broker: Broker, uid: int, data: dict) -> dict:
    operation = data.pop("op", None)
    if operation == "run":
        return broker.submit(uid, data)
    if operation == "wait" and set(data) == {"id"}:
        if not isinstance(data["id"], str) or len(data["id"]) != 32:
            raise ValueError("invalid request ID")
        return broker.collect(data["id"], uid)
    raise ValueError("unsupported request")


def handle(sock: socket.socket, broker: Broker, agent_uid: int) -> None:
    with sock:
        sock.settimeout(3)
        try:
            uid = peer_uid(sock)
            if uid != agent_uid:
                raise ValueError("caller is not the configured agent")
            response = dispatch(broker, uid, receive(sock))
        except (ValueError, TypeError, KeyError) as error:
            response = {"error": "request refused", "detail": str(error)}
        except OSError:
            response = {"error": "broker unavailable"}
        # The service owns the accepted request after the client disconnects.
        try:
            sock.sendall(json.dumps(response).encode() + b"\n")
        except OSError:
            if "values" in response:
                broker.restore(response["id"], response["values"])
