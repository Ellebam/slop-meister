"""One operation table decides what the helper, supervisor and provider accept."""

import pytest

from slopmeister.session.service_actions import arguments, jira, operations, provider

HOSTILE = [
    '" OR project = OTHER',
    "x ORDER BY key",
    "a\\",
    "--limit",
    "line\nbreak",
    "c1\x85",
    "../TEST-1",
    "https://other.invalid/TEST-1",
    "",
    " ",
]
# Free-text filters are escaped into literals, so only malformed text is refused for them.
FREE_TEXT = ("--text", "--summary", "--component", "--label")
CASES = [
    (option, value)
    for option in jira.FILTERS
    for value in HOSTILE
    if option not in FREE_TEXT or value in ("--limit", "line\nbreak", "c1\x85", "", " ")
]


@pytest.mark.parametrize("option,value", CASES)
def test_typed_jira_filters_refuse_hostile_values(option, value):
    with pytest.raises(operations.Rejected) as raised:
        arguments.parse("jira-read", ["--find", option, value])
    assert option in str(raised.value) and (not value.strip() or value not in raised.value.detail)


@pytest.mark.parametrize(
    "args",
    [
        ["--find", "--jql", "project = X"],
        ["--issue", "A/../B-1"],
        ["--issues", "A-1,myself/../B-2"],
        ["--find", "--text", "a", "--text", "b"],
        ["--issue", "TEST-1", "--related", "links,links"],
        ["--issue", "TEST-1", "--related", "comments"],
        ["--issues", ",".join(f"TEST-{n}" for n in range(1, 52))],
        ["--issues", "TEST-1,TEST-1"],
        ["--sprints", "0"],
        ["--sprints", "012"],
        ["--issue", "ТEST-1"],
        ["--find", "--limit", "101"],
        ["--find", "--order", "rank DESC"],
        ["--projects", "--project", "TEST"],
        ["--url", "https://jira.example.invalid/rest/api/2/search"],
        [],
    ],
)
def test_jira_forms_refuse_passthrough_and_unbounded_selectors(args):
    with pytest.raises(operations.Rejected):
        arguments.parse("jira-read", args)


def test_refusal_names_the_option_but_never_the_supplied_value():
    with pytest.raises(operations.Rejected) as raised:
        arguments.parse("jira-read", ["--find", "--sprint", "1 OR PRIVATE"])
    assert raised.value.detail == "--sprint expects a numeric sprint id or open"


@pytest.mark.parametrize(
    "args",
    [
        ["--find", "--text", 'x " OR y', "--status-category", "todo", "--assignee", "none"],
        ["--issue", "TEST-1", "--related"],
        ["--issue", "TEST-1", "--related", "children,parent"],
        ["--issues", "TEST-1,OTHER_2-3"],
        ["--boards", "--project", "TEST", "--name", "Team board"],
        ["--sprints", "12", "--state", "active", "--start", "25"],
    ],
)
def test_provider_accepts_exactly_what_the_supervisor_parsed(args):
    operation = arguments.parse("jira-read", args)
    assert operations.valid(jira.TABLE, operation)


@pytest.mark.parametrize(
    "operation",
    [
        {"mode": "find", "start": 0, "limit": 25, "order": "updated", "jql": "project = X"},
        {"mode": "find", "start": "0", "limit": 25, "order": "updated"},
        {"mode": "find", "start": 0, "limit": 25, "order": "updated", "text": "--limit"},
        {"mode": "issue", "key": "TEST-1/../../myself"},
        {"mode": "issues", "keys": ["TEST-1,TEST-2"]},
        {"mode": "sprints", "board": "1/../../2", "start": 0, "limit": 25},
        {"mode": "issue"},
        {"mode": "find", "start": True, "limit": 25, "order": "updated"},
        "find",
    ],
)
def test_provider_refuses_forged_operations_before_any_request(operation):
    data = dict(
        action="jira-read",
        operation=operation,
        origin="https://jira.example.invalid",
        expected_user="reader",
    )
    with pytest.raises(ValueError, match="REQUEST_INVALID"):
        provider.read(data)


def test_provider_refuses_a_page_url_that_skipped_supervisor_normalisation():
    operation = {
        "mode": "page",
        "id": "https://docs.example.invalid/pages/viewpage.action?pageId=1",
    }
    data = dict(
        action="confluence-read", operation=operation, origin="https://docs.example.invalid"
    )
    with pytest.raises(ValueError, match="REQUEST_INVALID"):
        provider.read(dict(data, expected_user="reader"))
