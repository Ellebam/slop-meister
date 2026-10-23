"""A terminated deployment removes only its private reviewed payload."""

import json
import os
from pathlib import Path
import signal
import subprocess
import time

import pytest

from host.tests.test_deploy import deployment as deployment

pytestmark = pytest.mark.xdist_group("host-deployment")


@pytest.fixture
def running_deployment(deployment, monkeypatch):
    repo, revision, log = deployment
    ready = log.parent / "ready"
    monkeypatch.setenv("DEPLOY_READY", str(ready))
    args = [
        "task",
        "host:ha:deploy",
        "HOST_INVENTORY=/synthetic/inventory.yml",
        "HOST_SETTINGS=/synthetic/settings.yml",
        f"HOST_REVISION={revision}",
    ]
    process = subprocess.Popen(
        args,
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        yield process, ready, log
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=10)


def test_ha_payload_cleanup_survives_a_terminated_task(running_deployment):
    process, ready, log = running_deployment
    deadline = time.monotonic() + 5
    while not ready.exists() and time.monotonic() < deadline and process.poll() is None:
        time.sleep(0.02)
    assert ready.exists() and process.poll() is None
    os.killpg(process.pid, signal.SIGTERM)
    output, error = process.communicate(timeout=10)
    assert process.returncode != 0, output + error
    payload = json.loads(Path(str(log) + ".payload").read_text())
    assert not Path(payload["root"]).exists()
