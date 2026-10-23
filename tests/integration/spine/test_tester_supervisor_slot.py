"""The detached supervisor must retain the public slot-state override through cleanup."""

import fcntl
import json
import os
from pathlib import Path
import sys
import time

import pytest

from slopmeister.slots import tester
from slopmeister.spine.tester import launch
from tests.integration.spine.test_tester_slots import allocated_subject as allocated_subject

pytestmark = pytest.mark.xdist_group("tester-slots")


@pytest.mark.parametrize("tool", ["claude", "codex", "opencode"])
def test_detached_supervisor_releases_the_configured_slot_state(
    allocated_subject, monkeypatch, tool
):
    _, args = allocated_subject
    start = launch._start_supervisor
    monkeypatch.setattr(launch, "_start_supervisor", lambda *_: None)
    monkeypatch.setattr(launch, "_await_acceptance", lambda root: root)
    root = launch.launch(args)
    run = json.loads((root / "run.json").read_text())
    run.update(tool=tool, provider_names=[])
    data = Path(run["slot"]["state"])
    descriptor = os.open(data / tester.RECORD, os.O_RDONLY)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    run["slot"]["fd"] = descriptor
    outcome = root / "cleanup-result.json"
    code = (
        "import json; from pathlib import Path; from slopmeister.slots import allocation,tester; "
        "allocation.bound_ports=lambda: []; tester.occupants.census=lambda _: []; "
        f"run=json.loads({json.dumps(run)!r}); error=tester.cleanup(Path({str(root)!r}),run); "
        f"Path({str(outcome)!r}).write_text(json.dumps({{'error':error}}))"
    )
    monkeypatch.setattr(launch.runs, "command", lambda *_: [sys.executable, "-c", code])
    try:
        start(root, run)
        wait_for_outcome(root, outcome)
        assert json.loads(outcome.read_text())["error"] is None
        assert not data.exists()
    finally:
        os.close(descriptor)


def wait_for_outcome(root, outcome):
    deadline = time.monotonic() + 5
    while not outcome.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert outcome.exists(), (root / "supervisor.log").read_text()
