"""Disposable workspaces and a portable process census for the public removal command."""

import json
import os
from pathlib import Path
import stat
import subprocess

import pytest

from slopmeister.install.fileops import lock_service_actions
from slopmeister.removal import remove_tree
from slopmeister.session.verify import snapshot as delivery_snapshot
from tests.support.repos import GIT_ENV, git, scratch_repo

ROOT = Path(__file__).resolve().parents[3]


def _record_delivery(repo, worktree):
    state = repo / ".git/worktrees/scratch/slopmeister-config/state.json"
    state.parent.mkdir()
    state.write_text(
        json.dumps(
            {"worktree": str(worktree), "files": delivery_snapshot(worktree, [".claude", ".codex"])}
        )
    )


@pytest.fixture
def workspace(tmp_path):
    repo = scratch_repo(tmp_path / "main")
    git(repo, "worktree", "add", "-q", "-b", "scratch", ".worktrees/scratch")
    worktree = repo / ".worktrees/scratch"
    with (repo / ".git/info/exclude").open("a") as stream:
        stream.write(".claude\n.codex\n.slot.env\n")
    for native in (".claude", ".codex"):
        action = worktree / native / "service-actions/jira-read"
        action.mkdir(parents=True)
        (action / "entry.py").write_text("# fixture\n")
    lock_service_actions(worktree, True)
    _record_delivery(repo, worktree)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "ps").write_text("#!/bin/sh\nexit 0\n")
    (binaries / "ps").chmod(0o755)
    env = {**os.environ, **GIT_ENV, "PATH": f"{binaries}:{os.environ['PATH']}"}
    env.update(PLOT_SESSION_ROOT=str(tmp_path / "sessions"), SLOT_STATE_DIR=str(tmp_path / "slots"))
    try:
        yield repo, worktree, env
    finally:
        remove_tree(tmp_path)


@pytest.fixture
def invoke(workspace):
    _, _, env = workspace

    def run(path, *flags):
        return subprocess.run(
            [str(ROOT / "bin/slopmeister"), "workspace-remove", str(path), *flags],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    return run


@pytest.fixture
def snapshot():
    def read(root):
        result = {}
        for path in (root, *root.rglob("*")):
            mode = path.lstat().st_mode
            value = os.readlink(path) if stat.S_ISLNK(mode) else None
            if stat.S_ISREG(mode):
                value = path.read_bytes()
            result[str(path.relative_to(root))] = (mode, value)
        return result

    return read
