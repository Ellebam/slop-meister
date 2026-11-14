"""Unfinished harvest stops its caller while preserving the state needed to resume."""

import json
from pathlib import Path
import subprocess

import pytest

from tests.native.removal.test_example_app_remove import (
    REPORT,
    WORKER,
    _ps,
    _stop_owned,
    _until,
    _worker,
    _world,
)
from tests.support.repos import git


def _unfinished_state(repo, path, env):
    metadata = repo / ".git/worktrees/scratch"
    retained = {
        path / "README.md": b"unfinished tracked work\n",
        path / "draft.txt": b"unfinished untracked work\n",
        path / ".slot.env": b"SLOT_NAME=scratch\nSLOT_TARGET=slopmeister\n",
        metadata / "locked": b"keep unfinished work\n",
        metadata / "slopmeister-config/issue.json": json.dumps(
            {"phase": "claimed", "issue": 7}
        ).encode(),
        Path(env["SLOT_STATE_DIR"]) / "slopmeister-slot1/.slot.env": b"owned slot\n",
    }
    for file, content in retained.items():
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)
    return retained


@pytest.mark.xdist_group("workspace-removal-processes")
@pytest.mark.parametrize("kind", ["claude", "codex"])
def test_stop_only_keeps_unfinished_workspace(tmp_path, kind):
    """The caller and child must exit without removing dirty work, its claim or slot."""
    repo, path, env, other = _world(tmp_path)
    retained = _unfinished_state(repo, path, env)
    registration = git(repo, "worktree", "list", "--porcelain")
    neighbour = _worker(other, env, "read")
    worker = _worker(path, env, WORKER.replace("--self --", "--self --stop-only --"), kind)
    try:
        refused = subprocess.run(
            [env["CLI"], "workspace-remove", "--self", "--stop-only", "--", str(path)],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert refused.returncode != 0 and "--self requires the calling worker" in refused.stderr
        assert worker.poll() is None and neighbour.poll() is None
        Path(env["GO"]).touch()
        _until(
            lambda: (
                Path(env["OUT"]).exists() and "session stop pending" in Path(env["OUT"]).read_text()
            )
        )
        output = Path(env["OUT"]).read_text()
        assert output.startswith(REPORT) and "session stop pending" in output, output
        logs = Path(env["PLOT_SESSION_STATE_DIR"])
        _until(
            lambda: any(
                "session stopped; workspace kept:" in p.read_text() for p in logs.glob("*.log")
            )
        )
        assert worker.wait(timeout=30) is not None and neighbour.poll() is None
        assert _ps(int(Path(env["CHILD"]).read_text()), "stat=") in ("", "Z")
        assert git(repo, "worktree", "list", "--porcelain") == registration
        assert all(file.read_bytes() == content for file, content in retained.items())
        assert all(p.stat().st_mode & 0o077 == 0 for p in logs.glob("*.log"))
        assert all(p.read_text().startswith(REPORT) for p in logs.glob("*.log"))
    finally:
        _stop_owned(worker, neighbour, env)
