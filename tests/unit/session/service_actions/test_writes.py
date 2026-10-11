"""Writes touch only named targets, refuse stale ones and never lose the lines of writes made."""

import json

import pytest

from slopmeister.session.service_actions import (
    arguments,
    confluence_write,
    jira_write,
    provider,
    supervisor,
)
from slopmeister.session.service_actions.operations import Rejected, valid

OLD = "2026-09-01T10:00:00.225+0000"
NEW = "2026-09-01T10:00:05.000+0000"


class Client:
    """Answers GETs by path and records every write, so a test sees exactly what would be sent."""

    def __init__(self, gets: dict, fail_on: int | None = None):
        self.gets, self.sent, self.fail_on = gets, [], fail_on
        self.origin = "https://jira.example.invalid"

    def get(self, path, query=None):
        value = self.gets[path]
        if isinstance(value, Exception):
            raise value
        return value.pop(0) if isinstance(value, list) else value

    def send(self, method, path, body):
        self.sent.append((method, path, json.loads(body)))
        if self.fail_on == len(self.sent):
            raise ValueError("HTTP_500")
        return {"key": f"SBX-{len(self.sent) + 10}", "id": str(len(self.sent) + 10)}


def _issue(key, updated=OLD):
    return {"key": key, "fields": {"updated": updated}}


def _jira(**extra):
    gets = {"rest/api/2/myself": {"name": "writer"}}
    for key in ("SBX-1", "SBX-2", "SBX-3"):
        gets[f"rest/api/2/issue/{key}"] = _issue(key)
    return Client(gets | extra.pop("gets", {}), **extra)


@pytest.mark.parametrize(
    ("action", "args", "message"),
    [
        ("jira-write", ["--comment", "A-1,A-2,A-3,A-4", "--body", "x"], "--comment expects"),
        ("jira-write", ["--delete", "A-1"], "expected one of"),
        ("jira-write", ["--comment", "A-1,A-2", "--body", "x", "--if-updated", OLD], "one value"),
        ("jira-write", ["--comment", "A-1", "--body", "x"], "one value per target"),
        ("jira-write", ["--comment", "A-1", "--if-updated", OLD], "requires --body"),
        ("jira-write", ["--update", "A-1", "--fields", "[{}]", "--if-updated", OLD], "one JSON"),
        ("jira-write", ["--link", "A-1", "--type", "Blocks", "--to-issue", "A-1"], "--if-updated"),
        ("jira-write", ["--comment", "A-1", "--body", "a\x07b", "--if-updated", OLD], "--body"),
        ("jira-write", ["--create", "SBX"], "requires --fields"),
        ("jira-write", ["--create", "SBX", "--fields", "[{},{},{},{}]"], "--fields expects"),
        ("confluence-write", ["--create-page", "7", "--pages", '{"title":"t"}'], "exactly a"),
        ("confluence-write", ["--update-page", "7,8", "--body", "b", "--if-version", "1"], "one"),
    ],
)
def test_refusals_happen_at_parse_before_any_request(action, args, message):
    with pytest.raises(Rejected, match=message):
        arguments.parse(action, args)


def test_provider_revalidation_refuses_a_fourth_target_built_around_the_parser():
    operation = {"mode": "comment", "keys": ["A-1", "A-2", "A-3", "A-4"], "body": "x"}
    operation["if-updated"] = [OLD] * 4
    assert not valid(jira_write.TABLE, operation)


def test_invalid_write_sends_nothing(monkeypatch):
    monkeypatch.setattr(provider.transport, "send", pytest.fail)
    operation = {"mode": "comment", "keys": ["A-1"], "body": "x"}
    data = {"action": "jira-write", "operation": operation, "origin": "https://j.invalid"}
    with pytest.raises(ValueError, match="REQUEST_INVALID"):
        provider.read(data | {"expected_user": "writer"})


def test_one_changed_target_refuses_the_whole_command_before_any_write():
    client = _jira(gets={"rest/api/2/issue/SBX-3": _issue("SBX-3", NEW)})
    args = ["--comment", "SBX-1,SBX-2,SBX-3", "--body", "x", "--if-updated", f"{OLD},{OLD},{OLD}"]
    with pytest.raises(ValueError, match="CONTENT_CHANGED"):
        jira_write.write(client, "writer", arguments.parse("jira-write", args))
    assert client.sent == []


def test_guard_from_a_search_read_matches_at_whole_seconds_only():
    client = _jira()
    truncated = "2026-09-01T10:00:00.000+0000"
    args = ["--comment", "SBX-1", "--body", "x", "--if-updated", truncated]
    jira_write.write(client, "writer", arguments.parse("jira-write", args))
    assert len(client.sent) == 1
    later = ["--comment", "SBX-1", "--body", "x", "--if-updated", "2026-09-01T09:59:59.225+0000"]
    with pytest.raises(ValueError, match="CONTENT_CHANGED"):
        jira_write.write(_jira(), "writer", arguments.parse("jira-write", later))


def test_a_later_failure_keeps_the_lines_of_writes_already_made():
    client = _jira(fail_on=2)
    args = ["--comment", "SBX-1,SBX-2,SBX-3", "--body", "x", "--if-updated", f"{OLD},{OLD},{OLD}"]
    result = jira_write.write(client, "writer", arguments.parse("jira-write", args))
    assert result["result"] == "WRITE_INCOMPLETE"
    assert [line["target"] for line in result["written"]] == ["SBX-1"]
    assert result["failed"] == {"target": "SBX-2", "error": "HTTP_500"}
    assert len(client.sent) == 2


def test_a_write_whose_version_read_fails_keeps_its_line():
    client = _jira(gets={"rest/api/2/issue/SBX-11": ValueError("REQUEST_TIMEOUT")})
    args = ["--create", "SBX", "--fields", '{"summary":"s"}']
    result = jira_write.write(client, "writer", arguments.parse("jira-write", args))
    line = result["written"][0]
    assert (line["created"], line["version_unconfirmed"]) == ("SBX-11", "REQUEST_TIMEOUT")
    assert "updated" not in line and len(client.sent) == 1


def test_a_first_failure_is_an_ordinary_failure():
    args = ["--comment", "SBX-1", "--body", "x", "--if-updated", OLD]
    with pytest.raises(ValueError, match="HTTP_500"):
        jira_write.write(_jira(fail_on=1), "writer", arguments.parse("jira-write", args))


@pytest.mark.parametrize("names", [[], ["Done", "Done"]])
def test_transition_refuses_a_name_that_is_missing_or_ambiguous(names):
    found = {"transitions": [{"id": str(i), "name": name} for i, name in enumerate(names)]}
    client = _jira(gets={"rest/api/2/issue/SBX-1/transitions": found})
    args = ["--transition", "SBX-1", "--to", "Done", "--if-updated", OLD]
    with pytest.raises(ValueError, match="SELECTOR_UNAVAILABLE"):
        jira_write.write(client, "writer", arguments.parse("jira-write", args))
    assert client.sent == []


def test_create_forces_the_named_project_over_the_fields():
    client = _jira(gets={"rest/api/2/issue/SBX-11": _issue("SBX-11")})
    fields = '{"summary":"s","project":{"key":"OTHER"}}'
    result = jira_write.write(
        client, "writer", arguments.parse("jira-write", ["--create", "SBX", "--fields", fields])
    )
    assert client.sent[0][2]["fields"]["project"] == {"key": "SBX"}
    assert result["written"][0]["created"] == "SBX-11"


def test_link_guards_both_issues_and_names_the_first_as_the_blocker():
    client = _jira()
    args = [
        "--link",
        "SBX-1",
        "--type",
        "Blocks",
        "--to-issue",
        "SBX-2",
        "--if-updated",
        f"{OLD},{NEW}",
    ]
    with pytest.raises(ValueError, match="CONTENT_CHANGED"):
        jira_write.write(client, "writer", arguments.parse("jira-write", args))
    args[-1] = f"{OLD},{OLD}"
    jira_write.write(client, "writer", arguments.parse("jira-write", args))
    assert client.sent == [
        (
            "POST",
            "rest/api/2/issueLink",
            {
                "type": {"name": "Blocks"},
                "inwardIssue": {"key": "SBX-1"},
                "outwardIssue": {"key": "SBX-2"},
            },
        )
    ]


def _page(identity, number):
    version = {"number": number, "when": "2026-09-01T10:00:00Z", "by": {"username": "writer"}}
    return {
        "id": identity,
        "type": "page",
        "title": "T",
        "space": {"key": "SBX"},
        "version": version,
    }


class Pages(Client):
    def send(self, method, path, body):
        self.sent.append((method, path, json.loads(body)))
        return _page(path.rsplit("/", 1)[1], 3)


def test_page_update_sends_the_next_version_and_keeps_the_title():
    client = Pages(
        {
            "rest/api/user/current": {"username": "writer", "type": "known"},
            "rest/api/content/7": _page("7", 2),
        }
    )
    args = ["--update-page", "7", "--body", "<p>new</p>", "--if-version", "2"]
    result = confluence_write.write(client, "writer", arguments.parse("confluence-write", args))
    method, path, body = client.sent[0]
    assert (method, path, body["version"], body["title"]) == (
        "PUT",
        "rest/api/content/7",
        {"number": 3},
        "T",
    )
    assert result["written"][0]["version"] == 3
    with pytest.raises(ValueError, match="CONTENT_CHANGED"):
        confluence_write.write(
            client, "writer", arguments.parse("confluence-write", args[:-1] + ["1"])
        )


def test_provider_exits_zero_on_incomplete_so_its_lines_survive(monkeypatch, capsys):
    incomplete = {"result": "WRITE_INCOMPLETE", "written": [{"target": "SBX-1"}]}
    monkeypatch.setattr(provider.runtime, "require_interpreter", lambda: None)
    monkeypatch.setattr(provider, "read", lambda data: incomplete)
    monkeypatch.setattr(
        provider.sys,
        "stdin",
        type(
            "I",
            (),
            {"buffer": type("B", (), {"read": lambda self, n: b'{"action":"jira-write"}'})()},
        )(),
    )
    assert provider.main([]) == 0
    assert json.loads(capsys.readouterr().out) == incomplete


def test_supervisor_prints_incomplete_writes_and_fails(monkeypatch, capsys):
    incomplete = {"result": "WRITE_INCOMPLETE", "written": [{"target": "SBX-1"}]}
    monkeypatch.setattr(supervisor, "fetch", lambda: json.dumps(incomplete).encode())
    assert supervisor.main([]) == 1
    assert json.loads(capsys.readouterr().out) == incomplete
