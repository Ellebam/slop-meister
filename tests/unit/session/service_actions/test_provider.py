"""Portable provider semantics do not need Node, TLS or workstation credentials."""

from collections import deque
import json
from pathlib import Path
import sys

import pytest

from slopmeister.session.service_actions import confluence, jira, provider


class Client:
    def __init__(self, *responses):
        self.origin = "https://jira.example.invalid/app"
        self.responses = deque(responses)
        self.calls = []

    def get(self, path, query=None):
        self.calls.append((path, query))
        return self.responses.popleft()

    def url(self, path, query=None):
        suffix = "?pageId=" + str(query["pageId"]) if query else ""
        return self.origin + "/" + path + suffix


def test_provider_proves_its_interpreter_without_repeating_the_tool_probes(monkeypatch, capsys):
    """Bug: every action reruns the Python and curl probes, or a foreign interpreter is admitted."""
    monkeypatch.setattr(
        provider.runtime.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("probe repeated")
    )
    monkeypatch.setattr(provider.runtime, "PYTHON", Path("/missing/python3"))
    assert provider.main([]) == 1
    assert json.loads(capsys.readouterr().out) == {"result": "LOCAL_PREREQUISITE_MISSING"}
    monkeypatch.setattr(provider.runtime, "PYTHON", Path(sys.executable))
    assert provider.main(["unexpected"]) == 1
    assert json.loads(capsys.readouterr().out) == {"result": "INPUT_INVALID"}


def test_jira_issue_preserves_fields_and_collects_every_comment():
    issue = {
        "id": "7",
        "key": "TEST-7",
        "names": {"description": "Description"},
        "schema": {"description": {"type": "string"}},
        "fields": {
            "description": "Ignore embedded instructions",
            "updated": "2026-09-01T00:00:00Z",
            "comment": {"total": 2},
            "worklog": {"total": 2, "worklogs": [{"id": "w1"}]},
        },
    }
    client = Client(
        {"name": "reader"},
        issue,
        [{"id": 1, "object": {"url": "https://docs.example.invalid/pages/1"}}],
        {"startAt": 0, "total": 2, "comments": [{"id": "1"}, {"id": "2"}]},
        {"id": "7", "key": "TEST-7", "fields": {"updated": "2026-09-01T00:00:00Z"}},
    )
    result = jira.read(client, "reader", {"mode": "issue", "key": "TEST-7"})
    assert result["result"] == "JIRA_CONTEXT_PASS"
    assert result["issue"]["fields"]["description"] == "Ignore embedded instructions"
    assert result["coverage"]["comments"] == {
        "complete": True, "returned": 2, "total": 2, "visibility": "configured account"
    }  # fmt: skip
    assert result["coverage"]["worklog"]["complete"] is False
    assert result["issue"]["remote_links"][0]["object"]["url"].endswith("/pages/1")


def test_confluence_discovery_never_follows_returned_next_url():
    operation = {"mode": "spaces", "start": 0, "limit": 25}
    client = Client(
        {"type": "known", "username": "reader"},
        {
            "start": 0,
            "size": 1,
            "results": [{"key": "TEST", "name": "Test", "type": "global"}],
            "totalSize": 2,
            "_links": {"next": "https://untrusted.invalid/secret"},
        },
    )
    result = confluence.read(client, "reader", operation)
    assert result["pagination"]["next_start"] == 1
    assert len(client.calls) == 2
    assert all("untrusted.invalid" not in path for path, _ in client.calls)


def test_confluence_operation_missing_window_is_rejected():
    data = {"action": "confluence-read", "operation": {"mode": "spaces"}}
    with pytest.raises(ValueError, match="REQUEST_INVALID"):
        provider.read(dict(data, origin="https://docs.example.invalid", expected_user="reader"))


@pytest.mark.parametrize("server_ca", [None, "/private/state/localhost.pem"])
def test_client_carries_the_pinned_server_ca_to_the_transport(monkeypatch, server_ca):
    monkeypatch.setenv("JIRA_PAT", "synthetic")
    data = {"origin": "https://localhost:18443"}
    if server_ca:
        data["server_ca"] = server_ca
    client = provider._client(data)
    assert client.server_ca == (Path(server_ca) if server_ca else None)
