"""A fixed backlog query cannot become a wider search or a write request."""

import copy
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from slopmeister.install.service_actions import validate_profile
from slopmeister.session.service_actions import arguments, provider
from tests.integration.install.helpers import consumer, profile

QUERY = 'project = "TEST" AND statusCategory != Done ORDER BY key ASC'


def _data(**changes):
    return dict(
        action="jira-read",
        origin="https://jira.example.invalid",
        expected_user="reader",
        backlog_jql=QUERY,
        operation={"mode": "backlog", "start": 0, "limit": 25},
        **changes,
    )


def test_backlog_selects_only_a_window_from_the_profile():
    """Bug: approved backlog reads cannot select the configured tracker query."""
    assert arguments.operation(profile() | {"backlog_jql": QUERY}, ["--backlog"]) == {
        "mode": "backlog",
        "start": 0,
        "limit": 25,
    }
    assert validate_profile(profile() | {"backlog_jql": QUERY}, "example", "jira-read")


@pytest.mark.parametrize(
    "query", ["", "project = TEST", "x\nORDER BY key ASC", "x\x85 ORDER BY key ASC", "x" * 2049]
)
def test_unordered_or_malformed_profile_queries_are_refused(query):
    """Bug: unstable ordering or controls make a fixed query unsafe to page."""
    with pytest.raises(ValueError):
        validate_profile(profile() | {"backlog_jql": query}, "example", "jira-read")


def test_query_is_not_admitted_for_another_action():
    """Bug: a Jira-only selector is silently enabled on another provider."""
    data = profile() | {"action": "confluence-read", "backlog_jql": QUERY}
    with pytest.raises(ValueError):
        validate_profile(data, "example", "confluence-read")


@pytest.mark.parametrize(
    "args",
    [
        ["--backlog", "--jql", "x"],
        ["--backlog", "--project", "OTHER"],
        ["--backlog", "--method", "POST"],
        ["--create", "TEST"],
        ["--backlog", "--limit", "101"],
    ],
)
def test_cli_overrides_and_writes_fail_before_credentials(tmp_path, monkeypatch, args):
    """Bug: a native-approved read can override its query or invoke a write."""
    module, data, _ = consumer(tmp_path, monkeypatch)
    (tmp_path / "config.json").write_text(json.dumps(data | {"backlog_jql": QUERY}))
    monkeypatch.delenv("SLOPMEISTER_SERVICE_ACTION_INPUT", raising=False)
    monkeypatch.setattr(module, "service_token", lambda *_: pytest.fail("credentials touched"))
    with pytest.raises(ValueError):
        module.fetch(args)


def test_missing_query_is_unknown_before_credentials(tmp_path, monkeypatch):
    """Bug: a legacy profile without a query becomes an empty or unbounded backlog."""
    module, _, _ = consumer(tmp_path, monkeypatch)
    monkeypatch.delenv("SLOPMEISTER_SERVICE_ACTION_INPUT", raising=False)
    monkeypatch.setattr(module, "service_token", lambda *_: pytest.fail("credentials touched"))
    with pytest.raises(ValueError, match="BACKLOG_NOT_CONFIGURED"):
        module.fetch(["--backlog"])


def _issue(relation="inward"):
    status = {"name": "Open", "statusCategory": {"id": 2, "key": "new"}}
    other = {
        "key": "TEST-9",
        "fields": {"summary": "Outside query", "status": copy.deepcopy(status)},
    }
    link = {
        "type": {"name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
        "inwardIssue": other,
    }
    if relation == "outward":
        link["outwardIssue"] = link.pop("inwardIssue")
    if relation == "done":
        link["inwardIssue"]["fields"]["status"]["statusCategory"] = {"id": 3, "key": "done"}
    if relation == "unreadable":
        del link["inwardIssue"]["fields"]["status"]
    if relation == "relates":
        link["type"] = {"name": "Relates", "inward": "relates to", "outward": "relates to"}

    return {
        "key": "TEST-1",
        "fields": {"summary": "Dependent", "status": status, "issuelinks": [link]},
    }


@pytest.mark.parametrize("relation", ["inward", "outward", "done", "unreadable", "relates"])
def test_backlog_keeps_direction_status_and_outside_query_blocker_with_get_only(
    monkeypatch, relation
):
    """Bug: candidate projection loses the blocker or its current status and direction."""
    issue, seen = _issue(relation), []

    def send(request):
        seen.append(request)
        if urlsplit(request.url).path.endswith("myself"):
            return {"name": "reader"}
        return {"startAt": 0, "maxResults": 25, "total": 1, "issues": [copy.deepcopy(issue)]}

    monkeypatch.setattr(provider.transport, "send", send)
    monkeypatch.setenv("JIRA_PAT", "synthetic")
    result = provider.read(_data())
    row = result["results"][0]
    assert row["issuelinks"] == issue["fields"]["issuelinks"]
    assert row["status_category"]["id"] == 2
    assert result["pagination"]["has_more"] is False
    query = parse_qs(urlsplit(seen[-1].url).query)
    assert query["jql"] == [QUERY] and "issuelinks" in query["fields"][0]
    assert all(request.method == "GET" and request.body is None for request in seen)


@pytest.mark.parametrize("links", [None, [], "absent"])
def test_missing_link_evidence_is_not_projected_as_empty(monkeypatch, links):
    """Bug: unavailable links are falsely reported as proving a ticket is available."""
    issue = _issue()
    if links == "absent":
        del issue["fields"]["issuelinks"]
    else:
        issue["fields"]["issuelinks"] = links
    responses = iter(
        [{"name": "reader"}, {"startAt": 0, "maxResults": 25, "total": 1, "issues": [issue]}]
    )
    monkeypatch.setattr(provider.transport, "send", lambda _: next(responses))
    monkeypatch.setenv("JIRA_PAT", "synthetic")
    row = provider.read(_data())["results"][0]
    assert row["issuelinks"] == (None if links == "absent" else links)


def test_provider_revalidates_backlog_before_http(monkeypatch):
    """Bug: an internal payload can smuggle a query override into the operation table."""
    data = _data()
    data["operation"]["jql"] = "project = OTHER"
    monkeypatch.setattr(provider.transport, "send", lambda _: pytest.fail("HTTP issued"))
    with pytest.raises(ValueError, match="REQUEST_INVALID"):
        provider.read(data)


@pytest.mark.parametrize(
    "query,code", [(None, "BACKLOG_NOT_CONFIGURED"), ("project = TEST", "BACKLOG_QUERY_INVALID")]
)
def test_provider_rejects_missing_or_bad_profile_query_before_http(monkeypatch, query, code):
    """Bug: query validation slips after the authenticated identity GET."""
    data = _data()
    data["backlog_jql"] = query
    monkeypatch.setattr(provider.transport, "send", lambda _: pytest.fail("HTTP issued"))
    with pytest.raises(ValueError, match=code):
        provider.read(data)


@pytest.mark.parametrize("code", ["HTTP_401", "HTTP_403", "REQUEST_TIMEOUT"])
def test_failed_backlog_read_is_not_empty_success_or_retried(monkeypatch, code):
    """Bug: a denied or failed search is converted to an available/empty backlog."""
    seen = []

    def send(request):
        seen.append(request)
        if len(seen) == 1:
            return {"name": "reader"}
        raise ValueError(code)

    monkeypatch.setattr(provider.transport, "send", send)
    monkeypatch.setenv("JIRA_PAT", "synthetic")
    with pytest.raises(ValueError, match=code):
        provider.read(_data())
    assert len(seen) == 2 and all(request.method == "GET" for request in seen)
