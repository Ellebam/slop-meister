"""A standalone Codex launch is credited only for its new process in the workspace."""

from pathlib import Path
import subprocess

from slopmeister.launch import confirm
from slopmeister.launch.model import Launch


def test_codex_pid_ignores_existing_and_sibling_processes(monkeypatch):
    """Bug: delivery either misses standalone Codex or credits a different worker."""
    launch = Launch("example-client", "example-client-worker", "repo", tool="codex")
    launch.wt = Path("/repo/.worktrees/example-client-worker")
    launch.codex_baseline = {100}
    seen = []

    def pgrep(pattern):
        seen.append(pattern)
        return [100, 101, 102] if pattern == "codex --no-daemon" else []

    def run(args, **_):
        pid = int(args[-1])
        root = launch.wt if pid != 102 else Path("/repo/.worktrees/example-client-other")
        return subprocess.CompletedProcess(args, 0, f"codex --no-daemon -C {root} -- prompt\n", "")

    monkeypatch.setattr(confirm, "_pgrep", pgrep)
    monkeypatch.setattr(confirm.subprocess, "run", run)
    assert confirm._pids(launch) == [101]
    assert seen == ["codex --no-daemon"]
