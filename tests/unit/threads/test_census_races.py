"""The census reads any number of agents in five programs, and a PID that changes hands
between those reads is never reported as the process it was, so closure never signals it."""

import subprocess

import pytest

from slopmeister.threads import occupants

AGENTS = range(101, 141)
STARTED = "Mon Sep  7 10:00:00 2026 claude"
# A forked agent child carries the agent's name until it starts its own program.
EXECUTED = "Mon Sep  7 10:00:00 2026 /bin/sleep"
# macOS shows a process it cannot read the arguments of, while it starts a program or exits.
UNREADABLE = "Mon Sep  7 10:00:00 2026 (claude)"
STRANGER = "Mon Sep  7 10:00:09 2026 claude"
GONE = None
# The identity of PID 101 at each identity read, two reads per census pass, the last one repeats.
EVENTS = {
    "stays": [STARTED],
    "exits": [STARTED, GONE],
    "execs": [STARTED, EXECUTED],
    "unreadable": [STARTED, UNREADABLE, STARTED],
    "replaced": [STARTED, STRANGER],
    "churns": [STARTED, UNREADABLE, STARTED, UNREADABLE, STARTED, UNREADABLE],
}
PASS_CALLS = 5


def _host(event, calls):
    """PID 101 follows its event's identities, one per identity read."""
    readings = EVENTS[event]
    identity_reads = []

    def current():
        return readings[min(len(identity_reads), len(readings) - 1)]

    def run(args):
        calls.append(args)
        if args[:3] == ["ps", "-ww", "-axo"]:
            return _done(args, "".join(f"{pid} ?? /opt/bin/claude\n" for pid in AGENTS))
        pids = [int(pid) for pid in args[args.index("-p") + 1].split(",")]
        listed = [pid for pid in pids if pid != 101 or current() is not GONE]
        if args[0] == "lsof":
            output = "".join(f"p{pid}\nfcwd\nn/work\n" for pid in listed)
        elif args[-1] == "pid=,args=":
            output = "".join(f"{pid} claude\n" for pid in listed)
        else:
            rows = [f"{pid} S {current() if pid == 101 else STARTED}\n" for pid in listed]
            identity_reads.append(True)
            output = "".join(rows)
        return _done(args, output)

    def kill(pid, signal):
        if pid == 101 and current() is GONE:
            raise ProcessLookupError(pid)

    return run, kill


def _done(args, output):
    return subprocess.CompletedProcess(args, 0, output, "")


@pytest.mark.parametrize(
    ("event", "survivor", "passes"),
    [
        ("stays", STARTED, 1),
        ("exits", None, 1),
        ("execs", None, 1),
        ("unreadable", STARTED, 2),
        ("replaced", STRANGER, 2),
    ],
)
def test_a_pid_that_changes_hands_between_reads_is_never_reported(
    monkeypatch, event, survivor, passes
):
    """Bug: the census ran three programs per agent and outlasted test limits on a busy host,
    and a batched read must not pair one process's identity with another's directory. On macOS a
    forked agent child that started its own program between the reads stopped every census, and
    a process macOS briefly showed as "(claude)" stopped a session's own removal."""
    calls = []
    run, kill = _host(event, calls)
    monkeypatch.setattr(occupants, "run", run)
    monkeypatch.setattr(occupants.os, "kill", kill)
    monkeypatch.setattr(occupants.os.path, "realpath", lambda path: path)
    found = {process.pid: process.signature for process in occupants.processes("/work", None)}
    expected = dict.fromkeys((pid for pid in AGENTS if pid != 101), STARTED)
    if survivor:
        expected[101] = survivor
    assert found == expected
    assert len(calls) == PASS_CALLS * passes


def test_a_pid_that_keeps_changing_stops_the_census(monkeypatch):
    """A PID whose identity changes in every pass may hide an agent, so absence is unproven."""
    calls = []
    run, kill = _host("churns", calls)
    monkeypatch.setattr(occupants, "run", run)
    monkeypatch.setattr(occupants.os, "kill", kill)
    monkeypatch.setattr(occupants.os.path, "realpath", lambda path: path)
    with pytest.raises(occupants.CensusError, match=r"PID 101 changed identity.*\(claude\)"):
        occupants.processes("/work", None)
    assert len(calls) == PASS_CALLS * occupants.CENSUS_PASSES
