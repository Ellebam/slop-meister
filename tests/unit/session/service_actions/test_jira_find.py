"""Jira discovery builds fixed JQL and reports its windows honestly."""

import pytest

from slopmeister.session.service_actions import arguments, jira, jira_find

FIELDS = [
    {"id": "customfield_10105", "name": "Sprint", "schema": {"custom": jira_find.SPRINT}},
    {"id": "customfield_10101", "name": "Lien d'epic", "schema": {"custom": jira_find.EPIC}},
    {"id": "customfield_10100", "name": "Rang", "schema": {"custom": jira_find.RANK}},
    {"id": "summary", "name": "Résumé", "schema": {"type": "string"}},
]


class Client:
    origin = "https://jira.example.invalid/app"

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, path, query=None):
        self.calls.append((path, query))
        value = self.routes[path]
        return value(query) if callable(value) else value


def _page(issues, start=0, total=None, size=25):
    total = len(issues) if total is None else total
    return {"startAt": start, "maxResults": size, "total": total, "issues": issues}


def _issue(number, **fields):
    return {"key": f"TEST-{number}", "fields": {"summary": f"Ticket {number}", **fields}}


def _find(args, routes=None, fields=FIELDS):
    routes = {"rest/api/2/myself": {"name": "reader"}, "rest/api/2/field": fields, **(routes or {})}
    routes.setdefault("rest/api/2/search", _page([_issue(1)]))
    client = Client(routes)
    result = jira.read(client, "reader", arguments.parse("jira-read", ["--find", *args]))
    return result, client


def _jql(client):
    return next(query["jql"] for path, query in client.calls if path == "rest/api/2/search")


@pytest.mark.parametrize(
    "args,expected",
    [
        (
            ["--text", 'a "b" \\ OR c:d', "--project", "TEST"],
            'text ~ "a \\\\\\"b\\\\\\" \\\\\\\\ OR c\\\\:d" AND project = "TEST"'
            " ORDER BY updated DESC, key DESC",
        ),
        (
            ["--component", 'Core" OR project = OTHER', "--label", "x"],
            'component = "Core\\" OR project = OTHER" AND labels = "x"'
            " ORDER BY updated DESC, key DESC",
        ),
        (
            ["--status-category", "todo", "--assignee", "none", "--order", "key"],
            "statusCategory = 2 AND assignee is EMPTY ORDER BY key ASC",
        ),
        (
            ["--assignee", "me", "--sprint", "open", "--epic", "TEST-9", "--order", "rank"],
            'assignee = currentUser() AND cf[10105] in openSprints() AND cf[10101] = "TEST-9"'
            " ORDER BY cf[10100] ASC",
        ),
        (
            ["--keys", "TEST-1,TEST-2", "--linked-to", "TEST-3", "--filter", "77"],
            'key in ("TEST-1", "TEST-2") AND issue in linkedIssues("TEST-3") AND filter = 77'
            " ORDER BY updated DESC, key DESC",
        ),
    ],
)
def test_filters_become_fixed_clauses_with_input_only_inside_literals(args, expected):
    _, client = _find(args)
    assert _jql(client) == expected


def test_board_filter_is_resolved_from_the_board_configuration():
    routes = {"rest/agile/1.0/board/5/configuration": {"filter": {"id": "4242"}}}
    _, client = _find(["--board", "5"], routes)
    assert _jql(client).startswith("filter = 4242 ")


@pytest.mark.parametrize(
    "args,fields,routes",
    [
        (["--epic", "TEST-1"], FIELDS[2:], {}),
        (["--sprint", "3"], FIELDS[1:], {}),
        (["--order", "rank"], [dict(FIELDS[2], id="customfield_1 OR 1=1")], {}),
        (["--order", "rank"], [FIELDS[2], dict(FIELDS[2], id="customfield_2")], {}),
        (["--board", "5"], FIELDS, {"rest/agile/1.0/board/5/configuration": {"filter": {}}}),
        (
            ["--board", "5"],
            FIELDS,
            {"rest/agile/1.0/board/5/configuration": {"filter": {"id": "1) OR (1=1"}}},
        ),
    ],
)
def test_unresolvable_explicit_selector_fails_instead_of_widening(args, fields, routes):
    client = Client({"rest/api/2/myself": {"name": "reader"}, "rest/api/2/field": fields, **routes})
    with pytest.raises(ValueError, match="SELECTOR_UNAVAILABLE"):
        jira.read(client, "reader", arguments.parse("jira-read", ["--find", *args]))
    assert all(path != "rest/api/2/search" for path, _ in client.calls)


def test_window_reports_next_start_total_and_candidate_metadata():
    issue = _issue(
        1,
        status={"name": "Ouvert"},
        assignee=None,
        labels=["team"],
        components=[{"name": "Core"}],
        parent={"key": "TEST-0"},
        customfield_10101="TEST-9",
        updated="2026-09-01",
    )
    routes = {"rest/api/2/search": _page([issue], start=0, total=3, size=1)}
    result, _ = _find(["--limit", "1"], routes)
    assert result["pagination"] == {
        "start": 0, "limit": 1, "returned": 1, "has_more": True, "next_start": 1, "total": 3
    }  # fmt: skip
    candidate = result["results"][0]
    assert candidate["epic"] == "TEST-9" and candidate["parent"] == "TEST-0"
    assert candidate["components"] == ["Core"] and candidate["assignee"] is None
    assert "absent ticket is not proven" in result["coverage"]["visibility"]


def test_empty_window_is_a_valid_result_not_proof_of_absence():
    result, _ = _find(["--text", "nothing"], {"rest/api/2/search": _page([])})
    assert result["results"] == [] and result["pagination"]["has_more"] is False


@pytest.mark.parametrize(
    "page",
    [
        _page([_issue(1)], total=0),
        _page([_issue(1)], start=5, total=10),
        _page([_issue(1)], total=5, size=25),
        _page([_issue(1), _issue(1)], total=2),
        _page([], total=4),
        {"startAt": 0, "total": 1, "issues": [_issue(1)]},
    ],
)
def test_inconsistent_search_windows_fail(page):
    with pytest.raises(ValueError, match="RESPONSE_INVALID"):
        _find([], {"rest/api/2/search": page})


def _agile(values, last, total=None, start=0):
    page = {"startAt": start, "maxResults": 25, "isLast": last, "values": values}
    return page if total is None else dict(page, total=total)


def test_board_and_sprint_listings_page_without_following_links():
    board = {"id": 5, "name": "Team", "type": "scrum", "location": {"projectKey": "TEST"}}
    sprint = {"id": 9, "name": "Sprint 9", "state": "active", "self": "https://other.invalid"}
    client = Client(
        {
            "rest/api/2/myself": {"name": "reader"},
            "rest/agile/1.0/board": _agile([board], False, total=2),
            "rest/agile/1.0/board/5/sprint": _agile([sprint], True),
        }
    )
    boards = jira.read(client, "reader", arguments.parse("jira-read", ["--boards"]))
    sprints = jira.read(client, "reader", arguments.parse("jira-read", ["--sprints", "5"]))
    assert boards["results"][0]["project"] == "TEST" and boards["pagination"]["next_start"] == 1
    assert boards["pagination"]["total"] is None
    assert sprints["results"][0]["state"] == "active" and "self" not in sprints["results"][0]


@pytest.mark.parametrize(
    "page",
    [
        _agile([], False),
        _agile([{"id": 1}, {"id": 1}], True),
        _agile([{"id": "1"}], True),
        _agile([{"id": 1}], "yes"),
    ],
)
def test_inconsistent_agile_windows_fail(page):
    client = Client({"rest/api/2/myself": {"name": "reader"}, "rest/agile/1.0/board": page})
    with pytest.raises(ValueError, match="RESPONSE_INVALID"):
        jira.read(client, "reader", arguments.parse("jira-read", ["--boards"]))


def test_project_listing_is_windowed_locally_with_a_known_total():
    projects = [{"key": f"P{n}", "name": f"Project {n}"} for n in range(30)]
    client = Client({"rest/api/2/myself": {"name": "reader"}, "rest/api/2/project": projects})
    args = ["--projects", "--start", "25", "--limit", "10"]
    result = jira.read(client, "reader", arguments.parse("jira-read", args))
    assert [item["key"] for item in result["results"]] == [f"P{n}" for n in range(25, 30)]
    assert result["pagination"]["total"] == 30 and result["pagination"]["has_more"] is False


def test_identity_mismatch_stops_before_any_search():
    client = Client({"rest/api/2/myself": {"name": "someone-else"}})
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
        jira.read(client, "reader", arguments.parse("jira-read", ["--find"]))
    assert len(client.calls) == 1


@pytest.mark.parametrize("status", ["HTTP_401", "HTTP_403"])
def test_denied_read_fails_without_retry_or_another_path(status):
    def denied(query):
        raise ValueError(status)

    routes = {"rest/api/2/myself": {"name": "reader"}, "rest/api/2/field": FIELDS}
    client = Client({**routes, "rest/api/2/search": denied})
    with pytest.raises(ValueError, match=status):
        jira.read(client, "reader", arguments.parse("jira-read", ["--find", "--project", "TEST"]))
    assert [path for path, _ in client.calls].count("rest/api/2/search") == 1
    assert len(client.calls) == 3
