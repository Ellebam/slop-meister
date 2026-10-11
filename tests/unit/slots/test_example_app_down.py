"""Self-cleanup releases a slot only for the worker that runs the command."""

import os
from pathlib import Path
import subprocess

import pytest

from slopmeister.errors import SlopmeisterError
from slopmeister.launch.model import Stop
from slopmeister.slots import allocation, down
from slopmeister.threads import occupants
from tests.unit.slots.test_allocation import slot_identity

ME = os.getpid()


def _worker(pid: int, inside: bool = True) -> occupants.Process:
    return occupants.Process(pid, "claude", "??", "started", f"/work/{pid}", inside, False)


def _machine(monkeypatch, workers, parents) -> None:
    monkeypatch.setattr(occupants, "census", lambda worktree: workers)
    monkeypatch.setattr(down, "_parents", lambda: parents)


def test_example_app_accepts_the_worker_that_runs_the_command(tmp_path, monkeypatch):
    """Bug: an authorized session could not release its own slot."""
    _machine(monkeypatch, [_worker(50)], {ME: 60, 60: 50, 50: 1})
    down._calling_worker(tmp_path, "scratch-slot1")


@pytest.mark.parametrize(
    ("workers", "parents", "named"),
    [
        ([_worker(50)], {ME: 60, 60: 1}, "pid 50"),
        ([_worker(50), _worker(55, inside=False)], {ME: 55, 55: 50, 50: 1}, "pid 50"),
        ([_worker(50), _worker(51)], {ME: 50, 50: 1}, "pid 51"),
        ([], {ME: 1}, "no occupant"),
    ],
    ids=["foreign-caller", "nested-worker", "second-occupant", "nobody"],
)
def test_example_app_refuses_any_caller_but_the_sole_occupant(monkeypatch, workers, parents, named):
    """Bug: a foreign session or a reviewer child stopped and deleted another session's slot."""
    _machine(monkeypatch, workers, parents)
    with pytest.raises(SlopmeisterError, match="--self requires") as refusal:
        down._calling_worker(Path("/work/50"), "scratch-slot1")
    assert named in str(refusal.value)


def test_example_app_refuses_when_the_census_fails(tmp_path, monkeypatch):
    """Bug: an inspection that could not complete was read as an empty worktree."""

    def broken(worktree):
        raise occupants.CensusError("cannot complete ps inspection")

    monkeypatch.setattr(occupants, "census", broken)
    with pytest.raises(SlopmeisterError, match="cannot tell whether a worker occupies") as refusal:
        down._calling_worker(tmp_path, "scratch-slot1")
    assert "cannot complete ps inspection, run this command outside" in str(refusal.value)


def _slot(tmp_path, monkeypatch, status: str) -> list[str]:
    """A scratch slot whose caller is its worker, with every later step recorded."""
    slot_identity(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(allocation, "definition", lambda target: {"ports": {"WEB": 4000}})
    monkeypatch.setattr(allocation, "main_root", lambda repo: tmp_path / "repo")
    monkeypatch.setattr(down, "_calling_worker", lambda worktree, project: None)
    steps: list[str] = []

    def run(argv, **kwargs):
        steps.append(" ".join(argv[3:5]) if argv[0] == "git" else "occupants")
        return subprocess.CompletedProcess(argv, 0, status if "status" in argv else "", "")

    monkeypatch.setattr(allocation, "run", run)
    return steps


ARGV = ["repo", "scratch", "scratch-one", "--self"]


def test_example_app_refuses_dirty_work_before_anything_is_stopped(tmp_path, monkeypatch):
    """Bug: the worker was stopped, then teardown refused its uncommitted work."""
    _slot(tmp_path, monkeypatch, "?? local.txt\n")
    monkeypatch.setattr(down, "_detach", lambda log: pytest.fail("forked before the refusal"))
    with pytest.raises(SlopmeisterError, match="uncommitted work"):
        down.main(ARGV)


def test_invoking_command_returns_and_names_the_log(tmp_path, monkeypatch, capsys):
    """Bug: the worker waited on its own teardown, or never learned where the result is."""
    steps = _slot(tmp_path, monkeypatch, "")
    monkeypatch.setattr(down, "_detach", lambda log: False)
    assert down.main(ARGV) == 0
    assert str(tmp_path / "slots/scratch-one.down.log") in capsys.readouterr().out
    assert "worktree remove" not in steps and (tmp_path / "slots/scratch-slot1").is_dir()


def test_surviving_process_stops_the_worker_then_tears_down_under_the_guard(tmp_path, monkeypatch):
    """Bug: teardown ran before the worker stopped, or skipped the ordinary occupancy guard."""
    steps = _slot(tmp_path, monkeypatch, "")
    monkeypatch.setattr(down, "_detach", lambda log: True)
    monkeypatch.setattr(down.closure, "close", lambda launch: steps.append(f"close {launch.name}"))
    assert down.main(ARGV) == 0
    assert (
        steps.index("close scratch-one") < steps.index("occupants") < steps.index("worktree remove")
    )
    assert not (tmp_path / "slots/scratch-slot1").exists()


def test_failed_shutdown_leaves_the_slot_untouched(tmp_path, monkeypatch):
    """Bug: teardown deleted the worktree under a worker that did not stop."""
    steps = _slot(tmp_path, monkeypatch, "")
    monkeypatch.setattr(down, "_detach", lambda log: True)

    def refuse(launch):
        raise Stop(1, "captured PID 50 did not stop")

    monkeypatch.setattr(down.closure, "close", refuse)
    with pytest.raises(SlopmeisterError, match="did not stop"):
        down.main(ARGV)
    assert "worktree remove" not in steps and (tmp_path / "slots/scratch-slot1").is_dir()
