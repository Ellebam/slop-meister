"""Notify a managed worker's operator when its native permission dialog opens."""

from contextlib import suppress
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from slopmeister.session import launch_identity

ROUTE = re.compile(r"run_[A-Za-z0-9_-]{1,128}")
ROUTE_VARIABLE = "SLOPMEISTER_PROMPT_ROUTE"
ORCAS = ("/usr/bin/orca-ide", "/Applications/Orca.app/Contents/Resources/bin/orca")
PAYLOAD_LIMIT = 1024 * 1024


def notice() -> None:
    run = os.environ.get(ROUTE_VARIABLE, "")
    handle = os.environ.get("ORCA_TERMINAL_HANDLE", "")
    if not ROUTE.fullmatch(run) or not handle:
        return
    workspace = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    identity = launch_identity.read(workspace)
    raw = sys.stdin.buffer.read(PAYLOAD_LIMIT + 1)
    if len(raw) > PAYLOAD_LIMIT:
        return
    request = json.loads(raw)
    if not isinstance(request, dict) or request.get("session_id") != identity["session_id"]:
        return
    orca = next((entry for entry in ORCAS if os.access(entry, os.X_OK)), None)
    if orca:
        # Content and command arguments can contain credentials. Keep them in the native dialog.
        subprocess.run(
            [
                orca,
                "orchestration",
                "send",
                "--from",
                handle,
                "--to",
                f"run:{run}",
                "--subject",
                "Permission prompt waiting",
                "--body",
                "Open this worker’s native permission dialog to inspect the action.",
                "--json",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            check=False,
        )


def main(argv: list[str]) -> int:
    if argv != ["notice"]:
        return 2
    with suppress(ValueError, OSError, KeyError, RecursionError, subprocess.TimeoutExpired):
        notice()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
