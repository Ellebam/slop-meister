"""Slot status uses the real macOS listener inventory."""

from pathlib import Path
import subprocess
import sys

from slopmeister.slots import allocation, status

ROOT = Path(__file__).resolve().parents[3]


def test_native_listener_inventory_preserves_pid_port_and_working_directory(tmp_path):
    """Bug: the Python port lost listener attribution or guessed a foreign process cwd."""
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import socket,time; s=socket.socket(); s.bind(('127.0.0.1',0)); "
            "s.listen(); print(s.getsockname()[1],flush=True); time.sleep(30)",
        ],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        port = int(child.stdout.readline())
        listeners = allocation.bound_ports()
        assert allocation.Listener(port, child.pid, "Python") in listeners or any(
            row.port == port and row.pid == child.pid for row in listeners
        )
        assert status._working_directories([child.pid]) == {child.pid: tmp_path.resolve()}
    finally:
        child.terminate()
        child.wait(timeout=5)
