"""A recorded stand-in worker proves self-cleanup leaves no live descendants or worktree."""

import json
import os
from pathlib import Path
import shlex
import subprocess
import time

import pytest

from slopmeister.install.fileops import lock_service_actions
from slopmeister.removal import remove_tree
from slopmeister.session.verify import snapshot
from tests.support.repos import GIT_ENV, git, scratch_repo

ROOT = Path(__file__).resolve().parents[3]
WORKER = """while [ ! -e "$GO" ]; do /bin/sleep 0.1; done
/bin/sleep 300 &
echo $! > "$CHILD"
/bin/sh -c 'cd "$REPO" && "$CLI" workspace-remove "$WORKSPACE" --self' > "$OUT" 2>&1
wait
"""


def _until(check):
    deadline = time.monotonic() + 30
    while not check():
        assert time.monotonic() < deadline, "cleanup did not finish"
        time.sleep(0.1)


def _ps(pid, column):
    result = subprocess.run(["ps", "-p", str(pid), "-o", column], capture_output=True, text=True)
    return result.stdout.strip()


def _worker(path, env, script):
    link = Path(env["TEST_ROOT"]) / f"standin-{path.name}/claude"
    link.parent.mkdir()
    link.symlink_to("/bin/bash")
    command = "exec -a claude " + shlex.join([str(link), "-c", script])
    process = subprocess.Popen(
        ["/bin/bash", "-c", command], cwd=path, env=env, stdin=subprocess.PIPE
    )
    _until(lambda: _ps(process.pid, "comm=") == "claude")
    return process


def _world(tmp_path):
    repo = scratch_repo(tmp_path / "main")
    git(repo, "worktree", "add", "-q", "-b", "scratch", ".worktrees/scratch")
    path = repo / ".worktrees/scratch"
    metadata = repo / ".git/worktrees/scratch/slopmeister-config"
    metadata.mkdir()
    (metadata / "issue.json").write_text(json.dumps({"phase": "closed", "issue": 7}))
    with (repo / ".git/info/exclude").open("a") as stream:
        stream.write(".claude\n.codex\n")
    for native in (".claude", ".codex"):
        action = path / native / "service-actions/jira-read"
        action.mkdir(parents=True)
        (action / "entry.py").touch()
    lock_service_actions(path, True)
    saved = {"plot": "slopmeister", "files": snapshot(path, [".claude", ".codex"])}
    (metadata / "state.json").write_text(json.dumps(saved))
    other = tmp_path / "neighbour"
    other.mkdir()
    env = {
        **os.environ,
        **GIT_ENV,
        "TEST_ROOT": str(tmp_path),
        "REPO": str(repo),
        "WORKSPACE": str(path),
        "CLI": str(ROOT / "bin/slopmeister"),
        **{key: str(tmp_path / key.lower()) for key in ("GO", "CHILD", "OUT")},
        "PLOT_SESSION_STATE_DIR": str(tmp_path / "logs"),
        "SLOT_STATE_DIR": str(tmp_path / "slots"),
    }
    return repo, path, env, other


def _stop_owned(worker, neighbour, env):
    for process in (worker, neighbour):
        if process.poll() is None:
            process.kill()
        process.wait()
    if Path(env["CHILD"]).exists():
        pid = int(Path(env["CHILD"]).read_text())
        if _ps(pid, "stat=") not in ("", "Z"):
            os.kill(pid, 15)
    remove_tree(Path(env["TEST_ROOT"]))


@pytest.mark.xdist_group("workspace-removal-processes")
def test_example_app_removes_the_owned_worker_and_descendants_but_keeps_a_neighbour(tmp_path):
    """Bug: cleanup died with the worker, left ghosts, or stopped a sibling or foreign caller."""
    repo, path, env, other = _world(tmp_path)
    neighbour = _worker(other, env, "read")
    worker = _worker(path, env, WORKER)
    try:
        for flags in (["--force"], ["--self"]):
            refused = subprocess.run(
                [env["CLI"], "workspace-remove", str(path), *flags],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert refused.returncode != 0 and path.exists(), refused.stdout + refused.stderr
        Path(env["GO"]).touch()
        logs = Path(env["PLOT_SESSION_STATE_DIR"])
        _until(lambda: any("workspace removed:" in p.read_text() for p in logs.glob("*.log")))
        assert not path.exists() and str(path) not in git(repo, "worktree", "list")
        assert worker.wait(timeout=30) is not None and neighbour.poll() is None
        assert _ps(int(Path(env["CHILD"]).read_text()), "stat=") in ("", "Z")
        assert "cleanup pending" in Path(env["OUT"]).read_text()
        assert all(p.stat().st_mode & 0o077 == 0 for p in logs.glob("*.log"))
    finally:
        _stop_owned(worker, neighbour, env)
