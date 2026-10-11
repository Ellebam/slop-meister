"""Service-action provider launches from its delivered reader directory."""

import json
from pathlib import Path
import sys
import time

import pytest

from tests.integration.install.helpers import consumer

PASSING_PROVIDER = """print('{"result":"JIRA_CONTEXT_PASS"}')\n"""


def _launch(tmp_path, monkeypatch, op):
    """Start the provider through a stand-in op while the caller sits in another directory."""
    module, data, _ = consumer(tmp_path, monkeypatch)
    del data["password_ref"], data["certificate_document"]
    package = tmp_path / "reader/service_actions"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "provider.py").write_text(PASSING_PROVIDER)
    stub = tmp_path / "op"
    stub.write_text("#!/bin/sh\n" + op)
    stub.chmod(0o700)
    monkeypatch.setattr(module, "ROOT", package.parent)
    monkeypatch.setattr(module, "OP", stub)
    monkeypatch.setattr(module, "PYTHON", Path(sys.executable))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    execution = ({"PATH": module.BASE_PATH}, time.monotonic() + 30)
    return module._provider(data, {"mode": "issue", "key": "TEST-7"}, execution)


def test_provider_starts_from_an_unrelated_working_directory(tmp_path, monkeypatch):
    """Bug: the child inherits the caller's directory and Python cannot find the provider."""
    result = _launch(tmp_path, monkeypatch, 'shift 2\nexec "$@"\n')
    assert json.loads(result)["result"] == "JIRA_CONTEXT_PASS"


def test_unresolved_field_keeps_the_credential_code(tmp_path, monkeypatch):
    """Bug: the provider start check swallows a real 1Password field failure."""
    with pytest.raises(ValueError, match="^FIELD_OR_PROVIDER_ACCESS_FAILED$"):
        _launch(tmp_path, monkeypatch, "exit 1\n")


def test_provider_that_cannot_start_names_the_provider_module(tmp_path, monkeypatch, capsys):
    """Bug: a damaged delivery reaches the token and is reported as a credential failure."""
    module, _, _ = consumer(tmp_path, monkeypatch)
    seen = []

    def require(**kwargs):
        seen.append(kwargs)
        raise ValueError("LOCAL_PREREQUISITE_MISSING:provider module")

    monkeypatch.setattr(module.runtime, "require", require)
    monkeypatch.setattr(module, "service_token", lambda *_args: pytest.fail("token was read"))
    assert module.main([]) == 1
    assert seen == [dict(check_current=True, module_root=tmp_path, cert=True)]
    assert json.loads(capsys.readouterr().out) == dict(
        result="LOCAL_PREREQUISITE_MISSING", component="provider module", provider_contacted=False
    )
