"""Real signals from closure reach only the test-owned predecessor, never its neighbour."""

import contextlib
import os
import signal
import subprocess
import sys
import time

import pytest

from slopmeister.launch import closure
from slopmeister.launch.model import Launch, Stop

REAL_RUN, REAL_KILL, REAL_SLEEP = subprocess.run, os.kill, time.sleep


def _sleeper(cwd, name: str, ignore_term: bool = False) -> subprocess.Popen:
    """A real sleep whose argv carries a session name; a trap set before exec survives it."""
    trap = "trap '' TERM; " if ignore_term else ""
    script = f"{trap}exec -a 'sleep --remote-control={name}' /bin/sleep 300"
    child = subprocess.Popen(["/bin/bash", "-c", script], cwd=cwd)
    for _ in range(100):
        argv = REAL_RUN(["ps", "-p", str(child.pid), "-o", "args="], capture_output=True, text=True)
        if "--remote-control" in argv.stdout:
            return child
        REAL_SLEEP(0.02)
    raise AssertionError("the sleeper never reached exec")


def _confine(monkeypatch, owned: dict[int, subprocess.Popen], parents=None, clients=None) -> None:
    """Only owned PIDs are listed or inspected, and with no handle file Orca is never reached."""

    def run(args, **kwargs):
        if args == ["ps", "-axo", "pid=,ppid="]:
            rows = "".join(f"{pid} {(parents or {}).get(pid, 1)}\n" for pid in owned)
            return subprocess.CompletedProcess(args, 0, rows, "")
        if args[:2] == ["ps", "-axo"]:
            rows = "".join(f"{pid} ?? /bin/claude\n" for pid in clients or owned)
            return subprocess.CompletedProcess(args, 0, rows, "")
        assert args[0] in ("ps", "lsof") and int(args[args.index("-p") + 1]) in owned, args
        return REAL_RUN(args, **kwargs)

    def kill(pid, sig):
        assert pid in owned, "a signal escaped test ownership"
        if sig == 0 and owned[pid].poll() is not None:
            raise ProcessLookupError(pid)  # this test, not a terminal, reaps these children
        REAL_KILL(pid, sig)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(closure.os, "kill", kill)
    monkeypatch.setattr(closure.time, "sleep", lambda seconds: REAL_SLEEP(0.05))


def _tree(worktree, marker):
    grandchild = "import time; time.sleep(300)"
    child = (
        "import subprocess,sys,time; "
        f"p=subprocess.Popen([sys.executable,'-c',{grandchild!r}]); "
        f"open({str(marker)!r},'a').write(str(p.pid)+'\\n'); time.sleep(300)"
    )
    root_code = (
        "import subprocess,sys,time; "
        f"p=subprocess.Popen([sys.executable,'-c',{child!r}]); "
        f"open({str(marker)!r},'w').write(str(p.pid)+'\\n'); time.sleep(300)"
    )
    root = subprocess.Popen(
        [sys.executable, "-c", root_code, "--remote-control=example-client-old"], cwd=worktree
    )
    deadline = time.monotonic() + 5
    while not marker.exists() or len(marker.read_text().splitlines()) < 2:
        assert time.monotonic() < deadline
        REAL_SLEEP(0.02)
    return root, tuple(map(int, marker.read_text().splitlines()))


def _stop_tree(root, neighbour, descendants):
    for pid in reversed(descendants):
        with contextlib.suppress(ProcessLookupError):
            REAL_KILL(pid, signal.SIGKILL)
    for process in (root, neighbour):
        if process.poll() is None:
            process.kill()
        process.wait()


@pytest.mark.xdist_group("launch-processes")
@pytest.mark.parametrize("ignores_term", [False, True], ids=["named", "timeout"])
def test_signals_reach_only_owned_processes(tmp_path, monkeypatch, ignores_term):
    """Bug: closure signals a same-prefix neighbour, or reports a surviving predecessor closed."""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("PLOT_SESSION_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "wt").mkdir()
    (tmp_path / "wt-other").mkdir()
    old = _sleeper(tmp_path / "wt", "example-client-old", ignores_term)
    neighbour = _sleeper(tmp_path / "wt-other", "example-client-old-2")
    owned = {old.pid: old, neighbour.pid: neighbour}
    try:
        _confine(monkeypatch, owned)
        launch = Launch("example-client", "example-client-old", "repo", claude_wt=tmp_path / "wt")
        if ignores_term:
            with pytest.raises(Stop, match=f"PID {old.pid} did not stop"):
                closure.close(launch)
            assert old.poll() is None
        else:
            closure.close(launch)
            assert old.wait(timeout=5) == -signal.SIGTERM
        assert neighbour.poll() is None
    finally:
        for child in owned.values():
            child.kill()
            child.wait()


def test_real_descendant_tree_is_closed_and_neighbour_survives(tmp_path, monkeypatch):
    """Bug: the client exited while its reparented child and grandchild survived."""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("PLOT_SESSION_STATE_DIR", str(tmp_path / "state"))
    worktree, other = tmp_path / "wt", tmp_path / "wt-other"
    worktree.mkdir()
    other.mkdir()
    marker = tmp_path / "pids"
    root, descendants = _tree(worktree, marker)
    neighbour = _sleeper(other, "example-client-other")
    child_pid, grandchild_pid = descendants
    owned = {root.pid: root, neighbour.pid: neighbour}
    owned.update({pid: root for pid in (child_pid, grandchild_pid)})
    parents = {root.pid: 1, child_pid: root.pid, grandchild_pid: child_pid, neighbour.pid: 1}
    try:
        _confine(monkeypatch, owned, parents, {root.pid, neighbour.pid})
        closure.close(Launch("example-client", "example-client-old", "repo", claude_wt=worktree))
        assert root.wait(timeout=5) == -signal.SIGTERM
        for pid in (child_pid, grandchild_pid):
            state = REAL_RUN(
                ["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True
            ).stdout.strip()
            assert not state or state.startswith("Z")
        assert neighbour.poll() is None
    finally:
        _stop_tree(root, neighbour, descendants)
