"""Related and batch reads return complete bodies or fail, never a partial neighbourhood."""

import time

import pytest

from slopmeister.session.service_actions import arguments, jira, jira_find, provider
from slopmeister.session.service_actions.constants import LIMIT

EPIC_FIELD = {"id": "customfield_10101", "schema": {"custom": jira_find.EPIC}}


class Client:
    origin = "https://jira.example.invalid"

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, path, query=None):
        self.calls.append((path, query))
        value = self.routes[path]
        return value(query) if callable(value) else value


def _body(key, **fields):
    comment = {"total": 1, "comments": [{"id": key + "-c"}]}
    fields = {"summary": key, "updated": "now", "comment": comment, **fields}
    return {"id": key.split("-")[1], "key": key, "fields": fields}


def _search(issues, total=None):
    def page(query):
        if query["fields"] == "parent":
            return {"startAt": 0, "maxResults": 51, "total": len(issues), "issues": issues}
        start = query["startAt"]
        found = issues[start : start + 100]
        count = len(issues) if total is None else total
        return {"startAt": start, "maxResults": 100, "total": count, "issues": found}

    return page


def _routes(root, related, children=()):
    routes = {
        "rest/api/2/myself": {"name": "reader"},
        "rest/api/2/field": [EPIC_FIELD],
        "rest/api/2/issue/ROOT-1": root,
        "rest/api/2/issue/ROOT-1/comment": {"startAt": 0, "total": 0, "comments": []},
        "rest/api/2/search": lambda query: (
            _search(list(children))(query)
            if query["fields"] == "parent"
            else _search(related)(query)
        ),
    }
    for issue in (root, *related):
        routes[f"rest/api/2/issue/{issue['key']}/remotelink"] = [{"id": 1}]
    return routes


def _root(**fields):
    root = _body("ROOT-1", **fields)
    root["fields"]["comment"] = {"total": 0, "comments": []}
    return root


def _read(routes, args):
    client = Client(routes)
    return jira.read(client, "reader", arguments.parse("jira-read", args)), client


def test_related_read_groups_links_parent_epic_and_children_with_bodies():
    links = [
        {"type": {"inward": "is blocked by", "outward": "blocks"}, "inwardIssue": {"key": "B-2"}},
        {"type": {"inward": "is blocked by", "outward": "blocks"}, "outwardIssue": {"key": "C-3"}},
    ]
    root = _root(issuelinks=links, parent={"key": "P-4"}, customfield_10101="E-5")
    related = [_body(key) for key in ("B-2", "C-3", "D-6", "E-5", "P-4")]
    routes = _routes(root, related, children=[{"key": "D-6"}])
    result, client = _read(routes, ["--issue", "ROOT-1", "--related"])
    by_key = {body["key"]: body for body in result["related"]["issues"]}
    assert by_key["B-2"]["relationships"] == ["inward: is blocked by"]
    assert by_key["C-3"]["relationships"] == ["outward: blocks"]
    assert by_key["E-5"]["relationships"] == ["epic"] and by_key["D-6"]["relationships"] == [
        "child"
    ]
    assert by_key["B-2"]["remote_links"] == [{"id": 1}] and "names" not in by_key["B-2"]
    assert result["coverage"]["related"]["relations_searched"] == [
        "links", "parent", "epic", "subtasks", "epic children"
    ]  # fmt: skip
    children_jql = next(q["jql"] for p, q in client.calls if q and q.get("fields") == "parent")
    assert children_jql == 'parent = "ROOT-1" OR cf[10101] = "ROOT-1" ORDER BY key ASC'
    assert not any(path.endswith("B-2/comment") for path, _ in client.calls)


def test_unreadable_neighbour_is_listed_not_silently_dropped():
    root = _root(issuelinks=[{"type": {"inward": "relates"}, "inwardIssue": {"key": "HID-9"}}])
    routes = _routes(root, [])
    result, _ = _read(routes, ["--issue", "ROOT-1", "--related", "links"])
    assert result["related"]["issues"] == [] and result["related"]["not_returned"] == ["HID-9"]


def test_incomplete_embedded_comments_are_paged_to_completion():
    partial = _body("B-2")
    partial["fields"]["comment"] = {"total": 2, "comments": [{"id": "1"}]}
    routes = _routes(_root(), [partial])
    routes["rest/api/2/issue/B-2/comment"] = {
        "startAt": 0, "total": 2, "comments": [{"id": "1"}, {"id": "2"}]
    }  # fmt: skip
    result, _ = _read(routes, ["--issues", "B-2"])
    body = result["issues"][0]
    assert body["fields"]["comment"]["total"] == 2 and body["coverage"]["comments"]["complete"]


def test_capped_child_page_fails_instead_of_dropping_children():
    children = [{"key": f"K-{n}"} for n in range(1, 51)]
    routes = _routes(_root(), [], children=children)
    page = {"startAt": 0, "maxResults": 50, "total": 51, "issues": children}
    routes["rest/api/2/search"] = lambda query: page
    with pytest.raises(ValueError, match="RELATED_LIMIT"):
        _read(routes, ["--issue", "ROOT-1", "--related", "children"])


def test_more_than_fifty_children_fails_with_related_limit():
    children = [{"key": f"K-{n}"} for n in range(1, 52)]
    routes = _routes(_root(), [], children=children)
    with pytest.raises(ValueError, match="RELATED_LIMIT"):
        _read(routes, ["--issue", "ROOT-1", "--related", "children"])


@pytest.mark.parametrize(
    "issues,total",
    [
        ([_body("X-9")], 1),
        ([_body("B-2"), _body("B-2")], 2),
        ([_body("B-2")], 3),
        ([], 1),
        ([_body("B-2"), _body("C-3")], 1),
        ([_body("B-2")], 2),
    ],
)
def test_batch_search_that_contradicts_the_requested_keys_fails(issues, total):
    routes = _routes(_root(), issues)
    routes["rest/api/2/search"] = _search(issues, total)
    with pytest.raises(ValueError, match="RESPONSE_INVALID"):
        _read(
            routes, ["--issues", "B-2,C-3"] if total < 3 or len(issues) > 1 else ["--issues", "B-2"]
        )


def test_oversized_related_result_fails_instead_of_clipping():
    related = [_body("B-2", description="x" * LIMIT)]
    root = _root(issuelinks=[{"type": {"inward": "relates"}, "inwardIssue": {"key": "B-2"}}])
    with pytest.raises(ValueError, match="ACTION_OUTPUT_LIMIT"):
        _read(_routes(root, related), ["--issue", "ROOT-1", "--related", "links"])


def test_request_budget_is_enforced_for_every_jira_read(monkeypatch):
    client = provider.Client("https://jira.example.invalid", "pat", time.monotonic() + 30)
    monkeypatch.setattr(provider.transport, "send", lambda request: {})
    for _ in range(100):
        client.get("rest/api/2/myself")
    with pytest.raises(ValueError, match="SEARCH_LIMIT"):
        client.get("rest/api/2/myself")
