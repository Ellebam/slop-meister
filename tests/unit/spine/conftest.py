"""A valid verdict, and a supervised run whose tester CLI, process group and home are fakes."""

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

import pytest

from slopmeister.spine import candidate
from slopmeister.spine.tester import runs

GROUP = 123456789


@pytest.fixture
def verdict(tmp_path: Path) -> dict:
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence/output.txt").write_text("actual command output\n")
    return {
        "scenarios": [
            {
                "id": "basic",
                "verdict": "pass",
                "evidence": [{"path": "evidence/output.txt", "quote": "actual command output"}],
            }
        ],
        "regressions": [],
    }


@dataclass
class World:
    """What the fake tester did and how the next call behaves."""

    tool: str
    session: str
    verdict: dict
    calls: list = field(default_factory=list)
    signals: list = field(default_factory=list)
    timeout: bool = False
    group_alive: bool = False
    returncode: int = 0
    prompt: str = ""
    event_text: str = ""
    newline: str = "\n"
    invalid_event: str = ""

    def events(self) -> list[dict]:
        if self.tool == "claude":
            return [
                {"type": "system", "subtype": "init", "session_id": self.session},
                {"type": "result", "is_error": False, "structured_output": self.verdict},
            ]
        return [{"type": "thread.started", "thread_id": self.session}, {"type": "turn.completed"}]

    def killpg(self, group: int, sig: int) -> None:
        assert group == GROUP, "cleanup targeted an unrelated process group"
        self.signals.append(sig)
        if sig == 0 and not self.group_alive:
            raise ProcessLookupError


class FakeProcess:
    pid = GROUP

    def __init__(self, world: World, command: list, options: dict) -> None:
        world.calls.append((command, options))
        self.world, self.returncode = world, None
        self.output = options["stdout"]
        self.root = Path(options["cwd"]).parent

    def communicate(self, prompt: str, timeout: float) -> None:
        world = self.world
        world.prompt = prompt
        for event in world.events():
            line = json.dumps({**event, "fixture_text": world.event_text}, ensure_ascii=False)
            self.output.write(line + world.newline)
        self.output.write(world.invalid_event)
        runs.save(self.root / "verdict.raw.json", world.verdict)
        self.output.flush()
        if world.timeout:
            raise subprocess.TimeoutExpired("fake-tester", timeout)
        self.returncode = world.returncode

    def wait(self, timeout: float) -> int:
        self.returncode = -15
        return self.returncode

    def poll(self) -> int | None:
        return self.returncode


@pytest.fixture(params=["claude", "codex"])
def supervised_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request) -> tuple:
    """Exercise the supervisor with fake events and native files, never an agent CLI."""
    verdict = request.getfixturevalue("verdict")
    root = tmp_path / "run"
    (root / "checkout").mkdir(parents=True)
    (root / "evidence").mkdir()
    (root / "evidence/output.txt").write_text("actual command output\n")
    world = World(request.param, str(uuid.uuid4()), verdict)
    run = _write_run(root, world.tool)
    native = _native_record(tmp_path / "fake-home", world)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "fake-home"))
    monkeypatch.setattr(runs, "git", lambda cwd, *args: _head(run, args))
    monkeypatch.setattr(candidate, "unchanged", lambda checkout, tree: True)
    monkeypatch.setattr(subprocess, "Popen", lambda command, **kw: FakeProcess(world, command, kw))
    monkeypatch.setattr(os, "killpg", world.killpg)
    return root, world, native


def _head(run: dict, args: tuple) -> str:
    return run["commit"] if args == ("rev-parse", "HEAD") else ""


def _write_run(root: Path, tool: str) -> dict:
    run = {
        "tool": tool, "model": "fake-model", "effort": "high", "commit": "a" * 40,
        "checkout": str(root / "checkout"), "required": ["basic"], "command": ["fake-tester"],
    }  # fmt: skip
    for name in ("guide.md", "validation.md"):
        (root / name).write_text("Approved fixture inputs")
    run["input_hashes"] = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in ("guide.md", "validation.md")
    }
    runs.save(root / "run.json", run)
    return run


def _native_record(home: Path, world: World) -> Path:
    folder = ".claude/projects/fixture" if world.tool == "claude" else ".codex/sessions/2026/09/09"
    native = home / folder / f"{world.session}.jsonl"
    native.parent.mkdir(parents=True)
    identity = (
        {"message": {"model": "fake-model"}, "effort": "high"}
        if world.tool == "claude"
        else {"type": "turn_context", "payload": {"model": "fake-model", "effort": "high"}}
    )
    native.write_text(json.dumps(identity) + "\n")
    return native
