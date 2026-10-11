"""Collect a tester's terminal result without relaunching or writing one."""

import json
import os
from pathlib import Path
import time

from slopmeister.spine.tester import runs

GRACE_SECONDS = 30
MISSING = (
    "Tester BLOCKED: the supervisor is gone and saved no terminal result. "
    "Inspect owned process evidence before further action.\nEvidence: {root}\n"
)


def collect(root: Path, wait_seconds: float) -> int:
    saved = root / "result.json"
    deadline = time.monotonic() + wait_seconds
    while not saved.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    if not saved.exists():
        # The supervisor saves its result before it exits, so look once more after it is gone.
        gone = _supervisor_gone(root)
        if not saved.exists():
            if gone:
                print(MISSING.format(root=root), end="")
                return 1
            print(f"PENDING: collect {root}; do not launch a duplicate tester")
            return 3
    result = json.loads(saved.read_text())
    print((root / "report.md").read_text(), end="")
    return int(result["exit_code"])


def _supervisor_gone(root: Path) -> bool:
    try:
        pid = json.loads((root / "accepted.json").read_text())["supervisor_pid"]
    except FileNotFoundError:
        # No supervisor was admitted yet, only the run's deadline can end the wait.
        run = json.loads((root / "run.json").read_text())
        return time.time() - run["started_at"] > runs.TIMEOUT_SECONDS + GRACE_SECONDS
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False
