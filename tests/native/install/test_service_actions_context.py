"""Jira and Confluence context reads preserve their bounded operation."""

from collections import deque
import json
import shutil
import subprocess
import sys

import pytest

from slopmeister.session.service_actions import confluence, jira, process, wire
from slopmeister.session.service_actions.constants import LIMIT
from tests.integration.install.helpers import ROOT, consumer


@pytest.mark.parametrize(
    "action,args,mode",
    [
        ("jira-read", ["--issue", "TEST-7"], "issue"),
        (
            "confluence-read",
            ["--search", "release notes", "--space", "TEST", "--start", "25"],
            "search",
        ),
        ("confluence-read", ["--title", "release"], "title"),
        *[("confluence-read", ["--" + mode, "🙂" * 1024], mode) for mode in ("search", "title")],
        ("confluence-read", ["--spaces"], "spaces"),
        ("confluence-read", ["--pages-in-space", "~reader"], "pages-in-space"),
        ("confluence-read", ["--children", "123", "--limit", "10"], "children"),
    ],
)
def test_context_selectors_reach_only_the_named_operation(
    tmp_path, monkeypatch, action, args, mode
):
    module, data, _ = consumer(tmp_path, monkeypatch)
    data["action"] = action
    monkeypatch.setenv("SLOPMEISTER_SERVICE_ACTION_INPUT", json.dumps(args))
    assert module.operation(data)["mode"] == mode


@pytest.mark.parametrize(
    "action,args",
    [
        *[
            ("jira-read", ["--issue", value])
            for value in (
                "",
                "../TEST-1",
                "https://example.invalid/TEST-1",
                "TEST-0",
                "test-1",
                "TEST-1;id",
                "TEST-1\n",
            )
        ],
        ("jira-read", ["--issue", "TEST-1", "--issue", "TEST-2"]),
        ("confluence-read", ["--pages-in-space", ".."]),
        ("confluence-read", ["--pages-in-space", "a/b"]),
        ("confluence-read", ["--search", "--spaces"]),
        ("confluence-read", ["--search", "term\x85text"]),
        *[("confluence-read", ["--" + mode, "🙂" * 1025]) for mode in ("search", "title")],
        ("confluence-read", ["--search", "x", "--limit", "0"]),
        ("confluence-read", ["--search", "x", "--start", "-1"]),
        ("confluence-read", ["--spaces", "--limit", "101"]),
        ("confluence-read", ["--spaces", "--limit", "1", "--limit", "2"]),
        ("confluence-read", ["--page", "1", "--start", "0"]),
    ],
)
def test_context_selector_rejection_precedes_credential_resolution(
    tmp_path, monkeypatch, action, args
):
    module, data, _ = consumer(tmp_path, monkeypatch)
    data["action"] = action
    (tmp_path / "config.json").write_text(json.dumps(data))
    monkeypatch.setenv("SLOPMEISTER_SERVICE_ACTION_INPUT", json.dumps(args))
    monkeypatch.setattr(module, "service_token", lambda *_args: pytest.fail("credentials touched"))
    with pytest.raises(ValueError, match="ARGUMENTS_NOT_SUPPORTED"):
        module.fetch()


class Client:
    def __init__(self, *responses):
        self.origin = "https://jira.example.invalid"
        self.responses = deque(responses)

    def get(self, _path, _query=None):
        return self.responses.popleft()

    def url(self, path, query=None):
        return self.origin + "/" + path + ("?pageId=" + query["pageId"] if query else "")


def _jira_context():
    issue = {
        "id": "7",
        "key": "TEST-7",
        "names": {"description": "Description"},
        "schema": {"description": {"type": "string"}},
        "fields": {"description": "Visible", "updated": "2026-09-15", "comment": {"total": 1}},
    }
    client = Client(
        {"name": "reader"},
        issue,
        [],
        {"startAt": 0, "total": 1, "comments": [{"id": "1", "body": "Visible"}]},
        {"id": "7", "key": "TEST-7", "fields": {"updated": "2026-09-15"}},
    )
    return jira.read(client, "reader", {"mode": "issue", "key": "TEST-7"})


def _confluence_context():
    page = {
        "id": "8",
        "type": "page",
        "status": "current",
        "title": "Visible",
        "space": {"key": "TEST"},
        "version": {"number": 1},
    }
    client = Client(
        {"type": "known", "username": "reader"},
        {"start": 0, "size": 1, "totalSize": 1, "results": [page], "_links": {}},
    )
    return confluence.read(
        client, "reader", {"mode": "search", "text": "Visible", "start": 0, "limit": 25}
    )


@pytest.mark.parametrize("pat_only", [False, True])
def test_jira_context_and_confluence_research_preserve_complete_visible_data(pat_only):
    jira_result = _jira_context()
    confluence_result = _confluence_context()
    assert jira_result["issue"]["fields"]["comment"]["comments"][0]["body"] == "Visible"
    assert confluence_result["results"][0]["title"] == "Visible"
    assert pat_only in (False, True)


def test_context_output_serializer_keeps_control_characters_and_checks_final_bytes():
    value = {"body": '\x00\x7f\x85\x9f\n\\"é🙂'}
    encoded = wire.encode(value)
    assert json.loads(encoded) == value
    assert all(not 127 <= ord(char) <= 159 for char in encoded.decode())
    with pytest.raises(ValueError, match="ACTION_OUTPUT_LIMIT"):
        wire.encode({"body": "\x85" * (LIMIT // 3)})


def _scenarios():
    return {
        ".codex": (
            "jira-read",
            {"mode": "issue", "key": "TEST-7"},
            [
                {"name": "reader"},
                {"id": "7", "key": "TEST-7", "fields": {"updated": "now", "comment": {"total": 0}}},
                [],
                {"startAt": 0, "total": 0, "comments": []},
                {"id": "7", "key": "TEST-7", "fields": {"updated": "now"}},
            ],
            "JIRA_CONTEXT_PASS",
        ),
        ".claude": (
            "confluence-read",
            {"mode": "spaces", "start": 0, "limit": 25},
            [
                {"type": "known", "username": "reader"},
                {"start": 0, "size": 0, "totalSize": 0, "results": [], "_links": {}},
            ],
            "CONFLUENCE_FETCH_PASS",
        ),
    }


def _run_delivered(tmp_path, tool: str, scenario):
    action, operation, responses, expected = scenario
    action_root = tmp_path / tool / "service-actions/example"
    shutil.copytree(ROOT / "slopmeister/session/service_actions", action_root / "service_actions")
    script = (
        "from service_actions import provider\n"
        + f"responses={responses!r}\n"
        + "provider.runtime.require_interpreter=lambda: None\n"
        + "provider.transport.send=lambda request: responses.pop(0)\n"
        + "raise SystemExit(provider.main([]))\n"
    )
    payload = dict(
        origin="https://jira.example.invalid",
        expected_user="reader",
        action=action,
        operation=operation,
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=action_root,
        env={"PATH": "/usr/bin:/bin", "JIRA_PAT": "disposable"},
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout)["result"] == expected


def test_context_driver_reads_printed_chunks_through_both_delivered_chains(tmp_path):
    for tool, scenario in _scenarios().items():
        _run_delivered(tmp_path, tool, scenario)


def test_context_deadline_includes_credential_setup_instead_of_resetting_it(tmp_path, monkeypatch):
    module, data, _ = consumer(tmp_path, monkeypatch)
    data["action"] = "jira-read"
    del data["password_ref"], data["certificate_document"]
    (tmp_path / "config.json").write_text(json.dumps(data))
    monkeypatch.setenv("SLOPMEISTER_SERVICE_ACTION_INPUT", '["--issue","TEST-7"]')
    now = [1000.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])

    def invoke(run):
        assert run.deadline == 1300.0
        if run.argv[1] == "user":
            now[0] += 100
            identity = dict(id=data["account_id"], type="SERVICE_ACCOUNT", state="ACTIVE")
            return json.dumps(identity).encode()
        if run.argv[1] == "vault":
            now[0] += 100
            return json.dumps([dict(id=data["vault_id"], name=data["vault_name"])]).encode()
        assert json.loads(run.payload)["remaining_ms"] == 99000
        return b'{"result":"JIRA_CONTEXT_PASS"}'

    monkeypatch.setattr(module, "invoke", invoke)
    assert json.loads(module.fetch())["result"] == "JIRA_CONTEXT_PASS"


def test_expired_deadline_refuses_before_starting_another_child(monkeypatch):
    monkeypatch.setattr(
        process.subprocess, "Popen", lambda *_a, **_k: pytest.fail("child launched")
    )
    with pytest.raises(ValueError, match="ACTION_TIMEOUT"):
        process.invoke(process.Run(["unused"], {}, deadline=process.time.monotonic() - 1))
