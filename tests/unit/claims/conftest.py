"""Shared in-process claim lifecycle fixtures."""

import pytest

from slopmeister.claims import evidence, github, lifecycle


def issue(labels=(), state="open", number=7):
    return {
        "number": number,
        "state": state,
        "title": "Work",
        "labels": [{"name": value} for value in labels],
    }


@pytest.fixture
def service(monkeypatch, tmp_path):
    remote = issue()
    writes = []

    def request(context, call):
        if call.method == "GET":
            if call.endpoint.startswith("labels"):
                return [{"name": "agent:claimed"}]
            return dict(remote)
        writes.append((call.method, call.endpoint, call.payload))
        if call.method == "POST":
            remote["labels"] = [{"name": "agent:claimed"}]
        elif call.method == "DELETE":
            remote["labels"] = []
        elif call.method == "PATCH":
            remote["state"] = call.payload["state"]
        return dict(remote)

    monkeypatch.setattr(github, "request", request)
    monkeypatch.setattr(evidence, "delivery_evidence", lambda record: None)
    monkeypatch.setattr(lifecycle, "other_owners", lambda context, number, workspace: [])
    path = tmp_path / "issue.json"
    saved = {"issue": 7, "workspace": str(tmp_path), "phase": "pending", "delivery": {}}
    evidence.save(path, saved)
    context = github.Repository(tmp_path, tmp_path, "owner/project", "remote", "slopmeister")
    return context, path, saved, remote, writes
