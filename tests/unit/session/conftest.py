"""The marked session every test of the op runs in."""

import json
import os
from pathlib import Path

import pytest

from slopmeister.session import secret_approval, secret_run, secret_tier
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
    monkeypatch.setenv(secret_run.MARK, "1")
    monkeypatch.setenv("PATH", str(real))
    for name in (secret_run.ROUTE, secret_run.INSIDE, secret_run.TOKEN):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("sys.argv", ["/elsewhere/op"])
    calls = []
    monkeypatch.setattr(os, "execve", lambda binary, argv, env: calls.append((argv, env)))
    monkeypatch.setattr(os, "execvpe", lambda name, argv, env: calls.append((argv, env)))
    # A test that reaches Home Assistant unasked fails loudly instead of waiting.
    monkeypatch.setattr(secret_approval, "ask", lambda *a: pytest.fail("asked Home Assistant"))
    return calls
