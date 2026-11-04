"""The marked session every test of the op runs in."""

import json
import os
from pathlib import Path
import subprocess

import pytest

from slopmeister.session import (
    browser_runtime,
    launch_identity,
    secret_approval,
    secret_run,
    secret_tier,
)
from slopmeister.session import browser_state as state
from tests.support.op_session import LISTS, ONE, TWO, private


@pytest.fixture
def session(monkeypatch, tmp_path):
    """A marked session on a machine with both tokens, every exec recorded and none run."""
    home = tmp_path / "home"
    files = home / secret_tier.DIRECTORY
    files.mkdir(parents=True)
    private(files / "tier-one.token", ONE + "\n")
    private(files / "tier-two.token", TWO + "\n")
    private(files / secret_tier.LISTS, json.dumps(LISTS))
    real = tmp_path / "real"
    real.mkdir()
    (real / "op").write_text("#!/bin/sh\n")
    (real / "op").chmod(0o755)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    workspace = tmp_path / "example-task"
    workspace.mkdir()
    launch_identity.write(
        workspace, (workspace.name, "claude", "00000000-0000-0000-0000-000000000001")
    )
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    for name, value in {
        "XDG_RUNTIME_DIR": str(runtime),
        secret_approval.WORKSPACE: str(workspace),
        secret_run.MARK: "1",
        "PATH": str(real),
    }.items():
        monkeypatch.setenv(name, value)
    for name in (secret_run.ROUTE, secret_run.INSIDE, secret_run.TOKEN):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("sys.argv", ["/elsewhere/op"])
    calls = []
    monkeypatch.setattr(os, "execve", lambda binary, argv, env: calls.append((argv, env)))
    monkeypatch.setattr(os, "execvpe", lambda name, argv, env: calls.append((argv, env)))
    # A test that reaches Home Assistant unasked fails loudly instead of waiting.
    monkeypatch.setattr(secret_approval, "ask", lambda *a: pytest.fail("asked Home Assistant"))
    return calls


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_runtime, "TEMP_ROOT", tmp_path)
    monkeypatch.setattr(state, "TEMP_ROOT", tmp_path)
    path = tmp_path / "slopmeister-browser-test"
    path.mkdir(mode=0o700)
    browser_runtime.save(path, {"worktree": str(tmp_path)})
    return path


@pytest.fixture
def tool(root, monkeypatch, tmp_path):
    """Record page tool calls instead of starting Node, with an installed entry present."""
    entry = tmp_path / "playwright-cli.js"
    entry.write_text("")
    monkeypatch.setattr(browser_runtime, "PAGE_ENTRY", entry)
    monkeypatch.setattr(browser_runtime, "node", lambda: tmp_path / "node")
    monkeypatch.setattr(browser_runtime, "request", lambda *_: {"result": "EMPTY"})
    calls = []
    replies = {}

    def run(argv, **options):
        calls.append((argv[2:], options))
        command = next((a for a in argv[2:] if not a.startswith("-")), "")
        code, output = replies.get(command, (0, "### Result\nok\n"))
        return subprocess.CompletedProcess(argv, code, output, "")

    monkeypatch.setattr(browser_runtime.subprocess, "run", run)
    return calls, replies


@pytest.fixture
def started(tool, tmp_path, monkeypatch):
    monkeypatch.setenv(browser_runtime.TOKEN, "dummy-private-token")
    monkeypatch.setenv(state.WORKSPACE, str(tmp_path))
    return tool
