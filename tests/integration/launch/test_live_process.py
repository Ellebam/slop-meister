"""The live-process preflight matches the whole session name, never a prefix of another."""

import os
import signal
import subprocess

import pytest

from tests.integration.launch.helpers import launch, machine, target


@pytest.mark.xdist_group("launch-processes")
def test_preflight_matches_exact_name(tmp_path):
    """A session name that prefixes a live name must not match the other worker."""
    world = machine(tmp_path)
    repo = target(tmp_path / "repo")
    live = subprocess.Popen(
        ["/bin/sh", "-c", "sleep 60; true", "fake-claude", "remote-control=example-client-wt10"],
        start_new_session=True,
    )
    try:
        launch(world, str(repo), "example-client", "example-client-wt1")
        refused = launch(world, str(repo), "example-client", "example-client-wt10", ok=False)
        assert "a live process already carries remote-control=example-client-wt10" in refused.stderr
    finally:
        os.killpg(live.pid, signal.SIGKILL)
        live.wait()
