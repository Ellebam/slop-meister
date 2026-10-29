"""Issue locks serialize separate claim processes."""

import json
import subprocess
import sys

from slopmeister.claims import locks
from tests.support import trees


def test_lock_is_shared_and_released_without_releasing_claim(tmp_path):
    context = {"common": tmp_path}
    receipt = trees.write(tmp_path, "issue.json", '{"phase":"claimed"}')
    code = 'import fcntl,sys; f=open(sys.argv[1],"r+"); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)'
    with locks.locked(context, 7):
        attempt = subprocess.run(
            [sys.executable, "-c", code, str(locks.lock_path(context, 7))], capture_output=True
        )
        assert attempt.returncode != 0
    result = subprocess.run([sys.executable, "-c", code, str(locks.lock_path(context, 7))])
    assert result.returncode == 0
    assert json.loads(receipt.read_text())["phase"] == "claimed"


def test_launcher_holds_issue_lock_while_preparing_workspace(tmp_path, monkeypatch):
    """Another launcher must not acquire the issue between preflight and initialization."""
    from slopmeister.claims import evidence, github, lifecycle
    from slopmeister.launch import issue
    from slopmeister.launch.model import Launch

    context = github.Repository(tmp_path, tmp_path, "owner/project", "remote", "fixture")
    monkeypatch.setattr(github, "context", lambda *args: context)
    monkeypatch.setattr(evidence, "eligible", lambda *args: True)
    monkeypatch.setattr(lifecycle, "preflight", lambda *args: None)
    launch = Launch(
        "fixture", "fixture-one", str(tmp_path), repo=tmp_path, issue_id="7", model_set=True
    )
    try:
        issue.claim(launch)
        code = (
            'import fcntl,sys; f=open(sys.argv[1],"r+"); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)'
        )
        attempt = subprocess.run(
            [sys.executable, "-c", code, str(locks.lock_path(context, 7))],
            capture_output=True,
            text=True,
        )
        assert attempt.returncode != 0, "issue lock escaped the launcher during preparation"
        assert "BlockingIOError" in attempt.stderr
    finally:
        if launch.lock_fd is not None:
            import os

            os.close(launch.lock_fd)
