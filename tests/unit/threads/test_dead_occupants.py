"""A killed worker its parent has not collected yet is no occupant."""

import subprocess

import pytest

from slopmeister.threads import occupants

PID = 101


def _run(state):
    def run(args):
        def done(code, out):
            return subprocess.CompletedProcess(args, code, out, "")

        if args[:2] == ["ps", "-axo"]:
            return done(0, f"{PID} ? claude\n")
        if args[0] == "lsof":
            return done(1, "")
        if args[-1] == "stat=":
            return done(0, state + "\n")
        return done(0, "[claude] <defunct>\n" if args[-1] == "args=" else "Mon Jan 1 claude\n")

    return run


def test_a_killed_worker_not_yet_collected_is_no_occupant(monkeypatch):
    """Bug: Linux lists a dead worker under its name, so a worker could not release its own slot."""
    monkeypatch.setattr(occupants, "run", _run("Z"))
    monkeypatch.setattr(occupants.os, "kill", lambda pid, signal: None)
    assert occupants.processes("/work", None) == []


@pytest.mark.parametrize("state", ["S", ""])
def test_a_live_worker_without_a_readable_directory_still_stops_the_census(monkeypatch, state):
    """Bug: a worker whose directory or process row cannot be read counts as absent and loses
    its worktree."""
    monkeypatch.setattr(occupants, "run", _run(state))
    monkeypatch.setattr(occupants.os, "kill", lambda pid, signal: None)
    with pytest.raises(occupants.CensusError, match="PID 101"):
        occupants.processes("/work", None)


def test_a_process_collected_during_its_inspection_is_no_occupant(monkeypatch):
    """Bug: an agent process anywhere on the host ends and is collected between the liveness
    probe and its process row, the empty row reads as alive, and an unrelated workspace removal
    refuses."""
    collected = []

    def run(args):
        if args[-1] == "stat=":
            collected.append(True)
        return _run("")(args)

    def kill(pid, signal):
        if collected:
            raise ProcessLookupError

    monkeypatch.setattr(occupants, "run", run)
    monkeypatch.setattr(occupants.os, "kill", kill)
    assert occupants.processes("/work", None) == []
