"""Reach the approval broker: its Unix socket on the Linux agent host, the SSH relay elsewhere.

Every exchange is one JSON line each way over a fresh connection. The relay on the broker host
runs the same submit-and-wait loop and prints each reply as a line, so the Mac reads the receipt
first and the final result last.
"""

import json
from pathlib import Path
import socket
import subprocess
import time

from slopmeister.session import remote_ssh

SOCKET = Path("/run/slopmeister-secret-ask/control.sock")
RELAY = "/usr/local/bin/slopmeister secret-ask relay"
ACTIVE = ("pending", "approved")
POLL_SECONDS = 1
EXCHANGE_TIMEOUT = 10
LINE_LIMIT = 1048576
STDERR_TAIL = 500


class Unreachable(Exception):
    """The broker cannot be reached, the message names the step that failed."""


class Refused(Exception):
    """The broker refused the request, so repeating it unchanged is pointless."""


def receive_line(sock: socket.socket) -> bytes:
    data = b""
    while not data.endswith(b"\n"):
        chunk = sock.recv(65536)
        if not chunk:
            raise OSError("the broker closed the connection before answering")
        data += chunk
        if len(data) > LINE_LIMIT:
            raise OSError("the broker's reply exceeds the limit")
    return data


def checked(line: bytes) -> dict:
    """The broker's reply as a dict, or the matching exception for an error reply."""
    try:
        reply = json.loads(line)
    except ValueError:
        raise OSError("the broker's reply is not JSON") from None
    if not isinstance(reply, dict):
        raise OSError("the broker's reply is not an object")
    if reply.get("error") == "request refused":
        raise Refused(str(reply.get("detail") or "request refused"))
    if "error" in reply:
        raise OSError(str(reply.get("detail") or reply["error"]))
    return reply


def exchange(path: Path, data: dict) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(EXCHANGE_TIMEOUT)
        client.connect(str(path))
        client.sendall(json.dumps(data).encode() + b"\n")
        return checked(receive_line(client))


def settle(path: Path, request: dict, client: tuple) -> dict:
    """Submit once, hand the receipt to the client's report, poll until no longer active.

    The client is (report, alive). Polling stops when alive() says the waiting client is gone,
    so an approval is never collected for a client that cannot receive it.
    """
    report, alive = client
    receipt = exchange(path, {**request, "op": "run"})
    report(receipt)
    while True:
        if not alive():
            raise OSError("the waiting client disconnected before the decision")
        reply = exchange(path, {"op": "wait", "id": receipt["id"]})
        if reply.get("state") not in ACTIVE:
            return reply
        time.sleep(POLL_SECONDS)


def alias(home: Path) -> str:
    """The one alias of the dedicated SSH configuration, which is the broker host."""
    config = remote_ssh.config_path(home)
    try:
        names = remote_ssh.aliases(home)
    except OSError:
        raise Unreachable(f"no broker socket at {SOCKET} and no SSH route at {config}") from None
    if len(names) != 1:
        raise Unreachable(
            f"{config} must declare exactly one alias, the broker host, found {names}"
        )
    return names[0]


def _relay_lines(ssh: subprocess.Popen, name: str, report) -> list[dict]:
    replies: list[dict] = []
    try:
        for line in ssh.stdout:
            replies.append(checked(line.encode()))
            if len(replies) == 1:
                report(replies[0])
    except OSError as error:
        raise Unreachable(f"the relay on {name} reported: {error}") from None
    return replies


def remote(home: Path, request: dict, report) -> dict:
    """Run the relay on the broker host over SSH and read its reply lines."""
    name = alias(home)
    try:
        ssh = subprocess.Popen(
            remote_ssh.argv(home, name, RELAY),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as error:
        raise Unreachable(f"ssh cannot start: {error}") from None
    with ssh:
        # The relay reads EOF on its stdin as the client leaving, so the input stays open until
        # the relay has printed its last line.
        ssh.stdin.write(json.dumps(request) + "\n")
        ssh.stdin.flush()
        replies = _relay_lines(ssh, name, report)
        ssh.stdin.close()
        detail = ssh.stderr.read().strip()[-STDERR_TAIL:]
    if len(replies) < 2:
        cause = detail or f"exit {ssh.returncode}"
        raise Unreachable(f"the SSH route {name} gave no result: {cause}")
    return replies[-1]


def reach(request: dict, report) -> dict:
    """The final reply for one request, through the local socket when it exists, else over SSH."""
    if SOCKET.exists():
        try:
            return settle(SOCKET, request, (report, lambda: True))
        except OSError as error:
            raise Unreachable(f"the broker socket {SOCKET} failed: {error}") from None
    return remote(Path.home(), request, report)
