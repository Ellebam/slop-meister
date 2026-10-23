"""Repository setup runs before delivery and owns only its unchanged output."""

import json
import os
from pathlib import Path
import sys

import pytest

from slopmeister.check import ownership
from slopmeister.errors import SlopmeisterError
from slopmeister.slots import allocation, setup
from tests.integration.slots.test_public_commands import _compose_world, _task, _world
from tests.support.repos import git

pytestmark = pytest.mark.xdist_group("slot-setup")


def configured(tmp_path, *, compose=False, failure=False):
    if compose:
        world, repository, env, _ = _compose_world(tmp_path)
    else:
        world, repository, env = _world(tmp_path)
    script = (
        "import os\nfrom pathlib import Path\nprint('setup diagnostics')\n"
        "lines = Path('.slot.env').read_text().splitlines()\n"
        "allocation = dict(line.split('=', 1) for line in lines)\n"
        "assert allocation['SLOT'] == os.environ['SLOT'] == '1'\n"
        "Path('.env.local').write_text('BACKEND_PORT=' + allocation['WEB'] + '\\n')\n"
        "Path('.hooks/generated').mkdir(parents=True)\n"
        "Path('.hooks/generated/hook').write_text('generated hook\\n')\n"
        + ("raise SystemExit(17)\n" if failure else "")
    )
    (repository / "prepare.py").write_text(script)
    (repository / ".gitignore").write_text(".env.local\n.hooks/generated/\nprivate.txt\n")
    git(repository, "add", "prepare.py", ".gitignore")
    git(repository, "commit", "-qm", "Add repository setup")
    plot = world.root / "plots/slopmeister/plot.toml"
    plot.write_text(
        plot.read_text().replace(
            "max = 2\n",
            'max = 2\nsetup = ["python3", "prepare.py"]\n'
            'setup_files = [".env.local", ".hooks/generated"]\n',
        )
    )
    return repository, env


def launch(repository, env):
    return _task(
        env,
        "slot:up",
        "--",
        str(repository),
        "slopmeister",
        "slopmeister-one",
        "--tool",
        "claude",
        input_text="Mode: freeform\nsetup fixture\n",
    )


def release(repository, env):
    return _task(env, "slot:down", "--", str(repository), "slopmeister", "slopmeister-one")


def test_setup_output_and_generated_hook_directory_are_removed_without_force(tmp_path):
    repository, env = configured(tmp_path, compose=True)
    result = launch(repository, env)
    assert result.returncode == 0, result.stdout + result.stderr
    worktree = repository / ".worktrees/slopmeister-one"
    assert (worktree / ".env.local").read_text().startswith("BACKEND_PORT=")
    cache = worktree / ".ruff_cache"
    cache.mkdir()
    (cache / ".gitignore").write_text("*\n")
    (cache / "CACHEDIR.TAG").write_text("disposable cache metadata\n")
    record = json.loads((Path(env["SLOT_STATE_DIR"]) / "slopmeister-slot1/setup.json").read_text())
    assert set(record) == {".env.local", ".hooks/generated/hook"}
    result = release(repository, env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not worktree.exists()
    assert not (Path(env["SLOT_STATE_DIR"]) / "slopmeister-slot1").exists()


@pytest.mark.parametrize(
    "name", [".env.local", ".hooks/generated/hook", ".hooks/generated/later", "private.txt"]
)
def test_teardown_preserves_worker_edits_and_unrelated_ignored_files(tmp_path, name):
    repository, env = configured(tmp_path)
    result = launch(repository, env)
    assert result.returncode == 0, result.stdout + result.stderr
    worktree = repository / ".worktrees/slopmeister-one"
    output = worktree / name
    before = output.read_bytes() if output.exists() else None
    output.write_text("worker work\n")
    result = release(repository, env)
    assert result.returncode != 0 and "ignored work" in result.stderr, result.stdout + result.stderr
    assert output.read_text() == "worker work\n"
    if before is None:
        output.unlink()
    else:
        output.write_bytes(before)
    result = release(repository, env)
    assert result.returncode == 0, result.stdout + result.stderr


def test_failed_setup_rolls_back_generated_files_claim_and_stack(tmp_path):
    repository, env = configured(tmp_path, compose=True, failure=True)
    result = launch(repository, env)
    assert result.returncode != 0 and "setup exited 17" in result.stderr, (
        result.stdout + result.stderr
    )
    assert not (repository / ".worktrees/slopmeister-one").exists()
    assert not (Path(env["SLOT_STATE_DIR"]) / "slopmeister-slot1").exists()
    assert not (tmp_path / "container").exists()
    assert not (tmp_path / "network").exists()


def test_failed_setup_keeps_private_diagnostics(tmp_path):
    repository, env = configured(tmp_path, failure=True)
    result = launch(repository, env)
    assert result.returncode != 0 and "setup exited 17" in result.stderr
    saved = list(Path(env["SLOT_STATE_DIR"]).glob("slopmeister-one.failed-*/setup.log"))
    assert len(saved) == 1 and saved[0].stat().st_mode & 0o777 == 0o600
    assert "setup diagnostics" in saved[0].read_text()


@pytest.mark.parametrize("recorded", [False, True])
@pytest.mark.parametrize(
    "name", ["node_modules/patched/index.js", "backend/dist/main.js", "tmp/proof.txt"]
)
@pytest.mark.parametrize(
    "flags",
    [("--skip-worktree",), ("--assume-unchanged",), ("--assume-unchanged", "--skip-worktree")],
)
def test_teardown_preserves_tracked_edits_beneath_ignored_cache(tmp_path, recorded, flags, name):
    repository, env = configured(tmp_path) if recorded else _world(tmp_path)[1:]
    original = repository / name
    original.parent.mkdir(parents=True)
    original.write_text("committed original\n")
    with (repository / ".gitignore").open("a") as stream:
        stream.write("node_modules/\nbackend/dist/\ntmp/\n")
    git(repository, "add", ".gitignore")
    git(repository, "add", "-f", name)
    git(repository, "commit", "-qm", "Track fixture cache file")
    result = launch(repository, env)
    assert result.returncode == 0, result.stdout + result.stderr
    worktree = repository / ".worktrees/slopmeister-one"
    for flag in flags:
        git(worktree, "update-index", flag, name)
    (worktree / name).write_text("worker edits\n")
    if name.startswith("tmp/"):
        proof = Path(env["PLOT_SESSION_STATE_DIR"]) / "slopmeister-one-proof/proof.txt"
        proof.parent.mkdir(parents=True)
        proof.write_bytes((worktree / name).read_bytes())
    assert git(worktree, "status", "--porcelain", "--untracked-files=all") == ""
    result = release(repository, env)
    assert result.returncode != 0 and "ignored work" in result.stderr, result.stdout + result.stderr
    assert name in result.stderr and (worktree / name).read_text() == "worker edits\n"
    assert (Path(env["SLOT_STATE_DIR"]) / "slopmeister-slot1/.slot.env").is_file()


@pytest.mark.parametrize("timeout", [False, True])
def test_setup_stops_its_children_on_exit_and_timeout(tmp_path, monkeypatch, timeout):
    data = tmp_path / "state"
    data.mkdir()
    claim = allocation.Claim(allocation.Live("scratch", 1, "scratch-one", tmp_path), data, None, {})
    child = tmp_path / "child.json"
    program = (
        "import json, os, subprocess, sys, time; from pathlib import Path; "
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "Path('child.json').write_text(json.dumps({'pid': p.pid, 'group': os.getpgrp()})); "
        + ("time.sleep(60)" if timeout else "sys.exit(0)")
    )
    monkeypatch.setattr(setup, "TIMEOUT", 2)
    if timeout:
        with pytest.raises(SlopmeisterError, match="setup exceeded 2 seconds"):
            setup._execute(claim, [sys.executable, "-c", program])
    else:
        setup._execute(claim, [sys.executable, "-c", program])
    recorded = json.loads(child.read_text())
    assert recorded["group"] != os.getpgrp()
    assert ownership.identity(recorded["pid"]) is None
