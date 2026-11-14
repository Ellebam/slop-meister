"""Self-cleanup releases a slot only for the worker that runs the command."""

import os
from pathlib import Path

import pytest

from slopmeister.errors import SlopmeisterError, UsageError
from slopmeister.slots import down
from slopmeister.threads import occupants

ME = os.getpid()


def test_slot_release_no_longer_accepts_a_separate_self_shutdown():
    """Live-worker shutdown belongs to workspace removal, before ordinary slot release."""
    with pytest.raises(UsageError, match="usage: slopmeister slots down"):
        down.parse(["repo", "scratch", "scratch-one", "--self"])


def _worker(pid: int, inside: bool = True) -> occupants.Process:
    return occupants.Process(pid, "claude", "??", "started", f"/work/{pid}", inside, False)


def _machine(monkeypatch, workers, parents) -> None:
    monkeypatch.setattr(occupants, "census", lambda worktree: workers)
    monkeypatch.setattr(down, "_parents", lambda: parents)


def test_example_app_accepts_the_worker_that_runs_the_command(tmp_path, monkeypatch):
    """Bug: an authorized session could not release its own slot."""
    _machine(monkeypatch, [_worker(50)], {ME: 60, 60: 50, 50: 1})
    assert down._calling_worker(tmp_path, "scratch-slot1") == _worker(50)


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


@pytest.fixture
def report_input(tmp_path, monkeypatch):
    path = tmp_path / "report"
    path.write_bytes(b"Task unfinished.\nKeep the draft.\nNext action: finish it.\n")
    with path.open("rb") as source:
        monkeypatch.setattr(down.sys, "stdin", source)
        yield path


@pytest.mark.parametrize(
    ("data", "diagnostic"),
    [
        (b"", "nonempty harvest report"),
        (b" \t\n", "nonempty harvest report"),
        (b"\xff", "utf-8"),
        (b"\x1b[8mhidden report", "terminal control"),
        (b"x" * (down.REPORT_BYTES + 1), "exceeds"),
    ],
)
def test_invalid_report_cannot_reach_fork(tmp_path, monkeypatch, report_input, data, diagnostic):
    report_input.write_bytes(data)
    monkeypatch.setattr(down.os, "fork", lambda: pytest.fail("forked without a valid report"))
    log = tmp_path / "result.log"
    with pytest.raises(SlopmeisterError, match=diagnostic):
        down._detach(log)
    assert not log.exists()


def test_report_is_visible_and_private_before_fork(tmp_path, monkeypatch, report_input, capsys):
    log = tmp_path / "result.log"
    log.write_text("old result\n")
    log.chmod(0o644)
    report_input.write_bytes(b"Keep $(false), $HOME and 'quotes' literal.\nNext: finish.\n")

    def fork():
        assert log.read_bytes() == report_input.read_bytes()
        assert capsys.readouterr().out.encode() == report_input.read_bytes()
        assert log.stat().st_mode & 0o077 == 0
        return 10

    monkeypatch.setattr(down.os, "fork", fork)
    assert down._detach(log) is False


@pytest.mark.parametrize("failure", ["log", "output"])
def test_failed_report_delivery_never_forks(tmp_path, monkeypatch, report_input, failure):
    log = tmp_path / "result.log"
    monkeypatch.setattr(down.os, "fork", lambda: pytest.fail("forked after report failure"))
    if failure == "log":
        log.symlink_to(report_input)
    else:

        def broken_output(*args, **kwargs):
            raise BrokenPipeError("display unavailable")

        monkeypatch.setattr("builtins.print", broken_output)
    with pytest.raises(SlopmeisterError, match="report delivery failed, worker not stopped"):
        down._detach(log)
    assert report_input.read_bytes().startswith(b"Task unfinished.")


def test_unclosed_report_input_refuses_before_fork(tmp_path, monkeypatch):
    reader, writer = os.pipe()
    try:
        with os.fdopen(reader, "rb") as source:
            monkeypatch.setattr(down.sys, "stdin", source)
            monkeypatch.setattr(down, "REPORT_TIMEOUT", 0.01)
            monkeypatch.setattr(down.os, "fork", lambda: pytest.fail("forked with open input"))
            os.write(writer, b"a report without EOF")
            with pytest.raises(SlopmeisterError, match="input did not close"):
                down._detach(tmp_path / "result.log")
    finally:
        os.close(writer)
