"""Compose readiness must precede worker delivery and preserve failed-start diagnostics."""

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from slopmeister.errors import SlopmeisterError
from slopmeister.slots import allocation, compose, up
from tests.unit.slots.test_commands import claim, request


def test_compose_runs_from_prepared_worktree_before_worker_launch(tmp_path, monkeypatch):
    """Bug: Compose started from the main checkout before the allocated worktree existed."""
    root, worktree = tmp_path / "repo", tmp_path / "repo/.worktrees/scratch-one"
    data = tmp_path / "scratch-slot1"
    data.mkdir(parents=True)
    (data / allocation.ALLOCATION).write_text("SLOT=1\n")
    item = claim(worktree, data)
    events = []

    def launch(argv, *, prepared, worktree_file):
        worktree.joinpath("docker").mkdir(parents=True)
        worktree.joinpath("docker/compose.yml").write_text("services: {}\n")
        worktree.joinpath(allocation.ALLOCATION).write_text(Path(worktree_file).read_text())
        events.append("prepared")
        prepared(SimpleNamespace(wt=worktree))
        events.append("worker")
        return 0, True

    monkeypatch.setattr(allocation, "definition", lambda target: {})
    monkeypatch.setattr(up.launch_cli, "run", launch)
    monkeypatch.setattr(
        allocation,
        "compose",
        lambda argv, **kwargs: (
            events.append(Path(argv[3]).resolve()) or subprocess.CompletedProcess(argv, 0)
        ),
    )
    assert up._handoff(request(), root, item) == (0, True)
    assert events == ["prepared", worktree.joinpath("docker/compose.yml").resolve(), "worker"]


def test_compose_wait_accepts_declared_one_shots_that_exit_zero(tmp_path, monkeypatch):
    """Bug: Compose --wait rejected a healthy stack because its initializer exited zero."""
    worktree = tmp_path / "worktree"
    compose = worktree / "docker/compose.yml"
    compose.parent.mkdir(parents=True)
    compose.write_text("services: {}\n")
    data = tmp_path / "scratch-slot1"
    data.mkdir()
    (data / allocation.ALLOCATION).write_text("SLOT=1\n")
    item = claim(worktree, data)

    def compose_call(argv, *, ok=True):
        if "up" in argv:
            assert ok is False
            return subprocess.CompletedProcess(argv, 1, "", "container init exited (0)\n")
        if "config" in argv:
            return subprocess.CompletedProcess(argv, 0, "api\ninit\n", "")
        rows = [
            {"Service": "api", "State": "running", "Health": "healthy", "ExitCode": 0},
            {"Service": "init", "State": "exited", "Health": "", "ExitCode": 0},
        ]
        return subprocess.CompletedProcess(argv, 0, "\n".join(map(json.dumps, rows)), "")

    monkeypatch.setattr(allocation, "compose", compose_call)
    up._compose_up(item)


def test_compose_wait_still_refuses_an_unhealthy_or_failed_service(monkeypatch):
    """Bug: the one-shot exception accepted a missing service or nonzero container exit."""
    rows = [
        {"Service": "api", "State": "running", "Health": "healthy", "ExitCode": 0},
        {"Service": "init", "State": "exited", "Health": "", "ExitCode": 1},
    ]

    def compose_call(argv, *, ok=True):
        output = "api\ninit\n" if "config" in argv else json.dumps(rows)
        return subprocess.CompletedProcess(argv, 0, output, "")

    monkeypatch.setattr(allocation, "compose", compose_call)
    with pytest.raises(SlopmeisterError, match="failed readiness"):
        compose._compose_ready(["-p", "scratch-slot1"])


def test_compose_failure_rolls_back_prepared_worktree_and_claim(tmp_path, monkeypatch):
    """Bug: an unhealthy prepared-worktree stack leaked its worktree and allocation claim."""
    root = tmp_path / "repo"
    worktree = root / ".worktrees/scratch-one"
    data = tmp_path / "scratch-slot1"
    data.mkdir()
    (data / allocation.ALLOCATION).write_text("SLOT=1\n")
    item = claim(worktree, data)
    removed = []

    def handoff(request, current, item):
        worktree.joinpath("docker").mkdir(parents=True)
        worktree.joinpath("docker/compose.yml").write_text("services: {}\n")
        raise SlopmeisterError("unhealthy")

    monkeypatch.setattr(up.target, "policy", lambda launch: None)
    monkeypatch.setattr(up, "_context", lambda request: ({}, root, worktree, ""))
    monkeypatch.setattr(up, "_claim", lambda request, slots, root: item)
    monkeypatch.setattr(up, "_handoff", handoff)
    monkeypatch.setattr(allocation, "remove_project", lambda project: removed.append(project) or [])
    monkeypatch.setattr(
        allocation,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, "", ""),
    )
    with pytest.raises(SlopmeisterError, match="unhealthy"):
        up.main(["/repo", "scratch", "scratch-one"])
    assert not data.exists() and not worktree.exists()
    assert removed == ["scratch-slot1"]
