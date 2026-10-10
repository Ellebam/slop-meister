"""Slot commands retain the old allocation and rollback boundaries."""

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from slopmeister.errors import SlopmeisterError
from slopmeister.slots import allocation, status, up


def request(*, wanted: str = "") -> up.Request:
    return up.Request("/repo", "scratch", "scratch-one", wanted, [])


def claim(worktree: Path, data: Path, *, compose=True) -> allocation.Claim:
    live = allocation.Live("scratch", 1, "scratch-one", worktree)
    manifest = worktree / "docker/compose.yml" if compose else None
    return allocation.Claim(live, data, manifest, {})


def test_lowest_free_slot_skips_live_and_residual_claims(tmp_path, monkeypatch):
    """Bug: an automatic allocation reused a live slot or residue instead of the lowest free one."""
    monkeypatch.setenv("SLOT_STATE_DIR", str(tmp_path))
    (tmp_path / "scratch-slot2").mkdir()
    live = allocation.Live("scratch", 1, "scratch-live", Path("/worktree"))
    monkeypatch.setattr(allocation, "live", lambda root: [live])
    assert up._available(request(), Path("/repo"), {"max": 3}) == 3


def test_bound_port_refuses_before_claiming_state(tmp_path, monkeypatch):
    """Bug: a foreign listener was accepted and the failed attempt left slot residue."""
    monkeypatch.setenv("SLOT_STATE_DIR", str(tmp_path / "slots"))
    monkeypatch.setattr(up, "_available", lambda request, root, slots: 1)
    monkeypatch.setattr(
        allocation, "bound_ports", lambda: [allocation.Listener(4001, 72, "python")]
    )
    with pytest.raises(SlopmeisterError, match=r"port 4001.*pid 72"):
        up._claim(request(), {"ports": {"WEB": 4000}}, tmp_path / "repo")
    assert not (tmp_path / "slots").exists()


def test_existing_compose_resource_refuses_before_claiming_state(tmp_path, monkeypatch):
    """Bug: a new allocation silently adopted and later deleted stale Docker resources."""
    monkeypatch.setenv("SLOT_STATE_DIR", str(tmp_path / "slots"))
    monkeypatch.setattr(up, "_available", lambda request, root, slots: 1)
    monkeypatch.setattr(allocation, "bound_ports", lambda: [])
    monkeypatch.setattr(allocation, "resolve_compose", lambda root, relative: root / relative)
    monkeypatch.setattr(
        allocation,
        "project_resources",
        lambda project: (allocation.Resource("container", "c1", "stale-api"),),
    )
    with pytest.raises(SlopmeisterError, match=r"stale-api.*scratch-slot1"):
        up._claim(request(), {"compose": "docker/compose.yml"}, tmp_path / "repo")
    monkeypatch.setattr(allocation, "project_resources", lambda project: None)
    with pytest.raises(SlopmeisterError, match="Docker is unavailable"):
        up._claim(request(), {"compose": "docker/compose.yml"}, tmp_path / "repo")
    assert not (tmp_path / "slots").exists()


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
    assert up._compose_ready(["-p", "scratch-slot1"]) is False


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


def test_launcher_failure_keeps_claim_after_handoff_begins(tmp_path, monkeypatch, capsys):
    """Bug: a failed launcher removed resources from under a worker that might already be live."""
    data = tmp_path / "scratch-slot1"
    data.mkdir()
    (data / allocation.ALLOCATION).write_text("SLOT=1\n")
    item = claim(tmp_path / "worktree", data, compose=False)
    monkeypatch.setattr(up, "_context", lambda request: ({}, tmp_path, tmp_path / "worktree", ""))
    monkeypatch.setattr(up, "_claim", lambda request, slots, root: item)
    monkeypatch.setattr(up, "_handoff", lambda request, root, claim: (1, True))
    assert up.main(["/repo", "scratch", "scratch-one"]) == 1
    assert data.is_dir() and "may be live" in capsys.readouterr().err


def test_launcher_failure_before_open_rolls_back_claim(tmp_path, monkeypatch):
    """Bug: a validation or preflight refusal left a claim even though no worker could be live."""
    data = tmp_path / "scratch-slot1"
    data.mkdir()
    (data / allocation.ALLOCATION).write_text("SLOT=1\n")
    item = claim(tmp_path / "worktree", data, compose=False)
    monkeypatch.setattr(up, "_context", lambda request: ({}, tmp_path, tmp_path / "worktree", ""))
    monkeypatch.setattr(up, "_claim", lambda request, slots, root: item)
    monkeypatch.setattr(up, "_handoff", lambda request, root, claim: (1, False))
    assert up.main(["/repo", "scratch", "scratch-one"]) == 1
    assert not data.exists()


def test_status_attributes_expected_and_stray_listeners_to_the_slot(tmp_path, monkeypatch, capsys):
    """Bug: status hid an unexpected listener or assigned it to a neighboring worktree."""
    root = tmp_path / "repo"
    worktree = root / ".worktrees/scratch-one"
    current = allocation.Live("scratch", 1, "scratch-one", worktree)
    monkeypatch.setattr(allocation, "main_root", lambda repo: root)
    monkeypatch.setattr(allocation, "live", lambda root: [current])
    monkeypatch.setattr(allocation, "definition", lambda target: {"ports": {"WEB": 4000}})
    monkeypatch.setattr(
        allocation,
        "bound_ports",
        lambda: [allocation.Listener(4001, 41, "python"), allocation.Listener(4999, 42, "node")],
    )
    monkeypatch.setattr(allocation, "project_resources", lambda project: ())
    monkeypatch.setattr(status, "_working_directories", lambda pids: {41: worktree, 42: worktree})
    monkeypatch.setattr(status, "_workers", lambda current: None)
    status.live(str(root))
    output = capsys.readouterr().out
    assert "listener 4001 pid 41 python\n" in output
    assert "listener 4999 pid 42 node stray\n" in output


def test_status_attributes_exact_compose_resources_to_each_slot(tmp_path, monkeypatch, capsys):
    """Bug: status reported only 'compose up' and hid which resources belonged to the slot."""
    root = tmp_path / "repo"
    current = allocation.Live("scratch", 2, "scratch-two", root / ".worktrees/scratch-two")
    monkeypatch.setattr(allocation, "main_root", lambda repo: root)
    monkeypatch.setattr(allocation, "live", lambda root: [current])
    monkeypatch.setattr(
        allocation,
        "definition",
        lambda target: {"compose": "docker/compose.yml", "ports": {"WEB": 4000}},
    )
    monkeypatch.setattr(allocation, "bound_ports", lambda: [])
    monkeypatch.setattr(status, "_working_directories", lambda pids: {})
    monkeypatch.setattr(status, "_workers", lambda current: None)
    monkeypatch.setattr(
        allocation,
        "project_resources",
        lambda project: (
            allocation.Resource("container", "c1", "scratch-api", "Up 5 seconds"),
            allocation.Resource("network", "n1", "scratch-default"),
        ),
    )
    status.live(str(root))
    output = capsys.readouterr().out
    assert "scratch-two slot 2 scratch WEB=4002 compose up" in output
    assert "scratch-two container scratch-api Up 5 seconds" in output
    assert "scratch-two network scratch-default" in output
