"""A scratch process table and Orca terminal list."""

from dataclasses import dataclass, field
from pathlib import Path
import signal
import subprocess

from slopmeister.launch import closure
from slopmeister.launch.model import Launch


@dataclass
class Box:
    """The process table and terminal inventory a closure observes, faults included."""

    wt: Path
    fault: str
    alive: dict[int, tuple[str, str, bool]] = field(default_factory=dict)
    terminals: dict[str, str] = field(default_factory=dict)
    parents: dict[int, int] = field(default_factory=dict)
    unsignallable: set[int] = field(default_factory=set)
    signals: list[int] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    states: dict[int, str] = field(default_factory=dict)
    identities: int = 0
    censuses: int = 0
    clock: float = 0

    def run(self, args, **_):
        handler = {"ps": self.ps, "lsof": self.lsof}.get(args[0])
        if handler is None:
            raise AssertionError(args)
        code, out = handler(args)
        return subprocess.CompletedProcess(args, code, out, "")

    def ps(self, args):
        if args == ["ps", "-axo", "pid=,ppid="]:
            rows = "".join(f"{pid} {self.parents.get(pid, 1)}\n" for pid in self.alive)
            result = 0, rows
        elif "-axo" in args:
            self.censuses += 1
            rows = "".join(f"{pid} ttys001 /bin/{kind}\n" for pid, (kind, *_) in self.alive.items())
            result = (1, "") if self.fault == "ps" else (0, rows)
        else:
            result = self.process(args)
        return result

    def process(self, args):
        """One PID answers bare, a census list answers each living PID on a row led by its PID."""
        columns, listed = args[args.index("-o") + 1], args[args.index("-p") + 1]
        fields, batched = columns.removeprefix("pid="), columns.startswith("pid=")
        rows = [
            (pid, self.row(pid, fields.lstrip(","), batched)) for pid in map(int, listed.split(","))
        ]
        lines = [f"{pid} {row}" if batched else row for pid, row in rows if row is not None]
        return (0 if lines else 1), "".join(line + "\n" for line in lines)

    def row(self, pid, fields, batched):
        if pid not in self.alive:
            return None
        if fields == "args=":
            return "agent --remote-control=example-client-old" if self.alive[pid][2] else "agent"
        # Census reads leave this count to closure's own identity checks.
        self.identities += not batched
        if self.fault == "reparent" and pid == 4001 and self.identities > 1:
            self.alive.pop(4000, None)
            self.parents[4001] = 1
        stale = self.fault == "identity" and self.censuses > 1
        identity = "changed" if stale else "Mon Sep  7 10:00:00 2026 agent"
        return f"{self.states.get(pid, 'S')} {identity}"

    def lsof(self, args):
        if self.fault == "lsof":
            return 1, ""
        pids = [pid for pid in map(int, args[3].split(",")) if pid in self.alive]
        return 0, "".join(f"p{pid}\nn{self.alive[pid][1]}\n" for pid in pids)

    def listing(self, **_):
        return None if self.fault == "orca-down" else dict(self.terminals)

    def close_terminal(self, handle, **_):
        assert handle == "old-terminal", "closed an unrelated terminal"
        self.events.append("close")
        if self.fault != "close":
            del self.terminals[handle]

    def sleep(self, seconds):
        self.clock += seconds
        self.events.append("sleep")

    def kill(self, pid, sig):
        assert pid in self.alive or sig == 0, "a signal escaped the workspace"
        if self.fault == "late-permission" and sig == signal.SIGTERM:
            raise PermissionError(pid)
        if pid in self.unsignallable:
            raise PermissionError(pid)
        if pid not in self.alive:
            raise ProcessLookupError(pid)
        if sig == signal.SIGTERM:
            self.signals.append(pid)
            self.events.append("term")
            if self.fault == "uninterruptible-after-term":
                self.states[pid] = "U"
            elif self.fault != "ignore-term":
                del self.alive[pid]


def make_box(tmp_path, monkeypatch, row) -> Box:
    processes, terminal, fault = row
    box = Box(tmp_path / "wt", fault)
    for pid, (kind, where, named) in enumerate(processes, 4000):
        box.alive[pid] = (kind, str(box.wt / where), named)
    box.terminals = {"other": str(tmp_path / "elsewhere")}
    monkeypatch.setenv("PLOT_SESSION_STATE_DIR", str(tmp_path / "state"))
    if terminal:
        box.terminals["old-terminal"] = str(box.wt)
        (tmp_path / "state").mkdir()
        (tmp_path / "state/example-client-old.orca").write_text("old-terminal\n")
    executable = tmp_path / "home/.local/bin/codex"
    executable.parent.mkdir(parents=True)
    executable.touch(mode=0o755)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setattr(subprocess, "run", box.run)
    monkeypatch.setattr(closure.os, "kill", box.kill)
    monkeypatch.setattr(closure.time, "sleep", box.sleep)
    monkeypatch.setattr(closure.time, "monotonic", lambda: box.clock)
    monkeypatch.setattr(closure.terminal, "ready", lambda: box.fault != "orca-down")
    monkeypatch.setattr(closure.terminal, "terminals", box.listing)
    monkeypatch.setattr(closure.terminal, "close", box.close_terminal)
    return box


def box_launch(box: Box) -> Launch:
    return Launch("example-client", "example-client-old", "repo", claude_wt=box.wt, wt=box.wt)
