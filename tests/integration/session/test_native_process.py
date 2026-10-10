"""Native channel inspection accepts only the configured client's own channel."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from slopmeister.session.service_actions import native_process

pytestmark = pytest.mark.xdist_group("service-actions-channel")

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = """
import json, os, socket, sys
from slopmeister.session.service_actions import native_process
if sys.argv[1] == 'foreign-socket':
    left, right = socket.socketpair()
    os.dup2(right.fileno(), 0)
exe, argv, parent = native_process.process(os.getpid())
owned = (native_process.owned_pipe(os.getppid()) if sys.argv[1] == 'pipe'
         else native_process.owned_socket(os.getppid()))
print(json.dumps([str(exe), argv, parent, owned]), flush=True)
"""


def _child(kind, channel, owner=True):
    process = subprocess.Popen(
        [sys.executable, "-c", PROGRAM, kind, "argument with spaces"],
        cwd=ROOT,
        stdin=channel,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        result = json.loads(process.stdout.readline())
        _, error = process.communicate(timeout=10)
        assert process.returncode == 0, error
        assert Path(result[0]).resolve() == native_process.process(os.getpid())[0].resolve()
        assert result[1][-2:] == [kind, "argument with spaces"]
        assert result[2] == os.getpid()
        assert result[3] is owner
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


def test_native_pipe_requires_the_parent_to_hold_its_write_end():
    """Bug: real client pipes fail, or an unrelated parent can supply a readable pipe."""
    read, write = os.pipe()
    try:
        _child("pipe", read)
        os.close(write)
        write = None
        _child("pipe", read, owner=False)
    finally:
        os.close(read)
        if write is not None:
            os.close(write)


def test_native_socket_requires_the_parent_to_hold_its_peer():
    """Bug: real client sockets fail, or a socket created by another process passes."""
    left, right = socket.socketpair()
    try:
        _child("socket", right)
        _child("foreign-socket", subprocess.DEVNULL, owner=False)
    finally:
        left.close()
        right.close()


def test_native_process_unavailable_identity_fails_closed():
    """Bug: a missing process yields an identity that could pass native binding checks."""
    with pytest.raises((OSError, ValueError)):
        native_process.process(2**30)


@pytest.mark.parametrize("kind", ["tcp", "peerless-unix"])
def test_native_socket_refuses_tcp_and_peerless_unix_channels(kind):
    """Bug: a TCP or unconnected socket can pass as the client's Unix input channel."""
    if kind == "tcp":
        with socket.socket() as listener, socket.socket() as connection:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            connection.connect(listener.getsockname())
            peer, _ = listener.accept()
            with peer:
                _child("socket", connection, owner=False)
    else:
        with socket.socket(socket.AF_UNIX) as unconnected:
            _child("socket", unconnected, owner=False)
