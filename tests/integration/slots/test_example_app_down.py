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
    log.write_text("a previous result\n")
    report = "Task finished. Next action: release the slot.\n"
    result = subprocess.run(
        [sys.executable, "-c", LINGER, str(log)],
        cwd=ROOT,
        input=report,
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    deadline = time.monotonic() + 30
    while not log.read_text().endswith("True True\n"):
        assert time.monotonic() < deadline, "the detached process never wrote"
        time.sleep(0.1)
    assert result.stdout == report and log.read_text() == report + "True True\n"
