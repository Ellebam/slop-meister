"""Noncanonical write invocations cannot reach the credential boundary."""

import json
import sys

import pytest

from slopmeister.session.service_actions import supervisor
from slopmeister.session.service_actions.constants import PYTHON, PYTHON_FLAGS


@pytest.fixture
def writer(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "executable", str(PYTHON))
    monkeypatch.setattr(supervisor, "ROOT", tmp_path)
    monkeypatch.setattr(supervisor.runtime, "require", lambda **_kwargs: None)
    monkeypatch.setattr(supervisor, "operation", lambda *_args: {})
    (tmp_path / "config.json").write_text(json.dumps({"action": "jira-write", "native": False}))

    def credentials(_data):
        raise ValueError("REACHED_CREDENTIAL_BOUNDARY")

    monkeypatch.setattr(supervisor, "_environment", credentials)
    return tmp_path


@pytest.mark.parametrize("direct", [False, True])
@pytest.mark.parametrize("variant", ["omitted", "reordered", "combined", "other_entry"])
def test_noncanonical_write_refuses_before_credentials(monkeypatch, writer, direct, variant):
    """Bug: omitting or regrouping flags bypasses native command approval and releases a PAT."""
    entry = [str(writer / "entry.py")] if direct else ["-m", "service_actions.supervisor"]
    flags = {
        "omitted": [],
        "reordered": ["-S", "-s", "-E"],
        "combined": ["-EsS"],
        "other_entry": list(PYTHON_FLAGS),
    }[variant]
    if variant == "other_entry":
        entry = ["entry.py"] if direct else ["-m", "service_actions.provider"]
    monkeypatch.setattr(sys, "orig_argv", [str(PYTHON), *flags, *entry])
    with pytest.raises(ValueError, match="^ARGUMENTS_NOT_SUPPORTED$"):
        supervisor.fetch([] if direct else None)


@pytest.mark.parametrize("direct", [False, True])
def test_canonical_write_keeps_direct_and_structured_sandbox_paths(monkeypatch, writer, direct):
    """Bug: the invocation guard also blocks the approved entry or local sandbox transport."""
    entry = [str(writer / "entry.py")] if direct else ["-m", "service_actions.supervisor"]
    monkeypatch.setattr(sys, "orig_argv", [str(PYTHON), *PYTHON_FLAGS, *entry])
    with pytest.raises(ValueError, match="^REACHED_CREDENTIAL_BOUNDARY$"):
        supervisor.fetch([] if direct else None)


def test_read_invocation_does_not_gain_the_write_guard(monkeypatch, writer):
    """Bug: a write-only hardening change silently alters existing read invocation behavior."""
    (writer / "config.json").write_text(json.dumps({"action": "jira-read"}))
    monkeypatch.setattr(sys, "orig_argv", [str(PYTHON), "entry.py"])
    with pytest.raises(ValueError, match="^REACHED_CREDENTIAL_BOUNDARY$"):
        supervisor.fetch([])


def test_interpreter_alias_cannot_escape_the_native_write_prefix(monkeypatch, writer):
    """Bug: a virtualenv or interpreter alias runs a write outside its fixed command gate."""
    monkeypatch.setattr(sys, "orig_argv", [str(PYTHON), *PYTHON_FLAGS, str(writer / "entry.py")])
    monkeypatch.setattr(sys, "executable", str(writer / "python"))
    with pytest.raises(ValueError, match="^ARGUMENTS_NOT_SUPPORTED$"):
        supervisor.fetch([])
