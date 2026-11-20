"""A permission notice identifies a pending worker without disclosing the requested action."""

import io
import json
from types import SimpleNamespace

import pytest

from slopmeister.session import prompt_record


@pytest.mark.parametrize("same_session", [True, False])
def test_notice_leaves_the_decision_and_request_contents_in_the_native_client(
    monkeypatch, capsys, same_session
):
    monkeypatch.setenv(prompt_record.ROUTE_VARIABLE, "run_manager")
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", "term_worker")
    monkeypatch.setattr(prompt_record.launch_identity, "read", lambda _: {"session_id": "worker"})
    payload = {"session_id": "worker" if same_session else "other", "tool_input": "fixture-input"}
    stream = SimpleNamespace(buffer=io.BytesIO(json.dumps(payload).encode()))
    monkeypatch.setattr(prompt_record.sys, "stdin", stream)
    monkeypatch.setattr(prompt_record.os, "access", lambda *_: True)
    sent = []
    monkeypatch.setattr(prompt_record.subprocess, "run", lambda args, **_: sent.append(args))
    assert prompt_record.main(["notice"]) == 0
    assert capsys.readouterr() == ("", "")
    assert len(sent) == int(same_session)
    if same_session:
        assert sent[0][4:7] == ["term_worker", "--to", "run:run_manager"]
        assert "fixture-input" not in " ".join(sent[0])
