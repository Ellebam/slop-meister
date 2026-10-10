"""The process that outlives a self-releasing worker leaves the worker's process tree first."""

from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
# The command lingers for a second after the fork, as a slow interpreter exit would.
LINGER = """\
import os, sys, time
from pathlib import Path
from slopmeister.slots import down
command = os.getpid()
if down._detach(Path(sys.argv[1])):
    print(os.getppid() != command, os.getsid(0) == os.getpid())
else:
    time.sleep(1)
"""


def test_detached_process_starts_only_after_the_command_has_exited(tmp_path):
    """Bug: the cleanup was still the worker's descendant and the shutdown stopped it too."""
    log = tmp_path / "down.log"
    subprocess.run([sys.executable, "-c", LINGER, str(log)], cwd=ROOT, check=True, timeout=30)
    deadline = time.monotonic() + 30
    while not (log.is_file() and log.read_text().strip()):
        assert time.monotonic() < deadline, "the detached process never wrote"
        time.sleep(0.1)
    assert log.read_text().split() == ["True", "True"]
